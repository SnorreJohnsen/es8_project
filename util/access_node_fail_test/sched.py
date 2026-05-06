#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
from typing import Any


def natural_adapter_key(adapter: str) -> tuple[int, str]:
    match = re.fullmatch(r"a([0-9]+)", adapter)
    if match is None:
        raise ValueError(f"Adapter name must look like a0, got {adapter!r}")
    return (int(match.group(1)), adapter)


def adapter_ids(graph: dict[str, Any]) -> list[str]:
    adapters = [
        str(node["id"])
        for node in graph.get("nodes", [])
        if re.fullmatch(r"a[0-9]+", str(node["id"]))
    ]
    if not adapters:
        raise ValueError("Graph contains no adapter nodes matching a<number>")
    return sorted(adapters, key=natural_adapter_key)


def device_name(adapter: str) -> str:
    natural_adapter_key(adapter)
    return f"d{adapter[1:]}"


def device_names(adapters: list[str]) -> list[str]:
    return [device_name(adapter) for adapter in adapters]


def access_node_name(graph: dict[str, Any], access_adapter: str) -> str:
    natural_adapter_key(access_adapter)
    node_ids = {str(node["id"]) for node in graph.get("nodes", [])}
    if access_adapter not in node_ids:
        raise ValueError(f"Access adapter {access_adapter!r} is not present in graph nodes")

    drone_neighbors: set[str] = set()
    for link in graph.get("links", []):
        source = str(link.get("source"))
        target = str(link.get("target"))
        if source == access_adapter and target.startswith("n"):
            drone_neighbors.add(target)
        elif target == access_adapter and source.startswith("n"):
            drone_neighbors.add(source)

    if not drone_neighbors:
        raise ValueError(f"No n* access node link found for adapter {access_adapter!r}")
    if len(drone_neighbors) > 1:
        neighbors = ", ".join(sorted(drone_neighbors))
        raise ValueError(f"Expected exactly one n* access node for {access_adapter!r}, found: {neighbors}")

    return next(iter(drone_neighbors))


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

    adapters = adapter_ids(graph)
    access_node = access_node_name(graph, args.access_adapter)
    default_devices = device_names(adapters)
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

    print(f"Generated {count} schedule(s); {args.access_adapter} access node is {access_node}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"error: {exc}")
