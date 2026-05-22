#!/bin/sh

# Shared helpers for measurement scripts. These functions are intentionally
# argument-driven so individual experiments can keep their own run policy.

msh_cleanup() {
	network_script="$1"
	python_exe="${2:-python3}"

	"$python_exe" "$network_script" clear
	modprobe -r batman_adv 2>/dev/null || true
}

msh_run_emulation() {
	graph="$1"
	sched="$2"
	link_loss="$3"
	logfile="$4"
	emulation_script="$5"
	network_script="$6"
	verbosity="${7:-verbose}"
	python_exe="${8:-python3}"
	shift 8

	msh_cleanup "$network_script" "$python_exe"
	modprobe batman_adv

	if [ -n "$link_loss" ]; then
		if "$python_exe" "$emulation_script" --sim-sched "$sched" --link-loss "$link_loss" --verbosity "$verbosity" "$@" "$graph" >"$logfile" 2>&1; then
			status=0
		else
			status=$?
		fi
	else
		if "$python_exe" "$emulation_script" --sim-sched "$sched" --verbosity "$verbosity" "$@" "$graph" >"$logfile" 2>&1; then
			status=0
		else
			status=$?
		fi
	fi

	msh_cleanup "$network_script" "$python_exe"
	return "$status"
}

msh_analyze_nsperf() {
	nsperf_analyze_script="$1"
	tx="$2"
	rx="$3"
	out="$4"
	python_exe="${5:-python3}"
	interval="${6:-}"

	if [ -n "$interval" ]; then
		"$python_exe" "$nsperf_analyze_script" --interval "$interval" --send "$tx" --recv "$rx" --json >"$out"
	else
		"$python_exe" "$nsperf_analyze_script" --send "$tx" --recv "$rx" --json >"$out"
	fi
}

msh_nsperf_analyze_jobs() {
	jobs="${1:-${NSPERF_ANALYZE_JOBS:-}}"

	if [ -z "$jobs" ]; then
		if command -v nproc >/dev/null 2>&1; then
			jobs=$(nproc)
		else
			jobs=1
		fi
	fi

	case "$jobs" in
	"" | *[!0-9]*)
		jobs=1
		;;
	esac
	if [ "$jobs" -le 0 ]; then
		jobs=1
	fi

	echo "$jobs"
}

msh_analyze_all_nsperf() {
	raw_dir="$1"
	out_dir_nsperf="$2"
	nsperf_analyze_script="$3"
	python_exe="${4:-python3}"
	jobs=$(msh_nsperf_analyze_jobs "${5:-}")
	skip_start_ms="${6:-}"

	mkdir -p "$out_dir_nsperf" "$out_dir_nsperf/intervals"
	echo "Analyzing nsperf streams with $jobs parallel job(s)"
	find "$raw_dir" -type f -name "*.send.csv" -print0 |
		xargs -0 -r -n 1 -P "$jobs" sh -c '
		raw_dir="$1"
		out_dir_nsperf="$2"
		nsperf_analyze_script="$3"
		python_exe="$4"
		skip_start_ms="$5"
		client_file="$6"

		client_filename=$(basename "$client_file")
		stream_id=$(basename "$client_file" .send.csv)
		server_device=$(echo "$client_filename" | cut -d "_" -f 1)
		client_device=$(echo "$client_filename" | cut -d "_" -f 2)
		simtime=$(echo "$client_filename" | cut -d "_" -f 3 | cut -d "." -f 1)
		server_file="${raw_dir}/${server_device}.recv.csv"
		echo "[nsperf:$stream_id]" "$client_file" "receiver: $server_device" "client: $client_device" "simtime: $simtime" "server_file: $server_file"

		if [ ! -f "$server_file" ]; then
			echo "server file not found: $server_file" >&2
			exit 1
		fi

		skip_suffix=""
		if [ -n "$skip_start_ms" ]; then
			skip_suffix="_skip_${skip_start_ms}ms"
			set -- --skip-start-ms "$skip_start_ms"
		else
			set --
		fi

		out="$out_dir_nsperf/${stream_id}${skip_suffix}.json"
		if ! "$python_exe" "$nsperf_analyze_script" "$@" --send "$client_file" --recv "$server_file" --json >"$out"; then
			exit $?
		fi

		for interval in "0.5" "1" "2" "5"; do
			out="$out_dir_nsperf/intervals/${stream_id}_inter_${interval}${skip_suffix}.json"
			if ! "$python_exe" "$nsperf_analyze_script" "$@" --interval "$interval" --send "$client_file" --recv "$server_file" --json >"$out"; then
				exit $?
			fi
		done
	' sh "$raw_dir" "$out_dir_nsperf" "$nsperf_analyze_script" "$python_exe" "$skip_start_ms"
}

