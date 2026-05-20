#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Arguments
graph_input="${1:-/home/aau/meshsim/testgraphs}"
out_dir="${2:-/home/aau/meshsim/output/access_node_fail_test}"

# Run controls. Override these with environment variables for smaller runs.
losses="${LOSSES:-0 0.05 0.1}"
clients="${CLIENTS:-d0 d1 d2 d3 d4}"
servers="${SERVERS:-d0 d1 d2 d3 d4}"
skip_self="${SKIP_SELF:-true}"
graph_pattern="${GRAPH_PATTERN:-Triangle_network_*_tolerance_*_datarate_Mbps_*_bandwidth_Mhz_*_nodes.json}"

sim_duration="${SIM_DURATION:-60}"
stream_duration="${STREAM_DURATION:-60s}"
down_time="${DOWN_TIME:-10}"
up_time="${UP_TIME:-20}"
bitrate="${BITRATE:-1M}"
access_adapter="${ACCESS_ADAPTER:-a0}"
verbosity="${VERBOSITY:-verbose}"
compress_program="${COMPRESS_PROGRAM:-pigz}"

# Paths
sched_script="${SCHED_SCRIPT:-$script_dir/sched.py}"
analyze_script="${ANALYZE_SCRIPT:-$script_dir/analyze.py}"
helpers_script="${HELPERS_SCRIPT:-$script_dir/../meshsim_meas_helpers.sh}"
emulation_script="${EMULATION_SCRIPT:-/home/aau/meshsim/repo/emulation.py}"
network_script="${NETWORK_SCRIPT:-/home/aau/meshsim/repo/meshnet-lab/network.py}"
nsperf_analyze_script="${NSPERF_ANALYZE_SCRIPT:-/home/aau/meshsim/repo/nsperf/tools/analyze.py}"
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

include_self_arg=""
if [ "$skip_self" = "false" ]; then
	include_self_arg="--include-self"
fi

log_dir="$out_dir/logs"
mkdir -p "$log_dir"

echo "Running access-node fail test"
echo "losses: $losses"
echo "clients: $clients"
echo "servers: $servers"
echo "skip_self: $skip_self"

for graph in $graphs; do
	graph_file=$(basename "$graph")
	graph_name=${graph_file%.json}
	graph_out_dir="$out_dir/$graph_name"
	sched_dir="$graph_out_dir/sched"

	echo "[graph=$graph_name] generating schedules"
	# clients/servers/include_self_arg are intentionally word-split into argv lists.
	"$PYTHON" "$sched_script" "$graph" "$sched_dir" \
		--clients $clients \
		--servers $servers \
		$include_self_arg \
		--access-adapter "$access_adapter" \
		--down-time "$down_time" \
		--up-time "$up_time" \
		--duration "$sim_duration" \
		--stream-duration "$stream_duration" \
		--bitrate "$bitrate"

	scheds=$(find "$sched_dir" -type f -name "*.json" | sort)
	for sched in $scheds; do
		stream=$(basename "$sched" .json)
		for loss in $losses; do
			result_dir="$graph_out_dir/$stream/$loss"
			if [ -e "$result_dir" ]; then
				echo "Result directory already exists: $result_dir" >&2
				exit 1
			fi

			timestamp=$(date -u +%Y%m%dT%H%M%SZ)
			logfile="$log_dir/log_${graph_name}_${stream}_${loss}_${timestamp}.txt"

			echo "[graph=$graph_name; stream=$stream; loss=$loss] running"
			msh_run_emulation "$graph" "$sched" "$loss" "$logfile" \
				"$emulation_script" "$network_script" "$verbosity" "$PYTHON"

			msh_analyze_all_nsperf "$emulation_dir/nsperf/raw" \
				"$emulation_dir/nsperf/streams" \
				"$nsperf_analyze_script" "$PYTHON"

			msh_finalize_emulation_output "$emulation_dir" "$result_dir" "$compress_program"

			msh_analyze_access_node_fail "$result_dir" "$analyze_script" \
				"$PYTHON" "$out_dir/access_node_fail_summary.csv"
		done
	done
done
