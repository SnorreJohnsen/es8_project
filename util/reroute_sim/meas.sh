#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Arguments
out_dir="${1:-/home/aau/meshsim/output/reroute_sim}"

graph="${GRAPH:-$script_dir/graph.json}"
sched="${SCHED:-$script_dir/sched.json}"

# Run controls. Override these with environment variables for smaller runs.
iterations="${ITERATIONS:-10}"
nsperf_skip_ms="${NSPERF_SKIP_MS:-}"

verbosity="${VERBOSITY:-verbose}"
compress_program="${COMPRESS_PROGRAM:-pigz}"

# Paths
helpers_script="${HELPERS_SCRIPT:-$script_dir/../meshsim_meas_helpers.sh}"
emulation_script="${EMULATION_SCRIPT:-/home/aau/meshsim/repo/emulation.py}"
network_script="${NETWORK_SCRIPT:-/home/aau/meshsim/repo/meshnet-lab/network.py}"
nsperf_analyze_script="${NSPERF_ANALYZE_SCRIPT:-/home/aau/meshsim/repo/nsperf/tools/analyze.py}"
emulation_dir="${EMULATION_DIR:-${PCAP_DIR:-/home/aau/meshsim/output/emulation}}"
PYTHON="${PYTHON_EXE:-python3}"

. "$helpers_script"

case "$iterations" in
"" | *[!0-9]*)
	echo "ITERATIONS must be a positive integer, got: $iterations" >&2
	exit 1
	;;
esac
if [ "$iterations" -le 0 ]; then
	echo "ITERATIONS must be > 0, got: $iterations" >&2
	exit 1
fi

if [ ! -f "$graph" ]; then
	echo "Graph file does not exist: $graph" >&2
	exit 1
fi
if [ ! -f "$sched" ]; then
	echo "Schedule file does not exist: $sched" >&2
	exit 1
fi

link_loss="0"
log_dir="$out_dir/logs"
mkdir -p "$log_dir"

echo "Running reroute simulation"
echo "graph: $graph"
echo "schedule: $sched"
echo "iterations: $iterations"
echo "link_loss: $link_loss"
if [ -n "$nsperf_skip_ms" ]; then
	echo "nsperf_skip_ms: $nsperf_skip_ms"
fi

completed_simulations=0
total_simulations="$iterations"
script_start_epoch=$(date +%s)

i=1
while [ "$i" -le "$iterations" ]; do
	iter_name=$(printf "iter_%02d" "$i")
	result_dir="$out_dir/$iter_name"

	if [ -e "$result_dir" ]; then
		echo "Result directory already exists: $result_dir" >&2
		exit 1
	fi

	timestamp=$(date -u +%Y%m%dT%H%M%SZ)
	logfile="$log_dir/log_${iter_name}_${timestamp}.txt"

	simulation_idx=$((completed_simulations + 1))
	msh_progress_start_context "$script_start_epoch" "$completed_simulations" \
		"$simulation_idx" "$total_simulations" \
		"iteration ${i}/${iterations}"

	run_start_epoch=$(date +%s)
	msh_run_emulation "$graph" "$sched" "$link_loss" "$logfile" \
		"$emulation_script" "$network_script" "$verbosity" "$PYTHON"

	msh_analyze_all_nsperf "$emulation_dir/nsperf/raw" \
		"$emulation_dir/nsperf/streams" \
		"$nsperf_analyze_script" "$PYTHON" "" "$nsperf_skip_ms"

	msh_finalize_emulation_output "$emulation_dir" "$result_dir" "$compress_program"

	completed_simulations=$((completed_simulations + 1))
	msh_progress_done "$script_start_epoch" "$run_start_epoch" \
		"$completed_simulations" "$total_simulations"

	i=$((i + 1))
done
