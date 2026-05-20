import subprocess
import sys
from pathlib import Path
from tqdm import tqdm

# ── Output root ───────────────────────────────────────────────────────────────
OUTPUT_ROOT = Path("./test_output_stress_beast")

# ── Input directories to analyse ─────────────────────────────────────────────
INPUT_DIRS = [
    #Path(r"C:\Repositeries\ES8-Semester\Project-ES8\nsperf_stress_1000startdelay"),
    Path(r"C:\Repositeries\ES8-Semester\Project-ES8\stress_beast"),
    #Path(r"C:\Repositeries\ES8-Semester\Project-ES8\nsperf_stress_flyvfart"),
]

# ── Axis / filter values to sweep over ───────────────────────────────────────
#SCHEDULED_THROUGHPUTS = ["100K", "500K", "1M", "2M", "5M"]
SCHEDULED_THROUGHPUTS = ["1M", "2M", "5M"]
MESH_SIZES            = ["18", "27", "38", "46"]

# (y_variable, percentile) pairs to generate for each sweep
Y_SPECS = [
    ("loss_vs_transmit",          "95"),
    ("loss_vs_scheduled",         "95"),
    ("scheduled_vs_transmit_loss","95"),
    ("throughput",                "95"),
    ("latency",                   "95"),
    ("latency",                   "mean"),
    ("jitter",                    "mean"),
]

# ── Plot specifications (auto-generated) ──────────────────────────────────────
PLOT_SPECS = []

for y, perc in Y_SPECS:
    for sch_tp in SCHEDULED_THROUGHPUTS:
        PLOT_SPECS.append({
            "percentile": perc,
            "x": "num_streams",
            "y": y,
            "hue": "meshsize",
            "filters": {"scheduled_throughput": sch_tp},
        })

for y, perc in Y_SPECS:
    for ms in MESH_SIZES:
        PLOT_SPECS.append({
            "percentile": perc,
            "x": "num_streams",
            "y": y,
            "hue": "scheduled_throughput",
            "filters": {"mesh_size": ms},
        })

# ── Optional global flags ─────────────────────────────────────────────────────
VERBOSE = False

# ─────────────────────────────────────────────────────────────────────────────

SCRIPT = Path(__file__).parent / "perf_analyis.py"


def build_cmd(input_dir: Path, output_dir: Path, spec: dict) -> list[str]:
    cmd = [
        sys.executable, str(SCRIPT),
        "-i", str(input_dir),
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


def run_spec(input_dir: Path, spec: dict, idx: int, total: int):
    hue = spec.get("hue")
    hue_folder = hue if hue else "no_hue"
    filter_folder = _filter_subfolder(spec)
    output_dir = OUTPUT_ROOT / input_dir.name / hue_folder / filter_folder
    output_dir.mkdir(parents=True, exist_ok=True)

    label = spec_label(spec)
    print(f"\n[{idx}/{total}]  {input_dir.name}")
    print(f"         {label}")
    print(f"         → {output_dir}")

    cmd = build_cmd(input_dir, output_dir, spec)
    result = subprocess.run(cmd, text=True)

    if result.returncode != 0:
        print(f"         [FAILED]")
        return False

    print(f"         [OK]")
    return True


if __name__ == "__main__":
    valid_dirs = [d for d in INPUT_DIRS if d.exists()]
    skipped = [d for d in INPUT_DIRS if not d.exists()]

    if skipped:
        for d in skipped:
            print(f"[SKIP] {d} — path does not exist")

    total = len(valid_dirs) * len(PLOT_SPECS)
    print(f"\nRunning {len(PLOT_SPECS)} spec(s) × {len(valid_dirs)} director(y/ies) = {total} total runs")
    print(f"Output root: {OUTPUT_ROOT.resolve()}\n")

    failures = 0
    runs = [(d, s) for d in valid_dirs for s in PLOT_SPECS]

    with tqdm(runs, desc="Runs", unit="plot", dynamic_ncols=True) as bar:
        for idx, (input_dir, spec) in enumerate(bar, 1):
            hue = spec.get("hue", "")
            bar.set_postfix_str(f"{input_dir.name} | {spec['x']} vs {spec['y']} | hue={hue}")
            ok = run_spec(input_dir, spec, idx, total)
            if not ok:
                failures += 1

    print(f"\n{'─' * 60}")
    print(f"Done.  {total - failures}/{total} runs succeeded.")
    if failures:
        print(f"       {failures} run(s) failed — check output above.")
    print(f"Output in: {OUTPUT_ROOT.resolve()}")
