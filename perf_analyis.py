import argparse
from pathlib import Path
import json
from typing import Tuple, Optional, Dict, Any
import re
import matplotlib.pyplot as plt
from collections import defaultdict
import numpy as np
import seaborn as sns
import pandas as pd
import hashlib

WIDTH = 150
PLOT_SPACING = 10
WINDOW_START_END_SPACING = 5
FONT_SIZE = 18
PALLETTE = ["#4C72B0", "#DC1D33","#16A944","#D9D31C"]

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

        if value_1 == 0:
            return None
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
    parts = stem.split("_")

    client = parts[0]
    server = parts[1]
    num = parts[2]

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

def find_experiment_root(path: Path) -> Path:
    """
    Stops at iter_X OR numeric/magnitude folder
    but does NOT go above iter level
    """

    for parent in path.parents:

        name = parent.name.lower()

        # stop at iter folders (IMPORTANT)
        if name.startswith("iter_"):
            return parent

        # stop at experiment numeric root
        if is_number(name):
            return parent

        # stop at magnitude root
        if name.endswith(("k", "m")):
            return parent

    return path.parent

def pairing_files(input: Path) -> list:
    experiments = []

    for stream_dir in input.rglob("nsperf/streams"):

        experiment_root = stream_dir.parents[2]  # <- THIS IS iter_X folder
        experiment_naming = stream_dir.parents[1]  # <- THIS IS iter_X folder

        nsperf_files = get_json_files(stream_dir)
        graph_file = next(experiment_root.rglob("graph.json"), None)

        experiments.append({
            "name": str(experiment_naming),   
            "nsperf": nsperf_files,
            "graphs": graph_file
        })

    return experiments

def experiment_sort_key(name: str):
    parts = Path(name).parts

    bitrate = 0
    loss = 0
    it = 0

    for p in parts:
        p_low = p.lower()

        if p_low.startswith("iter_"):
            it = int(p_low.split("_")[1])

        elif p_low.endswith("k"):
            bitrate = float(p_low[:-1]) * 1_000

        elif p_low.endswith("m"):
            bitrate = float(p_low[:-1]) * 1_000_000

        elif re.fullmatch(r"\d+", p_low):
            loss = int(p_low)

    return (bitrate, loss, it)

def experiment_name(name: str):
    parts = Path(name).parts

    bitrate = None
    loss = None
    it = None

    for p in parts:
        p_low = p.lower()

        if p_low.startswith("iter_"):
            it = p_low

        elif p_low.endswith("k") or p_low.endswith("m"):
            bitrate = p_low

        elif re.fullmatch(r"\d+(\.\d+)?", p_low):
            loss = p_low

    return "_".join([x for x in [bitrate, loss, it] if x])

######################################################
##### PLOT ###########################
######################################

def plot_graph(x_axis: list,
               y_axis: list,
               axis_labels,
               file_path: Path,
               file_name: str,
               titlename: str,
               sub_title: str,
               fontsize: int = 12,
               picture_size: tuple = (16,9),
               hue = None):

    fig, ax = plt.subplots(figsize=picture_size)

    if hue is not None:
        sns.scatterplot(
            x=x_axis,
            y=y_axis,
            hue=hue,
            ax=ax,
            palette=PALLETTE,
            alpha=0.6
        )
    else:
        sns.scatterplot(
            x=x_axis,
            y=y_axis,
            ax=ax,
            color=PALLETTE[0]
        )

    fig.suptitle(titlename, fontsize=fontsize*2, y=0.98)
    ax.set_title(sub_title, fontsize=fontsize*1.5, pad=10)
    ax.set_xlabel(axis_labels[0],fontsize=fontsize)
    ax.set_ylabel(axis_labels[1],fontsize=fontsize)
    ax.tick_params(axis='both', labelsize=fontsize*0.8)

    ax.grid(True)

    plt.tight_layout()

    output_file = file_path / file_name

    output_file.parent.mkdir(parents=True, exist_ok=True)

    plt.savefig(output_file)
    plt.close(fig)

