#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


IP_SUFFIX = "_ip.txt"
TC_SUFFIX = "_tc.txt"
SYSFS_SUFFIX = "_sysfs.json"

IP_FIELD_PREFIXES = {
    "RX": "rx",
    "TX": "tx",
}

TC_COUNTERS = [
    "sent_bytes",
    "sent_packets",
    "dropped",
    "overlimits",
    "requeues",
    "backlog_bytes",
    "backlog_packets",
    "backlog_requeues",
]

TC_SENT_RE = re.compile(
    r"\bSent\s+(\d+)\s+bytes\s+(\d+)\s+pkt"
    r"\s+\(dropped\s+(\d+),\s+overlimits\s+(\d+)\s+requeues\s+(\d+)\)",
    re.IGNORECASE,
)
TC_BACKLOG_RE = re.compile(
    r"\bbacklog\s+(\S+)\s+(\d+)p\s+requeues\s+(\d+)",
    re.IGNORECASE,
)

INTERFACE_TYPE_ORDER = [
    "batman_hardif",
    "batman_mesh_iface",
    "bridge_lan",
    "adapter_lan",
    "device_lan",
    "switch_mesh_link",
    "switch_node_downlink",
    "switch_node_bridge",
    "other",
]

SUMMARY_METRICS = [
    ("ip_rx_bytes_avg", "ip", "rx_bytes"),
    ("ip_tx_bytes_avg", "ip", "tx_bytes"),
    ("ip_rx_packets_avg", "ip", "rx_packets"),
    ("ip_tx_packets_avg", "ip", "tx_packets"),
    ("ip_rx_dropped_avg", "ip", "rx_dropped"),
    ("ip_tx_dropped_avg", "ip", "tx_dropped"),
    ("tc_sent_bytes_avg", "tc", "sent_bytes"),
    ("tc_sent_packets_avg", "tc", "sent_packets"),
    ("tc_dropped_avg", "tc", "dropped"),
]

SUMMARY_FIELDS = ["interface_type", "interface_count"] + [
    metric[0] for metric in SUMMARY_METRICS
]

INTERFACE_TYPE_LABELS = {
    "batman_hardif": "Bat Uplink",
    "batman_mesh_iface": "BATMAN Mesh",
    "bridge_lan": "Bridge LAN",
    "adapter_lan": "Adapter LAN",
    "device_lan": "Device LAN",
    "switch_mesh_link": "Mesh Link",
    "switch_node_downlink": "Node Downlink",
    "switch_node_bridge": "Node Bridge",
    "other": "Other",
}

LATEX_TABLE_ROWS = [
    "batman_hardif",
    "switch_mesh_link",
    "device_lan",
]

LATEX_TABLE_COLUMNS = [
    "interface_type",
    "interface_count",
    "ip_rx_packets_avg",
    "ip_tx_packets_avg",
    "ip_rx_dropped_avg",
    "ip_tx_dropped_avg",
    "tc_dropped_avg",
]

LATEX_COLUMN_LABELS = {
    "interface_type": "Interface",
    "interface_count": "Count",
    "ip_rx_packets_avg": "RX",
    "ip_tx_packets_avg": "TX",
    "ip_rx_dropped_avg": "RX",
    "ip_tx_dropped_avg": "TX",
    "tc_dropped_avg": "Dropped",
}

LATEX_COLUMN_GROUP_LABELS = {
    "ip_packets": "IP Packets Avg",
    "ip_dropped": "IP Dropped Avg",
    "tc_dropped": "TC Avg",
}

LATEX_HEADER_TOP_ROW = [
    ("interface_type", 1, None),
    ("interface_count", 1, None),
    ("ip_packets", 2, "|c|"),
    ("ip_dropped", 2, "|c|"),
    ("tc_dropped", 1, None),
]

LATEX_HEADER_SUB_ROW = [
    "",
    "",
    "ip_rx_packets_avg",
    "ip_tx_packets_avg",
    "ip_rx_dropped_avg",
    "ip_tx_dropped_avg",
    "tc_dropped_avg",
]

LATEX_COLUMN_SPEC = "l | r | r r | r r | r"

LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write("\n")


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def latex_escape(value: Any) -> str:
    return "".join(LATEX_SPECIAL_CHARS.get(char, char) for char in str(value))


def latex_bold(value: Any) -> str:
    return f"\\textbf{{{latex_escape(value)}}}"


