import networkx as nx
import argparse
import json
import os
import time
import glob
import subprocess
import shutil
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from pyvis_utils import (find_mac_path,
                         creation_of_pyvis)

adapter = []

'''
Example: of how to create txt file with nessacary measures and order:
& tshark -r pcap_file
-T fields -e frame.number -e frame.time_epoch -e frame.time_relative -e eth.src -e eth.dst -e eth.type -e frame.protocols -e frame.len -e batadv.batman.packet_type 
-e batadv.ogm2.orig -e batadv.ogm2.throughput -e batadv.ogm2.ttl > edges_d0_d4.txt
'''
# maybe add this when need to track unicast -e batadv.unicast.dst -e batadv.unicast.ttl

###############################################################################
#__________________________ HELPER FUNCTIONS _________________________________#
###############################################################################

def clean(x):
    return x.encode("utf-8", "ignore").decode("utf-8").strip()

def edge_with_type_exists(G, src, dst, order):
    if not G.has_edge(src, dst):
        return None
    
    for key, data in G[src][dst].items():
        if isinstance(data, dict) and data.get("type") == order:
            return key
    
    return None

def mac_node(node_id: str, reference_data: dict):
    macs = reference_data[node_id]["mac"]
    
    for interface, mac in macs.items():
        if interface.startswith("uplink"):
            return mac
    print(f"No Mac address of uplink found for {node_id} in {reference_data}")
    return None

def run_tshark(pcap_file, output_txt):
    # Find tshark
    tshark_path = shutil.which("tshark")

    if not tshark_path:
        candidate = r"C:\Program Files\Wireshark\tshark.exe"
        if os.path.exists(candidate):
            tshark_path = candidate

    if not tshark_path:
        raise RuntimeError(
            "tshark not found. Install Wireshark or add tshark to PATH."
        )

    # Build command
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

    # Run tshark
    print("CWD:", os.getcwd())
    print("Writing to:", os.path.abspath(output_txt))
    with open(output_txt, "w") as f:
        subprocess.run(cmd, stdout=f, check=True)

def mp4_creation(output_dir: str,
                 file_name: str,
                 input_pcap_name: str):
    
    frame_files = sorted(glob.glob(f"{output_dir}/{input_pcap_name}/frame_*.png"))

    if not frame_files:
        print("No frames found. Skipping video creation.")
    else:
        print(f"Creating video from {len(frame_files)} frames...")

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-framerate", "0.5",
            "-i", f"{output_dir}/{input_pcap_name}/frame_%04d.png",
            "-vf", "scale=1920:1080:flags=lanczos",
            "-c:v", "libx264",
            "-preset", "veryslow",
            "-crf", "12",
            "-pix_fmt", "yuv420p",
            f"{output_dir}/{input_pcap_name}/{file_name}.mp4"
        ]

        subprocess.run(ffmpeg_cmd, check=True)

        print(f"Video saved at {output_dir}/{input_pcap_name}/{file_name}.mp4")

def html_to_png(html_file, output_png):
    assert os.path.exists(html_file), html_file

    WIDTH = 1920
    HEIGHT = 1200

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument(f"--window-size={WIDTH},{HEIGHT}")
    options.add_argument("--force-device-scale-factor=4")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")

    # Insert this for thias to work
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    #driver = webdriver.Chrome(options=options)

    try:
        # load page
        driver.get("file://" + os.path.abspath(html_file))

        # # wait for page to fully load
        # WebDriverWait(driver, 10).until(
        #     lambda d: d.execute_script("return document.readyState") == "complete"
        # )

        # extra wait for PyVis JS rendering
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return window.network !== undefined")
        )
        time.sleep(2)

        # enforce size (important for consistent PNGs)
        driver.set_window_size(WIDTH, HEIGHT)

        # screenshot
        driver.save_screenshot(output_png)

    finally:
        driver.quit()

def get_state_changes(sim_file: str):

    states = {}

    with open(sim_file) as f:
        data = json.load(f)

    for item in data['sched_plan']:   # Should maybe be changed to sched_real
        event = item['event']

        if 'state' in event:
            name = event['name']
            time = item['time']
            state = event['state']

            if name not in states:
                states[name] = []

            states[name].append((time, state))

    return states

###############################################################################
#__________________________ EXECUTION FUNCTIONS ______________________________#
###############################################################################

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
                        # may need to split at, for bat_type and OGM2_orig_addr as may entail more then one
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

