import argparse
from pathlib import Path
import json
from typing import Tuple, Optional, Dict, Any
import re
import matplotlib.pyplot as plt
from collections import defaultdict
import numpy as np

WIDTH = 150
PLOT_SPACING = 10
WINDOW_START_END_SPACING = 5

def extract_percentile_data(dict_name: str, file_data: dict, percentile: str) -> dict:
    data = file_data.get(dict_name, {})

    def recurse(obj):
        result = {}

        for k, v in obj.items():

            # case 1: dict with percentile inside
            if isinstance(v, dict):

                if percentile in v:
                    result[k] = v[percentile]
                else:
                    nested = recurse(v)
                    if nested:  # only keep non-empty
                        result[k] = nested

            # case 2: scalar value
            else:
                result[k] = v

        return result

    return recurse(data)

def sorting_data_nsperf(file_data: dict,
                        percentile: str,
                        max_window: int = None,
                        interval_step: float = None) -> Tuple[dict, str]:
    # For full NSPERF file, interval not set

    flow_id = file_data.get("flow_id")
    run_id = file_data.get("run_id")
    schema = file_data.get("schema")

    ids = {
    "flow_id": flow_id,
    "run_id": run_id,
    "schema": schema
    }
    results = {}

    # FULL file mode (no intervals)
    if interval_step is None:
        counts = file_data.get("counts")
        rates = file_data.get("rates")
        timing = extract_percentile_data(dict_name = "timing",file_data=file_data,percentile=percentile)

        results = {
        "counts": counts,
        "rates": rates,
        "timing": timing
        }

    else: 
        windows = file_data.get("intervals", {}).get("windows", [])

        for w, window in enumerate(windows[:max_window]):
            end_time = window.get("end_s")
            start_time= window.get("start_s")
            # not hundred percent sure this how i want to do it yet can get nested results alot then
            # still also need to load in the rest then aswell this only deliveryy for send window
            delivery = extract_percentile_data(dict_name = "delivery_for_send_window",file_data=window,percentile=percentile)
            send = extract_percentile_data(dict_name = "send_window",file_data=window,percentile=percentile)
            recieve = extract_percentile_data(dict_name = "receive_window",file_data=window,percentile=percentile)
            results[f"window_{w}"] = {
                                        "start": start_time,
                                        "end": end_time,
                                        "delivery": delivery,
                                        "recieve": recieve,
                                        "send": send
                                    }

    
    return results, ids

def json_path(p: str) -> Path:
    path = Path(p)

    if not path.exists():
        raise argparse.ArgumentTypeError("Path does not exist")

    # Case 1: single file
    if path.is_file():
        if path.suffix.lower() != ".json":
            raise argparse.ArgumentTypeError("File must be a .json")
        return path

    # Case 2: directory
    if path.is_dir():
        json_files = list(path.rglob("*.json")) # looks at dir and nested dirs

        if not json_files:
            raise argparse.ArgumentTypeError(
                "Directory does not contain any .json files"
            )

        return path

    raise argparse.ArgumentTypeError("Invalid path type")

def get_json_files(path: Path) -> list:
    if path.is_file():
        return [path]

    if path.is_dir():
        return list(path.glob("*.json"))  # or rglob

    return []

def nsperf_interval_set(file: Path) -> Tuple[Optional[dict], dict]:
    with file.open() as f:
        data = json.load(f)

    intervals = data.get("intervals",{}).get("interval_seconds")
    windows = data.get("intervals", {}).get("windows", [])
    end_time = None
    if windows:
        last_window = windows[-1]
        end_time = last_window.get("end_s")

    return intervals, data, end_time

def percentile_refactor(percentile: str) -> str:
    allowed = ["50", "95", "99","mean","min","max"]
    if percentile not in allowed:
        print(f"The percentile chosen {percentile} is not within {allowed}")
        exit()
    else:
        if percentile.isdigit():
            return f"p{percentile}_ns"
        else:
            return f"{percentile}_ns"

