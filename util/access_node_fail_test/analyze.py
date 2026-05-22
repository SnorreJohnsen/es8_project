#!/usr/bin/env python3

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any


CSV_FIELDS = [
    "graph_name",
    "stream",
    "loss",
    "access_node",
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
    "settled",
    "settled_sim_time_s",
    "settle_time_s",
    "tolerance_fraction",
    "sustain_seconds",
    "sustain_intervals",
    "interval_seconds",
    "pre_drop_avg_received_bps",
    "outage_avg_received_bps",
    "post_active_avg_received_bps",
    "pre_drop_interval_count",
    "outage_interval_count",
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
    "access_node_fail_time",
    "min",
    "max",
    "mean",
    "p50",
]

LATEX_COLUMN_LABELS = {
    "access_node_fail_time": "Access-node fail time",
    "min": "Min [s]",
    "max": "Max [s]",
    "mean": "Mean [s]",
    "p50": "p50 [s]",
}

LATEX_COLUMN_SPEC = "l | r r r r"
ACCESS_NODE_FAIL_TIME_ROWS = [
    ("To recovery", "settle_time_s"),
]

PLOT_PALETTE = ["#4C72B0", "#DC1D33", "#16A944", "#D9D31C", "#E514D0"]
PLOT_FONT_SIZE = 22
TITLE_SCALE = 1.8
AXIS_VALUE_SCALE = 0.8


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


def one_event(entries: list[dict[str, Any]], description: str) -> dict[str, Any]:
    if len(entries) != 1:
        raise ValueError(f"Expected exactly one {description}, found {len(entries)}")
    return entries[0]


def nsperf_events(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entry for entry in entries
        if "nsperf_header" in event(entry)
        and "client_name" in event(entry)
        and "server_name" in event(entry)
    ]


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

    access_node = str(event(actual_down)["name"])
    if str(event(actual_up)["name"]) != access_node:
        raise ValueError(
            f"Actual DOWN node {access_node!r} does not match actual UP node {event(actual_up)['name']!r}"
        )

    planned_nsperf = one_event(nsperf_events(sched_plan), "planned nsperf event")
    actual_nsperf = one_event(nsperf_events(sched_real), "actual nsperf event")

    return {
        "access_node": access_node,
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
        "interval_count": len(rows),
        "avg_received_bps": sum(values) / len(values),
        "min_received_bps": min(values),
        "max_received_bps": max(values),
        "total_received_bits": sum(int(row["received_bits"]) for row in rows),
    }


def throughput_summaries(
    rows: list[dict[str, Any]],
    failure_time_s: float,
    active_time_s: float,
) -> dict[str, dict[str, Any]]:
    pre = [row for row in rows if float(row["sim_mid_s"]) < failure_time_s]
    outage = [
        row for row in rows
        if failure_time_s <= float(row["sim_mid_s"]) < active_time_s
    ]
    post = [row for row in rows if float(row["sim_mid_s"]) >= active_time_s]
    return {
        "pre_drop": summarize_rows(pre),
        "outage": summarize_rows(outage),
        "post_active": summarize_rows(post),
    }


