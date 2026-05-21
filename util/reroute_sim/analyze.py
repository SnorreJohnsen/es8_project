#!/usr/bin/env python3

import argparse
import csv
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any


CSV_FIELDS = [
    "result_set",
    "run_name",
    "run_dir",
    "stream_id",
    "nsperf_header",
    "failed_node",
    "client",
    "server",
    "requested_bps",
    "planned_failure_time_s",
    "actual_failure_time_s",
    "failure_delay_s",
    "planned_active_time_s",
    "actual_active_time_s",
    "active_delay_s",
    "outage_duration_s",
    "slow_route_detected",
    "slow_route_sim_time_s",
    "failure_to_slow_route_s",
    "fast_route_detected",
    "fast_route_sim_time_s",
    "active_to_fast_route_s",
    "slow_threshold_bps",
    "fast_threshold_fraction",
    "fast_threshold_bps",
    "fast_sustain_seconds",
    "fast_sustain_intervals",
    "interval_seconds",
    "pre_failure_avg_received_bps",
    "dropout_avg_received_bps",
    "slow_route_avg_received_bps",
    "post_active_avg_received_bps",
    "pre_failure_interval_count",
    "dropout_interval_count",
    "slow_route_interval_count",
    "post_active_interval_count",
]

LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

LATEX_TABLE_COLUMNS = [
    "reroute_time",
    "min",
    "max",
    "mean",
    "p50",
]

LATEX_COLUMN_LABELS = {
    "reroute_time": "Reroute time",
    "min": "Min [s]",
    "max": "Max [s]",
    "mean": "Mean [s]",
    "p50": "p50 [s]",
}

LATEX_COLUMN_SPEC = "l | r r r r"
REROUTE_TIME_ROWS = [
    ("From failure", "failure_to_slow_route_s"),
    ("From reactivation", "active_to_fast_route_s"),
]


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def parse_bitrate_bps(value: str) -> float:
    text = str(value).strip().lower()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([kmgt]?)(?:bps|b/s)?", text)
    if match is None:
        raise ValueError(f"Unsupported bitrate value: {value!r}")

    amount = float(match.group(1))
    suffix = match.group(2)
    scale = {
        "": 1.0,
        "k": 1_000.0,
        "m": 1_000_000.0,
        "g": 1_000_000_000.0,
        "t": 1_000_000_000_000.0,
    }[suffix]
    return amount * scale


def event(entry: dict[str, Any]) -> dict[str, Any]:
    value = entry.get("event")
    if not isinstance(value, dict):
        raise ValueError(f"Schedule entry has no event object: {entry!r}")
    return value


def state_events(entries: list[dict[str, Any]], state: str) -> list[dict[str, Any]]:
    return [
        entry for entry in entries
        if str(event(entry).get("state", "")).upper() == state
        and event(entry).get("name")
    ]


def nsperf_events(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entry for entry in entries
        if "nsperf_header" in event(entry)
        and "client_name" in event(entry)
        and "server_name" in event(entry)
    ]


def one_event(entries: list[dict[str, Any]], description: str) -> dict[str, Any]:
    if len(entries) != 1:
        raise ValueError(f"Expected exactly one {description}, found {len(entries)}")
    return entries[0]


def event_time(entry: dict[str, Any]) -> float:
    return float(entry["time"])


def extract_schedule_events(sim_sched: dict[str, Any]) -> dict[str, Any]:
    sched_plan = sim_sched.get("sched_plan", [])
    sched_real = sim_sched.get("sched_real", [])
    if not isinstance(sched_plan, list) or not isinstance(sched_real, list):
        raise ValueError("sim_sched.json must contain list sched_plan and sched_real")
    if not sched_real:
        raise ValueError("sim_sched.json has empty sched_real; actual event times are unavailable")

    planned_down = one_event(state_events(sched_plan, "DOWN"), "planned DOWN event")
    planned_up = one_event(state_events(sched_plan, "UP"), "planned UP event")
    actual_down = one_event(state_events(sched_real, "DOWN"), "actual DOWN event")
    actual_up = one_event(state_events(sched_real, "UP"), "actual UP event")

    failed_node = str(event(actual_down)["name"])
    if str(event(actual_up)["name"]) != failed_node:
        raise ValueError(
            f"Actual DOWN node {failed_node!r} does not match actual UP node {event(actual_up)['name']!r}"
        )

    planned_nsperf = one_event(nsperf_events(sched_plan), "planned nsperf event")
    actual_nsperf = one_event(nsperf_events(sched_real), "actual nsperf event")

    return {
        "failed_node": failed_node,
        "planned_down": planned_down,
        "planned_up": planned_up,
        "actual_down": actual_down,
        "actual_up": actual_up,
        "planned_nsperf": planned_nsperf,
        "actual_nsperf": actual_nsperf,
    }


