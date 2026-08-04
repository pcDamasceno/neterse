"""Behavioral suite for the ``neterse`` package.

Pins the public API surface (``render() -> [Candidate]``, ``optimize()``,
``register()``, ``iter_compressors()``) and the behavior of every
compressor family, spec-built and hand-written alike. The byte-parity
sweep against the pre-extraction baseline lives in ``test_parity.py``;
engine/platform/manifest specifics live in ``test_engine.py``.
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from neterse import (
    Candidate,
    __version__,
    iter_compressors,
    optimize,
    register,
    render,
)
from neterse import registry

from .corpus import (
    BGP_SUMMARY,
    BRIEF,
    COMMAND_FIXTURES,
    COUNTERS_ERRORS,
    DASHES,
    EIGRP,
    IOS_INTF_DETAIL,
    IP_ROUTE,
    NXOS_INTF_DETAIL,
    NXOS_INTF_DOWN,
    PORTCHANNEL,
    STATUS,
)


# ===========================================================================
# Frozen public API surface
# ===========================================================================

def test_version_and_exports():
    assert __version__ == "0.1.0"
    assert callable(optimize) and callable(render) and callable(register)
    assert callable(iter_compressors)


def test_candidate_is_frozen_with_estimates():
    c = Candidate(text="abcd" * 10, method="toon", source="fn")
    assert c.est_chars == 40
    assert c.est_tokens() == 10
    assert c.est_tokens(chars_per_token=2) == 20
    assert c.dropped_fields is None  # undeclared (legacy) — not "nothing dropped"
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.text = "mutated"  # type: ignore[misc]


def test_render_empty_output_returns_no_candidates():
    assert render("", command="show interface status") == []


def test_render_unknown_command_returns_no_candidates():
    assert render("some output", command="show something weird") == []


def test_default_path_is_stable_under_matching_platform_and_profile_aliases():
    """The byte-parity path: a MATCHING platform string, the default
    profile and its ``full`` alias must all reproduce the plain result
    exactly (mismatch behavior is pinned in test_engine.py, projections
    in test_profiles.py, the parsed tier in test_parsed.py)."""
    plain = render(IP_ROUTE, command="show ip route")
    for kwargs in (
        {"platform": "cisco_nxos"},
        {"profile": "default"},
        {"profile": "full"},
        {"platform": "cisco_nxos", "profile": "full"},
    ):
        again = render(IP_ROUTE, command="show ip route", **kwargs)
        assert [c.text for c in plain] == [c.text for c in again]
        assert all(c.profile == "default" for c in again)


@pytest.mark.parametrize(
    "label,command,body",
    [pytest.param(*f, id=f[0]) for f in COMMAND_FIXTURES],
)
def test_optimize_equals_min_render(label, command, body):
    """The convenience wrapper is exactly 'first smallest candidate or raw'."""
    candidates = render(body, command=command)
    expected = (
        min(candidates, key=lambda c: len(c.text)).text if candidates else body
    )
    assert optimize(command, body) == expected
    for c in candidates:
        assert 0 < len(c.text) < len(body)
        assert c.method == "toon"
        assert c.source


def test_register_plugin_roundtrip_and_failopen():
    saved = list(registry.REGISTRY)
    try:
        @register(r"^fake\s+plugin\s+cmd$")
        def _boom(_raw: str) -> str:
            raise ValueError("plugin bug")

        @register(r"^fake\s+plugin\s+cmd$")
        def _tiny(_raw: str) -> str:
            return "TINY"

        out = render("x" * 100, command="fake plugin cmd")
        assert [c.text for c in out] == ["TINY"]      # raiser dropped, fail-open
        assert out[0].source == "_tiny"
        assert optimize("fake plugin cmd", "x" * 100) == "TINY"
    finally:
        registry.REGISTRY[:] = saved


def test_iter_compressors_is_a_snapshot_of_pairs():
    snap = iter_compressors()
    assert isinstance(snap, tuple)
    assert len(snap) == len(registry.REGISTRY) >= 15
    for pattern, fn in snap:
        assert isinstance(pattern, re.Pattern)
        assert callable(fn)


# ===========================================================================
# Ported behavioral tests (historical suite, package import path)
# ===========================================================================

def test_counter_errors_keeps_only_nonzero_rows():
    out = optimize("show interface counters errors", COUNTERS_ERRORS)
    assert "Eth1/37,0,6,0,6,0,0" in out
    assert "Eth1/39,0,2064,0,2064,0,0" in out
    assert "\nmgmt0," not in out
    assert "\nEth1/1," not in out


def test_counter_errors_all_zero_table_marked():
    out = optimize("show interface counters errors", COUNTERS_ERRORS)
    assert "Single-Col" in out
    assert "(all zero)" in out


def test_counter_errors_shrinks_and_drops_separators():
    out = optimize("show interface counters errors", COUNTERS_ERRORS)
    assert len(out) < len(COUNTERS_ERRORS)
    assert DASHES not in out


def test_counter_errors_failopen_without_header():
    raw = "no port table here\njust noise"
    assert optimize("show interface counters errors", raw) == raw


def test_counter_errors_per_interface_rejoins_wrapped_row():
    raw = """\
