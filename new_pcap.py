import networkx as nx
from pyvis.network import Network
import argparse
import json
import re
import pyshark
from tqdm import tqdm
import numpy as np
from dataclasses import dataclass
import webbrowser, os
import matplotlib.pyplot as plt
import glob
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
import time
from collections import deque
import subprocess
import shutil

adapter = []

'''
Example: of how to create txt file with nessacary measures and order:
& tshark -r pcap_file
-T fields -e frame.number -e frame.time_epoch -e frame.time_relative -e eth.src -e eth.dst -e eth.type -e frame.protocols -e frame.len -e batadv.batman.packet_type 
-e batadv.ogm2.orig -e batadv.ogm2.throughput -e batadv.ogm2.ttl > edges_d0_d4.txt
'''
# maybe add this when need to track unicast -e batadv.unicast.dst -e batadv.unicast.ttl

def find_mac_path(obj, target_mac, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}/{k}"
            result = find_mac_path(v, target_mac, new_path)
            if result:
                return result

    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            new_path = f"{path}[{i}]"
            result = find_mac_path(item, target_mac, new_path)
            if result:
                return result

    else:
        if isinstance(obj, str) and obj.strip().lower() == target_mac.strip().lower():
            return path

    return None

def clean(x):
    return x.encode("utf-8", "ignore").decode("utf-8").strip()

def natural_key(text):
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r'(\d+)', text)
    ]

# def extract_uplink_macs(reference_data):
#     uplink_macs = []

#     for data in reference_data.values():
#         mac_dict = data.get('mac', {})

#         for iface, mac in mac_dict.items():
#             if 'uplink' in iface:
#                 uplink_macs.append(mac)
#             elif 'veth0' in iface:
#                 uplink_macs.append(mac)

#     return uplink_macs

def extract_used_macs_from_graph(G):
    used = set()

    for s, d in G.edges():
        used.add(s)
        used.add(d)

    return used

def extract_uplink_macs(reference_data):
    uplink_macs = set()

    for node, data in reference_data.items():
        mac_dict = data.get("mac", {})

        for iface, mac in mac_dict.items():
            if iface == "lo":
                continue

            if "uplink" in iface:
                uplink_macs.add(mac)

    return uplink_macs

def creation_of_edges_OGM2(*,
                      G,
                      file: str,
                      encoding: str,
                      start_time: int = 0,
                      OGM2_orig_mac: str,
                      time_interval: float = 1):
    
    '''
    docstring:
    G: networksx with need to be nx.MultiDiGraph()
    file: network stream with format of:
    frame_number | time | relative time | eth.src | eth.dst | eth.type | frame.protocols | bat_packet_type | bat_ogm2.orig
    OGM2_orig_mac: Need to uplink from reference data of the desired node
    time_interval: How long interval to track over, OGM2 interval is 1 sec and therefore default
    '''
    
    with open(file, "r", encoding=encoding, errors="ignore") as f:
            OGM2_interval = None
            order = 0
            for i, line in enumerate(f):

                # get the relative time
                parts = line.strip().split()
                time = float(clean(parts[2]))

                # ensure above desired start time
                if time < start_time:
                    continue
                # find first OGM of Orig send from the ORIG addr
                elif time > start_time and OGM2_interval is None:
                    src = clean(parts[3])
                    dst = clean(parts[4])
                    protocol = clean(parts[6])

                    # may need to split at , for bat_type and OGM2_orig_addr as may entail more then one
                    if len(parts) == 12:
                        bat_type = clean(parts[8])
                        bat_types = [b.strip() for b in bat_type.split(",")]
                        OGM2_orig_addr = clean(parts[9])
                        OGM2_orig_addrs = [O.strip() for O in OGM2_orig_addr.split(",")]
                        OGM2_tp = clean(parts[10])
                        OGM2_tps = [
                                        TP.strip()[:-1] + "." + TP.strip()[-1]
                                        if len(TP.strip()) > 1 else TP.strip()
                                        for TP in OGM2_tp.split(",")
                                    ]
                        # if find orig OGM2 message at the orig we start timer 
                        if src == OGM2_orig_mac and OGM2_orig_mac in OGM2_orig_addrs and 'batadv' in protocol and '4' in bat_types:
                            index = OGM2_orig_addrs.index(OGM2_orig_mac)

                            print(f"OGM2 Original Address {OGM2_orig_mac} Massage found at time {time} with throughput: {OGM2_tps[index]} mbit/s ")
                            OGM2_interval = time_interval
                            stop_time = time+OGM2_interval
                            G.add_edge(src, dst, type=order,TP=OGM2_tps[index], weight=1)
                        else:
                            continue
                    else:
                        continue
                # find route of the OGM2 massages
                elif time < stop_time:
                    src = clean(parts[3])
                    dst = clean(parts[4])
                    protocol = clean(parts[6])
                    if len(parts) == 12:
                        bat_type = clean(parts[8])
                        OGM2_orig_addr = clean(parts[9])
                        # may need to split at , for bat_type and OGM2_orig_addr as may entail more then one
                        bat_types = [b.strip() for b in bat_type.split(",")]
                        OGM2_orig_addrs = [O.strip() for O in OGM2_orig_addr.split(",")]
                        OGM2_tp = clean(parts[10])
                        OGM2_tps = [
                                    TP.strip()[:-1] + "." + TP.strip()[-1]
                                    if len(TP.strip()) > 1 else TP.strip()
                                    for TP in OGM2_tp.split(",")
                                ]
                        # found transmition with the OGM2_orig_mac within
                        if src != OGM2_orig_mac and OGM2_orig_mac in OGM2_orig_addrs and 'batadv' in protocol and '4' in bat_types:
                            index = OGM2_orig_addrs.index(OGM2_orig_mac)
                            edge_key = edge_with_type_exists(G, src, dst, order)
                            if edge_key is not None:
                                G[src][dst][edge_key]["weight"] += 1
                            else:
                                order += 1
                                G.add_edge(src, dst, type=order,TP=OGM2_tps[index], weight=1)
                                
                    else:
                        continue
                else:
                    print(f"the full OGM2 interval: {OGM2_interval} sec is now done, Time is: {time}")
                    break

    return G

