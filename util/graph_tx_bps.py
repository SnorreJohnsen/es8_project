import argparse
import csv
from collections import defaultdict
from pathlib import Path
import subprocess
import sys

import matplotlib.pyplot as plt


def run_tshark(pcap: Path, mac: str) -> list[tuple[float, int]]:
    cmd = [
        "tshark",
        "-r", str(pcap),
        "-Y", f"wlan.sa == {mac} or eth.src == {mac}",
        "-T", "fields",
        "-e", "frame.time_epoch",
        "-e", "frame.len",
        "-E", "separator=,",
        "-E", "quote=n",
        "-E", "occurrence=f",
    ]

    try:
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(e.stderr, file=sys.stderr)
        raise

    rows: list[tuple[float, int]] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        ts_s, frame_len = line.split(",", 1)
        rows.append((float(ts_s), int(frame_len) * 8))

    return rows


def bucket_bits(
    samples: list[tuple[float, int]],
    bucket_s: float,
) -> tuple[list[float], list[int]]:
    if not samples:
        return [0.0], [0]

    t0 = samples[0][0]
    buckets: dict[int, int] = defaultdict(int)

    for ts, bits in samples:
        idx = int((ts - t0) // bucket_s)
        buckets[idx] += bits

    max_idx = max(buckets)
    times = [i * bucket_s for i in range(max_idx + 1)]
    bits = [buckets[i] for i in range(max_idx + 1)]
    return times, bits


def accumulate(values: list[int]) -> list[int]:
    total = 0
    out: list[int] = []
    for v in values:
        total += v
        out.append(total)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap", type=Path)
    ap.add_argument("mac", help="MAC address to count transmitted bits for")
    ap.add_argument("output", type=Path, help="Output image path for bar graph, e.g. out.png")
    ap.add_argument(
        "--bucket",
        type=float,
        default=1.0,
        help="Bucket width in seconds (default: 1.0)",
    )
    ap.add_argument(
        "--csv",
        type=Path,
        help="Optional CSV output path for per-bucket bits",
    )
    ap.add_argument(
        "--accum-csv",
        type=Path,
        help="Optional CSV output path for accumulated bits",
    )
    ap.add_argument(
        "--accum-plot",
        type=Path,
        help="Optional output image path for accumulated bits plot",
    )
    args = ap.parse_args()

    if args.bucket <= 0:
        raise ValueError("--bucket must be > 0")

    samples = run_tshark(args.pcap, args.mac.lower())
    times, bits = bucket_bits(samples, args.bucket)
    accum_bits = accumulate(bits)

    if args.csv:
        with args.csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "bits"])
            w.writerows(zip(times, bits))

    if args.accum_csv:
        with args.accum_csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "accum_bits"])
            w.writerows(zip(times, accum_bits))

    plt.figure()
    plt.bar(times, bits, width=args.bucket, align="edge")
    plt.xlabel(f"Time since first frame [s] (bucket={args.bucket}s)")
    plt.ylabel("Bits transmitted in bucket")
    plt.title(f"Transmitted bits vs time for {args.mac}")
    plt.grid(True, axis="y")
    plt.tight_layout()
    plt.savefig(args.output, dpi=150)
    plt.close()

    if args.accum_plot:
        plt.figure()
        plt.plot(times, accum_bits)
        plt.xlabel(f"Time since first frame [s] (bucket={args.bucket}s)")
        plt.ylabel("Accumulated bits")
        plt.title(f"Accumulated transmitted bits vs time for {args.mac}")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(args.accum_plot, dpi=150)
        plt.close()


if __name__ == "__main__":
    main()