def all_link_throughput(*,
                      G,
                      file: str,
                      encoding: str,
                      start_time: int = 0,
                      stop_time: int,
                      stepsize_anime: float = 1,
                      gif: bool = False,
                      browser_html: bool = False,
                      flag_interval: bool = False,
                      input_pcap_name: str,
                      output_dir: str,
                      states: tuple = None):
    
    last_rendered_time = start_time
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
                        os.makedirs(output_dir, exist_ok=True)
                        frame_idx += 1
                        base_folder = f'{output_dir}/{input_pcap_name}'
                        html_file = f"{base_folder}/graph_{float(time):.2f}.html"
                        png_file = f"{base_folder}/frame_{frame_idx:04d}.png"
                        Path(html_file).parent.mkdir(parents=True, exist_ok=True)
                        Path(png_file).parent.mkdir(parents=True, exist_ok=True)
                        creation_of_pyvis(G=G,
                                          index=time,
                                          reference_data=addr_data,
                                          json_nodes=json_link_nodes,
                                          current_pkt = pkt_num,
                                          total_pkts = tot_pkts,
                                          time = time,
                                          total_time = tot_time,
                                          time_prev = time_prev,
                                          last_rendered_time=last_rendered_time,
                                          packet_prev=packet_prev,
                                          plot_type='Throughput',
                                          output_file=html_file,
                                          states=states,
                                          browser_html = browser_html,
                                          flag_interval=flag_interval)
                        print("_______________________________________________________________________________")
                        #first_time_tcp_packet = None
                        last_rendered_time = time

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
                          flag_interval: bool = False,
                          states: dict = None,
                          plot_type: str,
                          input_pcap_name: str,
                          output_dir: str):

    last_rendered_time = start_time
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
                        os.makedirs(output_dir, exist_ok=True)
                        frame_idx += 1
                        base_folder = f'{output_dir}/{input_pcap_name}'
                        html_file = f"{base_folder}/graph_{float(time):.2f}.html"
                        png_file = f"{base_folder}/frame_{frame_idx:04d}.png"
                        Path(html_file).parent.mkdir(parents=True, exist_ok=True)
                        Path(png_file).parent.mkdir(parents=True, exist_ok=True)
                        print(f"TCP & UDP streams existing is:")

                        # sort after count amount
                        for (s, d,stream_type), info in sorted(tcp_streams.items(),
                           key=lambda item: item[1]['count'],
                           reverse=True):
                            print(f"Type: {stream_type} | Node: Src {info['src_node']} -> Dst {info['dst_node']} | Link Use Count: {info['count']}|||",
                                f"Mac info: SRC {s} type: {info['src_mac_type']} | DST {d} type: {info['dst_mac_type']}")
                        creation_of_pyvis(G=G,
                                          index=time,
                                          reference_data=addr_data,
                                          json_nodes=json_link_nodes,
                                          current_pkt=pkt_num,
                                          total_pkts=tot_pkts,
                                          time=time,
                                          total_time=tot_time,
                                          time_prev=time_prev,
                                          last_rendered_time=last_rendered_time,
                                          packet_prev=packet_prev,
                                          plot_type=plot_type,
                                          output_file=html_file,
                                          states=states,
                                          browser_html=browser_html,
                                          flag_interval=flag_interval)
                        print("_______________________________________________________________________________")
                        first_time_tcp_packet = None
                        last_rendered_time = time

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

