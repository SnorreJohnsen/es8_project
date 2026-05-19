import re
import numpy as np
import json
import os
import webbrowser
from pyvis.network import Network

def extract_node_info(graph_json, addrs_json):

    # build base dict from graph - ALL nodes/adapters included
    result = {
        n["id"]: {"x": n["x"], "y": n["y"], "z": n["z"]}
        for n in graph_json["nodes"]
        if n["id"].startswith(("n", "a", "d"))
    }

    for node_id, info in addrs_json.items():
        if node_id not in result:
            continue

        interfaces = {
            iface: mac_addr
            for iface, mac_addr in info.get("mac", {}).items()
            if iface != "lo" and mac_addr != "00:00:00:00:00:00"
        }

        preferred_mac = None

        # Prefer uplink for plotting/PyVis identity
        for iface, mac_addr in interfaces.items():
            if iface.startswith("uplink"):
                preferred_mac = mac_addr
                break

        # Fallbacks for nodes that do not have uplink, e.g. d* devices
        if preferred_mac is None:
            for prefix in ("veth0", "lan0", "bat0", "br-lan"):
                for iface, mac_addr in interfaces.items():
                    if iface.startswith(prefix):
                        preferred_mac = mac_addr
                        break
                if preferred_mac is not None:
                    break

        result[node_id]["mac"] = preferred_mac
        result[node_id]["interfaces"] = interfaces

    return result

def extract_link_metrics(graph_json, bidirectional=True):
    result = {}

    for link in graph_json.get('links', []):
        src = link.get('source')
        dst = link.get('target')

        if src is None or dst is None:
            continue

        phyrate = link.get('phyrate_mbps')
        loss = link.get('loss_percent')

        metrics = {
            'phyrate_mbps': float(phyrate) if phyrate is not None else None,
            'loss_percent': float(loss) if loss is not None else None
        }

        result[(src, dst)] = metrics

        if bidirectional:
            result[(dst, src)] = metrics.copy()
    
    return result

def build_mac_lookup(node_adapters_info):
    """
    Maps every known MAC address to:
    {
        "node_id": ...,
        "interface": ...,
        "plot_mac": ...  # preferred/uplink MAC
    }
    """

    mac_lookup = {}

    for node_id, info in node_adapters_info.items():
        plot_mac = info.get("mac")
        if plot_mac is None:
            continue

        for iface, mac_addr in info.get("interfaces", {}).items():
            mac_lookup[mac_addr.lower()] = {
                "node_id": node_id,
                "interface": iface,
                "plot_mac": plot_mac.lower()
            }

    return mac_lookup

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

def heatmap_color(norm):
    if norm < 0.25:
        return f"rgb(0,{int(255 * norm * 4)},255)"         # blue → cyan
    elif norm < 0.5:
        return f"rgb(0,255,{int(255 * (1 - (norm - 0.25)*4))})"  # cyan → green
    elif norm < 0.75:
        return f"rgb({int(255 * (norm - 0.5)*4)},255,0)"   # green → yellow
    else:
        return f"rgb(255,{int(255 * (1 - (norm - 0.75)*4))},0)"  # yellow → red

def normalize(w, min_w, max_w):

    if max_w == min_w:
        return 0.5

    x = (w - min_w) / (max_w - min_w)
    x = max(0.0, min(1.0, x))
    x = x ** 0.6

    return float(x)

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
                            plot_type: str):
    
    # Setting shape for different states
    shape = "dot"
    current_state = None

    # Node coloring
    color = "gray"
    if "a" in node_id:
        color = "red"
        #label = f"MAC: {node_mac}\nADAPTER: {node_id}"
        label = f"ADAPTER: {node_id}"   # only use this for figure
        shape = 'triangle'
    elif "n" in node_id:
        color = "blue"
        #label = f"MAC: {node_mac}\nNODE: {node_id}"
        label = f"NODE: {node_id}"   # only use this for figure
    elif "d" in node_id:
        color = "green" if plot_type == "throughput" else "blue"
        #label = f"MAC: {node_mac}\nDEVICE: {node_id}"
        label = f"DEVICE: {node_id}"   # only use this for figure

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

##############################################################################
#_______________________________ HTML FUNCTIONS ______________________________#
###############################################################################

