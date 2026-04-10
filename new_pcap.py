import networkx as nx
from pyvis.network import Network
import argparse
import json
import re
import pyshark
from tqdm import tqdm
import numpy as np
from dataclasses import dataclass

adapter = []

'''
Example: of how to create txt file with nessacary measures and order:
& tshark -r pcap_file
-T fields -e frame.number -e frame.time_epoch -e frame.time_relative -e eth.src -e eth.dst -e eth.type -e frame.protocols -e batadv.batman.packet_type
-e batadv.ogm2.orig > edges_d0_d4.txt
'''



@dataclass
class Node:
    id: str
    x: int
    y: int
    z: int

a0 = Node(id="a0", x=0,y=0,z=0)
a1 = Node(id="a1", x=3000,y=3000,z=3000)
a2 = Node(id="a2", x=1000,y=10000,z=10000)
a3 = Node(id="a3", x=12000,y=5000,z=1500)
a4 = Node(id="a4", x=25000,y=9000,z=3000)

adapter.append(a0)
adapter.append(a1)
adapter.append(a2)
adapter.append(a3)
adapter.append(a4)


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
                      start_packet: int = 0,
                      stop_packet: int):
    
    with open(file, "r", encoding="utf-16", errors="ignore") as f:
            for i, line in enumerate(f):
                if i < start_packet:
                    continue
                if i >= stop_packet:
                    break

                parts = line.strip().split()
                # Frame_NR SRC DST TYPE

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
                        else:
                            G.add_edge(s, d, type=t, weight=1)

                        break

                    # Possible filter for batman still not to know if arp or what it is
                    # if p.split(":")[2] == 'batadv' and p.split(":")[-1] == 'data':
                    # if p.split(":")[2] == 'batadv' and p+1.split(":")[-1] == 'tcp':
                    #     if G.has_edge(s, d):
                    #         G[s][d]["weight"] += 1
                    #     else:
                    #         G.add_edge(s, d, type=t, weight=1)
    return G

def creation_of_pyvis(G,
                      reference_data: str,
                      json_nodes: str,
                      output_file="packet_graph.html"):
    # Create PyVis network
    net = Network(height="800px", width="100%", directed=True, bgcolor="#222222", font_color="white")

    # Optional: better physics (important for mesh graphs)
    net.barnes_hut()

    with open(json_nodes,"r") as f:
        node_link_data = json.load(f)
    nodes_pos_data = node_link_data.get("nodes", [])
    pos_lookup = {n["id"]: n for n in nodes_pos_data}
    adapter_pos_lookup = {a.id: a for a in adapter}
    # Add nodes + edges
    nodes = []
    for node in G.nodes():
        node_info = find_mac_path(reference_data, node)

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
        net.add_node(node, label=f"MAC: {node} \n NODE: {node_id} \n ADDR TYPE {addr_type} {addr_type_type}",x=x,y=y,physics=False)
        nodes.append((node_id, node, addr_type, addr_type_type))

    # natural sort here
    nodes.sort(key=lambda x: natural_key(x[0]))

    for node_id, mac, addr_type, addr_type_type in nodes:
        net.add_node(
            mac,
            label=f"MAC: {mac}\nNODE: {node_id}\nADDR TYPE {addr_type} {addr_type_type}"
        )
        print(f"{node_id} -> {mac}")

    weights = [data.get("weight", 1) for _, _, data in G.edges(data=True)]
    min_w = min(weights)
    max_w = max(weights)

    for src, dst, data in G.edges(data=True):
        weight = data.get('weight',1)
        norm = normalize(w=weight,min_w=min_w,max_w=max_w)
        color = heatmap_color(norm=norm)
        net.add_edge(
        src,
        dst,
        title=f"Order of message: {data.get('type')}| Throughput = {data.get('TP')} mbit/s | count: {weight}",
        color= color,               # controls thickness
        width=1 + np.log1p(weight)  # optional smoother scaling
    )

    # Save and open
    net.write_html(output_file, open_browser=True, notebook=False)

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
    parser.add_argument("-addr","--addresses",type=str, help ="Json file including all associated adresses for the Nodes,Adapters,Devices")
    parser.add_argument("-j","--json",type=str, help ="Json file Including pos of nodes")
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
    G = nx.MultiDiGraph()
    Mac_a4= mac_node("a4",reference_data=addr_data)
    creation_of_edges_OGM2(G=G,file=analysis_file,start_time=20,OGM2_orig_mac=Mac_a4,time_interval=1)

    # TPC stream seing how it goes through the netwrok of iperf tcp stream
    # Build graph
    #G = nx.DiGraph()
    # G = creation_of_edges_TCP(G=G,file=analysis_file,start_packet=start,stop_packet=end)
    
    creation_of_pyvis(G=G,reference_data=addr_data,json_nodes=json_link_nodes)

