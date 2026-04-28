#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


DETECTOR_CHOICES = ("prototype_matching", "suffix_cohesion", "local_stability")
PLOT_CHOICES = ("settle-vs-mesh", "dist-vs-mesh", "bucket-compare")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot settle-time statistics from the aggregate JSON produced by detect_steady_state.py"
    )
    parser.add_argument("--input", required=True, help="Aggregate JSON produced by batch mode")
    parser.add_argument("--plot", required=True, choices=PLOT_CHOICES, help="Plot type to generate")
    parser.add_argument("--output", required=True, help="Output image path, e.g. plot.png")
    parser.add_argument(
        "--detector",
        default="local_stability",
        choices=DETECTOR_CHOICES,
        help="Detector to visualize",
    )
    parser.add_argument(
        "--bucket-size",
        type=float,
        help="Filter runs to a single bucket size in seconds",
    )
    parser.add_argument(
        "--mesh-size",
        type=int,
        help="Filter runs to a single mesh size. Mainly used with bucket-compare.",
    )
    parser.add_argument(
        "--stat",
        choices=("median", "mean"),
        default="median",
        help="Summary statistic for line plots",
    )
    return parser.parse_args()


def load_runs(path: Path) -> list[dict[str, Any]]:
    with path.open() as handle:
        data = json.load(handle)
    runs = data.get("runs")
    if not isinstance(runs, list):
        raise ValueError("Input JSON does not contain a top-level 'runs' list")
    return runs


def float_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=tol)