def plot_boxplot(
    df: pd.DataFrame,
    axis_labels,
    file_path: Path,
    file_name: str,
    titlename: str,
    sub_title: str,
    fontsize: int = 12,
    picture_size: tuple = (16,9),
    ):

    fig, ax = plt.subplots(figsize=picture_size)

    if "hue" in df.columns and df["hue"].notna().any():

        sns.boxplot(
            data=df,
            x="x",
            y="y",
            hue="hue",
            ax=ax,
            palette=PALLETTE
        )

    else:

        sns.boxplot(
            data=df,
            x="x",
            y="y",
            ax=ax,
            color=PALLETTE[0]
        )
    fig.suptitle(titlename, fontsize=fontsize*2, y=0.98)
    ax.set_title(sub_title, fontsize=fontsize*1.5, pad=10)
    ax.set_xlabel(axis_labels[0],fontsize=fontsize)
    ax.set_ylabel(axis_labels[1],fontsize=fontsize)
    ax.tick_params(axis='both', labelsize=fontsize*0.8)
    ax.grid(True)

    plt.tight_layout()

    output_file = file_path / file_name

    # ensure folder exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    plt.savefig(output_file)
    plt.close(fig)

def plot_violin(
    violin_df: pd.DataFrame,
    axis_labels,
    file_path: Path,
    file_name: str,
    titlename: str,
    sub_title: str,
    fontsize: int = 12,
    picture_size: tuple = (16,9),
):

    fig, ax = plt.subplots(figsize=picture_size)

    has_hue = (
        "hue" in violin_df.columns
        and violin_df["hue"].notna().any()
    )

    if has_hue:

        split = violin_df["hue"].nunique() >= 2

        sns.violinplot(
            data=violin_df,
            x="x",
            y="y",
            hue="hue",
            split=split,
            inner="quart",      # THIS fixes ugly boxplot
            cut=0,              # prevents long spikes
            linewidth=2.5,
            bw_method=.2,              # smoother shape
            density_norm="width",      # makes widths consistent
            palette=PALLETTE,
            ax=ax,
        )
        for pc in ax.collections:
            pc.set_alpha(0.6)
    else:

        sns.violinplot(
            data=violin_df,
            x="x",
            y="y",
            inner="quart",
            cut=0,
            linewidth=2.5,
            bw_method=.2,
            density_norm="width",
            color=PALLETTE[0],
            ax=ax,
        )

    fig.suptitle(titlename, fontsize=fontsize*2, y=0.98)

    ax.set_title(
        sub_title,
        fontsize=fontsize*1.5,
        pad=10
    )

    ax.set_xlabel(axis_labels[0], fontsize=fontsize)
    ax.set_ylabel(axis_labels[1], fontsize=fontsize)
    ax.tick_params(axis='both', labelsize=fontsize*0.8)

    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    output_file = file_path / file_name
    output_file.parent.mkdir(parents=True, exist_ok=True)

    plt.savefig(output_file, dpi=300)
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
            # skip exact same object only
            if s is o:
                continue

            # overlap condition
            if o["start_s"] <= s["stop_s"] and o["stop_s"] > s["start_s"]:
                count += 1

        s["active_streams"] = count

    return streams

def plot_naming(axis_names: list[str],
                percentile_matrixs: list[str],
                percentile: str,
                file_name: str,
                stream_file_name: str) -> str:
    percentile_str = ""

    for name in axis_names:
        if name in percentile_matrixs:
            percentile_str += f"percentile_{percentile}_"
    axis_part = "_".join(axis_names)
    plot_file_name = f"{file_name}_{percentile_str}axis_{axis_part}_{stream_file_name}"
    return plot_file_name

def plot_titling(
    stream: str,
    axis_names: list[str],
    percentile_matrixs: list[str],
    percentile: str,
    constants: list
) -> tuple[str,str]:
    parts = stream.split("|")[1:]
    title_parts = ["With Streams Used Being"]
    for part in parts:
        title_parts.append(part)
    under_title_parts = []

    # Check manually if any axis is in percentile_matrixs
    has_percentile = False
    for name in axis_names:
        if name in percentile_matrixs:
            has_percentile = True
            break

    if has_percentile:
        percentile_str = percentile.split("_")[0]
        title_parts.append(f"Percentile: {percentile_str}")

    # Add global constant variables 
    if constants:                           #ensure not empty
        under_title_parts.append("Fixed Parameters")
        for constant in constants:
            under_title_parts.append(f"{constant}")

    title = " | ".join(title_parts)
    under_title = " | ".join(under_title_parts)
    return title,under_title

