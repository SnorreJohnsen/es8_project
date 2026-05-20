#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write("\n")


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
    net_stats_dir = emulation_dir / "net_stats"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute deltas from emulation net_stats before/after snapshots.",
    )
    parser.add_argument("emulation_dir", type=Path, help="Emulation output directory")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path, defaults to <emulation_dir>/net_stats/details.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    emulation_dir = args.emulation_dir.expanduser().resolve()
    output = args.output or emulation_dir / "net_stats" / "details.json"

    try:
        details = analyze_net_stats(emulation_dir)
    except FileNotFoundError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    write_json(output, details)


if __name__ == "__main__":
    main()
