import pyshark
from tqdm import tqdm
import hashlib
import subprocess
import numpy as np
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import itertools

def describe(data, f=None):
    data = np.array(data)
    
    # Helper function to print and optionally write to txt file
    def write(s):
        print(s)
        if f:
            f.write(s + "\n")
        
    write(f"Count: {len(data)}")
    write(f"Mean: {np.mean(data):.6f}")
    write(f"Std: {np.std(data):.6f}")
    write(f"Min: {np.min(data)}")
    write(f"25%: {np.percentile(data, 25)}")
    write(f"Median: {np.median(data)}")
    write(f"75%: {np.percentile(data, 75)}")
    write(f"80%: {np.percentile(data, 80)}")
    write(f"99%: {np.percentile(data, 99)}")
    write(f"99.99%: {np.percentile(data, 99.99)}")
    write(f"Max: {np.max(data)}")

def hist_box(diffs: list,
             stats_folder: Path,
             num_packets: int):

    # ---- Save Histogram for this iteration ----
    plt.figure(figsize=(8,5))
    plt.hist(diffs, bins=30, color='skyblue', edgecolor='black')
    plt.xlabel('Time Difference (s)')
    plt.ylabel('Count')
    plt.title(f'Histogram for {num_packets} packets')
    plt.grid(True, linestyle='--', alpha=0.5)
    hist_path = stats_folder / f"time_difference_histogram_{num_packets}_packets.png"
    plt.savefig(hist_path)
    plt.close()

    # ---- Save Boxplot for this iteration ----
    plt.figure(figsize=(8,8))
    plt.boxplot(diffs, vert=True, patch_artist=True, boxprops=dict(facecolor='lightgreen'))
    plt.ylabel('Time Difference (s)')
    plt.title(f'Boxplot for {num_packets} packets')
    plt.grid(True, linestyle='--', alpha=0.5)
    boxplot_path = stats_folder / f"time_difference_boxplot_{num_packets}_packets.png"
    plt.savefig(boxplot_path)
    plt.close()

# Helper to get total number of packets in the file
def get_packet_count(pcap_file):

    capinfos_path = r"C:\Program Files\Wireshark\capinfos.exe"

    result = subprocess.run(
        [capinfos_path, pcap_file],
        capture_output=True,
        text=True
    )
    
    for line in result.stdout.splitlines():
        if "Number of packets:" in line:
            return int (line.split(":")[1].replace(" ", "").replace("k", "000").replace("M", "000000"))
    exit(-1)
        
def max_diff_same_frame(pcap_file,
                        total_packets: int,
                        desired_packets: int=None):

    capture = pyshark.FileCapture(pcap_file,
                                  keep_packets=False,
                                  use_json=True,
                                  include_raw=True)

    frames = {}  # key -> [first_ts, last_ts]

    if desired_packets is not None:
        packets_processed = min(total_packets, desired_packets)
    else:
        packets_processed = total_packets

    for i, pkt in tqdm(enumerate(capture), total=packets_processed, desc="Processing packets", unit="pkt"):
        if i == packets_processed: break
        try:
            ts = float(pkt.sniff_timestamp)

            # Use hash of full frame (fast + reliable)
            raw_bytes = bytes(pkt.get_raw_packet())
            h = hashlib.sha256(raw_bytes).hexdigest()

            if h not in frames:
                frames[h] = [ts]
            else:
                frames[h].append(ts)

        except AttributeError:
            continue

    diffs = np.zeros(shape=packets_processed, dtype=np.float64)
    total_diffs = 0
    for key, timestamps in frames.items():
        t_first = timestamps[0]
        for t in timestamps[1:]:
            diff = t - t_first
            diffs[total_diffs] = diff
            total_diffs += 1
    diffs_actual = diffs[:total_diffs]
    return diffs_actual

if __name__ == "__main__":

    # Replace with your PCAP path
    pcap_file = r"C:\UNI\8.Semester\Project\pcap_test_files\merged_smus_test.pcap"

    # Define folder and filename for .txt
    stats_folder = Path(__file__).parent / "pcap_time_diff_stats"
    stats_folder.mkdir(parents=True, exist_ok=True)

    txt_path = stats_folder / "time_difference_pcap.txt"
    hist_path = stats_folder / "time_difference_histogram.png"
    boxplot_path = stats_folder / "time_difference_boxplot.png"

    # Get total packets and desired packets
    total_packets = get_packet_count(pcap_file=pcap_file)
    desired_packets = [1_000, 10_000, 100_000, 1_000_000, total_packets]
 
    # Save txt file
    with open(txt_path, "w") as f:
        for packet in desired_packets:
            # Calculate maximum time difference between two identical frames
            diffs = max_diff_same_frame(pcap_file=pcap_file, total_packets=total_packets, desired_packets=packet)

            # Optional header in the file
            if packet is None:
                f.write(f"\n=== Analysis for ALL {total_packets} packets ===\n")
            elif packet is total_packets:
                f.write(f"\n=== Analysis for ALL {total_packets} packets ===\n")
            else:
                f.write(f"\n=== Analysis for {packet} packets ===\n")

            describe(diffs, f=f)

            hist_box(diffs=diffs,
                     stats_folder=stats_folder,
                     num_packets=packet)

    print(f'Results saved to {txt_path}')
    print(f'Histograms saved to {hist_path}')
    print(f'Boxplots saved to {boxplot_path}')