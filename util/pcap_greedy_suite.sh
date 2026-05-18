#!/bin/sh

export TARGET_BITRATES="5M"
export ITERATIONS="1"
export EXTRA_EMULATION_ARGS="--pcap"

util/nsperf_stress_test_many_streams/meas.sh /home/aau/meshsim/testgraphs /home/aau/meshsim/output/pcap_greedy | tee /home/aau/stress_log.txt
