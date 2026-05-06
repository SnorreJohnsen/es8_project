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
		server_device=$(echo "$client_filename" | cut -d "_" -f 1)
		client_device=$(echo "$client_filename" | cut -d "_" -f 2)
		simtime=$(echo "$client_filename" | cut -d "_" -f 3 | cut -d "." -f 1)
		server_file="${raw_dir}/${server_device}.recv.csv"
		echo "$client_file" "receiver: $server_device" "client: $client_device" "simtime: $simtime" "server_file: $server_file"

		if [ ! -f "$server_file" ]; then
			echo "server file not found: $server_file" >&2
			return 1
		fi

		out="$out_dir_nsperf/${server_device}_${client_device}_${simtime}.json"
		msh_analyze_nsperf "$nsperf_analyze_script" "$client_file" "$server_file" "$out" "$python_exe"

		for interval in "0.5" "1" "2" "5"; do
			out="$out_dir_nsperf/intervals/${server_device}_${client_device}_${simtime}_inter_${interval}.json"
			mkdir -p "$out_dir_nsperf/intervals"
			msh_analyze_nsperf "$nsperf_analyze_script" "$client_file" "$server_file" "$out" "$python_exe" "$interval"
		done
	done
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