-------------------------------------------------------------------------------
Port          Align-Err    FCS-Err   Xmit-Err    Rcv-Err  UnderSize OutDiscards
-------------------------------------------------------------------------------
Eth1/37                 0          6          0          6          0
0

-------------------------------------------------------------------------------
Port           Single-Col  Multi-Col   Late-Col  Exces-Col  Carri-Sen       Runts
-------------------------------------------------------------------------------
Eth1/37                 0          0          0          0          0
0
"""
    out = optimize("show interface Ethernet1/37 counters errors", raw)
    assert "Eth1/37,0,6,0,6,0,0" in out
    assert "Single-Col,Multi-Col,Late-Col,Exces-Col,Carri-Sen,Runts  (all zero)" in out
    assert len(out) < len(raw)


def test_counter_errors_incomplete_wrapped_row_fails_open():
    raw = """\
Port          Align-Err    FCS-Err   Xmit-Err    Rcv-Err  UnderSize OutDiscards
Eth1/37                 0          6          0          6          0
"""
    assert optimize("show interface Ethernet1/37 counters errors", raw) == raw


def test_transceiver_inventory_unions_fields_losslessly():
    raw = """\
Ethernet1/1
    transceiver is present
    type is 10Gbase-SR
    serial number is AVD2034DAKN
    Link length supported for 50/125um OM3 fiber is 300 m

Ethernet1/45
    transceiver is present
    type is 10Gbase-LR
    serial number is AVD2052KEGS
    Link length supported for 9/125um fiber is 10 km
"""
    out = optimize("show interface transceiver", raw)
    lines = out.splitlines()
    assert lines[0] == (
        "interface,transceiver,type,serial_number,"
        "link_length_supported_for_50_125um_om3_fiber,"
        "link_length_supported_for_9_125um_fiber"
    )
    assert lines[1] == "Ethernet1/1,present,10Gbase-SR,AVD2034DAKN,300 m,"
    assert lines[2] == "Ethernet1/45,present,10Gbase-LR,AVD2052KEGS,,10 km"
    assert len(out) < len(raw)


def test_transceiver_inventory_does_not_claim_details():
    raw = "Ethernet1/1\n    transceiver is present\n    type is 10Gbase-SR"
    assert optimize("show interface transceiver details", raw) == raw


def test_transceiver_inventory_truncation_fails_open():
    raw = """\
Ethernet1/1
    transceiver is present
    type is 10Gbase-SR
[TRUNCATED - middle omitted]
"""
    assert optimize("show interface transceiver", raw) == raw


def test_interface_status_csv_header_and_rows():
    out = optimize("show interface status", STATUS)
    lines = out.splitlines()
    assert lines[0] == "port,name,status,vlan,duplex,speed,type"
    assert "Eth1/11,RSRFF206 Twe1/0/3,connected,routed,full,10G,10Gbase-SR" in lines
    assert "Eth1/45,RFRA3213-Eth1/48,connected,routed,full,10G,10Gbase-LR" in lines
    assert "Po101,MFS4163-Po101,connected,trunk,full,10G,--" in lines


def test_interface_status_preserves_names_with_spaces():
    assert "RSRFF206 Twe1/0/3" in optimize("show interface status", STATUS)


def test_interface_status_drops_separators_and_repeated_headers():
    out = optimize("show interface status", STATUS)
    assert DASHES not in out
    assert out.count("port,name,status") == 1
    assert len(out) < len(STATUS)


def test_interface_status_per_interface_variant_matches():
    out = optimize("show interface ethernet1/11 status", STATUS)
    assert out.startswith("port,name,status")


def test_interface_status_spaced_selector_variant_matches():
    out = optimize(
        "show interface ethernet1/9-12, ethernet1/15, ethernet1/17 status",
        STATUS,
    )
    assert out.startswith("port,name,status")


def test_interface_status_filtered_without_header():
    raw = """\
