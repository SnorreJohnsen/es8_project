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
    "graph_name",
    "mesh_size",
    "node",
    "node_type",
    "duration_s",
    "bucket_s",
    "total_bits",
    "avg_tx_bps",
    "max_bps",
    "p50_bps",
    "p90_bps",
    "p95_bps",
    "p99_bps",
]

NETWORK_FIELDS = [
    "graph_name",
    "mesh_size",
    "node_count",
    "duration_s",
    "bucket_s",
    "total_bits",
    "avg_total_tx_bps",
    "max_total_tx_bps",
    "avg_node_tx_bps",
    "max_node_avg_tx_bps",
    "p50_node_avg_tx_bps",
    "p90_node_avg_tx_bps",
    "p95_node_avg_tx_bps",
    "p99_node_avg_tx_bps",
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


def drone_nodes(graph: dict[str, Any]) -> list[str]:
    return sorted(
        (str(node["id"]) for node in graph["nodes"] if str(node["id"]).startswith("n")),
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


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple[int, str, tuple[str, int, int | str]]:
        mesh_size = str(row["mesh_size"])
        try:
            mesh_key = int(mesh_size)
        except ValueError:
            mesh_key = 10**12

        return (
            mesh_key,
            str(row.get("graph_name", "")),
            natural_key(str(row.get("node", ""))),
        )

    return sorted(rows, key=key)


def upsert_csv(
    path: Path,
    new_rows: list[dict[str, Any]],
    fields: list[str],
    key_fields: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if path.exists():
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames == fields:
                replace_keys = {
                    tuple(str(row[field]) for field in key_fields)
                    for row in new_rows
                }
                rows = [
                    existing
                    for existing in reader
                    if tuple(str(existing.get(field, "")) for field in key_fields) not in replace_keys
                ]

    rows.extend({field: row[field] for field in fields} for row in new_rows)
    rows = sort_rows(rows)

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_plot_data(nodes_csv: Path) -> tuple[Any, list[str]]:
    import pandas as pd

    df = pd.read_csv(nodes_csv)
    if df.empty:
        raise ValueError(f"No node rows found in {nodes_csv}")

    mesh_order = sorted(
        (str(value) for value in df["mesh_size"].dropna().unique()),
        key=lambda value: (int(value) if str(value).isdigit() else 10**12, str(value)),
    )
    df["mesh_size"] = df["mesh_size"].astype(str)
    return df, mesh_order


def plot_distribution(
    nodes_csv: Path,
    output: Path,
    kind: str,
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    df, mesh_order = load_plot_data(nodes_csv)

    width = max(7.0, min(18.0, 0.75 * len(mesh_order) + 4.0))
    plt.figure(figsize=(width, 5.0))
    sns.set_theme(style="whitegrid")
    if kind == "box":
        ax = sns.boxplot(data=df, x="mesh_size", y="avg_tx_bps", order=mesh_order)
    elif kind == "violin":
        ax = sns.violinplot(
            data=df,
            x="mesh_size",
            y="avg_tx_bps",
            order=mesh_order,
            cut=0,
            inner="quartile",
        )
    else:
        raise ValueError(f"Unknown distribution plot kind: {kind}")

    ax.set_xlabel("Mesh size [drones]")
    ax.set_ylabel("Average TX bitrate per drone [bps]")
    ax.set_title("B.A.T.M.A.N. maintenance bitrate by mesh size")
    plt.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, dpi=150)
    plt.close()


def write_aggregate_plots(out_dir: Path) -> None:
    nodes_csv = out_dir / "maint_bps_nodes.csv"
    plot_distribution(nodes_csv, out_dir / "maint_bps_boxplot.png", "box")
    plot_distribution(nodes_csv, out_dir / "maint_bps_violinplot.png", "violin")


def analyze(
    emulation_dir: Path,
    mesh_size: str,
    out_dir: Path,
    bucket_s: float,
    graph_name: str,
    details_dir: Path,
) -> None:
    sim_sched = load_json(emulation_dir / "sim_sched.json")
    graph = load_json(emulation_dir / "graph.json")
    addrs = load_json(emulation_dir / "node_addrs.json")

    start_epoch = float(sim_sched["start_timestamp"])
    duration = float(sim_sched["duration"])
    nodes = drone_nodes(graph)
    if not nodes:
        raise ValueError("No n* drone nodes found in graph.json")

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
        total_bits = sum(bits)
        node_dir = details_dir / graph_name / node

        write_bucket_outputs(node_dir, times, bits, bps)
        write_plots(node_dir, times, bits, accumulate(bits), bucket_s, node, mac)

        stats = bps_stats(bps)
        row: dict[str, Any] = {
            "graph_name": graph_name,
            "mesh_size": mesh_size,
            "node": node,
            "node_type": node_type(node),
            "duration_s": duration,
            "bucket_s": bucket_s,
            "total_bits": total_bits,
            "avg_tx_bps": total_bits / duration,
            **stats,
        }
        node_rows.append(row)
        all_node_bps.append(bps)

    upsert_csv(out_dir / "maint_bps_nodes.csv", node_rows, NODE_FIELDS, ["graph_name", "node"])

    bucket_count = len(all_node_bps[0]) if all_node_bps else 0
    total_bps_by_bucket = [
        sum(node_bps[idx] for node_bps in all_node_bps)
        for idx in range(bucket_count)
    ]
    total_bits = sum(int(row["total_bits"]) for row in node_rows)
    node_avg_tx_bps = [float(row["avg_tx_bps"]) for row in node_rows]
    network_row = {
        "graph_name": graph_name,
        "mesh_size": mesh_size,
        "node_count": len(node_rows),
        "duration_s": duration,
        "bucket_s": bucket_s,
        "total_bits": total_bits,
        "avg_total_tx_bps": total_bits / duration,
        "max_total_tx_bps": max(total_bps_by_bucket) if total_bps_by_bucket else 0.0,
        "avg_node_tx_bps": mean(node_avg_tx_bps),
        "max_node_avg_tx_bps": max(node_avg_tx_bps) if node_avg_tx_bps else 0.0,
        "p50_node_avg_tx_bps": percentile(node_avg_tx_bps, 50),
        "p90_node_avg_tx_bps": percentile(node_avg_tx_bps, 90),
        "p95_node_avg_tx_bps": percentile(node_avg_tx_bps, 95),
        "p99_node_avg_tx_bps": percentile(node_avg_tx_bps, 99),
    }
    upsert_csv(out_dir / "maint_bps_network.csv", [network_row], NETWORK_FIELDS, ["graph_name"])
    write_aggregate_plots(out_dir)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("emulation_dir", type=Path, help="Live emulation output directory")
    ap.add_argument("mesh_size", help="Mesh size label")
    ap.add_argument("out_dir", type=Path, help="Maintenance measurement output root")
    ap.add_argument("--bucket", type=float, default=1.0, help="Bucket width in seconds")
    ap.add_argument("--graph-name", help="Graph/run label for aggregate rows")
    ap.add_argument("--details-dir", type=Path, help="Directory for detailed per-node outputs")
    ap.add_argument(
        "--plot-only",
        action="store_true",
        help="Regenerate aggregate plots from maint_bps_nodes.csv and exit",
    )
    args = ap.parse_args()

    if args.bucket <= 0:
        raise ValueError("--bucket must be > 0")

    if args.plot_only:
        write_aggregate_plots(args.out_dir)
        return

    graph_name = args.graph_name or args.emulation_dir.name
    details_dir = args.details_dir or args.out_dir / "details"
    analyze(args.emulation_dir, args.mesh_size, args.out_dir, args.bucket, graph_name, details_dir)


if __name__ == "__main__":
    main()
