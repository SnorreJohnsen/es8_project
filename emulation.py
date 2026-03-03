import os
import sys
import argparse
import json

sys.path.append('meshnet-lab/')
import software as mn_software
import network as mn_network
from shared import eprint

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("graph", help="Graph of the full network mesh (json)")
    args = parser.parse_args()

    if not os.path.isfile(args.graph):
        eprint(f'File not found: {args.graph}')
        exit(1)
    with open(args.graph) as f:
        state = json.load(f)

    link_command = "tc qdisc add dev {ifname} netem rate {bandwidth_mbit}"
    mn_network.apply(state, link_command=link_command)

if __name__ == "__main__":
    main()