def interval_label(value: str) -> str:
    try:
        parsed = float(value)
    except ValueError:
        return value
    if parsed.is_integer():
        return str(int(parsed))
    return f"{parsed:g}"


def find_interval_json(run_dir: Path, interval: str, explicit_path: Path | None) -> Path:
    if explicit_path is not None:
        if not explicit_path.is_file():
            raise FileNotFoundError(f"Interval JSON not found: {explicit_path}")
        return explicit_path

    intervals_dir = run_dir / "nsperf" / "streams" / "intervals"
    label = interval_label(interval)
    matches = sorted(intervals_dir.glob(f"*_inter_{label}*.json"))
    if len(matches) != 1:
        found = ", ".join(path.name for path in matches[:5])
        extra = "" if len(matches) <= 5 else ", ..."
        raise ValueError(
            f"Expected exactly one {label}s interval JSON in {intervals_dir}, "
            f"found {len(matches)}: {found}{extra}"
        )
    return matches[0]


def stream_id_from_interval(path: Path) -> str:
    name = path.name
    match = re.match(r"(.+)_inter_[0-9]+(?:\.[0-9]+)?(?:_skip_[0-9]+ms)?\.json$", name)
    if match is None:
        return path.stem
    return match.group(1)


def latency_stat_ms(stats: Any, key: str) -> float | None:
    if not isinstance(stats, dict) or int(stats.get("count", 0)) <= 0:
        return None
    value = stats.get(key)
    if value is None:
        return None
    return float(value) / 1_000_000.0


def interval_rows(interval_data: dict[str, Any], nsperf_start_s: float) -> tuple[float, list[dict[str, Any]]]:
    intervals = interval_data.get("intervals")
    if not isinstance(intervals, dict):
        raise ValueError("nsperf interval analysis JSON does not contain an intervals object")

    interval_seconds = float(intervals["interval_seconds"])
    rows: list[dict[str, Any]] = []
    for window in intervals.get("windows", []):
        receive = window.get("receive_window", {})
        send = window.get("send_window", {})
        delivery = window.get("delivery_for_send_window", {})
        latency_stats = delivery.get("host_local_latency_estimate_ns")
        sim_start = nsperf_start_s + float(window["start_s"])
        sim_end = nsperf_start_s + float(window["end_s"])
        received_bps = receive.get("received_bps")
        generated_bps = send.get("generated_bps")
        rows.append({
            "index": int(window["index"]),
            "sim_start_s": sim_start,
            "sim_end_s": sim_end,
            "sim_mid_s": (sim_start + sim_end) / 2.0,
            "received_bps": 0.0 if received_bps is None else float(received_bps),
            "generated_bps": None if generated_bps is None else float(generated_bps),
            "received_bits": int(receive.get("received_bits", 0)),
            "received_valid": int(receive.get("received_valid", 0)),
            "lost_after_successful_send": int(
                delivery.get("lost_after_successful_send", 0)
            ),
            "latency_mean_ms": latency_stat_ms(latency_stats, "mean_ns"),
            "latency_p95_ms": latency_stat_ms(latency_stats, "p95_ns"),
        })

    if not rows:
        raise ValueError("nsperf interval analysis JSON contains no windows")

    return interval_seconds, rows


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["received_bps"]) for row in rows]
    if not values:
        return {
            "interval_count": 0,
            "avg_received_bps": None,
            "min_received_bps": None,
            "max_received_bps": None,
            "total_received_bits": 0,
        }

    return {
        "interval_count": len(values),
        "avg_received_bps": sum(values) / len(values),
        "min_received_bps": min(values),
        "max_received_bps": max(values),
        "total_received_bits": sum(int(row["received_bits"]) for row in rows),
    }