Eth1/1        FREE               disabled  1         auto    auto    10Gbase-SR
Eth1/11       RSRFF206 Twe1/0/3  connected routed    full    10G     10Gbase-SR
"""
    out = optimize("show interface status | include Eth1/(1|11)", raw)
    assert out.splitlines() == [
        "port,name,status,vlan,duplex,speed,type",
        "Eth1/1,FREE,disabled,1,auto,auto,10Gbase-SR",
        "Eth1/11,RSRFF206 Twe1/0/3,connected,routed,full,10G,10Gbase-SR",
    ]


def test_interface_brief_csv_and_wrapped_header_dropped():
    out = optimize("show interface ethernet1/9 brief", BRIEF)
    lines = out.splitlines()
    assert lines[0] == "interface,vlan,type,mode,status,reason,speed,port_ch"
    assert "Eth1/9,1,eth,access,down,Administratively down,auto(D),--" in lines
    assert "\nInterface," not in out
    assert DASHES not in out


def test_nxos_interface_detail_extracts_key_fields():
    out = optimize("show interface ethernet1/45", NXOS_INTF_DETAIL)
    assert out.startswith("Ethernet1/45")
    assert "status=up/up" in out
    assert 'desc="RFRA3213-Eth1/48"' in out
    assert "mtu=1500" in out
    assert "bw=10000000Kbit" in out
    assert "duplex=full/10" in out
    assert "crc=48" in out
    assert len(out) < len(NXOS_INTF_DETAIL) * 0.5


def test_nxos_interface_down_with_reason():
    out = optimize("show interface ethernet1/9", NXOS_INTF_DOWN)
    assert out.startswith("Ethernet1/9")
    assert "status=down/down" in out
    assert 'reason="Administratively down"' in out
    assert 'desc="FREE"' in out
    assert len(out) < len(NXOS_INTF_DOWN) * 0.6


def test_ios_interface_detail_still_works():
    out = optimize("show interfaces GigabitEthernet0/1", IOS_INTF_DETAIL)
    assert out.startswith("GigabitEthernet0/1")
    assert "status=up/up" in out
    assert "crc=2" in out


def test_eigrp_neighbors_csv():
    out = optimize("show ip eigrp neighbors", EIGRP)
    lines = out.splitlines()
    assert lines[0].startswith("IP-EIGRP neighbors for process 190")
    assert lines[1] == "h,address,interface,hold,uptime,srtt,rto,q,seq"
    assert "5,192.168.13.85,Eth1/38,11,11w6d,1,50,0,549000" in lines
    assert "Cnt Num" not in out
    assert len(out) < len(EIGRP)


def test_eigrp_neighbors_vrf_all_command_matches():
    out = optimize("show ip eigrp neighbors vrf all", EIGRP)
    assert "h,address,interface,hold,uptime,srtt,rto,q,seq" in out


def test_portchannel_summary_drops_legend():
    out = optimize("show port-channel summary", PORTCHANNEL)
    lines = out.splitlines()
    assert lines[0] == "group,port_channel,type,protocol,member_ports"
    assert "101,Po101(SU),Eth,LACP,Eth1/42(P) Eth1/43(P)" in lines
    assert "Hot-standby" not in out
    assert "BFD Session Wait" not in out
    assert len(out) < len(PORTCHANNEL) * 0.6


def test_optimize_tries_all_and_keeps_smallest():
    saved = list(registry.REGISTRY)
    try:
        register(r"^fakecmd$")(lambda r: r[:20])   # medium
        register(r"^fakecmd$")(lambda r: "TINY")    # smallest
        register(r"^fakecmd$")(lambda r: r + "X")   # longer (ignored)
        assert optimize("fakecmd", "x" * 100) == "TINY"
    finally:
        registry.REGISTRY[:] = saved


def test_unknown_command_returns_raw():
    raw = "some totally unstructured output"
    assert optimize("show something weird", raw) == raw


def test_empty_output_returns_empty():
    assert optimize("show interface status", "") == ""


def test_ios_ip_route_golden():
    """The post-decision-20 baseline for the route family, pinned exactly
    (this family is exempt from snapshot parity — see test_parity.py)."""
    assert optimize("show ip route", IP_ROUTE) == (
        "proto,prefix,ad/metric,next_hop,interface\n"
        "O,10.1.1.0/24,110/20,10.0.0.1,GigabitEthernet0/1\n"
        "O,10.1.2.0/24,110/30,10.0.0.1,GigabitEthernet0/1\n"
        "C,10.0.0.0/24,,,GigabitEthernet0/0\n"
        "S*,0.0.0.0/0,1/0,192.168.1.1,"
    )


def test_ios_bgp_summary_golden():
    """The post-decision-24 baseline for the bgp-summary family, pinned
    exactly (exempt from snapshot parity — see test_parity.py). The old
    regex captured the V column (constant 4) as "as"; the fixture's two
    different ASes are the proof it now reads the real one."""
    assert optimize("show ip bgp summary", BGP_SUMMARY) == (
        "neighbor,as,state_pfxrcd\n"
        "10.0.0.1,65001,25\n"
        "10.0.0.5,65002,Idle"
    )
