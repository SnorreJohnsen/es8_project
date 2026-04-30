import argparse
from pathlib import Path
import json
from typing import Tuple, Optional, Dict, Any

WIDTH = 80

def sorting_data_nsperf(file_data: Path,
                        interval_step: float = None) -> list:
    # For full NSPERF file, interval not set
    results = []

    # FULL file mode (no intervals)
    if interval_step is None:
        rates = file_data.get("rates")
        return rates if rates else []

    else: 
        windows = file_data.get("intervals", {}).get("windows", [])

        for window in windows:
            end_time = window.get("end_s")
            start_time = window.get("start_s")

            results.append({
                "start": start_time,
                "end": end_time
            })
    
    return results

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tool for analysing the NSPERF/IPERF streams from the graphs')
    parser.add_argument('-i','--input',type=json_path,required=True,help='The desired directory or file which is be performed analysis on (Json Format IPERF/NSPERF)')
    args = parser.parse_args()

    json_files = get_json_files(args.input)

    title = " Files used for analysis "
    print(title.center(WIDTH, "-"))
    for f in json_files:
        print(f)
    print("-" * WIDTH)

    for f in json_files:
        interval_step, json_file_data= nsperf_interval_set(file=f)
        data = sorting_data_nsperf(file_data=json_file_data,interval_step=interval_step)
        file_text = f" Extracted data from file {f} "
        print(file_text.center(WIDTH, "-"))
        print(data)
