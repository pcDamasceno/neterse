"""Goldens over REAL device captures (containerlab cisco_iol, IOS 17.12.1).

The synthetic corpus masked three defects that live-lab verification
(2026-08-03, OSPF summarization lab r1–r4) exposed; these fixtures are
the actual captures, and the assertions here are what "faithful" means
on them. If a spec change breaks one of these, it broke real output.
"""
from __future__ import annotations

import re

import pytest

from neterse import optimize, render

from .fixture_corpus import FILE_FIXTURES


def _body(label: str) -> str:
    for f in FILE_FIXTURES:
        if f.label == label:
            return f.body
    pytest.fail(f"fixture {label} missing")


def test_route_table_keeps_every_route():
    """Decision 20: the legacy regex dropped ALL two-token-code routes
    (9 of 19 on r1 — every learned OSPF route on an OSPF lab)."""
    raw = _body("cisco_ios/show_ip_route")
    out = optimize("show ip route", raw)
    rows = out.splitlines()[1:]
    # every actual route line survives: 8 C/L locals + 11 learned
    raw_routes = re.findall(r"^[A-Z*]{1,2}(?: [A-Z][A-Z0-9]?)? +\d+\.", raw, re.M)
    assert len(rows) == len(raw_routes) == 19
    assert sum(1 for r in rows if r.startswith("O IA,")) == 5
    assert sum(1 for r in rows if r.startswith("O E2,")) == 4
    # columns carry the real values, not artifacts
    assert "O IA,2.2.2.2,110/11,12.12.12.2,Ethernet0/1" in rows
    assert "C,12.12.12.0/24,,,Ethernet0/1" in rows
    assert not any(r.endswith(",is") for r in rows)   # the `is` artifact
    assert not any(":" in r.split(",")[4] for r in rows), \
        "route-age leaked into the interface column"
    assert len(out) < len(raw) * 0.35


def test_route_manifest_declares_the_remaining_drops():
    raw = _body("cisco_ios/show_ip_route")
    (cand,) = [c for c in render(raw, command="show ip route", platform="cisco_ios")]
    assert cand.dropped_fields == (
        "route_age", "ecmp_alternate_paths", "subnet_group_headers"
    )


def test_int_brief_keeps_admin_down_status_whole():
    """Decision 21: `administratively down` is one status value; it used
    to split across status/protocol with the real protocol column lost."""
    raw = _body("cisco_ios/show_ip_interface_brief")
    out = optimize("show ip interface brief", raw)
    assert "Ethernet0/3,unassigned,administratively down,down" in out.splitlines()
    # count parity: every interface line becomes exactly one row
    n_ifaces = len(re.findall(r"^(?:Ethernet|Loopback)", raw, re.M))
    assert len(out.splitlines()) == 1 + n_ifaces


def test_bgp_summary_keeps_the_real_as_per_neighbor():
    """Decision 24: the legacy regex rendered the V column (constant 4)
    under the "as" header — on this capture (r2, BGP lab) that made the
    eBGP neighbor (AS 100) indistinguishable from the iBGP ones (AS 200)."""
    raw = _body("cisco_ios/show_ip_bgp_summary")
    out = optimize("show ip bgp summary", raw)
    assert out.splitlines() == [
        "neighbor,as,state_pfxrcd",
        "192.168.12.1,100,2",
        "192.168.23.3,200,2",
        "192.168.34.4,200,4",
    ]
    (cand,) = render(raw, command="show ip bgp summary", platform="cisco_ios")
    assert "version" in cand.dropped_fields   # V is dropped AND declared now


def test_ospf_neighbor_rows_survive_verbatim():
    raw = _body("cisco_ios/show_ip_ospf_neighbor")
    out = optimize("show ip ospf neighbor", raw)
    assert "0.0.0.3,1,FULL/DR,00:00:38,23.23.23.3,Ethernet0/2" in out.splitlines()
    assert "0.0.0.1,1,FULL/BDR,00:00:33,12.12.12.1,Ethernet0/1" in out.splitlines()


