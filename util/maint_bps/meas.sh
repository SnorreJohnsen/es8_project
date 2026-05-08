#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Arguments
graph_input="${1:-/home/aau/meshsim/testgraphs}"
out_dir="${2:-/home/aau/meshsim/output/maint_bps}"

# Run controls. Override these with environment variables for smaller runs.
graph_pattern="${GRAPH_PATTERN:-Triangle_network_*_tolerance_*_datarate_Mbps_*_bandwidth_Mhz_*_nodes.json}"
sim_duration="${SIM_DURATION:-300}"
bucket_size="${BUCKET_SIZE:-1}"
verbosity="${VERBOSITY:-verbose}"
compress_program="${COMPRESS_PROGRAM:-pigz}"

# Paths
sched_script="${SCHED_SCRIPT:-$script_dir/sched.py}"
analyze_script="${ANALYZE_SCRIPT:-$script_dir/analyze.py}"
helpers_script="${HELPERS_SCRIPT:-$script_dir/../meshsim_meas_helpers.sh}"
emulation_script="${EMULATION_SCRIPT:-/home/aau/meshsim/repo/emulation.py}"
network_script="${NETWORK_SCRIPT:-/home/aau/meshsim/repo/meshnet-lab/network.py}"
emulation_dir="${EMULATION_DIR:-${PCAP_DIR:-/home/aau/meshsim/output/emulation}}"
PYTHON="${PYTHON_EXE:-python3}"

. "$helpers_script"

if [ -f "$graph_input" ]; then
	graphs="$graph_input"
elif [ -d "$graph_input" ]; then
	graphs=$(find "$graph_input" -type f -name "$graph_pattern" | sort)
else
	echo "Graph input does not exist: $graph_input" >&2
	exit 1
fi

if [ -z "$graphs" ]; then
	echo "No graphs found in $graph_input matching $graph_pattern" >&2
	exit 1
fi

get_mesh_size() {
	mesh_size=$(basename "$1" | grep -o -e '[0-9]\+_nodes' | head -1 | cut -d_ -f1)
	if [ -z "$mesh_size" ]; then
		echo "Could not determine mesh size from graph filename: $1" >&2
		exit 1
	fi
	echo "$mesh_size"
}

log_dir="$out_dir/logs"
sched_dir="$out_dir/sched"
mkdir -p "$log_dir" "$sched_dir"

echo "Running maintenance bitrate test"
echo "duration: $sim_duration"
echo "bucket_size: $bucket_size"

for graph in $graphs; do
	mesh_size=$(get_mesh_size "$graph")
	result_dir="$out_dir/$mesh_size"
	sched="$sched_dir/${mesh_size}.json"

	if [ -e "$result_dir" ]; then
		echo "Result directory already exists: $result_dir" >&2
		exit 1
	fi

	echo "[mesh_size=$mesh_size] generating empty schedule"
	"$PYTHON" "$sched_script" "$sched" --duration "$sim_duration"

	timestamp=$(date -u +%Y%m%dT%H%M%SZ)
	logfile="$log_dir/log_${mesh_size}_${timestamp}.txt"

	echo "[mesh_size=$mesh_size] running simulation"
	msh_run_emulation "$graph" "$sched" "" "$logfile" \
		"$emulation_script" "$network_script" "$verbosity" "$PYTHON"

	echo "[mesh_size=$mesh_size] analyzing maintenance bitrate"
	"$PYTHON" "$analyze_script" "$emulation_dir" "$mesh_size" "$out_dir" --bucket "$bucket_size"

	msh_finalize_emulation_output "$emulation_dir" "$result_dir" "$compress_program"
done
