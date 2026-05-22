#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Arguments
graph_input="${1:-/home/aau/meshsim/testgraphs}"
out_dir="${2:-/home/aau/meshsim/output/maint_bps}"

# Run controls. Override these with environment variables for smaller runs.
graph_pattern="${GRAPH_PATTERN:-triangle_*_nodes.json}"
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
		mesh_size=$("$PYTHON" -c 'import json, sys; graph = json.load(open(sys.argv[1])); print(sum(1 for node in graph["nodes"] if str(node.get("id", "")).startswith("n")))' "$1")
	fi
	if [ -z "$mesh_size" ] || [ "$mesh_size" -le 0 ]; then
		echo "Could not determine mesh size from graph filename or graph nodes: $1" >&2
		exit 1
	fi
	echo "$mesh_size"
}

log_dir="$out_dir/logs"
sched_dir="$out_dir/sched"
runs_dir="$out_dir/runs"
details_dir="$out_dir/details"
mkdir -p "$log_dir" "$sched_dir" "$runs_dir" "$details_dir"

echo "Running maintenance bitrate test"
echo "duration: $sim_duration"
echo "bucket_size: $bucket_size"

for graph in $graphs; do
	mesh_size=$(get_mesh_size "$graph")
	graph_file=$(basename "$graph")
	graph_name=${graph_file%.json}
	result_dir="$runs_dir/$graph_name"
	sched="$sched_dir/${graph_name}.json"

	if [ -e "$result_dir" ]; then
		echo "Result directory already exists: $result_dir" >&2
		exit 1
	fi

	echo "[graph=$graph_name; mesh_size=$mesh_size] generating empty schedule"
	"$PYTHON" "$sched_script" "$sched" --duration "$sim_duration"

	timestamp=$(date -u +%Y%m%dT%H%M%SZ)
	logfile="$log_dir/log_${graph_name}_${timestamp}.txt"

	echo "[graph=$graph_name; mesh_size=$mesh_size] running simulation"
	msh_run_emulation "$graph" "$sched" "" "$logfile" \
		"$emulation_script" "$network_script" "$verbosity" "$PYTHON" \
		--pcap

	echo "[graph=$graph_name; mesh_size=$mesh_size] analyzing maintenance bitrate"
	"$PYTHON" "$analyze_script" "$emulation_dir" "$mesh_size" "$out_dir" \
		--bucket "$bucket_size" \
		--graph-name "$graph_name" \
		--details-dir "$details_dir"

	msh_finalize_emulation_output "$emulation_dir" "$result_dir" "$compress_program"
done
