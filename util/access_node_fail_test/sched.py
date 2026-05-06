#!/usr/bin/env python3

import argparse
import json
import os
import shutil
from typing import Any


def stub_adapter_positions() -> list[tuple[float, float, float]]:
    return [
        (765.0, 5000.0, 0.0),
        (5510.0, 2260.0, 0.0),
        (15000.0, 7739.0, 0.0),
        (24489.0, 7739.0, 0.0),
        (29234.0, 5000.0, 0.0),
    ]


def device_names(adapter_count: int) -> list[str]:
    return [f"d{i}" for i in range(adapter_count)]


def adapter_index(adapter_name: str) -> int:
    if not adapter_name.startswith("a"):
        raise ValueError(f"Adapter name must look like a0, got {adapter_name!r}")
    try:
        return int(adapter_name[1:])
    except ValueError as exc:
        raise ValueError(f"Adapter name must look like a0, got {adapter_name!r}") from exc


def coord(node: dict[str, Any]) -> tuple[float, float, float]:
    return (float(node["x"]), float(node["y"]), float(node.get("z", 0.0)))


def dist_sq(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def closest_node_name(graph: dict[str, Any], pos: tuple[float, float, float]) -> str:
    nodes = graph.get("nodes", [])
    if not nodes:
        raise ValueError("Graph has no nodes")

    drone_nodes = [node for node in nodes if str(node["id"]).startswith("n")]
    candidates = drone_nodes or nodes
    closest = min(candidates, key=lambda node: dist_sq(pos, coord(node)))
    return str(closest["id"])


def schedule(
    access_node: str,
    client: str,
    server: str,
    bitrate: str,
    stream_duration: str,
    sim_duration: float,
    down_time: float,
    up_time: float,
    nsperf_header: str,
) -> dict[str, Any]:
    return {
        "start_timestamp": 0,
        "duration": sim_duration,
        "sched_plan": [
            {
                "time": 0,
                "event": {
                    "nsperf_header": nsperf_header,
                    "client_name": client,
                    "server_name": server,
                    "bitrate": bitrate,
                    "duration": stream_duration,
                },
            },
            {"time": down_time, "event": {"name": access_node, "state": "DOWN"}},
            {"time": up_time, "event": {"name": access_node, "state": "UP"}},
        ],
        "sched_real": [],
    }


def stream_name(client: str, server: str) -> str:
    return f"{client}_to_{server}"


def write_schedule(path: str, sim: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sim, f, separators=(",", ":"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("graph", help="Network json graph")
    ap.add_argument("outdir", help="Output directory for simulation schedules")
    ap.add_argument("--clients", nargs="+", help="Client device names")
    ap.add_argument("--servers", nargs="+", help="Server device names")
    ap.add_argument("--include-self", action="store_true", help="Include streams where client and server are the same")
    ap.add_argument("--access-adapter", default="a0", help="Adapter whose closest drone should be dropped")
    ap.add_argument("--down-time", type=float, default=10.0, help="When to bring the access node down")
    ap.add_argument("--up-time", type=float, default=20.0, help="When to bring the access node up")
    ap.add_argument("--duration", type=float, default=60.0, help="Simulation duration")
    ap.add_argument("--stream-duration", default="60s", help="nsperf stream duration")
    ap.add_argument("--bitrate", default="1M", help="nsperf bitrate")
    ap.add_argument("--nsperf-header", default="access_node_fail", help="nsperf schedule marker")
    args = ap.parse_args()

    if not os.path.isfile(args.graph):
        raise FileNotFoundError(f"File not found: {args.graph}")
    with open(args.graph, encoding="utf-8") as f:
        graph = json.load(f)

    adapter_positions = stub_adapter_positions()
    access_adapter_idx = adapter_index(args.access_adapter)
    try:
        access_adapter_pos = adapter_positions[access_adapter_idx]
    except IndexError as exc:
        raise ValueError(f"No stub position for adapter {args.access_adapter!r}") from exc

    access_node = closest_node_name(graph, access_adapter_pos)
    default_devices = device_names(len(adapter_positions))
    clients = args.clients or default_devices
    servers = args.servers or default_devices

    if args.down_time >= args.up_time:
        raise ValueError("--down-time must be less than --up-time")
    if args.up_time >= args.duration:
        raise ValueError("--up-time must be less than --duration")

    try:
        shutil.rmtree(args.outdir)
    except FileNotFoundError:
        pass
    os.makedirs(args.outdir)

    count = 0
    for client in clients:
        for server in servers:
            if client == server and not args.include_self:
                continue
            sim = schedule(
                access_node=access_node,
                client=client,
                server=server,
                bitrate=args.bitrate,
                stream_duration=args.stream_duration,
                sim_duration=args.duration,
                down_time=args.down_time,
                up_time=args.up_time,
                nsperf_header=args.nsperf_header,
            )
            write_schedule(os.path.join(args.outdir, f"{stream_name(client, server)}.json"), sim)
            count += 1

    print(f"Generated {count} schedule(s); {args.access_adapter} closest node is {access_node}")


if __name__ == "__main__":
    main()