def latex_header_label(key: str) -> str:
    label = LATEX_COLUMN_GROUP_LABELS.get(key, LATEX_COLUMN_LABELS.get(key, key))
    return latex_bold(label)


def latex_top_header_cells() -> list[str]:
    cells = []
    for key, span, alignment in LATEX_HEADER_TOP_ROW:
        label = latex_header_label(key)
        if span == 1:
            cells.append(label)
            continue
        cells.append(f"\\multicolumn{{{span}}}{{{alignment or 'c'}}}{{{label}}}")
    return cells


def latex_sub_header_cells() -> list[str]:
    cells = []
    for key in LATEX_HEADER_SUB_ROW:
        cells.append(latex_header_label(key) if key else "")
    return cells


def latex_summary_value(field: str, row: dict[str, Any]) -> str:
    if field == "interface_type":
        interface_type = str(row.get(field, "other"))
        return latex_escape(INTERFACE_TYPE_LABELS.get(interface_type, interface_type))
    if field == "interface_count":
        return str(int(row.get(field, 0)))
    return f"{float(row.get(field, 0)):.0f}"


def write_latex_table(path: Path, rows: list[dict[str, Any]]) -> None:
    rows_by_type = {str(row.get("interface_type")): row for row in rows}
    output = [
        f"\\begin{{tabular}}{{{LATEX_COLUMN_SPEC}}}",
        "\\rowcolor{gray!30}",
        " & ".join(latex_top_header_cells()) + r" \\",
        "\\rowcolor{gray!30}",
        " & ".join(latex_sub_header_cells()) + r" \\",
        "\\midrule",
    ]

    body_rows = [
        rows_by_type[interface_type_name]
        for interface_type_name in LATEX_TABLE_ROWS
        if interface_type_name in rows_by_type
    ]
    for index, row in enumerate(body_rows):
        if index % 2 == 1:
            output.append(r"\rowcolor{gray!10}")
        output.append(
            " & ".join(latex_summary_value(field, row) for field in LATEX_TABLE_COLUMNS)
            + r" \\"
        )

    output.extend([r"\bottomrule", r"\end{tabular}"])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def snapshot_stdout(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""

    marker = "\nstdout:\n"
    marker_index = text.find(marker)
    if marker_index == -1:
        return text

    stdout = text[marker_index + len(marker):]
    stderr_marker = "\nstderr:\n"
    stderr_index = stdout.find(stderr_marker)
    if stderr_index != -1:
        stdout = stdout[:stderr_index]

    return stdout


def parse_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def parse_ip_stats(stdout: str) -> dict[str, int]:
    stats: dict[str, int] = {}
    lines = stdout.splitlines()

    for index, line in enumerate(lines):
        stripped = line.strip()
        label = stripped[:2]
        if label not in IP_FIELD_PREFIXES or not stripped.startswith(f"{label}:"):
            continue

        headers = stripped[len(label) + 1:].split()
        values_index = index + 1
        if not headers:
            if values_index >= len(lines):
                continue
            headers = lines[values_index].split()
            values_index += 1

        if values_index >= len(lines):
            continue

        values = lines[values_index].split()
        prefix = IP_FIELD_PREFIXES[label]
        for header, value in zip(headers, values):
            parsed = parse_int(value)
            if parsed is None:
                continue
            stats[f"{prefix}_{header}"] = parsed

    return stats


def parse_tc_size(value: str) -> int:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]*)", value)
    if match is None:
        return 0

    number = float(match.group(1))
    unit = match.group(2).lower()
    multipliers = {
        "": 1,
        "b": 1,
        "k": 1_000,
        "kb": 1_000,
        "m": 1_000_000,
        "mb": 1_000_000,
        "g": 1_000_000_000,
        "gb": 1_000_000_000,
    }
    multiplier = multipliers.get(unit)
    if multiplier is None:
        return 0

    return int(number * multiplier)


def empty_tc_stats() -> dict[str, int]:
    return {key: 0 for key in TC_COUNTERS}


