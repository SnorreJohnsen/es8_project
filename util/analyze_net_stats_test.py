from __future__ import annotations

import importlib.util
import csv
import json
import tempfile
from pathlib import Path


def load_analyze_module():
    path = Path(__file__).with_name("analyze_net_stats.py")
    spec = importlib.util.spec_from_file_location("analyze_net_stats", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_snapshot(path: Path, stdout: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "timestamp: 2026-05-20T12:00:00+02:00",
                "namespace: ns-n0",
                "interface: uplink",
                "command: test",
                "returncode: 0",
                "",
                "stdout:",
                stdout.rstrip("\n"),
                "",
                "stderr:",
                "",
            ]
        ),
        encoding="utf-8",
    )


def ip_stdout(rx_bytes: int, rx_packets: int, rx_dropped: int,
              tx_bytes: int, tx_packets: int, tx_dropped: int,
              ifname: str = "uplink") -> str:
    return f"""2: {ifname}@if3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    link/ether 02:00:00:00:00:01 brd ff:ff:ff:ff:ff:ff
    RX: bytes  packets  errors  dropped missed  mcast
    {rx_bytes} {rx_packets} 0 {rx_dropped} 0 2
    TX: bytes  packets  errors  dropped carrier collsns
    {tx_bytes} {tx_packets} 1 {tx_dropped} 3 4
"""


def tc_stdout(sent_bytes: int, sent_packets: int, dropped: int,
              overlimits: int, requeues: int, backlog_bytes: int,
              backlog_packets: int, backlog_requeues: int) -> str:
    return f"""qdisc netem 8001: root refcnt 2 limit 1000
 Sent {sent_bytes} bytes {sent_packets} pkt (dropped {dropped}, overlimits {overlimits} requeues {requeues})
 backlog {backlog_bytes}b {backlog_packets}p requeues {backlog_requeues}
"""


