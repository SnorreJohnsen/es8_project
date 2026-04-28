#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run steady-state detection and generate the standard settle-time plots for a result directory."
    )
    parser.add_argument("results_root", help="Directory containing <mesh-size>/plot/<node>/<bucket-size>_bucket/bucket.csv")
    parser.add_argument(
        "--output-dir",
        help="Directory for the aggregate JSON and plots. Defaults to <results_root>/detection_results",
    )
    parser.add_argument(
        "--summary-name",
        default="settle_summary_local_stability.json",
        help="Filename for the aggregate JSON inside the output directory",
    )
    parser.add_argument(
        "--detector",
        default="local_stability",
        help="Detector name to plot from the generated summary",
    )
    parser.add_argument(
        "--include-legacy-detectors",
        action="store_true",
        help="Also run legacy detectors in the aggregate JSON. Plots still use --detector.",
    )
    parser.add_argument("--python", default=sys.executable, help="Python executable to use for child scripts")
    return parser.parse_args()


def run(cmd: list[str], *, stdout_path: Path | None = None) -> None:
    print(" ".join(cmd), flush=True)
    if stdout_path is None:
        subprocess.run(cmd, check=True)
        return
    with stdout_path.open("w") as handle:
        subprocess.run(cmd, check=True, stdout=handle)


def load_summary(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def sorted_float_keys(keys: list[str]) -> list[float]:
    return sorted(float(key) for key in keys)


def sorted_int_keys(keys: list[str]) -> list[int]:
    return sorted(int(key) for key in keys)


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    detect_script = script_dir / "detect_steady_state.py"
    plot_script = script_dir / "plot_settle_stats.py"

    results_root = Path(args.results_root).expanduser().resolve()
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else results_root / "detection_results"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_path = output_dir / args.summary_name
    detect_cmd = [
        args.python,
        str(detect_script),
        "--batch-root",
        str(results_root),
    ]
    if args.include_legacy_detectors:
        detect_cmd.append("--include-legacy-detectors")
    run(detect_cmd, stdout_path=summary_path)

    summary = load_summary(summary_path)
    grouped = summary.get("grouped", {})
    bucket_sizes = sorted_float_keys(list(grouped.get("by_bucket_size", {}).keys()))
    mesh_sizes = sorted_int_keys(list(grouped.get("by_mesh_size", {}).keys()))

    for bucket_size in bucket_sizes:
        bucket_label = str(bucket_size).replace(".", "p")
        run(
            [
                args.python,
                str(plot_script),
                "--input",
                str(summary_path),
                "--plot",
                "settle-vs-mesh",
                "--bucket-size",
                str(bucket_size),
                "--detector",
                args.detector,
                "--output",
                str(output_dir / f"settle_vs_mesh_bucket_{bucket_label}.png"),
            ]
        )
        run(
            [
                args.python,
                str(plot_script),
                "--input",
                str(summary_path),
                "--plot",
                "dist-vs-mesh",
                "--bucket-size",
                str(bucket_size),
                "--detector",
                args.detector,
                "--output",
                str(output_dir / f"dist_vs_mesh_bucket_{bucket_label}.png"),
            ]
        )

    run(
        [
            args.python,
            str(plot_script),
            "--input",
            str(summary_path),
            "--plot",
            "bucket-compare",
            "--detector",
            args.detector,
            "--output",
            str(output_dir / "bucket_compare_all_meshes.png"),
        ]
    )

    for mesh_size in mesh_sizes:
        run(
            [
                args.python,
                str(plot_script),
                "--input",
                str(summary_path),
                "--plot",
                "bucket-compare",
                "--mesh-size",
                str(mesh_size),
                "--detector",
                args.detector,
                "--output",
                str(output_dir / f"bucket_compare_mesh_{mesh_size}.png"),
            ]
        )

    print(f"Wrote summary and plots to {output_dir}", flush=True)


if __name__ == "__main__":
    main()
