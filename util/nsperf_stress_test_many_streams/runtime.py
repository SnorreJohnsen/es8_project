#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path
from typing import Any, Union


DEFAULT_NUM_STREAMS = (1, 2, 4, 6, 8, 10, 15, 20, 25, 30, 40)
DEFAULT_BITRATES = ("100k", "500k", "1M", "2M", "5M")
DEFAULT_GRAPH_PATTERN = "Triangle_network_*_tolerance_*_datarate_Mbps_*_bandwidth_Mhz_*_nodes.json"

MESH_OVERHEAD_BY_DRONES = {
    18: 100.1,
    27: 141.1,
    38: 245.5,
    46: 386.1,
}

TRAFFIC_COEFF_S_PER_MBIT = 0.01803


def report(t: float) -> None:
    print(f"seconds={t}")
    print(f"minutes={t / 60}")
    print(f"hours={t / 3600}")
    print(f"days={t / (3600 * 24)}")


def parse_bitrate_mbps(x: Union[str, int, float]) -> float:
    if isinstance(x, (int, float)):
        return float(x)

    s = x.strip().lower()

    if s.endswith("k"):
        return float(s[:-1]) / 1000
    if s.endswith("m"):
        return float(s[:-1])

    return float(s)


def parse_int_sequence(value: str) -> tuple[int, ...]:
    seq = tuple(int(item) for item in value.replace(",", " ").split())
    if not seq:
        raise ValueError("num streams sequence cannot be empty")
    if any(item <= 0 for item in seq):
        raise ValueError("all num streams sequence values must be > 0")
    return seq


def parse_words(value: str) -> tuple[str, ...]:
    words = tuple(value.split())
    if not words:
        raise ValueError("value cannot be empty")
    return words


def simtime(
    fixed: float = 60,
    silence: float = 30,
    streamlen: float = 10,
    delay: float = 10,
    num_streams: tuple[int, ...] = DEFAULT_NUM_STREAMS,
) -> float:
    return fixed + delay + len(num_streams) * (silence + streamlen)


def traffic_mbit(
    bitrate_mbps: float,
    streamlen: float = 10,
    num_streams: tuple[int, ...] = DEFAULT_NUM_STREAMS,
) -> float:
    return bitrate_mbps * streamlen * sum(num_streams)


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


def single_runtime_row(
    drones: int,
    bitrate: str,
    fixed: float = 60,
    silence: float = 30,
    streamlen: float = 10,
    delay: float = 10,
    num_streams: tuple[int, ...] = DEFAULT_NUM_STREAMS,
    mesh_overhead_by_drones: dict[int, float] = MESH_OVERHEAD_BY_DRONES,
    traffic_coeff_s_per_mbit: float = TRAFFIC_COEFF_S_PER_MBIT,
) -> dict[str, Any]:
    scheduled = simtime(
        fixed=fixed,
        silence=silence,
        streamlen=streamlen,
        delay=delay,
        num_streams=num_streams,
    )
    bitrate_mbps = parse_bitrate_mbps(bitrate)
    traffic = traffic_mbit(
        bitrate_mbps=bitrate_mbps,
        streamlen=streamlen,
        num_streams=num_streams,
    )
    mesh_overhead = mesh_overhead_s(
        drones=drones,
        mesh_overhead_by_drones=mesh_overhead_by_drones,
    )
    traffic_overhead = traffic_coeff_s_per_mbit * traffic
    single_runtime = scheduled + mesh_overhead + traffic_overhead

    return {
        "drones": drones,
        "bitrate": bitrate,
        "bitrate_mbps": bitrate_mbps,
        "traffic_mbit": traffic,
        "scheduled_s": scheduled,
        "mesh_overhead_s": mesh_overhead,
        "traffic_overhead_s": traffic_overhead,
        "single_runtime_s": single_runtime,
    }


def runtime_rows(
    num_drones: Union[int, tuple[int, ...]] = (18, 27, 38, 46),
    bitrates: tuple[str, ...] = DEFAULT_BITRATES,
    num_loss: int = 1,
    num_iters: int = 10,
    fixed: float = 60,
    silence: float = 30,
    streamlen: float = 10,
    delay: float = 10,
    num_streams: tuple[int, ...] = DEFAULT_NUM_STREAMS,
    mesh_overhead_by_drones: dict[int, float] = MESH_OVERHEAD_BY_DRONES,
    traffic_coeff_s_per_mbit: float = TRAFFIC_COEFF_S_PER_MBIT,
) -> list[dict[str, Any]]:
    if isinstance(num_drones, int):
        num_drones = (num_drones,)

    rows = []
    runs = num_loss * num_iters
    for drones in num_drones:
        for bitrate in bitrates:
            row = single_runtime_row(
                drones=drones,
                bitrate=bitrate,
                fixed=fixed,
                silence=silence,
                streamlen=streamlen,
                delay=delay,
                num_streams=num_streams,
                mesh_overhead_by_drones=mesh_overhead_by_drones,
                traffic_coeff_s_per_mbit=traffic_coeff_s_per_mbit,
            )
            row["runs"] = runs
            row["subtotal_s"] = row["single_runtime_s"] * runs
            rows.append(row)

    return rows