# ---------------------------------------------------------------------------
# show cdp neighbors (decision 25) — IOS fixed-width table, space-laden values
# ---------------------------------------------------------------------------

# Long device IDs wrap onto their own line in real IOS output; the columns
# follow with the first column blank. Synthetic (the lab's hostnames are
# short), spacing copied from the real capture's offsets.
CDP_WRAPPED = (
    "Device ID        Local Intrfce     Holdtme    Capability  Platform  Port ID\n"
    "core-rtr1.very-long.example.com\n"
    "                 Eth 0/0           165               R    Linux Uni Eth 0/0\n"
    "r1.lab           Eth 0/1           128               R    Linux Uni Eth 0/1\n"
)


def test_cdp_neighbors_ios_parses_space_laden_columns():
    """Decision 25: the legacy line-regex entry expects single-token
    interface/platform values and fails open on real IOS output
    (`Eth 0/2`, `Linux Uni`) — the whole family reached the model raw."""
    raw = _body("cisco_ios/show_cdp_neighbors")
    out = optimize("show cdp neighbors", raw)
    lines = out.splitlines()
    assert lines[0] == "device,local_intf,holdtime,capability,platform,remote_port"
    assert "r3.lab,Eth 0/2,154,R,Linux Uni,Eth 0/1" in lines
    assert "r3.lab,Eth 0/0,165,R,Linux Uni,Eth 0/0" in lines
    assert "r1.lab,Eth 0/1,128,R,Linux Uni,Eth 0/1" in lines
    assert "r1.lab,Eth 0/0,143,R,Linux Uni,Eth 0/0" in lines
    assert len(lines) == 1 + 4          # legend + total line are gone
    assert "Capability Codes" not in out
    assert len(out) < len(raw) * 0.6


def test_cdp_neighbors_wrapped_device_id_rejoined():
    out = optimize("show cdp neighbors", CDP_WRAPPED)
    lines = out.splitlines()
    assert (
        "core-rtr1.very-long.example.com,Eth 0/0,165,R,Linux Uni,Eth 0/0"
        in lines
    )
    assert "r1.lab,Eth 0/1,128,R,Linux Uni,Eth 0/1" in lines
    assert len(lines) == 1 + 2


def test_cdp_neighbors_winner_and_manifest():
    raw = _body("cisco_ios/show_cdp_neighbors")
    candidates = render(raw, command="show cdp neighbors", platform="cisco_ios")
    best = min(candidates, key=lambda c: len(c.text))
    assert best.source == "spec:cisco_ios/show_cdp_neighbors"
    assert best.dropped_fields == ("entry_count",)


def test_cdp_neighbors_legacy_on_format_output_unchanged():
    """Decision 25 lifts byte-parity for the cdp/lldp command family, so
    the legacy entry's on-format rendering is pinned HERE instead: for
    unindented single-token rows (the corpus body) it must still produce
    exactly the baseline CSV."""
    from .corpus import CDP_NEIGHBORS
    from .legacy_snapshot import optimize as baseline_optimize

    for cmd in ("show cdp neighbors", "show lldp neighbors"):
        out = optimize(cmd, CDP_NEIGHBORS)
        assert out == baseline_optimize(cmd, CDP_NEIGHBORS)
        assert out.splitlines()[0] == (
            "device,local_intf,capability,platform,remote_port"
        )
        assert "SW2,Eth1/1,S I,N9K-C93180,Eth1/2" in out.splitlines()


def test_cdp_neighbors_detail_stays_failopen():
    # `show cdp neighbors detail` is block output; the anchored command
    # regex must not claim it, and the table parser must not fire on it.
    detail = (
        "-------------------------\n"
        "Device ID: r3.lab\n"
        "Entry address(es):\n"
        "  IP address: 192.168.23.3\n"
        "Platform: Linux Unix,  Capabilities: Router\n"
    )
    assert optimize("show cdp neighbors detail", detail) == detail
