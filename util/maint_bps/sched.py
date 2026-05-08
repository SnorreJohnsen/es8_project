#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from typing import Any


def empty_schedule(duration: float) -> dict[str, Any]:
    return {
        "start_timestamp": 0,
        "duration": duration,
        "sched_plan": [],
        "sched_real": [],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("output", type=Path, help="Output schedule JSON path")
    ap.add_argument("--duration", type=float, default=300.0, help="Simulation duration in seconds")
    args = ap.parse_args()

    if args.duration <= 0:
        raise ValueError("--duration must be > 0")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(empty_schedule(args.duration), f, separators=(",", ":"))


if __name__ == "__main__":
    main()
