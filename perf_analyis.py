import argparse
from pathlib import Path
import json
from typing import Tuple, Optional, Dict, Any
import re
import matplotlib.pyplot as plt
from collections import defaultdict

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

def percentile_refactor(percentile: float) -> str:
    if not (0 <= percentile <= 100):
        raise argparse.ArgumentTypeError("Percentile must be between 0 and 100")
    
    if percentile <= 1:
        prc_percentile = percentile
        percentile = percentile * 100
        print(f"\nWrong Formatting {prc_percentile}, expect in range above 1 to 100, therefore set to {percentile}")

    allowed = [0, 50, 95, 99]
    closest = min(allowed, key=lambda x: abs(x - percentile))
    if closest != percentile:
        print(f"\nThe ONLY possible percentiles: {allowed} | {percentile} Therefore changed to {closest} \n")
    if closest == 0:
        return "mean_ns"
    else:
        return f"p{closest}_ns"

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
        return value
    # NSPERF IS A TUPLE
    if isinstance(nsperf_variable, list) and len(nsperf_variable) == 3:
        _,value_1 = find_nsperf_variable(data=data,target=nsperf_variable[0])
        sign = nsperf_variable[1]
        _,value_2 = find_nsperf_variable(data=data,target=nsperf_variable[2])

        if value_1 is None or value_2 is None or sign is None:
            print("Missing values in equation")
            return None
        value = calc_tuple_nsperf(key_1=value_1,key_2=value_2,sign=sign)
        return value
    if isinstance(nsperf_variable, list) and len(nsperf_variable) == 4:
        _,value_1 = find_nsperf_variable(data=data,target=nsperf_variable[0])
        sign = nsperf_variable[1]
        _,value_2 = find_nsperf_variable(data=data,target=nsperf_variable[2])

        if value_1 is None or value_2 is None or sign is None:
            print("Missing values in equation")
            return None
        value = calc_tuple_nsperf(key_1=value_1,key_2=value_2,sign=sign)
        value += float(nsperf_variable[3])
        return value

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
    if input.is_dir():
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

