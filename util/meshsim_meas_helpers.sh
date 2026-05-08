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

	msh_cleanup "$network_script" "$python_exe"
	modprobe batman_adv

	if [ -n "$link_loss" ]; then
		if "$python_exe" "$emulation_script" --sim-sched "$sched" --link-loss "$link_loss" --verbosity "$verbosity" "$graph" >"$logfile" 2>&1; then
			status=0
		else
			status=$?
		fi
	else
		if "$python_exe" "$emulation_script" --sim-sched "$sched" --verbosity "$verbosity" "$graph" >"$logfile" 2>&1; then
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

msh_analyze_all_nsperf() {
	raw_dir="$1"
	out_dir_nsperf="$2"
	nsperf_analyze_script="$3"
	python_exe="${4:-python3}"

	mkdir -p "$out_dir_nsperf"
	client_files=$(find "$raw_dir" -type f -name "*.send.csv")
	for client_file in $client_files; do
		client_filename=$(basename "$client_file")
		stream_id=$(basename "$client_file" .send.csv)
		server_device=$(echo "$client_filename" | cut -d "_" -f 1)
		client_device=$(echo "$client_filename" | cut -d "_" -f 2)
		simtime=$(echo "$client_filename" | cut -d "_" -f 3 | cut -d "." -f 1)
		server_file="${raw_dir}/${server_device}.recv.csv"
		echo "$client_file" "receiver: $server_device" "client: $client_device" "simtime: $simtime" "server_file: $server_file"

		if [ ! -f "$server_file" ]; then
			echo "server file not found: $server_file" >&2
			return 1
		fi

		out="$out_dir_nsperf/${stream_id}.json"
		msh_analyze_nsperf "$nsperf_analyze_script" "$client_file" "$server_file" "$out" "$python_exe"

		for interval in "0.5" "1" "2" "5"; do
			out="$out_dir_nsperf/intervals/${stream_id}_inter_${interval}.json"
			mkdir -p "$out_dir_nsperf/intervals"
			msh_analyze_nsperf "$nsperf_analyze_script" "$client_file" "$server_file" "$out" "$python_exe" "$interval"
		done
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
