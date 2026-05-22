#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path
from typing import Any, Union


DEFAULT_BITRATES = ("100k", "500k", "1M", "2M", "5M")
DEFAULT_NUM_CONNS = (1, 2, 4, 6, 8, 10, 15, 20, 25, 30, 40)
DEFAULT_FAILURE_PROBABILITIES = (0.0, 0.005, 0.025, 0.04)
DEFAULT_REPLACEMENT_DELAYS = (15.0,)
DEFAULT_DROPOUT_TIME_STEPS = (5.0,)
DEFAULT_GRAPH_PATTERN = "Triangle_network_*_tolerance_*_datarate_Mbps_*_bandwidth_Mhz_*_nodes.json"

MESH_OVERHEAD_BY_DRONES = {
    18: 100.1,
    27: 141.1,
    38: 245.5,
    46: 386.1,
}

TRAFFIC_COEFF_S_PER_MBIT = 0.01803
DROPOUT_EVENT_COEFF_S = 0.35


def report(seconds: float) -> None:
    print(f"seconds={seconds}")
    print(f"minutes={seconds / 60}")
    print(f"hours={seconds / 3600}")
    print(f"days={seconds / (3600 * 24)}")


def parse_bitrate_mbps(value: Union[str, int, float]) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    s = value.strip().lower()
    if s.endswith("k"):
        return float(s[:-1]) / 1000
    if s.endswith("m"):
        return float(s[:-1])
    return float(s)


def parse_words(value: str) -> tuple[str, ...]:
    words = tuple(value.split())
    if not words:
        raise ValueError("value cannot be empty")
    return words


def parse_int_sequence(value: str) -> tuple[int, ...]:
    seq = tuple(int(item) for item in value.replace(",", " ").split())
    if not seq:
        raise ValueError("sequence cannot be empty")
    if any(item <= 0 for item in seq):
        raise ValueError("all sequence values must be > 0")
    return seq


def parse_float_sequence(value: str) -> tuple[float, ...]:
    seq = tuple(float(item) for item in value.replace(",", " ").split())
    if not seq:
        raise ValueError("sequence cannot be empty")
    return seq


def mesh_overhead_s(
    drones: int,
    mesh_overhead_by_drones: dict[int, float] = MESH_OVERHEAD_BY_DRONES,
) -> float:
    if drones <= 0:
        raise ValueError(f"drone count must be > 0, got {drones}")

    if drones in mesh_overhead_by_drones:
        return float(mesh_overhead_by_drones[drones])

    points = sorted((int(k), float(v)) for k, v in mesh_overhead_by_drones.items())
    if len(points) < 2:
        raise ValueError("at least two mesh overhead points are required")

    if drones < points[0][0]:
        lower, upper = points[0], points[1]
    elif drones > points[-1][0]:
        lower, upper = points[-2], points[-1]
    else:
        lower = points[0]
        upper = points[-1]
        for left, right in zip(points, points[1:]):
            if left[0] <= drones <= right[0]:
                lower, upper = left, right
                break

    x0, y0 = lower
    x1, y1 = upper
    return y0 + ((drones - x0) * (y1 - y0) / (x1 - x0))


def graph_drone_count(graph: Path) -> int:
    with graph.open(encoding="utf-8") as f:
        data = json.load(f)

    count = sum(
        1
        for node in data.get("nodes", [])
        if re.fullmatch(r"n[0-9]+", str(node.get("id")))
    )
    if count <= 0:
        raise ValueError(f"{graph} contains no drone nodes matching n<number>")
    return count


def resolve_graphs(graph_input: Path, graph_pattern: str) -> list[Path]:
    if graph_input.is_file():
        return [graph_input]
    if graph_input.is_dir():
        return sorted(path for path in graph_input.rglob(graph_pattern) if path.is_file())
    raise ValueError(f"Graph input does not exist: {graph_input}")


