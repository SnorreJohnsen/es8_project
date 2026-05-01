from dataclasses import dataclass, asdict
from functools import total_ordering
import os
import sys
import argparse
import json
import subprocess
import signal
import time
import shutil
import math
import re
import errno
import random
from datetime import datetime, timedelta
from pprint import pprint
from copy import copy
from pydantic import BaseModel
from pydantic_core import from_json, to_json

from mesh_design_lib import data_rate_given_dist_comm
from drop_model import DropoutEvent, DropoutParams, MultipleDroneSim, State

sim_root = "/home/aau/meshsim/"
repo_root = os.path.join(sim_root, "repo")

sys.path.append(os.path.join(repo_root, 'meshnet-lab/'))
import network as mn_network
from network import mtu
from shared import eprint, globalTerminalGroup, get_remote_mapping, Remote, stop_all_terminals, get_thread_id, exec

## Check for dependencies
ok = True
# check if programs used are available
dependencies = ["iperf3", "batctl", "battpctl"]
for dep in dependencies:
    if shutil.which(dep) is None:
        print(f"ERROR: {dep} is not installed or not in PATH.")
        ok = False

# check if superuser
if os.geteuid() != 0:
    print("ERROR: user is not super user")
    ok = False

# check if batman_adv patched version is loaded
def batadv_patch_loaded() -> bool:
    """
    checks if the correct batman patched module is loaded before procceding as this is required for correct simulation
    """
    # Check if batman_adv loaded
    loaded = False
    result = subprocess.run("lsmod", stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for line in result.stdout.splitlines():
        modname = line.split(b" ")[0]
        if modname == b"batman_adv":
            loaded = True
            break
    if not loaded:
        print("ERROR: batman_adv is not loaded")
        return False
    
    # Check if batman_adv is patched version
    patched = False
    result = subprocess.run(["dmesg", "-fkern", "-Lnever", "-linfo"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    batadv_loaded_regex = br"B\.A\.T\.M\.A\.N\. advanced .* loaded$"
    matches = [line for line in result.stdout.splitlines() if re.search(batadv_loaded_regex, line)]
    if len(matches) > 0:
        batadv_patched_regex = br"^\[.*\] batman_adv: B\.A\.T\.M\.A\.N\. advanced \d{4}\.\d patched \(compatibility version \d+\) loaded$"
        patched = bool(re.fullmatch(batadv_patched_regex, matches[-1]))

    # if batman patched not in dmesg check in modinfo
    if not patched:
        try:
            result = subprocess.run(
                ["modinfo", "-F", "description", "batman_adv"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True
            )

            description = result.stdout.strip()

            if "B.A.T.M.A.N. advanced patched" in description:
                patched = True

        except subprocess.CalledProcessError:
            patched = False

    if not patched:
        print("ERROR: batman_adv is not patched version")
        return False

    return loaded and patched

if not batadv_patch_loaded():
    print("ERROR: batman_adv patched version is not loaded. User is responsible for loading patched version of batman_adv.")
    ok = False

if not ok:
    sys.exit(-errno.EINVAL)

# List of processes for termination end of script
tcpdump_procs = []
iperf3_servers = []
nsperf_servers = []

# Directory paths for outputs
output_root = os.path.join(sim_root, "output", "emulation")
iperf3_dir = os.path.join(output_root, "iperf3", "raw")
nsperf_dir = os.path.join(output_root, "nsperf", "raw")
pcap_dir = os.path.join(output_root, "pcaps", "raw")
node_addrs_json_path = os.path.join(output_root, "node_addrs.json")
graph_json_path = os.path.join(output_root, "graph.json")
sim_sched_json_path = os.path.join(output_root, "sim_sched.json")

# Global variables
IPERF3_REF_PORT = 60000 # start port for iperf3
NSPERF_PORT = 50000

# Simulation schedule types
class IperfEvent(BaseModel):
    iperf_header: str
    client_name: str
    server_name: str
    bitrate: str # 4M or 3K for example
    udp: bool
    duration: int

class NsperfEvent(BaseModel):
    nsperf_header: str
    client_name: str
    server_name: str
    bitrate: str # 4M or 3K for example
    duration: str # 5s

SchedEvent = DropoutEvent | IperfEvent | NsperfEvent

@total_ordering
class SchedEntry(BaseModel):
    time: float
    event: SchedEvent

    def __le__(self, other):
        return self.time <= other.time

class Sim(BaseModel):
    start_timestamp: float
    duration: float
    sched_plan: list[SchedEntry]
    sched_real: list[SchedEntry]

# subprocess handling
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


def start_tcpdump(node_name: str, ifname: str, ns_name: str, out_dir: str):
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
    cmd = ["ip", "netns", "exec", ns_name,
            "tcpdump", "-i", ifname, "-n", "-U", "-w", pcap_path]

    if verbosity == "verbose":
        print(f"start_tcpdump({node_name=}, {ifname=}, {ns_name=}, {out_dir=})")
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

def run_iperf3_server(server_name: str, client_name: str):
    """
    Setup an iperf3 server from a client name.
    Server port is specified from IPERF3_REF_PORT and the device number.
    """
    client_num = int(client_name.strip("d"))
    server_port = IPERF3_REF_PORT + client_num

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
                      timestamp: float,
                      duration: int = 5, 
                      udp: bool = False, 
                      bitrate: str = ''):
    """
    Setup iperf3 client to connect to a iperf3 server. 
    Output client stdout to json file of naming convention {server_name}_{client_name}.json

    duration: time for test [s] (default=5s)
    udp: flag for choosing UDP test (default TCP)
    bitrate: max bitrate stream try to achieve (default=none)
    """
    # extract ip and port from client device
    client_num = int(client_name.strip("d"))
    server_port = IPERF3_REF_PORT + client_num

    server_num = int(server_name.strip("d"))
    server_ip = f"10.200.100.{server_num+10}"

    iperf3_path = os.path.join(out_dir, f"{server_name}_{client_name}_{timestamp:.0f}.json")
    iperf3_args = ["-c", server_ip, "-p", server_port, "-t", duration, "--json"]
    if udp:
        iperf3_args.append("-u")
    if bitrate:
        iperf3_args.append("--bitrate")
        iperf3_args.append(bitrate)

    iperf3_args.append("--logfile")
    iperf3_args.append(iperf3_path)
    client_cmd = ["ip", "netns", "exec", f"ns-{client_name}", "iperf3"] + iperf3_args
    client_cmd = [f"{x}" for x in client_cmd]

    if verbosity == "verbose":
        print(f"run_iperf3_client({server_name=}, {client_name=}, {out_dir=})")
        print(" ".join(client_cmd))

    subprocess.Popen(client_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    start_new_session=True,
                    close_fds=True)

def start_iperf3_servers(node_names: list[str]):
    for server in node_names:
        for client in node_names:
            if client == server:
                continue
            run_iperf3_server(server, client)

def run_nsperf_client(server_name: str,
                      client_name: str,
                      out_dir: str, 
                      timestamp: float,
                      duration: str, 
                      bitrate: str):
    # extract ip and port from server device
    server_port = NSPERF_PORT
    server_ipv4, subnet_bits = ipv4_addr(server_name)

    nsperf_path = os.path.join(out_dir, f"{server_name}_{client_name}_{timestamp:.0f}.send.csv")

    run_id = "run-" + datetime.now().isoformat(timespec="seconds").replace("+00:00", "Z")
    flow_id = f"{server_name}_{client_name}_{timestamp:.0f}"

    client_cmd = ["ip", "netns", "exec", f"ns-{server_name}", 
                  "nsperf", "client", "--dst", server_ipv4, "--port", str(server_port), 
                  "--bitrate", bitrate, "--duration", duration, 
                  "--run-id", run_id, "--flow-id", flow_id, "--out", nsperf_path]

    if verbosity == "verbose":
        print(f"run_nsperf_client({server_name=}, {client_name=}, {out_dir=})")
        print(" ".join(client_cmd))

    subprocess.Popen(client_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    start_new_session=True,
                    close_fds=True)

def run_nsperf_server(server_name: str, out_dir: str):
    server_port = NSPERF_PORT
    server_ipv4, subnet_bits = ipv4_addr(server_name)

    nsperf_path =  os.path.join(out_dir, f"{server_name}.recv.csv")
    server_cmd = ["ip", "netns", "exec", f"ns-{server_name}", 
                  "nsperf", "server", "--bind", server_ipv4, "--port", str(server_port), "--out", nsperf_path]
    server_proc = subprocess.Popen(server_cmd,
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)

    nsperf_servers.append(server_proc)

    if verbosity == "verbose":
        print(f"run_nsperf_server({server_name=})")
        print(" ".join(server_cmd))

def start_nsperf_servers(node_names: list[str]):
    for server in node_names:
            run_nsperf_server(server, nsperf_dir)

def stop_all_nsperf_servers():
    sigint_all(nsperf_servers)

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
            "phyrate_mbps": round(data_rate_given_dist_comm(math.sqrt(dist_sq)), 2),
            "loss_percent": 10,
        }

        graph["links"].append(link)

    graph["nodes"].extend(devs)

def start_batadv(node_name: str, version5: bool = True, tid = None):
    if version5:
        start_script = os.path.join(repo_root, "emulation_scripts", "start_batadv_v.sh")
    else:
        raise NotImplementedError("Only BATMAN_V implemented")
    if not tid:
        tid = get_thread_id()
    remote = None
    exec(tid, remote, f'ip netns exec "ns-{node_name}" "{start_script}" "ns-{node_name}"')

def battp_set_link_throughput(n1: str, n2: str, tp: float):
    """
    use battpctl to set link throughput in both directions between two nodes.
    """
    tid = get_thread_id()
    remote = None

    # get n1 and n2 MAC address
    bat_mac_cmd = "ip -o -brief link show uplink | awk '{print $3}'"
    n1_mac = exec(tid, remote, f'ip netns exec "ns-{n1}" {bat_mac_cmd}', get_output=True)[0].strip() # [0] to only get stdout
    n2_mac = exec(tid, remote, f'ip netns exec "ns-{n2}" {bat_mac_cmd}', get_output=True)[0].strip()

    # set throughput limit in both directions (*10 is to go from unit Mbit to 100kbit)
    exec(tid, remote, f'ip netns exec "ns-{n1}" battpctl set bat0 uplink {n2_mac} {int(tp*10)}')
    exec(tid, remote, f'ip netns exec "ns-{n2}" battpctl set bat0 uplink {n1_mac} {int(tp*10)}')

def batctl_set_neigh_throughputs(graph: dict):
    """
    set throughput limit in both direction to all neighbour nodes in a graph.
    """

    for link in graph["links"]:
        battp_set_link_throughput(n1=link["source"], n2=link["target"], tp=float(link["phyrate_mbps"]))

def get_node_addrs(node_id: str, cmd: str):
    """
    get node addresses from command.
    """
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

def set_node_down(node_name: str):
    """
    move uplink to trash namespace and remove bat0 to simulate node down
    
    assumes namespace for node is already created
    """
    tid = get_thread_id()
    remote = None

    exec(tid, remote, f'ip netns exec "ns-{node_name}" batctl meshif bat0 interface destroy 2>/dev/null || true')
    exec(tid, remote, f'ip netns add "trash-{node_name}" 2>/dev/null || true')
    exec(tid, remote, f'ip netns exec "ns-{node_name}" ip link set uplink down')
    exec(tid, remote, f'ip netns exec "ns-{node_name}" ip link set uplink nomaster')
    exec(tid, remote, f'ip netns exec "ns-{node_name}" ip link set uplink netns "trash-{node_name}"')

def set_node_up(node_name: str, graph: dict):
    """
    move uplink from trash to ns-node_name and add bat0 to simulate node up
    
    assumes node was previously pulled down with `set_node_down()`
    """
    tid = get_thread_id()
    remote = None
    exec(tid, remote, f'ip netns exec "trash-{node_name}" ip link set uplink netns "ns-{node_name}"')
    start_batadv(node_name, version5=True, tid=tid)
    exec(tid, remote, f'ip netns exec "ns-{node_name}" ip link set uplink up', get_output=True) # get_output=True -> syncronous guard

    filt = lambda link: link["source"] == node_name or link["target"] == node_name
    links = filter(filt, graph["links"])
    for link in links:
        battp_set_link_throughput(link["source"], link["target"], float(link["phyrate_mbps"]))

def gen_dropout_sched(nodes: list[str], t_start_step: float, t_sim_end: float, params: DropoutParams) -> list[SchedEntry]:
    """
    nodes: list of node names
    t_start_step: linear step size for offsetting drones by different start time [s]
    t_sim_end: end time for simulation [s]
    params: dropout model parameters

    returns: list[tuple[float, str, State]]
    dropout update schedule entries for nodes with [time, drone name, new state]
    """
    sims = MultipleDroneSim(
            names = nodes,
            t_start_step = t_start_step,
            params = params, 
            )

    sims.stepuntil(t_sim_end)
    events = []
    for t, event in sims.get():
        e = SchedEntry(
                time=t,
                event=event)
        events.append(e)
    return events

def stub_iperf_sched():
    """
    create manual iperf schedule entries at specific time
    """
    # sched: list[tuple[float, IperfEvent]] = []
    events: list[SchedEntry] = []

    sim_times = [0.0, 10.0, 20.0, 30.0, 32.0, 34.0, 35.0, 40.0]
    iperf_events = [IperfEvent(client_name="d0", server_name="d1", bitrate="4M", udp=False, duration=5),
                    IperfEvent(client_name="d1", server_name="d2", bitrate="2M", udp=False, duration=6),
                    IperfEvent(client_name="d2", server_name="d3", bitrate="2M", udp=False, duration=7),
                    IperfEvent(client_name="d3", server_name="d4", bitrate="3M", udp=False, duration=8),
                    IperfEvent(client_name="d4", server_name="d5", bitrate="3M", udp=False, duration=9),
                    IperfEvent(client_name="d5", server_name="d0", bitrate="1M", udp=False, duration=5),
                    IperfEvent(client_name="d0", server_name="d1", bitrate="1M", udp=False, duration=6),
                    IperfEvent(client_name="d1", server_name="d2", bitrate="4M", udp=False, duration=7),
                    ]

    for sim_time, event in zip(sim_times, iperf_events):
        e = SchedEntry(
                time=sim_time,
                event=event)
        events.append(e)

    return events

def do_event(e: SchedEvent, graph: dict, simtime: float):
    """
    performs either iperf or dropout event from given graph and schedule event type
    """
    if verbosity != "quiet":
        print(f"Event {e} run at {datetime.now()}")
    if isinstance(e, IperfEvent):
        e_: IperfEvent = e # just to make pyright happy :(
        run_iperf3_client(
                server_name=e.server_name,
                client_name=e.client_name,
                out_dir=iperf3_dir,
                timestamp=simtime,
                duration=e_.duration,
                udp=e.udp,
                bitrate=e.bitrate,
                )
    elif isinstance(e, NsperfEvent):
        run_nsperf_client(
                server_name=e.server_name,
                client_name=e.client_name,
                out_dir=nsperf_dir,
                timestamp=simtime,
                duration=e.duration,
                bitrate=e.bitrate,
                )
    elif isinstance(e, DropoutEvent):
        if e.state != State.UP:
            set_node_down(e.name)
        else:
            set_node_up(e.name, graph)
    else:
        raise ValueError("Invalid event type: " + type(e))

def run_sim_sched(graph: dict, sched: list[SchedEntry], duration: float) -> Sim:
    """
    runs simulation schedule from given graph of nodes and schedule list in a set duration.
    """
    t_start = datetime.now()
    t_end = t_start + timedelta(seconds=duration)

    if verbosity != "quiet":
        print(f"""
        {'='*50}
        {'SIMULATION'.center(50)}
        {'='*50}
        Start time : {t_start}
        End time   : {t_end}
        Duration   : {duration:.1f} s
        {'='*50}
        """)

    # perform sim while duration not expired
    sched_sorted = sorted(sched)

    sched_real: list[SchedEntry] = []

    done = False
    i = 0

    while not done:
        t_current = datetime.now()
        t_elapsed = (t_current - t_start).total_seconds()

        # if there are more events
        if i < len(sched_sorted):
            e = sched_sorted[i]
            if t_elapsed >= e.time:
                # handle event
                do_event(e.event, graph, t_elapsed)
                e_cp = copy(e)
                e_cp.time = t_elapsed
                sched_real.append(e_cp)
                i += 1
            elif e.time-t_elapsed > 2:
                # sleep till next event
                time.sleep(e.time-t_elapsed-1)

        # Stop if simulation duration is reached
        if t_elapsed > duration:
            done = True

    return Sim(start_timestamp=t_start.timestamp(), duration=duration, sched_plan=sched_sorted, sched_real=sched_real)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('graph', 
                        help='Graph of the full network mesh (json)')
    parser.add_argument('-s', '--sim-sched', required=False, 
                        help='Simulation schedule (json)')
    parser.add_argument('-g', '--gen-sched', required=False, action="store_true",
                        help='Generate schedule with iperf3 traffic')
    parser.add_argument('--drop-model', type=float, required=False,
                        help='Add dropout model schedule with given drop percentage per timestep to schedule.')
    parser.add_argument('-d', '--duration', type=int, required=False, 
                        help='Duration for simulation [s]')
    parser.add_argument('-l', '--link-loss', type=str, required=False, 
                        help='Set link loss fx "1%%". If not set the link loss from graph is used.')
    parser.add_argument('-v', '--verbosity', choices=['verbose', 'normal', 'quiet'], default='normal', 
                        help='Set verbosity.')
    args = parser.parse_args()

    global verbosity
    verbosity = args.verbosity
    globalTerminalGroup.setVerbosity(args.verbosity)

    # Setup output directories
    try:
        shutil.rmtree(pcap_dir)
        shutil.rmtree(iperf3_dir)
        shutil.rmtree(nsperf_dir)
    except FileNotFoundError as e:
        pass

    os.makedirs(exist_ok=False, name=pcap_dir)
    os.makedirs(exist_ok=False, name=iperf3_dir)
    os.makedirs(exist_ok=False, name=nsperf_dir)

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
    adapter_pos = [(765.0, 5000.0, 0.0), 
                   (5510.0, 2260.0, 0.0),
                   (15000.0, 7739.0, 0.0), 
                   (24489.0, 7739.0, 0.0), 
                   (29234.0, 5000.0, 0.0)]
    place_test_adapters(graph, adapter_pos)
    with open(graph_json_path, "w") as f:
        json.dump(graph, f)

    # Create network name spaces with links from json graph
    tc_script = os.path.join(repo_root, "emulation_scripts", "tc.sh")

    # set link loss 
    if args.link_loss:
        link_command = tc_script + f" '{{action}}' '{{ifname}}' '{args.link_loss}' '{{phyrate_mbps}}'"
    else:
        link_command = tc_script + " '{action}' '{ifname}' '{loss_percent}' '{phyrate_mbps}'"

    mn_network.apply(graph, link_command=link_command)

    # Init batman-adv on all nodes and adapters
    rmap = get_remote_mapping([Remote()]) # running everything locally
    all_ids = rmap.keys()
    drone_ids = list(filter(lambda x: x.startswith("n"), all_ids))
    adapter_ids = list(filter(lambda x: x.startswith("a"), all_ids))

    # Start tcpdump for each node
    for id in all_ids:
        start_tcpdump(id, f"br-{id}", "switch", pcap_dir)
    time.sleep(0.5)  # allow to launch tcpdumps
    

    # Load or generate schedule
    sched = None
    duration = None

    # load sched
    if args.sim_sched:
        if verbosity != "quiet":
            print(f"Loading simulation schedule from file {args.sim_sched}")
        # Load schedule
        try:
            with open(args.sim_sched, "r") as f:
                sim_obj = Sim.model_validate(from_json(f.read()))
            sched = sim_obj.sched_plan
            duration = args.duration or sim_obj.duration
        except:
            raise ValueError(f"Invalid sim schedule file {args.sim_sched}")

    # generate sched
    if args.gen_sched:
        if not args.duration:
            raise ValueError("Cannot generate schedule without arg --duration")
        duration = args.duration
        if verbosity != "quiet":
            print("Generating simulation schedule")

        sched = stub_iperf_sched()

    # add drop model to sched if argument is set
    if args.drop_model:
        if sched is None: 
            raise ValueError("Adding drop model to schedule requires existing schedule")
        # set Dropout model parameters and generate schedule
        dropout_params = DropoutParams(
                        failure_probability = args.drop_model,
                        replacement_distribution_sampler = lambda : 100*random.random()+50,
                        time_step = 10,
                        fly_up_time = 30,
                        fly_down_time = 30,
                        desired_fly_time = 900,
                        recharging_time = 700,
                )
        dropout_sched = gen_dropout_sched(nodes=drone_ids,
                          t_start_step=50,
                          t_sim_end=args.duration,
                          params=dropout_params)

        sched = dropout_sched + sched

    if sched is None:
        raise ValueError("Cannot perform simulation without a schedule")
    if duration is None: 
        raise ValueError("Cannot perform simulation if duration is not set with --duration or specified in the loaded schedule")



    if verbosity != "quiet":
        print(f"Running simulation on {len(drone_ids)} drones and {len(adapter_ids)} devices")

    for nid in drone_ids:
        start_batadv(nid, version5=True)
    for nid in adapter_ids:
        start_batadv(nid, version5=True)

    device_ids = []
    for adapter_id in adapter_ids:
        device_id = adapter_id.replace("a", "d")
        device_ids.append(device_id)
        create_device(device_id, adapter_id)
    time.sleep(2)

    # Add devices and start tcpdump
    for device_id in device_ids:
        start_tcpdump(device_id, "veth0", f"ns-{device_id}", pcap_dir)

    start_iperf3_servers(device_ids)
    start_nsperf_servers(device_ids)

    # Make json files for IP addrs and MAC addrs overview
    get_all_addrs(graph, device_ids)

    if verbosity != "quiet":
        print("Wait for batman-adv to be ready")
    time.sleep(10) # wait for batman to be ready

    # Apply throughput override
    batctl_set_neigh_throughputs(graph)
    if verbosity != "quiet":
        print("Wait for throughput override")
    time.sleep(10) # wait for moving average in throughput override

    sim = run_sim_sched(graph=graph, sched=sched, duration=duration)
    with open(sim_sched_json_path, "wb") as f:
        f.write(to_json(sim))

    # input("Press Enter to end emulation")

    stop_all_iperf3_servers()
    stop_all_nsperf_servers()
    stop_all_tcpdump()
    stop_all_terminals()

if __name__ == "__main__":
    main()
