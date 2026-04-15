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

adapter = []

'''
Example: of how to create txt file with nessacary measures and order:
& tshark -r pcap_file
-T fields -e frame.number -e frame.time_epoch -e frame.time_relative -e eth.src -e eth.dst -e eth.type -e frame.protocols -e batadv.batman.packet_type
-e batadv.ogm2.orig -e batadv.ogm2.throughput > edges_d0_d4.txt
'''


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

def extract_uplink_macs(reference_data):
    uplink_macs = []

    for data in reference_data.values():
        mac_dict = data.get('mac', {})

        for iface, mac in mac_dict.items():
            if 'uplink' in iface:
                uplink_macs.append(mac)

    return uplink_macs

def creation_of_edges_OGM2(*,
                      G,
                      file: str,
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
    
    with open(file, "r", encoding="utf-16", errors="ignore") as f:
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
                    if len(parts) == 10:
                        bat_type = clean(parts[7])
                        bat_types = [b.strip() for b in bat_type.split(",")]
                        OGM2_orig_addr = clean(parts[8])
                        OGM2_orig_addrs = [O.strip() for O in OGM2_orig_addr.split(",")]
                        OGM2_tp = clean(parts[9])
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
                    if len(parts) == 10:
                        bat_type = clean(parts[7])
                        OGM2_orig_addr = clean(parts[8])
                        # may need to split at , for bat_type and OGM2_orig_addr as may entail more then one
                        bat_types = [b.strip() for b in bat_type.split(",")]
                        OGM2_orig_addrs = [O.strip() for O in OGM2_orig_addr.split(",")]
                        OGM2_tp = clean(parts[9])
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
                      file: str,
                      start_time: int = 0,
                      OGM2_orig_mac: str,
                      time_interval: float = 1,
                      eth_src: str = None,
                      node_id: str):
    
    '''
    docstring:
    G: networksx with need to be nx.MultiDiGraph()
    file: network stream with format of:
    frame_number | time | relative time | eth.src | eth.dst | eth.type | frame.protocols | bat_packet_type | bat_ogm2.orig
    OGM2_orig_mac: Need to uplink from reference data of the desired node
    time_interval: How long interval to track over, OGM2 interval is 1 sec and therefore default
    '''
    
    with open(file, "r", encoding="utf-16", errors="ignore") as f:
            stop_time = start_time + time_interval
            throughput = None
            print(f"The Node id: {node_id} with Mac Adress {eth_src} | OGM Original Address to be found: {OGM2_orig_mac}")
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
                    if len(parts) == 10:
                        bat_type = clean(parts[7])
                        bat_types = [b.strip() for b in bat_type.split(",")]
                        OGM2_orig_addr = clean(parts[8])
                        OGM2_orig_addrs = [O.strip() for O in OGM2_orig_addr.split(",")]
                        OGM2_tp = clean(parts[9])
                        OGM2_tps = [
                                        TP.strip()[:-1] + "." + TP.strip()[-1]
                                        if len(TP.strip()) > 1 else TP.strip()
                                        for TP in OGM2_tp.split(",")
                                    ]
                        #print(f"{src=},{OGM2_orig_addrs=}")
                        #print(f"{eth_src=},{OGM2_orig_mac=}")
                        # if find orig OGM2 message at the orig we start timer 
                        if src == eth_src and OGM2_orig_mac in OGM2_orig_addrs and 'batadv' in protocol and '4' in bat_types:
                            index = OGM2_orig_addrs.index(OGM2_orig_mac)
                            # only print when throughput changes
                            if throughput != OGM2_tps[index]:
                                throughput = OGM2_tps[index]
                                print(f"Time is {time} | Throughput: {OGM2_tps[index]} mbit/s ")
                        else:
                            continue
                    else:   
                        continue
                else:
                    continue
    print("__________________________________________________________________________________________")
    return 

def edge_with_type_exists(G, src, dst, order):
    if not G.has_edge(src, dst):
        return None
    
    for key, data in G[src][dst].items():
        if isinstance(data, dict) and data.get("type") == order:
            return key
    
    return None

def creation_of_edges_TCP(*,
                      G,
                      file: str,
                      start_time: int = 0,
                      time_interval: int,
                      stepsize_anime: float = 1):
    
    with open(file, "r", encoding="utf-16", errors="ignore") as f:
            stop_time = start_time + time_interval
            anime_time = 0
            for i, line in enumerate(f):
                parts = line.strip().split()
                time = float(clean(parts[2]))
                if time < start_time:
                    continue
                elif time > stop_time:
                    break

                # FRAME_NR EPOCH_TIME RELATIVE_TIME SRC DST TYPE PROTOCOLS BATMAN_TYPE BATMAN_ORIG
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
                    
                    # Only make the batadv packet, not the tcp
                    if 'batadv' in p and 'tcp' in p and n == 0:
                        if G.has_edge(s, d):
                            G[s][d]["weight"] += 1
                            G[s][d]["last_time"] = time
                        else:
                            G.add_edge(s, d, type=t, weight=1, first_time = time,last_time = time)
                        break
                if time > start_time + anime_time + 1:
                    anime_time += stepsize_anime
                    if len(G.edges) > 0:
                        print(f"Animation Number: {anime_time} | Time is {time}")
                        creation_of_pyvis(G=G,reference_data=addr_data,json_nodes=json_link_nodes,index=time)
                        print("_______________________________________________________________________________")
                    # Possible filter for batman still not to know if arp or what it is
                    # if p.split(":")[2] == 'batadv' and p.split(":")[-1] == 'data':
                    # if p.split(":")[2] == 'batadv' and p+1.split(":")[-1] == 'tcp':
                    #     if G.has_edge(s, d):
                    #         G[s][d]["weight"] += 1
                    #     else:
                    #         G.add_edge(s, d, type=t, weight=1)
    return G

