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


def interval_rows(interval_data: dict[str, Any], nsperf_start_s: float) -> tuple[float, list[dict[str, Any]]]:
    intervals = interval_data.get("intervals")
    if not isinstance(intervals, dict):
        raise ValueError("nsperf interval analysis JSON does not contain an intervals object")

    interval_seconds = float(intervals["interval_seconds"])
    rows: list[dict[str, Any]] = []
    for window in intervals.get("windows", []):
        receive = window.get("receive_window", {})
        send = window.get("send_window", {})
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
                window.get("delivery_for_send_window", {}).get("lost_after_successful_send", 0)
            ),
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
    for xpos, label in markers:
        ax.axvline(xpos, color="red", linestyle="--", linewidth=1.2, label=label)
        ax.text(xpos, ymax * 1.02, label, color="red", rotation=90, va="bottom", ha="center")

    ax.set_xlabel("Simulation time [s]")
    ax.set_ylabel("Received throughput [bps]")
    ax.set_title("Access-node fail throughput recovery")
    ax.grid(True, axis="y", alpha=0.3)
    ax.set_ylim(bottom=0, top=max(ymax * 1.18, upper * 1.18))
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    return value


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

    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path, help="Finalized access-node fail result directory")
    ap.add_argument("--aggregate-csv", type=Path, help="Aggregate CSV path to upsert")
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

    analyze(args)


if __name__ == "__main__":
    main()