def runtime(
    num_drones: Union[int, tuple[int, ...]] = (18, 27, 38, 46),
    bitrates: tuple[str, ...] = DEFAULT_BITRATES,
    num_loss: int = 1,
    num_iters: int = 10,
    fixed: float = 60,
    silence: float = 30,
    streamlen: float = 10,
    delay: float = 10,
    num_streams: tuple[int, ...] = DEFAULT_NUM_STREAMS,
    mesh_overhead_by_drones: dict[int, float] = MESH_OVERHEAD_BY_DRONES,
    traffic_coeff_s_per_mbit: float = TRAFFIC_COEFF_S_PER_MBIT,
    dump: bool = True,
) -> float:
    rows = runtime_rows(
        num_drones=num_drones,
        bitrates=bitrates,
        num_loss=num_loss,
        num_iters=num_iters,
        fixed=fixed,
        silence=silence,
        streamlen=streamlen,
        delay=delay,
        num_streams=num_streams,
        mesh_overhead_by_drones=mesh_overhead_by_drones,
        traffic_coeff_s_per_mbit=traffic_coeff_s_per_mbit,
    )
    total = sum(row["subtotal_s"] for row in rows)

    if dump:
        print_report(
            rows=rows,
            total=total,
            num_drones=(num_drones,) if isinstance(num_drones, int) else num_drones,
            bitrates=bitrates,
            num_loss=num_loss,
            num_iters=num_iters,
            fixed=fixed,
            silence=silence,
            streamlen=streamlen,
            delay=delay,
            num_streams=num_streams,
            mesh_overhead_by_drones=mesh_overhead_by_drones,
            traffic_coeff_s_per_mbit=traffic_coeff_s_per_mbit,
        )

    return total


def print_report(
    rows: list[dict[str, Any]],
    total: float,
    num_drones: tuple[int, ...],
    bitrates: tuple[str, ...],
    num_loss: int,
    num_iters: int,
    fixed: float,
    silence: float,
    streamlen: float,
    delay: float,
    num_streams: tuple[int, ...],
    mesh_overhead_by_drones: dict[int, float],
    traffic_coeff_s_per_mbit: float,
) -> None:
    scheduled = simtime(
        fixed=fixed,
        silence=silence,
        streamlen=streamlen,
        delay=delay,
        num_streams=num_streams,
    )

    print("=== inputs ===")
    print(f"num_drones={num_drones}")
    print(f"bitrates={bitrates}")
    print(f"num_loss={num_loss}")
    print(f"num_iters={num_iters}")
    print(f"fixed={fixed}")
    print(f"silence={silence}")
    print(f"streamlen={streamlen}")
    print(f"delay={delay}")
    print(f"num_streams={num_streams}")
    print(f"sum_num_streams={sum(num_streams)}")
    print()

    print("=== model ===")
    print(f"scheduled_s={scheduled}")
    print(f"mesh_overhead_by_drones={mesh_overhead_by_drones}")
    print(f"traffic_coeff_s_per_mbit={traffic_coeff_s_per_mbit}")
    print()

    print("=== per case ===")
    for row in rows:
        print(
            f"{row['drones']} drones, {row['bitrate']}: "
            f"single={row['single_runtime_s']:.1f}s "
            f"({row['single_runtime_s'] / 60:.2f} min), "
            f"runs={row['runs']}, "
            f"subtotal={row['subtotal_s']:.1f}s "
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
    ap.add_argument("--num-loss", type=int, default=1)
    ap.add_argument("--num-iters", type=int, default=10)
    ap.add_argument("--fixed", type=float, default=60.0)
    ap.add_argument("--silence", type=float, default=30.0)
    ap.add_argument("--streamlen", type=float, default=10.0)
    ap.add_argument("--delay", type=float, default=10.0)
    ap.add_argument("--num-streams-sequence", default=" ".join(str(i) for i in DEFAULT_NUM_STREAMS))
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

    graphs = list(args.graph)
    if args.graph_input is not None:
        graphs.extend(resolve_graphs(args.graph_input, args.graph_pattern))

    num_drones = list(args.num_drones)
    num_drones.extend(graph_drone_count(graph) for graph in graphs)
    if not num_drones:
        num_drones = [18, 27, 38, 46]

    bitrates = tuple(args.bitrate) if args.bitrate else parse_words(args.bitrates)
    num_streams = parse_int_sequence(args.num_streams_sequence)

    rows = runtime_rows(
        num_drones=tuple(num_drones),
        bitrates=bitrates,
        num_loss=args.num_loss,
        num_iters=args.num_iters,
        fixed=args.fixed,
        silence=args.silence,
        streamlen=args.streamlen,
        delay=args.delay,
        num_streams=num_streams,
    )
    total = sum(row["subtotal_s"] for row in rows)

    if args.output == "total-seconds":
        print(f"{total:.6f}")
        return

    if args.output == "single-seconds":
        if len(rows) != 1:
            raise ValueError("--output single-seconds requires one graph/drone count and one bitrate")
        print(f"{rows[0]['single_runtime_s']:.6f}")
        return

    if args.output == "json":
        print(
            json.dumps(
                {
                    "total_s": total,
                    "num_drones": num_drones,
                    "bitrates": bitrates,
                    "num_loss": args.num_loss,
                    "num_iters": args.num_iters,
                    "fixed": args.fixed,
                    "silence": args.silence,
                    "streamlen": args.streamlen,
                    "delay": args.delay,
                    "num_streams": num_streams,
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
        num_loss=args.num_loss,
        num_iters=args.num_iters,
        fixed=args.fixed,
        silence=args.silence,
        streamlen=args.streamlen,
        delay=args.delay,
        num_streams=num_streams,
        mesh_overhead_by_drones=MESH_OVERHEAD_BY_DRONES,
        traffic_coeff_s_per_mbit=TRAFFIC_COEFF_S_PER_MBIT,
    )


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}")