def find_slow_route(
    rows: list[dict[str, Any]],
    failure_time_s: float,
    threshold_bps: float,
) -> dict[str, Any]:
    for row in rows:
        if float(row["sim_start_s"]) < failure_time_s:
            continue
        if float(row["received_bps"]) > threshold_bps:
            detected_sim_time = float(row["sim_start_s"])
            return {
                "detected": True,
                "detected_sim_time_s": detected_sim_time,
                "failure_to_slow_route_s": detected_sim_time - failure_time_s,
                "window_start_index": int(row["index"]),
                "window_end_index": int(row["index"]),
                "threshold_bps": threshold_bps,
            }

    return {
        "detected": False,
        "detected_sim_time_s": None,
        "failure_to_slow_route_s": None,
        "window_start_index": None,
        "window_end_index": None,
        "threshold_bps": threshold_bps,
    }


def find_fast_route(
    rows: list[dict[str, Any]],
    active_time_s: float,
    threshold_bps: float,
    sustain_intervals: int,
) -> dict[str, Any]:
    candidates = [row for row in rows if float(row["sim_start_s"]) >= active_time_s]
    for idx in range(0, len(candidates) - sustain_intervals + 1):
        window = candidates[idx:idx + sustain_intervals]
        if all(float(row["received_bps"]) >= threshold_bps for row in window):
            detected_sim_time = float(window[0]["sim_start_s"])
            return {
                "detected": True,
                "detected_sim_time_s": detected_sim_time,
                "active_to_fast_route_s": detected_sim_time - active_time_s,
                "window_start_index": int(window[0]["index"]),
                "window_end_index": int(window[-1]["index"]),
                "threshold_bps": threshold_bps,
            }

    return {
        "detected": False,
        "detected_sim_time_s": None,
        "active_to_fast_route_s": None,
        "window_start_index": None,
        "window_end_index": None,
        "threshold_bps": threshold_bps,
    }


