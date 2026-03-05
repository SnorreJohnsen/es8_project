import os
import sys
import argparse
import json
import subprocess
import signal
import time

sys.path.append('meshnet-lab/')
import software as mn_software
import network as mn_network
from shared import eprint, globalTerminalGroup, get_remote_mapping, Remote, stop_all_terminals

# Create list of tcpdump processes
tcpdump_procs = []

def sigint_all(procs: list[subprocess.Popen], timeout: float = 5.0) -> None:
    """
    Terminate multiple subprocess process groups.

    Sends SIGINT to each running process group, waits up to `timeout`
    seconds for termination, then escalates to SIGTERM and finally
    SIGKILL if necessary.

    Assumes each subprocess was started with `start_new_session=True`
    so that `p.pid` is the process group ID.

    Parameters
    ----------
    procs : List of subprocess objects to terminate.
    timeout : Seconds to wait between escalation steps (default: 5.0).
    """
    # 1) Ask nicely: SIGINT to each process group
    for p in procs:
        if p.poll() is None:  # still running
            try:
                os.killpg(p.pid, signal.SIGINT)  # p.pid is the pgid when start_new_session=True
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
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    for p in procs:
        if p.poll() is None:
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # last resort
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

def stop_all_tcpdump():
    sigint_all(tcpdump_procs)


def start_tcpdump(node_name: str, out_dir: str):
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
            "tcpdump", "-i", "bat0", "-n", "-U", "-w", pcap_path]
    
    if verbosity == "verbose":
        print(f"start_tcpdump({node_name=}, {out_dir=})")
        print(" ".join(cmd))

    proc = subprocess.Popen(cmd,
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,
                       start_new_session=False,
                       close_fds=True) 
    
    tcpdump_procs.append(proc)   

    
    

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("graph", help="Graph of the full network mesh (json)")
    parser.add_argument('-v', '--verbosity', choices=['verbose', 'normal', 'quiet'], default='normal', help='Set verbosity.')    
    args = parser.parse_args()

    global verbosity
    verbosity = args.verbosity
    globalTerminalGroup.setVerbosity(args.verbosity)
    
    # make directory for pcap files for all nodes
    os.makedirs(exist_ok=True, name="pcaps")

    if not os.path.isfile(args.graph):
        eprint(f'File not found: {args.graph}')
        exit(1)
    with open(args.graph) as f:
        state = json.load(f)
    
    # Create network name spaces with links from json graph
    link_command = "tc qdisc add dev {ifname} root netem rate {bandwidth_mbit}mbit"
    mn_network.apply(state, link_command=link_command)

    # Init batman-adv on all nodes
    rmap = get_remote_mapping([Remote()]) # running everything locally
    ids = rmap.keys()
    mn_software._start_protocol("batman-adv", rmap, ids)

    # Start tcpdump for each node
    for id in ids:
        start_tcpdump(id, "pcaps")

    time.sleep(30)

    stop_all_tcpdump()         
    stop_all_terminals()        

if __name__ == "__main__":
    main()
