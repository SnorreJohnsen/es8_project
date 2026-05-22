from __future__ import annotations

import importlib.util
from pathlib import Path


def load_snapshot_module():
    path = Path(__file__).with_name("net_stats_snapshot.py")
    spec = importlib.util.spec_from_file_location("net_stats_snapshot", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


IP_LINK_SHOW = """1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    RX: bytes  packets  errors  dropped missed  mcast
    10 1 0 0 0 0
    TX: bytes  packets  errors  dropped carrier collsns
    10 1 0 0 0 0
2: uplink@if7: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    link/ether 02:00:00:00:00:01 brd ff:ff:ff:ff:ff:ff
    RX: bytes  packets  errors  dropped missed  mcast
    100 10 0 1 0 2
    TX: bytes  packets  errors  dropped carrier collsns
    200 20 0 2 0 0
3: bat0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    link/ether 02:00:00:00:00:02 brd ff:ff:ff:ff:ff:ff
    RX: bytes  packets  errors  dropped missed  mcast
    300 30 0 3 0 4
    TX: bytes  packets  errors  dropped carrier collsns
    400 40 0 4 0 0
"""


TC_QDISC_SHOW = """qdisc noqueue 0: dev lo root refcnt 2
 Sent 10 bytes 1 pkt (dropped 0, overlimits 0 requeues 0)
 backlog 0b 0p requeues 0
qdisc netem 8001: dev uplink root refcnt 2 limit 1000
 Sent 100 bytes 10 pkt (dropped 1, overlimits 2 requeues 3)
 backlog 4b 5p requeues 6
qdisc ingress ffff: dev uplink parent ffff:fff1 ----------------
 Sent 50 bytes 5 pkt (dropped 0, overlimits 0 requeues 0)
 backlog 0b 0p requeues 0
qdisc noqueue 0: dev bat0 root refcnt 2
"""


SYSFS_STDOUT = """lo rx_bytes 1
uplink rx_bytes 100
uplink tx_bytes 200
bat0 rx_bytes 300
bat0 bad_value nope
"""


def test_parse_interface_names() -> None:
    snapshot = load_snapshot_module()
    assert snapshot.parse_interface_names(IP_LINK_SHOW) == ["uplink", "bat0"]


def test_split_ip_link_show() -> None:
    snapshot = load_snapshot_module()
    blocks = snapshot.split_ip_link_show(IP_LINK_SHOW)

    assert sorted(blocks) == ["bat0", "uplink"]
    assert "2: uplink@if7:" in blocks["uplink"]
    assert "3: bat0:" in blocks["bat0"]
    assert "1: lo:" not in "".join(blocks.values())


def test_split_tc_qdisc_show() -> None:
    snapshot = load_snapshot_module()
    blocks = snapshot.split_tc_qdisc_show(TC_QDISC_SHOW)

    assert sorted(blocks) == ["bat0", "uplink"]
    assert "qdisc netem 8001: dev uplink" in blocks["uplink"]
    assert "qdisc ingress ffff: dev uplink" in blocks["uplink"]
    assert "qdisc noqueue 0: dev bat0" in blocks["bat0"]
    assert "dev lo" not in "".join(blocks.values())


def test_parse_sysfs_stats() -> None:
    snapshot = load_snapshot_module()
    assert snapshot.parse_sysfs_stats(SYSFS_STDOUT) == {
        "uplink": {"rx_bytes": 100, "tx_bytes": 200},
        "bat0": {"rx_bytes": 300},
    }


def run_tests() -> None:
    test_parse_interface_names()
    test_split_ip_link_show()
    test_split_tc_qdisc_show()
    test_parse_sysfs_stats()


if __name__ == "__main__":
    run_tests()
