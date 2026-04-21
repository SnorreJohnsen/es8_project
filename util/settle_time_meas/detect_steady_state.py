#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


TIME_COLUMN_CANDIDATES = (
    "time_s",
    "time",
    "timestamp",
    "bucket_time",
    "bucket_start",
    "start_time",
    "t",
)

BITS_COLUMN_CANDIDATES = (
    "bits",
    "tx_bits",
    "transmitted_bits",
    "bucket_bits",
    "txbits",
)


@dataclass
class WindowFeature:
    window_index: int
    start_idx: int
    end_idx: int
    start_time: float
    end_time: float
    mean: float
    median: float
    zero_fraction: float
    subblock_count: int
    spread_mad: float
    spread_rel: float
    trend_rel: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect outage, recovery, and post-outage steady-state onset from a bucketed TX-bits CSV."
    )
    parser.add_argument("bucket_csv", nargs="?", help="Path to bucket.csv")
    parser.add_argument(
        "--batch-root",
        help="Walk a settle_time_meas root and analyze all matching bucket.csv files under <mesh-size>/plot/<node>/<bucket-size>_bucket/bucket.csv",
    )
    parser.add_argument(
        "--bucket-size-filter",
        type=float,
        help="In batch mode, only include runs whose parsed bucket size matches this value",
    )
    parser.add_argument("--time-column", help="Override inferred time column")
    parser.add_argument("--bits-column", help="Override inferred bits column")
    parser.add_argument("--window-s", type=float, default=3.0, help="Analysis window duration in seconds")
    parser.add_argument("--step-s", type=float, default=1.0, help="Window step in seconds")
    parser.add_argument(
        "--min-suffix-s",
        type=float,
        default=10.0,
        help="Minimum suffix duration in seconds required to accept a steady-state candidate",
    )
    parser.add_argument(
        "--mean-rel-tol",
        type=float,
        default=0.20,
        help="Allowed relative mean difference between windows",
    )
    parser.add_argument(
        "--std-rel-tol",
        type=float,
        default=0.30,
        help="Allowed absolute difference between robust relative spread scores",
    )
    parser.add_argument(
        "--trend-tol",
        type=float,
        default=0.0,
        help="Allowed relative trend score. Non-positive enables auto scaling.",
    )
    parser.add_argument(
        "--zero-frac-tol",
        type=float,
        default=None,
        help="Allowed fraction of zero buckets in a steady-state window. Defaults to an auto-scaled value based on bucket size.",
    )
    parser.add_argument(
        "--match-fraction-threshold",
        type=float,
        default=0.80,
        help="Required matching fraction for prototype detector and local-pass fractions for cohesion detector",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Include full window features and candidate-evaluation diagnostics in the JSON output",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Emit only the core timestamps, detector outputs, and warnings",
    )
    args = parser.parse_args()
    if args.batch_root is None and args.bucket_csv is None:
        parser.error("Provide either bucket_csv or --batch-root")
    if args.batch_root is not None and args.bucket_csv is not None:
        parser.error("Use either bucket_csv or --batch-root, not both")
    return args


def base_result(csv_path: str) -> dict[str, Any]:
    return {
        "bucket_csv": csv_path,
        "time_column": None,
        "bits_column": None,
        "bucket_size_seconds": None,
        "warnings": [],
        "parameters": {},
        "outage": {
            "start_idx": None,
            "end_idx": None,
            "start_time": None,
            "end_time": None,
            "length_buckets": None,
            "length_seconds": None,
        },
        "recovery": {
            "first_nonzero_after_outage_idx": None,
            "first_nonzero_after_outage_time": None,
        },
        "windowing": {
            "analysis_start_idx": None,
            "analysis_start_time": None,
            "analysis_points": None,
            "window_n": None,
            "step_n": None,
            "window_duration_seconds_actual": None,
            "step_duration_seconds_actual": None,
            "min_suffix_windows": None,
            "num_windows": 0,
            "windows": [],
        },
        "prototype_matching": detector_result_template(),
        "suffix_cohesion": detector_result_template(),
    }


def configured_parameters(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "window_s": args.window_s,
        "step_s": args.step_s,
        "min_suffix_s": args.min_suffix_s,
        "mean_rel_tol": args.mean_rel_tol,
        "std_rel_tol": args.std_rel_tol,
        "trend_tol": args.trend_tol,
        "zero_frac_tol": args.zero_frac_tol,
        "match_fraction_threshold": args.match_fraction_threshold,
    }


