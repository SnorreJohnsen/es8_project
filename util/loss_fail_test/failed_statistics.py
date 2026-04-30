import json
import argparse
from pathlib import Path
from collections import defaultdict

def is_iperf3_failed(json_file: Path) -> bool:
    try:
        with open(json_file, "r") as f:
            data = json.load(f)

        if "error" in data:
            return True

        connected = data["start"].get("connected")
        if not connected:
            return True

        return False

    except Exception:
        return True

def summary_print(stats):
    width = 50

    print(f"""
    {'=' * width}
    {'SUMMARY'.center(width)}
    {'=' * width}
    """)

    for folder in sorted(stats, key=float):
        s = stats[folder]["success"]
        f = stats[folder]["failed"]

        total = s + f
        pct_failed = (f / total * 100) if total > 0 else 0

        line = (
            f"{folder:>4}   "
            f"Total: {total:>3}   "
            f"Failed: {f:>3}   "
            f"({pct_failed:>6.2f}%)"
        )

        print(line.center(width))

def plot_failed_stats(stats, save_path=None):
    import matplotlib.pyplot as plt
    import numpy as np

    folders = sorted(stats.keys(), key=float)

    failed_pct = []
    total_files = []

    for f in folders:
        failed = stats[f]["failed"]
        total = stats[f]["failed"] + stats[f]["success"]

        total_files.append(total)

        pct = (failed / total * 100) if total > 0 else 0
        failed_pct.append(pct)

    assert min(total_files) == max(total_files), (
            f"Expected equal connection count, got {total_files}"
            )

    x = np.arange(len(folders))

    plt.figure(figsize=(12, 5))

    plt.plot(x, failed_pct, marker='o', linestyle='-', label="Failure rate (%)")

    plt.xlabel("Link loss (%)")
    plt.ylabel("Failure rate (%)")
    plt.title("iPerf3 Failure Rate vs Link Loss")

    plt.xticks(x, folders, rotation=45, ha="right")
    plt.grid(True, alpha=0.3)

    legend_text = f"Connections: {total_files[0]}"
    plt.legend([legend_text])

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path)
        plt.close()
    else:
        plt.show()

def main():
    parser = argparse.ArgumentParser(description="Tool to show stats for link loss tests")
    parser.add_argument('directory',
                        help='Directory with raw iperf3 json output of form: "directory/{link_loss}/iperf3/raw')
    parser.add_argument('-p', '--plot-show',
                        action="store_true",
                        help='Show graph of failed percentage vs link losses')
    parser.add_argument('-P', '--plot-save',
                        required=False,
                        help='Save graph of failed percentage vs link losses to specified path')
    args = parser.parse_args()

    stats = defaultdict(lambda: {"success": 0, "failed": 0})

    output_root = Path(args.directory)
    raw_dirs = output_root.glob("*/iperf3/raw")

    for raw_dir in raw_dirs:
        folder_name = raw_dir.parent.parent.name # this is the * folder

        for json_file in raw_dir.glob("*.json"):
            if is_iperf3_failed(json_file):
                stats[folder_name]["failed"] += 1
            else:
                stats[folder_name]["success"] += 1

    if args.plot_show or args.plot_save:
        plot_failed_stats(stats, save_path=args.plot_save)

    summary_print(stats)

if __name__ == "__main__":
    main()
