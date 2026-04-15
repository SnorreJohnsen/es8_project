#!/bin/sh

set -eu

# Arguments
graph_dir="${1:-/home/aau/meshsim/testgraphs}"
out_dir="${2:-/home/aau/meshsim/output/settle_time_meas}"
sched_script="${SCHED_SCRIPT:-/home/aau/meshsim/repo/util/settle_time_meas/sched.py}"
emulation_script="${EMULATION_SCRIPT:-/home/aau/meshsim/repo/emulation.py}"
graph_tx_bps_script="${GRAPH_TX_BPS_SCRIPT:-/home/aau/meshsim/repo/util/graph_tx_bps.py}"
network_script="${NETWORK_SCRIPT:-/home/aau/meshsim/repo/meshnet-lab/network.py}"
pcap_dir="${PCAP_DIR:-/home/aau/meshsim/output/emulation/pcaps}"
addr_json="${ADDR_JSON:-/home/aau/meshsim/output/emulation/node_addrs.json}"
PYTHON="${PYTHON_EXE:-python3}"

graphs=$(find "$graph_dir" -type f -name "Triangle_network_*_tolerance_*_datarate_Mbps_*_bandwidth_Mhz_*_nodes.json")

# function to get num nodes
get_num() {
	echo "$1" | grep -o -e '[0-9]\+_nodes' | cut -d_ -f1
}

# function to get node name
get_node() {
	echo "$1" | grep -o -e 'n[0-9]\+'
}

# function to clean namespaces
cleanup() {
	$PYTHON "$network_script" clear
	modprobe -r batman_adv
}

# function to run emulation
run_emulation() {
	graph="$1"
	sched="$2"

	cleanup
	modprobe batman_adv
	$PYTHON "$emulation_script" --verbosity quiet --sim-sched "$sched" "$graph" >/dev/null
	cleanup
}

# function to plot transmitted bytes versus time
plot_tx() {
	pcap="$1"
	mac="$2"
	outdir="$3"
	bucket_size="$4"
	bucket_fig="$outdir/bucket.png"
	bucket_csv="$outdir/bucket.csv"
	accum_fig="$outdir/accum.png"
	accum_csv="$outdir/accum.csv"
	$PYTHON "$graph_tx_bps_script" --bucket "$bucket_size" \
		--csv "$bucket_csv" --accum-csv "$accum_csv" \
		--accum-plot "$accum_fig" \
		"$pcap" "$mac" "$bucket_fig"
}

# function to get mac from addr overview
get_mac() {
	addr_json="$1"
	node="$2"
	cat "$addr_json" | jq ".$node.mac | to_entries[] | select(.key | startswith(\"uplink\")) | .value" | sed 's/"//g'
}

echo "Running everything"
for graph in $graphs; do
	num=$(get_num "$graph")
	basedir="$out_dir/$num"
	echo "[size=$num] graph $graph"

	# Generate schedules
	sched_dir="$basedir/sched"
	$PYTHON "$sched_script" "$graph" "$sched_dir"

	# Run sims
	plot_dir="$basedir/plot"
	scheds=$(find "$sched_dir" -type f -name "*.json")
	for sched in $scheds; do
		node=$(get_node "$sched")
		echo "[size=$num; node=$node] running $sched"
		run_emulation "$graph" "$sched"

		for bucket in $(seq 0.1 0.1 1 | sed "s/,/./"); do
			mac=$(get_mac "$addr_json" "$node")
			sched_plot_dir="$plot_dir/$node/${bucket}_bucket"
			plot_tx "$pcap_dir/raw/$node.pcap" "$mac" "$sched_plot_dir" "$bucket"
		done
	done
done