def tracking_of_OGM2_at_source(*,
                               addr_data: str,
                               file: str,
                               encoding: str,
                               start_time: int = 0,
                               OGM2_orig_mac: str,
                               time_interval: float = 1,
                               eth_src: str = None):
    
    '''
    docstring:
    G: networksx with need to be nx.MultiDiGraph()
    file: network stream with format of:
    frame_number | time | relative time | eth.src | eth.dst | eth.type | frame.protocols | bat_packet_type | bat_ogm2.orig
    OGM2_orig_mac: Need to uplink from reference data of the desired node
    time_interval: How long interval to track over, OGM2 interval is 1 sec and therefore default
    '''

    src_mac_info = find_mac_path(addr_data, eth_src)
    OGM2_mac_info = find_mac_path(addr_data, OGM2_orig_mac)

    # find "n0" id and type "veth:.."
    src_parts = src_mac_info.split("/")
    src_node = src_parts[1]

    # find "n0" id and type "veth:.."
    OGM2_parts = OGM2_mac_info.split("/")
    OGM2_node = OGM2_parts[1]

    with open(file, "r", encoding=encoding, errors="ignore") as f:
            stop_time = start_time + time_interval
            throughput = None
            print(f"OGM Original Address at node id: {OGM2_node} with MAC address: {OGM2_orig_mac} | Broadcasted at node id: {src_node} with MAC Adress {eth_src}")
            print("------------------------------------------------------------------------------------------------------------")
            for i, line in enumerate(f):

                # get the relative time
                parts = line.strip().split()
                time = float(clean(parts[2]))

                # ensure above desired start time
                if time < start_time:
                    continue
                # find first OGM of Orig send from the ORIG addr
                elif time > start_time and time < stop_time:
                    src = clean(parts[3])
                    dst = clean(parts[4])
                    protocol = clean(parts[6])

                    # may need to split at, for bat_type and OGM2_orig_addr as may entail more then one
                    if len(parts) == 12:

                        bat_type = clean(parts[8])
                        bat_types = [b.strip() for b in bat_type.split(",")]
                        OGM2_orig_addr = clean(parts[9])
                        OGM2_orig_addrs = [O.strip() for O in OGM2_orig_addr.split(",")]
                        OGM2_tp = clean(parts[10])
                        OGM2_tps = [
                                        TP.strip()[:-1] + "." + TP.strip()[-1]
                                        if len(TP.strip()) > 1 else TP.strip()
                                        for TP in OGM2_tp.split(",")
                                    ]
                        OGM2_ttl = clean(parts[11])
                        OGM2_ttls = [O.strip() for O in OGM2_ttl.split(",")]
                        #print(f"{src=},{OGM2_orig_addrs=}")
                        #print(f"{eth_src=},{OGM2_orig_mac=}")
                        # if find orig OGM2 message at the orig we start timer 
                        if src == eth_src and OGM2_orig_mac in OGM2_orig_addrs and 'batadv' in protocol and '4' in bat_types:
                            index = OGM2_orig_addrs.index(OGM2_orig_mac)
                            # only print when throughput changes
                            if throughput != OGM2_tps[index]:
                                throughput = OGM2_tps[index]
                                ttl = int(OGM2_ttls[index])
                                print(f"Time is {time:6.2f} | Throughput: {float(OGM2_tps[index]):6.2f} mbit/s | TTL: {ttl} -> Hops: {50 - ttl}")
                        else:
                            continue
                    else:   
                        continue
                else:
                    continue
    print("_______________________________________________________________________________")
    return 

def edge_with_type_exists(G, src, dst, order):
    if not G.has_edge(src, dst):
        return None
    
    for key, data in G[src][dst].items():
        if isinstance(data, dict) and data.get("type") == order:
            return key
    
    return None