msh_analyze_nsperf_tree() {
	src_dir="$1"
	nsperf_analyze_script="$2"
	python_exe="${3:-python3}"
	jobs="${4:-}"
	skip_start_ms="${5:-}"

	if [ -z "$src_dir" ] || [ -z "$nsperf_analyze_script" ]; then
		echo "usage: msh_analyze_nsperf_tree SRC_DIR NSPERF_ANALYZE_SCRIPT [PYTHON_EXE] [JOBS] [SKIP_START_MS]" >&2
		return 2
	fi
	if [ ! -d "$src_dir" ]; then
		echo "source directory not found: $src_dir" >&2
		return 1
	fi

	find "$src_dir" -type d -name raw -path "*/nsperf/raw" |
		sort |
		while IFS= read -r raw_dir; do
			out_dir_nsperf="${raw_dir%/raw}/streams"
			echo "Analyzing nsperf raw dir: $raw_dir -> $out_dir_nsperf"
			msh_analyze_all_nsperf "$raw_dir" "$out_dir_nsperf" \
				"$nsperf_analyze_script" "$python_exe" "$jobs" "$skip_start_ms" || exit $?
		done
}

msh_remove_nsperf_streams_tree() {
	src_dir="$1"

	if [ -z "$src_dir" ]; then
		echo "usage: msh_remove_nsperf_streams_tree SRC_DIR" >&2
		return 2
	fi
	if [ ! -d "$src_dir" ]; then
		echo "source directory not found: $src_dir" >&2
		return 1
	fi

	find "$src_dir" -depth -type d -name streams -path "*/nsperf/streams" |
		sort -r |
		while IFS= read -r streams_dir; do
			echo "Removing nsperf streams dir: $streams_dir"
			rm -rf "$streams_dir" || exit $?
		done
}

msh_analyze_access_node_fail() {
	run_dir="$1"
	analyze_script="$2"
	python_exe="${3:-python3}"
	aggregate_csv="${4:-}"
	latex_output="${5:-}"
	violin_output="${6:-}"

	if [ -z "$run_dir" ] || [ -z "$analyze_script" ]; then
		echo "usage: msh_analyze_access_node_fail RUN_DIR ANALYZE_SCRIPT [PYTHON_EXE] [AGGREGATE_CSV] [LATEX_OUTPUT] [VIOLIN_OUTPUT]" >&2
		return 2
	fi
	if [ -n "$latex_output" ] && [ -z "$aggregate_csv" ]; then
		echo "LATEX_OUTPUT requires AGGREGATE_CSV" >&2
		return 2
	fi
	if [ -n "$violin_output" ] && [ -z "$aggregate_csv" ]; then
		echo "VIOLIN_OUTPUT requires AGGREGATE_CSV" >&2
		return 2
	fi
	if [ ! -d "$run_dir" ]; then
		echo "access-node fail run directory not found: $run_dir" >&2
		return 1
	fi
	if [ ! -f "$analyze_script" ]; then
		echo "access-node fail analyzer script not found: $analyze_script" >&2
		return 1
	fi
	if [ ! -f "$run_dir/sim_sched.json" ]; then
		echo "sim schedule not found: $run_dir/sim_sched.json" >&2
		return 1
	fi
	if [ ! -d "$run_dir/nsperf/streams/intervals" ]; then
		echo "nsperf interval analysis directory not found: $run_dir/nsperf/streams/intervals" >&2
		return 1
	fi

	echo "Analyzing access-node fail run: $run_dir"
	if [ -n "$aggregate_csv" ]; then
		set -- "$run_dir" --aggregate-csv "$aggregate_csv"
		if [ -n "$latex_output" ]; then
			set -- "$@" --latex-output "$latex_output"
		fi
		if [ -n "$violin_output" ]; then
			set -- "$@" --violin-output "$violin_output"
		fi
		"$python_exe" "$analyze_script" "$@"
	else
		"$python_exe" "$analyze_script" "$run_dir"
	fi
}