def find_settle(
    rows: list[dict[str, Any]],
    active_time_s: float,
    requested_bps: float,
    tolerance_fraction: float,
    sustain_intervals: int,
) -> dict[str, Any]:
    lower = requested_bps * (1.0 - tolerance_fraction)
    upper = requested_bps * (1.0 + tolerance_fraction)
    candidates = [row for row in rows if float(row["sim_start_s"]) >= active_time_s]

    for idx in range(0, len(candidates) - sustain_intervals + 1):
        window = candidates[idx:idx + sustain_intervals]
        if all(lower <= float(row["received_bps"]) <= upper for row in window):
            settled_sim_time = float(window[0]["sim_start_s"])
            return {
                "settled": True,
                "settled_sim_time_s": settled_sim_time,
                "settle_time_s": settled_sim_time - active_time_s,
                "settle_window_start_index": int(window[0]["index"]),
                "settle_window_end_index": int(window[-1]["index"]),
                "lower_bps": lower,
                "upper_bps": upper,
            }

    return {
        "settled": False,
        "settled_sim_time_s": None,
        "settle_time_s": None,
        "settle_window_start_index": None,
        "settle_window_end_index": None,
        "lower_bps": lower,
        "upper_bps": upper,
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
    tolerance_fraction: float,
    failure_time_s: float,
    active_time_s: float,
    settle: dict[str, Any],
    output: Path,
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    times = [float(row["sim_mid_s"]) for row in rows]
    received = [float(row["received_bps"]) for row in rows]
    lower = requested_bps * (1.0 - tolerance_fraction)
    upper = requested_bps * (1.0 + tolerance_fraction)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(times, received, marker="o", linewidth=1.2, markersize=3, label="Received bps")
    ax.axhline(requested_bps, color="black", linewidth=1.0, label="Requested throughput")
    ax.axhspan(lower, upper, color="green", alpha=0.12, label="+-10% target band")

    markers = [
        (failure_time_s, "Failure"),
        (active_time_s, "Active"),
    ]
    if settle["settled_sim_time_s"] is not None:
        markers.append((float(settle["settled_sim_time_s"]), "Settled"))

    ymax = max([requested_bps, upper, *received]) if received else upper

    ax.set_xlabel("Simulation time [s]")
    ax.set_ylabel("Received throughput [bps]")
    ax.set_title("Access-node fail throughput recovery")
    ax.grid(True, axis="y", alpha=0.3)
    ax.set_ylim(bottom=0, top=max(ymax * 1.18, upper * 1.18))
    draw_event_markers(ax, markers, list(zip(times, received)))
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def plot_throughput_latency(
    rows: list[dict[str, Any]],
    requested_bps: float,
    tolerance_fraction: float,
    failure_time_s: float,
    active_time_s: float,
    settle: dict[str, Any],
    output: Path,
) -> None:
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
    lower = requested_bps * (1.0 - tolerance_fraction)
    upper = requested_bps * (1.0 + tolerance_fraction)

    markers = [
        (failure_time_s, "Failure"),
        (active_time_s, "Active"),
    ]
    if settle["settled_sim_time_s"] is not None:
        markers.append((float(settle["settled_sim_time_s"]), "Settled"))

    output.parent.mkdir(parents=True, exist_ok=True)
    fig, (ax_throughput, ax_latency) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ax_throughput.plot(times, received, marker="o", linewidth=1.2, markersize=3, label="Received bps")
    ax_throughput.axhline(requested_bps, color="black", linewidth=1.0, label="Requested throughput")
    ax_throughput.axhspan(lower, upper, color="green", alpha=0.12, label="+-10% target band")
    throughput_ymax = max([requested_bps, upper, *received]) if received else upper
    ax_throughput.set_xlabel("Simulation time [s]")
    ax_throughput.set_ylabel("Received throughput [bps]")
    ax_throughput.set_title("Access-node fail throughput recovery")
    ax_throughput.grid(True, axis="y", alpha=0.3)
    ax_throughput.set_ylim(bottom=0, top=max(throughput_ymax * 1.18, upper * 1.18))
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
    ax_latency.set_title("Access-node fail send-window latency")
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


def access_node_fail_time_stats(rows: list[dict[str, Any]], field: str) -> dict[str, float | None]:
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
    if field == "access_node_fail_time":
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
    for label, field in ACCESS_NODE_FAIL_TIME_ROWS:
        row = {"access_node_fail_time": label}
        row.update(access_node_fail_time_stats(aggregate_rows, field))
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


def mesh_size_from_graph_name(graph_name: str) -> int | None:
    match = re.search(r"_(\d+)_nodes$", graph_name)
    if match is None:
        return None
    return int(match.group(1))


def is_zero_loss(value: Any) -> bool:
    parsed = parse_optional_float(value)
    return parsed is not None and math.isclose(parsed, 0.0, abs_tol=1e-12)


def access_node_recovery_plot_rows(aggregate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plot_rows = []
    for row in aggregate_rows:
        if not is_zero_loss(row.get("loss")):
            continue
        mesh_size = mesh_size_from_graph_name(str(row.get("graph_name", "")))
        recovery_time = parse_optional_float(row.get("settle_time_s"))
        if mesh_size is None or recovery_time is None:
            continue
        plot_rows.append({
            "mesh_size": mesh_size,
            "recovery_time_s": recovery_time,
        })
    return plot_rows


def write_recovery_violin_plot(path: Path, aggregate_rows: list[dict[str, Any]]) -> None:
    plot_rows = access_node_recovery_plot_rows(aggregate_rows)
    if not plot_rows:
        raise ValueError("No loss 0 rows with graph mesh size and settle_time_s found for violin plot")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    try:
        import pandas as pd
        import seaborn as sns
    except ImportError as exc:
        raise RuntimeError(
            "--violin-output requires pandas and seaborn in the selected Python environment"
        ) from exc

    df = pd.DataFrame(plot_rows)
    mesh_order = sorted(df["mesh_size"].unique())

    fig, ax = plt.subplots(figsize=(16, 9))
    sns.violinplot(
        data=df,
        x="mesh_size",
        y="recovery_time_s",
        order=mesh_order,
        inner="quart",
        cut=0,
        linewidth=2.5,
        bw_method=.2,
        density_norm="width",
        color=PLOT_PALETTE[0],
        ax=ax,
    )
    for collection in ax.collections:
        collection.set_alpha(0.6)

    fig.suptitle("Access-node fail recovery time", fontsize=PLOT_FONT_SIZE * TITLE_SCALE, y=0.98)
    ax.set_xlabel("Mesh size", fontsize=PLOT_FONT_SIZE)
    ax.set_ylabel("Recovery time [s]", fontsize=PLOT_FONT_SIZE)
    ax.tick_params(axis="both", labelsize=PLOT_FONT_SIZE * AXIS_VALUE_SCALE)
    ax.grid(True, which="major", alpha=0.3)
    fig.tight_layout()

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    plt.close(fig)


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
        str(item.get("graph_name", "")),
        str(item.get("stream", "")),
        str(item.get("loss", "")),
    ))

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def infer_labels(run_dir: Path, args: argparse.Namespace) -> tuple[str, str, str]:
    graph_name = args.graph_name
    stream = args.stream
    loss = args.loss

    if loss is None:
        loss = run_dir.name
    if stream is None and run_dir.parent != run_dir:
        stream = run_dir.parent.name
    if graph_name is None and run_dir.parent.parent != run_dir.parent:
        graph_name = run_dir.parent.parent.name

    return graph_name or "", stream or "", loss or ""


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = args.run_dir
    sim_sched = load_json(run_dir / "sim_sched.json")
    events = extract_schedule_events(sim_sched)

    actual_failure_time = event_time(events["actual_down"])
    actual_active_time = event_time(events["actual_up"])
    planned_failure_time = event_time(events["planned_down"])
    planned_active_time = event_time(events["planned_up"])
    nsperf_start_time = event_time(events["actual_nsperf"])
    nsperf_event = event(events["actual_nsperf"])

    requested_bps = parse_bitrate_bps(nsperf_event["bitrate"])
    interval_json = find_interval_json(run_dir, args.interval, args.interval_json)
    interval_data = load_json(interval_json)
    interval_seconds, rows = interval_rows(interval_data, nsperf_start_time)
    sustain_intervals = max(1, math.ceil(args.sustain_seconds / interval_seconds))

    settle = find_settle(
        rows=rows,
        active_time_s=actual_active_time,
        requested_bps=requested_bps,
        tolerance_fraction=args.tolerance,
        sustain_intervals=sustain_intervals,
    )
    summaries = throughput_summaries(rows, actual_failure_time, actual_active_time)
    graph_name, stream, loss = infer_labels(run_dir, args)

    summary = {
        "schema": "access-node-fail-analysis-v1",
        "graph_name": graph_name,
        "stream": stream,
        "loss": loss,
        "run_dir": str(run_dir),
        "interval_json": str(interval_json),
        "access_node": events["access_node"],
        "client": nsperf_event["client_name"],
        "server": nsperf_event["server_name"],
        "nsperf_header": nsperf_event["nsperf_header"],
        "requested_bitrate": nsperf_event["bitrate"],
        "requested_bps": requested_bps,
        "tolerance_fraction": args.tolerance,
        "sustain_seconds": args.sustain_seconds,
        "sustain_intervals": sustain_intervals,
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
        "settle": settle,
        "throughput": summaries,
    }

    summary_path = run_dir / "access_node_fail_summary.json"
    write_json(summary_path, summary)
    plot_throughput(
        rows=rows,
        requested_bps=requested_bps,
        tolerance_fraction=args.tolerance,
        failure_time_s=actual_failure_time,
        active_time_s=actual_active_time,
        settle=settle,
        output=run_dir / "access_node_fail_throughput.png",
    )
    plot_throughput_latency(
        rows=rows,
        requested_bps=requested_bps,
        tolerance_fraction=args.tolerance,
        failure_time_s=actual_failure_time,
        active_time_s=actual_active_time,
        settle=settle,
        output=run_dir / "access_node_fail_throughput_latency.png",
    )

    if args.aggregate_csv is not None:
        row = {
            "graph_name": graph_name,
            "stream": stream,
            "loss": loss,
            "access_node": events["access_node"],
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
            "settled": settle["settled"],
            "settled_sim_time_s": settle["settled_sim_time_s"],
            "settle_time_s": settle["settle_time_s"],
            "tolerance_fraction": args.tolerance,
            "sustain_seconds": args.sustain_seconds,
            "sustain_intervals": sustain_intervals,
            "interval_seconds": interval_seconds,
            "pre_drop_avg_received_bps": summaries["pre_drop"]["avg_received_bps"],
            "outage_avg_received_bps": summaries["outage"]["avg_received_bps"],
            "post_active_avg_received_bps": summaries["post_active"]["avg_received_bps"],
            "pre_drop_interval_count": summaries["pre_drop"]["interval_count"],
            "outage_interval_count": summaries["outage"]["interval_count"],
            "post_active_interval_count": summaries["post_active"]["interval_count"],
        }
        upsert_csv(args.aggregate_csv, row, ["graph_name", "stream", "loss"])
        aggregate_rows = read_csv_rows(args.aggregate_csv)
        if args.latex_output is not None:
            write_latex_table(args.latex_output, aggregate_rows)
        if args.violin_output is not None:
            write_recovery_violin_plot(args.violin_output, aggregate_rows)

    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path, help="Finalized access-node fail result directory")
    ap.add_argument("--aggregate-csv", type=Path, help="Aggregate CSV path to upsert")
    ap.add_argument("--latex-output", type=Path, help="Output LaTeX tabular path")
    ap.add_argument("--violin-output", type=Path, help="Output recovery-time violin plot path")
    ap.add_argument("--graph-name", help="Graph name label for aggregate output")
    ap.add_argument("--stream", help="Stream label for aggregate output")
    ap.add_argument("--loss", help="Loss label for aggregate output")
    ap.add_argument("--interval", default="0.5", help="nsperf interval seconds to use")
    ap.add_argument("--interval-json", type=Path, help="Explicit nsperf interval JSON path")
    ap.add_argument("--tolerance", type=float, default=0.10, help="Settle tolerance fraction")
    ap.add_argument("--sustain-seconds", type=float, default=2.0, help="Required in-band duration")
    args = ap.parse_args()

    if args.tolerance < 0:
        raise ValueError("--tolerance must be >= 0")
    if args.sustain_seconds <= 0:
        raise ValueError("--sustain-seconds must be > 0")
    if args.latex_output is not None and args.aggregate_csv is None:
        raise ValueError("--latex-output requires --aggregate-csv")
    if args.violin_output is not None and args.aggregate_csv is None:
        raise ValueError("--violin-output requires --aggregate-csv")

    analyze(args)


if __name__ == "__main__":
    main()
