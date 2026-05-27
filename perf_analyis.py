import argparse
import textwrap
from pathlib import Path
import json
from typing import Tuple, Optional, Dict, Any
import re
import matplotlib.pyplot as plt
from collections import defaultdict, Counter
import numpy as np
import seaborn as sns
import pandas as pd
import hashlib
from tqdm import tqdm

WIDTH = 150
PLOT_SPACING = 10
WINDOW_START_END_SPACING = 5
FONT_SIZE = 22
TITLE_SCALE = 1.8
UNDERTITLE_SCALE = 1.3
AXIS_VALUE_SCALE = 0.8
PALLETTE = ["#4C72B0", "#DC1D33","#16A944","#D9D31C","#E514D0"]
# Colours for theoretical hop-count overlay (kept distinct from PALLETTE)
THEORY_COLORS = ["#e41a1c", "#ff7f00", "#4daf4a", "#984ea3", "#a65628", "#f781bf"]

def extract_percentile_data(dict_name: str, file_data: dict, percentile: str) -> dict:
    data = file_data.get(dict_name, {})

    def recurse(obj):
        result = {}
        for k, v in obj.items():
            if isinstance(v, dict):
                if percentile in v:
                    result[k] = v[percentile]
                else:
                    nested = recurse(v)
                    if nested:
                        result[k] = nested
            else:
                result[k] = v
        return result

    return recurse(data)

def sorting_data_nsperf(file_data: dict,
                        percentile: str,
                        max_window: int = None,
                        interval_step: float = None) -> Tuple[dict, str]:
    flow_id = file_data.get("flow_id")
    run_id = file_data.get("run_id")
    schema = file_data.get("schema")

    ids = {
        "flow_id": flow_id,
        "run_id": run_id,
        "schema": schema
    }
    results = {}

    if interval_step is None:
        counts = file_data.get("counts")
        rates = file_data.get("rates")
        timing = extract_percentile_data(dict_name="timing", file_data=file_data, percentile=percentile)

        results = {
            "counts": counts,
            "rates": rates,
            "timing": timing
        }

    else:
        windows = file_data.get("intervals", {}).get("windows", [])

        for w, window in enumerate(windows[:max_window]):
            end_time = window.get("end_s")
            start_time = window.get("start_s")
            delivery = extract_percentile_data(dict_name="delivery_for_send_window", file_data=window, percentile=percentile)
            send = extract_percentile_data(dict_name="send_window", file_data=window, percentile=percentile)
            receive = extract_percentile_data(dict_name="receive_window", file_data=window, percentile=percentile)
            results[f"window_{w}"] = {
                "start": start_time,
                "end": end_time,
                "delivery": delivery,
                "receive": receive,
                "send": send
            }

    return results, ids

def json_path(p: str) -> Path:
    path = Path(p)

    if not path.exists():
        raise argparse.ArgumentTypeError("Path does not exist")

    if path.is_file():
        if path.suffix.lower() != ".json":
            raise argparse.ArgumentTypeError("File must be a .json")
        return path

    if path.is_dir():
        json_files = list(path.rglob("*.json"))
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
        return list(path.glob("*.json"))

    return []

def nsperf_interval_set(file: Path) -> Tuple[Optional[dict], dict]:
    with file.open() as f:
        data = json.load(f)

    intervals = data.get("intervals", {}).get("interval_seconds")
    windows = data.get("intervals", {}).get("windows", [])
    end_time = None
    if windows:
        last_window = windows[-1]
        end_time = last_window.get("end_s")

    return intervals, data, end_time

def percentile_refactor(percentile: str) -> str:
    allowed = ["50", "95", "99", "mean", "min", "max"]
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
    for section_name, section_data in data.items():
        if isinstance(section_data, dict) and target in section_data:
            return section_name, section_data[target]
    return None, None