msh_analyze_access_node_fail_tree() {
	src_dir="$1"
	analyze_script="$2"
	python_exe="${3:-python3}"

	if [ -z "$src_dir" ] || [ -z "$analyze_script" ]; then
		echo "usage: msh_analyze_access_node_fail_tree SRC_DIR ANALYZE_SCRIPT [PYTHON_EXE]" >&2
		return 2
	fi
	if [ ! -d "$src_dir" ]; then
		echo "source directory not found: $src_dir" >&2
		return 1
	fi
	if [ ! -f "$analyze_script" ]; then
		echo "access-node fail analyzer script not found: $analyze_script" >&2
		return 1
	fi

	aggregate_csv="$src_dir/access_node_fail_summary.csv"
	latex_output="$src_dir/access_node_fail_table.tex"
	violin_output="$src_dir/access_node_fail_recovery_violinplot.png"
	find "$src_dir" -type f -name sim_sched.json |
		sort |
		while IFS= read -r sched_json; do
			run_dir=$(dirname "$sched_json")
			if [ ! -d "$run_dir/nsperf/streams/intervals" ]; then
				echo "Skipping access-node fail run without nsperf intervals: $run_dir" >&2
				continue
			fi

			msh_analyze_access_node_fail "$run_dir" "$analyze_script" \
				"$python_exe" "$aggregate_csv" "$latex_output" "$violin_output" || exit $?
		done
}

msh_remove_access_node_fail_analysis_tree() {
	src_dir="$1"

	if [ -z "$src_dir" ]; then
		echo "usage: msh_remove_access_node_fail_analysis_tree SRC_DIR" >&2
		return 2
	fi
	if [ ! -d "$src_dir" ]; then
		echo "source directory not found: $src_dir" >&2
		return 1
	fi

	if [ -f "$src_dir/access_node_fail_summary.csv" ]; then
		echo "Removing access-node fail aggregate: $src_dir/access_node_fail_summary.csv"
		rm -f "$src_dir/access_node_fail_summary.csv" || return $?
	fi
	if [ -f "$src_dir/access_node_fail_table.tex" ]; then
		echo "Removing access-node fail LaTeX table: $src_dir/access_node_fail_table.tex"
		rm -f "$src_dir/access_node_fail_table.tex" || return $?
	fi
	if [ -f "$src_dir/access_node_fail_recovery_violinplot.png" ]; then
		echo "Removing access-node fail violin plot: $src_dir/access_node_fail_recovery_violinplot.png"
		rm -f "$src_dir/access_node_fail_recovery_violinplot.png" || return $?
	fi

	find "$src_dir" -type f \( -name access_node_fail_summary.json -o -name access_node_fail_throughput.png -o -name access_node_fail_throughput_latency.png \) |
		sort -r |
		while IFS= read -r artifact; do
			echo "Removing access-node fail analysis artifact: $artifact"
			rm -f "$artifact" || exit $?
		done
}