def build_injection(color_bar_title: str,
                    color_bar_data_links: list,
                    color_bar_data_nodes: list,
                    current_pkt: int,
                    total_pkts: int,
                    time: float,
                    total_time: float,
                    interval: bool = False,
                    time_prev: float = None,
                    packet_prev: int = None):
    
    # For links
    arr_links = np.array(color_bar_data_links)
    min_links = np.min(arr_links)
    q1_links = np.percentile(arr_links, 25)
    median_links = np.percentile(arr_links, 50)
    q3_links = np.percentile(arr_links, 75)
    max_links = np.max(arr_links)

    # For nodes
    arr_nodes = np.array(color_bar_data_nodes)
    min_nodes = np.min(arr_nodes)
    q1_nodes = np.percentile(arr_nodes, 25)
    median_nodes = np.percentile(arr_nodes, 50)
    q3_nodes = np.percentile(arr_nodes, 75)
    max_nodes = np.max(arr_nodes)

    if interval:
        if time_prev is None or packet_prev is None:
            raise ValueError("time_prev and packet_prev must be provided when interval=True")
        
        packet_info_html = """
        <div id="packet-info">
            <div> Packet interval <b>""" + f"{packet_prev}" + """ - """ + f"{current_pkt}" + """</b> pkts read out of <b>""" + f"{total_pkts}" + """</b> pkts </div>
            <div> Time of interval <b>""" + f"{time_prev:.2f}" + """ - """ + f"{time:.2f}" + """</b> out of <b>""" + f"{total_time:.2f}" + """</b> total time of instance </div>
            <div> UP/DOWN snapshot at <b>""" + f"{time:.2f}" + """</b> </div>
        </div>
        """
    else:
        packet_info_html = """
        <div id="packet-info">
            <div><b>""" + f"{current_pkt}" + """</b> pkts read out of <b>""" + f"{total_pkts}" + """</b> pkts</div>
            <div>Time of instance <b>""" + f"{time:.2f}" + """</b> out of <b>""" + f"{total_time:.2f}" + """</b> total time of instance </div>
        </div>
        """

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
        width: 800px;
        padding: 24px;
        background: white;
        border-radius: 18px;
        font-family: Arial;
        font-size: 28px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        z-index: 9999;
    }
    #heatmap-container {
        display: flex;
        align-items: center;
        gap: 30px;
    }
    #heatmap-main {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        height: 90px;
        flex: 1;
    }
    #heatmap-bar {
        height: 30px;
        width: 100%;
        border-radius: 10px;
        background: linear-gradient(
            to right,
            rgb(0,0,255),
            rgb(0,255,255),
            rgb(0,255,0),
            rgb(255,255,0),
            rgb(255,0,0)
        );
    }
    #heatmap-labels-top,
    #heatmap-labels {
        display: flex;
        justify-content: space-between;
        font-size: 24px;
    }
    #heatmap-side-text {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        height: 90px;
        font-size: 24px;
        font-weight: bold;
        white-space: nowrap;
    }
    #packet-info {
        position: fixed;
        top: 20px;
        left: 30px;
        background: rgba(255, 255, 255, 0.9);
        padding: 16px 24px;
        border-radius: 18px;
        font-family: Arial;
        font-size: 28px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2);
        z-index: 9999;
    }

    </style>
    <div id="heatmap-legend">
        <b>""" + f'{color_bar_title}' + """</b>
        <div id="heatmap-container">
            <div id="heatmap-side-text">
                <div>node</div>
                <div>link</div>
            </div>
            <div id="heatmap-main">
                <div id="heatmap-labels-top">
                    <span>""" + f"{format_unit(min_nodes)}" + """</span>
                    <span>""" + f"{format_unit(q1_nodes)}" + """</span>
                    <span>""" + f"{format_unit(median_nodes)}" + """</span>
                    <span>""" + f"{format_unit(q3_nodes)}" + """</span>
                    <span>""" + f"{format_unit(max_nodes)}" + """</span>
                </div>

                <div id="heatmap-bar"></div>

                <div id="heatmap-labels">
                    <span>""" + f"{format_unit(min_links)}" +"%" + """</span>
                    <span>""" + f"{format_unit(q1_links)}" + "%" + """</span>
                    <span>""" + f"{format_unit(median_links)}" + "%" + """</span>
                    <span>""" + f"{format_unit(q3_links)}" + "%" + """</span>
                    <span>""" + f"{format_unit(max_links)}" + "%" + """</span>
                </div>
            </div>
        </div>
    </div>
    """ + packet_info_html

    return injection

###############################################################################
#___________________________ VISUALIZATION FUNCTIONS _________________________#
###############################################################################

def compute_graph_metrics(G,
                          plot_type: str,
                          time: float,
                          time_prev: float,
                          precision_number: float=1e-7):
    
    # Add nodes and edges with styling
    link_values = []
    node_tx = {}

    for src, dst, data in G.edges(data=True):
        if plot_type == 'tcp':
            v = data.get('weight', 1)
        elif plot_type == 'udp':
            v = data.get('weight', 1)
        elif plot_type == 'throughput':
            #dt = max(data.get('last_time') - data.get('first_time'), precision_number)   # burst throughput
            dt = max(time - time_prev, precision_number)   # interval throughput 
            bits = data.get("bits", 0)
            v = bits / dt
        link_values.append(v)
        node_tx[src] = node_tx.get(src, 0) + v # outgoing transmission from a node

    node_values = list(node_tx.values())

    return link_values, node_values, node_tx

def creation_of_pyvis(G,
                      index: str,
                      addr_data: str,
                      graph_data: str,
                      current_pkt: str,
                      total_pkts: str,
                      time: float,
                      total_time: float,
                      time_prev: float,
                      last_rendered_time: float,
                      packet_prev: int,
                      plot_type: str,
                      output_file: str,
                      states: tuple = None,
                      browser_html: bool = False,
                      flag_interval: bool = False):
    
    precision_number = 1e-7

    # Get name, time and state for when states changes
    node_states = states if states else {}

    # ensure still work even with wierd spacing and upper and lower casing wording
    plot_type = plot_type.strip().lower()
    print(f"Creating Pyvis HTML at time: {time}")
    # Create PyVis network
    net = Network(height="100vh", width="100vw", directed=True, bgcolor="white", font_color="black")
    net.barnes_hut() # Optional: better physics (important for mesh graphs)

    # Load layout data (graph.json)
    with open(graph_data,"r") as f:
        graph_data = json.load(f)

    link_values, node_values, node_value_lookup = compute_graph_metrics(G=G,
                                                                        plot_type=plot_type,
                                                                        time=time,
                                                                        time_prev=time_prev)

    min_links = min(link_values)
    max_links = max(link_values)
    min_nodes = min(node_values)
    max_nodes = max(node_values)

    # Get info from graph.json and node_addrs.json
    node_adapters_info = extract_node_info(graph_json=graph_data, addrs_json=addr_data)
    link_info = extract_link_metrics(graph_json=graph_data)
    
    mac_to_node = {}

    for node_id, info in node_adapters_info.items():
        x = info['x']
        y = info['y']
        mac = info.get('mac')
    
        if mac:
            mac_to_node[mac.lower()] = node_id

        label, shape, color = setting_node_attributes(node_mac=mac,
                                                      node_id=node_id,
                                                      node_states=node_states,
                                                      last_rendered_time=last_rendered_time,
                                                      time=time,
                                                      plot_type=plot_type)
        
        node_value = node_value_lookup.get(mac, 0)
        norm = normalize(w=node_value,min_w=min_nodes,max_w=max_nodes)
        color = heatmap_color(norm=norm)
        if mac not in G.nodes() or node_value == 0.00:
            color = 'black'
        if plot_type in ('tcp', 'udp'):
            title = f'Transmitted packets: {format_unit(node_value)}' 
        elif plot_type == 'throughput':
            title = f'Transmitted bits: {format_unit(node_value)}bps'          

        net.add_node(
            node_id,
            label=label,
            size=10,
            title=title,
            color=color,
            x=x/20,
            y=y/20,
            physics=False,
            shape=shape
        )

        # For debugging
        if mac in G.nodes():
            print(f"{node_id:<3} -> {str(mac):<17}")
        else:
            print(f'{node_id:<3} -> {str(mac):<17} - This node/adapter do not contain any links')
    
    for src_mac, dst_mac, data in G.edges(data=True):
        # Convert MACs -> graph node IDs
        src = mac_to_node.get(src_mac.lower())
        dst = mac_to_node.get(dst_mac.lower())

        # Skip if mapping not found
        if src is None or dst is None:
            continue
    
        #  check if reverse edge exists
        has_reverse = G.has_edge(dst_mac, src_mac)

        if has_reverse and src != dst:
            smooth = {
                'enabled': True,
                'type': 'curvedCW',
                'roundness': 0.1
            }
        else:
            smooth = False

        # Lookup physical link metrics
        link_metrics = link_info.get((src, dst))
        phyrate = link_metrics.get("phyrate_mbps") if link_metrics else None
        loss_percent = link_metrics.get("loss_percent") if link_metrics else None

        if plot_type == 'tcp':
            value = data.get('weight',1)
            norm = normalize(w=value,min_w=min_links,max_w=max_links)
            color = heatmap_color(norm=norm)
            net.add_edge(
            src,
            dst,
            smooth=smooth,
            title=f"Tranmission time for: First {data.get('first_time')} | Last {data.get('last_time')} |  count: {format_unit(data.get('weight'))}",        
            # title=f"Order of message: {data.get('type')}| Throughput = {data.get('TP')} mbit/s | count: {weight}",
            color= color,               
            width=3
        )
        elif plot_type == 'udp':
            value = data.get('weight',1)
            norm = normalize(w=value,min_w=min_links,max_w=max_links)
            color = heatmap_color(norm=norm)
            net.add_edge(
            src,
            dst,
            smooth=smooth,
            title=f"Tranmission time for: First {data.get('first_time')} | Last {data.get('last_time')} |  count: {format_unit(data.get('weight'))}",        
            # title=f"Order of message: {data.get('type')}| Throughput = {data.get('TP')} mbit/s | count: {weight}",
            color=color,
            width=3
        )
        elif plot_type == "throughput":
            #dt = max(data.get('last_time') - data.get('first_time'), precision_number)  # burst throughput
            dt = max(time - time_prev, precision_number) # interval throughput
            bits = data.get("bits", 0)
            value = bits / dt

            phyrate_text = f"{phyrate:.2f}" if phyrate is not None else "N/A"
            loss_text = f"{loss_percent:.2f}" if loss_percent is not None else "N/A"

            if phyrate is not None and phyrate > 0:
                load_percent = 100 * value / (phyrate * 1_000_000)
                load_text = f"{load_percent:.3f}"
            else:
                load_text = 'N/A'
            
            #norm = normalize(w=value,min_w=min_links,max_w=max_links)
            norm = normalize(w=load_percent,min_w=0, max_w=100)
            color = heatmap_color(norm=norm)

            print(f'src: {src:<3} | dst: {dst:<3} | phyrate: {str(phyrate):>6} Mbps | total: {format_unit(bits):>8}b | rate: {format_unit(value):>8}bps | dt: {dt:>6.2f} s | link load: {load_text:>6} %') 
            net.add_edge(
                src,
                dst,
                smooth=smooth,
                title=(
                    f"src: {src} -> dst: {dst} | "
                    f"phyrate: {phyrate_text} Mbps | "
                    f"message count: {data.get('count')} | "
                    f"total: {format_unit(bits)}b | "
                    f"rate: {format_unit(value)}bps | "
                    f"link load: {load_text} % "
                ),
                color=color,
                width=3
            )

    # Save and open
    # Save HTML (DO NOT use show)
    net.write_html(output_file)

    color_bar_data_nodes = node_values
    if plot_type == 'tcp':
        color_bar_title = 'TCP packets transmitted on'
        color_bar_data_links = link_values
    elif plot_type == 'udp':
        color_bar_title = 'UDP packets transmitted on'
        color_bar_data_links = link_values
    elif plot_type == 'throughput':
        color_bar_title = 'Throughput [bps] on'
        #color_bar_data_links = link_values # use for throughput on link
        color_bar_data_links = [0, 25, 50, 75, 100] # use for relative link load
    
    # Inject auto-fit script
    with open(output_file, "r+", encoding="utf-8") as f:
        html = f.read()
       
        # Insert injection
        if flag_interval == True:
            injection = build_injection(color_bar_title=color_bar_title,
                                        color_bar_data_links=color_bar_data_links,
                                        color_bar_data_nodes=color_bar_data_nodes,
                                        current_pkt=current_pkt,
                                        total_pkts=total_pkts,
                                        time=time,
                                        total_time=total_time,
                                        interval=flag_interval,
                                        time_prev=time_prev,
                                        packet_prev=packet_prev)
        else:
            injection = build_injection(color_bar_title=color_bar_title,
                                        color_bar_data_links=color_bar_data_links,
                                        color_bar_data_nodes=color_bar_data_nodes,
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