def write_json(path: Path, value: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def detail_interface(rx_packets: int, tx_packets: int, rx_dropped: int,
                     tx_dropped: int, tc_dropped: int) -> dict[str, dict[str, int]]:
    return {
        "ip": {
            "rx_packets": rx_packets,
            "tx_packets": tx_packets,
            "rx_dropped": rx_dropped,
            "tx_dropped": tx_dropped,
        },
        "sysfs": {},
        "tc": {"dropped": tc_dropped},
    }


def write_details(path: Path, details: dict[str, dict[str, dict[str, dict[str, int]]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(details), encoding="utf-8")


def add_interface_fixture(
    root: Path,
    namespace: str,
    ifname: str,
    *,
    rx_bytes_delta: int = 50,
    tx_bytes_delta: int = 75,
    rx_packets_delta: int = 4,
    tx_packets_delta: int = 5,
    rx_dropped_delta: int = 2,
    tx_dropped_delta: int = 4,
    tc_sent_bytes_delta: int = 500,
    tc_sent_packets_delta: int = 6,
    tc_dropped_delta: int = 3,
) -> None:
    before = root / "net_stats" / "before" / namespace
    after = root / "net_stats" / "after" / namespace

    write_snapshot(
        before / f"{ifname}_ip.txt",
        ip_stdout(100, 10, 1, 200, 20, 2, ifname=ifname),
    )
    write_snapshot(
        after / f"{ifname}_ip.txt",
        ip_stdout(
            100 + rx_bytes_delta,
            10 + rx_packets_delta,
            1 + rx_dropped_delta,
            200 + tx_bytes_delta,
            20 + tx_packets_delta,
            2 + tx_dropped_delta,
            ifname=ifname,
        ),
    )
    write_snapshot(
        before / f"{ifname}_tc.txt",
        tc_stdout(1000, 10, 1, 2, 3, 4, 5, 6),
    )
    write_snapshot(
        after / f"{ifname}_tc.txt",
        tc_stdout(
            1000 + tc_sent_bytes_delta,
            10 + tc_sent_packets_delta,
            1 + tc_dropped_delta,
            2,
            3,
            4,
            5,
            6,
        ),
    )
    write_json(before / f"{ifname}_sysfs.json", {"rx_bytes": 100, "tx_bytes": 200})
    write_json(after / f"{ifname}_sysfs.json", {"rx_bytes": 160, "tx_bytes": 260})


def build_fixture(root: Path) -> None:
    before = root / "net_stats" / "before" / "ns-n0"
    after = root / "net_stats" / "after" / "ns-n0"

    write_snapshot(before / "uplink_ip.txt", ip_stdout(100, 10, 1, 200, 20, 2))
    write_snapshot(after / "uplink_ip.txt", ip_stdout(150, 14, 3, 275, 25, 6))
    write_snapshot(before / "uplink_tc.txt", tc_stdout(1000, 10, 1, 2, 3, 4, 5, 6))
    write_snapshot(after / "uplink_tc.txt", tc_stdout(1500, 16, 4, 6, 8, 12, 14, 18))
    write_json(before / "uplink_sysfs.json", {"rx_bytes": 100, "tx_bytes": 200, "before_only": 1})
    write_json(after / "uplink_sysfs.json", {"rx_bytes": 160, "tx_bytes": 260, "after_only": 1})

    write_snapshot(root / "net_stats" / "before" / "ns-before-only" / "eth0_ip.txt", "")
    write_snapshot(root / "net_stats" / "after" / "ns-after-only" / "eth0_ip.txt", "")
    write_snapshot(before / "before_only_ip.txt", "")
    write_snapshot(after / "after_only_ip.txt", "")


def build_summary_fixture(root: Path) -> None:
    add_interface_fixture(root, "ns-n0", "uplink", rx_bytes_delta=50)
    add_interface_fixture(root, "ns-a0", "uplink", rx_bytes_delta=150)
    add_interface_fixture(root, "ns-n0", "bat0")
    add_interface_fixture(root, "ns-a0", "br-lan")
    add_interface_fixture(root, "ns-a0", "lan0")
    add_interface_fixture(root, "ns-d0", "veth0")
    add_interface_fixture(root, "switch", "ve-n0-n1")
    add_interface_fixture(root, "switch", "dl-n0")
    add_interface_fixture(root, "switch", "br-n0")
    add_interface_fixture(root, "ns-x", "mystery0")


def build_details_tree_fixture(root: Path) -> None:
    write_details(
        root / "iter_01" / "net_stats" / "details.json",
        {
            "ns-n0": {
                "uplink": detail_interface(10, 20, 1, 2, 3),
            },
            "switch": {
                "ve-n0-n1": detail_interface(30, 40, 5, 6, 7),
            },
            "ns-d0": {
                "veth0": detail_interface(50, 60, 8, 9, 10),
            },
        },
    )
    write_details(
        root / "nested" / "iter_02" / "net_stats" / "details.json",
        {
            "ns-n0": {
                "uplink": detail_interface(20, 30, 3, 4, 5),
            },
            "switch": {
                "ve-n0-n1": detail_interface(50, 70, 9, 10, 11),
            },
            "ns-d0": {
                "veth0": detail_interface(70, 90, 12, 13, 14),
            },
        },
    )


def test_analyze_net_stats_fixture() -> None:
    analyze = load_analyze_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_fixture(root)
        details = analyze.analyze_net_stats(root)
        output = root / "net_stats" / "details.json"
        analyze.write_json(output, details)
        summary_output = root / "net_stats" / "summary.csv"
        analyze.write_summary_csv(summary_output, analyze.summarize_by_interface_type(details))
        written = json.loads(output.read_text(encoding="utf-8"))

    assert sorted(details) == ["ns-n0"]
    assert written == details
    assert sorted(details["ns-n0"]) == ["uplink"]

    uplink = details["ns-n0"]["uplink"]
    assert uplink["ip"]["rx_bytes"] == 50
    assert uplink["ip"]["rx_packets"] == 4
    assert uplink["ip"]["rx_dropped"] == 2
    assert uplink["ip"]["tx_bytes"] == 75
    assert uplink["ip"]["tx_packets"] == 5
    assert uplink["ip"]["tx_dropped"] == 4

    assert uplink["sysfs"] == {"rx_bytes": 60, "tx_bytes": 60}

    assert uplink["tc"] == {
        "backlog_bytes": 8,
        "backlog_packets": 9,
        "backlog_requeues": 12,
        "dropped": 3,
        "overlimits": 4,
        "requeues": 5,
        "sent_bytes": 500,
        "sent_packets": 6,
    }


def test_summary_csv_fixture() -> None:
    analyze = load_analyze_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_summary_fixture(root)
        details = analyze.analyze_net_stats(root / "net_stats")
        rows = analyze.summarize_by_interface_type(details)
        summary_output = root / "net_stats" / "summary.csv"
        analyze.write_summary_csv(summary_output, rows)
        latex_output = root / "net_stats" / "net_stats_table.tex"
        analyze.write_latex_table(latex_output, rows)

        with summary_output.open(newline="", encoding="utf-8") as f:
            csv_rows = list(csv.DictReader(f))
        latex_table = latex_output.read_text(encoding="utf-8")

    by_type = {row["interface_type"]: row for row in csv_rows}
    assert list(by_type) == [
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

    assert by_type["batman_hardif"]["interface_count"] == "2"
    assert float(by_type["batman_hardif"]["ip_rx_bytes_avg"]) == 100.0
    assert float(by_type["batman_hardif"]["ip_tx_bytes_avg"]) == 75.0
    assert float(by_type["batman_hardif"]["ip_rx_dropped_avg"]) == 2.0
    assert float(by_type["batman_hardif"]["ip_tx_dropped_avg"]) == 4.0
    assert float(by_type["batman_hardif"]["tc_sent_bytes_avg"]) == 500.0
    assert float(by_type["batman_hardif"]["tc_dropped_avg"]) == 3.0

    assert by_type["bridge_lan"]["interface_count"] == "1"
    assert float(by_type["bridge_lan"]["ip_rx_bytes_avg"]) == 50.0
    assert by_type["other"]["interface_count"] == "1"

    assert r"\begin{tabular}{l | r | r r | r r | r}" in latex_table
    assert r"\end{tabular}" in latex_table
    assert r"\begin{table}" not in latex_table
    assert r"\caption" not in latex_table
    assert r"\label" not in latex_table
    assert r"\multicolumn{2}{|c|}{\textbf{IP Packets Avg}}" in latex_table
    assert r"\multicolumn{2}{|c|}{\textbf{IP Dropped Avg}}" in latex_table
    assert r"\textbf{TC Avg}" in latex_table
    assert r"Bat Uplink & 2 & 4 & 5 & 2 & 4 & 3 \\" in latex_table
    assert r"Mesh Link & 1 & 4 & 5 & 2 & 4 & 3 \\" in latex_table
    assert r"Device LAN & 1 & 4 & 5 & 2 & 4 & 3 \\" in latex_table
    assert "BATMAN Mesh" not in latex_table


def test_details_tree_summary_fixture() -> None:
    analyze = load_analyze_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_details_tree_fixture(root)
        details_path_count = len(analyze.details_tree_paths(root))
        rows = analyze.summarize_details_tree(root)
        summary_output = root / "net_stats_summary.csv"
        latex_output = root / "net_stats_table.tex"
        analyze.write_summary_csv(summary_output, rows)
        analyze.write_latex_table(latex_output, rows)

        with summary_output.open(newline="", encoding="utf-8") as f:
            csv_rows = list(csv.DictReader(f))
        latex_table = latex_output.read_text(encoding="utf-8")

    by_type = {row["interface_type"]: row for row in csv_rows}
    assert details_path_count == 2
    assert by_type["batman_hardif"]["interface_count"] == "2"
    assert float(by_type["batman_hardif"]["ip_rx_packets_avg"]) == 15.0
    assert float(by_type["batman_hardif"]["ip_tx_packets_avg"]) == 25.0
    assert float(by_type["batman_hardif"]["ip_rx_dropped_avg"]) == 2.0
    assert float(by_type["batman_hardif"]["ip_tx_dropped_avg"]) == 3.0
    assert float(by_type["batman_hardif"]["tc_dropped_avg"]) == 4.0

    assert by_type["switch_mesh_link"]["interface_count"] == "2"
    assert float(by_type["switch_mesh_link"]["ip_rx_packets_avg"]) == 40.0
    assert float(by_type["switch_mesh_link"]["tc_dropped_avg"]) == 9.0
    assert by_type["device_lan"]["interface_count"] == "2"
    assert float(by_type["device_lan"]["ip_tx_packets_avg"]) == 75.0

    assert r"\begin{tabular}{l | r | r r | r r | r}" in latex_table
    assert r"\begin{table}" not in latex_table
    assert r"Bat Uplink & 2 & 15 & 25 & 2 & 3 & 4 \\" in latex_table
    assert r"Mesh Link & 2 & 40 & 55 & 7 & 8 & 9 \\" in latex_table
    assert r"Device LAN & 2 & 60 & 75 & 10 & 11 & 12 \\" in latex_table


def test_details_tree_requires_details_files() -> None:
    analyze = load_analyze_module()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            analyze.summarize_details_tree(Path(tmp))
        except FileNotFoundError as exc:
            assert "No net_stats/details.json files found" in str(exc)
        else:
            raise AssertionError("expected missing details tree to fail")


def run_tests() -> None:
    test_analyze_net_stats_fixture()
    test_summary_csv_fixture()
    test_details_tree_summary_fixture()
    test_details_tree_requires_details_files()


if __name__ == "__main__":
    run_tests()