msh_analyze_reroute() {
	run_dir="$1"
	analyze_script="$2"
	python_exe="${3:-python3}"
	aggregate_csv="${4:-}"
	latex_output="${5:-}"

	if [ -z "$run_dir" ] || [ -z "$analyze_script" ]; then
		echo "usage: msh_analyze_reroute RUN_DIR ANALYZE_SCRIPT [PYTHON_EXE] [AGGREGATE_CSV] [LATEX_OUTPUT]" >&2
		return 2
	fi
	if [ -n "$latex_output" ] && [ -z "$aggregate_csv" ]; then
		echo "LATEX_OUTPUT requires AGGREGATE_CSV" >&2
		return 2
	fi
	if [ ! -d "$run_dir" ]; then
		echo "reroute run directory not found: $run_dir" >&2
		return 1
	fi
	if [ ! -f "$analyze_script" ]; then
		echo "reroute analyzer script not found: $analyze_script" >&2
		return 1
	fi
	if [ ! -f "$run_dir/sim_sched.json" ]; then
		echo "sim schedule not found: $run_dir/sim_sched.json" >&2
		return 1
	fi
	if [ ! -d "$run_dir/nsperf/streams/intervals" ]; then
		echo "nsperf interval analysis directory not found: $run_dir/nsperf/streams/intervals" >&2
		return 1
	fi

	echo "Analyzing reroute run: $run_dir"
	if [ -n "$aggregate_csv" ]; then
		if [ -n "$latex_output" ]; then
			"$python_exe" "$analyze_script" "$run_dir" \
				--aggregate-csv "$aggregate_csv" \
				--latex-output "$latex_output"
		else
			"$python_exe" "$analyze_script" "$run_dir" --aggregate-csv "$aggregate_csv"
		fi
	else
		"$python_exe" "$analyze_script" "$run_dir"
	fi
}

msh_analyze_reroute_tree() {
	src_dir="$1"
	analyze_script="$2"
	python_exe="${3:-python3}"

	if [ -z "$src_dir" ] || [ -z "$analyze_script" ]; then
		echo "usage: msh_analyze_reroute_tree SRC_DIR ANALYZE_SCRIPT [PYTHON_EXE]" >&2
		return 2
	fi
	if [ ! -d "$src_dir" ]; then
		echo "source directory not found: $src_dir" >&2
		return 1
	fi
	if [ ! -f "$analyze_script" ]; then
		echo "reroute analyzer script not found: $analyze_script" >&2
		return 1
	fi

	aggregate_csv="$src_dir/reroute_summary.csv"
	latex_output="$src_dir/reroute_table.tex"
	find "$src_dir" -type f -name sim_sched.json |
		sort |
		while IFS= read -r sched_json; do
			run_dir=$(dirname "$sched_json")
			if [ ! -d "$run_dir/nsperf/streams/intervals" ]; then
				echo "Skipping reroute run without nsperf intervals: $run_dir" >&2
				continue
			fi

			msh_analyze_reroute "$run_dir" "$analyze_script" \
				"$python_exe" "$aggregate_csv" "$latex_output" || exit $?
		done
}

msh_remove_reroute_analysis_tree() {
	src_dir="$1"

	if [ -z "$src_dir" ]; then
		echo "usage: msh_remove_reroute_analysis_tree SRC_DIR" >&2
		return 2
	fi
	if [ ! -d "$src_dir" ]; then
		echo "source directory not found: $src_dir" >&2
		return 1
	fi

	if [ -f "$src_dir/reroute_summary.csv" ]; then
		echo "Removing reroute aggregate: $src_dir/reroute_summary.csv"
		rm -f "$src_dir/reroute_summary.csv" || return $?
	fi
	if [ -f "$src_dir/reroute_table.tex" ]; then
		echo "Removing reroute LaTeX table: $src_dir/reroute_table.tex"
		rm -f "$src_dir/reroute_table.tex" || return $?
	fi

	find "$src_dir" -type f \( -name reroute_summary.json -o -name reroute_throughput.png -o -name reroute_throughput_latency.png \) |
		sort -r |
		while IFS= read -r artifact; do
			echo "Removing reroute analysis artifact: $artifact"
			rm -f "$artifact" || exit $?
		done
}

