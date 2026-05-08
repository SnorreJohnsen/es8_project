#!/usr/bin/env python3

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

UTIL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UTIL_DIR))

from graph_tx_bps import accumulate, bits_to_bps, bucket_bits, run_tshark  # noqa: E402


NODE_FIELDS = [
    "mesh_size",
    "node",
    "node_type",
    "total_bits",
    "mean_bps",
    "max_bps",
    "p50_bps",
    "p90_bps",
    "p95_bps",
    "p99_bps",
]

NETWORK_FIELDS = [
    "mesh_size",
    "node_count",
    "total_bits",
    "mean_total_bps",
    "max_total_bps",
    "mean_node_mean_bps",
    "max_node_mean_bps",
    "p50_node_mean_bps",
    "p90_node_mean_bps",
    "p95_node_mean_bps",
    "p99_node_mean_bps",
]


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def node_type(node: str) -> str:
    if node.startswith("n"):
        return "drone"
    if node.startswith("a"):
        return "adapter"
    return "other"


def network_nodes(graph: dict[str, Any]) -> list[str]:
    return sorted(
        (str(node["id"]) for node in graph["nodes"] if str(node["id"]).startswith(("n", "a"))),
        key=natural_key,
    )


def natural_key(value: str) -> tuple[str, int, int | str]:
    match = re.fullmatch(r"([A-Za-z]+)([0-9]+)", value)
    if match is None:
        return (value, 1, value)
    prefix, number = match.groups()
    return (prefix, 0, int(number))


def uplink_mac(addrs: dict[str, Any], node: str) -> str:
    try:
        macs = addrs[node]["mac"]
    except KeyError as exc:
        raise KeyError(f"No MAC address entry for node {node}") from exc

    for ifname in sorted(macs):
        if ifname.startswith("uplink"):
            return str(macs[ifname]).lower()

    raise KeyError(f"No uplink MAC address for node {node}")


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    pos = (len(ordered) - 1) * (pct / 100.0)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]

    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def bps_stats(values: list[float]) -> dict[str, float]:
    return {
        "mean_bps": mean(values),
        "max_bps": max(values) if values else 0.0,
        "p50_bps": percentile(values, 50),
        "p90_bps": percentile(values, 90),
        "p95_bps": percentile(values, 95),
        "p99_bps": percentile(values, 99),
    }


def write_bucket_outputs(
    node_dir: Path,
    times: list[float],
    bits: list[int],
    bps: list[float],
) -> None:
    node_dir.mkdir(parents=True, exist_ok=True)

    with (node_dir / "bucket.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "bits", "bps"])
        writer.writerows(zip(times, bits, bps))

    with (node_dir / "accum.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "accum_bits"])
        writer.writerows(zip(times, accumulate(bits)))


def write_plots(
    node_dir: Path,
    times: list[float],
    bits: list[int],
    accum_bits: list[int],
    bucket_s: float,
    node: str,
    mac: str,
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.figure()
    plt.bar(times, bits, width=bucket_s, align="edge")
    plt.xlabel(f"Time since simulation start [s] (bucket={bucket_s}s)")
    plt.ylabel("Bits transmitted in bucket")
    plt.title(f"Transmitted bits vs time for {node} ({mac})")
    plt.grid(True, axis="y")
    plt.tight_layout()
    plt.savefig(node_dir / "bucket.png", dpi=150)
    plt.close()

    plt.figure()
    plt.plot(times, accum_bits)
    plt.xlabel(f"Time since simulation start [s] (bucket={bucket_s}s)")
    plt.ylabel("Accumulated bits")
    plt.title(f"Accumulated transmitted bits vs time for {node} ({mac})")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(node_dir / "accum.png", dpi=150)
    plt.close()


def write_nodes_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NODE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def sort_mesh_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple[int, str]:
        mesh_size = str(row["mesh_size"])
        try:
            return (int(mesh_size), mesh_size)
        except ValueError:
            return (10**12, mesh_size)

    return sorted(rows, key=key)


def upsert_network_csv(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if path.exists():
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = [existing for existing in reader if existing.get("mesh_size") != str(row["mesh_size"])]

    rows.append({field: row[field] for field in NETWORK_FIELDS})
    rows = sort_mesh_rows(rows)

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NETWORK_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def analyze(emulation_dir: Path, mesh_size: str, out_dir: Path, bucket_s: float) -> None:
    sim_sched = load_json(emulation_dir / "sim_sched.json")
    graph = load_json(emulation_dir / "graph.json")
    addrs = load_json(emulation_dir / "node_addrs.json")

    start_epoch = float(sim_sched["start_timestamp"])
    duration = float(sim_sched["duration"])
    nodes = network_nodes(graph)
    if not nodes:
        raise ValueError("No n* or a* network nodes found in graph.json")

    node_rows: list[dict[str, Any]] = []
    all_node_bps: list[list[float]] = []

    for node in nodes:
        mac = uplink_mac(addrs, node)
        pcap = emulation_dir / "pcaps" / "raw" / f"{node}.pcap"
        if not pcap.is_file():
            raise FileNotFoundError(f"Missing pcap for node {node}: {pcap}")

        samples = run_tshark(pcap, mac)
        times, bits = bucket_bits(samples, bucket_s, start_epoch=start_epoch, duration=duration)
        bps = bits_to_bps(bits, bucket_s)
        node_dir = emulation_dir / "plots" / node

        write_bucket_outputs(node_dir, times, bits, bps)
        write_plots(node_dir, times, bits, accumulate(bits), bucket_s, node, mac)

        stats = bps_stats(bps)
        row: dict[str, Any] = {
            "mesh_size": mesh_size,
            "node": node,
            "node_type": node_type(node),
            "total_bits": sum(bits),
            **stats,
        }
        node_rows.append(row)
        all_node_bps.append(bps)

    write_nodes_csv(emulation_dir / "maint_bps_nodes.csv", node_rows)

    bucket_count = len(all_node_bps[0]) if all_node_bps else 0
    total_bps_by_bucket = [
        sum(node_bps[idx] for node_bps in all_node_bps)
        for idx in range(bucket_count)
    ]
    node_mean_bps = [float(row["mean_bps"]) for row in node_rows]
    network_row = {
        "mesh_size": mesh_size,
        "node_count": len(node_rows),
        "total_bits": sum(int(row["total_bits"]) for row in node_rows),
        "mean_total_bps": mean(total_bps_by_bucket),
        "max_total_bps": max(total_bps_by_bucket) if total_bps_by_bucket else 0.0,
        "mean_node_mean_bps": mean(node_mean_bps),
        "max_node_mean_bps": max(node_mean_bps) if node_mean_bps else 0.0,
        "p50_node_mean_bps": percentile(node_mean_bps, 50),
        "p90_node_mean_bps": percentile(node_mean_bps, 90),
        "p95_node_mean_bps": percentile(node_mean_bps, 95),
        "p99_node_mean_bps": percentile(node_mean_bps, 99),
    }
    upsert_network_csv(out_dir / "maint_bps_network.csv", network_row)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("emulation_dir", type=Path, help="Live emulation output directory")
    ap.add_argument("mesh_size", help="Mesh size label")
    ap.add_argument("out_dir", type=Path, help="Maintenance measurement output root")
    ap.add_argument("--bucket", type=float, default=1.0, help="Bucket width in seconds")
    args = ap.parse_args()

    if args.bucket <= 0:
        raise ValueError("--bucket must be > 0")

    analyze(args.emulation_dir, args.mesh_size, args.out_dir, args.bucket)


if __name__ == "__main__":
    main()
