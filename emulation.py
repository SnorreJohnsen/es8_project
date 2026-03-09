import os
import sys
import argparse
import json
import subprocess
import signal
import time
import shutil
import math
from pprint import pprint

from mesh_design_lib import data_rate_given_dist_comm

sys.path.append('meshnet-lab/')
import software as mn_software
import network as mn_network
from shared import eprint, globalTerminalGroup, get_remote_mapping, Remote, stop_all_terminals

# Create list of tcpdump processes
tcpdump_procs = []

pcap_dir = os.path.join("pcaps", "raw")


def sigint_all(procs: list[subprocess.Popen], timeout: float = 5.0) -> None:
    """
    Terminate multiple subprocess.

    Sends SIGINT to each running subprocess, waits up to `timeout`
    seconds for termination, then escalates to SIGTERM and finally
    SIGKILL if necessary.

    Parameters
    ----------
    procs : List of subprocess objects to terminate.
    timeout : Seconds to wait between escalation steps (default: 5.0).
    """
    # 1) Ask nicely: SIGINT to each process group
    for p in procs:
        if p.poll() is None:  # still running
            try:
                p.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass

    # 2) Reap / wait
    for p in procs:
        if p.poll() is None:
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass

    # 3) Escalate if anything is still alive
    for p in procs:
        if p.poll() is None:
            try:
                p.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass

    for p in procs:
        if p.poll() is None:
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # last resort
                try:
                    p.send_signal(signal.SIGKILL)
                except ProcessLookupError:
                    pass

def stop_all_tcpdump():
    sigint_all(tcpdump_procs)


def start_tcpdump(node_name: str, ifname: str, out_dir: str):
    """
    Starts a tcpdump on a node to capture traffic

    Parameters
    ----------
    node_name :
        Name of node in network graph.
    out_dir :
        Output directory for pcap files
    """

    pcap_path = os.path.join(out_dir, f"{node_name}.pcap")
    cmd = ["ip", "netns", "exec", f"ns-{node_name}",
            "tcpdump", "-i", ifname, "-n", "-U", "-w", pcap_path]

    if verbosity == "verbose":
        print(f"start_tcpdump({node_name=}, {out_dir=})")
        print(" ".join(cmd))

    proc = subprocess.Popen(cmd,
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,
                       start_new_session=True,
                       close_fds=True)

    tcpdump_procs.append(proc)

def find_closest_node(this: dict, others: list[dict]):

    min_dist_sq = None
    closest = None
    for other in others:
        dx = other["x"] - this["x"]
        dy = other["y"] - this["y"]
        dz = other["z"] - this["z"]
        dist_sq = dx**2 + dy**2 + dz**2

        if min_dist_sq is None:
            min_dist_sq = dist_sq
            closest = other
        else:
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                closest = other

    if closest is None or min_dist_sq is None:
        raise ValueError("Malformed graph (nodes cannot be empty)")

    return closest, min_dist_sq

def place_test_devices(graph: dict, dev_coords: list[tuple[float, float, float]]):
    devs = []
    for i, (x, y, z) in enumerate(dev_coords):
        dev = {
            "id": f"d{i}",
            "x": round(x, 2),
            "y": round(y, 2),
            "z": round(z, 2),
        }
        devs.append(dev)
        closest_drone, dist_sq = find_closest_node(dev, graph["nodes"])
        link = {
            "source": dev["id"],
            "target": closest_drone["id"],
            "bandwidth_mbit": round(data_rate_given_dist_comm(math.sqrt(dist_sq)), 2),
        }

        graph["links"].append(link)

    graph["nodes"].extend(devs)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("graph", help="Graph of the full network mesh (json)")
    parser.add_argument('-v', '--verbosity', choices=['verbose', 'normal', 'quiet'], default='normal', help='Set verbosity.')
    args = parser.parse_args()

    global verbosity
    verbosity = args.verbosity
    globalTerminalGroup.setVerbosity(args.verbosity)

    # Delelte pcap directory
    try:
        shutil.rmtree(pcap_dir)
    except FileNotFoundError as e:
        pass

    # make directory for pcap files for all nodes
    os.makedirs(exist_ok=False, name=pcap_dir)

    if not os.path.isfile(args.graph):
        eprint(f'File not found: {args.graph}')
        exit(1)
    with open(args.graph) as f:
        graph = json.load(f)

    place_test_devices(graph, [(0, 0, 0), (25000, 9000, 3000)])
    if verbosity == "verbose":
        print("graph")
        pprint(graph)

    # Create network name spaces with links from json graph
    link_command = "tc qdisc add dev {ifname} root netem rate {bandwidth_mbit}mbit"
    mn_network.apply(graph, link_command=link_command)

    # Init batman-adv on all nodes
    rmap = get_remote_mapping([Remote()]) # running everything locally
    all_ids = rmap.keys()
    drone_ids = list(filter(lambda x: x.startswith("n"), all_ids))
    device_ids = list(filter(lambda x: x.startswith("d"), all_ids))

    if verbosity != "quiet":
        print(f"Running simulation on {len(drone_ids)} drones and {len(device_ids)} devices")

    mn_software._start_protocol("batman-adv", rmap, drone_ids)

    # Start tcpdump for each node
    for id in drone_ids:
        start_tcpdump(id, "bat0", pcap_dir)

    for id in device_ids:
        start_tcpdump(id, "uplink", pcap_dir)

    time.sleep(2)  # allow to launch tcpdumps

    stop_all_tcpdump()
    stop_all_terminals()

if __name__ == "__main__":
    main()