def all_link_throughput(*,
                      G,
                      file: str,
                      encoding: str,
                      start_time: int = 0,
                      stop_time: int,
                      stepsize_anime: float = 1,
                      gif: bool = False,
                      browser_html: bool = False,
                      flag_interval: bool = False):
    frame_idx = 0
    with open(file, "r", encoding=encoding, errors="ignore") as f:
            lines = f.readlines()
            last_line = lines[-1]
            last_parts = last_line.strip().split()
            tot_pkts = clean(last_parts[0])
            tot_time = float(clean(last_parts[2]))
            # Sanity check for stop time
            if stop_time < start_time:
                print('\nWARNING!! stop time is lower than start time')
                return
            if stop_time > tot_time:
                print('\nWARNING!! stop time is higher than total capture time')
                print(f'Setting stop time equal to total time: {tot_time}')
                stop_time = tot_time
            print('\n________________________________ Link Througput ________________________________\n')

            anime_time = stepsize_anime
            first_time_tcp_packet = None
            first_before_stop = True

            for i, line in enumerate(lines):
                parts = line.strip().split()
                time = float(clean(parts[2]))
                if time < start_time:
                    continue
                elif time > stop_time and first_before_stop == True:
                    first_before_stop = False
                elif time > stop_time and first_before_stop == False:
                    break

                # FRAME_NR EPOCH_TIME RELATIVE_TIME SRC DST
                pkt_num = clean(parts[0])
                src = clean(parts[3])
                dst = clean(parts[4])
                # All batman type are above 9 len
                if len(parts) >= 9:
                    frame_length = clean(parts[7])
                # arp and such which dont entail batman
                elif len(parts) == 8:
                    frame_length = clean(parts[7])
                else:
                    print(parts)
                    exit()      
                # To ensure we dont capture batman ttl
                if ',' in frame_length:
                        print(f'Suppose to be frame length but get result {frame_length}')
                        exit()
                        

                srcs = [s.strip() for s in src.split(",")]
                dsts = [d.strip() for d in dst.split(",")]


                for n, (s,d) in enumerate(zip(srcs, dsts)):
                    if s == "ff:ff:ff:ff:ff:ff" or d == "ff:ff:ff:ff:ff:ff":
                        # need to do something if broadcast like maybe at to all links that the node have
                        continue
                    
                    # Only make the batadv packet, not the tcp
                    if G.has_edge(s, d):
                        G[s][d]["bits"] += int(frame_length)
                        G[s][d]["last_time"] = time
                        G[s][d]['count'] += 1
                    else:
                        G.add_edge(s, d, bits=int(frame_length), first_time = time,last_time = time, count=1)
                        if first_time_tcp_packet == None:
                            first_time_tcp_packet = time
                            time_prev = first_time_tcp_packet
                            packet_prev = int(pkt_num)
                if time > start_time + anime_time or time == tot_time or time >= stop_time:
                    anime_prev = start_time + anime_time
                    anime_time += stepsize_anime
                    if len(G.edges) > 0:
                        if time == tot_time or time >= stop_time:
                            print(f"Animation captured Up to Time: {time}")
                            if flag_interval is True:
                                time_last_anime = anime_prev-stepsize_anime
                                print(f"Shows last {time-time_last_anime:.2f} secs | Being the remaining packet of interval: {time_last_anime} sec - {time} sec ")
                        else:
                            print(f"Animation Time: {anime_prev} | Time is {time}")
                        os.makedirs("throughput_graphs", exist_ok=True)
                        frame_idx += 1
                        html_file = f"throughput_graphs/graph_{float(time):.2f}.html"
                        png_file = f"throughput_graphs/frame_{frame_idx:04d}.png"
                        creation_of_pyvis(G=G,
                                          reference_data=addr_data,
                                          json_nodes=json_link_nodes,
                                          index=time,output_file=html_file,
                                          browser_html = browser_html,
                                          current_pkt = pkt_num,
                                          total_pkts = tot_pkts,
                                          time = time,
                                          total_time = tot_time,
                                          flag_interval=flag_interval,
                                          time_prev = time_prev,
                                          packet_prev=packet_prev,
                                          plot_type='Throughput')
                        print("_______________________________________________________________________________")
                        #first_time_tcp_packet = None

                        if flag_interval is True:
                            first_time_tcp_packet = None
                            G = nx.DiGraph()

                        # only use this conversion not often slower then a snail
                        if gif is True:
                            html_to_png(html_file, png_file)
                    else:
                        print(f"At time: {time} No Packet's found, Will go to next Time Step")
                        print("_______________________________________________________________________________")
    return G