def plot_variables_allowed(data_variable: str,
                           variable_map: list[dict]) -> Optional[Tuple[str, str]]:
    for item in variable_map:
        alias = item.get("aliases", [])
        if data_variable in alias:
            return item.get("name"), item.get("nsperf")

    print(f"WARNING: variable not available")
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
        print(f"Still need implementation for this NSPERF variable | {nsperf_variable=}")
        exit()

    if isinstance(nsperf_variable, str):
        _, value = find_nsperf_variable(data, nsperf_variable)
        value = round(value, 2) if value is not None else None
        return value

    if not isinstance(nsperf_variable, list):
        return None

    while "(" in nsperf_variable:
        start = None
        end = None

        for i, item in enumerate(nsperf_variable):
            if item == "(":
                start = i
            if item == ")" and start is not None:
                end = i
                break

        if start is None or end is None:
            print("[WARN] Unmatched parentheses")
            return None

        inner_expr = nsperf_variable[start + 1:end]
        inner_value = extract_variable_full(data, inner_expr)
        if inner_value is None:
            return None

        nsperf_variable = (
            nsperf_variable[:start]
            + [inner_value]
            + nsperf_variable[end + 1:]
        )

    values = []
    ops = []
    for item in nsperf_variable:
        if isinstance(item, str) and item in {"+", "-", "*", "/"}:
            ops.append(item)
            continue

        if isinstance(item, (int, float)):
            values.append(item)
        else:
            _, v = find_nsperf_variable(data, item)
            if v is None:
                print(f"[WARN] Missing key: {item} in {nsperf_variable}")
                return None
            if v == 0:
                return None
            values.append(v)

    if len(values) == 0:
        return None

    if len(values) == 2 and len(ops) == 0:
        return values[0], values[1]

    expected = None
    if len(nsperf_variable) > 0 and isinstance(nsperf_variable[-1], (int, float)):
        expected = values.pop()

    if len(values) != len(ops) + 1:
        print(f"[WARN] Mismatch values/operators: {nsperf_variable}")
        return None

    result = values[0]
    for i, op in enumerate(ops):
        result = calc_tuple_nsperf(result, values[i + 1], op)
        if result is None:
            return None

    if expected is not None:
        result = expected - result

    return round(result, 2)

def normalize_nsperf(name: str) -> str:
    return name.removeprefix("nsperf_")

def normalize_graph(name: str) -> str:
    return name.removeprefix("graph_")

def pair_nsperf_graph(nsperf_files: list,
                      graph_files: list) -> tuple[list, list]:
    pairs = []
    if len(graph_files) == 1:
        for n in nsperf_files:
            pairs.append((n, graph_files))
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
        node_id = node['id']
        grid_id.append(node_id)
        if "n" in node_id:
            nodes_id.append(node_id)

    links = data['links']
    for link in links:
        link_loss = link['loss_percent']
    return grid_id, nodes_id, f"{link_loss:.2f}"

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
    """Stops at iter_X or numeric/magnitude folder, does not go above iter level."""
    for parent in path.parents:
        name = parent.name.lower()

        if name.startswith("iter_"):
            return parent

        if is_number(name):
            return parent

        if name.endswith(("k", "m")):
            return parent

    return path.parent

def pairing_files(input: Path) -> list:
    experiments = []

    stream_dirs = list(input.rglob("nsperf/streams"))
    if not stream_dirs:
        stream_dirs = list(input.rglob("nsperf\\streams"))

    for stream_dir in stream_dirs:
        experiment_root = stream_dir.parents[2]
        experiment_naming = stream_dir.parents[1]

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

