import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from tqdm import tqdm

# ── Output root ───────────────────────────────────────────────────────────────
OUTPUT_ROOT = Path("./test_drop_brother")

# ── Input directories to analyse ─────────────────────────────────────────────
# SCAN_ROOT   : root folder to search under
# SCAN_SUFFIX : only collect dirs whose name ends with this (e.g. "_step")
# GROUP_BY_SUFFIX : if set, group collected dirs by the ancestor folder whose
#                   name ends with this suffix (e.g. "_fail" → one group per
#                   unique fail value, all its step dirs merged into one run).
#                   Set to None to treat each found dir as its own input.
# INPUT_BASE  : strip this prefix when building output subfolder paths.
#               Set to None to just use the dir name.
SCAN_ROOT        = Path(r"C:\Repositeries\ES8-Semester\Project-ES8\drop_final_stripped")
SCAN_SUFFIX      = "_step"
GROUP_BY_SUFFIX  = "_fail"
INPUT_BASE       = Path(r"C:\Repositeries\ES8-Semester\Project-ES8")

def _find_ancestor_part(path: Path, suffix: str) -> str:
    for part in path.parts:
        if part.endswith(suffix):
            return part
    return "ungrouped"

if SCAN_ROOT is not None:
    print(f"Scanning {SCAN_ROOT} for *{SCAN_SUFFIX} dirs...")
    _all_dirs = list(SCAN_ROOT.rglob("*"))
    _found = sorted(
        p for p in tqdm(_all_dirs, desc="Scanning", unit="dir", dynamic_ncols=True)
        if p.is_dir() and p.name.endswith(SCAN_SUFFIX)
    )
    print(f"  Found {len(_found)} dir(s) ending in '{SCAN_SUFFIX}'")
    if GROUP_BY_SUFFIX is not None:
        _groups: dict[str, list[Path]] = defaultdict(list)
        for p in tqdm(_found, desc=f"Grouping by *{GROUP_BY_SUFFIX}", unit="dir", dynamic_ncols=True):
            _groups[_find_ancestor_part(p, GROUP_BY_SUFFIX)].append(p)
        INPUT_GROUPS = dict(_groups)
    else:
        INPUT_GROUPS = {p.name: [p] for p in _found}
else:
    _manual: list[Path] = [
        #Path(r"C:\Repositeries\ES8-Semester\Project-ES8\nsperf_stress_1000startdelay"),
        #Path(r"C:\Repositeries\ES8-Semester\Project-ES8\stress_beast"),
        #Path(r"C:\Repositeries\ES8-Semester\Project-ES8\stress_beast_1000ms"),
        Path(r"C:\Repositeries\ES8-Semester\nsperf_stress_test_many_streams"),
        #Path(r"C:\Repositeries\ES8-Semester\nsperf_stress_test_dropout"),
        #Path(r"C:\Repositeries\ES8-Semester\Project-ES8\nsperf_stress_flyvfart"),
    ]
    INPUT_GROUPS = {p.name: [p] for p in _manual}

print("Groups found:")
for group_name, dirs in INPUT_GROUPS.items():
    print(f"  {group_name}  ({len(dirs)} dir(s))")
# ── Axis / filter values to sweep over ───────────────────────────────────────
#SCHEDULED_THROUGHPUTS = ["5M"]
#MESH_SIZES            = ["18", "27","38"]
SCHEDULED_THROUGHPUTS = ["1M", "2M", "5M"]
MESH_SIZES            = ["18", "27", "38", "46"]

# (y_variable, percentile, hue) triples
# hue = "meshsize"            → fix scheduled_throughput, sweep over SCHEDULED_THROUGHPUTS
# hue = "scheduled_throughput" → fix mesh_size,           sweep over MESH_SIZES
Y_SPECS = [
    #("loss_vs_transmit",           "95",  "meshsize"),
    ("loss_vs_scheduled",          "95",  "meshsize"),
    #("scheduled_vs_transmit_loss", "95",  "meshsize"),
    ("throughput",                 "95",  "meshsize"),
    ("latency",                    "99",  "scheduled_throughput"),
    ("latency",                    "95",  "scheduled_throughput"),
    #("latency",                    "mean","scheduled_throughput"),
    #("jitter",                     "mean","scheduled_throughput"),
    ("jitter",                     "95",  "scheduled_throughput"),
    ("jitter",                     "99",  "scheduled_throughput"),
]

# ── Plot specifications (auto-generated) ──────────────────────────────────────
PLOT_SPECS = []

for y, perc, hue in Y_SPECS:
    if hue == "meshsize":
        for sch_tp in SCHEDULED_THROUGHPUTS:
            PLOT_SPECS.append({
                "percentile": perc,
                "x": "num_streams",
                "y": y,
                "hue": "meshsize",
                "filters": {"scheduled_throughput": sch_tp},
            })
    elif hue == "scheduled_throughput":# scheduled_throughput
        for ms in MESH_SIZES:
            PLOT_SPECS.append({
                "percentile": perc,
                "x": "num_streams",
                "y": y,
                "hue": "scheduled_throughput",
                "filters": {"mesh_size": ms},
            })