def creation_of_edges_TCP(*,
                      G,
                      file: str,
                      encoding: str,
                      start_time: int = 0,
                      stop_time: int,
                      stepsize_anime: float = 1,
                      gif: bool = False,
                      browser_html: bool = False,
                      flag_interval: bool = False):

    tcp_streams = {}
    frame_idx = 0
    with open(file, "r", encoding=encoding, errors="ignore") as f:
            lines = f.readlines()
            last_line = lines[-1]
            last_parts = last_line.strip().split()
            tot_pkts = clean(last_parts[0])
            tot_time = float(clean(last_parts[2]))
            # Sanity check for stop time
            if stop_time < start_time:
                print('\nWARNING!! stop time is lower than start time')
                return
            if stop_time > tot_time:
                print('\nWARNING!! stop time is higher than total capture time')
                print(f'Setting stop time equal to total time: {tot_time}')
                stop_time = tot_time
            
            print('\n_________________________________ TCP & UDP STREAMS _____________________________\n')

            anime_time = stepsize_anime
            first_time_tcp_packet = None
            first_before_stop = True

            for i, line in enumerate(lines):
                parts = line.strip().split()
                time = float(clean(parts[2]))
                if time < start_time:
                    continue
                elif time > stop_time and first_before_stop == True:
                    first_before_stop = False
                elif time > stop_time and first_before_stop == False:
                    break

                # FRAME_NR EPOCH_TIME RELATIVE_TIME SRC DST TYPE PROTOCOLS BATMAN_TYPE BATMAN_ORIG
                pkt_num = clean(parts[0])
                src = clean(parts[3])
                dst = clean(parts[4])
                type = clean(parts[5])
                protocol = clean(parts[6])

                protocols = [p.strip() for p in protocol.split(",")]
                srcs = [s.strip() for s in src.split(",")]
                dsts = [d.strip() for d in dst.split(",")]
                types = [t.strip() for t in type.split(",")]

                for n, (s, d,t,p) in enumerate(zip(srcs, dsts,types,protocols * len(srcs))):
                    if s == "ff:ff:ff:ff:ff:ff" or d == "ff:ff:ff:ff:ff:ff":
                        continue
                    
                    if 'batadv' in p:
                        if 'tcp' in p or 'udp' in p:   # check that udp is called 'udp' in txt.
                            if n == 0:
                                if G.has_edge(s, d):
                                    G[s][d]["weight"] += 1
                                    G[s][d]["last_time"] = time
                                else:
                                    G.add_edge(s, d, type=t, weight=1, first_time = time,last_time = time)
                                    if first_time_tcp_packet == None:
                                        first_time_tcp_packet = time
                                        time_prev = first_time_tcp_packet
                                        packet_prev = int(pkt_num)
                                
                            if n == 1:
                                if 'udp' in p:
                                    stream_type = 'UDP'
                                if 'tcp' in p:
                                    stream_type = 'TCP'
                                stream = (s, d,stream_type)

                                if stream not in tcp_streams:
                                    src_mac_info = find_mac_path(addr_data, s)
                                    dst_mac_info = find_mac_path(addr_data, d)

                                    # find "n0" id and type "veth:.."
                                    src_parts = src_mac_info.split("/")
                                    src_node = src_parts[1]
                                    src_mac_type = src_parts[3]

                                    dst_parts = dst_mac_info.split("/")
                                    dst_node = dst_parts[1]
                                    dst_mac_type = dst_parts[3]

                                    tcp_streams[stream] = {
                                        "src_node": src_node,
                                        "dst_node": dst_node,
                                        "src_mac_type": src_mac_type, 
                                        "dst_mac_type": dst_mac_type, 
                                        "count": 1                           
                                    }
                                else:
                                    tcp_streams[stream]["count"] += 1

                if time > start_time + anime_time or time == tot_time or time >= stop_time:
                    anime_prev = start_time + anime_time
                    anime_time += stepsize_anime
                    if len(G.edges) > 0:
                        if time == tot_time or time >= stop_time:
                            print(f"Animation captured Up to Time: {time}")
                            if flag_interval is True:
                                time_last_anime = anime_prev-stepsize_anime
                                print(f"Shows last {time-time_last_anime:.2f} secs | Being the remaining TCP & UDP packet of interval: {time_last_anime} sec - {time} sec ")
                        else:
                            print(f"Animation Time: {anime_prev} | Time is {time}")
                        os.makedirs("stream_graphs", exist_ok=True)
                        frame_idx += 1
                        html_file = f"stream_graphs/graph_{float(time):.2f}.html"
                        png_file = f"stream_graphs/frame_{frame_idx:04d}.png"
                        print(f"TCP & UDP streams existing is:")

                        # sort after count amount
                        for (s, d,stream_type), info in sorted(tcp_streams.items(),
                           key=lambda item: item[1]['count'],
                           reverse=True):
                            print(f"Type: {stream_type} | Node: Src {info['src_node']} -> Dst {info['dst_node']} | Link Use Count: {info['count']}|||",
                                f"Mac info: SRC {s} type: {info['src_mac_type']} | DST {d} type: {info['dst_mac_type']}")
                        creation_of_pyvis(G=G,
                                          reference_data=addr_data,
                                          json_nodes=json_link_nodes,
                                          index=time,output_file=html_file,
                                          browser_html = browser_html,
                                          current_pkt = pkt_num,
                                          total_pkts = tot_pkts,
                                          time = time,
                                          total_time = tot_time,
                                          flag_interval=flag_interval,
                                          time_prev = time_prev,
                                          packet_prev=packet_prev)
                        print("_______________________________________________________________________________")
                        first_time_tcp_packet = None

                        if flag_interval is True:
                            G = nx.DiGraph()
                            tcp_streams = {}

                        # only use this conversion not often slower then a snail
                        if gif is True:
                            html_to_png(html_file, png_file)
                    else:
                        print(f"At time: {time} No TCP Packet's found, Will go to next Time Step")
                        print("_______________________________________________________________________________")
    return G

def html_to_png(html_file, output_png):
    assert os.path.exists(html_file), html_file

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1200,800")

    # Insert this for thias to work
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    #driver = webdriver.Chrome(options=options)

    try:
        # load page
        driver.get("file://" + os.path.abspath(html_file))

        # wait for page to fully load
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # extra wait for PyVis JS rendering
        time.sleep(2)

        # enforce size (important for consistent PNGs)
        driver.set_window_size(1200, 800)

        # screenshot
        driver.save_screenshot(output_png)

    finally:
        driver.quit()

