import math
import os
import argparse
import json

from pprint import pprint

from mesh_design_lib import data_rate_given_dist_comm

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

def parse_adapter_pos(adapter_coords: str) -> list[tuple[float, float, float]]:
    coords = []
    for item in adapter_coords.split(";"):
        x, y, z = item.strip("() ").split(",")
        coords.append((float(x), float(y), float(z)))
    return coords

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('graph', 
                        help='Graph of the full network mesh (json)')
    parser.add_argument('--adapter-pos', required=True, 
                        help='List of (x, y, z) tuples, e.g. "(1,2,0);(3,4,2)".')
    parser.add_argument('output', 
                        help='Output path of the graph with adapters placed (json)')
    parser.add_argument('-v', '--verbosity', choices=['verbose', 'normal', 'quiet'], default='normal', 
                        help='Set verbosity.')
    args = parser.parse_args()

    if not os.path.isfile(args.graph):
        print(f'File not found: {args.graph}')
        exit(1)
    with open(args.graph) as f:
        graph = json.load(f)

    if args.verbosity == "verbose":
        print("graph")
        pprint(graph)

    adapter_pos = parse_adapter_pos(args.adapter_pos)
    place_test_adapters(graph, adapter_pos)

    with open(args.output, "w") as f:
        json.dump(graph, f)

if __name__ == "__main__":
    main()