msh_analyze_net_stats() {
	emulation_dir="$1"
	net_stats_analyze_script="${2:-${NET_STATS_ANALYZE_SCRIPT:-/home/aau/meshsim/repo/util/analyze_net_stats.py}}"
	python_exe="${3:-python3}"

	if [ -z "$emulation_dir" ]; then
		echo "usage: msh_analyze_net_stats EMULATION_DIR [NET_STATS_ANALYZE_SCRIPT] [PYTHON_EXE]" >&2
		return 2
	fi
	if [ ! -d "$emulation_dir" ]; then
		echo "emulation directory not found: $emulation_dir" >&2
		return 1
	fi
	if [ ! -f "$net_stats_analyze_script" ]; then
		echo "net stats analyzer script not found: $net_stats_analyze_script" >&2
		return 1
	fi
	if [ ! -d "$emulation_dir/net_stats/before" ]; then
		echo "net stats before snapshot directory not found: $emulation_dir/net_stats/before" >&2
		return 1
	fi
	if [ ! -d "$emulation_dir/net_stats/after" ]; then
		echo "net stats after snapshot directory not found: $emulation_dir/net_stats/after" >&2
		return 1
	fi

	echo "Analyzing net stats: $emulation_dir -> $emulation_dir/net_stats/details.json"
	"$python_exe" "$net_stats_analyze_script" "$emulation_dir"
}

msh_analyze_net_stats_tree() {
	src_dir="$1"
	net_stats_analyze_script="${2:-${NET_STATS_ANALYZE_SCRIPT:-/home/aau/meshsim/repo/util/analyze_net_stats.py}}"
	python_exe="${3:-python3}"

	if [ -z "$src_dir" ]; then
		echo "usage: msh_analyze_net_stats_tree SRC_DIR [NET_STATS_ANALYZE_SCRIPT] [PYTHON_EXE]" >&2
		return 2
	fi
	if [ ! -d "$src_dir" ]; then
		echo "source directory not found: $src_dir" >&2
		return 1
	fi
	if [ ! -f "$net_stats_analyze_script" ]; then
		echo "net stats analyzer script not found: $net_stats_analyze_script" >&2
		return 1
	fi

	find "$src_dir" -type d -path "*/net_stats/before" |
		sort |
		while IFS= read -r before_dir; do
			net_stats_dir="${before_dir%/before}"
			emulation_dir="${net_stats_dir%/net_stats}"
			if [ ! -d "$net_stats_dir/after" ]; then
				continue
			fi

			msh_analyze_net_stats "$emulation_dir" "$net_stats_analyze_script" "$python_exe" || exit $?
		done
}

msh_analyze_net_stats_details_tree() {
	src_dir="$1"
	net_stats_analyze_script="${2:-${NET_STATS_ANALYZE_SCRIPT:-/home/aau/meshsim/repo/util/analyze_net_stats.py}}"
	python_exe="${3:-python3}"

	if [ -z "$src_dir" ]; then
		echo "usage: msh_analyze_net_stats_details_tree SRC_DIR [NET_STATS_ANALYZE_SCRIPT] [PYTHON_EXE]" >&2
		return 2
	fi
	if [ ! -d "$src_dir" ]; then
		echo "source directory not found: $src_dir" >&2
		return 1
	fi
	if [ ! -f "$net_stats_analyze_script" ]; then
		echo "net stats analyzer script not found: $net_stats_analyze_script" >&2
		return 1
	fi

	echo "Aggregating net stats details tree: $src_dir -> $src_dir/net_stats_summary.csv"
	"$python_exe" "$net_stats_analyze_script" --details-tree "$src_dir"
}

msh_pause_file_default() {
	out_dir="$1"
	echo "$out_dir/PAUSE"
}

msh_pause_before_next_run() {
	pause_file="$1"

	if [ ! -e "$pause_file" ]; then
		return 0
	fi

	printf "\n[pause] pause marker exists: %s\n" "$pause_file"
	printf "[pause] pausing before next run. Press Enter/c to continue, or q to exit cleanly.\n"

	while [ -e "$pause_file" ]; do
		printf "[pause] continue or quit? [c/q] "
		if [ -t 0 ]; then
			if IFS= read -r answer; then
				:
			else
				answer="q"
			fi
		elif (: </dev/tty) 2>/dev/null; then
			if IFS= read -r answer </dev/tty; then
				:
			else
				answer="q"
			fi
		else
			if IFS= read -r answer; then
				:
			else
				answer="q"
			fi
		fi

		case "$answer" in
		"" | c | C | continue | Continue | CONTINUE)
			rm -f "$pause_file"
			printf "[pause] removed pause marker and continuing: %s\n" "$pause_file"
			return 0
			;;
		q | Q | quit | Quit | QUIT | exit | Exit | EXIT)
			printf "[pause] exiting cleanly before starting the next run.\n"
			exit 0
			;;
		*)
			printf "[pause] unknown response: %s\n" "$answer"
			;;
		esac
	done
}