def accumulative_injection(color_bar_title: str,
                           color_bar_data: list,
                           current_pkt,
                           total_pkts,
                           time,
                           total_time):
    arr = np.array(color_bar_data)

    min_v = np.min(arr)
    q1 = np.percentile(arr, 25)
    median = np.percentile(arr, 50)
    q3 = np.percentile(arr, 75)
    max_v = np.max(arr)

    injection = """
        <script type="text/javascript">
        window.addEventListener("load", function () {
            if (typeof network !== "undefined") {

                // FORCE stabilization immediately
                network.stabilize(1000);

                // After stabilization → fit and lock view
                setTimeout(function () {
                    network.fit({
                        animation: {
                            duration: 0
                        }
                    });

                    // Optional: disable physics so it doesn't move again
                    network.setOptions({ physics: false });

                }, 100);
            }
        });
        </script>

        <style>
        #heatmap-legend {
            position: fixed;
            top: 20px;
            right: 30px;
            width: 500px;  /* maybe reduce from 1540 */
            padding: 12px;
            background: white;
            border-radius: 8px;
            font-family: Arial;
            font-size: 14px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
            z-index: 9999;
        }

        #heatmap-bar {
            height: 20px;
            width: 100%;
            border-radius: 5px;
            background: linear-gradient(
                to right,
                rgb(0,0,255),     /* blue */
                rgb(0,255,255),   /* cyan */
                rgb(0,255,0),     /* green */
                rgb(255,255,0),   /* yellow */
                rgb(255,0,0)      /* red */
            );
        }

        #heatmap-labels {
            display: flex;
            justify-content: space-between;
            margin-top: 5px;
            font-size: 12px;
        }
        </style>

        <div id="heatmap-legend">
            <b>""" + f'{color_bar_title}' + """</b>
            <div id="heatmap-bar"></div>
            <div id="heatmap-labels">
                <span>""" + f"{format_unit(min_v)}" + """</span>
                <span>""" + f"{format_unit(q1)}" + """</span>
                <span>""" + f"{format_unit(median)}" + """</span>
                <span>""" + f"{format_unit(q3)}" + """</span>
                <span>""" + f"{format_unit(max_v)}" + """</span>

            </div>
        </div>

        <style>
        #packet-info {
            position: fixed;
            top: 30px;
            left: 30px;
            background: rgba(255, 255, 255, 0.9);
            padding: 8px 12px;
            border-radius: 6px;
            font-family: Arial;
            font-size: 13px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.2);
            z-index: 9999;
        }
        </style>

        <div id="packet-info">
            <div><b>""" + f"{current_pkt}" + """</b> pkts read out of <b>""" + f"{total_pkts}" + """</b> pkts</div>
            <div>Time of instance <b>""" + f"{time:.2f}" + """</b> out of <b>""" + f"{total_time:.2f}" + """</b> total time of instance </div>
        </div>
        """
    return injection

def window_injection(color_bar_title: str,
                     color_bar_data: list,
                           current_pkt: int,
                           total_pkts: int,
                           time: float,
                           total_time: float,
                           time_prev: float,
                           packet_prev: int):
    
    
    arr = np.array(color_bar_data)

    min_v = np.min(arr)
    q1 = np.percentile(arr, 25)
    median = np.percentile(arr, 50)
    q3 = np.percentile(arr, 75)
    max_v = np.max(arr)

    injection = """
        <script type="text/javascript">
        window.addEventListener("load", function () {
            if (typeof network !== "undefined") {

                // FORCE stabilization immediately
                network.stabilize(1000);

                // After stabilization → fit and lock view
                setTimeout(function () {
                    network.fit({
                        animation: {
                            duration: 0
                        }
                    });

                    // Optional: disable physics so it doesn't move again
                    network.setOptions({ physics: false });

                }, 100);
            }
        });
        </script>

        <style>
        #heatmap-legend {
            position: fixed;
            top: 20px;
            right: 30px;
            width: 500px;  /* maybe reduce from 1540 */
            padding: 12px;
            background: white;
            border-radius: 8px;
            font-family: Arial;
            font-size: 14px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
            z-index: 9999;
        }

        #heatmap-bar {
            height: 20px;
            width: 100%;
            border-radius: 5px;
            background: linear-gradient(
                to right,
                rgb(0,0,255),     /* blue */
                rgb(0,255,255),   /* cyan */
                rgb(0,255,0),     /* green */
                rgb(255,255,0),   /* yellow */
                rgb(255,0,0)      /* red */
            );
        }

        #heatmap-labels {
            display: flex;
            justify-content: space-between;
            margin-top: 5px;
            font-size: 12px;
        }
        </style>

        <div id="heatmap-legend">
            <b>""" + f'{color_bar_title}' + """</b>
            <div id="heatmap-bar"></div>
            <div id="heatmap-labels">
                <span>""" + f"{format_unit(min_v)}" + """</span>
                <span>""" + f"{format_unit(q1)}" + """</span>
                <span>""" + f"{format_unit(median)}" + """</span>
                <span>""" + f"{format_unit(q3)}" + """</span>
                <span>""" + f"{format_unit(max_v)}" + """</span>

            </div>
        </div>

        <style>
        #packet-info {
            position: fixed;
            top: 30px;
            left: 30px;
            background: rgba(255, 255, 255, 0.9);
            padding: 8px 12px;
            border-radius: 6px;
            font-family: Arial;
            font-size: 13px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.2);
            z-index: 9999;
        }
        </style>

        <div id="packet-info">
            <div>Packet interval <b>""" + f"{packet_prev}" + """ - """ + f'{current_pkt}' + """</b> pkts read out of <b>""" + f"{total_pkts}" + """</b> pkts</div>
            <div>Time of interval <b>""" + f"{time_prev:.2f}" + """ - """ + f"{time:.2f}"  + """</b> out of <b>""" + f"{total_time:.2f}" + """</b> total time of instance </div>
        </div>
        """
    return injection

