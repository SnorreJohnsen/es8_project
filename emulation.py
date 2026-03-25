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
from network import mtu
from shared import eprint, globalTerminalGroup, get_remote_mapping, Remote, stop_all_terminals, get_thread_id, exec

# List of processes for termination end of script
tcpdump_procs = []
iperf3_servers = []

# Directory paths for outputs
output_root = "emulation_output"
iperf3_dir = os.path.join(output_root, "iperf3", "raw")
pcap_dir = os.path.join(output_root, "pcaps", "raw")
node_addrs_json_path = os.path.join(output_root, "node_addrs.json")

# Global variables
IPERF3_REF_PORT = 60000 # start port for iperf3

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

def ipv4_addr(device_name: str):
    """
    Create ipv4 address based on device name of form: 10.200.100.10 for d0
    Return: ipv4 address, subnet bits
    """
    assert device_name.startswith("d"), "expects somewhat valid-looking device name (for example d0)"

    lsb = int(device_name.strip("d"))+10
    
    assert lsb < 255, "too many devices. increase size of lab subnet"

    device_ip_addr = f"10.200.100.{lsb}"

    # (ip, subnet bits)
    return device_ip_addr, 24

def stop_all_iperf3_servers():
    sigint_all(iperf3_servers)

def run_iperf3_server(server_name: str):
    """
    Setup an iperf3 server from a device name.
    Server port is specified from IPERF3_REF_PORT and the device number.
    """
    server_num = int(server_name.strip("d"))
    server_port = IPERF3_REF_PORT + server_num

    server_cmd = ["ip", "netns", "exec", f"ns-{server_name}", 
                  "iperf3", "-s", "-p", str(server_port)]
    server_proc = subprocess.Popen(server_cmd,
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)

    iperf3_servers.append(server_proc)

    if verbosity == "verbose":
        print(f"run_iperf3_server({server_name=})")
        print(" ".join(server_cmd))

def run_iperf3_client(server_name: str,
                      client_name: str,
                      out_dir: str, 
                      duration: float = 5, 
                      udp: bool = False, 
                      bitrate: str = ''):
    """
    Setup iperf3 client to connect to a iperf3 server. 
    Output client stdout to json file of naming convention {server_name}_{client_name}.json

    duration: time for test [s] (default=5s)
    udp: flag for choosing UDP test (default TCP)
    bitrate: max bitrate stream try to achieve (default=none)
    """
    # extract ip and port from server device
    server_num = int(server_name.strip("d"))
    server_port = IPERF3_REF_PORT + server_num
    server_ip = f"10.200.100.{server_num+10}"

    client_cmd = ["ip", "netns", "exec", f"ns-{client_name}",
                  "iperf3", "-c", server_ip, "-p", str(server_port), "-t", str(duration), "--json"]

    # UDP option
    if udp:
        client_cmd += ["-u"]
        if bitrate != '':
            client_cmd += ["-b", bitrate]

    # bitrate option if UDP was not chosen this is used for TCP
    elif bitrate != '':
        client_cmd += ["--bitrate", bitrate]

    client_proc = subprocess.run(client_cmd,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    text=True,
                                    start_new_session=True,
                                    close_fds=True)

    iperf3_path = os.path.join(out_dir, f"{server_name}_{client_name}.json")
    with open(iperf3_path, "w") as f:
        f.write(client_proc.stdout)

    if verbosity == "verbose":
        print(f"run_iperf3_client({server_name=}, {client_name=}, {out_dir=})")
        print(" ".join(client_cmd))

def find_closest_node(this: dict, others: list[dict]):
    """
    Finds closest node in a list of nodes.
    """
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