def plot_graph(x_axis: list,
               y_axis: list,
               axis_labels,
               file_path: Path,
               file_name: str,
               titlename: str,
               sub_title: str,
               fontsize: int = 12,
               picture_size: tuple = (16, 9),
               hue=None,
               hue_label: str = None,
               log_scale_x: bool = False,
               log_scale_y: bool = False,
               theory_hops: int = 0):

    fig, ax = plt.subplots(figsize=picture_size)

    if hue is not None:
        n_hues = len(set(hue))
        sns.scatterplot(
            x=x_axis,
            y=y_axis,
            hue=hue,
            ax=ax,
            palette=PALLETTE[:n_hues],
            alpha=0.6
        )
    else:
        sns.scatterplot(
            x=x_axis,
            y=y_axis,
            ax=ax,
            color=PALLETTE[0],
            alpha=0.6
        )

    # Theoretical hop-count overlay (assumes x is link_loss in %)
    theory_handles = []
    if theory_hops > 0:
        x_sorted = sorted(set(x_axis))
        for hop in range(1, theory_hops + 1):
            color = THEORY_COLORS[(hop - 1) % len(THEORY_COLORS)]
            theory_y = [(1 - (1 - x / 100) ** hop) * 100 for x in x_sorted]
            (line,) = ax.plot(
                x_sorted, theory_y,
                linestyle="--", color=color, linewidth=2.5,
                marker="o", markersize=6, zorder=5,
                label=f"{hop} hop{'s' if hop > 1 else ''}",
            )
            theory_handles.append(line)

    data_handles, data_labels = ax.get_legend_handles_labels()
    # Separate seaborn data handles from theory handles
    seaborn_handles = [h for h, l in zip(data_handles, data_labels)
                       if not l.endswith("hop") and not l.endswith("hops")]
    seaborn_labels  = [l for l in data_labels
                       if not l.endswith("hop") and not l.endswith("hops")]

    legend_kw = dict(fontsize=fontsize * AXIS_VALUE_SCALE,
                     title_fontsize=fontsize, frameon=True)
    if theory_handles and seaborn_handles:
        leg1 = ax.legend(seaborn_handles, seaborn_labels,
                         title=hue_label or (axis_labels[2] if len(axis_labels) > 2 else ""),
                         loc="upper left", **legend_kw)
        ax.add_artist(leg1)
        ax.legend(theory_handles, [h.get_label() for h in theory_handles],
                  title="Theoretical loss", loc="upper right", **legend_kw)
    elif theory_handles:
        ax.legend(theory_handles, [h.get_label() for h in theory_handles],
                  title="Theoretical loss", loc="best", **legend_kw)
    elif seaborn_handles:
        ax.legend(seaborn_handles, seaborn_labels,
                  title=hue_label or (axis_labels[2] if len(axis_labels) > 2 else ""),
                  loc="best", **legend_kw)

    fig.suptitle(titlename, fontsize=fontsize * TITLE_SCALE, y=0.98)
    ax.set_title(sub_title, fontsize=fontsize * UNDERTITLE_SCALE, pad=10)
    if log_scale_x:
        ax.set_xscale("log")
    if log_scale_y:
        ax.set_yscale("log")
    ax.set_xlabel(axis_labels[0], fontsize=fontsize)
    ax.set_ylabel(axis_labels[1], fontsize=fontsize)
    ax.tick_params(axis='both', labelsize=fontsize * AXIS_VALUE_SCALE)
    ax.grid(True, which="both" if (log_scale_x or log_scale_y) else "major")

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
    picture_size: tuple = (16, 9),
    log_scale_y: bool = False,
    hue_label: str = None,
):

    fig, ax = plt.subplots(figsize=picture_size)

    if "hue" in df.columns and df["hue"].notna().any():
        n_hues = df["hue"].nunique()
        sns.boxplot(
            data=df,
            x="x",
            y="y",
            hue="hue",
            ax=ax,
            palette=PALLETTE[:n_hues]
        )
    else:
        sns.boxplot(
            data=df,
            x="x",
            y="y",
            ax=ax,
            color=PALLETTE[0]
        )

    ax.legend(
            title=hue_label or axis_labels[2],
            loc="best",
            fontsize=fontsize * AXIS_VALUE_SCALE,
            title_fontsize=fontsize,
            frameon=True,
        )
    if log_scale_y:
        ax.set_yscale("log")
    fig.suptitle(titlename, fontsize=fontsize * TITLE_SCALE, y=0.98)
    ax.set_title(sub_title, fontsize=fontsize * UNDERTITLE_SCALE, pad=10)
    ax.set_xlabel(axis_labels[0], fontsize=fontsize)
    ax.set_ylabel(axis_labels[1], fontsize=fontsize)
    ax.tick_params(axis='both', labelsize=fontsize * AXIS_VALUE_SCALE)
    ax.grid(True, which="both" if log_scale_y else "major")

    plt.tight_layout()

    output_file = file_path / file_name
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
    picture_size: tuple = (16, 9),
    log_scale_y: bool = False,
    hue_label: str = None,
    theory_hops: int = 0,
):

    fig, ax = plt.subplots(figsize=picture_size)

    has_hue = (
        "hue" in violin_df.columns
        and violin_df["hue"].notna().any()
    )

    if has_hue:
        split = violin_df["hue"].nunique() >= 2
        n_hues = violin_df["hue"].nunique()
        sns.violinplot(
            data=violin_df,
            x="x",
            y="y",
            hue="hue",
            split=split,
            inner="quart",
            cut=0,
            linewidth=2.5,
            bw_method=.2,
            density_norm="width",
            palette=PALLETTE[:n_hues],
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

    # Theoretical hop-count overlay
    # Violin x-axis is categorical: sorted unique x values map to positions 0, 1, 2, …
    theory_handles = []
    if theory_hops > 0:
        x_categories = sorted(violin_df["x"].unique())
        positions = list(range(len(x_categories)))
        for hop in range(2, theory_hops + 1):
            color = THEORY_COLORS[(hop - 1) % len(THEORY_COLORS)]
            theory_y = [(1 - (1 - x / 100) ** hop) * 100 for x in x_categories]
            (line,) = ax.plot(
                positions, theory_y,
                linestyle="--", color=color, linewidth=2.5,
                marker="o", markersize=6, zorder=5,
                label=f"{hop} hop{'s' if hop > 1 else ''}",
            )
            theory_handles.append(line)

    # Build legend(s)
    seaborn_handles, seaborn_labels = ax.get_legend_handles_labels()
    seaborn_handles = [h for h, l in zip(seaborn_handles, seaborn_labels)
                       if not l.endswith("hop") and not l.endswith("hops")]
    seaborn_labels  = [l for l in seaborn_labels
                       if not l.endswith("hop") and not l.endswith("hops")]

    legend_kw = dict(fontsize=fontsize * AXIS_VALUE_SCALE,
                     title_fontsize=fontsize, frameon=True)
    if theory_handles and seaborn_handles:
        leg1 = ax.legend(seaborn_handles, seaborn_labels,
                         title=hue_label or (axis_labels[2] if len(axis_labels) > 2 else ""),
                         loc="best", **legend_kw)
        ax.add_artist(leg1)
        ax.legend(theory_handles, [h.get_label() for h in theory_handles],
                  title="Theoretical loss", loc="best", **legend_kw)
    elif theory_handles:
        ax.legend(theory_handles, [h.get_label() for h in theory_handles],
                  title="Theoretical loss", loc="best", **legend_kw)
    elif seaborn_handles:
        ax.legend(seaborn_handles, seaborn_labels,
                  title=hue_label or (axis_labels[2] if len(axis_labels) > 2 else ""),
                  loc="best", **legend_kw)

    if log_scale_y:
        ax.set_yscale("log")
    fig.suptitle(titlename, fontsize=fontsize * TITLE_SCALE, y=0.98)
    ax.set_title(sub_title, fontsize=fontsize * UNDERTITLE_SCALE, pad=10)
    ax.set_xlabel(axis_labels[0], fontsize=fontsize)
    ax.set_ylabel(axis_labels[1], fontsize=fontsize)
    ax.tick_params(axis='both', labelsize=fontsize * AXIS_VALUE_SCALE)
    ax.grid(True, which="both" if log_scale_y else "major", alpha=0.3)

    plt.tight_layout()

    output_file = file_path / file_name
    output_file.parent.mkdir(parents=True, exist_ok=True)

    plt.savefig(output_file, dpi=300)
    plt.close(fig)

def axis_units(axis_names: list, variable_map: list[dict], percentile: str = None) -> tuple[list, list, list, list]:
    labels = []
    unit_strings = []
    scales = []
    log_scales = []

    perc_str = percentile.replace("_ns", "") if percentile else None

    for name in axis_names:
        info = next((v for v in variable_map if v["name"] == name), None)
        if info:
            if perc_str and info.get("uses_percentile"):
                labels.append(f"{info['label']} [{info['unit']}] ({perc_str})")
            else:
                labels.append(f"{info['label']} [{info['unit']}]")
            unit_strings.append(f"[{info['unit']}]")
            scales.append(info["scale"])
            log_scales.append(info.get("log_scale", False))
        else:
            print(f"Could not find unit info for variable: {name}")
            labels.append(f"{name} [-]")
            unit_strings.append("[-]")
            scales.append(1)
            log_scales.append(False)

    return labels, unit_strings, scales, log_scales

def bin_splitting(values: list, n_bins: int = 10) -> list:
    if len(values) < n_bins:
        n_bins = len(values)
    values = np.array(values)
    sorted_vals = np.sort(values)
    splits = np.array_split(sorted_vals, n_bins)
    return [s.tolist() for s in splits]

def bin_naming(bins: list[list]) -> list:
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
            if s is o:
                continue
            if o["start_s"] <= s["stop_s"] and o["stop_s"] > s["start_s"]:
                count += 1

        s["active_streams"] = count

    return streams

def _req_tp_round_precision(sch_tp: float) -> int:
    if sch_tp >= 1_000_000:
        return -5   # nearest 100 K
    if sch_tp >= 100_000:
        return -4   # nearest 10 K
    return -3       # nearest 1 K

def _abbrev_name(name: str) -> str:
    return "".join(p[0] for p in name.split("_")).upper()

def _fmt_const_value(v) -> str:
    if not isinstance(v, (int, float)):
        return str(v)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.4g}M"
    if v >= 1_000:
        return f"{v / 1_000:.4g}k"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return f"{v:.4g}"