def filter_runs(
    runs: list[dict[str, Any]],
    *,
    bucket_size: float | None = None,
    mesh_size: int | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for run in runs:
        if bucket_size is not None and not float_equal(run["bucket_size_seconds"], bucket_size):
            continue
        if mesh_size is not None and int(run["mesh_size"]) != mesh_size:
            continue
        filtered.append(run)
    return filtered


def detector_settling(run: dict[str, Any], detector: str) -> float | None:
    if detector not in run:
        return None
    value = run[detector]["settling_time_seconds"]
    return None if value is None else float(value)


def group_by_key(runs: list[dict[str, Any]], key_name: str) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault(run[key_name], []).append(run)
    return grouped


def summarize_detector(runs: list[dict[str, Any]], detector: str) -> dict[str, Any]:
    values = [value for run in runs if (value := detector_settling(run, detector)) is not None]
    if not values:
        return {
            "n": len(runs),
            "success_rate": 0.0,
            "mean": None,
            "median": None,
            "p25": None,
            "p75": None,
            "std": None,
        }
    array = np.array(values, dtype=float)
    return {
        "n": len(runs),
        "success_rate": len(values) / len(runs),
        "mean": float(np.mean(array)),
        "median": float(np.median(array)),
        "p25": float(np.percentile(array, 25)),
        "p75": float(np.percentile(array, 75)),
        "std": float(np.std(array)),
    }


def choose_summary_value(summary: dict[str, Any], stat: str) -> float | None:
    return summary["median"] if stat == "median" else summary["mean"]


def choose_yerr(summary: dict[str, Any], stat: str) -> tuple[float, float] | None:
    center = choose_summary_value(summary, stat)
    if center is None:
        return None
    if stat == "median":
        return (center - summary["p25"], summary["p75"] - center)
    return (summary["std"], summary["std"])


def plot_settle_vs_mesh(
    runs: list[dict[str, Any]],
    detector: str,
    stat: str,
    bucket_size: float | None,
    output: Path,
) -> None:
    grouped = group_by_key(runs, "mesh_size")
    mesh_sizes = sorted(int(key) for key in grouped)
    x_values: list[int] = []
    y_values: list[float] = []
    lower_err: list[float] = []
    upper_err: list[float] = []

    for mesh_size in mesh_sizes:
        summary = summarize_detector(grouped[mesh_size], detector)
        center = choose_summary_value(summary, stat)
        if center is None:
            continue
        errs = choose_yerr(summary, stat)
        if errs is None:
            continue
        x_values.append(mesh_size)
        y_values.append(center)
        lower_err.append(errs[0])
        upper_err.append(errs[1])

    if not x_values:
        raise ValueError("No successful runs remain for settle-vs-mesh plot after filtering")

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.errorbar(
        x_values,
        y_values,
        yerr=np.array([lower_err, upper_err]),
        marker="o",
        linewidth=2,
        capsize=4,
    )
    bucket_label = f", bucket={bucket_size:g}s" if bucket_size is not None else ""
    ax.set_title(f"Settling Time vs Mesh Size ({detector}, {stat}{bucket_label})")
    ax.set_xlabel("Mesh Size")
    ax.set_ylabel("Settling Time [s]")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def plot_dist_vs_mesh(
    runs: list[dict[str, Any]],
    detector: str,
    bucket_size: float | None,
    output: Path,
) -> None:
    grouped = group_by_key(runs, "mesh_size")
    mesh_sizes = sorted(int(key) for key in grouped)
    data: list[list[float]] = []
    labels: list[str] = []

    for mesh_size in mesh_sizes:
        values = [value for run in grouped[mesh_size] if (value := detector_settling(run, detector)) is not None]
        if not values:
            continue
        data.append(values)
        labels.append(str(mesh_size))

    if not data:
        raise ValueError("No successful runs remain for dist-vs-mesh plot after filtering")

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.boxplot(data, tick_labels=labels, showfliers=True)
    bucket_label = f", bucket={bucket_size:g}s" if bucket_size is not None else ""
    ax.set_title(f"Settling Time Distribution by Mesh Size ({detector}{bucket_label})")
    ax.set_xlabel("Mesh Size")
    ax.set_ylabel("Settling Time [s]")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def plot_bucket_compare(
    runs: list[dict[str, Any]],
    detector: str,
    stat: str,
    mesh_size: int | None,
    output: Path,
) -> None:
    mesh_groups = group_by_key(runs, "mesh_size")
    selected_mesh_sizes = [mesh_size] if mesh_size is not None else sorted(int(key) for key in mesh_groups)
    if not selected_mesh_sizes:
        raise ValueError("No runs remain for bucket-compare plot after filtering")

    fig, axes = plt.subplots(
        nrows=len(selected_mesh_sizes),
        ncols=2,
        figsize=(12, 4 * len(selected_mesh_sizes)),
        squeeze=False,
    )

    for row_index, current_mesh_size in enumerate(selected_mesh_sizes):
        mesh_runs = mesh_groups.get(current_mesh_size, [])
        if not mesh_runs:
            raise ValueError(f"No runs found for mesh size {current_mesh_size}")
        bucket_groups = group_by_key(mesh_runs, "bucket_size_seconds")
        bucket_sizes = sorted(float(key) for key in bucket_groups)

        x_values: list[float] = []
        settle_values: list[float] = []
        lower_err: list[float] = []
        upper_err: list[float] = []
        success_rates: list[float] = []

        for bucket_size in bucket_sizes:
            summary = summarize_detector(bucket_groups[bucket_size], detector)
            center = choose_summary_value(summary, stat)
            errs = choose_yerr(summary, stat)
            x_values.append(bucket_size)
            success_rates.append(summary["success_rate"])
            if center is None or errs is None:
                settle_values.append(np.nan)
                lower_err.append(0.0)
                upper_err.append(0.0)
            else:
                settle_values.append(center)
                lower_err.append(errs[0])
                upper_err.append(errs[1])

        settle_ax = axes[row_index][0]
        settle_ax.errorbar(
            x_values,
            settle_values,
            yerr=np.array([lower_err, upper_err]),
            marker="o",
            linewidth=2,
            capsize=4,
        )
        settle_ax.set_title(f"Mesh {current_mesh_size}: Settling vs Bucket Size ({detector}, {stat})")
        settle_ax.set_xlabel("Bucket Size [s]")
        settle_ax.set_ylabel("Settling Time [s]")
        settle_ax.grid(True, axis="y", alpha=0.3)

        success_ax = axes[row_index][1]
        success_ax.plot(x_values, success_rates, marker="o", linewidth=2)
        success_ax.set_ylim(0.0, 1.05)
        success_ax.set_title(f"Mesh {current_mesh_size}: Success Rate vs Bucket Size ({detector})")
        success_ax.set_xlabel("Bucket Size [s]")
        success_ax.set_ylabel("Success Rate")
        success_ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    runs = load_runs(Path(args.input))

    if args.plot in ("settle-vs-mesh", "dist-vs-mesh"):
        runs = filter_runs(runs, bucket_size=args.bucket_size)
    elif args.plot == "bucket-compare":
        runs = filter_runs(runs, mesh_size=args.mesh_size)

    if not runs:
        raise ValueError("No runs remain after applying the requested filters")

    if args.plot == "settle-vs-mesh":
        plot_settle_vs_mesh(runs, args.detector, args.stat, args.bucket_size, output)
    elif args.plot == "dist-vs-mesh":
        plot_dist_vs_mesh(runs, args.detector, args.bucket_size, output)
    else:
        plot_bucket_compare(runs, args.detector, args.stat, args.mesh_size, output)


if __name__ == "__main__":
    main()
