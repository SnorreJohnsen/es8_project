from __future__ import annotations

import re
from collections import defaultdict


LINK_HEADER_RE = re.compile(r"^\d+:\s+([^:]+):")
TC_QDISC_RE = re.compile(r"^qdisc\s+.*?\sdev\s+(\S+)\b")


def normalize_ifname(ifname: str) -> str:
    return ifname.strip().split("@", 1)[0]


def parse_interface_names(link_show_stdout: str) -> list[str]:
    interfaces = []
    seen = set()

    for line in link_show_stdout.splitlines():
        match = LINK_HEADER_RE.match(line)
        if match is None:
            continue

        ifname = normalize_ifname(match.group(1))
        if ifname == "lo" or not ifname or ifname in seen:
            continue

        seen.add(ifname)
        interfaces.append(ifname)

    return interfaces


def split_ip_link_show(link_show_stdout: str) -> dict[str, str]:
    blocks: dict[str, list[str]] = defaultdict(list)
    current_ifname = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_ifname is None or current_ifname == "lo":
            return
        if blocks[current_ifname]:
            blocks[current_ifname].append("")
        blocks[current_ifname].extend(current_lines)

    for line in link_show_stdout.splitlines():
        match = LINK_HEADER_RE.match(line)
        if match is not None:
            flush()
            current_ifname = normalize_ifname(match.group(1))
            current_lines = []
        if current_ifname is not None:
            current_lines.append(line)

    flush()

    return {
        ifname: "\n".join(lines) + ("\n" if lines else "")
        for ifname, lines in blocks.items()
    }


def split_tc_qdisc_show(qdisc_show_stdout: str) -> dict[str, str]:
    blocks: dict[str, list[str]] = defaultdict(list)
    current_ifname = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_ifname is None or current_ifname == "lo":
            return
        if blocks[current_ifname]:
            blocks[current_ifname].append("")
        blocks[current_ifname].extend(current_lines)

    for line in qdisc_show_stdout.splitlines():
        match = TC_QDISC_RE.match(line)
        if match is not None:
            flush()
            current_ifname = normalize_ifname(match.group(1))
            current_lines = []
        if current_ifname is not None:
            current_lines.append(line)

    flush()

    return {
        ifname: "\n".join(lines) + ("\n" if lines else "")
        for ifname, lines in blocks.items()
    }


def parse_sysfs_stats(sysfs_stdout: str) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = defaultdict(dict)

    for line in sysfs_stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) != 3:
            continue

        ifname, stat_name, stat_value = parts
        ifname = normalize_ifname(ifname)
        if ifname == "lo" or not ifname:
            continue

        try:
            stats[ifname][stat_name] = int(stat_value)
        except ValueError:
            continue

    return dict(stats)
