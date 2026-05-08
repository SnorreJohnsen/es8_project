import argparse
import csv
from collections import defaultdict
import math
from pathlib import Path
import subprocess
import sys


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
    start_epoch: float | None = None,
    duration: float | None = None,
) -> tuple[list[float], list[int]]:
    if start_epoch is None:
        if not samples:
            return [0.0], [0]

        t0 = samples[0][0]
        buckets: dict[int, int] = defaultdict(int)

        for ts, bits in samples:
            if duration is not None and ts >= t0 + duration:
                continue
            idx = int((ts - t0) // bucket_s)
            buckets[idx] += bits

        if duration is not None:
            bucket_count = max(1, math.ceil(duration / bucket_s))
        else:
            bucket_count = max(buckets) + 1

        times = [i * bucket_s for i in range(bucket_count)]
        bits = [buckets[i] for i in range(bucket_count)]
        return times, bits

    t0 = start_epoch
    buckets: dict[int, int] = defaultdict(int)

    for ts, bits in samples:
        if ts < t0:
            continue
        if duration is not None and ts >= t0 + duration:
            continue
        idx = int((ts - t0) // bucket_s)
        buckets[idx] += bits

    if duration is not None:
        bucket_count = max(1, math.ceil(duration / bucket_s))
    elif buckets:
        bucket_count = max(buckets) + 1
    else:
        bucket_count = 1

    times = [i * bucket_s for i in range(bucket_count)]
    bits = [buckets[i] for i in range(bucket_count)]
    return times, bits


def bits_to_bps(bits: list[int], bucket_s: float) -> list[float]:
    return [value / bucket_s for value in bits]


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
        "--start-epoch",
        type=float,
        help="Optional epoch timestamp to use as t=0 for bucketing",
    )
    ap.add_argument(
        "--duration",
        type=float,
        help="Optional duration in seconds to include from bucket origin",
    )
    ap.add_argument(
        "--csv",
        type=Path,
        help="Optional CSV output path for per-bucket bits and bps",
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

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    if args.csv:
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
    if args.accum_csv:
        Path(args.accum_csv).parent.mkdir(parents=True, exist_ok=True)
    if args.accum_plot:
        Path(args.accum_plot).parent.mkdir(parents=True, exist_ok=True)

    if args.bucket <= 0:
        raise ValueError("--bucket must be > 0")
    if args.duration is not None and args.duration <= 0:
        raise ValueError("--duration must be > 0")

    samples = run_tshark(args.pcap, args.mac.lower())
    times, bits = bucket_bits(samples, args.bucket, args.start_epoch, args.duration)
    bps = bits_to_bps(bits, args.bucket)
    accum_bits = accumulate(bits)
    time_label = "Time since simulation start" if args.start_epoch is not None else "Time since first frame"

    if args.csv:
        with args.csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "bits", "bps"])
            w.writerows(zip(times, bits, bps))

    if args.accum_csv:
        with args.accum_csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "accum_bits"])
            w.writerows(zip(times, accum_bits))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.figure()
    plt.bar(times, bits, width=args.bucket, align="edge")
    plt.xlabel(f"{time_label} [s] (bucket={args.bucket}s)")
    plt.ylabel("Bits transmitted in bucket")
    plt.title(f"Transmitted bits vs time for {args.mac}")
    plt.grid(True, axis="y")
    plt.tight_layout()
    plt.savefig(args.output, dpi=150)
    plt.close()

    if args.accum_plot:
        plt.figure()
        plt.plot(times, accum_bits)
        plt.xlabel(f"{time_label} [s] (bucket={args.bucket}s)")
        plt.ylabel("Accumulated bits")
        plt.title(f"Accumulated transmitted bits vs time for {args.mac}")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(args.accum_plot, dpi=150)
        plt.close()


if __name__ == "__main__":
    main()