if __name__ == "__main__":

    default_start_time = 0
    default_stop_time = 30
    default_interval = 5

    parser = argparse.ArgumentParser(description="What Parameters mean")
    parser.add_argument("-in", "--input", type=str, help="Input file location | Either folder of pcaps, single pcap or txt file")
    parser.add_argument("-addr", "--addresses", type=str, help="Json file including all associated adresses for the Nodes, Adapters, Devices (node_addr.json)")
    parser.add_argument("-j", "--json", type=str, help="Json file including pos of nodes (graph.json)")
    parser.add_argument("-s", "--states", type=str, help="Json file for simulation schedule (reroute.json)")
    parser.add_argument("-gif", "--gif_enabled", action="store_true", help="enable creation of gif from png's, (png's are not created if gif is disabled)")
    parser.add_argument("-e", "--existing_png_for_gif", action="store_true", help="Don't recreate png, for gif instead use already existing pngs created previously")
    parser.add_argument("-b", "--browser", action="store_true", help="If to enable that the HTML plots are opened in the browser")
    parser.add_argument("-f", "--flag_interval", action="store_true", help="Set to enable HTML for intervals")
    parser.add_argument("-sta", "--start_time", type=float, help="Choose start time for analysis. Default = 0 sec")
    parser.add_argument("-sto", "--stop_time", type=float, help="Choose stop time for analysis. Default = 30 sec")
    parser.add_argument("-i", "--interval", type=float, help="Choose interval size of windows. Default = 5 sec")
    parser.add_argument("-m", "--method", type=str, help="Choose type of analysis method. throughput, tcp, udp or (ogm, ogm2, ogmv2).")
    parser.add_argument("-ogm_orig", "--ogmv2_originator", type=str, help="Choose ogmv2 originator node. Can be multiple nodes (n1,n2)")
    parser.add_argument("-ogm_eth_src", "--ogmv2_ethernet_source", type=str, help="Choose ogmv2 ethernet source node. Can be multiple nodes (n1,n2)")
    parser.add_argument("-o", "--output_dir", type=str, help="(Optional) Set an output directory.")

    args = parser.parse_args()

    analysis_file = args.input
    addr_file = args.addresses
    json_link_nodes = args.json
    states_json = args.states
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
    output_dir = args.output_dir
    method_type = method_type.strip().lower()

    states = None
    if states_json is not None:
        states = get_state_changes(states_json)

    if start_time is not None:
        default_start_time = start_time
    if stop_time is not None:
        default_stop_time = stop_time
    if interval_time is not None:
        default_interval = interval_time

    with open(addr_file,"r") as f:
        addr_data = json.load(f)
    
    # Save files in method_type folder
    method_dirs = {
    'throughput': 'throughput_graphs',
    'tcp': 'stream_graphs',
    'udp': 'stream_graphs',
    'ogm': 'ogm_files',
    'ogmv2': 'ogm_files',
    'ogm2': 'ogm_files'
    }

    if method_type not in method_dirs:
        print(f"ERROR: Invalid method '{method_type}'. Change -m to valid method.")
        exit()
    
    subdir = method_dirs[method_type]

    if output_dir is None:
        output_dir = subdir
    else:
        output_dir = os.path.join(output_dir, subdir)
    os.makedirs(output_dir, exist_ok=True)

    # Makes it possible to input multiple pcaps from folder or a single pcap    
    input_path = Path(analysis_file)

    if input_path.is_dir():
        pcap_files = list(input_path.glob("*.pcap"))
    else:
        pcap_files = [input_path]

    # Allow both pcap and txt from analysis file
    for pcap in pcap_files:
        analysis_file = str(pcap)
        input_name = pcap.stem
        print(f"Processing: {pcap.name}")

        if analysis_file.endswith(".txt"):   
            encoding = "utf-16"
        if analysis_file.endswith(".pcap"):
            if output_dir is None:
                output_dir_tshark = os.path.join(os.getcwd(), "tshark_outputs")
            else:
                output_dir_tshark = os.path.join(output_dir, "tshark_outputs")    
            os.makedirs(output_dir_tshark, exist_ok=True)

            txt_file = os.path.join(
                output_dir_tshark,
                os.path.splitext(os.path.basename(analysis_file))[0] + ".txt"
            )
            encoding = "utf-8"
            run_tshark(analysis_file, txt_file)
            analysis_file = txt_file  # continue using the generated txt

        # ensure input either given txt or converted to txt
        if not analysis_file.endswith(".txt"):
            print(f"ERROR: Failed to resolve analysis file ({pcap}) to .txt")
            exit()

        # TPC stream seing how it goes through the netwrok of iperf tcp stream
        # Build graph
        G = nx.DiGraph()

        if method_type == 'ogmv2' or method_type == 'ogm' or method_type == 'ogm2':
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
                                                encoding=encoding,
                                                start_time=13,
                                                OGM2_orig_mac=MAC_orig_node,
                                                time_interval=20,
                                                eth_src=MAC_eth_src_node)

        if method_type == 'tcp' or method_type == 'udp':
            G = creation_of_edges_TCP(G=G,
                                    file=analysis_file,
                                    encoding=encoding,
                                    start_time=default_start_time,
                                    stop_time=default_stop_time,
                                    stepsize_anime=default_interval,
                                    gif=enable_gif,
                                    browser_html=enable_browser,
                                    flag_interval=enable_interval_graph,
                                    states=states,
                                    plot_type=method_type,
                                    input_pcap_name=input_name,
                                    output_dir=output_dir)
            
            if enable_gif is True or exist_gif is True:
                mp4_creation(output_dir=output_dir, file_name='tcp_and_udp_streams', input_pcap_name=input_name)

        if method_type == 'throughput':
            F = all_link_throughput(G=G,
                                    file=analysis_file,
                                    encoding=encoding,
                                    start_time=default_start_time,
                                    stop_time=default_stop_time,
                                    stepsize_anime=default_interval,
                                    gif=enable_gif,
                                    browser_html=enable_browser,
                                    flag_interval=enable_interval_graph,
                                    input_pcap_name=input_name,
                                    output_dir=output_dir,
                                    states=states)
            
            if enable_gif is True or exist_gif is True:
                mp4_creation(output_dir=output_dir, file_name='Throughput', input_pcap_name=input_name)