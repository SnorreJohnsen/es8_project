#!/bin/sh
set -eu

usage() {
	printf 'Usage: %s INPUT_DIR OUTPUT_FILE [TOLERANCE_SECONDS]\n' "${0##*/}" >&2
	exit 2
}

[ "$#" -ge 2 ] && [ "$#" -le 3 ] || usage

input_dir=$1
output=$2
tolerance=${3:-0.001}

[ -d "$input_dir" ] || {
	printf 'Error: input directory does not exist: %s\n' "$input_dir" >&2
	exit 1
}

command -v mergecap >/dev/null 2>&1 || {
	printf 'Error: mergecap not found in PATH\n' >&2
	exit 1
}
command -v reordercap >/dev/null 2>&1 || {
	printf 'Error: reordercap not found in PATH\n' >&2
	exit 1
}
command -v editcap >/dev/null 2>&1 || {
	printf 'Error: editcap not found in PATH\n' >&2
	exit 1
}

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

mergecap -w "$workdir/merged.pcapng" "$@"
reordercap "$workdir/merged.pcapng" "$workdir/merged.sorted.pcapng"
editcap -w "$tolerance" "$workdir/merged.sorted.pcapng" "$output"