def traffic_mbit(
    bitrate_mbps: float,
    num_conns: int,
    sim_duration: float,
    start_time: float,
) -> float:
    stream_duration = sim_duration - start_time
    return bitrate_mbps * stream_duration * num_conns


def expected_dropout_events(
    drones: int,
    sim_duration: float,
    failure_probability: float,
    replacement_delay: float,
    dropout_time_step: float,
) -> float:
    if failure_probability <= 0:
        return 0.0

    expected_up_time = dropout_time_step / failure_probability
    expected_cycle_time = expected_up_time + replacement_delay
    expected_failures_per_drone = sim_duration / expected_cycle_time
    return expected_failures_per_drone * 2 * drones


def single_runtime_row(
    drones: int,
    bitrate: str,
    num_conns: int,
    failure_probability: float,
    replacement_delay: float,
    dropout_time_step: float,
    fixed: float = 60.0,
    sim_duration: float = 150.0,
    start_time: float = 10.0,
    mesh_overhead_by_drones: dict[int, float] = MESH_OVERHEAD_BY_DRONES,
    traffic_coeff_s_per_mbit: float = TRAFFIC_COEFF_S_PER_MBIT,
    dropout_event_coeff_s: float = DROPOUT_EVENT_COEFF_S,
) -> dict[str, Any]:
    if num_conns <= 0:
        raise ValueError(f"num_conns must be > 0, got {num_conns}")
    if failure_probability < 0 or failure_probability > 1:
        raise ValueError(f"failure_probability must be between 0 and 1, got {failure_probability}")
    if replacement_delay < 0:
        raise ValueError(f"replacement_delay must be >= 0, got {replacement_delay}")
    if dropout_time_step <= 0:
        raise ValueError(f"dropout_time_step must be > 0, got {dropout_time_step}")
    if sim_duration <= start_time:
        raise ValueError("sim_duration must be greater than start_time")
    if start_time < 0:
        raise ValueError(f"start_time must be >= 0, got {start_time}")

    bitrate_mbps = parse_bitrate_mbps(bitrate)
    traffic = traffic_mbit(
        bitrate_mbps=bitrate_mbps,
        num_conns=num_conns,
        sim_duration=sim_duration,
        start_time=start_time,
    )
    mesh_overhead = mesh_overhead_s(
        drones=drones,
        mesh_overhead_by_drones=mesh_overhead_by_drones,
    )
    traffic_overhead = traffic_coeff_s_per_mbit * traffic
    dropout_events = expected_dropout_events(
        drones=drones,
        sim_duration=sim_duration,
        failure_probability=failure_probability,
        replacement_delay=replacement_delay,
        dropout_time_step=dropout_time_step,
    )
    dropout_overhead = dropout_events * dropout_event_coeff_s
    single_runtime = fixed + sim_duration + mesh_overhead + traffic_overhead + dropout_overhead

    return {
        "drones": drones,
        "bitrate": bitrate,
        "bitrate_mbps": bitrate_mbps,
        "num_conns": num_conns,
        "failure_probability": failure_probability,
        "replacement_delay": replacement_delay,
        "dropout_time_step": dropout_time_step,
        "traffic_mbit": traffic,
        "fixed_s": fixed,
        "scheduled_s": sim_duration,
        "mesh_overhead_s": mesh_overhead,
        "traffic_overhead_s": traffic_overhead,
        "expected_dropout_events": dropout_events,
        "dropout_overhead_s": dropout_overhead,
        "single_runtime_s": single_runtime,
    }


