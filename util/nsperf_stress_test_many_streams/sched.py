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


def parse_num_streams_sequence(value: str) -> list[int]:
    seq = [int(item) for item in value.split()]
    if not seq:
        raise ValueError("num streams sequence cannot be empty")
    if any(count <= 0 for count in seq):
        raise ValueError("all num streams sequence values must be > 0")
    return seq


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


def schedule(
    devices: list[str],
    num_streams_sequence: list[int],
    target_bitrate: str,
    stream_duration_s: float,
    silence_s: float,
    start_time_s: float,
    seed: int,
    nsperf_header: str,
) -> dict[str, Any]:
    rng = random.Random(seed)
    sched_plan: list[dict[str, Any]] = []

    group_spacing_s = stream_duration_s + silence_s
    for group_idx, num_streams in enumerate(num_streams_sequence):
        group_time = start_time_s + group_idx * group_spacing_s
        for stream_idx in range(num_streams):
            client, server = choose_stream(devices, rng)
            sched_plan.append(
                {
                    "time": group_time,
                    "event": {
                        "nsperf_header": f"{nsperf_header}_g{group_idx}_s{stream_idx}",
                        "client_name": client,
                        "server_name": server,
                        "bitrate": target_bitrate,
                        "duration": f"{stream_duration_s:g}s",
                    },
                }
            )

    duration = start_time_s + len(num_streams_sequence) * group_spacing_s
    return {
        "start_timestamp": 0,
        "duration": duration,
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
    ap.add_argument("--iteration", type=int, required=True)
    ap.add_argument("--num-streams-sequence", default="1 2 4 6 8 10 15")
    ap.add_argument("--stream-duration", type=float, default=10.0)
    ap.add_argument("--silence", type=float, default=30.0)
    ap.add_argument("--start-time", type=float, default=10.0)
    ap.add_argument("--seed", type=int, help="Override deterministic seed")
    ap.add_argument("--seed-base", default="nsperf_stress_test_many_streams")
    ap.add_argument("--nsperf-header", default="nsperf_stress")
    ap.add_argument("--adapter-rows", type=int, default=3)
    ap.add_argument("--adapter-cols", type=int, default=7)
    ap.add_argument("--adapter-z", type=float, default=0.0)
    args = ap.parse_args()

    if args.iteration < 0:
        raise ValueError("--iteration must be >= 0")
    if args.stream_duration <= 0:
        raise ValueError("--stream-duration must be > 0")
    if args.silence < 0:
        raise ValueError("--silence must be >= 0")
    if args.start_time < 0:
        raise ValueError("--start-time must be >= 0")

    with args.graph.open(encoding="utf-8") as f:
        graph = json.load(f)

    adapters = adapter_ids(graph)
    devices = device_names(adapters)
    seq = parse_num_streams_sequence(args.num_streams_sequence)
    seed = args.seed
    if seed is None:
        seed = stable_seed(
            [
                args.seed_base,
                args.graph_name,
                args.loss,
                args.target_bitrate,
                str(args.iteration),
                " ".join(str(value) for value in seq),
            ]
        )

    sim = schedule(
        devices=devices,
        num_streams_sequence=seq,
        target_bitrate=args.target_bitrate,
        stream_duration_s=args.stream_duration,
        silence_s=args.silence,
        start_time_s=args.start_time,
        seed=seed,
        nsperf_header=args.nsperf_header,
    )
    write_json(args.output, sim)

    metadata = {
        "graph": str(args.graph),
        "graph_name": args.graph_name,
        "loss": args.loss,
        "target_bitrate": args.target_bitrate,
        "iteration": args.iteration,
        "seed": seed,
        "seed_base": args.seed_base,
        "adapter_rows": args.adapter_rows,
        "adapter_cols": args.adapter_cols,
        "adapter_z": args.adapter_z,
        "adapter_count": len(adapters),
        "device_count": len(devices),
        "num_streams_sequence": seq,
        "stream_duration_s": args.stream_duration,
        "silence_s": args.silence,
        "start_time_s": args.start_time,
        "duration": sim["duration"],
    }
    metadata_output = args.metadata_output or args.output.with_suffix(".meta.json")
    write_json(metadata_output, metadata)

    print(
        "Generated schedule "
        f"{args.output}; bitrate={args.target_bitrate}; iteration={args.iteration}; seed={seed}"
    )


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"error: {exc}")