def creation_of_pyvis(G,
                      index: str,
                      reference_data: str,
                      json_nodes: str,
                      current_pkt: str,
                      total_pkts: str,
                      time: float,
                      total_time: float,
                      time_prev: float,
                      packet_prev: int,
                      output_file="packet_graph.html",
                      browser_html: bool = False,
                      flag_interval: bool = False,
                      plot_type: str = 'TCP'
                      ):
    precision_number = 1e-7
    # ensure still work even with wierd spacing and upper and lower casing wording
    plot_type = plot_type.strip().lower()
    print(f"Creating Pyvis HTML at time: {time}")
    # Create PyVis network
    net = Network(height="800px", width="100%", directed=True, bgcolor="grey", font_color="black")
    # Optional: better physics (important for mesh graphs)
    net.barnes_hut()

    # Load layout data (graph.json)
    with open(json_nodes,"r") as f:
        node_link_data = json.load(f)
    nodes_pos_data = node_link_data.get("nodes", [])
    pos_lookup = {n["id"]: n for n in nodes_pos_data}   # includes both nodes and adapters
    nodes = []     # Add nodes + edges

    # 1. Add nodes that exist in G (only include nodes and adapters that have links)
    uplink_macs = extract_uplink_macs(reference_data)
    used_macs = set(extract_used_macs_from_graph(G))
    node_macs = used_macs.union(uplink_macs)

    for node in node_macs:

        node_info = find_mac_path(reference_data, node)

        # node_info = /n4/mac/uplink@if15  (example)
        if node_info:
            parts = node_info.split("/")
            node_id = parts[1]
            addr_type = parts[2]
            addr_type_type = parts[3]
            # expected adapter and node ids in the json lookup

            if node_id in pos_lookup and "uplink" in addr_type_type:
                x = pos_lookup[node_id]["x"]
                y = pos_lookup[node_id]["y"]
            elif "d" in node_id:
                x = 30000 + np.random.random() * 1000
                y = 15000 + np.random.random() * 1000
            else:
                x = -10000 + np.random.random() * 1000
                y = 15000 + np.random.random() * 1000
        else:
            # expect to be 33:33:00:00:00:02 which is to do with 0x08...
            node_id = "unknown"
            addr_type = "unknown"
            addr_type_type = "unknown"
            x = 30000
            y = 15000
        
        # node styling
        color = "gray"
        if "a" in node_id:
            color = "red"
        elif "n" in node_id:
            color = "blue"
        elif "d" in node_id:
            color = "green" if plot_type == "throughput" else "blue"

        net.add_node(
            node,
            label=f"MAC: {node}\nNODE: {node_id}",
            size=10,
            color=color,
            x=x / 10,
            y=y / 10,
            physics=False
        )
        
        if "uplink" in addr_type_type:
            priority = 0
        elif "veth" in addr_type_type:
            priority = 1
        elif "bat0" in addr_type_type:
            priority = 2
        elif "unknown" in addr_type_type:
            priority = 3
        else:
            priority = 4

        nodes.append((node_id, node, addr_type, addr_type_type,priority))


    # natural sort here
    nodes.sort(key=lambda x: (x[4], natural_key(x[0])))

    current_priority = None
    for node_id, mac, addr_type, addr_type_type, priority in nodes:

        if priority != current_priority:
            current_priority = priority
            clean_iface = addr_type_type.split("@")[0]
            text = f" PRIORITY {priority} | {clean_iface} "
            text = text.ljust(80 - 30, "-")
            print(f"{'-' * 30}{text}")
        net.add_node(
            mac,
            label=f"MAC: {mac}\nNODE: {node_id}\nADDR TYPE: {addr_type} {addr_type_type}"
        )
        if mac in G.nodes():
            print(f"{node_id} -> {mac}")
        else:
            print(f'{node_id} -> {mac} - This node/adapter do not contain any links')
    # ensure ALL graph nodes exist
    for node in G.nodes():
        if node not in net.get_nodes():
            net.add_node(
                node,
                label=f"MAC: {node}",
                size=8,
                color="gray",
                physics=False
            )

    # Add edges with styling
    values = []

    for _, _, data in G.edges(data=True):
        if plot_type == 'tcp':
            v = data.get('weight', 1)
        elif plot_type == 'throughput':
            dt = max(data.get('last_time') - data.get('first_time'), precision_number)
            bits = data.get("bits", 0)
            v = bits / dt
        values.append(v)

    min_v = min(values)
    max_v = max(values)
    
    for src, dst, data in G.edges(data=True):
        #  check if reverse edge exists
        has_reverse = G.has_edge(dst, src)

        if has_reverse and src != dst:
            smooth = {
                'enabled': True,
                'type': 'curvedCW',
                'roundness': 0.1
            }
        else:
            smooth = False

        if plot_type == 'tcp':
            value = data.get('weight',1)
            norm = normalize(w=value,min_w=min_v,max_w=max_v)
            color = heatmap_color(norm=norm)
            net.add_edge(
            src,
            dst,
            smooth=smooth,
            title=f"Tranmission time for: First {data.get('first_time')} | Last {data.get('last_time')} |  count: {data.get('weight')}",        
            # title=f"Order of message: {data.get('type')}| Throughput = {data.get('TP')} mbit/s | count: {weight}",
            color= color,               
            width=1 + np.log1p(value)  # optional smoother scaling
        )
        elif plot_type == "throughput":
            dt = max(data.get('last_time') - data.get('first_time'), precision_number)
            bits = data.get("bits", 0)
            value = bits / dt
            norm = normalize(w=value,min_w=min_v,max_w=max_v)
            color = heatmap_color(norm=norm)

            net.add_edge(
                src,
                dst,
                smooth=smooth,
                title=(
                    f"First {data.get('first_time')} | "
                    f"Last {data.get('last_time')} | "
                    f"message count: {data.get('count')} | "
                    f"rate: {format_unit(value)}bit/s | "
                    f"total: {format_unit(bits)}bit"
                ),
                color=color,
                width = 1 + 0.2 * np.log1p(value)   # width between 1 and 5
            )

    # Save and open
    # Save HTML (DO NOT use show)
    net.write_html(output_file)
    values = []
    for _, _, data in G.edges(data=True):
        if plot_type == 'tcp':
            v = data.get('weight', 1)
        elif plot_type == 'throughput':
            dt = max(data.get('last_time') - data.get('first_time'), precision_number)
            bits = data.get("bits", 0)
            v = bits / dt
        values.append(v)
    
    color_bar_data = values
    if plot_type == 'tcp':
        color_bar_title = 'TCP packets transmitted on link'
    elif plot_type == 'throughput':
        color_bar_title = 'Throughput [bits/s] on link'

    # Inject auto-fit script
    with open(output_file, "r+", encoding="utf-8") as f:
        html = f.read()
       
        # Inset injection
        if flag_interval == True:
            injection = window_injection(color_bar_title=color_bar_title,
                                         color_bar_data = color_bar_data,
                                         current_pkt=current_pkt,
                                         total_pkts=total_pkts,
                                         time=time,
                                         total_time=total_time,
                                         time_prev = time_prev,
                                         packet_prev=packet_prev)
        else:
            injection = accumulative_injection(color_bar_title=color_bar_title,
                                               color_bar_data = color_bar_data,
                                         current_pkt=current_pkt,
                                         total_pkts=total_pkts,
                                         time=time,
                                         total_time=total_time)

        html = html.replace("</body>", injection + "\n</body>")

        f.seek(0)
        f.write(html)
        f.truncate()
    if browser_html is True:
        webbrowser.open("file://" + os.path.abspath(output_file))

