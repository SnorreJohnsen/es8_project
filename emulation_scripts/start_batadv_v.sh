#!/bin/sh

id="$1"

if ! test -e /sys/class/net/bat0; then
	echo "start batman-adv in ${id}"

	ip link set "uplink" down
	ip link set "uplink" up
	ip -4 addr flush dev "uplink"
	ip -6 addr flush dev "uplink"

	# batman-adv is not running
	batctl meshif "bat0" interface create routing_algo BATMAN_V
	batctl meshif "bat0" interface add "uplink"
	ip link set "bat0" up
else
	echo "batman-adv already runs in ${id}"
fi