def find_nsperf_variable(data: dict, target: str) -> Optional[Tuple[str, str]]:
    if target in data:
        return None, data[target]
    #nested check
    for section_name, section_data in data.items():
        if isinstance(section_data, dict) and target in section_data:
            return section_name, section_data[target]
    return None, None

def plot_variables_allowed(data_variable: str,
                           variable_map: list[dict]) -> Optional[Tuple[str, str]]:
    for item in variable_map:
        alias= item.get("aliases",[])
        if data_variable in alias:
            return item.get("name"),item.get("nsperf")
        
    print(f"WARNING: variable not avaliable")
    return None
    
def calc_tuple_nsperf(key_1: float,
                      key_2: float,
                      sign: str) -> Optional[float]:
    if sign == "/":
        return key_1 / key_2
    elif sign == "+":
        return key_1 + key_2
    elif sign == "-":
        return key_1 - key_2
    elif sign == "*":
        return key_1 * key_2
    else:
        print(f"Unknown operator: {sign}")
        return None

def extract_variable_full(data: dict,
                          nsperf_variable: str) -> float:
    
    if nsperf_variable == "IDK":
        print(f"Still need implemenation for this NSPERF variable | {nsperf_variable=}")
        exit()
    # NSPERF IS A STRING
    if isinstance(nsperf_variable, str):
        _, value = find_nsperf_variable(data, nsperf_variable)
        if value is not None:
            return round(value,2)
        else:
            return None
    # NSPERF IS A TUPLE
    if isinstance(nsperf_variable, list) and len(nsperf_variable) == 2:
        _,value_1 = find_nsperf_variable(data=data,target=nsperf_variable[0])
        _,value_2 = find_nsperf_variable(data=data,target=nsperf_variable[1])

        if value_1 is None or value_2 is None:
            print("Missing values in equation")
            return None
        else:
            return value_1,value_2

    if isinstance(nsperf_variable, list) and len(nsperf_variable) == 3:
        _,value_1 = find_nsperf_variable(data=data,target=nsperf_variable[0])
        sign = nsperf_variable[1]
        _,value_2 = find_nsperf_variable(data=data,target=nsperf_variable[2])

        if value_1 is None or value_2 is None or sign is None:
            print("Missing values in equation")
            return None
        value = calc_tuple_nsperf(key_1=value_1,key_2=value_2,sign=sign)
        if value is not None:
            return round(value,2)
        else:
            return None
    if isinstance(nsperf_variable, list) and len(nsperf_variable) == 4:
        _,value_1 = find_nsperf_variable(data=data,target=nsperf_variable[0])
        sign = nsperf_variable[1]
        _,value_2 = find_nsperf_variable(data=data,target=nsperf_variable[2])

        if value_1 is None or value_2 is None or sign is None:
            print("Missing values in equation")
            return None
        value = calc_tuple_nsperf(key_1=value_1,key_2=value_2,sign=sign)
        value = float(nsperf_variable[3]) - value
        if value is not None:
            return round(value,2)
        else:
            return None

def normalize_nsperf(name: str) -> str:
    return name.removeprefix("nsperf_")

def normalize_graph(name: str) -> str:
    return name.removeprefix("graph_")

def pair_nsperf_graph(nsperf_files: list,
                      graph_files: list) -> tuple[list,list]:
    
    pairs = []
    if len(graph_files) == 1:
        for n in nsperf_files:
            pairs.append((n,graph_files))
    if len(graph_files) < 1:
        pass
    pass

def extract_graph(file: Path) -> dict:

    grid_id = []
    nodes_id = []
    with file.open() as f:
        data = json.load(f)
    
    nodes = data['nodes']
    for node in nodes:
        node_id= node['id']
        grid_id.append(node_id)
        if "n" in node_id:
            nodes_id.append(node_id)
    
    links = data['links']
    # if we assume that the link losses are all set the same
    # else need to do something differently
    for link in links:
        link_loss = link['loss_percent']
    return grid_id,nodes_id, f"{link_loss:.2f}"

