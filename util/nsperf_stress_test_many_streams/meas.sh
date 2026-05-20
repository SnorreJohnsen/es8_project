#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Arguments
graph_input="${1:-/home/aau/meshsim/testgraphs}"
out_dir="${2:-/home/aau/meshsim/output/nsperf_stress_test_many_streams}"

# Run controls. Override these with environment variables for smaller runs.
losses="${LOSSES:-0}"
target_bitrates="${TARGET_BITRATES:-100k 500k 1M 2M 5M}"
iterations="${ITERATIONS:-10}"
num_streams_sequence="${NUM_STREAMS_SEQUENCE:-1 2 4 6 8 10 15 20 25 30 40}"
graph_pattern="${GRAPH_PATTERN:-triangle_*_nodes.json}"

adapter_rows="${ADAPTER_ROWS:-3}"
adapter_cols="${ADAPTER_COLS:-7}"
adapter_z="${ADAPTER_Z:-0}"
stream_duration="${STREAM_DURATION:-10}"
silence="${SILENCE:-30}"
start_time="${START_TIME:-10}"
seed_base="${SEED_BASE:-nsperf_stress_test_many_streams}"
verbosity="${VERBOSITY:-verbose}"
compress_program="${COMPRESS_PROGRAM:-pigz}"

# Paths
grid_script="${GRID_SCRIPT:-$script_dir/grid.py}"
sched_script="${SCHED_SCRIPT:-$script_dir/sched.py}"
runtime_script="${RUNTIME_SCRIPT:-$script_dir/runtime.py}"
helpers_script="${HELPERS_SCRIPT:-$script_dir/../meshsim_meas_helpers.sh}"
place_adapters_script="${PLACE_ADAPTERS_SCRIPT:-/home/aau/meshsim/repo/mesh_place_adapters.py}"
emulation_script="${EMULATION_SCRIPT:-/home/aau/meshsim/repo/emulation.py}"
network_script="${NETWORK_SCRIPT:-/home/aau/meshsim/repo/meshnet-lab/network.py}"
nsperf_analyze_script="${NSPERF_ANALYZE_SCRIPT:-/home/aau/meshsim/repo/nsperf/tools/analyze.py}"
net_stats_analyze_script="${NET_STATS_ANALYZE_SCRIPT:-/home/aau/meshsim/repo/util/analyze_net_stats.py}"
emulation_dir="${EMULATION_DIR:-${PCAP_DIR:-/home/aau/meshsim/output/emulation}}"
PYTHON="${PYTHON_EXE:-python3}"
runtime_fixed="${RUNTIME_FIXED:-60}"

. "$helpers_script"
pause_file="${PAUSE_FILE:-$(msh_pause_file_default "$out_dir")}"

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

log_dir="$out_dir/logs"
placed_graph_dir="$out_dir/placed_graphs"
grid_meta_dir="$out_dir/grid"
mkdir -p "$log_dir" "$placed_graph_dir" "$grid_meta_dir"

graph_count=$(msh_word_count "$graphs")
loss_count=$(msh_word_count "$losses")
bitrate_count=$(msh_word_count "$target_bitrates")
total_simulations=$((graph_count * loss_count * bitrate_count * iterations))
completed_simulations=0
completed_model_seconds="0"
completed_observed_seconds="0"
script_start_epoch=$(date +%s)
model_total_seconds=$("$PYTHON" "$runtime_script" \
	--graph-input "$graph_input" \
	--graph-pattern "$graph_pattern" \
	--bitrates "$target_bitrates" \
	--num-loss "$loss_count" \
	--num-iters "$iterations" \
	--fixed "$runtime_fixed" \
	--silence "$silence" \
	--streamlen "$stream_duration" \
	--delay "$start_time" \
	--num-streams-sequence "$num_streams_sequence" \
	--output total-seconds)
model_total_duration=$(msh_format_duration "$model_total_seconds")
model_total_seconds_fmt=$(msh_format_seconds_1 "$model_total_seconds")

echo "Running nsperf stress test with many streams"
echo "losses: $losses"
echo "target_bitrates: $target_bitrates"
echo "iterations: $iterations"
echo "num_streams_sequence: $num_streams_sequence"
echo "adapter grid: ${adapter_rows}x${adapter_cols}, z=$adapter_z"
echo "runtime_fixed: $runtime_fixed"
echo "total_simulations: $total_simulations"
echo "model_total_runtime: $model_total_duration (${model_total_seconds_fmt}s)"
echo "pause_file: $pause_file"
echo "to pause before next simulation: touch $pause_file"