# ── Optional global flags ─────────────────────────────────────────────────────
VERBOSE    = False
PLOT_TYPE  = "violin"   # scatter | box | violin | all  (comma-separated for multiple)
BASE_TITLE = "Drop Test - 5 Iterations"  # prepended to every plot title

# ─────────────────────────────────────────────────────────────────────────────

SCRIPT = Path(__file__).parent / "perf_analyis.py"


def _group_title(group_name: str) -> str:
    """Build a plot title from the group name.

    If the group name ends with GROUP_BY_SUFFIX (e.g. '0.015_fail') the
    failure probability is extracted and rendered as a mathtext subscript:
        Dropout Stress Test  |  P_failure = 0.015
    Otherwise (no grouping / ungrouped dir) just return BASE_TITLE.
    """
    if GROUP_BY_SUFFIX and group_name.endswith(GROUP_BY_SUFFIX):
        fail_val   = group_name[: -len(GROUP_BY_SUFFIX)].rstrip("_")
        fail_label = rf"$p_{{\mathrm{{failure}}}}$ = {fail_val}"
        return f"{BASE_TITLE}  |  {fail_label}"
    return BASE_TITLE


def build_cmd(group_dirs: list[Path], output_dir: Path, spec: dict, group_name: str = "") -> list[str]:
    cmd = [sys.executable, str(SCRIPT)]
    for d in group_dirs:
        cmd += ["-i", str(d)]
    cmd += [
        "-o", str(output_dir),
        "-p", spec["percentile"],
        "-x", spec["x"],
        "-y", spec["y"],
    ]
    if spec.get("hue"):
        cmd += ["--hue", spec["hue"]]
    if spec.get("client"):
        cmd += ["-c", spec["client"]]
    if spec.get("server"):
        cmd += ["-s", spec["server"]]
    for k, v in spec.get("filters", {}).items():
        cmd += ["-f", f"{k}={v}"]
    title = spec.get("title") or (group_name and _group_title(group_name))
    if title:
        cmd += ["--title", title]
    if PLOT_TYPE and PLOT_TYPE != "all":
        cmd += ["--plot-type", PLOT_TYPE]
    if VERBOSE:
        cmd += ["-v"]
    return cmd


def spec_label(spec: dict) -> str:
    label = f"{spec['x']} vs {spec['y']}  |  p{spec['percentile']}"
    if spec.get("hue"):
        label += f"  |  hue={spec['hue']}"
    if spec.get("filters"):
        fixed = "  ".join(f"{k}={v}" for k, v in spec["filters"].items())
        label += f"  |  fixed: {fixed}"
    return label


def _filter_subfolder(spec: dict) -> str:
    filters = spec.get("filters", {})
    if not filters:
        return "no_filter"
    parts = [
        f"{''.join(p[0] for p in k.split('_')).upper()}={v}"
        for k, v in filters.items()
    ]
    return "_".join(parts)


def run_spec(group_name: str, group_dirs: list[Path], spec: dict, idx: int, total: int):
    hue = spec.get("hue") or "no_hue"
    filter_folder = _filter_subfolder(spec)
    output_dir = OUTPUT_ROOT / group_name / hue / filter_folder
    output_dir.mkdir(parents=True, exist_ok=True)

    label = spec_label(spec)
    print(f"\n[{idx}/{total}]  {group_name}  ({len(group_dirs)} dir(s))")
    print(f"         {label}")
    print(f"         → {output_dir}")

    cmd = build_cmd(group_dirs, output_dir, spec, group_name)
    result = subprocess.run(cmd, text=True)

    if result.returncode != 0:
        print(f"         [FAILED]")
        return False

    print(f"         [OK]")
    return True


if __name__ == "__main__":
    valid_groups = {
        name: [d for d in dirs if d.exists()]
        for name, dirs in INPUT_GROUPS.items()
    }
    valid_groups = {name: dirs for name, dirs in valid_groups.items() if dirs}

    total = len(valid_groups) * len(PLOT_SPECS)
    print(f"\nRunning {len(PLOT_SPECS)} spec(s) × {len(valid_groups)} group(s) = {total} total runs")
    print(f"Output root: {OUTPUT_ROOT.resolve()}\n")

    failures = 0
    runs = [(name, dirs, s) for name, dirs in valid_groups.items() for s in PLOT_SPECS]

    with tqdm(runs, desc="Runs", unit="plot", dynamic_ncols=True) as bar:
        for idx, (group_name, group_dirs, spec) in enumerate(bar, 1):
            hue = spec.get("hue", "")
            bar.set_postfix_str(f"{group_name} | {spec['x']} vs {spec['y']} | hue={hue}")
            ok = run_spec(group_name, group_dirs, spec, idx, total)
            if not ok:
                failures += 1

    print(f"\n{'─' * 60}")
    print(f"Done.  {total - failures}/{total} runs succeeded.")
    if failures:
        print(f"       {failures} run(s) failed — check output above.")
    print(f"Output in: {OUTPUT_ROOT.resolve()}")