def nsperf_key(p: Path):
    stem = Path(p).stem  

    client, server, num = stem.split("_")

    client_id = int(re.findall(r"\d+", client)[0])
    server_id = int(re.findall(r"\d+", server)[0])
    run_id = int(num)

    return (client_id, server_id, run_id)

def is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False

def pairing_files(input: Path) -> list:
    experiments = []

    if input.is_dir() and is_number(input.name):
        nsperf_files = get_json_files(input / "nsperf" / "streams")
        graph_file = (input / "graph.json")
        experiments.append({
                "name": input.name,
                "nsperf": nsperf_files,
                "graphs": graph_file
        })
        return experiments
    elif input.is_dir():
        dirs = [d for d in input.iterdir() if d.is_dir() and is_number(d.name)]
        
        for d in dirs:
            nsperf_files = get_json_files(d / "nsperf" / "streams")
            graph_file = (d / "graph.json")

            experiments.append({
                "name": d.name,
                "nsperf": nsperf_files,
                "graphs": graph_file
            })
        return experiments
    else:
        print(f"expected different formatting of directory")
        exit()

######################################################
##### PLOT ###########################
######################################

def plot_graph(x_axis: list,
               y_axis: list,
               axis_labels,
               file_path: Path,
               file_name: str,
               titlename: str,
               fontsize: int = 12,
               picture_size: tuple = (16,9),
               type_graph: int = 1):

    fig, ax = plt.subplots(figsize=picture_size)
    if type_graph == 1:
        ax.plot(x_axis, y_axis, 'o')
    elif type_graph == 2:
        ax.plot(x_axis, y_axis, marker='o')
    else:
        print("Choose type avaible for plotting")
        exit()

    ax.set_title(titlename,fontsize=fontsize*2)
    ax.set_xlabel(axis_labels[0],fontsize=fontsize)
    ax.set_ylabel(axis_labels[1],fontsize=fontsize)
    ax.tick_params(axis='both', labelsize=fontsize)

    ax.grid(True)

    plt.tight_layout()

    output_file = file_path / file_name

    # ensure folder exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    plt.savefig(output_file)
    plt.close(fig)

def plot_boxplot(boxplot_data: list,
                 axis_labels,
                 file_path: Path,
                 file_name: str,
                 titlename: str,
                 fontsize: int = 12,
                 picture_size: tuple = (16,9)):
    if axis_labels[0] != "link_loss [%]":
        sorted_items = sorted(boxplot_data.items(),key=lambda item: float(item[0].split("_")[0]))
        labels = [k for k, _ in sorted_items]
        values = [v for _, v in sorted_items]
    else:
        labels = box_data.keys()
        values = box_data.values()

    fig, ax = plt.subplots(figsize=picture_size)

    ax.boxplot(values, tick_labels=labels)
    ax.set_title(titlename,fontsize=fontsize*2)
    ax.set_xlabel(axis_labels[0],fontsize=fontsize)
    ax.set_ylabel(axis_labels[1],fontsize=fontsize)
    ax.grid(True)

    plt.tight_layout()

    output_file = file_path / file_name

    # ensure folder exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    plt.savefig(output_file)
    plt.close(fig)

def axis_units(axis_names: list) -> tuple[list,list]:

    procent = ["link_loss","total_loss"]
    unitless = ["num_streams","hops","mesh_size"]
    unit_mb = ["throughput","request_throughput"]
    unit_time = ["latency","jitter"]

    units = []
    unit_scales = []

    for name in axis_names:
        if name in unitless:
            unit = "[-]"
            unitscale = 1
        elif name in unit_mb:
            unit = "[Mb]"
            unitscale = 1e-6
        elif name in unit_time:
            unit = "[ms]"
            unitscale = 1e-6 #maybe change ot milli if to high numbers
        elif name in procent:
            unit = "[%]"
            if name == procent[0]:
                unitscale = 1
            elif name == procent[1]:
                unitscale = 100
        else:
            unit = "[-]"
            unitscale = 1
            print(f"Could not find an Unit for this variable | Unit = {unit} | unitscale = {unitscale}")
        units.append(unit)
        unit_scales.append(unitscale)

    return units, unit_scales

