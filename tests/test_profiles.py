"""Phase-2 profiles: opt-in, declared-lossy projections with inline markers.

The contract: the DEFAULT profile stays complete-but-compact and
byte-identical to the baseline (test_parity.py); a non-default profile
may narrow output only where an entry (or the parsed tier) explicitly
declared how, must say what it withheld INLINE, and must fall back to
the complete rendering everywhere else. An unknown profile name never
loses data.
"""
from __future__ import annotations

import pytest

from terse import render
from terse.engine import build, omission_marker

from .corpus import (
    BRIEF,
    IP_INT_BRIEF,
    IP_ROUTE,
    PARSED_IP_INT_BRIEF,
    RUNNING_CONFIG,
    STATUS,
)

MARKER_STATUS = omission_marker(("name", "vlan", "duplex", "speed", "type"))


# ---------------------------------------------------------------------------
# Spec-tier projections
# ---------------------------------------------------------------------------

def test_updown_on_interface_status_keeps_port_and_status_only():
    (cand,) = render(STATUS, command="show interface status", profile="updown")
    lines = cand.text.splitlines()
    assert lines[0] == "port,status"
    assert "Eth1/11,connected" in lines
    assert "Po101,connected" in lines
    assert lines[-1] == MARKER_STATUS
    assert cand.profile == "updown"
    # manifest = base drops + projected-out columns
    assert cand.dropped_fields == ("name", "vlan", "duplex", "speed", "type")
    # and it is smaller than the complete rendering, which is the point
    (full,) = render(STATUS, command="show interface status")
    assert len(cand.text) < len(full.text)


def test_updown_on_ip_int_brief_merges_base_manifest():
    (cand,) = render(IP_INT_BRIEF, command="show ip interface brief", profile="updown")
    lines = cand.text.splitlines()
    assert lines[0] == "interface,status,protocol"
    assert "GigabitEthernet0/1,up,up" in lines
    assert lines[-1] == omission_marker(("ip",))
    # base drops (ok, method) stay declared alongside the projection's (ip)
    assert cand.dropped_fields == ("ok", "method", "ip")


def test_updown_on_nxos_brief_keeps_reason():
    cands = render(
        BRIEF, command="show interface ethernet1/9 brief",
        platform="cisco_nxos", profile="updown",
    )
    (cand,) = cands
    assert cand.text.splitlines()[0] == "interface,status,reason"
    assert "Eth1/9,down,Administratively down" in cand.text


def test_marker_names_the_recovery_path():
    (cand,) = render(STATUS, command="show interface status", profile="updown")
    assert "re-query profile=full" in cand.text.splitlines()[-1]
    # and the alias it advertises really is the complete rendering
    (full,) = render(STATUS, command="show interface status", profile="full")
    (default,) = render(STATUS, command="show interface status")
    assert full.text == default.text


# ---------------------------------------------------------------------------
# Fallbacks — a profile can only narrow where declared
# ---------------------------------------------------------------------------

def test_entries_without_the_profile_render_their_complete_default():
    plain = render(IP_ROUTE, command="show ip route")
    under = render(IP_ROUTE, command="show ip route", profile="updown")
    assert [c.text for c in plain] == [c.text for c in under]
    assert all(c.profile == "default" for c in under)
    assert all("[omitted:" not in c.text for c in under)


def test_unknown_profile_name_is_harmless_everywhere():
    for command, body in (
        ("show interface status", STATUS),
        ("show running-config", RUNNING_CONFIG),
    ):
        plain = render(body, command=command)
        under = render(body, command=command, profile="no_such_profile")
        assert [c.text for c in plain] == [c.text for c in under]


def test_code_tier_entries_are_untouched_by_profiles():
    plain = render(RUNNING_CONFIG, command="show run")
    under = render(RUNNING_CONFIG, command="show run", profile="updown")
    assert [c.text for c in plain] == [c.text for c in under]


def test_profile_variant_fails_open_on_unparseable_input():
    """A projection of nothing is nothing — no marker on raw passthrough."""
    assert render("garbage", command="show interface status", profile="updown") == []


# ---------------------------------------------------------------------------
# Parsed-tier projections
# ---------------------------------------------------------------------------

def test_updown_projects_parsed_rows_by_field_name():
    cands = [
        c for c in render(
            IP_INT_BRIEF, command="x", parsed=PARSED_IP_INT_BRIEF, profile="updown"
        )
        if c.method == "parsed"
    ]
    csv = next(c for c in cands if c.source == "parsed:csv")
    lines = csv.text.splitlines()
    assert lines[0] == "interface,status,proto"
    assert lines[1] == "GigabitEthernet0/1,up,up"
    assert lines[-1] == omission_marker(("ip_address",))
    assert csv.dropped_fields == ("ip_address",)
    assert csv.profile == "updown"
    toon = next(c for c in cands if c.source == "parsed:toon")
    assert toon.text.splitlines()[0] == "[3]{interface,status,proto}:"
    assert toon.text.splitlines()[-1] == omission_marker(("ip_address",))


def test_parsed_profile_falls_back_to_full_when_schema_is_unknown():
    """Field names the profile's patterns don't discriminate → complete
    encoding, no marker, no silent loss."""
    rows = [{"foo": "1", "bar": "2"}, {"foo": "3", "bar": "4"}]
    cands = [
        c for c in render("q" * 200, command="x", parsed=rows, profile="updown")
        if c.method == "parsed"
    ]
    for c in cands:
        assert c.profile == "default"
        assert c.dropped_fields == ()
        assert "[omitted:" not in c.text


# ---------------------------------------------------------------------------
# Build-time strictness
# ---------------------------------------------------------------------------

def test_malformed_projections_fail_loudly_at_build_time():
    spec = {
        "id": "t/x",
        "strategy": "fixed_width_table",
        "keywords": ["A", "B"],
        "header": "a,b",
        "profiles": {
            "bad_name": {"keep": ["nope"]},
            "keeps_all": {"keep": ["a", "b"]},
        },
    }
    with pytest.raises(ValueError):
        build(spec, profile="bad_name")
    with pytest.raises(ValueError):
        build(spec, profile="keeps_all")
    with pytest.raises(KeyError):
        build(spec, profile="undeclared")
