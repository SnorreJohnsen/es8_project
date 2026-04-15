#!/bin/sh

set -eu

# Arguments
graph_dir="${1:-/home/aau/meshsim/testgraphs}"
out_dir="${2:-/home/aau/meshsim/output/settle_time_meas}"
sched_script="${SCHED_SCRIPT:-/home/aau/meshsim/repo/util/settle_time_meas/sched.py}"
emulation_script="${EMULATION_SCRIPT:-/home/aau/meshsim/repo/emulation.py}"
PYTHON="${PYTHON_EXE:-python3}"

graphs=$(find "$graph_dir" -type f -name "Triangle_network_*_tolerance_*_datarate_Mbps_*_bandwidth_Mhz_*_nodes.json")

# function to get num nodes
get_num() {
	echo "$1" | grep -o -e '[0-9]\+_nodes' | cut -d_ -f1
}

# function to run emulation
run_emulation() {
	graph="$1"
	sched="$2"

	modprobe -r batman_adv
	modprobe batman_adv
	$PYTHON "$emulation_script" --verbosity quiet --sim-sched "$sched" "$graph"
	modprobe -r batman_adv
}

echo "[1] Preparing sim schedules"
for graph in $graphs; do
	num=$(get_num "$graph")
	basedir="$out_dir/$num"
	echo "$num nodes in graph $graph"

	# Generate schedules
	sched_dir="$basedir/sched"
	$PYTHON "$sched_script" "$graph" "$sched_dir"

	# Run sims
	scheds=$(find "$sched_dir" -type f -name "*.json")
	for sched in $scheds; do
		echo "size=$num; running $sched"
		run_emulation "$graph" "$sched"
	done
done