def bin_splitting(values: list, n_bins: int = 10) -> list:
    if len(values) < n_bins:
        n_bins = len(values)
    values = np.array(values)
    sorted_vals = np.sort(values)
    # Split by index (guarantees equal counts)
    splits = np.array_split(sorted_vals, n_bins)
    
    return [s.tolist() for s in splits]

def bin_naming(bins: list[list] ) -> list:
    bin_names = []
    for bin in bins:
        min_val = min(bin)
        max_val = max(bin)
        bin_names.append(f"{min_val:.5f}_{max_val:.5f}")
    return bin_names

def convert_ns_to_s_list_numstreams(starts_ns: list[int],
                    stops_ns: list[int]) -> tuple[int, list[float], list[float]]:
    
    if not starts_ns or not stops_ns:
        return None, [], []

    # 🔥 reference = global minimum start
    reference = min(starts_ns)

    start_s_list = []
    stop_s_list = []

    for start, stop in zip(starts_ns, stops_ns):
        start_reference = start - reference
        stop_reference = stop - reference

        time_interval_ns = stop_reference - start_reference

        time_interval_s = round(time_interval_ns * 1e-9, 0)
        start_s = round(start_reference * 1e-9, 0)

        stop_s = start_s + time_interval_s

        start_s_list.append(start_s)
        stop_s_list.append(stop_s)

    return start_s_list, stop_s_list