graph_idx=0
for graph in $graphs; do
	graph_idx=$((graph_idx + 1))
	graph_file=$(basename "$graph")
	graph_name=${graph_file%.json}
	graph_out_dir="$out_dir/$graph_name"
	placed_graph="$placed_graph_dir/${graph_name}.json"
	grid_meta="$grid_meta_dir/${graph_name}.json"

	echo "[graph=$graph_name] generating adapter grid"
	adapter_pos=$("$PYTHON" "$grid_script" "$graph" \
		--rows "$adapter_rows" \
		--cols "$adapter_cols" \
		--z "$adapter_z" \
		--json "$grid_meta")

	echo "[graph=$graph_name] placing adapters"
	"$PYTHON" "$place_adapters_script" "$graph" --adapter-pos "$adapter_pos" "$placed_graph" --verbosity quiet

	loss_idx=0
	for loss in $losses; do
		loss_idx=$((loss_idx + 1))
		bitrate_idx=0
		for bitrate in $target_bitrates; do
			bitrate_idx=$((bitrate_idx + 1))
			i=1
			while [ "$i" -le "$iterations" ]; do
				msh_pause_before_next_run "$pause_file"

				iter_name=$(printf "iter_%02d" "$i")
				sched_dir="$graph_out_dir/sched/$bitrate/$loss"
				sched="$sched_dir/${iter_name}.json"
				metadata="$sched_dir/${iter_name}.meta.json"
				result_dir="$graph_out_dir/$bitrate/$loss/$iter_name"

				if [ -e "$result_dir" ]; then
					echo "Result directory already exists: $result_dir" >&2
					exit 1
				fi

				echo "[graph=$graph_name; loss=$loss; bitrate=$bitrate; iteration=$i] generating schedule"
				"$PYTHON" "$sched_script" "$placed_graph" "$sched" \
					--metadata-output "$metadata" \
					--graph-name "$graph_name" \
					--loss "$loss" \
					--target-bitrate "$bitrate" \
					--iteration "$i" \
					--num-streams-sequence "$num_streams_sequence" \
					--stream-duration "$stream_duration" \
					--silence "$silence" \
					--start-time "$start_time" \
					--seed-base "$seed_base" \
					--adapter-rows "$adapter_rows" \
					--adapter-cols "$adapter_cols" \
					--adapter-z "$adapter_z"

				timestamp=$(date -u +%Y%m%dT%H%M%SZ)
				logfile="$log_dir/log_${graph_name}_${bitrate}_${loss}_${iter_name}_${timestamp}.txt"
				model_single_runtime_s=$("$PYTHON" "$runtime_script" \
					--graph "$graph" \
					--bitrates "$bitrate" \
					--num-loss 1 \
					--num-iters 1 \
					--fixed "$runtime_fixed" \
					--silence "$silence" \
					--streamlen "$stream_duration" \
					--delay "$start_time" \
					--num-streams-sequence "$num_streams_sequence" \
					--output single-seconds)
				remaining_model_seconds=$(awk -v total="$model_total_seconds" -v completed="$completed_model_seconds" 'BEGIN {
					remaining = total - completed
					if (remaining < 0) {
						remaining = 0
					}
					printf "%.6f", remaining
				}')

				simulation_idx=$((completed_simulations + 1))
				progress_context="graph ${graph_idx}/${graph_count} ${graph_name} | loss ${loss_idx}/${loss_count} ${loss} | bitrate ${bitrate_idx}/${bitrate_count} ${bitrate} | iteration ${i}/${iterations}"
				msh_progress_start_context_model "$script_start_epoch" "$completed_simulations" \
					"$simulation_idx" "$total_simulations" \
					"$progress_context" "$model_single_runtime_s" \
					"$remaining_model_seconds" "$completed_model_seconds" \
					"$completed_observed_seconds"
				run_start_epoch=$(date +%s)
				msh_run_emulation "$placed_graph" "$sched" "$loss" "$logfile" \
					"$emulation_script" "$network_script" "$verbosity" "$PYTHON"

				msh_analyze_all_nsperf "$emulation_dir/nsperf/raw" \
					"$emulation_dir/nsperf/streams" \
					"$nsperf_analyze_script" "$PYTHON"

				msh_analyze_net_stats "$emulation_dir" "$net_stats_analyze_script" "$PYTHON"

				msh_finalize_emulation_output "$emulation_dir" "$result_dir" "$compress_program"

				run_end_epoch=$(date +%s)
				run_elapsed=$((run_end_epoch - run_start_epoch))
				completed_model_seconds=$(awk -v completed="$completed_model_seconds" -v single="$model_single_runtime_s" 'BEGIN {
					printf "%.6f", completed + single
				}')
				completed_observed_seconds=$(awk -v completed="$completed_observed_seconds" -v run="$run_elapsed" 'BEGIN {
					printf "%.6f", completed + run
				}')
				remaining_model_seconds=$(awk -v total="$model_total_seconds" -v completed="$completed_model_seconds" 'BEGIN {
					remaining = total - completed
					if (remaining < 0) {
						remaining = 0
					}
					printf "%.6f", remaining
				}')
				completed_simulations=$((completed_simulations + 1))
				msh_progress_done_model "$script_start_epoch" "$run_start_epoch" \
					"$completed_simulations" "$total_simulations" \
					"$remaining_model_seconds" "$completed_model_seconds" \
					"$completed_observed_seconds"

				i=$((i + 1))
			done

			msh_analyze_net_stats_details_tree "$graph_out_dir/$bitrate/$loss" \
				"$net_stats_analyze_script" "$PYTHON"
		done
	done
done