def plot_graph(x_axis: list,
               y_axis: list,
               file_path: Path,
               file_name: str,
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

    ax.set_xlabel("X Axis", fontsize=fontsize)
    ax.set_ylabel("Y Axis", fontsize=fontsize)
    ax.tick_params(axis='both', labelsize=fontsize)

    ax.grid(True)

    plt.tight_layout()

    output_file = file_path / file_name

    # ensure folder exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    plt.savefig(output_file)
    plt.close(fig)

def plot_boxplot(boxplot_data: list,
                 file_path: Path,
                 file_name: str,
                 fontsize: int = 12,
                 picture_size: tuple = (16,9)):
    labels = list(box_data.keys())
    values = list(box_data.values())

    fig, ax = plt.subplots(figsize=picture_size)

    ax.boxplot(values, tick_labels=labels)

    ax.set_xlabel("X Axis",fontsize=fontsize)
    ax.set_ylabel("Y Axis",fontsize=fontsize)
    ax.grid(True)

    plt.tight_layout()

    output_file = file_path / file_name

    # ensure folder exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    plt.savefig(output_file)
    plt.show()
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tool for analysing the NSPERF/IPERF streams from the graphs')
    parser.add_argument('-i','--input',type=json_path,required=True,help='The desired directory or file which is be performed analysis on (Json Format IPERF/NSPERF)')
    parser.add_argument('-o','--output',type=Path,help='The desired directory for saving PLOTS')
    parser.add_argument('-g','--graph',type=json_path,help='The directory or file which is the entail nodes and links desription (Json Format)')
    parser.add_argument('-p','--percentile',type=float,required=True,help='What data is of interest for the analysis 0 = mean 50 %,95 % 99 % percentile (Json Format IPERF/NSPERF)')
    parser.add_argument('-x','--x_axis',type=str,required=True,help='Variable for X axis')
    parser.add_argument('-y','--y_axis',type=str,required=True,help='Variable for Y axis')
    args = parser.parse_args()

    input_path = args.input

    output_path = args.output or Path("./plots")

    experiments = pairing_files(input=input_path)
    percentile = percentile_refactor(args.percentile)

    experiments = sorted(experiments, key=lambda e: float(e["name"]))

    variable_map  = []
    variable_map .append({"name": "link_loss", "aliases": ["link_loss", "link loss"], "nsperf": "link_loss"})                     #Need to change to just what's in graph
    variable_map .append({"name": "total_loss", "aliases": ["total_loss", "total loss"], "nsperf": ["received_bits", "/", "generated_bits","-1"]})
    variable_map .append({"name": "throughput", "aliases": ["throughput", "tp"], "nsperf": "received_bps"})
    variable_map .append({"name": "latency", "aliases": ["latency", "lat"], "nsperf": "host_local_latency_estimate_ns"})    #IDK if this is the right latency
    variable_map .append({"name": "jitter", "aliases": ["jitter", "jit"], "nsperf": "host_local_latency_jitter_abs_ns"})    #IDK if this is the right jitter
    variable_map .append({"name": "num_streams", "aliases": ["num_streams", "num streams"], "nsperf": "IDK"})
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


    title = " Files used for analysis "
    print(title.center(WIDTH, "-"))

    for exp in experiments:
        exp["nsperf"] = sorted(exp["nsperf"], key=nsperf_key)
        nsperf_files = exp["nsperf"]
        graph_file = exp["graphs"]

        title = f" Link loss: {exp['name']} "
        print()
        print(title.center(WIDTH, "_"))

        for f in nsperf_files:
            interval_step, json_file_data, end_time = nsperf_interval_set(f)

            end_str = "" if end_time is None else str(end_time)

            print(
                f"{str(f).ljust(path_width)} | "
                f"interval: {str(interval_step).ljust(PLOT_SPACING)} | "
                f"End time {end_str.ljust(PLOT_SPACING)} | "
                f"Graph: {str(graph_file).ljust(path_width)}"
            )

    print("-" * WIDTH)
    plot_data = defaultdict(list)
    for i, exp in enumerate(experiments):
        exp["nsperf"] = sorted(exp["nsperf"], key=nsperf_key)
        nsperf_files = exp["nsperf"]
        graph_file = exp["graphs"]
        
        title = f" Plot Creation for directory \'{exp["name"]}\' | Axis | X: {axis_names[0]} | Y: {axis_names[1]} "
        print()
        print(title.center(WIDTH, "_"))
        prev_client = None
        first_client = True
        for f in nsperf_files:
            # Just for structure
            stem = Path(f).stem  
            client, server, num = stem.split("_")
            if client != prev_client and first_client is False:
                    print("=" * WIDTH)
            interval_step, json_file_data, end_time = nsperf_interval_set(f)
            data,ids = sorting_data_nsperf(file_data=json_file_data,interval_step=interval_step,percentile=percentile,max_window=None)
            prev_client = client
            first_client = False
            """         This just for intermediate for seing what is saved    """
            # file_text = f" Extracted data from file \'{f}\' with ID {ids.get("flow_id")} "
            # print(file_text.center(WIDTH, "-"))
            # for w_key, w_data in data.items():
            #     print(w_key)      # e.g. "window_0"
            #     print(w_data)     # the inner dict
            grid,nodes, graph_link_loss = extract_graph(graph_file)
            link_loss = float(exp["name"]) if is_number(exp["name"]) else graph_link_loss
            mesh_size = len(nodes)
            if interval_step is None:
                axis_values = []
                data["mesh_size"] = mesh_size
                data["link_loss"] = link_loss
                for axis_nsperf in axis_nsperfs:
                        axis_value = extract_variable_full(data=data,nsperf_variable=axis_nsperf)
                        axis_values.append(axis_value)
                print(f"File {str(f).ljust(path_width)} | X value = {str(axis_values[0]).ljust(PLOT_SPACING)} | Y value = {str(axis_values[1]).ljust(PLOT_SPACING)}")

                plot_data[link_loss].append({
                                            "client": client,
                                            "server": server,
                                            "num": num,
                                            "x_axis": axis_values[0],
                                            "y_axis": axis_values[1]
                                            })
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

    for loss, runs in plot_data.items():
        x_axis_values = []
        y_axis_values = []
        client_server = []
        box_data = defaultdict(list)
        for entry in runs:
            x_axis_values.append(entry["x_axis"])
            y_axis_values.append(entry["y_axis"])
            client_server.append(f"{entry['client']}-{entry['server']}")
            value = entry["y_axis"]
            # as of now done fixed needs to so can use with the different arguments avaible for plotting
            box_data[f"{entry['client']}-{entry['server']}"].append(value if value is not None else 0)
        
        plot_graph(
            x_axis=client_server,
            y_axis=y_axis_values,
            fontsize=12,
            picture_size=(16, 9),
            file_path=output_path,
            type_graph = 1,
            file_name=f"link_loss_{loss}_X_{axis_names[0]}_Y_{axis_names[1]}.png"
        )
        plot_boxplot(
            boxplot_data=box_data,
            fontsize=12,
            picture_size=(16, 9),
            file_path=output_path,
            file_name=f"link_loss_{loss}_X_{axis_names[0]}_Y_{axis_names[1]}_boxplot.png"
        )