def add_active_stream_count(streams: list[dict]) -> list[dict]:
    for i, s in enumerate(streams):
        count = 1

        for o in streams:

            # ❌ skip self
            if (
                s["client"] == o["client"]
                and s["server"] == o["server"]
                and s["num"] == o["num"]
            ):
                continue

            # overlap condition
            if o["start_s"] <= s["stop_s"] and o["stop_s"] > s["start_s"]:
                count += 1

        s["active_streams"] = count

    return streams
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tool for analysing the NSPERF/IPERF streams from the graphs')
    parser.add_argument('-i','--input',type=json_path,required=True,help='The desired directory or file which is be performed analysis on (Json Format IPERF/NSPERF)')
    parser.add_argument('-o','--output',type=Path,help='The desired directory for saving PLOTS')
    # parser.add_argument('-g','--graph',type=json_path,help='The directory or file which is the entail nodes and links desription (Json Format)')
    parser.add_argument('-p','--percentile',type=str,required=True,help='What data is of interest for the analysis 0 = mean 50 %,95 % 99 % percentile (Json Format IPERF/NSPERF)')
    parser.add_argument('-x','--x_axis',type=str,required=True,help='Variable for X axis')
    parser.add_argument('-y','--y_axis',type=str,required=True,help='Variable for Y axis')
    parser.add_argument('-c','--client',type=str,help='If Desire only observe one specific Stream Set Client and Server')
    parser.add_argument('-s','--server',type=str,help='If Desire only observe one specific Stream Set Client and Server')
    parser.add_argument('-f','--filter',action="store_true",help='Filter streams at time stamp: 0')
    args = parser.parse_args()

    input_path = args.input
    output_path = args.output or Path("./plots")
    req_client = args.client
    req_server = args.server
    if req_client is not None:
        req_client = req_client.strip().lower()
        req_client = req_client.split(",")
    if req_server is not None:
        req_server = req_server.strip().lower()
        req_server = req_server.split(",")
    filter_0 = args.filter
    experiments = pairing_files(input=input_path)
    percentile = percentile_refactor(args.percentile)

    experiments = sorted(experiments, key=lambda e: float(e["name"]))

    variable_map  = []
    variable_map .append({"name": "link_loss", "aliases": ["link_loss", "link loss"], "nsperf": "link_loss"})                     #Need to change to just what's in graph
    variable_map .append({"name": "total_loss", "aliases": ["total_loss", "total loss"], "nsperf": ["received_bits", "/", "generated_bits","1"]})
    variable_map .append({"name": "throughput", "aliases": ["throughput", "tp"], "nsperf": "received_bps"})
    variable_map .append({"name": "latency", "aliases": ["latency", "lat"], "nsperf": "host_local_latency_estimate_ns"})    #IDK if this is the right latency
    variable_map .append({"name": "jitter", "aliases": ["jitter", "jit"], "nsperf": "host_local_latency_jitter_abs_ns"})    #IDK if this is the right jitter
    variable_map .append({"name": "num_streams", "aliases": ["num_streams", "num streams"], "nsperf": ["send_start_ns", "send_end_ns"]})
    variable_map .append({"name": "request_throughput", "aliases": ["request_throughput", "request throughput", "req_tp", "req tp"], "nsperf": "generated_bps"}) # NOT Sure if the right one
    variable_map .append({"name": "hops", "aliases": ["hops"], "nsperf": "IDK"})                                            # STILL NOT SURE IF POSSIBLE
    variable_map .append({"name": "mesh_size", "aliases": ["mesh_size", "mesh size"], "nsperf": "mesh_size"})                           #ALSO TAKE FROM GRAPH

    # sanity check if that varaible for axis are avaliable
    axis_names = []
    axis_nsperfs = []
    for axis in [args.x_axis, args.y_axis]:
        axis = axis.strip().lower()
        results = plot_variables_allowed(data_variable=axis,variable_map=variable_map)
        if results is None:
            exit()

        name, nsperf = results
        axis_names.append(name)
        axis_nsperfs.append(nsperf)
        
    print(f"{percentile=}")

    path_width = max(len(str(f))for exp in experiments for f in exp["nsperf"]) + 2


    # title = " Files used for analysis "
    # print(title.center(WIDTH, "-"))

    # for exp in experiments:
    #     exp["nsperf"] = sorted(exp["nsperf"], key=nsperf_key)
    #     nsperf_files = exp["nsperf"]
    #     graph_file = exp["graphs"]

    #     # title = f" Link loss: {exp['name']} "
    #     # print()
    #     # print(title.center(WIDTH, "_"))

    #     for f in nsperf_files:
    #         interval_step, json_file_data, end_time = nsperf_interval_set(f)

    #         end_str = "" if end_time is None else str(end_time)

    #         # print(
    #         #     f"{str(f).ljust(path_width)} | "
    #         #     f"interval: {str(interval_step).ljust(PLOT_SPACING)} | "
    #         #     f"End time {end_str.ljust(PLOT_SPACING)} | "
    #         #     f"Graph: {str(graph_file).ljust(path_width)}"
    #         # )

    graph_reference_path = experiments[0]["graphs"]

    with open(graph_reference_path) as f:
        graph_reference = json.load(f)
        
    graph_same = True

    print("-" * WIDTH)
    plot_data = defaultdict(list)
    for i, exp in enumerate(experiments):
        exp["nsperf"] = sorted(exp["nsperf"], key=nsperf_key)
        nsperf_files = exp["nsperf"]
        graph_file = exp["graphs"]
        
        # check if they are the same graphs used
        with open(graph_file) as f:
            graph_data = json.load(f)
        if graph_reference != graph_data:
            graph_same = False

        title = f" Files in directory \'{exp["name"]}\' | Axis | X: {axis_names[0]} | Y: {axis_names[1]} "
        print()
        print(title.center(WIDTH, "_"))
        prev_client = None
        first_client = True
        for f in nsperf_files:
            # Just for structure
            stem = Path(f).stem  
            client, server, num = stem.split("_")
            interval_step, json_file_data, end_time = nsperf_interval_set(f)
            data,ids = sorting_data_nsperf(file_data=json_file_data,interval_step=interval_step,percentile=percentile,max_window=None)
            """         This just for intermediate for seing what is saved    """
            # file_text = f" Extracted data from file \'{f}\' with ID {ids.get("flow_id")} "
            # print(file_text.center(WIDTH, "-"))
            # for w_key, w_data in data.items():
            #     print(w_key)      # e.g. "window_0"
            #     print(w_data)     # the inner dict
            grid,nodes, graph_link_loss = extract_graph(graph_file)
            full_grid = grid.copy()
            for item in grid:
                if "a" in item:
                    full_grid.append(item.replace("a", "d"))
            if req_client is None:
                req_client = full_grid
            if req_server is None:
                req_server = full_grid
            link_loss = float(exp["name"]) if is_number(exp["name"]) else graph_link_loss
            mesh_size = len(nodes)
            if interval_step is None:
                axis_values = []
                data["mesh_size"] = mesh_size
                data["link_loss"] = link_loss
                for axis_nsperf in axis_nsperfs:
                        axis_value = extract_variable_full(data=data,nsperf_variable=axis_nsperf)
                        axis_values.append(axis_value)
            
                plot_data[link_loss].append({
                                            "client": client,
                                            "server": server,
                                            "num": num,
                                            "x_axis": axis_values[0],
                                            "y_axis": axis_values[1]
                                            })
                if client in req_client and server in req_server:
                    if client != prev_client and first_client is False:
                        title = f" Client: {client} "
                        print(title.center(WIDTH,"="))
                    print(f"File {str(f).ljust(path_width)} | X value = {str(axis_values[0]).ljust(PLOT_SPACING)} | Y value = {str(axis_values[1]).ljust(PLOT_SPACING)}")
                    prev_client = client
                    first_client = False
            else:
                for w_key, w_data in data.items():
                    axis_values = []
                    w_data["link_loss"] = link_loss
                    w_data["mesh_size"] = mesh_size
                    w_idx = w_key.split("_")[1]
                    start = w_data.get("start")
                    end = w_data.get("end")
                    window_info = f"Start {start} End {end} s"
                    for axis_nsperf in axis_nsperfs:
                        axis_value = extract_variable_full(data=w_data,nsperf_variable=axis_nsperf)
                        axis_values.append(axis_value)

                    print(f"Window {str(w_idx).ljust(PLOT_SPACING)} | Start: {str(start).ljust(WINDOW_START_END_SPACING)} End {str(end).ljust(WINDOW_START_END_SPACING)} [s] | X value = {str(axis_values[0]).ljust(PLOT_SPACING)} | Y value = {str(axis_values[1]).ljust(PLOT_SPACING)}")
    
    axis_values = []
    client_server = []
    files_not_used = []
    box_data = defaultdict(list)

    num_stream_axis = None
    if axis_names[0] == "num_streams":
        num_stream_axis = "x_axis"
    if axis_names[1] == "num_streams":
        num_stream_axis = "y_axis"

    if num_stream_axis is not None:
        for loss, runs in plot_data.items():
            starts_ns = []
            stops_ns = []
            streams = []
            for entry in runs:
                if entry[num_stream_axis] is not None:
                    start_ns,stop_ns= entry[num_stream_axis]
                    starts_ns.append(start_ns)
                    stops_ns.append(stop_ns)
                    streams.append({
                        "entry": entry,
                        "client": entry["client"],
                        "server": entry["server"],
                        "num": entry["num"],
                        # Only temporarily
                        "start_ns": start_ns,
                        "stop_ns": stop_ns
                    })
            starts_s, stops_s = convert_ns_to_s_list_numstreams(starts_ns, stops_ns)
            # FOR DEBUG
            for i, s in enumerate(streams):
                s.pop("start_ns")
                s.pop("stop_ns")
                s["start_s"] = starts_s[i]
                s["stop_s"] = stops_s[i]
            streams = add_active_stream_count(streams)
            """ DEBUGGING """
            # sorted_stream = sorted(streams, key=lambda s: s["start_s"])
            # for s in sorted_stream:
            #     print(f"link_loss {loss}: {s['client']} -> {s['server']} | start: {s['start_s']}")
            for s in streams:
                entry = s["entry"]
                entry[num_stream_axis] = s["active_streams"]

    for loss, runs in plot_data.items():
        for entry in runs:
            # IF set to one specific stream only save data for this stream
            # else use every stream
            if entry['client'] in req_client and entry['server'] in req_server:
                if entry["x_axis"] is not None and entry["y_axis"] is not None:     # if they are none we dont want them
                    client_server.append(f"{entry['client']}-{entry['server']}")
                    axis_values.append({"x_axis": entry["x_axis"],
                                        "y_axis": entry["y_axis"]
                                        })
                else:
                    files_not_used.append(f"{entry['client']}_{entry['server']}_{entry["num"]}")
    title = " Files NOT used | Because entail values of None"
    print(title.center(WIDTH, "_"))
    # finding file which is not use
    for file_id in files_not_used:
        for path in nsperf_files:
            if file_id in str(path):
                print(path)

    if full_grid == req_client and full_grid == req_server:
        stream = "All"
        stream_file_name = "all"
    elif full_grid == req_server:
        stream = f"Client: {req_client}"
        stream_file_name = f"c_{req_client}"
    elif full_grid == req_client:
        stream = f"Server: {req_server}"
        stream_file_name = f"s_{req_server}"
    else:
        stream = f"Client: {req_client} | Server: {req_server}"
        stream_file_name = f"c_{req_client}_s_{req_server}"
    title = f" Creating Plots | {stream} "
    plot_file_name = f"data_{percentile}_axis_{axis_names[0]}_{axis_names[1]}_{stream_file_name}"
    print(title.center(WIDTH, "_"))

    percentile_matrixs = []
    for item in variable_map:
        nsperf = item.get("nsperf")
        if "host_local" in nsperf:
            name_item = item.get("name")
            percentile_matrixs.append(name_item)
    plot_title = f"{stream} | Mesh Size: {mesh_size}"
    for name in axis_names:
        if name in percentile_matrixs:
            percentile_str= percentile.split("_")[0]
            plot_title = f"Stream {stream} | Mesh Size: {mesh_size} | Percentile: '{percentile_str}'"

    scaled_values = []
    units, unit_scales = axis_units(axis_names=axis_names)

    axis_keys = ["x_axis", "y_axis"]

    scaled_values = []

    for key, scale in zip(axis_keys, unit_scales):
        values = np.array([entry[key] for entry in axis_values])
        scaled_values.append(values * scale)

    scaled_x_values, scaled_y_values = scaled_values


    axis_labels = []
    for i, axis in enumerate(axis_names):
        axis_labels.append(f"{axis} {units[i]}")
    plot_graph(
        x_axis=scaled_x_values,
        y_axis=scaled_y_values,
        axis_labels = axis_labels,
        fontsize=12,
        picture_size=(16, 9),
        file_path=output_path,
        titlename = f" DATA points for {plot_title}",
        type_graph = 1,
        file_name=f"{plot_file_name}.png"
    )
    if axis_names[0] != "link_loss":
        bin_values = bin_splitting(scaled_x_values)
        bin_names = bin_naming(bin_values)

        for x, y in zip(scaled_x_values, scaled_y_values):
            for i, bin_list in enumerate(bin_values):
                if x in bin_list:
                    box_data[bin_names[i]].append(y)
                    break

    else:
        # no bins, just group by value
        for x, y in zip(scaled_x_values, scaled_y_values):
            box_data[x].append(y)

    plot_boxplot(
        boxplot_data = box_data,
        axis_labels = axis_labels,
        titlename = f" BOXPLOT FOR {plot_title}",
        fontsize=12,
        picture_size=(16, 9),
        file_path=output_path,
        file_name=f"{plot_file_name}_boxplot.png"
    )

    percentile_not = ["total_loss","link_loss","throughput","request_throughput","num_streams","mesh_size"]

    for name in percentile_not:
        if name in axis_names:
            print(f"\nPercentile Setting does not matter for parameters '{name}'")
        if graph_same is False:
            print("\nWARNING: Graphs used don't have same structure")