def runtime_rows(
    num_drones: Union[int, tuple[int, ...]] = (18, 27, 38, 46),
    bitrates: tuple[str, ...] = DEFAULT_BITRATES,
    num_conns_values: tuple[int, ...] = DEFAULT_NUM_CONNS,
    failure_probabilities: tuple[float, ...] = DEFAULT_FAILURE_PROBABILITIES,
    replacement_delays: tuple[float, ...] = DEFAULT_REPLACEMENT_DELAYS,
    dropout_time_steps: tuple[float, ...] = DEFAULT_DROPOUT_TIME_STEPS,
    num_loss: int = 1,
    num_iters: int = 10,
    fixed: float = 60.0,
    sim_duration: float = 150.0,
    start_time: float = 10.0,
    mesh_overhead_by_drones: dict[int, float] = MESH_OVERHEAD_BY_DRONES,
    traffic_coeff_s_per_mbit: float = TRAFFIC_COEFF_S_PER_MBIT,
    dropout_event_coeff_s: float = DROPOUT_EVENT_COEFF_S,
) -> list[dict[str, Any]]:
    if isinstance(num_drones, int):
        num_drones = (num_drones,)

    rows = []
    runs = num_loss * num_iters
    for drones in num_drones:
        for bitrate in bitrates:
            for num_conns in num_conns_values:
                for failure_probability in failure_probabilities:
                    for replacement_delay in replacement_delays:
                        for dropout_time_step in dropout_time_steps:
                            row = single_runtime_row(
                                drones=drones,
                                bitrate=bitrate,
                                num_conns=num_conns,
                                failure_probability=failure_probability,
                                replacement_delay=replacement_delay,
                                dropout_time_step=dropout_time_step,
                                fixed=fixed,
                                sim_duration=sim_duration,
                                start_time=start_time,
                                mesh_overhead_by_drones=mesh_overhead_by_drones,
                                traffic_coeff_s_per_mbit=traffic_coeff_s_per_mbit,
                                dropout_event_coeff_s=dropout_event_coeff_s,
                            )
                            row["runs"] = runs
                            row["subtotal_s"] = row["single_runtime_s"] * runs
                            rows.append(row)

    return rows


def runtime(
    num_drones: Union[int, tuple[int, ...]] = (18, 27, 38, 46),
    bitrates: tuple[str, ...] = DEFAULT_BITRATES,
    num_conns_values: tuple[int, ...] = DEFAULT_NUM_CONNS,
    failure_probabilities: tuple[float, ...] = DEFAULT_FAILURE_PROBABILITIES,
    replacement_delays: tuple[float, ...] = DEFAULT_REPLACEMENT_DELAYS,
    dropout_time_steps: tuple[float, ...] = DEFAULT_DROPOUT_TIME_STEPS,
    num_loss: int = 1,
    num_iters: int = 10,
    fixed: float = 60.0,
    sim_duration: float = 150.0,
    start_time: float = 10.0,
    mesh_overhead_by_drones: dict[int, float] = MESH_OVERHEAD_BY_DRONES,
    traffic_coeff_s_per_mbit: float = TRAFFIC_COEFF_S_PER_MBIT,
    dropout_event_coeff_s: float = DROPOUT_EVENT_COEFF_S,
    dump: bool = True,
) -> float:
    rows = runtime_rows(
        num_drones=num_drones,
        bitrates=bitrates,
        num_conns_values=num_conns_values,
        failure_probabilities=failure_probabilities,
        replacement_delays=replacement_delays,
        dropout_time_steps=dropout_time_steps,
        num_loss=num_loss,
        num_iters=num_iters,
        fixed=fixed,
        sim_duration=sim_duration,
        start_time=start_time,
        mesh_overhead_by_drones=mesh_overhead_by_drones,
        traffic_coeff_s_per_mbit=traffic_coeff_s_per_mbit,
        dropout_event_coeff_s=dropout_event_coeff_s,
    )
    total = sum(row["subtotal_s"] for row in rows)

    if dump:
        print_report(
            rows=rows,
            total=total,
            num_drones=(num_drones,) if isinstance(num_drones, int) else num_drones,
            bitrates=bitrates,
            num_conns_values=num_conns_values,
            failure_probabilities=failure_probabilities,
            replacement_delays=replacement_delays,
            dropout_time_steps=dropout_time_steps,
            num_loss=num_loss,
            num_iters=num_iters,
            fixed=fixed,
            sim_duration=sim_duration,
            start_time=start_time,
            mesh_overhead_by_drones=mesh_overhead_by_drones,
            traffic_coeff_s_per_mbit=traffic_coeff_s_per_mbit,
            dropout_event_coeff_s=dropout_event_coeff_s,
        )

    return total


