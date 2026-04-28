#!/bin/sh

set -eu

# Arguments
graph="${1:-/home/aau/meshsim/testgraphs/Triangle_network_10_tolerance_20.0_datarate_Mbps_8.0_bandwidth_Mhz_10_nodes.json}"
sched="${2:-/home/aau/meshsim/testscheds/loss_test.json}"
out_dir="${3:-/home/aau/meshsim/output/loss_fail_test}"
emulation_script="${EMULATION_SCRIPT:-/home/aau/meshsim/repo/emulation.py}"
network_script="${NETWORK_SCRIPT:-/home/aau/meshsim/repo/meshnet-lab/network.py}"
emulation_dir="${PCAP_DIR:-/home/aau/meshsim/output/emulation}"
PYTHON="${PYTHON_EXE:-python3}"

log_dir="$out_dir/logs"
mkdir -p "$log_dir"

# function to clean namespaces
cleanup() {
	$PYTHON "$network_script" clear
	modprobe -r batman_adv
}

# function to run emulation
run_emulation() {
	graph="$1"
	sched="$2"
	link_loss="$3"
	t=$(date --utc | sed "s/ /_/g")
	logfile="${log_dir}/log_${link_loss}_${t}.txt"

	cleanup
	modprobe batman_adv
	$PYTHON "$emulation_script" --sim-sched "$sched" --link-loss "$link_loss" --verbosity verbose "$graph" #>"$logfile"
	cleanup
}

echo "Running sims"
for loss in "0" "0.1" "0.5" "1" "2" "3" "4" "5" "6" "7" "8" "9" "10"; do
	echo "[*] Link loss $loss"
	run_emulation "$graph" "$sched" "$loss"
	mv "$emulation_dir" "$out_dir/$loss"
done