msh_word_count() {
	words="${1:-}"
	if [ -z "$words" ]; then
		echo 0
		return
	fi

	set -- $words
	echo "$#"
}

msh_format_duration() {
	seconds="${1:-0}"
	seconds=${seconds%.*}
	if [ -z "$seconds" ]; then
		seconds=0
	fi

	hours=$((seconds / 3600))
	minutes=$(((seconds % 3600) / 60))
	secs=$((seconds % 60))
	printf "%02d:%02d:%02d\n" "$hours" "$minutes" "$secs"
}

msh_epoch_utc() {
	epoch="$1"
	if out=$(date -u -d "@$epoch" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null); then
		echo "$out"
	elif out=$(date -u -r "$epoch" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null); then
		echo "$out"
	else
		echo "${epoch}s_epoch"
	fi
}

msh_progress_eta() {
	start_epoch="$1"
	completed="$2"
	total="$3"

	if [ "$completed" -le 0 ]; then
		printf "avg n/a | eta n/a\n"
		return
	fi

	now_epoch=$(date +%s)
	elapsed=$((now_epoch - start_epoch))
	remaining=$((total - completed))
	avg=$(awk -v elapsed="$elapsed" -v completed="$completed" 'BEGIN { printf "%.1f", elapsed / completed }')
	eta_epoch=$(awk -v now="$now_epoch" -v elapsed="$elapsed" -v completed="$completed" -v remaining="$remaining" 'BEGIN { printf "%d", now + ((elapsed / completed) * remaining) }')
	eta=$(msh_epoch_utc "$eta_epoch")
	printf "avg %ss/run | eta %s\n" "$avg" "$eta"
}

msh_progress_start() {
	script_start_epoch="$1"
	completed="$2"
	simulation_idx="$3"
	total_simulations="$4"
	graph_idx="$5"
	graph_count="$6"
	graph_name="$7"
	loss_idx="$8"
	loss_count="$9"
	shift 9
	loss="$1"
	bitrate_idx="$2"
	bitrate_count="$3"
	bitrate="$4"
	iteration="$5"
	iterations="$6"

	now_epoch=$(date +%s)
	elapsed=$(msh_format_duration "$((now_epoch - script_start_epoch))")
	eta=$(msh_progress_eta "$script_start_epoch" "$completed" "$total_simulations")

	printf "[progress] starting simulation %s/%s | graph %s/%s %s | loss %s/%s %s | bitrate %s/%s %s | iteration %s/%s | elapsed %s | %s\n" \
		"$simulation_idx" "$total_simulations" \
		"$graph_idx" "$graph_count" "$graph_name" \
		"$loss_idx" "$loss_count" "$loss" \
		"$bitrate_idx" "$bitrate_count" "$bitrate" \
		"$iteration" "$iterations" \
		"$elapsed" "$eta"
}

msh_progress_start_context() {
	script_start_epoch="$1"
	completed="$2"
	simulation_idx="$3"
	total_simulations="$4"
	context="$5"

	now_epoch=$(date +%s)
	elapsed=$(msh_format_duration "$((now_epoch - script_start_epoch))")
	eta=$(msh_progress_eta "$script_start_epoch" "$completed" "$total_simulations")

	printf "[progress] starting simulation %s/%s | %s | elapsed %s | %s\n" \
		"$simulation_idx" "$total_simulations" "$context" "$elapsed" "$eta"
}

msh_format_seconds_1() {
	seconds="${1:-0}"
	awk -v seconds="$seconds" 'BEGIN { printf "%.1f", seconds + 0 }'
}