def detector_result_template() -> dict[str, Any]:
    return {
        "steady_state_start_idx": None,
        "steady_state_start_time": None,
        "settling_time_seconds": None,
        "accepted_candidate_window_index": None,
        "selected_metrics": None,
        "candidate_evaluations": [],
    }


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.array(values, dtype=float), q))


def summarize_values(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
        }
    array = np.array(values, dtype=float)
    return {
        "mean": float(np.mean(array)),
        "median": float(np.median(array)),
        "std": float(np.std(array)),
        "min": float(np.min(array)),
        "max": float(np.max(array)),
        "p10": percentile(values, 10),
        "p25": percentile(values, 25),
        "p75": percentile(values, 75),
        "p90": percentile(values, 90),
    }


def to_builtin(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: to_builtin(val) for key, val in value.items()}
    if isinstance(value, list):
        return [to_builtin(item) for item in value]
    if isinstance(value, tuple):
        return [to_builtin(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def infer_column(
    df: pd.DataFrame,
    override: str | None,
    candidates: tuple[str, ...],
    label: str,
    warnings: list[str],
    *,
    monotonic_time: bool = False,
    exclude: set[str] | None = None,
) -> str:
    exclude = exclude or set()
    columns = list(df.columns)
    if override:
        if override not in df.columns:
            raise ValueError(f"Requested {label} column '{override}' was not found in CSV")
        return override

    lower_map = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate in lower_map and lower_map[candidate] not in exclude:
            return lower_map[candidate]

    numeric_columns: list[str] = []
    for column in columns:
        if column in exclude:
            continue
        numeric_series = pd.to_numeric(df[column], errors="coerce")
        if numeric_series.notna().all():
            numeric_columns.append(column)

    if monotonic_time:
        for column in numeric_columns:
            values = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
            diffs = np.diff(values)
            if len(values) > 1 and np.all(diffs >= 0) and np.any(diffs > 0):
                warnings.append(
                    f"Inferred time column '{column}' because it is numeric and nondecreasing."
                )
                return column
    else:
        if numeric_columns:
            warnings.append(
                f"Inferred {label} column '{numeric_columns[0]}' because no preferred column name was found."
            )
            return numeric_columns[0]

    raise ValueError(f"Could not infer {label} column from CSV")


def infer_bucket_size_seconds(times: np.ndarray, warnings: list[str]) -> float:
    if len(times) < 2:
        raise ValueError("Need at least two rows to infer bucket size")

    diffs = np.diff(times)
    positive_diffs = diffs[diffs > 0]
    if len(positive_diffs) == 0:
        raise ValueError("Could not infer bucket size because timestamps do not increase")

    bucket_size = float(np.median(positive_diffs))
    max_deviation = float(np.max(np.abs(positive_diffs - bucket_size)))
    tolerance = max(1e-9, bucket_size * 1e-3)
    if max_deviation > tolerance:
        warnings.append(
            "Timestamp spacing is not perfectly uniform; inferred bucket size from the median positive timestamp difference."
        )
    return bucket_size


def contiguous_true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    run_start: int | None = None
    for index, value in enumerate(mask):
        if value and run_start is None:
            run_start = index
        elif not value and run_start is not None:
            runs.append((run_start, index - 1))
            run_start = None
    if run_start is not None:
        runs.append((run_start, len(mask) - 1))
    return runs


def ceil_to_buckets(seconds: float, bucket_size_seconds: float, minimum: int) -> int:
    if seconds <= 0:
        return minimum
    return max(minimum, int(math.ceil(seconds / bucket_size_seconds)))


def relative_difference(a: float, b: float, scale_floor: float = 1.0) -> float:
    scale = max(abs(a), abs(b), scale_floor)
    return abs(a - b) / scale


def compute_subblock_means(values: np.ndarray, subblock_n: int) -> np.ndarray:
    means: list[float] = []
    for start_idx in range(0, len(values), subblock_n):
        block = values[start_idx : start_idx + subblock_n]
        if len(block) == 0:
            continue
        means.append(float(np.mean(block)))
    return np.array(means, dtype=float)


def compute_spread_mad(values: np.ndarray) -> float:
    if len(values) == 0:
        return 0.0
    median = float(np.median(values))
    return float(np.median(np.abs(values - median)))


def compute_trend_rel(values: np.ndarray, window_mean: float) -> float:
    if len(values) < 2:
        return 0.0
    half = len(values) // 2
    if half == 0:
        return 0.0
    first = values[:half]
    second = values[-half:]
    first_mean = float(np.mean(first))
    second_mean = float(np.mean(second))
    return abs(second_mean - first_mean) / max(abs(window_mean), 1.0)


def build_windows(
    times: np.ndarray,
    bits: np.ndarray,
    recovery_start_idx: int,
    window_n: int,
    step_n: int,
    subblock_n: int,
) -> list[WindowFeature]:
    windows: list[WindowFeature] = []
    window_index = 0
    for start_idx in range(recovery_start_idx, len(bits) - window_n + 1, step_n):
        end_idx = start_idx + window_n - 1
        segment = bits[start_idx : end_idx + 1]
        window_mean = float(np.mean(segment))
        subblock_means = compute_subblock_means(segment, subblock_n)
        spread_mad = compute_spread_mad(subblock_means)
        spread_rel = spread_mad / max(abs(window_mean), 1.0)
        windows.append(
            WindowFeature(
                window_index=window_index,
                start_idx=start_idx,
                end_idx=end_idx,
                start_time=float(times[start_idx]),
                end_time=float(times[end_idx]),
                mean=window_mean,
                median=float(np.median(segment)),
                zero_fraction=float(np.mean(segment == 0)),
                subblock_count=int(len(subblock_means)),
                spread_mad=spread_mad,
                spread_rel=float(spread_rel),
                trend_rel=float(compute_trend_rel(subblock_means, window_mean)),
            )
        )
        window_index += 1
    return windows


def auto_trend_tolerance(mean_rel_tol: float) -> float:
    return max(0.1, mean_rel_tol)


def auto_zero_fraction_tolerance(bucket_size_seconds: float) -> float:
    # Smaller bucket sizes naturally produce sparser occupancy, so tolerate
    # a higher zero fraction there. At 1.0 s buckets this falls to 0.0.
    return min(0.95, max(0.0, 1.0 - bucket_size_seconds))


def serialize_windows(windows: list[WindowFeature]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for window in windows:
        serialized.append(
            {
                "window_index": window.window_index,
                "start_idx": window.start_idx,
                "end_idx": window.end_idx,
                "start_time": window.start_time,
                "end_time": window.end_time,
                "mean": window.mean,
                "median": window.median,
                "zero_fraction": window.zero_fraction,
                "subblock_count": window.subblock_count,
                "spread_mad": window.spread_mad,
                "spread_rel": window.spread_rel,
                "trend_rel": window.trend_rel,
            }
        )
    return serialized


def evaluate_prototype_matching(
    windows: list[WindowFeature],
    min_suffix_windows: int,
    mean_rel_tol: float,
    std_rel_tol: float,
    trend_tol: float,
    zero_frac_tol: float,
    match_fraction_threshold: float,
    recovery_start_time: float,
) -> dict[str, Any]:
    result = detector_result_template()

    for candidate_index, prototype in enumerate(windows):
        suffix = windows[candidate_index:]
        prototype_ok = (
            prototype.zero_fraction <= zero_frac_tol and prototype.trend_rel <= trend_tol
        )
        match_details: list[dict[str, Any]] = []

        for other in suffix:
            mean_diff = relative_difference(prototype.mean, other.mean)
            spread_diff = abs(prototype.spread_rel - other.spread_rel)
            mean_ok = mean_diff <= mean_rel_tol
            spread_ok = spread_diff <= std_rel_tol
            zero_ok = other.zero_fraction <= zero_frac_tol
            trend_ok = other.trend_rel <= trend_tol
            matched = prototype_ok and mean_ok and spread_ok and zero_ok and trend_ok
            match_details.append(
                {
                    "window_index": other.window_index,
                    "mean_rel_diff": mean_diff,
                    "spread_rel_diff": spread_diff,
                    "mean_ok": mean_ok,
                    "spread_ok": spread_ok,
                    "zero_ok": zero_ok,
                    "trend_ok": trend_ok,
                    "matched": matched,
                }
            )

        match_fraction = float(np.mean([detail["matched"] for detail in match_details]))
        enough_suffix = len(suffix) >= min_suffix_windows
        accepted = enough_suffix and match_fraction >= match_fraction_threshold and prototype_ok

        evaluation = {
            "candidate_window_index": prototype.window_index,
            "candidate_start_idx": prototype.start_idx,
            "candidate_start_time": prototype.start_time,
            "suffix_window_count": len(suffix),
            "enough_suffix": enough_suffix,
            "prototype_ok": prototype_ok,
            "match_fraction": match_fraction,
            "accepted": accepted,
            "match_details": match_details,
        }
        result["candidate_evaluations"].append(evaluation)

        if accepted and result["steady_state_start_time"] is None:
            result["steady_state_start_idx"] = prototype.start_idx
            result["steady_state_start_time"] = prototype.start_time
            result["settling_time_seconds"] = prototype.start_time - recovery_start_time
            result["accepted_candidate_window_index"] = prototype.window_index
            result["selected_metrics"] = {
                "match_fraction": match_fraction,
                "suffix_window_count": len(suffix),
                "prototype_ok": prototype_ok,
            }
            break

    return result


def evaluate_suffix_cohesion(
    windows: list[WindowFeature],
    min_suffix_windows: int,
    mean_rel_tol: float,
    std_rel_tol: float,
    trend_tol: float,
    zero_frac_tol: float,
    match_fraction_threshold: float,
    recovery_start_time: float,
) -> dict[str, Any]:
    result = detector_result_template()

    for candidate_index, candidate in enumerate(windows):
        suffix = windows[candidate_index:]
        enough_suffix = len(suffix) >= min_suffix_windows

        means = np.array([window.mean for window in suffix], dtype=float)
        spread_rels = np.array([window.spread_rel for window in suffix], dtype=float)
        zero_fracs = np.array([window.zero_fraction for window in suffix], dtype=float)
        trend_rels = np.array([window.trend_rel for window in suffix], dtype=float)

        mean_center = float(np.median(means)) if len(means) else 0.0
        spread_center = float(np.median(spread_rels)) if len(spread_rels) else 0.0

        mean_rel_devs = (
            np.abs(means - mean_center) / max(abs(mean_center), 1.0) if len(means) else np.array([])
        )
        spread_rel_devs = (
            np.abs(spread_rels - spread_center) if len(spread_rels) else np.array([])
        )

        mean_spread_rel = float(np.max(mean_rel_devs)) if len(mean_rel_devs) else math.inf
        spread_spread_rel = float(np.max(spread_rel_devs)) if len(spread_rel_devs) else math.inf
        mean_ok_fraction = float(np.mean(mean_rel_devs <= mean_rel_tol)) if len(mean_rel_devs) else 0.0
        spread_ok_fraction = float(np.mean(spread_rel_devs <= std_rel_tol)) if len(spread_rel_devs) else 0.0
        zero_ok_fraction = float(np.mean(zero_fracs <= zero_frac_tol)) if len(zero_fracs) else 0.0
        trend_ok_fraction = float(np.mean(trend_rels <= trend_tol)) if len(trend_rels) else 0.0
        candidate_ok = candidate.zero_fraction <= zero_frac_tol and candidate.trend_rel <= trend_tol

        accepted = (
            enough_suffix
            and candidate_ok
            and mean_ok_fraction >= match_fraction_threshold
            and spread_ok_fraction >= match_fraction_threshold
            and zero_ok_fraction >= match_fraction_threshold
            and trend_ok_fraction >= match_fraction_threshold
        )

        evaluation = {
            "candidate_window_index": candidate.window_index,
            "candidate_start_idx": candidate.start_idx,
            "candidate_start_time": candidate.start_time,
            "suffix_window_count": len(suffix),
            "enough_suffix": enough_suffix,
            "candidate_ok": candidate_ok,
            "mean_center": mean_center,
            "spread_center": spread_center,
            "mean_ok_fraction": mean_ok_fraction,
            "spread_ok_fraction": spread_ok_fraction,
            "mean_spread_rel": mean_spread_rel,
            "spread_spread_rel": spread_spread_rel,
            "zero_ok_fraction": zero_ok_fraction,
            "trend_ok_fraction": trend_ok_fraction,
            "accepted": accepted,
        }
        result["candidate_evaluations"].append(evaluation)

        if accepted and result["steady_state_start_time"] is None:
            result["steady_state_start_idx"] = candidate.start_idx
            result["steady_state_start_time"] = candidate.start_time
            result["settling_time_seconds"] = candidate.start_time - recovery_start_time
            result["accepted_candidate_window_index"] = candidate.window_index
            result["selected_metrics"] = {
                "mean_center": mean_center,
                "spread_center": spread_center,
                "mean_ok_fraction": mean_ok_fraction,
                "spread_ok_fraction": spread_ok_fraction,
                "mean_spread_rel": mean_spread_rel,
                "spread_spread_rel": spread_spread_rel,
                "zero_ok_fraction": zero_ok_fraction,
                "trend_ok_fraction": trend_ok_fraction,
                "suffix_window_count": len(suffix),
                "candidate_ok": candidate_ok,
            }
            break

    return result


def analyze(args: argparse.Namespace, csv_path_override: str | None = None) -> dict[str, Any]:
    csv_path_str = csv_path_override if csv_path_override is not None else args.bucket_csv
    result = base_result(str(csv_path_str))
    warnings = result["warnings"]

    csv_path = Path(str(csv_path_str))
    if not csv_path.is_file():
        warnings.append(f"CSV file not found: {csv_path}")
        return result

    df = pd.read_csv(csv_path)
    if df.empty:
        warnings.append("CSV is empty")
        return result

    time_column = infer_column(
        df,
        args.time_column,
        TIME_COLUMN_CANDIDATES,
        "time",
        warnings,
        monotonic_time=True,
    )
    bits_column = infer_column(
        df,
        args.bits_column,
        BITS_COLUMN_CANDIDATES,
        "bits",
        warnings,
        exclude={time_column},
    )
    result["time_column"] = time_column
    result["bits_column"] = bits_column

    reduced = df[[time_column, bits_column]].copy()
    reduced[time_column] = pd.to_numeric(reduced[time_column], errors="coerce")
    reduced[bits_column] = pd.to_numeric(reduced[bits_column], errors="coerce")
    reduced = reduced.dropna(subset=[time_column, bits_column])
    if reduced.empty:
        warnings.append("No rows remained after numeric conversion of time/bits columns")
        return result

    if not reduced[time_column].is_monotonic_increasing:
        warnings.append("Input rows were not sorted by time; sorted rows before analysis.")
        reduced = reduced.sort_values(time_column, kind="mergesort")

    times = reduced[time_column].to_numpy(dtype=float)
    bits = reduced[bits_column].to_numpy(dtype=float)

    bucket_size_seconds = infer_bucket_size_seconds(times, warnings)
    result["bucket_size_seconds"] = bucket_size_seconds

    zero_runs = contiguous_true_runs(bits == 0)
    if not zero_runs:
        warnings.append("No zero-valued outage run was found in the bucket signal")
        return result

    outage_start_idx, outage_end_idx = max(
        zero_runs, key=lambda run: run[1] - run[0] + 1
    )
    outage_length_buckets = outage_end_idx - outage_start_idx + 1
    outage_length_seconds = outage_length_buckets * bucket_size_seconds
    result["outage"] = {
        "start_idx": outage_start_idx,
        "end_idx": outage_end_idx,
        "start_time": float(times[outage_start_idx]),
        "end_time": float(times[outage_end_idx]),
        "length_buckets": outage_length_buckets,
        "length_seconds": outage_length_seconds,
    }

    recovery_start_idx: int | None = None
    for index in range(outage_end_idx + 1, len(bits)):
        if bits[index] > 0:
            recovery_start_idx = index
            break

    if recovery_start_idx is None:
        warnings.append("No post-outage nonzero bucket was found after the main zero run")
        return result

    recovery_start_time = float(times[recovery_start_idx])
    result["recovery"] = {
        "first_nonzero_after_outage_idx": recovery_start_idx,
        "first_nonzero_after_outage_time": recovery_start_time,
    }

    window_n = ceil_to_buckets(args.window_s, bucket_size_seconds, minimum=2)
    step_n = ceil_to_buckets(args.step_s, bucket_size_seconds, minimum=1)
    subblock_s = min(1.0, args.window_s / 3.0)
    subblock_n = ceil_to_buckets(subblock_s, bucket_size_seconds, minimum=1)
    window_duration_seconds_actual = window_n * bucket_size_seconds
    step_duration_seconds_actual = step_n * bucket_size_seconds
    min_suffix_windows = max(
        1, int(math.ceil(args.min_suffix_s / max(step_duration_seconds_actual, bucket_size_seconds)))
    )

    windows = build_windows(times, bits, recovery_start_idx, window_n, step_n, subblock_n)
    result["windowing"] = {
        "analysis_start_idx": recovery_start_idx,
        "analysis_start_time": recovery_start_time,
        "analysis_points": len(bits) - recovery_start_idx,
        "window_n": window_n,
        "step_n": step_n,
        "subblock_n": subblock_n,
        "subblock_duration_seconds_actual": subblock_n * bucket_size_seconds,
        "window_duration_seconds_actual": window_duration_seconds_actual,
        "step_duration_seconds_actual": step_duration_seconds_actual,
        "min_suffix_windows": min_suffix_windows,
        "num_windows": len(windows),
        "windows": serialize_windows(windows),
    }

    trend_tol_used = (
        args.trend_tol
        if args.trend_tol > 0
        else auto_trend_tolerance(args.mean_rel_tol)
    )
    zero_frac_tol_used = (
        args.zero_frac_tol
        if args.zero_frac_tol is not None
        else auto_zero_fraction_tolerance(bucket_size_seconds)
    )

    result["parameters"] = {
        "window_s": args.window_s,
        "step_s": args.step_s,
        "min_suffix_s": args.min_suffix_s,
        "mean_rel_tol": args.mean_rel_tol,
        "std_rel_tol": args.std_rel_tol,
        "trend_tol": args.trend_tol,
        "trend_tol_used": trend_tol_used,
        "zero_frac_tol": args.zero_frac_tol,
        "zero_frac_tol_used": zero_frac_tol_used,
        "match_fraction_threshold": args.match_fraction_threshold,
    }

    post_recovery_duration = (len(bits) - recovery_start_idx) * bucket_size_seconds
    if len(windows) == 0:
        warnings.append("Not enough post-recovery data to construct a single analysis window")
        return result
    if len(windows) < min_suffix_windows:
        warnings.append(
            "Not enough post-recovery windows to satisfy the minimum suffix duration requirement"
        )
    if post_recovery_duration < max(args.min_suffix_s, window_duration_seconds_actual):
        warnings.append(
            "Post-recovery capture duration is short relative to the configured window/minimum suffix durations"
        )

    result["prototype_matching"] = evaluate_prototype_matching(
        windows=windows,
        min_suffix_windows=min_suffix_windows,
        mean_rel_tol=args.mean_rel_tol,
        std_rel_tol=args.std_rel_tol,
        trend_tol=trend_tol_used,
        zero_frac_tol=zero_frac_tol_used,
        match_fraction_threshold=args.match_fraction_threshold,
        recovery_start_time=recovery_start_time,
    )

    result["suffix_cohesion"] = evaluate_suffix_cohesion(
        windows=windows,
        min_suffix_windows=min_suffix_windows,
        mean_rel_tol=args.mean_rel_tol,
        std_rel_tol=args.std_rel_tol,
        trend_tol=trend_tol_used,
        zero_frac_tol=zero_frac_tol_used,
        match_fraction_threshold=args.match_fraction_threshold,
        recovery_start_time=recovery_start_time,
    )

    if result["prototype_matching"]["steady_state_start_time"] is None:
        warnings.append("Prototype-matching detector did not find a steady-state onset")
    if result["suffix_cohesion"]["steady_state_start_time"] is None:
        warnings.append("Suffix-cohesion detector did not find a steady-state onset")

    return result


def parse_batch_path(batch_root: Path, csv_path: Path) -> dict[str, Any] | None:
    try:
        rel = csv_path.relative_to(batch_root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) != 5:
        return None
    mesh_part, plot_part, node_name, bucket_dir, file_name = parts
    if plot_part != "plot" or file_name != "bucket.csv" or not bucket_dir.endswith("_bucket"):
        return None
    bucket_text = bucket_dir[: -len("_bucket")]
    try:
        bucket_size_seconds = float(bucket_text)
    except ValueError:
        return None
    mesh_size: int | str
    try:
        mesh_size = int(mesh_part)
    except ValueError:
        mesh_size = mesh_part
    return {
        "mesh_size": mesh_size,
        "node_name": node_name,
        "bucket_size_seconds": bucket_size_seconds,
        "bucket_csv": str(csv_path),
    }


def detector_summary_from_result(result: dict[str, Any], detector_key: str) -> dict[str, Any]:
    detector = result[detector_key]
    return {
        "steady_state_start_time": detector["steady_state_start_time"],
        "settling_time_seconds": detector["settling_time_seconds"],
    }


def run_record_from_result(path_info: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "mesh_size": path_info["mesh_size"],
        "node_name": path_info["node_name"],
        "bucket_size_seconds": path_info["bucket_size_seconds"],
        "bucket_csv": path_info["bucket_csv"],
        "outage_start_time": result["outage"]["start_time"],
        "outage_end_time": result["outage"]["end_time"],
        "first_nonzero_after_outage_time": result["recovery"]["first_nonzero_after_outage_time"],
        "prototype_matching": detector_summary_from_result(result, "prototype_matching"),
        "suffix_cohesion": detector_summary_from_result(result, "suffix_cohesion"),
        "warnings": list(result["warnings"]),
    }


def detector_group_summary(runs: list[dict[str, Any]], detector_key: str) -> dict[str, Any]:
    values = [
        float(run[detector_key]["settling_time_seconds"])
        for run in runs
        if run[detector_key]["settling_time_seconds"] is not None
    ]
    return {
        "n": len(runs),
        "success_n": len(values),
        "failure_n": len(runs) - len(values),
        "settling_time_seconds": summarize_values(values),
    }


def summarize_group(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(runs),
        "prototype_matching": detector_group_summary(runs, "prototype_matching"),
        "suffix_cohesion": detector_group_summary(runs, "suffix_cohesion"),
    }


def group_runs(runs: list[dict[str, Any]], key_fn: Any) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        key = str(key_fn(run))
        grouped.setdefault(key, []).append(run)
    return grouped


def build_grouped_summaries(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_mesh_groups = group_runs(runs, lambda run: run["mesh_size"])
    by_bucket_groups = group_runs(runs, lambda run: run["bucket_size_seconds"])

    by_mesh_size = {
        key: summarize_group(group_runs_list) for key, group_runs_list in sorted(by_mesh_groups.items())
    }
    by_bucket_size = {
        key: summarize_group(group_runs_list) for key, group_runs_list in sorted(by_bucket_groups.items())
    }

    mesh_bucket_groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for run in runs:
        mesh_key = str(run["mesh_size"])
        bucket_key = str(run["bucket_size_seconds"])
        mesh_bucket_groups.setdefault(mesh_key, {}).setdefault(bucket_key, []).append(run)

    by_mesh_size_and_bucket_size: dict[str, Any] = {}
    for mesh_key in sorted(mesh_bucket_groups):
        by_mesh_size_and_bucket_size[mesh_key] = {
            bucket_key: summarize_group(mesh_bucket_groups[mesh_key][bucket_key])
            for bucket_key in sorted(mesh_bucket_groups[mesh_key])
        }

    return {
        "by_mesh_size": by_mesh_size,
        "by_bucket_size": by_bucket_size,
        "by_mesh_size_and_bucket_size": by_mesh_size_and_bucket_size,
    }


def analyze_batch(args: argparse.Namespace) -> dict[str, Any]:
    batch_root = Path(args.batch_root).expanduser().resolve()
    meta_warnings: list[str] = []
    runs: list[dict[str, Any]] = []
    batch_paths = sorted(batch_root.glob("*/plot/*/*_bucket/bucket.csv"))

    if not batch_root.is_dir():
        meta_warnings.append(f"Batch root not found or not a directory: {batch_root}")
    if not batch_paths:
        meta_warnings.append(f"No bucket.csv files matched under batch root: {batch_root}")

    for csv_path in batch_paths:
        path_info = parse_batch_path(batch_root, csv_path)
        if path_info is None:
            meta_warnings.append(f"Skipped path with unexpected layout: {csv_path}")
            continue
        if (
            args.bucket_size_filter is not None
            and not math.isclose(
                path_info["bucket_size_seconds"], args.bucket_size_filter, rel_tol=0.0, abs_tol=1e-9
            )
        ):
            continue

        try:
            result = analyze(args, str(csv_path))
        except Exception as exc:  # pragma: no cover - defensive batch path
            result = base_result(str(csv_path))
            result["warnings"].append(f"Unhandled analysis error: {exc}")
        runs.append(run_record_from_result(path_info, result))

    batch_result = {
        "meta": {
            "batch_root": str(batch_root),
            "path_scheme": "<root>/<mesh-size>/plot/<node-name>/<bucket-size>_bucket/bucket.csv",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "detector_version": "mvp1",
            "filters": {
                "bucket_size_filter_seconds": args.bucket_size_filter,
            },
            "detector_parameters": configured_parameters(args),
            "warnings": meta_warnings,
            "run_count": len(runs),
        },
        "runs": runs,
        "grouped": build_grouped_summaries(runs),
    }
    return batch_result


def prune_result_for_output(result: dict[str, Any], debug: bool, quick: bool) -> dict[str, Any]:
    if debug:
        return result
    if quick:
        return {
            "bucket_csv": result["bucket_csv"],
            "bucket_size_seconds": result["bucket_size_seconds"],
            "outage_start_time": result["outage"]["start_time"],
            "outage_end_time": result["outage"]["end_time"],
            "first_nonzero_after_outage_time": result["recovery"]["first_nonzero_after_outage_time"],
            "prototype_matching": {
                "steady_state_start_time": result["prototype_matching"]["steady_state_start_time"],
                "settling_time_seconds": result["prototype_matching"]["settling_time_seconds"],
            },
            "suffix_cohesion": {
                "steady_state_start_time": result["suffix_cohesion"]["steady_state_start_time"],
                "settling_time_seconds": result["suffix_cohesion"]["settling_time_seconds"],
            },
            "warnings": result["warnings"],
        }

    pruned = {
        "bucket_csv": result["bucket_csv"],
        "time_column": result["time_column"],
        "bits_column": result["bits_column"],
        "bucket_size_seconds": result["bucket_size_seconds"],
        "warnings": result["warnings"],
        "parameters": result["parameters"],
        "outage": result["outage"],
        "recovery": result["recovery"],
        "windowing": {
            "analysis_start_idx": result["windowing"]["analysis_start_idx"],
            "analysis_start_time": result["windowing"]["analysis_start_time"],
            "analysis_points": result["windowing"]["analysis_points"],
            "window_n": result["windowing"]["window_n"],
            "step_n": result["windowing"]["step_n"],
            "window_duration_seconds_actual": result["windowing"]["window_duration_seconds_actual"],
            "step_duration_seconds_actual": result["windowing"]["step_duration_seconds_actual"],
            "min_suffix_windows": result["windowing"]["min_suffix_windows"],
            "num_windows": result["windowing"]["num_windows"],
        },
        "prototype_matching": {
            "steady_state_start_idx": result["prototype_matching"]["steady_state_start_idx"],
            "steady_state_start_time": result["prototype_matching"]["steady_state_start_time"],
            "settling_time_seconds": result["prototype_matching"]["settling_time_seconds"],
            "accepted_candidate_window_index": result["prototype_matching"]["accepted_candidate_window_index"],
            "selected_metrics": result["prototype_matching"]["selected_metrics"],
        },
        "suffix_cohesion": {
            "steady_state_start_idx": result["suffix_cohesion"]["steady_state_start_idx"],
            "steady_state_start_time": result["suffix_cohesion"]["steady_state_start_time"],
            "settling_time_seconds": result["suffix_cohesion"]["settling_time_seconds"],
            "accepted_candidate_window_index": result["suffix_cohesion"]["accepted_candidate_window_index"],
            "selected_metrics": result["suffix_cohesion"]["selected_metrics"],
        },
    }
    return pruned


def main() -> None:
    args = parse_args()
    if args.batch_root is not None:
        cleaned = to_builtin(analyze_batch(args))
    else:
        try:
            result = analyze(args)
        except Exception as exc:  # pragma: no cover - defensive JSON output path
            result = base_result(str(args.bucket_csv))
            result["warnings"].append(f"Unhandled analysis error: {exc}")
        cleaned = to_builtin(prune_result_for_output(result, args.debug, args.quick))
    print(json.dumps(cleaned, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