def parse_tc_stats(stdout: str) -> dict[str, int]:
    stats = empty_tc_stats()

    for match in TC_SENT_RE.finditer(stdout):
        sent_bytes, sent_packets, dropped, overlimits, requeues = match.groups()
        stats["sent_bytes"] += int(sent_bytes)
        stats["sent_packets"] += int(sent_packets)
        stats["dropped"] += int(dropped)
        stats["overlimits"] += int(overlimits)
        stats["requeues"] += int(requeues)

    for match in TC_BACKLOG_RE.finditer(stdout):
        backlog_bytes, backlog_packets, backlog_requeues = match.groups()
        stats["backlog_bytes"] += parse_tc_size(backlog_bytes)
        stats["backlog_packets"] += int(backlog_packets)
        stats["backlog_requeues"] += int(backlog_requeues)

    return stats


def load_sysfs_stats(path: Path) -> dict[str, int]:
    try:
        raw = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    stats = {}
    for key, value in raw.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            stats[str(key)] = value
    return stats


def delta(before: dict[str, int], after: dict[str, int],
          keys: list[str] | None = None) -> dict[str, int]:
    if keys is None:
        keys = sorted(set(before) & set(after))
    return {key: after[key] - before[key] for key in keys if key in before and key in after}


def interface_names(ns_dir: Path) -> set[str]:
    names = set()
    if not ns_dir.is_dir():
        return names

    for path in ns_dir.iterdir():
        name = path.name
        for suffix in [IP_SUFFIX, TC_SUFFIX, SYSFS_SUFFIX]:
            if name.endswith(suffix):
                names.add(name[:-len(suffix)])
                break

    return names


def namespace_names(snapshot_dir: Path) -> set[str]:
    if not snapshot_dir.is_dir():
        return set()
    return {path.name for path in snapshot_dir.iterdir() if path.is_dir()}


def resolve_net_stats_dir(path: Path) -> Path:
    if (path / "before").is_dir() or (path / "after").is_dir():
        return path
    return path / "net_stats"


def analyze_interface(before_dir: Path, after_dir: Path, ifname: str) -> dict[str, dict[str, int]]:
    before_ip = parse_ip_stats(snapshot_stdout(before_dir / f"{ifname}{IP_SUFFIX}"))
    after_ip = parse_ip_stats(snapshot_stdout(after_dir / f"{ifname}{IP_SUFFIX}"))

    before_sysfs = load_sysfs_stats(before_dir / f"{ifname}{SYSFS_SUFFIX}")
    after_sysfs = load_sysfs_stats(after_dir / f"{ifname}{SYSFS_SUFFIX}")

    before_tc = parse_tc_stats(snapshot_stdout(before_dir / f"{ifname}{TC_SUFFIX}"))
    after_tc = parse_tc_stats(snapshot_stdout(after_dir / f"{ifname}{TC_SUFFIX}"))

    return {
        "ip": delta(before_ip, after_ip),
        "sysfs": delta(before_sysfs, after_sysfs),
        "tc": delta(before_tc, after_tc, TC_COUNTERS),
    }


def analyze_net_stats(emulation_dir: Path) -> dict[str, dict[str, dict[str, dict[str, int]]]]:
    net_stats_dir = resolve_net_stats_dir(emulation_dir)
    before_root = net_stats_dir / "before"
    after_root = net_stats_dir / "after"

    if not before_root.is_dir():
        raise FileNotFoundError(f"Missing before snapshot directory: {before_root}")
    if not after_root.is_dir():
        raise FileNotFoundError(f"Missing after snapshot directory: {after_root}")

    details = {}
    for namespace in sorted(namespace_names(before_root) & namespace_names(after_root)):
        before_ns_dir = before_root / namespace
        after_ns_dir = after_root / namespace
        interfaces = sorted(interface_names(before_ns_dir) & interface_names(after_ns_dir))
        if not interfaces:
            continue

        details[namespace] = {}
        for ifname in interfaces:
            details[namespace][ifname] = analyze_interface(before_ns_dir, after_ns_dir, ifname)

    return details


def details_tree_paths(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("details.json")
        if path.parent.name == "net_stats"
    )


def empty_summary_groups() -> dict[str, dict[str, Any]]:
    return {
        interface_type: {
            "interface_count": 0,
            **{field: 0 for field, _, _ in SUMMARY_METRICS},
        }
        for interface_type in INTERFACE_TYPE_ORDER
    }


