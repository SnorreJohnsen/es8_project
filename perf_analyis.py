import argparse
from pathlib import Path
import json
from typing import Tuple, Optional, Dict, Any

WIDTH = 80

def sorting_data_nsperf(file_data: Path,
                        percentile: str,
                        interval_step: float = None,) -> Tuple[list, str]:
    # For full NSPERF file, interval not set
    results = []
    flow_id = file_data.get("flow_id")

    # FULL file mode (no intervals)
    if interval_step is None:
        rates = file_data.get("rates")
        timing = file_data.get("timing")
        host_latency = timing.get("host_local_latency_estimate_ns").get(percentile)

        results = {"host latency": host_latency }

        #results = rates

    else: 
        windows = file_data.get("intervals", {}).get("windows", [])

        for window in windows:
            end_time = window.get("end_s")
            start_time = window.get("start_s")
            host_latency= window.get("delivery_for_send_window",{}).get("host_local_latency_estimate_ns",{}).get(percentile)

            results.append({
                "start": start_time,
                "end": end_time,
                "host latency": host_latency
            })
    
    return results,flow_id

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

    intervals = data.get("intervals")
    if intervals:
        print("Intervals found")
    else:
        print("Intervals not found")
    
    print("=" * WIDTH, "\n")
    return intervals, data

def percentile_refactor(percentile: float) -> str:
    if not (0 <= percentile <= 100):
        raise argparse.ArgumentTypeError("Percentile must be between 0 and 100")
    
    if percentile <= 1:
        prc_percentile = percentile
        percentile = percentile * 100
        print(f"\nWrong Formatting {prc_percentile}, expect in range above 1 to 100, therefore set to {percentile}")

    allowed = [50, 95, 99]
    closest = min(allowed, key=lambda x: abs(x - percentile))
    if closest != percentile:
        print(f"\nThe ONLY possible percentiles: {allowed} | {percentile} Therefore changed to {closest} \n")
    if closest == 50:
        return "mean_ns"
    else:
        return f"p{closest}_ns"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tool for analysing the NSPERF/IPERF streams from the graphs')
    parser.add_argument('-i','--input',type=json_path,required=True,help='The desired directory or file which is be performed analysis on (Json Format IPERF/NSPERF)')
    parser.add_argument('-p','--percentile',type=float,required=True,help='What data is of interest for the analysis mean,95\% 99\% percentile (Json Format IPERF/NSPERF)')
    args = parser.parse_args()

    json_files = get_json_files(args.input)
    percentile = percentile_refactor(args.percentile)
    print(f"{percentile=}")

    title = " Files used for analysis "
    print(title.center(WIDTH, "-"))
    for f in json_files:
        print(f)
    print("-" * WIDTH)

    for f in json_files:
        interval_step, json_file_data= nsperf_interval_set(file=f)
        data,flow_id = sorting_data_nsperf(file_data=json_file_data,interval_step=interval_step,percentile=percentile)
        file_text = f" Extracted data from file \'{f}\' with ID {flow_id} "
        print(file_text.center(WIDTH, "-"))
        print(data)
