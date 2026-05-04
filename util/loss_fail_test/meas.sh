#!/bin/sh

set -eu

# Arguments
graph="${1:-/home/aau/meshsim/testgraphs/Triangle_network_10_tolerance_20.0_datarate_Mbps_8.0_bandwidth_Mhz_10_nodes.json}"
sched="${2:-/home/aau/meshsim/testscheds/loss_nsperf.json}"
out_dir="${3:-/home/aau/meshsim/output/loss_fail_test}"
emulation_script="${EMULATION_SCRIPT:-/home/aau/meshsim/repo/emulation.py}"
network_script="${NETWORK_SCRIPT:-/home/aau/meshsim/repo/meshnet-lab/network.py}"
nsperf_analyze_script="${NETWORK_SCRIPT:-/home/aau/meshsim/repo/nsperf/tools/analyze.py}"
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
	$PYTHON "$emulation_script" --sim-sched "$sched" --link-loss "$link_loss" --verbosity verbose "$graph" >"$logfile" 2>&1
	cleanup
}

# function to analyze nsperf stream
analyze_nsperf() {
	tx="$1"
	rx="$2"
	out="$3"
	interval="${4:-}"
	if [ -n "$interval" ]; then
		$PYTHON "$nsperf_analyze_script" --interval "$interval" --send "$tx" --recv "$rx" --json >"$out"
	else
		$PYTHON "$nsperf_analyze_script" --send "$tx" --recv "$rx" --json >"$out"
	fi
}

# function to analyze all nsperf streams
analyze_all_nsperf() {
	raw_dir="$1"
	out_dir_nsperf="$2"

	mkdir -p "$out_dir_nsperf"
	client_files=$(find "$raw_dir" -type f -name "*.send.csv")
	for client_file in $client_files; do
		client_filename=$(basename "$client_file")
		server_device=$(echo "$client_filename" | cut -d "_" -f 1)
		client_device=$(echo "$client_filename" | cut -d "_" -f 2)
		simtime=$(echo "$client_filename" | cut -d "_" -f 3 | cut -d "." -f 1)
		server_file="${raw_dir}/${server_device}.recv.csv"
		echo "$client_file" "receiver: $server_device" "client: $client_device" "simtime: $simtime" "server_file: $server_file"

		ls "$server_file" >/dev/null || (echo "server file not found" && exit)

		out="$out_dir_nsperf/${server_device}_${client_device}_${simtime}.json"
		analyze_nsperf "$client_file" "$server_file" "$out"

		for interval in "0.5" "1" "2" "5"; do
			out="$out_dir_nsperf/intervals/${server_device}_${client_device}_${simtime}_inter_${interval}.json"
			mkdir -p "$out_dir_nsperf/intervals"
			analyze_nsperf "$client_file" "$server_file" "$out" "$interval"
		done
	done
}

echo "Running sims"
for loss in "0" "0.01" "0.02" "0.04" "0.06" "0.08" "0.1" \
	"0.12" "0.15" "0.18" "0.2" "0.25" "0.3" "0.4" \
	"0.5" "1" "2" "3" "4" "5" "6" "7" "8" "9" "10"; do
	echo "[*] Link loss $loss"
	run_emulation "$graph" "$sched" "$loss"
	analyze_all_nsperf "$emulation_dir/nsperf/raw" "$emulation_dir/nsperf/streams"
	cd "$emulation_dir" && tar -c --use-compress-program=pigz -f "pcaps.tar.gz" "pcaps" && cd -
	rm -rf "$emulation_dir/pcaps"
	mv "$emulation_dir" "$out_dir/$loss"
done
