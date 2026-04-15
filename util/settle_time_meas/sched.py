from dataclasses import dataclass, asdict
from enum import Enum
import os
import json
import shutil
from pydantic import BaseModel
from pydantic_core import to_json

class State(str, Enum):
    RECHARGING = "RECHARGING"
    FLYING_UP = "FLYING_UP"
    UP = "UP"
    FLYING_DOWN = "FLYING_DOWN"
    DOWN = "DOWN"

class DropoutEvent(BaseModel):
    name: str
    state: State

# Simulation schedule types
class IperfEvent(BaseModel):
    client_name: str
    server_name: str
    bitrate: str # 4M or 3K for example
    udp: bool
    duration: int

SchedEventType = DropoutEvent | IperfEvent # cooked that this is called *Type and the others aren't. maybe none of them are called that...

class SchedEntry(BaseModel):
    time: float
    event: SchedEventType

class Sim(BaseModel):
    start_timestamp: float
    duration: float
    sched_plan: list[SchedEntry]
    sched_real: list[SchedEntry]

def sched(node: str, uptime: float, downtime: float, duration: float) -> Sim:
    sched = [
            SchedEntry(time=downtime, event=DropoutEvent(name=node, state=State.DOWN)),
            SchedEntry(time=uptime, event=DropoutEvent(name=node, state=State.UP)),
            ]

    return Sim(
        start_timestamp=0, #ignored when loading sim
        duration=duration,
        sched_plan=sched,
        sched_real=[])

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("graph", help="Network json graph")
    ap.add_argument("outdir", help="Output directory for simulation schedules")
    ap.add_argument("--down-time", default=0, help="When to bring node down")
    ap.add_argument("--up-time", default=10, help="When to bring node up")
    ap.add_argument("--duration", default=30, help="Simulation duration")
    args = ap.parse_args()

    # Load mesh json
    if not os.path.isfile(args.graph):
        raise FileNotFoundError(f'File not found: {args.graph}')
    with open(args.graph) as f:
        graph = json.load(f)

    # Set up output dir
    try:
        shutil.rmtree(args.outdir)
    except FileNotFoundError as e:
        pass
    os.makedirs(args.outdir)

    # Generate schedules
    for node in graph["nodes"]:
        node = node["id"]
        sim = sched(node, args.up_time, args.down_time, args.duration)
        outpath = os.path.join(args.outdir, f"drop_{node}.json")
        with open(outpath, "wb") as f:
            f.write(to_json(sim))
