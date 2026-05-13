#!/bin/sh

util/nsperf_stress_test_many_streams/meas.sh | tee /home/aau/stress_log.txt
util/nsperf_stress_test_dropout/meas.sh | tee /home/aau/stress_drop_log.txt
