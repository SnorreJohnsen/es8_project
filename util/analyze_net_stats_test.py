from __future__ import annotations

import importlib.util
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
              tx_bytes: int, tx_packets: int, tx_dropped: int) -> str:
    return f"""2: uplink@if3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
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


def test_analyze_net_stats_fixture() -> None:
    analyze = load_analyze_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_fixture(root)
        details = analyze.analyze_net_stats(root)
        output = root / "net_stats" / "details.json"
        analyze.write_json(output, details)
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


def run_tests() -> None:
    test_analyze_net_stats_fixture()


if __name__ == "__main__":
    run_tests()