def resolve_stream(req_client, req_server, full_grid, grid_type):
    client_full = set(req_client) == set(full_grid)
    server_full = set(req_server) == set(full_grid)

    base = f"grid_{grid_type}"

    if client_full and server_full:
        return f"{base} | All", f"g{grid_type}_all"

    if client_full:
        return f"{base} | Server: {req_server}", f"g{grid_type}_s_{req_server}"

    if server_full:
        return f"{base} | Client: {req_client}", f"g{grid_type}_c_{req_client}"

    return (
        f"{base} | C: {req_client} | S: {req_server}",
        f"g{grid_type}_c_{req_client}_s_{req_server}"
    )

def graph_fingerprint(graph_data: dict) -> str:
    normalized = json.dumps(graph_data, sort_keys=True).encode()
    return hashlib.md5(normalized).hexdigest()

def parse_value(v):
    v = str(v).strip().lower()

    multiplier = 1

    if v.endswith("k"):
        multiplier = 1_000
        v = v[:-1]
    elif v.endswith("m"):
        multiplier = 1_000_000
        v = v[:-1]

    try:
        return float(v) * multiplier
    except:
        return v

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
    parser.add_argument('-0','--zero_filter',action="store_true",help='Filter streams at time stamp: 0')
    parser.add_argument('--hue',type=str,help='Optional grouping variable for seaborn hue')
    parser.add_argument('-v','--verbose',action = "store_true",help='set verbosity')
    parser.add_argument("-f","--filter",action="append",help="Filter format: key=value (can be repeated)")

    args = parser.parse_args()
    filters = args.filter or []
    verbosity = args.verbose
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


    experiments = sorted(experiments, key=lambda e: experiment_sort_key(e["name"]))

    variable_map  = []
    variable_map .append({"name": "link_loss", "aliases": ["link_loss", "link loss"], "nsperf": "link_loss"})                     #Need to change to just what's in graph
    variable_map .append({"name": "total_loss", "aliases": ["total_loss", "total loss"], "nsperf": ["received_bits", "/", "generated_bits","1"]})
    variable_map .append({"name": "throughput", "aliases": ["throughput", "tp"], "nsperf": "received_bps"})
    variable_map .append({"name": "latency", "aliases": ["latency", "lat"], "nsperf": "host_local_latency_estimate_ns"})    #IDK if this is the right latency
    variable_map .append({"name": "jitter", "aliases": ["jitter", "jit"], "nsperf": "host_local_latency_jitter_abs_ns"})    #IDK if this is the right jitter
    variable_map .append({"name": "num_streams", "aliases": ["num_streams", "num streams"], "nsperf": ["send_start_ns", "send_end_ns"]})
    variable_map .append({"name": "request_throughput", "aliases": ["request_throughput", "request throughput", "req_tp", "req tp"], "nsperf": "generated_bps"}) # NOT Sure if the right one
    # variable_map .append({"name": "hops", "aliases": ["hops"], "nsperf": "IDK"})                                            # STILL NOT SURE IF POSSIBLE
    variable_map .append({"name": "mesh_size", "aliases": ["mesh_size", "mesh size"], "nsperf": "mesh_size"})                           #ALSO TAKE FROM GRAPH

    # sanity check if that varaible for axis are avaliable
    axis_names = []
    axis_nsperfs = []

    requested_axes = [args.x_axis, args.y_axis]

    if args.hue:
        requested_axes.append(args.hue)

    for axis in requested_axes:
            axis = axis.strip().lower()
            results = plot_variables_allowed(data_variable=axis,variable_map=variable_map)
            if results is None:
                exit()

            name, nsperf = results
            axis_names.append(name)
            axis_nsperfs.append(nsperf)
    
    all_nsperfs = {}

    for variable in variable_map:
        name = variable["name"]
        nsperf = variable["nsperf"]

        plot_variables_allowed(data_variable=name,variable_map=variable_map)
        all_nsperfs[name] = nsperf
    
    valid_keys = set()

    for v in variable_map:
        valid_keys.add(v["name"])
    # for changing name 
    for exp in experiments:
        exp["name"] = experiment_name(exp["name"])

    print(f"{percentile=}")

    path_width = max(len(f.name)for exp in experiments for f in exp["nsperf"]) + 2

    graph_reference_path = experiments[0]["graphs"]

    with open(graph_reference_path) as f:
        graph_reference = json.load(f)
        
    grid_type_map = {}
    grid_type = 0

    print("-" * WIDTH)
    plot_data = defaultdict(lambda: defaultdict(list))

    grouped_by_grid = defaultdict(list)

    # -------------------------
    # 1. GROUP PHASE (what you already did)
    # -------------------------
    for exp in experiments:
        graph_file = exp["graphs"]

        with open(graph_file) as f:
            graph_data = json.load(f)

        graph_key = graph_fingerprint(graph_data)
        grid_type = grid_type_map.setdefault(graph_key, len(grid_type_map))

        exp["grid_type"] = grid_type
        grouped_by_grid[grid_type].append(exp)

    # -------------------------
    # 2. PROCESS PHASE (THIS IS WHAT YOU'RE MISSING)
    # -------------------------

    req_client_grids = {}
    req_server_grids = {}
    full_grids = {}
    for grid_type, experiments_in_grid in grouped_by_grid.items():

        # -------------------------
        # GRID LEVEL (graph loaded once per grid)
        # -------------------------
        first_graph = experiments_in_grid[0]["graphs"]

        full_grid, nodes, graph_link_loss = extract_graph(first_graph)
        full_grid_with_devices = []

        for node in full_grid:
            if node.startswith("a"):
                full_grid_with_devices.append("d" + node[1:])
            else:
                full_grid_with_devices.append(node)
        mesh_size = len(nodes)

        # optional fallback stream selection
        req_client_local = req_client if req_client is not None else full_grid_with_devices
        req_server_local = req_server if req_server is not None else full_grid_with_devices
        req_client_grids[grid_type] = req_client_local
        req_server_grids[grid_type] = req_server_local
        full_grids[grid_type] = full_grid_with_devices
        for exp in experiments_in_grid:

            # -------------------------
            # EXPERIMENT LEVEL
            # -------------------------
            stream, stream_file_name = resolve_stream(
                req_client_local,
                req_server_local,
                full_grid,
                grid_type
            )

            # extract bitrate / loss from experiment name (your logic)
            link_loss = graph_link_loss
            for split in exp["name"].split("_"):
                if is_number(split):
                    link_loss = float(split)
                    break
            if verbosity is True:
                print()
                print(f"Files in directory '{exp['name']}'".center(WIDTH, "_"))

            # -------------------------
            # FILE LEVEL (THIS IS WHERE YOUR REAL WORK HAPPENS)
            # -------------------------
            prev_client = None
            first_client = True
            for f in exp["nsperf"]:
                # Just for structure
                stem = Path(f).stem  
                parts = stem.split("_")

                client = parts[0]
                server = parts[1]
                num = parts[2]

                interval_step, json_file_data, end_time = nsperf_interval_set(f)
                data,ids = sorting_data_nsperf(file_data=json_file_data,interval_step=interval_step,percentile=percentile,max_window=None)
                """         This just for intermediate for seing what is saved    """
                # file_text = f" Extracted data from file \'{f}\' with ID {ids.get("flow_id")} "
                # print(file_text.center(WIDTH, "-"))
                # for w_key, w_data in data.items():
                #     print(w_key)      # e.g. "window_0"
                #     print(w_data)     # the inner dict
                if interval_step is None:
                    axis_values = []
                    all_nsperf_values = {}
                    data["mesh_size"] = mesh_size
                    data["link_loss"] = link_loss
                    for variable in variable_map:
                            nsperf = variable["nsperf"]
                            name = variable["name"]
                            nsperf_value = extract_variable_full(data=data,nsperf_variable=nsperf)
                            #overwritting of requested throughput on streams
                            if name == "request_throughput":
                                for split in exp["name"].split("_"):
                                    if split.lower().endswith("k"):
                                        nsperf_value = float(split[:-1]) * 1_000
                                        break
                                    elif split.lower().endswith("m"):
                                        nsperf_value = float(split[:-1]) * 1_000_000
                                        break
                            all_nsperf_values[name] = nsperf_value
                            if nsperf in axis_nsperfs:
                                axis_values.append(nsperf_value)
                    plot_data[grid_type][exp["name"]].append({
                                                "client": client,
                                                "server": server,
                                                "num": num,
                                                **all_nsperf_values,
                                                "grid_type": grid_type
                                                })
                    if client in req_client_local and server in req_server_local and verbosity is True:
                        if client != prev_client and first_client is False:
                            title = f" Client: {client} "
                            print(title.center(WIDTH,"="))
                        print(f"File {f.name.ljust(path_width)} | Name = {str(exp["name"]).ljust(PLOT_SPACING)} | X value = {str(axis_values[0]).ljust(PLOT_SPACING)} | Y value = {str(axis_values[1]).ljust(PLOT_SPACING)}")
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

    # first run til to extract the amount of num_streams there is during a stream
    for grid_type, experiments in plot_data.items():
        for exp_name, runs in experiments.items():

            starts_ns = []
            stops_ns = []
            streams = []

            for entry in runs:
                if entry["num_streams"] is not None:

                    start_ns, stop_ns = entry["num_streams"]
                    starts_ns.append(start_ns)
                    stops_ns.append(stop_ns)

                    streams.append({
                        "entry": entry,
                        "client": entry["client"],
                        "server": entry["server"],
                        "num": entry["num"],

                        # temporary
                        "start_ns": start_ns,
                        "stop_ns": stop_ns
                    })

            starts_s, stops_s = convert_ns_to_s_list_numstreams(
                starts_ns,
                stops_ns
            )

            for i, s in enumerate(streams):
                s.pop("start_ns")
                s.pop("stop_ns")
                s["start_s"] = starts_s[i]
                s["stop_s"] = stops_s[i]

            streams = add_active_stream_count(streams)

            for s in streams:
                entry = s["entry"]
                entry["num_streams"] = s["active_streams"]
                # if "iter_03" in loss and int(s['num']) == 210:
                # if s["active_streams"] in (7,9,14):
                    # print(f"link_loss {loss}: {s['client']} -> {s['server']} Num: {s['num']} | start: {s['start_s']} stop: {s['stop_s']} | streams: {s['active_streams']}")

    filtered_plot_data = defaultdict(lambda: defaultdict(list))

    filter_map = {}

    for f in filters:
        key, value = f.split("=")
        filter_map[key] = parse_value(value)

    normalized_filter_map = {}

    for k, v in filter_map.items():
        results = plot_variables_allowed(data_variable=k, variable_map=variable_map)
        if results is None:
            exit()

        name, _ = results   # convert alias → real key
        normalized_filter_map[name] = v

    filter_map = normalized_filter_map

    count = 0
    for grid_type, experiments in plot_data.items():
        for exp_name, entries in experiments.items():

            for entry in entries:
                skip = False

                for k, v in filter_map.items():
                    if k not in entry or entry[k] != v:
                        skip = True
                        break

                if skip:
                    continue
                count += 1
                filtered_plot_data[grid_type][exp_name].append(entry)
    print(f"Found {count} Entries which fit the filtering")
    # To check what constants are constant in each folder
    constant_vars = {}  # exp_name -> dict of constant variable -> value
    for grid_type, experiments in filtered_plot_data.items():
        for exp_name, entries in experiments.items():

            if not entries:
                continue

            constants = {}
            keys = entries[0].keys()

            for key in keys:
                if key in ("client", "server", "num", "grid_type"):
                    continue
                first_value = entries[0][key]
                all_same = True

                for entry in entries[1:]:
                    if entry.get(key) != first_value:
                        all_same = False
                        break

                if all_same:
                    constants[key] = first_value  # key + value

            constant_vars[(grid_type, exp_name)] = constants

    #check if all folders have some constant being equal to each other
    common_keys = None

    for consts in constant_vars.values():
        keys = set(consts.keys())
        if common_keys is None:
            common_keys = keys.copy()
        else:
            common_keys &= keys

    global_constants = {}

    for key in common_keys:
        first_exp = next(iter(constant_vars))
        first_value = constant_vars[first_exp][key]

        same_everywhere = True
        for consts in constant_vars.values():
            if consts[key] != first_value:
                same_everywhere = False
                break

        if same_everywhere:
            global_constants[key] = first_value

    # scale to right unit
    constant_names = list(global_constants.keys())
    units_for_constants, scales_for_constants = axis_units(axis_names=constant_names)
    scaled_constants = {}
    for name, scale in zip(constant_names, scales_for_constants):
        raw_value = global_constants[name]
        scaled_constants[name] = raw_value * scale
    constant_labels = []
    for name, unit in zip(constant_names, units_for_constants):
        value = scaled_constants[name]
        constant_labels.append(f"{name}: {value:.2f} {unit}")

    count = 0
    for grid_type, experiments in filtered_plot_data.items():

        req_client_local = req_client_grids[grid_type]
        req_server_local = req_server_grids[grid_type]

        for exp_name, runs in experiments.items():

            for entry in runs:

                # stream filtering
                if (
                    entry['client'] in req_client_local
                    and entry['server'] in req_server_local
                ):
                    count += 1
                    x_value = entry[axis_names[0]]
                    y_value = entry[axis_names[1]]

                    hue_value = None

                    if len(axis_names) > 2:
                        hue_value = entry.get(axis_names[2])

                    if x_value is not None and y_value is not None:

                        client_server.append(
                            f"{entry['client']}-{entry['server']}"
                        )

                        axis_values.append({
                            "x_axis": x_value,
                            "y_axis": y_value,
                            "hue": hue_value
                        })

                    else:

                        files_not_used.append(
                            f"{entry['client']}_{entry['server']}_{entry['num']}"
                        )
    print(f"Found {count} streams with specified client and server")
    title = " Files NOT used | Because entail values of None"
    print(title.center(WIDTH, "_"))
  
    for file_id in files_not_used:                # finding file which is not use

        for grid_type, experiments in grouped_by_grid.items():

            for exp in experiments:

                for path in exp["nsperf"]:

                    if file_id in str(path):
                        print(path)


    for grid_type in req_client_grids:

        req_c = req_client_grids[grid_type]
        req_s = req_server_grids[grid_type]
        full  = full_grids[grid_type]

        stream, stream_file_name = resolve_stream(
            req_c,
            req_s,
            full,
            grid_type
        )

        title = f" Creating Plots | {stream} "
        print(title.center(WIDTH, "_"))

    percentile_matrixs = []
    for item in variable_map:
        nsperf = item.get("nsperf")
        if "host_local" in nsperf:
            name_item = item.get("name")
            percentile_matrixs.append(name_item)
    base_name = Path(input_path).name  # or .stem

    scaled_values = []
    units, unit_scales = axis_units(axis_names=axis_names)

    axis_keys = ["x_axis", "y_axis"]

    scaled_values = []

    for key, scale in zip(axis_keys, unit_scales):
        values = np.array([entry[key] for entry in axis_values])
        scaled_values.append(values * scale)

    scaled_x_values, scaled_y_values = scaled_values
    
    violin_data = {
    "x": scaled_x_values,
    "y": scaled_y_values,
    "hue": [e["hue"] for e in axis_values]
    }

    hue_value = entry.get(axis_names[2]) if len(axis_names) > 2 else None

    violin_df = pd.DataFrame(violin_data)

    axis_labels = []
    for i, axis in enumerate(axis_names):
        axis_labels.append(f"{axis} {units[i]:}")
    axis_labels_naming = [label.replace(" ", "_") for label in axis_labels]


    plot_file_name = plot_naming(axis_names=axis_names,
                                 percentile_matrixs=percentile_matrixs,
                                 percentile=percentile,
                                 file_name=base_name,
                                 stream_file_name=stream_file_name)
    plot_title,plot_under_title = plot_titling(stream=stream,
                              axis_names=axis_labels_naming,
                              percentile_matrixs=percentile_matrixs,
                              percentile=percentile,
                              constants=constant_labels)
    plot_graph(
        x_axis=scaled_x_values,
        y_axis=scaled_y_values,
        axis_labels = axis_labels,
        hue = (
            [e["hue"] for e in axis_values]
            if any(e["hue"] is not None for e in axis_values)
            else None
        ),
        fontsize=FONT_SIZE,
        picture_size=(16, 9),
        file_path=output_path,
        titlename = f" DATA points {plot_title}",
        sub_title = plot_under_title,
        file_name=f"{plot_file_name}.png"
    )
    if axis_names[0] not in ("link_loss", "num_streams"):
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
    df=violin_df,
    axis_labels=axis_labels,
    fontsize=FONT_SIZE,
    picture_size=(16, 9),
    file_path=output_path,
    file_name=f"{plot_file_name}_boxplot.png",
    titlename=f"BOXPLOT {plot_title}",
    sub_title=plot_under_title,
    )
    plot_violin(
        violin_df = violin_df,
        axis_labels = axis_labels,
        titlename = f" Violin {plot_title}",
        fontsize=FONT_SIZE,
        picture_size=(16, 9),
        file_path=output_path,
        file_name=f"{plot_file_name}_violin.png",
        sub_title = plot_under_title,
    )

    for name in percentile_matrixs:
        if name in axis_names:
            print(f"\nPercentile Setting does matter for parameters '{name}'")
    if len(req_client_grids) >= 2:
        print("\nWARNING: Graphs used don't have same structure")
        print("Specifically you have")
        for grid_type in full_grids:
            full_grid = full_grids[grid_type]

            print(f"Grid Type: {grid_type}")
            print("Full Grid intials:")
            print(full_grid)
            print("-" * WIDTH)