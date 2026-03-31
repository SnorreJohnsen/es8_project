#!/bin/sh
set -eu

usage() {
	printf 'Usage: %s INPUT_DIR OUTPUT_FILE [TOLERANCE_SECONDS]\n' "${0##*/}" >&2
	exit 2
}

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || {
		printf 'Error: %s not found in PATH\n' "$1" >&2
		exit 1
	}
}

file_size_bytes() {
	wc -c <"$1" | tr -d '[:space:]'
}

packet_count() {
	capinfos -c -M "$1" 2>/dev/null | awk -F': *' '/Number of packets/ { print $2; exit }'
}

human_size() {
	du -h "$1" | awk '{print $1}'
}

[ "$#" -ge 2 ] && [ "$#" -le 3 ] || usage

input_dir=$1
output=$2
tolerance=${3:-0.001}

[ -d "$input_dir" ] || {
	printf 'Error: input directory does not exist: %s\n' "$input_dir" >&2
	exit 1
}

require_cmd mergecap
require_cmd reordercap
require_cmd editcap
require_cmd capinfos
require_cmd du
require_cmd wc
require_cmd awk

workdir=$(mktemp -d)
cleanup() {
	rm -rf "$workdir"
}
trap cleanup EXIT INT TERM HUP

set -- "$input_dir"/*.pcap
[ -e "$1" ] || {
	printf 'Error: no .pcap files found in: %s\n' "$input_dir" >&2
	exit 1
}

input_count=$#
printf 'Merging %s .pcap file(s)\n' "$input_count"

mergecap -w "$workdir/merged.pcapng" "$@"
reordercap "$workdir/merged.pcapng" "$workdir/merged.sorted.pcapng"

merged_packets=$(packet_count "$workdir/merged.sorted.pcapng")
merged_size_human=$(human_size "$workdir/merged.sorted.pcapng")

printf 'Merged capture: %s, %s packet(s)\n' "$merged_size_human" "$merged_packets"
printf 'Removing duplicate frames (tolerance: %s s)\n' "$tolerance"

editcap -w "$tolerance" "$workdir/merged.sorted.pcapng" "$output"

cleaned_packets=$(packet_count "$output")
cleaned_size_human=$(human_size "$output")

merged_size_bytes=$(file_size_bytes "$workdir/merged.sorted.pcapng")
cleaned_size_bytes=$(file_size_bytes "$output")
removed_packets=$((merged_packets - cleaned_packets))
saved_bytes=$((merged_size_bytes - cleaned_size_bytes))

printf 'Cleaned capture: %s, %s packet(s)\n' "$cleaned_size_human" "$cleaned_packets"
printf 'Removed duplicates: %s packet(s), %s byte(s)\n' "$removed_packets" "$saved_bytes"
