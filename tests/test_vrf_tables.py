"""Regression coverage for large IOS/IOS-XE per-VRF tables."""
from __future__ import annotations

from neterse import optimize, render


SHOW_VRF = """  Name                             Default RD            Protocols   Interfaces
  Cef                              10.79.1.245:5005      ipv4        Vl618
  Mgmt-vrf                         <not set>             ipv4,ipv6   Gi0/0
  acc_mca                          10.7.255.1:20001      ipv4        Lo99
                                                                     Lo101
                                                                     Vl870
                                                                     Tu4

  Platform iVRF Name               iVRF Id               Interfaces
  __Platform_iVRF:_ID00_           0                     LI3/2
"""

ROUTE_SUMMARY = """IP routing table name is default (0x0)
IP routing table maximum-paths is 32
Route Source    Networks    Subnets     Replicates  Overhead    Memory (bytes)
static          0           0           0           0           0
connected       0           10          0           1120        3120
isis TradingBB  0           106         0           17920       33072
  Level 1: 0 Level 2: 106 Inter-area: 0
bgp 12625       0           0           0           0           0
  External: 0 Internal: 0 Local: 0
internal        1                                               42672
Total           1           116         0           19040       78864

IP routing table name is acc_mca (0x6)
IP routing table maximum-paths is 32
Route Source    Networks    Subnets     Replicates  Overhead    Memory (bytes)
connected       0           7           0           784         2184
ospf 101        0           0           0           0           0
  Intra-area: 0 Inter-area: 0 External-1: 0 External-2: 0
  NSSA External-1: 0 NSSA External-2: 0
Total           2           7           0           784         3608
"""


def test_show_vrf_rejoins_wrapped_interfaces_without_losing_values():
    out = optimize("show vrf", SHOW_VRF)
    assert out.splitlines() == [
        "name,default_rd,protocols,interfaces",
        "Cef,10.79.1.245:5005,ipv4,Vl618",
        'Mgmt-vrf,<not set>,"ipv4,ipv6",Gi0/0',
        "acc_mca,10.7.255.1:20001,ipv4,Lo99;Lo101;Vl870;Tu4",
        "platform_ivrf_name,ivrf_id,interfaces",
        "__Platform_iVRF:_ID00_,0,LI3/2",
    ]


def test_show_vrf_fails_open_when_platform_ivrf_row_is_malformed():
    raw = SHOW_VRF + "  platform-vrf                                           Gi0/1\n"
    assert optimize("show vrf", raw) == raw


def test_route_summary_preserves_vrf_source_and_detail_grouping():
    out = optimize("show ip route vrf * summary", ROUTE_SUMMARY)
    lines = out.splitlines()
    assert lines[0] == "vrf=default,id=0x0,max_paths=32"
    assert "isis TradingBB,0,106,0,17920,33072" in lines
    assert "detail,Level 1: 0 Level 2: 106 Inter-area: 0" in lines
    assert "internal,1,,,,42672" in lines
    assert "vrf=acc_mca,id=0x6,max_paths=32" in lines
    assert "detail,NSSA External-1: 0 NSSA External-2: 0" in lines


def test_route_summary_fails_open_after_downstream_truncation():
    raw = ROUTE_SUMMARY.replace(
        "IP routing table name is acc_mca",
        "[TRUNCATED - 30 lines omitted]\nIP routing table name is acc_mca",
    )
    assert optimize("show ip route vrf * summary", raw) == raw


def test_vrf_compressors_are_declared_lossless():
    for command, raw in (
        ("show vrf", SHOW_VRF),
        ("show ip route vrf * summary", ROUTE_SUMMARY),
    ):
        candidates = render(raw, command=command, platform="cisco_iosxe")
        best = min(candidates, key=lambda candidate: len(candidate.text))
        assert best.dropped_fields == ()