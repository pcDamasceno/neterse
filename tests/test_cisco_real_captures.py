"""Goldens over REAL device captures (containerlab cisco_iol, IOS 17.12.1).

The synthetic corpus masked three defects that live-lab verification
(2026-08-03, OSPF summarization lab r1–r4) exposed; these fixtures are
the actual captures, and the assertions here are what "faithful" means
on them. If a spec change breaks one of these, it broke real output.
"""
from __future__ import annotations

import re

import pytest

from terse import optimize, render

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


def test_ospf_neighbor_rows_survive_verbatim():
    raw = _body("cisco_ios/show_ip_ospf_neighbor")
    out = optimize("show ip ospf neighbor", raw)
    assert "0.0.0.3,1,FULL/DR,00:00:38,23.23.23.3,Ethernet0/2" in out.splitlines()
    assert "0.0.0.1,1,FULL/BDR,00:00:33,12.12.12.1,Ethernet0/1" in out.splitlines()
