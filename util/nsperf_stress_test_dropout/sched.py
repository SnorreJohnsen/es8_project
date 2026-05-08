#!/usr/bin/env python3

import argparse
import hashlib
import json
import random
import re
from pathlib import Path
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
        if re.fullmatch(r"a[0-9]+", str(node.get("id")))
    ]
    if not adapters:
        raise ValueError("Graph contains no adapter nodes matching a<number>")
    return sorted(adapters, key=natural_adapter_key)


def device_name(adapter: str) -> str:
    natural_adapter_key(adapter)
    return f"d{adapter[1:]}"


def device_names(adapters: list[str]) -> list[str]:
    return [device_name(adapter) for adapter in adapters]


def stable_seed(parts: list[str]) -> int:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def choose_stream(devices: list[str], rng: random.Random) -> tuple[str, str]:
    if len(devices) < 2:
        raise ValueError("At least two devices are required to generate non-loopback streams")
    client = rng.choice(devices)
    server = rng.choice(devices)
    while server == client:
        server = rng.choice(devices)
    return client, server


def parse_float(name: str, value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric, got {value!r}") from exc
    return parsed


def schedule(
    devices: list[str],
    num_conns: int,
    target_bitrate: str,
    stream_duration_s: float,
    start_time_s: float,
    sim_duration_s: float,
    seed: int,
    nsperf_header: str,
) -> dict[str, Any]:
    rng = random.Random(seed)
    sched_plan: list[dict[str, Any]] = []

    for stream_idx in range(num_conns):
        client, server = choose_stream(devices, rng)
        sched_plan.append(
            {
                "time": start_time_s,
                "event": {
                    "nsperf_header": f"{nsperf_header}_c{num_conns}_s{stream_idx}",
                    "client_name": client,
                    "server_name": server,
                    "bitrate": target_bitrate,
                    "duration": f"{stream_duration_s:g}s",
                },
            }
        )

    return {
        "start_timestamp": 0,
        "duration": sim_duration_s,
        "sched_plan": sched_plan,
        "sched_real": [],
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(value, f, separators=(",", ":"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("graph", type=Path, help="Graph JSON with adapters already placed")
    ap.add_argument("output", type=Path, help="Output schedule JSON path")
    ap.add_argument("--metadata-output", type=Path, help="Output metadata JSON path")
    ap.add_argument("--graph-name", required=True)
    ap.add_argument("--loss", required=True)
    ap.add_argument("--target-bitrate", required=True)
    ap.add_argument("--num-conns", type=int, required=True)
    ap.add_argument("--failure-probability", required=True)
    ap.add_argument("--replacement-delay", required=True)
    ap.add_argument("--dropout-time-step", required=True)
    ap.add_argument("--iteration", type=int, required=True)
    ap.add_argument("--sim-duration", type=float, default=300.0)
    ap.add_argument("--start-time", type=float, default=10.0)
    ap.add_argument("--seed", type=int, help="Override deterministic seed")
    ap.add_argument("--seed-base", default="nsperf_stress_test_dropout")
    ap.add_argument("--nsperf-header", default="nsperf_dropout_stress")
    ap.add_argument("--adapter-rows", type=int, default=3)
    ap.add_argument("--adapter-cols", type=int, default=7)
    ap.add_argument("--adapter-z", type=float, default=0.0)
    args = ap.parse_args()

    if args.iteration < 0:
        raise ValueError("--iteration must be >= 0")
    if args.num_conns <= 0:
        raise ValueError("--num-conns must be > 0")
    if args.start_time < 0:
        raise ValueError("--start-time must be >= 0")
    if args.sim_duration <= args.start_time:
        raise ValueError("--sim-duration must be greater than --start-time")

    failure_probability = parse_float("--failure-probability", args.failure_probability)
    replacement_delay = parse_float("--replacement-delay", args.replacement_delay)
    dropout_time_step = parse_float("--dropout-time-step", args.dropout_time_step)
    if failure_probability < 0 or failure_probability > 1:
        raise ValueError("--failure-probability must be between 0 and 1")
    if replacement_delay < 0:
        raise ValueError("--replacement-delay must be >= 0")
    if dropout_time_step <= 0:
        raise ValueError("--dropout-time-step must be > 0")

    with args.graph.open(encoding="utf-8") as f:
        graph = json.load(f)

    adapters = adapter_ids(graph)
    devices = device_names(adapters)
    seed = args.seed
    if seed is None:
        seed = stable_seed(
            [
                args.seed_base,
                args.graph_name,
                args.loss,
                args.target_bitrate,
                str(args.num_conns),
                args.failure_probability,
                args.replacement_delay,
                args.dropout_time_step,
                str(args.iteration),
            ]
        )

    stream_duration_s = args.sim_duration - args.start_time
    sim = schedule(
        devices=devices,
        num_conns=args.num_conns,
        target_bitrate=args.target_bitrate,
        stream_duration_s=stream_duration_s,
        start_time_s=args.start_time,
        sim_duration_s=args.sim_duration,
        seed=seed,
        nsperf_header=args.nsperf_header,
    )
    write_json(args.output, sim)

    updown_drop_params = {
        "failure_probability": failure_probability,
        "replacement_delay": replacement_delay,
        "time_step": dropout_time_step,
    }
    metadata = {
        "graph": str(args.graph),
        "graph_name": args.graph_name,
        "loss": args.loss,
        "target_bitrate": args.target_bitrate,
        "num_conns": args.num_conns,
        "failure_probability": failure_probability,
        "replacement_delay": replacement_delay,
        "dropout_time_step": dropout_time_step,
        "iteration": args.iteration,
        "seed": seed,
        "seed_base": args.seed_base,
        "adapter_rows": args.adapter_rows,
        "adapter_cols": args.adapter_cols,
        "adapter_z": args.adapter_z,
        "adapter_count": len(adapters),
        "device_count": len(devices),
        "start_time_s": args.start_time,
        "stream_duration_s": stream_duration_s,
        "duration": sim["duration"],
        "updown_drop_params": updown_drop_params,
        "updown_drop_params_json": json.dumps(updown_drop_params, separators=(",", ":")),
    }
    metadata_output = args.metadata_output or args.output.with_suffix(".meta.json")
    write_json(metadata_output, metadata)

    print(
        "Generated schedule "
        f"{args.output}; bitrate={args.target_bitrate}; num_conns={args.num_conns}; "
        f"failure_probability={args.failure_probability}; iteration={args.iteration}; seed={seed}"
    )


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"error: {exc}")
