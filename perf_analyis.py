import argparse
from pathlib import Path
import json
from typing import Tuple, Optional, Dict, Any

WIDTH = 120

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
                        interval_step: float = None,) -> Tuple[list, str]:
    # For full NSPERF file, interval not set

    flow_id = file_data.get("flow_id")
    run_id = file_data.get("run_id")
    schema = file_data.get("schema")

    ids = {
    "flow_id": flow_id,
    "run_id": run_id,
    "schema": schema
    }

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

        for window in windows[:3]:
            end_time = window.get("end_s")
            start_time = window.get("start_s")
            # not hundred percent sure this how i want to do it yet can get nested results alot then
            # still also need to load in the rest then aswell this only deliveryy for send window
            delivery = extract_percentile_data(dict_name = "delivery_for_send_window",file_data=window,percentile=percentile)

            results = {
                "start": start_time,
                "end": end_time,
                "delivery_for_send_window": delivery
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
    return intervals, data

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tool for analysing the NSPERF/IPERF streams from the graphs')
    parser.add_argument('-i','--input',type=json_path,required=True,help='The desired directory or file which is be performed analysis on (Json Format IPERF/NSPERF)')
    parser.add_argument('-p','--percentile',type=float,required=True,help='What data is of interest for the analysis 0 = mean 50%,95\% 99\% percentile (Json Format IPERF/NSPERF)')
    args = parser.parse_args()

    json_files = get_json_files(args.input)
    percentile = percentile_refactor(args.percentile)
    print(f"{percentile=}")

    title = " Files used for analysis "
    print(title.center(WIDTH, "-"))
    interval_steps = []
    file_data_list = []

    path_width= max(len(str(f)) for f in json_files) + 2

    for f in json_files:
        interval_step, json_file_data = nsperf_interval_set(file=f)

        interval_steps.append(interval_step)
        file_data_list.append(json_file_data)

        print(f"{str(f).ljust(path_width)} | interval: {interval_step}")

    print("-" * WIDTH)

    for i, f in enumerate(json_files):
        data,ids = sorting_data_nsperf(file_data=file_data_list[i],interval_step=interval_steps[i],percentile=percentile)
        file_text = f" Extracted data from file \'{f}\' with ID {ids.get("flow_id")} "
        print(file_text.center(WIDTH, "-"))
        print(data,"\n")