def format_unit(value):
    units = ["", "K", "M", "G", "T"]
    scale = 1000.0  # use 1024.0 if you prefer binary units

    i = 0
    while value >= scale and i < len(units) - 1:
        value /= scale
        i += 1

    return f"{value:.2f} {units[i]}"

def normalize(w,min_w,max_w):
    if max_w == min_w:
        return 0.5
    return (w - min_w) / (max_w - min_w)

def mac_node(node_id: str, reference_data: dict):
    macs = reference_data[node_id]["mac"]
    
    for interface, mac in macs.items():
        if interface.startswith("uplink"):
            return mac
    print(f"No Mac address of uplink found for {node_id} in {reference_data}")
    return None

def heatmap_color(norm):
    if norm < 0.25:
        return f"rgb(0,{int(255 * norm * 4)},255)"         # blue → cyan
    elif norm < 0.5:
        return f"rgb(0,255,{int(255 * (1 - (norm - 0.25)*4))})"  # cyan → green
    elif norm < 0.75:
        return f"rgb({int(255 * (norm - 0.5)*4)},255,0)"   # green → yellow
    else:
        return f"rgb(255,{int(255 * (1 - (norm - 0.75)*4))},0)"  # yellow → red

def draw_graph(G, path):
    plt.figure(figsize=(6, 6))

    pos = nx.spring_layout(G, seed=42)

    nx.draw(
        G,
        pos,
        with_labels=True,
        node_size=500,
        font_size=10
    )

    plt.savefig(path)
    plt.close()

def run_tshark(pcap_file, output_txt):
    # 1. Find tshark
    tshark_path = shutil.which("tshark")

    if not tshark_path:
        candidate = r"C:\Program Files\Wireshark\tshark.exe"
        if os.path.exists(candidate):
            tshark_path = candidate

    if not tshark_path:
        raise RuntimeError(
            "tshark not found. Install Wireshark or add tshark to PATH."
        )

    # 2. Build command
    cmd = [
        tshark_path,
        "-r", pcap_file,
        "-T", "fields",
        "-e", "frame.number",
        "-e", "frame.time_epoch",
        "-e", "frame.time_relative",
        "-e", "eth.src",
        "-e", "eth.dst",
        "-e", "eth.type",
        "-e", "frame.protocols",
        "-e", "frame.len",
        "-e", "batadv.batman.packet_type",
        "-e", "batadv.ogm2.orig",
        "-e", "batadv.ogm2.throughput",
        "-e", "batadv.ogm2.ttl"
    ]

    # 3. Run tshark
    print("CWD:", os.getcwd())
    print("Writing to:", os.path.abspath(output_txt))
    with open(output_txt, "w") as f:
        subprocess.run(cmd, stdout=f, check=True)

