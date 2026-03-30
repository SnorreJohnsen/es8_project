#!/usr/bin/env sh

# script to set tc-netem links

action="$1"
ifname="$2"
loss_percent="$3"
phyrate_mbps="$4"

case "$action" in
"create")
	tc qdisc add dev "${ifname}" root netem rate "${phyrate_mbps}mbit" loss "${loss_percent}%"
	;;
"update")
	tc qdisc change dev "${ifname}" root netem rate "${phyrate_mbps}mbit" loss "${loss_percent}%"
	;;
"remove")
	tc qdisc del dev "${ifname}" root
	;;
esac