def creation_of_pyvis(G,
                      index: str,
                      reference_data: str,
                      json_nodes: str,
                      output_file="packet_graph.html",
                      ):
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
    nodes_adapters_macs = extract_uplink_macs(reference_data=reference_data)  # ALL MAC addresses
    for node in nodes_adapters_macs:

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
        
        # for nodes that contains links
        if "a" in node_id:
            net.add_node(node, label=f"MAC: {node} \n NODE: {node_id}", size=10, color='red',x=x/10,y=y/10,physics=False, font={'size': 300, 'bold': True})
            nodes.append((node_id, node, addr_type, addr_type_type))
        
        # for nodes that dont contain links
        elif "n" in node_id:
            net.add_node(node, label=f"MAC: {node} \n NODE: {node_id}", size=10, color='blue',x=x/10,y=y/10,physics=False, font={'size': 300, 'bold': True})
            nodes.append((node_id, node, addr_type, addr_type_type))

    # natural sort here
    nodes.sort(key=lambda x: natural_key(x[0]))

    for node_id, mac, addr_type, addr_type_type in nodes:
        net.add_node(
            mac,
            label=f"MAC: {mac}\nNODE: {node_id}\nADDR TYPE: {addr_type} {addr_type_type}"
        )
        if mac in G.nodes():
            print(f"{node_id} -> {mac}")
        else:
            print(f'{node_id} -> {mac} - This node/adapter do not contain any links')

    # Add edges with styling
    weights = [data.get("weight", 1) for _, _, data in G.edges(data=True)]
    min_w = min(weights)
    max_w = max(weights)

    for src, dst, data in G.edges(data=True):
        weight = data.get('weight',1)
        norm = normalize(w=weight,min_w=min_w,max_w=max_w)
        color = heatmap_color(norm=norm)

        
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


        net.add_edge(
        src,
        dst,
        smooth=smooth,
        title=f"Tranmission time for: First {data.get('first_time')} | Last {data.get('last_time')} |  count: {weight}",        
        # title=f"Order of message: {data.get('type')}| Throughput = {data.get('TP')} mbit/s | count: {weight}",
        color= color,               
        width=1 + np.log1p(weight)  # optional smoother scaling
    )

    # Save and open
    # Save HTML (DO NOT use show)
    name_graph = f"{output_file}_time_{index}.html"
    net.write_html(name_graph)

    # Inject auto-fit script
    with open(name_graph, "r+", encoding="utf-8") as f:
        html = f.read()

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
        """

        html = html.replace("</body>", injection + "\n</body>")

        f.seek(0)
        f.write(html)
        f.truncate()
    webbrowser.open("file://" + os.path.abspath(name_graph))

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="What Parameters mean")
    parser.add_argument("-in","--input", type=str ,help ="Input file location | NEEDS TO BE TXT")
    parser.add_argument("-addr","--addresses",type=str, help ="Json file including all associated adresses for the Nodes, Adapters, Devices (node_addr.json)")
    parser.add_argument("-j","--json",type=str, help ="Json file Including pos of nodes (graph.json)")
    args = parser.parse_args()

    analysis_file = args.input
    addr_file = args.addresses
    json_link_nodes = args.json

    capture = pyshark.FileCapture(analysis_file)

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
    Mac_a0= mac_node("a0",reference_data=addr_data)
    Mac_n8= mac_node("n8",reference_data=addr_data)
    Mac_n6= mac_node("n6",reference_data=addr_data)
    Mac_n5= mac_node("n5",reference_data=addr_data)
    Mac_n4= mac_node("n4",reference_data=addr_data)   
    Mac_a4= mac_node("a4",reference_data=addr_data)
    
    # For debug of why we take a shortcut looking at throughput from OGM2
    # tracking_of_OGM2_at_source(file=analysis_file,start_time=13,OGM2_orig_mac=Mac_a4,time_interval=20,eth_src=Mac_n6,node_id="n6")
    # tracking_of_OGM2_at_source(file=analysis_file,start_time=13,OGM2_orig_mac=Mac_a4,time_interval=20,eth_src=Mac_n5,node_id="n5")

    # tracking_of_OGM2_at_source(file=analysis_file,start_time=13,OGM2_orig_mac=Mac_a0,time_interval=20,eth_src=Mac_n4,node_id="n4")
    # tracking_of_OGM2_at_source(file=analysis_file,start_time=13,OGM2_orig_mac=Mac_a0,time_interval=20,eth_src=Mac_n5,node_id="n5")
    # tracking_of_OGM2_at_source(file=analysis_file,start_time=13,OGM2_orig_mac=Mac_a0,time_interval=20,eth_src=Mac_n8,node_id="n8")
    # tracking_of_OGM2_at_source(file=analysis_file,start_time=13,OGM2_orig_mac=Mac_a0,time_interval=20,eth_src=Mac_n6,node_id="n6")

    # tracking_of_OGM2_at_source(file=analysis_file,start_time=13,OGM2_orig_mac=Mac_a4,time_interval=20,eth_src=Mac_n4,node_id="n4")
    # tracking_of_OGM2_at_source(file=analysis_file,start_time=13,OGM2_orig_mac=Mac_a4,time_interval=20,eth_src=Mac_n5,node_id="n5")
    # tracking_of_OGM2_at_source(file=analysis_file,start_time=13,OGM2_orig_mac=Mac_a4,time_interval=20,eth_src=Mac_n8,node_id="n8")
    
    G = creation_of_edges_TCP(G=G,file=analysis_file,start_time=0, time_interval=30,stepsize_anime=2)

    # creation_of_pyvis(G=G,reference_data=addr_data,json_nodes=json_link_nodes)