def create_device(name: str, adapter_name: str, create_timeout: float = 10):
    """
    Creates device(d) and corresponding namespace with static ipv4 address and connects it to the adapter(a) namespace.
    Assumes that a{j} is already set up for batman (bat0 exists and is connected to a hard interface)
    
    Anatomy: namespace:interface 
    d{j}:veth0 -> a{j}:lan0 -> a{j}:br-lan -> a{j}:bat0
    """
    nsname = f"ns-{name}"
    nsname_adapter = f"ns-{adapter_name}"
    tid = get_thread_id()
    remote = None
    upname = "veth0"
    downname = "lan0"
    brname = "br-lan"

    exec(tid, remote, f'ip netns add "{nsname}"')
    exec(tid, remote, f'ip netns exec "{nsname}" ip link set dev "lo" up')

    # create interface pair in device namespace
    exec(tid, remote, f'ip netns exec "{nsname}" ip link add name "{upname}" type veth peer name "{downname}"')

    # move downlink from device namespace to adapter namespace
    exec(tid, remote, f'ip netns exec "{nsname}" ip link set "{downname}" netns "{nsname_adapter}"')

    # create bridge in adapter namespace
    exec(tid, remote, f'ip netns exec "{nsname_adapter}" ip link add name "{brname}" type bridge')
    exec(tid, remote, f'ip netns exec "{nsname_adapter}" ip link set dev "{brname}" up mtu {mtu}')

    # disable spanning tree protocol (should be off by default anyway)
    exec(tid, remote, f'ip netns exec "{nsname_adapter}" ip link set "{brname}" type bridge stp_state 0')

    # make the bridge to act as a hub
    exec(tid, remote, f'ip netns exec "{nsname_adapter}" ip link set "{brname}" type bridge ageing_time 0')
    exec(tid, remote, f'ip netns exec "{nsname_adapter}" ip link set "{brname}" type bridge forward_delay 0')

    # put ifaces into bridge
    exec(tid, remote, f'ip netns exec "{nsname_adapter}" ip link set "{downname}" master "{brname}"')
    exec(tid, remote, f'ip netns exec "{nsname_adapter}" ip link set "bat0" master "{brname}"')

    device_ip_addr, subnet_bits = ipv4_addr(name)
    # bring ifaces up
    exec(tid, remote, f'ip netns exec "{nsname}" ip addr add "{device_ip_addr}/{subnet_bits}" dev "{upname}"')
    exec(tid, remote, f'ip netns exec "{nsname}" ip link set dev "{upname}" up mtu {mtu}')
    exec(tid, remote, f'ip netns exec "{nsname_adapter}" ip link set dev "{downname}" up mtu {mtu}') 

