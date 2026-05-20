import subprocess
import sys
from pathlib import Path
from tqdm import tqdm

# ── Output root ───────────────────────────────────────────────────────────────
OUTPUT_ROOT = Path("./test_output")

# ── Input directories to analyse ─────────────────────────────────────────────
INPUT_DIRS = [
    Path(r"C:\Repositeries\ES8-Semester\Project-ES8\nsperf_stress_1000startdelay"),
    Path(r"C:\Repositeries\ES8-Semester\Project-ES8\nsperf_stress_flyvfart"),
]

# ── Plot specifications ───────────────────────────────────────────────────────
# Each entry produces one plot run per input directory.
#
# Required keys : percentile, x, y
# Optional keys : hue, client, server, filters (dict of variable=value)
#
# Available variables: link_loss, throughput, latency, jitter, num_streams,
#                      transmit_throughput, scheduled_throughput,
#                      loss_vs_transmit, loss_vs_scheduled,
#                      scheduled_vs_transmit_loss, mesh_size

PLOT_SPECS = [
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_transmit",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "100K"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_transmit",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "500K"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_transmit",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "1M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_transmit",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "2M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_transmit",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "5M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_scheduled",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "100K"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_scheduled",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "500K"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_scheduled",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "1M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_scheduled",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "2M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_scheduled",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "5M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "scheduled_vs_transmit_loss",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "100K"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "scheduled_vs_transmit_loss",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "500K"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "scheduled_vs_transmit_loss",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "1M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "scheduled_vs_transmit_loss",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "2M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "scheduled_vs_transmit_loss",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "5M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "throughput",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "100K"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "throughput",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "500K"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "throughput",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "1M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "throughput",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "2M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "throughput",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "5M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "latency",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "100K"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "latency",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "500K"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "latency",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "1M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "latency",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "2M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "latency",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "5M"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "latency",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "100K"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "latency",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "500K"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "latency",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "1M"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "latency",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "2M"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "latency",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "5M"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "jitter",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "100K"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "jitter",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "500K"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "jitter",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "1M"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "jitter",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "2M"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "jitter",
        "hue": "meshsize",
        "filters": {"scheduled_throughput": "5M"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_transmit",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "18"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_transmit",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "27"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_transmit",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "38"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_transmit",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "46"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_scheduled",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "18"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_scheduled",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "27"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_scheduled",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "38"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "loss_vs_scheduled",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "46"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "scheduled_vs_transmit_loss",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "18"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "scheduled_vs_transmit_loss",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "27"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "scheduled_vs_transmit_loss",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "38"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "scheduled_vs_transmit_loss",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "46"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "throughput",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "18"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "throughput",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "27"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "throughput",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "38"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "throughput",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "46"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "latency",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "18"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "latency",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "27"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "latency",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "38"},
    },
    {
        "percentile": "95",
        "x": "num_streams",
        "y": "latency",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "46"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "latency",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "18"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "latency",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "27"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "latency",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "38"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "latency",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "46"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "jitter",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "18"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "jitter",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "27"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "jitter",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "38"},
    },
    {
        "percentile": "mean",
        "x": "num_streams",
        "y": "jitter",
        "hue": "scheduled_throughput",
        "filters": {"mesh_size": "46"},
    },
]

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
