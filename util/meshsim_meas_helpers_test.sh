#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
helpers_script="$script_dir/meshsim_meas_helpers.sh"
net_stats_analyze_script="$repo_root/util/analyze_net_stats.py"
PYTHON="${PYTHON_EXE:-python3}"

. "$helpers_script"

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

write_snapshot() {
	path="$1"
	mkdir -p "$(dirname "$path")"
	{
		echo "timestamp: 2026-05-20T12:00:00+02:00"
		echo "namespace: ns-n0"
		echo "interface: uplink"
		echo "command: test"
		echo "returncode: 0"
		echo
		echo "stdout:"
		cat
		echo
		echo "stderr:"
	} >"$path"
}

write_sysfs_json() {
	path="$1"
	rx_bytes="$2"
	tx_bytes="$3"
	mkdir -p "$(dirname "$path")"
	cat >"$path" <<EOF
{"rx_bytes": $rx_bytes, "tx_bytes": $tx_bytes}
EOF
}

build_net_stats_fixture() {
	emulation_dir="$1"
	before="$emulation_dir/net_stats/before/ns-n0"
	after="$emulation_dir/net_stats/after/ns-n0"

	write_snapshot "$before/uplink_ip.txt" <<'EOF'
2: uplink@if3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    link/ether 02:00:00:00:00:01 brd ff:ff:ff:ff:ff:ff
    RX: bytes  packets  errors  dropped missed  mcast
    100 10 0 1 0 2
    TX: bytes  packets  errors  dropped carrier collsns
    200 20 1 2 3 4
EOF
	write_snapshot "$after/uplink_ip.txt" <<'EOF'
2: uplink@if3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    link/ether 02:00:00:00:00:01 brd ff:ff:ff:ff:ff:ff
    RX: bytes  packets  errors  dropped missed  mcast
    150 14 0 3 0 2
    TX: bytes  packets  errors  dropped carrier collsns
    275 25 1 6 3 4
EOF
	write_snapshot "$before/uplink_tc.txt" <<'EOF'
qdisc netem 8001: dev uplink root refcnt 2 limit 1000
 Sent 1000 bytes 10 pkt (dropped 1, overlimits 2 requeues 3)
 backlog 4b 5p requeues 6
EOF
	write_snapshot "$after/uplink_tc.txt" <<'EOF'
qdisc netem 8001: dev uplink root refcnt 2 limit 1000
 Sent 1500 bytes 16 pkt (dropped 4, overlimits 6 requeues 8)
 backlog 12b 14p requeues 18
EOF
	write_sysfs_json "$before/uplink_sysfs.json" 100 200
	write_sysfs_json "$after/uplink_sysfs.json" 160 260
}

assert_details() {
	details_path="$1"
	"$PYTHON" - "$details_path" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    details = json.load(f)

uplink = details["ns-n0"]["uplink"]
assert uplink["ip"]["rx_bytes"] == 50
assert uplink["ip"]["rx_dropped"] == 2
assert uplink["ip"]["tx_bytes"] == 75
assert uplink["ip"]["tx_dropped"] == 4
assert uplink["sysfs"] == {"rx_bytes": 60, "tx_bytes": 60}
assert uplink["tc"]["sent_bytes"] == 500
assert uplink["tc"]["sent_packets"] == 6
assert uplink["tc"]["dropped"] == 3
assert uplink["tc"]["backlog_bytes"] == 8
PY
}

single_dir="$tmp_dir/single"
build_net_stats_fixture "$single_dir"
msh_analyze_net_stats "$single_dir" "$net_stats_analyze_script" "$PYTHON"
test -f "$single_dir/net_stats/details.json"
assert_details "$single_dir/net_stats/details.json"

tree_dir="$tmp_dir/tree"
build_net_stats_fixture "$tree_dir/run_01"
build_net_stats_fixture "$tree_dir/nested/run_02"
mkdir -p "$tree_dir/incomplete/net_stats/before/ns-n0"

msh_analyze_net_stats_tree "$tree_dir" "$net_stats_analyze_script" "$PYTHON"
test -f "$tree_dir/run_01/net_stats/details.json"
test -f "$tree_dir/nested/run_02/net_stats/details.json"
test ! -e "$tree_dir/incomplete/net_stats/details.json"
assert_details "$tree_dir/run_01/net_stats/details.json"
assert_details "$tree_dir/nested/run_02/net_stats/details.json"

echo "meshsim measurement helper tests passed"