def print_report(
    rows: list[dict[str, Any]],
    total: float,
    num_drones: tuple[int, ...],
    bitrates: tuple[str, ...],
    num_conns_values: tuple[int, ...],
    failure_probabilities: tuple[float, ...],
    replacement_delays: tuple[float, ...],
    dropout_time_steps: tuple[float, ...],
    num_loss: int,
    num_iters: int,
    fixed: float,
    sim_duration: float,
    start_time: float,
    mesh_overhead_by_drones: dict[int, float],
    traffic_coeff_s_per_mbit: float,
    dropout_event_coeff_s: float,
) -> None:
    print("=== inputs ===")
    print(f"num_drones={num_drones}")
    print(f"bitrates={bitrates}")
    print(f"num_conns={num_conns_values}")
    print(f"failure_probabilities={failure_probabilities}")
    print(f"replacement_delays={replacement_delays}")
    print(f"dropout_time_steps={dropout_time_steps}")
    print(f"num_loss={num_loss}")
    print(f"num_iters={num_iters}")
    print(f"fixed={fixed}")
    print(f"sim_duration={sim_duration}")
    print(f"start_time={start_time}")
    print()

    print("=== model ===")
    print(f"mesh_overhead_by_drones={mesh_overhead_by_drones}")
    print(f"traffic_coeff_s_per_mbit={traffic_coeff_s_per_mbit}")
    print(f"dropout_event_coeff_s={dropout_event_coeff_s}")
    print()

    print("=== per case ===")
    if len(rows) > 80:
        print(f"{len(rows)} rows omitted from human output; use --output json for details")
    else:
        for row in rows:
            print(
                f"{row['drones']} drones, {row['bitrate']}, "
                f"{row['num_conns']} conns, p={row['failure_probability']}, "
                f"delay={row['replacement_delay']}, step={row['dropout_time_step']}: "
                f"single={row['single_runtime_s']:.1f}s "
                f"({row['single_runtime_s'] / 60:.2f} min), "
                f"runs={row['runs']}, subtotal={row['subtotal_s']:.1f}s "
                f"({row['subtotal_s'] / 3600:.2f} h)"
            )
    print()

    print("=== total ===")
    report(total)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph-input", type=Path, help="Graph file or directory to inspect")
    ap.add_argument("--graph-pattern", default=DEFAULT_GRAPH_PATTERN)
    ap.add_argument("--graph", action="append", type=Path, default=[])
    ap.add_argument("--num-drones", action="append", type=int, default=[])
    ap.add_argument("--bitrates", default=" ".join(DEFAULT_BITRATES))
    ap.add_argument("--bitrate", action="append", default=[])
    ap.add_argument("--num-conns", default=" ".join(str(value) for value in DEFAULT_NUM_CONNS))
    ap.add_argument("--num-conn", action="append", type=int, default=[])
    ap.add_argument(
        "--failure-probabilities",
        default=" ".join(str(value) for value in DEFAULT_FAILURE_PROBABILITIES),
    )
    ap.add_argument("--failure-probability", action="append", type=float, default=[])
    ap.add_argument(
        "--replacement-delays",
        default=" ".join(str(value) for value in DEFAULT_REPLACEMENT_DELAYS),
    )
    ap.add_argument("--replacement-delay", action="append", type=float, default=[])
    ap.add_argument(
        "--dropout-time-steps",
        default=" ".join(str(value) for value in DEFAULT_DROPOUT_TIME_STEPS),
    )
    ap.add_argument("--dropout-time-step", action="append", type=float, default=[])
    ap.add_argument("--num-loss", type=int, default=1)
    ap.add_argument("--num-iters", type=int, default=10)
    ap.add_argument("--fixed", type=float, default=60.0)
    ap.add_argument("--sim-duration", type=float, default=150.0)
    ap.add_argument("--start-time", type=float, default=10.0)
    ap.add_argument("--dropout-event-coeff", type=float, default=DROPOUT_EVENT_COEFF_S)
    ap.add_argument(
        "--output",
        choices=("human", "json", "total-seconds", "single-seconds"),
        default="human",
    )
    args = ap.parse_args()

    if args.num_loss <= 0:
        raise ValueError("--num-loss must be > 0")
    if args.num_iters <= 0:
        raise ValueError("--num-iters must be > 0")
    if args.dropout_event_coeff < 0:
        raise ValueError("--dropout-event-coeff must be >= 0")

    graphs = list(args.graph)
    if args.graph_input is not None:
        graphs.extend(resolve_graphs(args.graph_input, args.graph_pattern))

    num_drones = list(args.num_drones)
    num_drones.extend(graph_drone_count(graph) for graph in graphs)
    if not num_drones:
        num_drones = [18, 27, 38, 46]

    bitrates = tuple(args.bitrate) if args.bitrate else parse_words(args.bitrates)
    num_conns_values = tuple(args.num_conn) if args.num_conn else parse_int_sequence(args.num_conns)
    failure_probabilities = (
        tuple(args.failure_probability)
        if args.failure_probability
        else parse_float_sequence(args.failure_probabilities)
    )
    replacement_delays = (
        tuple(args.replacement_delay)
        if args.replacement_delay
        else parse_float_sequence(args.replacement_delays)
    )
    dropout_time_steps = (
        tuple(args.dropout_time_step)
        if args.dropout_time_step
        else parse_float_sequence(args.dropout_time_steps)
    )

    rows = runtime_rows(
        num_drones=tuple(num_drones),
        bitrates=bitrates,
        num_conns_values=num_conns_values,
        failure_probabilities=failure_probabilities,
        replacement_delays=replacement_delays,
        dropout_time_steps=dropout_time_steps,
        num_loss=args.num_loss,
        num_iters=args.num_iters,
        fixed=args.fixed,
        sim_duration=args.sim_duration,
        start_time=args.start_time,
        dropout_event_coeff_s=args.dropout_event_coeff,
    )
    total = sum(row["subtotal_s"] for row in rows)

    if args.output == "total-seconds":
        print(f"{total:.6f}")
        return

    if args.output == "single-seconds":
        if len(rows) != 1:
            raise ValueError("--output single-seconds requires exactly one value for each case dimension")
        print(f"{rows[0]['single_runtime_s']:.6f}")
        return

    if args.output == "json":
        print(
            json.dumps(
                {
                    "total_s": total,
                    "num_drones": num_drones,
                    "bitrates": bitrates,
                    "num_conns": num_conns_values,
                    "failure_probabilities": failure_probabilities,
                    "replacement_delays": replacement_delays,
                    "dropout_time_steps": dropout_time_steps,
                    "num_loss": args.num_loss,
                    "num_iters": args.num_iters,
                    "fixed": args.fixed,
                    "sim_duration": args.sim_duration,
                    "start_time": args.start_time,
                    "dropout_event_coeff_s": args.dropout_event_coeff,
                    "rows": rows,
                },
                separators=(",", ":"),
            )
        )
        return

    print_report(
        rows=rows,
        total=total,
        num_drones=tuple(num_drones),
        bitrates=bitrates,
        num_conns_values=num_conns_values,
        failure_probabilities=failure_probabilities,
        replacement_delays=replacement_delays,
        dropout_time_steps=dropout_time_steps,
        num_loss=args.num_loss,
        num_iters=args.num_iters,
        fixed=args.fixed,
        sim_duration=args.sim_duration,
        start_time=args.start_time,
        mesh_overhead_by_drones=MESH_OVERHEAD_BY_DRONES,
        traffic_coeff_s_per_mbit=TRAFFIC_COEFF_S_PER_MBIT,
        dropout_event_coeff_s=args.dropout_event_coeff,
    )


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}")