msh_progress_model_eta() {
	remaining_model_seconds="${1:-0}"
	completed_model_seconds="${2:-0}"
	completed_observed_seconds="${3:-0}"

	scale=$(awk -v model="$completed_model_seconds" -v observed="$completed_observed_seconds" 'BEGIN {
		if (model > 0) {
			printf "%.3f", observed / model
		} else {
			printf "1.000"
		}
	}')
	scaled_remaining=$(awk -v remaining="$remaining_model_seconds" -v scale="$scale" 'BEGIN {
		remaining = remaining + 0
		if (remaining < 0) {
			remaining = 0
		}
		printf "%d", remaining * scale
	}')
	now_epoch=$(date +%s)
	eta_epoch=$((now_epoch + scaled_remaining))
	eta=$(msh_epoch_utc "$eta_epoch")
	remaining_fmt=$(msh_format_duration "$scaled_remaining")

	printf "model_scale %sx | model_remaining %s | model_eta %s\n" \
		"$scale" "$remaining_fmt" "$eta"
}

msh_progress_start_context_model() {
	script_start_epoch="$1"
	completed="$2"
	simulation_idx="$3"
	total_simulations="$4"
	context="$5"
	model_single_seconds="$6"
	remaining_model_seconds="$7"
	completed_model_seconds="$8"
	completed_observed_seconds="$9"

	now_epoch=$(date +%s)
	elapsed=$(msh_format_duration "$((now_epoch - script_start_epoch))")
	model_eta=$(msh_progress_model_eta \
		"$remaining_model_seconds" \
		"$completed_model_seconds" \
		"$completed_observed_seconds")
	model_single_fmt=$(msh_format_duration "$model_single_seconds")
	model_single_s=$(msh_format_seconds_1 "$model_single_seconds")

	printf "[progress] starting simulation %s/%s | %s | elapsed %s | model_single %s (%ss) | %s\n" \
		"$simulation_idx" "$total_simulations" "$context" "$elapsed" \
		"$model_single_fmt" "$model_single_s" "$model_eta"
}

msh_progress_done_model() {
	script_start_epoch="$1"
	run_start_epoch="$2"
	completed="$3"
	total_simulations="$4"
	remaining_model_seconds="$5"
	completed_model_seconds="$6"
	completed_observed_seconds="$7"

	now_epoch=$(date +%s)
	run_duration=$(msh_format_duration "$((now_epoch - run_start_epoch))")
	elapsed=$(msh_format_duration "$((now_epoch - script_start_epoch))")
	model_eta=$(msh_progress_model_eta \
		"$remaining_model_seconds" \
		"$completed_model_seconds" \
		"$completed_observed_seconds")

	printf "[progress] completed simulation %s/%s | run %s | elapsed %s | %s\n" \
		"$completed" "$total_simulations" "$run_duration" "$elapsed" "$model_eta"
}

msh_progress_done() {
	script_start_epoch="$1"
	run_start_epoch="$2"
	completed="$3"
	total_simulations="$4"

	now_epoch=$(date +%s)
	run_duration=$(msh_format_duration "$((now_epoch - run_start_epoch))")
	elapsed=$(msh_format_duration "$((now_epoch - script_start_epoch))")
	eta=$(msh_progress_eta "$script_start_epoch" "$completed" "$total_simulations")

	printf "[progress] completed simulation %s/%s | run %s | elapsed %s | %s\n" \
		"$completed" "$total_simulations" "$run_duration" "$elapsed" "$eta"
}

msh_compress_pcaps() {
	emulation_dir="$1"
	compress_program="${2:-pigz}"

	if [ -d "$emulation_dir/pcaps" ]; then
		tar -c --use-compress-program="$compress_program" -f "$emulation_dir/pcaps.tar.gz" -C "$emulation_dir" "pcaps"
		rm -rf "$emulation_dir/pcaps"
	fi
}

msh_move_emulation_output() {
	emulation_dir="$1"
	result_dir="$2"

	if [ -e "$result_dir" ]; then
		echo "Result directory already exists: $result_dir" >&2
		return 1
	fi

	mkdir -p "$(dirname "$result_dir")"
	mv "$emulation_dir" "$result_dir"
}

msh_finalize_emulation_output() {
	emulation_dir="$1"
	result_dir="$2"
	compress_program="${3:-pigz}"

	msh_compress_pcaps "$emulation_dir" "$compress_program"
	msh_move_emulation_output "$emulation_dir" "$result_dir"
}
