import re
import numpy as np
import json
import os
import webbrowser
from pyvis.network import Network

###############################################################################
#______________________________ HELPER FUNCTIONS _____________________________#
###############################################################################

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

def natural_key(text):
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r'(\d+)', text)
    ]

def heatmap_color(norm):
    if norm < 0.25:
        return f"rgb(0,{int(255 * norm * 4)},255)"         # blue → cyan
    elif norm < 0.5:
        return f"rgb(0,255,{int(255 * (1 - (norm - 0.25)*4))})"  # cyan → green
    elif norm < 0.75:
        return f"rgb({int(255 * (norm - 0.5)*4)},255,0)"   # green → yellow
    else:
        return f"rgb(255,{int(255 * (1 - (norm - 0.75)*4))},0)"  # yellow → red

def normalize(w,min_w,max_w):
    if max_w == min_w:
        return 0.5
    return (w - min_w) / (max_w - min_w)

def format_unit(value):
    units = ["", "K", "M", "G", "T"]
    scale = 1000.0  # use 1024.0 if you prefer binary units

    i = 0
    while value >= scale and i < len(units) - 1:
        value /= scale
        i += 1

    return f"{value:.2f} {units[i]}"

def setting_node_attributes(node_mac,
                            node_id,
                            node_states: dict,
                            last_rendered_time: float,
                            time: float,
                            flag_interval: bool,
                            plot_type: str):
    
    
    # Node coloring
    color = "gray"
    if "a" in node_id:
        color = "red"
    elif "n" in node_id:
        color = "blue"
    elif "d" in node_id:
        color = "green" if plot_type == "throughput" else "blue"

    # Setting label and shape for different states
    label = f"MAC: {node_mac}\nNODE: {node_id}"
    shape = "dot"
    current_state = None

    if node_id in node_states:

        # Find current state at time
        for t, state in node_states[node_id]:
            if t <= time:
                current_state = state
            else:
                break

        # Find event in current interval
        for t, state in node_states[node_id]:
            if last_rendered_time < t <= time:
                label += f"\nSTATE CHANGE: {state} at {t:.2f}s"

        # Set shape based on current state
        if current_state == "DOWN":
            shape = "square"
            color = 'black'
        else:
            shape = "dot"
    
    return label, shape, color

###############################################################################
#_______________________________ HTML FUNCTIONS ______________________________#
###############################################################################

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
            <div>Packet interval <b>""" + f"{packet_prev}" + """ - """ + f"{current_pkt}" + """</b> pkts read out of <b>""" + f"{total_pkts}" + """</b> pkts</div>
            <div>Time of interval <b>""" + f"{time_prev:.2f}" + """ - """ + f"{time:.2f}"  + """</b> out of <b>""" + f"{total_time:.2f}" + """</b> total time of instance </div>
            <div>UP/DOWN  snapshot at <b>""" + f"{time:.2f}" """</b></div>
        </div>
        """
    return injection

###############################################################################
#___________________________ VISUALIZATION FUNCTIONS _________________________#
###############################################################################

def creation_of_pyvis(G,
                      index: str,
                      reference_data: str,
                      json_nodes: str,
                      current_pkt: str,
                      total_pkts: str,
                      time: float,
                      total_time: float,
                      time_prev: float,
                      last_rendered_time: float,
                      packet_prev: int,
                      output_file: str = "packet_graph.html",
                      states: tuple = None,
                      browser_html: bool = False,
                      flag_interval: bool = False,
                      plot_type: str = 'TCP'):
    
    precision_number = 1e-7

    # Get name, time and state for when states changes
    node_states = states if states else {}

    # ensure still work even with wierd spacing and upper and lower casing wording
    plot_type = plot_type.strip().lower()
    print(f"Creating Pyvis HTML at time: {time}")
    # Create PyVis network
    net = Network(height="100vh", width="100vw", directed=True, bgcolor="grey", font_color="black")
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

        label, shape, color = setting_node_attributes(node_mac=node,
                                                      node_id=node_id,
                                                      node_states=node_states,
                                                      last_rendered_time=last_rendered_time,
                                                      time=time,
                                                      flag_interval=flag_interval,
                                                      plot_type=plot_type)

        net.add_node(
            node,
            label=label,
            size=10,
            color=color,
            x=x / 10,
            y=y / 10,
            physics=False,
            shape=shape
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
                physics=False,
                shape=shape
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
       
        # Insert injection
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
                                               total_pkts=total_pkts,time=time,
                                               total_time=total_time)

        html = html.replace("</body>", injection + "\n</body>")

        f.seek(0)
        f.write(html)
        f.truncate()
    if browser_html is True:
        webbrowser.open("file://" + os.path.abspath(output_file))