def place_test_adapters(graph: dict, dev_coords: list[tuple[float, float, float]]):
    """
    Place adapter at device coordiantes to connect a device to drone(node). 
    Adapter is connected to the closest drone(node).    
    """
    devs = []
    for i, (x, y, z) in enumerate(dev_coords):
        dev = {
            "id": f"a{i}",
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

def batctl_set_neigh_throughputs(graph: dict):
    """
    set throughput limit in both direction to a neighbour node.
    """
    tid = get_thread_id()
    remote = None

    for link in graph["links"]:
        source = link["source"]
        target = link["target"]
        bw = float(link["bandwidth_mbit"])

        # get source and target MAC address
        bat_mac_cmd = "ip -o -brief link show uplink | awk '{print $3}'"
        source_mac = exec(tid, remote, f'ip netns exec "ns-{source}" {bat_mac_cmd}', get_output=True)[0].strip() # [0] to only get stdout
        target_mac = exec(tid, remote, f'ip netns exec "ns-{target}" {bat_mac_cmd}', get_output=True)[0].strip()

        # set throughput limit in both directions (*10 is to go from unit Mbit to 100kbit)
        exec(tid, remote, f'ip netns exec "ns-{source}" battpctl set bat0 uplink {target_mac} {int(bw*10)}')
        exec(tid, remote, f'ip netns exec "ns-{target}" battpctl set bat0 uplink {source_mac} {int(bw*10)}')

def get_node_addrs(node_id: str, cmd: str):
    tid = get_thread_id()
    remote = None

    raw = exec(tid, remote, f'ip netns exec "ns-{node_id}" {cmd}', get_output=True)[0]
    if raw:
        pairs = map(lambda x: x.split(" "), raw.splitlines())
        return {k:v for k, v in filter(lambda x: len(x) == 2, pairs)}
    else:
        return {}

def get_all_addrs(graph: dict, extra_ids: list[str]):
    """
    Get all mac, ipv4, ipv6 for a node and output in a json file.
    """
    addrs_json = {}

    get_macs_cmd = "ip -o -brief link show | awk '{print $1, $3}'"
    get_ipv6_cmd = "ip -6 -brief a | awk '{print $1, $3}'"
    get_ipv4_cmd = "ip -4 -brief a | awk '{print $1, $3}'"
    ids = [n["id"] for n in graph["nodes"]]
    for node_id in ids+extra_ids:
        addrs_json[node_id] = {
            "ipv4": get_node_addrs(node_id, get_ipv4_cmd),
            "ipv6": get_node_addrs(node_id, get_ipv6_cmd),
            "mac": get_node_addrs(node_id, get_macs_cmd) 
            }
    with open(node_addrs_json_path, "w") as f:
        json.dump(addrs_json, f)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("graph", help="Graph of the full network mesh (json)")
    parser.add_argument('-v', '--verbosity', choices=['verbose', 'normal', 'quiet'], default='normal', help='Set verbosity.')
    args = parser.parse_args()

    global verbosity
    verbosity = args.verbosity
    globalTerminalGroup.setVerbosity(args.verbosity)

    # Setup output directories
    try:
        shutil.rmtree(pcap_dir)
        shutil.rmtree(iperf3_dir)
    except FileNotFoundError as e:
        pass

    os.makedirs(exist_ok=False, name=pcap_dir)
    os.makedirs(exist_ok=False, name=iperf3_dir)

    # Load mesh json
    if not os.path.isfile(args.graph):
        eprint(f'File not found: {args.graph}')
        exit(1)
    with open(args.graph) as f:
        graph = json.load(f)

    if verbosity == "verbose":
        print("graph")
        pprint(graph)

    # Place device adapters
    adapter_pos = [(0.0, 0.0, 0.0), 
                   (3000.0, 3000.0, 3000.0),
                   (1000.0, 10000.0, 10000.0), 
                   (12000.0, 5000.0, 1500.0), 
                   (25000.0, 9000.0, 3000.0)]
    place_test_adapters(graph, adapter_pos)

    # Create network name spaces with links from json graph
    link_command = "tc qdisc add dev {ifname} root netem rate {bandwidth_mbit}mbit"
    mn_network.apply(graph, link_command=link_command)

    # Init batman-adv on all nodes and adapters
    rmap = get_remote_mapping([Remote()]) # running everything locally
    all_ids = rmap.keys()
    drone_ids = list(filter(lambda x: x.startswith("n"), all_ids))
    adapter_ids = list(filter(lambda x: x.startswith("a"), all_ids))

    if verbosity != "quiet":
        print(f"Running simulation on {len(drone_ids)} drones and {len(adapter_ids)} devices")

    mn_software._start_protocol("batman-adv", rmap, drone_ids)
    mn_software._start_protocol("batman-adv", rmap, adapter_ids)

    device_ids = []
    for adapter_id in adapter_ids:
        device_id = adapter_id.replace("a", "d")
        device_ids.append(device_id)
        create_device(device_id, adapter_id)

    # Make json files for IP addrs and MAC addrs overview
    get_all_addrs(graph, device_ids)

    if verbosity != "quiet":
        print("Wait for batman-adv to be ready")
    time.sleep(2) # wait for batman to be ready (30s)

    # Apply throughput override
    # batctl_set_neigh_throughputs(graph)
    # if verbosity != "quiet":
    #     print("Wait for throughput override")
    # time.sleep(10) # wait for moving average in throughput override

    # Add devices and start tcpdump
    for device_id in device_ids:
        start_tcpdump(device_id, "veth0", pcap_dir)

    # Start tcpdump for each node
    for id in all_ids:
        start_tcpdump(id, "uplink", pcap_dir)

    time.sleep(2)  # allow to launch tcpdumps

    # start iperf3 test
    run_iperf3_server(server_name="d0")

    time.sleep(5) # wait for iperf3 servers to start
    run_iperf3_client(server_name="d0", client_name="d1", out_dir=iperf3_dir, duration=5, udp=False)
    time.sleep(10)
    run_iperf3_client(server_name="d0", client_name="d4", out_dir=iperf3_dir, duration=5, udp=False)



    input("Press Enter to end emulation")

    stop_all_iperf3_servers()
    stop_all_tcpdump()
    stop_all_terminals()

if __name__ == "__main__":
    main()