def add_details_to_summary_groups(
    grouped: dict[str, dict[str, Any]],
    details: dict[str, dict[str, dict[str, dict[str, int]]]],
) -> None:
    for namespace, interfaces in details.items():
        if not isinstance(interfaces, dict):
            continue
        for ifname, data in interfaces.items():
            if not isinstance(data, dict):
                continue
            group = grouped[interface_type(namespace, ifname)]
            group["interface_count"] += 1
            for field, section, metric in SUMMARY_METRICS:
                section_data = data.get(section, {})
                if not isinstance(section_data, dict):
                    continue
                value = section_data.get(metric, 0)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                group[field] += value


def summary_rows_from_groups(grouped: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for interface_type_name in INTERFACE_TYPE_ORDER:
        group = grouped[interface_type_name]
        interface_count = group["interface_count"]
        if interface_count == 0:
            continue

        row: dict[str, Any] = {
            "interface_type": interface_type_name,
            "interface_count": interface_count,
        }
        for field, _, _ in SUMMARY_METRICS:
            row[field] = group[field] / interface_count
        rows.append(row)

    return rows


def load_details(path: Path) -> dict[str, dict[str, dict[str, dict[str, int]]]]:
    details = load_json(path)
    if not isinstance(details, dict):
        raise ValueError(f"Expected object in details file: {path}")
    return details


def summarize_details_tree(root: Path) -> list[dict[str, Any]]:
    details_paths = details_tree_paths(root)
    if not details_paths:
        raise FileNotFoundError(f"No net_stats/details.json files found below: {root}")

    grouped = empty_summary_groups()
    for path in details_paths:
        add_details_to_summary_groups(grouped, load_details(path))
    return summary_rows_from_groups(grouped)


def interface_type(namespace: str, ifname: str) -> str:
    if ifname == "uplink":
        return "batman_hardif"
    if ifname.startswith("bat"):
        return "batman_mesh_iface"
    if namespace.startswith("ns-a") and ifname == "br-lan":
        return "bridge_lan"
    if namespace.startswith("ns-a") and ifname == "lan0":
        return "adapter_lan"
    if namespace.startswith("ns-d") and ifname == "veth0":
        return "device_lan"
    if namespace == "switch" and ifname.startswith("ve-"):
        return "switch_mesh_link"
    if namespace == "switch" and ifname.startswith("dl-"):
        return "switch_node_downlink"
    if namespace == "switch" and ifname.startswith("br-"):
        return "switch_node_bridge"
    return "other"


def summarize_by_interface_type(
    details: dict[str, dict[str, dict[str, dict[str, int]]]],
) -> list[dict[str, Any]]:
    grouped = empty_summary_groups()
    add_details_to_summary_groups(grouped, details)
    return summary_rows_from_groups(grouped)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute deltas from emulation net_stats before/after snapshots.",
    )
    parser.add_argument("emulation_dir", type=Path, help="Emulation output directory, net_stats directory, or details tree")
    parser.add_argument(
        "--details-tree",
        action="store_true",
        help="Aggregate recursively from */net_stats/details.json files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path, defaults to <emulation_dir>/net_stats/details.json",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="Output CSV path, defaults to <emulation_dir>/net_stats/summary.csv",
    )
    parser.add_argument(
        "--latex-output",
        type=Path,
        help="Output LaTeX tabular path, defaults to <emulation_dir>/net_stats/net_stats_table.tex",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    emulation_dir = args.emulation_dir.expanduser().resolve()

    if args.details_tree:
        if args.output is not None:
            raise SystemExit("ERROR: --output is not supported with --details-tree")
        summary_output = args.summary_output or emulation_dir / "net_stats_summary.csv"
        latex_output = args.latex_output or emulation_dir / "net_stats_table.tex"
        try:
            summary_rows = summarize_details_tree(emulation_dir)
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(f"ERROR: {exc}") from exc
        write_summary_csv(summary_output, summary_rows)
        write_latex_table(latex_output, summary_rows)
        return

    net_stats_dir = resolve_net_stats_dir(emulation_dir)
    output = args.output or net_stats_dir / "details.json"
    summary_output = args.summary_output or net_stats_dir / "summary.csv"
    latex_output = args.latex_output or net_stats_dir / "net_stats_table.tex"

    try:
        details = analyze_net_stats(emulation_dir)
    except FileNotFoundError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    summary_rows = summarize_by_interface_type(details)
    write_json(output, details)
    write_summary_csv(summary_output, summary_rows)
    write_latex_table(latex_output, summary_rows)


if __name__ == "__main__":
    main()