def plot_naming(axis_names: list[str],
                percentile_metrics: list[str],
                percentile: str,
                file_name: str,
                global_constants: dict) -> str:
    perc_str = ""
    if any(name in percentile_metrics for name in axis_names):
        perc_str = f"_p{percentile.replace('_ns', '')}"

    x, y = axis_names[0], axis_names[1]
    hue_str = f"_hue_{axis_names[2]}" if len(axis_names) > 2 else ""

    const_str = ""
    if global_constants:
        parts = sorted(f"{_abbrev_name(k)}={_fmt_const_value(v)}" for k, v in global_constants.items())
        const_str = "_" + "_".join(parts)

    return f"{file_name}_{x}_vs_{y}{perc_str}{hue_str}{const_str}"

def plot_titling(
    stream: str,
    axis_names: list[str],
    percentile_metrics: list[str],
    percentile: str,
    constants: list
) -> tuple[str, str]:
    parts = stream.split("|")[1:]
    title_parts = ["With Streams Used Being"]
    for part in parts:
        title_parts.append(part)
    under_title_parts = []

    has_percentile = any(name in percentile_metrics for name in axis_names)

    _ = has_percentile  # percentile shown on axis label, not in title

    if constants:
        for constant in constants:
            under_title_parts.append(f"{constant}")

    title = " | ".join(title_parts)
    under_title = " | ".join(sorted(under_title_parts))
    return title, under_title

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
    parser.add_argument('-i', '--input', type=json_path, required=True, action='append', help='Input directory or file (can be repeated to merge multiple sources)')
    parser.add_argument('-o', '--output', type=Path, help='The desired directory for saving PLOTS')
    parser.add_argument('-p', '--percentile', type=str, required=True, help='Percentile selection: 50, 95, 99, mean, min, max')
    parser.add_argument('-x', '--x_axis', type=str, required=True, help='Variable for X axis')
    parser.add_argument('-y', '--y_axis', type=str, required=True, help='Variable for Y axis')
    parser.add_argument('-c', '--client', type=str, help='If Desire only observe one specific Stream Set Client and Server')
    parser.add_argument('-s', '--server', type=str, help='If Desire only observe one specific Stream Set Client and Server')
    parser.add_argument('-0', '--zero_filter', action="store_true", help='Filter streams at time stamp: 0')
    parser.add_argument('--hue', type=str, help='Optional grouping variable for seaborn hue')
    parser.add_argument('-v', '--verbose', action="store_true", help='set verbosity')
    parser.add_argument("-f", "--filter", action="append", help="Filter format: key=value (can be repeated)")
    parser.add_argument("--title", type=str, default=None, help="Override the plot title (default: auto-generated)")
    parser.add_argument("--theory-hops", type=int, default=0, metavar="N",
                        help="Overlay theoretical hop-count packet-loss curves for 1..N hops (assumes x=link_loss %%)")
    parser.add_argument("--plot-type", type=str, default="all",
                        help="Which plot(s) to generate: scatter, box, violin, or all (default: all). Comma-separated for multiple, e.g. violin,box")

    args = parser.parse_args()
    filters = args.filter or []
    verbosity = args.verbose
    input_paths = args.input
    output_path = args.output or Path("./plots")
    req_client = args.client
    req_server = args.server
    custom_title = args.title
    theory_hops  = args.theory_hops
    _requested_plots = {p.strip().lower() for p in args.plot_type.split(",")}
    do_scatter = "all" in _requested_plots or "scatter" in _requested_plots
    do_box     = "all" in _requested_plots or "box"     in _requested_plots
    do_violin  = "all" in _requested_plots or "violin"  in _requested_plots

    if req_client is not None:
        req_client = req_client.strip().lower().split(",")
    if req_server is not None:
        req_server = req_server.strip().lower().split(",")

    experiments = []
    for ip in input_paths:
        experiments.extend(pairing_files(input=ip))
    percentile = percentile_refactor(args.percentile)
    experiments = sorted(experiments, key=lambda e: experiment_sort_key(e["name"]))

    variable_map = [
        {"name": "link_loss",               "aliases": ["link_loss", "link loss"],                                              "nsperf": "link_loss",                                                                                                          "label": "Link Loss",                   "unit": "%",    "scale": 1},
        {"name": "loss_vs_transmit",         "aliases": ["loss_vs_transmit", "loss_vs_trans"],                                  "nsperf": ["received_bits", "/", "generated_bits", 1],                                                                          "label": "Loss after TX Success",            "unit": "%",    "scale": 100},
        {"name": "throughput",               "aliases": ["throughput", "tp"],                                                   "nsperf": "received_bps",                                                                                                       "label": "Throughput",                  "unit": "Mb/s", "scale": 1e-6},
        {"name": "latency",                  "aliases": ["latency", "lat"],                                                     "nsperf": "host_local_latency_estimate_ns",                                                                                     "label": "Latency",                     "unit": "ms",   "scale": 1e-6, "uses_percentile": True, "log_scale": True},
        {"name": "jitter",                   "aliases": ["jitter", "jit"],                                                      "nsperf": "host_local_latency_jitter_abs_ns",                                                                                   "label": "Jitter",                      "unit": "ms",   "scale": 1e-6, "uses_percentile": True, "log_scale": True},
        {"name": "num_streams",              "aliases": ["num_streams", "num streams"],                                         "nsperf": ["send_start_ns", "send_end_ns"],                                                                                     "label": "Number of Streams",           "unit": "-",    "scale": 1},
        {"name": "transmit_throughput",      "aliases": ["transmit_throughput", "transmit throughput", "transmit_bps", "tr_tp", "tra_tp"], "nsperf": "generated_bps",    "hide_from_title": True,                                                                                     "label": "Transmit Throughput",         "unit": "Mb/s", "scale": 1e-6, "hide_from_title": True},
        {"name": "scheduled_throughput",     "aliases": ["scheduled_throughput", "sch_tp"],                                    "nsperf": ["generated_bps", "/", "send_attempts", "*", "scheduled_packets_logged"],                                             "label": "Scheduled Throughput",        "unit": "Mb/s", "scale": 1e-6},
        {"name": "loss_vs_scheduled",        "aliases": ["loss_vs_scheduled", "scheduled_loss", "loss_vs_sch","total_loss"],                "nsperf": ["received_bits", "/", "(", "generated_bits", "/", "send_attempts", "*", "scheduled_packets_logged", ")", 1],         "label": "Total Packet Loss",           "unit": "%",    "scale": 100},
        {"name": "mesh_size",                "aliases": ["mesh_size", "mesh size", "meshsize"],                                            "nsperf": "mesh_size",                                                                                                          "label": "Mesh Size",                   "unit": "-",    "scale": 1},
        {"name": "scheduled_vs_transmit_loss","aliases": ["scheduled_vs_transmit_loss", "sch_vs_trans"],                                                     "hide_from_title": True,                                                     "nsperf": ["send_attempts", "/", "scheduled_packets_logged", 1],                                                                "label": "TX Failure",  "unit": "%",    "scale": 100},
    ]

    axis_names = []
    axis_nsperfs = []

    requested_axes = [args.x_axis, args.y_axis]
    if args.hue:
        requested_axes.append(args.hue)

    for axis in requested_axes:
        axis = axis.strip().lower()
        results = plot_variables_allowed(data_variable=axis, variable_map=variable_map)
        if results is None:
            exit()
        name, nsperf = results
        axis_names.append(name)
        axis_nsperfs.append(nsperf)

    all_nsperfs = {v["name"]: v["nsperf"] for v in variable_map}

    for exp in experiments:
        exp["name"] = experiment_name(exp["name"])

    print(f"{percentile=}")

    if not experiments:
        print(f"[ERROR] No experiments found in: {[str(p) for p in input_paths]}")
        print("[ERROR] Check that the directories contain nsperf/streams/*.json files")
        exit(1)

    empty_nsperf = [e["name"] for e in experiments if not e["nsperf"]]
    if empty_nsperf:
        print(f"[WARNING] {len(empty_nsperf)} experiment(s) have no nsperf files: {empty_nsperf[:5]}")

    path_width = max((len(f.name) for exp in experiments for f in exp["nsperf"]), default=20) + 2

    graph_reference_path = experiments[0]["graphs"]
    with open(graph_reference_path) as f:
        graph_reference = json.load(f)

    grid_type_map = {}
    grid_type = 0

    if verbosity:
        print("-" * WIDTH)
    plot_data = defaultdict(lambda: defaultdict(list))
    grouped_by_grid = defaultdict(list)

    for exp in tqdm(experiments, desc="Grouping Grid Types", disable=not verbosity):
        graph_file = exp["graphs"]

        with open(graph_file) as f:
            graph_data = json.load(f)

        graph_key = graph_fingerprint(graph_data)
        grid_type = grid_type_map.setdefault(graph_key, len(grid_type_map))

        exp["grid_type"] = grid_type
        grouped_by_grid[grid_type].append(exp)

    req_client_grids = {}
    req_server_grids = {}
    full_grids = {}

    for grid_type, experiments_in_grid in tqdm(grouped_by_grid.items(), desc="Processing All Grid types"):
        first_graph = experiments_in_grid[0]["graphs"]

        full_grid, nodes, graph_link_loss = extract_graph(first_graph)
        full_grid_with_devices = []

        for node in full_grid:
            if node.startswith("a"):
                full_grid_with_devices.append("d" + node[1:])
            else:
                full_grid_with_devices.append(node)
        mesh_size = len(nodes)

        req_client_local = req_client if req_client is not None else full_grid_with_devices
        req_server_local = req_server if req_server is not None else full_grid_with_devices
        req_client_grids[grid_type] = req_client_local
        req_server_grids[grid_type] = req_server_local
        full_grids[grid_type] = full_grid_with_devices

        for exp in tqdm(experiments_in_grid, desc=f"Processing Grid Type {grid_type}", leave=False,):
            stream, stream_file_name = resolve_stream(
                req_client_local,
                req_server_local,
                full_grid,
                grid_type
            )

            link_loss = graph_link_loss
            for split in exp["name"].split("_"):
                if is_number(split):
                    link_loss = float(split)
                    break

            if verbosity is True:
                print()
                print(f"Files in directory '{exp['name']}'".center(WIDTH, "_"))

            prev_client = None
            first_client = True
            for f in tqdm(exp["nsperf"], desc=f"Processing all Files within directory {exp['name'][:20]}", leave=False, disable=not verbosity):
                stem = Path(f).stem
                parts = stem.split("_")

                client = parts[0]
                server = parts[1]
                num = parts[2]

                interval_step, json_file_data, end_time = nsperf_interval_set(f)
                data, ids = sorting_data_nsperf(file_data=json_file_data, interval_step=interval_step, percentile=percentile, max_window=None)
                print(data)

                if interval_step is None:
                    axis_values = []
                    all_nsperf_values = {}
                    data["mesh_size"] = mesh_size
                    data["link_loss"] = link_loss

                    for variable in variable_map:
                        nsperf = variable["nsperf"]
                        name = variable["name"]
                        nsperf_value = extract_variable_full(data=data, nsperf_variable=nsperf)
                        if name == "scheduled_throughput":
                            folder_value = None
                            for split in exp["name"].split("_"):
                                s = split.lower()
                                try:
                                    if s.endswith("k"):
                                        folder_value = float(s[:-1]) * 1_000
                                        break
                                    elif s.endswith("m"):
                                        folder_value = float(s[:-1]) * 1_000_000
                                        break
                                except ValueError:
                                    continue
                            if folder_value is not None:
                                nsperf_value = folder_value
                            elif nsperf_value is not None:
                                nsperf_value = round(nsperf_value, -5)
                        all_nsperf_values[name] = nsperf_value

                    sch_tp = all_nsperf_values.get("scheduled_throughput")
                    req_tp = all_nsperf_values.get("transmit_throughput")
                    if sch_tp is not None and req_tp is not None:
                        all_nsperf_values["transmit_throughput"] = round(req_tp, _req_tp_round_precision(sch_tp))

                    for variable in variable_map:
                        nsperf = variable["nsperf"]
                        name = variable["name"]
                        if nsperf in axis_nsperfs:
                            axis_values.append(all_nsperf_values[name])

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
                            print(title.center(WIDTH, "="))
                        print(f"File {f.name.ljust(path_width)} | Name = {str(exp['name']).ljust(PLOT_SPACING)} | X value = {str(axis_values[0]).ljust(PLOT_SPACING)} | Y value = {str(axis_values[1]).ljust(PLOT_SPACING)}")
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
                        for axis_nsperf in axis_nsperfs:
                            axis_value = extract_variable_full(data=w_data, nsperf_variable=axis_nsperf)
                            axis_values.append(axis_value)

                        print(f"Window {str(w_idx).ljust(PLOT_SPACING)} | Start: {str(start).ljust(WINDOW_START_END_SPACING)} End {str(end).ljust(WINDOW_START_END_SPACING)} [s] | X value = {str(axis_values[0]).ljust(PLOT_SPACING)} | Y value = {str(axis_values[1]).ljust(PLOT_SPACING)}")

    axis_values = []
    client_server = []
    files_not_used = []
    box_data = defaultdict(list)

    sch_vs_req_tp = defaultdict(lambda: {
        "total": 0,
        "match": 0,
        "mismatch": 0,
        "trans_counts": Counter()
    })

    for grid_type, experiments in plot_data.items():
        for exp_name, runs in experiments.items():
            for entry in runs:
                req_tp = entry.get("transmit_throughput")
                sch_tp = entry.get("scheduled_throughput")

                if req_tp is None or sch_tp is None:
                    continue

                bucket = round(sch_tp, -5)
                stats = sch_vs_req_tp[bucket]

                stats["total"] += 1
                stats["trans_counts"][req_tp] += 1

                if req_tp == bucket:
                    stats["match"] += 1
                else:
                    stats["mismatch"] += 1

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
                        "start_ns": start_ns,
                        "stop_ns": stop_ns
                    })

            starts_s, stops_s = convert_ns_to_s_list_numstreams(starts_ns, stops_ns)

            for i, s in enumerate(streams):
                s.pop("start_ns")
                s.pop("stop_ns")
                s["start_s"] = starts_s[i]
                s["stop_s"] = stops_s[i]

            streams = add_active_stream_count(streams)

            for s in streams:
                entry = s["entry"]
                entry["num_streams"] = s["active_streams"]

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
        name, _ = results
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

    constant_vars = {}
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
                all_same = all(entry.get(key) == first_value for entry in entries[1:])
                if all_same:
                    constants[key] = first_value

            constant_vars[(grid_type, exp_name)] = constants

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
        same_everywhere = all(consts[key] == first_value for consts in constant_vars.values())
        if same_everywhere:
            global_constants[key] = first_value

    hidden = {v["name"] for v in variable_map if v.get("hide_from_title")}
    constant_names = list(global_constants.keys())
    constant_display_labels, _, scales_for_constants, _ = axis_units(axis_names=constant_names, variable_map=variable_map)
    if verbosity:
        print(global_constants)

    constant_labels = []
    for display_label, scale, name in zip(constant_display_labels, scales_for_constants, constant_names):
        if name in hidden:
            continue
        value = global_constants[name] * scale
        constant_labels.append(f"{display_label}: {value:.2f}")

    count = 0
    if verbosity:
        print(" Files NOT used | Because entail values of None".center(WIDTH, "_"))

    for grid_type, experiments in filtered_plot_data.items():
        req_client_local = req_client_grids[grid_type]
        req_server_local = req_server_grids[grid_type]

        for exp_name, runs in experiments.items():
            for entry in runs:
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
                        client_server.append(f"{entry['client']}-{entry['server']}")
                        axis_values.append({
                            "x_axis": x_value,
                            "y_axis": y_value,
                            "hue": hue_value
                        })
                    else:
                        if verbosity:
                            print(f"Name: {exp_name} | Stream {entry['client']}-{entry['server']} Num: {entry['num']} | Mesh Grid Type {grid_type} with {entry['mesh_size']} Nodes | X: {x_value} | Y: {y_value}")

    print(f"Found {count} entries matching filters and stream selection")

    if verbosity:
        print("=" * WIDTH)
        for sch_tp, stats in sorted(sch_vs_req_tp.items()):
            total = stats["total"]
            match_pct = (stats["match"] / total * 100) if total else 0

            print("\n" + "-" * 50)
            print(f"Scheduled TP: {sch_tp}")
            print(f"Total samples : {total}")
            print(f"Match rate    : {match_pct:.2f}%")
            print(f"Match         : {stats['match']}")
            print(f"Mismatch      : {stats['mismatch']}")
            print("Transmit distribution:")
            for req_tp, cnt in sorted(stats["trans_counts"].items(), reverse=True):
                print(f"   {req_tp:<10} -> {cnt}")

        for grid_type in req_client_grids:
            req_c = req_client_grids[grid_type]
            req_s = req_server_grids[grid_type]
            full = full_grids[grid_type]

            stream, stream_file_name = resolve_stream(req_c, req_s, full, grid_type)
            print(f" Creating Plots | {stream} ".center(WIDTH, "_"))

    percentile_metrics = [v["name"] for v in variable_map if v.get("uses_percentile")]

    base_name = Path(input_paths[0]).name

    axis_labels, _, unit_scales, log_scales = axis_units(axis_names=axis_names, variable_map=variable_map, percentile=percentile)
    axis_keys = ["x_axis", "y_axis"]
    scaled_values = []

    for key, scale in zip(axis_keys, unit_scales):
        values = np.array([entry[key] for entry in axis_values])
        scaled_values.append(np.round(values * scale, 10))

    scaled_x_values, scaled_y_values = scaled_values

    hue_scale = unit_scales[2] if len(unit_scales) > 2 else 1
    scaled_hue_values = [
        round(e["hue"] * hue_scale, 10) if e["hue"] is not None else None
        for e in axis_values
    ]

    violin_df = pd.DataFrame({
        "x": scaled_x_values,
        "y": scaled_y_values,
        "hue": scaled_hue_values
    })

    axis_labels_for_naming = [label.replace(" ", "_") for label in axis_labels]

    plot_file_name = plot_naming(axis_names=axis_names,
                                 percentile_metrics=percentile_metrics,
                                 percentile=percentile,
                                 file_name=base_name,
                                 global_constants=global_constants)

    plot_title, plot_under_title = plot_titling(stream=stream,
                                                axis_names=axis_labels_for_naming,
                                                percentile_metrics=percentile_metrics,
                                                percentile=percentile,
                                                constants=constant_labels)

    log_x = log_scales[0] if len(log_scales) > 0 else False
    log_y = log_scales[1] if len(log_scales) > 1 else False
    hue_legend = textwrap.fill(axis_labels[2], width=14) if len(axis_labels) > 2 else None

    if do_scatter:
        plot_graph(
            x_axis=scaled_x_values,
            y_axis=scaled_y_values,
            axis_labels=axis_labels,
            hue=(
                scaled_hue_values
                if any(v is not None for v in scaled_hue_values)
                else None
            ),
            hue_label=hue_legend,
            fontsize=FONT_SIZE,
            picture_size=(16, 9),
            file_path=output_path / "data_points",
            titlename=custom_title or plot_title,
            sub_title=plot_under_title,
            file_name=f"{plot_file_name}.png",
            log_scale_x=log_x,
            log_scale_y=log_y,
            theory_hops=theory_hops,
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
        for x, y in zip(scaled_x_values, scaled_y_values):
            box_data[x].append(y)

    if do_box:
        plot_boxplot(
            df=violin_df,
            axis_labels=axis_labels,
            fontsize=FONT_SIZE,
            picture_size=(16, 9),
            file_path=output_path / "boxplot",
            file_name=f"{plot_file_name}.png",
            titlename=custom_title or plot_title,
            sub_title=plot_under_title,
            log_scale_y=log_y,
            hue_label=hue_legend,
        )

    if do_violin:
        plot_violin(
            violin_df=violin_df,
            axis_labels=axis_labels,
            titlename=custom_title or plot_title,
            fontsize=FONT_SIZE,
            picture_size=(16, 9),
            file_path=output_path / "violin",
            file_name=f"{plot_file_name}.png",
            sub_title=plot_under_title,
            log_scale_y=log_y,
            hue_label=hue_legend,
            theory_hops=theory_hops,
        )
    if verbosity:
        for name in percentile_metrics:
            if name in axis_names:
                print(f"\nPercentile Setting does matter for parameters '{name}'")

        if len(req_client_grids) >= 2:
            print("\nWARNING: Graphs used don't have same structure")
            print("Specifically you have")
            for grid_type in full_grids:
                full_grid = full_grids[grid_type]
                print(f"Grid Type: {grid_type}")
                print("Full Grid initials:")
                print(full_grid)
                print("-" * WIDTH)
