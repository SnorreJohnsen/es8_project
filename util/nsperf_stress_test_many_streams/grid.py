#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path
from typing import Any


def has_adapter_nodes(graph: dict[str, Any]) -> bool:
    return any(re.fullmatch(r"a[0-9]+", str(node.get("id"))) for node in graph.get("nodes", []))


def grid_positions(
    rows: int,
    cols: int,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    z: float,
) -> list[tuple[float, float, float]]:
    if rows <= 0:
        raise ValueError("--rows must be > 0")
    if cols <= 0:
        raise ValueError("--cols must be > 0")
    if x_max < x_min:
        raise ValueError("--x-max must be >= --x-min")
    if y_max < y_min:
        raise ValueError("--y-max must be >= --y-min")

    x_step = 0.0 if cols == 1 else (x_max - x_min) / (cols - 1)
    y_step = 0.0 if rows == 1 else (y_max - y_min) / (rows - 1)

    positions = []
    for row in range(rows):
        y = y_min + y_step * row
        for col in range(cols):
            x = x_min + x_step * col
            positions.append((x, y, z))
    return positions


def format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def adapter_pos_arg(positions: list[tuple[float, float, float]]) -> str:
    return ";".join(
        f"({format_number(x)},{format_number(y)},{format_number(z)})"
        for x, y, z in positions
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("graph", type=Path, help="Base graph JSON, used to reject pre-placed adapters")
    ap.add_argument("--rows", type=int, default=3, help="Number of adapter grid rows")
    ap.add_argument("--cols", type=int, default=7, help="Number of adapter grid columns")
    ap.add_argument("--x-min", type=float, default=0.0)
    ap.add_argument("--x-max", type=float, default=30000.0)
    ap.add_argument("--y-min", type=float, default=0.0)
    ap.add_argument("--y-max", type=float, default=10000.0)
    ap.add_argument("--z", type=float, default=0.0)
    ap.add_argument("--json", type=Path, help="Optional JSON metadata output path")
    args = ap.parse_args()

    with args.graph.open(encoding="utf-8") as f:
        graph = json.load(f)
    if has_adapter_nodes(graph):
        raise SystemExit("error: input graph already contains adapter nodes matching a<number>")

    positions = grid_positions(args.rows, args.cols, args.x_min, args.x_max, args.y_min, args.y_max, args.z)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        with args.json.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "rows": args.rows,
                    "cols": args.cols,
                    "x_min": args.x_min,
                    "x_max": args.x_max,
                    "y_min": args.y_min,
                    "y_max": args.y_max,
                    "z": args.z,
                    "count": len(positions),
                    "positions": positions,
                },
                f,
                separators=(",", ":"),
            )

    print(adapter_pos_arg(positions))


if __name__ == "__main__":
    main()