if __name__ == "__main__":

    default_start_time = 0
    default_stop_time = 30
    default_interval = 5

    parser = argparse.ArgumentParser(description="What Parameters mean")
    parser.add_argument("-in","--input", type=str ,help ="Input file location | NEEDS TO BE TXT")
    parser.add_argument("-addr","--addresses",type=str, help ="Json file including all associated adresses for the Nodes, Adapters, Devices (node_addr.json)")
    parser.add_argument("-j","--json",type=str, help ="Json file Including pos of nodes (graph.json)")
    parser.add_argument("-gif","--gif_enabled",action="store_true", help ="enable creation of gif from png's, (png's are not created if gif is disabled)")
    parser.add_argument("-e","--existing_png_for_gif",action="store_true", help ="Don't recreate png, for gif instead use already existing pngs created previously")
    parser.add_argument("-b","--browser",action="store_true", help ="If to enable that the HTML plots are opened in the browser")
    parser.add_argument("-f","--flag_interval",action="store_true", help ="Set to enable HTML for intervals")
    parser.add_argument("-sta","--start_time", type=float, help ="Choose start time for analysis. Default = 0 sec")
    parser.add_argument("-sto","--stop_time", type=float, help ="Choose stop time for analysis. Default = 30 sec")
    parser.add_argument("-i","--interval", type=float, help ="Choose interval size of windows. Default = 5 sec")
    parser.add_argument("-m","--method", type=str, help ="Choose type of analysis method. throughput, tcp, udp or ogmv2.")
    parser.add_argument("-ogm_orig","--ogmv2_originator", type=str, help ="Choose ogmv2 originator node. Can be multiple nodes (n1,n2)")
    parser.add_argument("-ogm_eth_src","--ogmv2_ethernet_source", type=str, help ="Choose ogmv2 ethernet source node. Can be multiple nodes (n1,n2)")

    args = parser.parse_args()

    analysis_file = args.input
    addr_file = args.addresses
    json_link_nodes = args.json
    enable_gif = args.gif_enabled
    exist_gif = args.existing_png_for_gif
    enable_browser = args.browser
    enable_interval_graph = args.flag_interval
    start_time = args.start_time
    stop_time = args.stop_time
    interval_time = args.interval
    method_type = args.method
    ogmv2_orig = args.ogmv2_originator
    ogmv2_eth_src = args.ogmv2_ethernet_source
    method_type = method_type.strip().lower()
    
    # Allow both pcap and txt from analysis file 
    if analysis_file.endswith(".txt"):   
        encoding = "utf-16"
    if analysis_file.endswith(".pcap"):
        output_dir = os.path.join(os.getcwd(), "tshark_outputs")
        os.makedirs(output_dir, exist_ok=True)

        txt_file = os.path.join(
            output_dir,
            os.path.splitext(os.path.basename(analysis_file))[0] + ".txt"
        )
        encoding = "utf-8"
        run_tshark(analysis_file, txt_file)
        analysis_file = txt_file  # continue using the generated txt
    # ensure input either given txt or converted to txt
    if not analysis_file.endswith(".txt"):
        print("ERROR: Failed to resolve analysis file to .txt")
        exit()

    if start_time is not None:
        default_start_time = start_time
    if stop_time is not None:
        default_stop_time = stop_time
    if interval_time is not None:
        default_interval = interval_time
    
    start = 0
    end = 10000000

    with open(addr_file,"r") as f:
        addr_data = json.load(f)

    # checking order of OGM2 messages being transmitted throughout the network
    # Build graph
    #G = nx.MultiDiGraph()
    #Mac_a4= mac_node("a4",reference_data=addr_data)
    #G = creation_of_edges_OGM2(G=G,file=analysis_file,start_time=20,OGM2_orig_mac=Mac_a4,time_interval=1)

    # TPC stream seing how it goes through the netwrok of iperf tcp stream
    # Build graph
    G = nx.DiGraph()
    F = nx.DiGraph()

    if method_type == 'ogmv2':
        if ogmv2_orig is None or ogmv2_eth_src is None:
            print("\nERROR: Need to provide both ogmv2 originator and ethernet source node/nodes")
            exit()
        ogmv2_origs = [orig.strip() for orig in ogmv2_orig.split(',')]
        ogmv2_eth_srcs = [src.strip() for src in ogmv2_eth_src.split(',')] 
        # Load layout data (graph.json)
        with open(json_link_nodes,"r") as f:
            node_link_data = json.load(f)
        nodes_pos_data = node_link_data.get("nodes", [])
        pos_lookup = {n["id"]: n for n in nodes_pos_data}   # includes both nodes and adapters

        for orig in ogmv2_origs:
            if orig not in pos_lookup:
                print(f'\nThe ogmv2 originator {orig} is not a node in the graph.json')
                exit()
            else:
                MAC_orig_node = mac_node(orig,reference_data=addr_data)
            for src in ogmv2_eth_srcs:
                if src not in pos_lookup:
                    print(f'\nThe ethernet source {src} is not a node in the graph.json')
                    exit()
                else:
                    MAC_eth_src_node = mac_node(src,reference_data=addr_data)
                    tracking_of_OGM2_at_source(addr_data=addr_data, 
                                               file=analysis_file,
                                               encoding = encoding,
                                               start_time=13,
                                               OGM2_orig_mac=MAC_orig_node,
                                               time_interval=20,
                                               eth_src=MAC_eth_src_node)

    if method_type == 'tcp' or method_type == 'udp':
        G = creation_of_edges_TCP(G=G,
                              file=analysis_file,
                              encoding = encoding,
                              start_time=default_start_time,
                              stop_time=default_stop_time,
                              stepsize_anime=default_interval,
                              gif=enable_gif,
                              browser_html = enable_browser,
                              flag_interval=enable_interval_graph)
        if enable_gif is True or exist_gif is True:

            frame_files = sorted(glob.glob("frames/frame_*.png"))

            if not frame_files:
                print("No frames found. Skipping video creation.")
            else:
                print(f"Creating video from {len(frame_files)} frames...")

                ffmpeg_cmd = [
                    "ffmpeg",
                    "-y",  # overwrite output
                    "-framerate", "0.5",
                    "-i", "frames/frame_%04d.png",
                    "-c:v", "libx264",
                    "-preset", "slow",
                    "-crf", "18",
                    "-pix_fmt", "yuv420p",
                    "network.mp4"
                ]

                subprocess.run(ffmpeg_cmd, check=True)

                print("Video saved as network.mp4")

    if method_type == 'throughput':
        F = all_link_throughput(G=F,
                            file = analysis_file,
                            encoding = encoding,
                            start_time=default_start_time,
                            stop_time=default_stop_time,
                            stepsize_anime=default_interval,
                            gif=enable_gif,
                            browser_html=enable_browser,
                            flag_interval=enable_interval_graph)
        if enable_gif is True or exist_gif is True:

            frame_files = sorted(glob.glob("throughput_graphs/frame_*.png"))

            if not frame_files:
                print("No frames found. Skipping video creation.")
            else:
                print(f"Creating video from {len(frame_files)} frames...")

                ffmpeg_cmd = [
                    "ffmpeg",
                    "-y",  # overwrite output
                    "-framerate", "0.5",
                    "-i", "throughput_graphs/frame_%04d.png",
                    "-c:v", "libx264",
                    "-preset", "slow",
                    "-crf", "18",
                    "-pix_fmt", "yuv420p",
                    "Throughput.mp4"
                ]

                subprocess.run(ffmpeg_cmd, check=True)

                print("Video saved as Throughput.mp4")