def throughput_summaries(
    rows: list[dict[str, Any]],
    failure_time_s: float,
    active_time_s: float,
    slow_route: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    slow_time = slow_route["detected_sim_time_s"]
    pre_failure = [row for row in rows if float(row["sim_mid_s"]) < failure_time_s]
    if slow_time is None:
        dropout = [
            row for row in rows
            if failure_time_s <= float(row["sim_mid_s"]) < active_time_s
        ]
        slow_rows: list[dict[str, Any]] = []
    else:
        dropout = [
            row for row in rows
            if failure_time_s <= float(row["sim_mid_s"]) < float(slow_time)
        ]
        slow_rows = [
            row for row in rows
            if float(slow_time) <= float(row["sim_mid_s"]) < active_time_s
        ]
    post_active = [row for row in rows if float(row["sim_mid_s"]) >= active_time_s]

    return {
        "pre_failure": summarize_rows(pre_failure),
        "dropout": summarize_rows(dropout),
        "slow_route": summarize_rows(slow_rows),
        "post_active": summarize_rows(post_active),
    }


def draw_event_markers(
    ax: Any,
    markers: list[tuple[float | None, str]],
    data_points: list[tuple[float, float]],
) -> None:
    from matplotlib.transforms import blended_transform_factory

    valid_markers = sorted(
        (float(xpos), label) for xpos, label in markers
        if xpos is not None
    )
    if not valid_markers:
        return

    for xpos, _label in valid_markers:
        ax.axvline(xpos, color="red", linestyle="--", linewidth=1.2, label="_nolegend_")

    xmin, xmax = ax.get_xlim()
    xspan = max(xmax - xmin, 1.0)
    close_threshold = xspan * 0.035
    x_offset = xspan * 0.012
    x_padding = xspan * 0.01
    data_window = max(xspan * 0.04, 2.0)
    ymin, ymax = ax.get_ylim()
    yspan = max(ymax - ymin, 1.0)
    lanes = [0.18, 0.32, 0.46, 0.60, 0.74, 0.88]
    transform = blended_transform_factory(ax.transData, ax.transAxes)

    selected: list[tuple[float, float]] = []
    for xpos, label in valid_markers:
        local_points = [
            max(0.0, min(1.0, (y - ymin) / yspan))
            for x, y in data_points
            if abs(x - xpos) <= data_window
        ]

        def lane_score(lane: float) -> float:
            if local_points:
                score = min(abs(lane - point) for point in local_points)
            else:
                score = 1.0
            for other_x, other_lane in selected:
                if abs(xpos - other_x) <= close_threshold and abs(lane - other_lane) < 0.001:
                    score -= 1.0
            return score

        y_text = max(lanes, key=lane_score)

        if xpos > xmin + xspan * 0.72:
            text_x = max(xpos - x_offset, xmin + x_padding)
            ha = "right"
        else:
            text_x = min(xpos + x_offset, xmax - x_padding)
            ha = "left"

        ax.annotate(
            label,
            xy=(xpos, y_text),
            xycoords=transform,
            xytext=(text_x, y_text),
            textcoords=transform,
            color="red",
            va="center",
            ha=ha,
            bbox={
                "boxstyle": "round,pad=0.18",
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.88,
            },
            arrowprops={
                "arrowstyle": "-",
                "color": "red",
                "linewidth": 0.8,
                "shrinkA": 0,
                "shrinkB": 0,
            },
            zorder=5,
        )
        selected.append((xpos, y_text))


def finite_points(times: list[float], values: list[float | None]) -> list[tuple[float, float]]:
    return [
        (time, float(value)) for time, value in zip(times, values)
        if value is not None and math.isfinite(float(value))
    ]


def plot_throughput(
    rows: list[dict[str, Any]],
    requested_bps: float,
    fast_threshold_bps: float,
    failure_time_s: float,
    active_time_s: float,
    slow_route: dict[str, Any],
    fast_route: dict[str, Any],
    output: Path,
) -> None:
    if "MPLCONFIGDIR" not in os.environ:
        mpl_config_dir = Path(tempfile.gettempdir()) / "meshsim-matplotlib"
        mpl_config_dir.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(mpl_config_dir)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    times = [float(row["sim_mid_s"]) for row in rows]
    received = [float(row["received_bps"]) for row in rows]

    output.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(times, received, marker="o", linewidth=1.2, markersize=3, label="Received bps")
    ax.axhline(requested_bps, color="black", linewidth=1.0, label="Requested throughput")
    ax.axhline(fast_threshold_bps, color="green", linestyle=":", linewidth=1.2, label="90% requested throughput")

    markers = [
        (failure_time_s, "Failure"),
        (slow_route["detected_sim_time_s"], "Slow route"),
        (active_time_s, "Active"),
        (fast_route["detected_sim_time_s"], "Fast route"),
    ]
    ymax = max([requested_bps, fast_threshold_bps, *received]) if received else requested_bps

    ax.set_xlabel("Simulation time [s]")
    ax.set_ylabel("Received throughput [bps]")
    ax.set_title("Reroute throughput")
    ax.grid(True, axis="y", alpha=0.3)
    ax.set_ylim(bottom=0, top=max(ymax * 1.18, requested_bps * 1.18))
    draw_event_markers(ax, markers, list(zip(times, received)))
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def plot_throughput_latency(
    rows: list[dict[str, Any]],
    requested_bps: float,
    fast_threshold_bps: float,
    failure_time_s: float,
    active_time_s: float,
    slow_route: dict[str, Any],
    fast_route: dict[str, Any],
    output: Path,
) -> None:
    if "MPLCONFIGDIR" not in os.environ:
        mpl_config_dir = Path(tempfile.gettempdir()) / "meshsim-matplotlib"
        mpl_config_dir.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(mpl_config_dir)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    times = [float(row["sim_mid_s"]) for row in rows]
    received = [float(row["received_bps"]) for row in rows]
    latency_mean = [
        None if row["latency_mean_ms"] is None else float(row["latency_mean_ms"])
        for row in rows
    ]
    latency_p95 = [
        None if row["latency_p95_ms"] is None else float(row["latency_p95_ms"])
        for row in rows
    ]
    latency_mean_plot = [
        math.nan if value is None else value for value in latency_mean
    ]
    latency_p95_plot = [
        math.nan if value is None else value for value in latency_p95
    ]

    markers = [
        (failure_time_s, "Failure"),
        (slow_route["detected_sim_time_s"], "Slow route"),
        (active_time_s, "Active"),
        (fast_route["detected_sim_time_s"], "Fast route"),
    ]

    output.parent.mkdir(parents=True, exist_ok=True)
    fig, (ax_throughput, ax_latency) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ax_throughput.plot(times, received, marker="o", linewidth=1.2, markersize=3, label="Received bps")
    ax_throughput.axhline(requested_bps, color="black", linewidth=1.0, label="Requested throughput")
    ax_throughput.axhline(
        fast_threshold_bps,
        color="green",
        linestyle=":",
        linewidth=1.2,
        label="90% requested throughput",
    )
    throughput_ymax = max([requested_bps, fast_threshold_bps, *received]) if received else requested_bps
    ax_throughput.set_xlabel("Simulation time [s]")
    ax_throughput.set_ylabel("Received throughput [bps]")
    ax_throughput.set_title("Reroute throughput")
    ax_throughput.grid(True, axis="y", alpha=0.3)
    ax_throughput.set_ylim(bottom=0, top=max(throughput_ymax * 1.18, requested_bps * 1.18))
    draw_event_markers(ax_throughput, markers, list(zip(times, received)))
    ax_throughput.legend(loc="best")

    ax_latency.plot(
        times,
        latency_mean_plot,
        marker="o",
        linewidth=1.2,
        markersize=3,
        label="Mean send-window latency",
    )
    ax_latency.plot(
        times,
        latency_p95_plot,
        marker="o",
        linewidth=1.2,
        markersize=3,
        label="p95 send-window latency",
    )
    latency_values = [
        value for value in [*latency_mean, *latency_p95]
        if value is not None and math.isfinite(float(value))
    ]
    latency_ymax = max(latency_values) if latency_values else 1.0
    ax_latency.set_xlabel("Simulation time [s]")
    ax_latency.set_ylabel("Latency by send window [ms]")
    ax_latency.set_title("Reroute send-window latency")
    ax_latency.grid(True, axis="y", alpha=0.3)
    ax_latency.set_ylim(bottom=0, top=max(latency_ymax * 1.18, 1.0))
    draw_event_markers(
        ax_latency,
        markers,
        [
            *finite_points(times, latency_mean),
            *finite_points(times, latency_p95),
        ],
    )
    ax_latency.legend(loc="best")

    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    return value


def latex_escape(value: Any) -> str:
    return "".join(LATEX_SPECIAL_CHARS.get(char, char) for char in str(value))


def latex_bold(value: Any) -> str:
    return f"\\textbf{{{latex_escape(value)}}}"


def latex_header_label(key: str) -> str:
    return latex_bold(LATEX_COLUMN_LABELS.get(key, key))


def parse_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def percentile_50(values: list[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def reroute_time_stats(rows: list[dict[str, Any]], field: str) -> dict[str, float | None]:
    values = [
        parsed for parsed in (parse_optional_float(row.get(field)) for row in rows)
        if parsed is not None
    ]
    if not values:
        return {
            "min": None,
            "max": None,
            "mean": None,
            "p50": None,
        }
    return {
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
        "p50": percentile_50(values),
    }


def latex_table_value(field: str, row: dict[str, Any]) -> str:
    if field == "reroute_time":
        return latex_escape(row[field])
    value = row.get(field)
    if value is None:
        return ""
    return f"{float(value):.1f}"


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_latex_table(path: Path, aggregate_rows: list[dict[str, Any]]) -> None:
    table_rows = []
    for label, field in REROUTE_TIME_ROWS:
        row = {"reroute_time": label}
        row.update(reroute_time_stats(aggregate_rows, field))
        table_rows.append(row)

    output = [
        f"\\begin{{tabular}}{{{LATEX_COLUMN_SPEC}}}",
        "\\rowcolor{gray!30}",
        " & ".join(latex_header_label(field) for field in LATEX_TABLE_COLUMNS) + r" \\",
        "\\midrule",
    ]
    for index, row in enumerate(table_rows):
        if index % 2 == 1:
            output.append(r"\rowcolor{gray!10}")
        output.append(
            " & ".join(latex_table_value(field, row) for field in LATEX_TABLE_COLUMNS)
            + r" \\"
        )
    output.extend([r"\bottomrule", r"\end{tabular}"])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def upsert_csv(path: Path, row: dict[str, Any], key_fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if path.exists():
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames == CSV_FIELDS:
                key = tuple(str(row[field]) for field in key_fields)
                rows = [
                    existing for existing in reader
                    if tuple(str(existing.get(field, "")) for field in key_fields) != key
                ]

    rows.append({field: csv_value(row.get(field)) for field in CSV_FIELDS})
    rows = sorted(rows, key=lambda item: (
        str(item.get("result_set", "")),
        str(item.get("run_name", "")),
        str(item.get("run_dir", "")),
    ))

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def infer_labels(run_dir: Path, args: argparse.Namespace) -> tuple[str, str]:
    result_set = args.result_set
    run_name = args.run_name

    if result_set is None and run_dir.parent != run_dir:
        result_set = run_dir.parent.name
    if run_name is None:
        run_name = run_dir.name

    return result_set or "", run_name or ""


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = args.run_dir
    sim_sched = load_json(run_dir / "sim_sched.json")
    events = extract_schedule_events(sim_sched)

    planned_failure_time = event_time(events["planned_down"])
    planned_active_time = event_time(events["planned_up"])
    actual_failure_time = event_time(events["actual_down"])
    actual_active_time = event_time(events["actual_up"])
    nsperf_start_time = event_time(events["actual_nsperf"])
    nsperf_event = event(events["actual_nsperf"])

    requested_bps = parse_bitrate_bps(nsperf_event["bitrate"])
    interval_json = find_interval_json(run_dir, args.interval, args.interval_json)
    interval_data = load_json(interval_json)
    interval_seconds, rows = interval_rows(interval_data, nsperf_start_time)

    fast_threshold_bps = requested_bps * args.fast_threshold_fraction
    fast_sustain_intervals = max(1, math.ceil(args.fast_sustain_seconds / interval_seconds))
    slow_route = find_slow_route(
        rows=rows,
        failure_time_s=actual_failure_time,
        threshold_bps=args.slow_threshold_bps,
    )
    fast_route = find_fast_route(
        rows=rows,
        active_time_s=actual_active_time,
        threshold_bps=fast_threshold_bps,
        sustain_intervals=fast_sustain_intervals,
    )
    summaries = throughput_summaries(rows, actual_failure_time, actual_active_time, slow_route)
    result_set, run_name = infer_labels(run_dir, args)

    summary = {
        "schema": "reroute-analysis-v1",
        "result_set": result_set,
        "run_name": run_name,
        "run_dir": str(run_dir),
        "interval_json": str(interval_json),
        "stream_id": stream_id_from_interval(interval_json),
        "failed_node": events["failed_node"],
        "client": nsperf_event["client_name"],
        "server": nsperf_event["server_name"],
        "nsperf_header": nsperf_event["nsperf_header"],
        "requested_bitrate": nsperf_event["bitrate"],
        "requested_bps": requested_bps,
        "slow_threshold_bps": args.slow_threshold_bps,
        "fast_threshold_fraction": args.fast_threshold_fraction,
        "fast_threshold_bps": fast_threshold_bps,
        "fast_sustain_seconds": args.fast_sustain_seconds,
        "fast_sustain_intervals": fast_sustain_intervals,
        "interval_seconds": interval_seconds,
        "planned": {
            "failure_time_s": planned_failure_time,
            "active_time_s": planned_active_time,
            "nsperf_start_time_s": event_time(events["planned_nsperf"]),
        },
        "actual": {
            "failure_time_s": actual_failure_time,
            "active_time_s": actual_active_time,
            "nsperf_start_time_s": nsperf_start_time,
            "failure_delay_s": actual_failure_time - planned_failure_time,
            "active_delay_s": actual_active_time - planned_active_time,
            "outage_duration_s": actual_active_time - actual_failure_time,
        },
        "slow_route": slow_route,
        "fast_route": fast_route,
        "throughput": summaries,
    }

    write_json(run_dir / "reroute_summary.json", summary)
    plot_throughput(
        rows=rows,
        requested_bps=requested_bps,
        fast_threshold_bps=fast_threshold_bps,
        failure_time_s=actual_failure_time,
        active_time_s=actual_active_time,
        slow_route=slow_route,
        fast_route=fast_route,
        output=run_dir / "reroute_throughput.png",
    )
    plot_throughput_latency(
        rows=rows,
        requested_bps=requested_bps,
        fast_threshold_bps=fast_threshold_bps,
        failure_time_s=actual_failure_time,
        active_time_s=actual_active_time,
        slow_route=slow_route,
        fast_route=fast_route,
        output=run_dir / "reroute_throughput_latency.png",
    )

    if args.aggregate_csv is not None:
        row = {
            "result_set": result_set,
            "run_name": run_name,
            "run_dir": str(run_dir),
            "stream_id": stream_id_from_interval(interval_json),
            "nsperf_header": nsperf_event["nsperf_header"],
            "failed_node": events["failed_node"],
            "client": nsperf_event["client_name"],
            "server": nsperf_event["server_name"],
            "requested_bps": requested_bps,
            "planned_failure_time_s": planned_failure_time,
            "actual_failure_time_s": actual_failure_time,
            "failure_delay_s": actual_failure_time - planned_failure_time,
            "planned_active_time_s": planned_active_time,
            "actual_active_time_s": actual_active_time,
            "active_delay_s": actual_active_time - planned_active_time,
            "outage_duration_s": actual_active_time - actual_failure_time,
            "slow_route_detected": slow_route["detected"],
            "slow_route_sim_time_s": slow_route["detected_sim_time_s"],
            "failure_to_slow_route_s": slow_route["failure_to_slow_route_s"],
            "fast_route_detected": fast_route["detected"],
            "fast_route_sim_time_s": fast_route["detected_sim_time_s"],
            "active_to_fast_route_s": fast_route["active_to_fast_route_s"],
            "slow_threshold_bps": args.slow_threshold_bps,
            "fast_threshold_fraction": args.fast_threshold_fraction,
            "fast_threshold_bps": fast_threshold_bps,
            "fast_sustain_seconds": args.fast_sustain_seconds,
            "fast_sustain_intervals": fast_sustain_intervals,
            "interval_seconds": interval_seconds,
            "pre_failure_avg_received_bps": summaries["pre_failure"]["avg_received_bps"],
            "dropout_avg_received_bps": summaries["dropout"]["avg_received_bps"],
            "slow_route_avg_received_bps": summaries["slow_route"]["avg_received_bps"],
            "post_active_avg_received_bps": summaries["post_active"]["avg_received_bps"],
            "pre_failure_interval_count": summaries["pre_failure"]["interval_count"],
            "dropout_interval_count": summaries["dropout"]["interval_count"],
            "slow_route_interval_count": summaries["slow_route"]["interval_count"],
            "post_active_interval_count": summaries["post_active"]["interval_count"],
        }
        upsert_csv(args.aggregate_csv, row, ["run_dir"])
        if args.latex_output is not None:
            write_latex_table(args.latex_output, read_csv_rows(args.aggregate_csv))

    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path, help="Finalized reroute result directory")
    ap.add_argument("--aggregate-csv", type=Path, help="Aggregate CSV path to upsert")
    ap.add_argument("--latex-output", type=Path, help="Output LaTeX tabular path")
    ap.add_argument("--result-set", help="Result set label for aggregate output")
    ap.add_argument("--run-name", help="Run label for aggregate output")
    ap.add_argument("--interval", default="0.5", help="nsperf interval seconds to use")
    ap.add_argument("--interval-json", type=Path, help="Explicit nsperf interval JSON path")
    ap.add_argument(
        "--slow-threshold-bps",
        type=float,
        default=0.0,
        help="Slow-route detection requires received_bps greater than this value",
    )
    ap.add_argument(
        "--fast-threshold-fraction",
        type=float,
        default=0.90,
        help="Fast-route detection threshold as a fraction of requested bitrate",
    )
    ap.add_argument(
        "--fast-sustain-seconds",
        type=float,
        default=2.0,
        help="Required sustained duration above fast-route threshold",
    )
    args = ap.parse_args()

    if args.slow_threshold_bps < 0:
        raise ValueError("--slow-threshold-bps must be >= 0")
    if args.fast_threshold_fraction < 0:
        raise ValueError("--fast-threshold-fraction must be >= 0")
    if args.fast_sustain_seconds <= 0:
        raise ValueError("--fast-sustain-seconds must be > 0")
    if args.latex_output is not None and args.aggregate_csv is None:
        raise ValueError("--latex-output requires --aggregate-csv")

    analyze(args)


if __name__ == "__main__":
    main()
