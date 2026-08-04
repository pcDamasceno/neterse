"""``neterse.ntc`` — the optional ntc-templates front-end (decision 29).

ntc-templates itself is NOT a test dependency: these tests install a fake
``ntc_templates.parse`` module (or block the import entirely) and pin the
contract that matters — fail-open without the extra, rows flowing into the
parsed tier with it, and byte-identical behavior to the core API whenever
parsing yields nothing.
"""
from __future__ import annotations

import sys
import types

import pytest

import neterse
from neterse import ntc

from .corpus import IP_INT_BRIEF

ROWS = [
    {"interface": "GigabitEthernet0/0", "ip": "10.0.0.1", "status": "up"},
    {"interface": "GigabitEthernet0/1", "ip": "10.0.0.2", "status": "down"},
]


def _install_fake(monkeypatch, parse_output):
    parse_mod = types.ModuleType("ntc_templates.parse")
    parse_mod.parse_output = parse_output
    pkg = types.ModuleType("ntc_templates")
    pkg.parse = parse_mod
    monkeypatch.setitem(sys.modules, "ntc_templates", pkg)
    monkeypatch.setitem(sys.modules, "ntc_templates.parse", parse_mod)


def _block_import(monkeypatch):
    # None in sys.modules makes the lazy import raise ImportError even
    # when a real ntc-templates happens to be installed.
    monkeypatch.setitem(sys.modules, "ntc_templates", None)
    monkeypatch.setitem(sys.modules, "ntc_templates.parse", None)


# ---------------------------------------------------------------------------
# parse()
# ---------------------------------------------------------------------------

def test_parse_returns_rows_and_passes_the_ntc_keying(monkeypatch):
    calls = {}

    def fake(platform, command, data):
        calls.update(platform=platform, command=command, data=data)
        return ROWS

    _install_fake(monkeypatch, fake)
    rows = ntc.parse("raw", command="show ip int brief", platform="cisco_ios")
    assert rows == ROWS
    assert calls == {
        "platform": "cisco_ios", "command": "show ip int brief", "data": "raw",
    }


def test_parse_fails_open_without_the_extra(monkeypatch):
    _block_import(monkeypatch)
    assert ntc.parse("raw", command="show version", platform="cisco_ios") is None


def test_parse_fails_open_when_no_template_matches(monkeypatch):
    def fake(platform, command, data):
        raise Exception("No template found")

    _install_fake(monkeypatch, fake)
    assert ntc.parse("raw", command="show foo", platform="cisco_ios") is None


@pytest.mark.parametrize("shape", ["a string", [], ["str", "rows"], 42, None])
def test_parse_declines_non_row_shapes(monkeypatch, shape):
    _install_fake(monkeypatch, lambda platform, command, data: shape)
    assert ntc.parse("raw", command="show x", platform="cisco_ios") is None


# ---------------------------------------------------------------------------
# render() / optimize()
# ---------------------------------------------------------------------------

def test_render_emits_both_tiers(monkeypatch):
    _install_fake(monkeypatch, lambda platform, command, data: ROWS)
    cands = ntc.render(
        IP_INT_BRIEF, command="show ip interface brief", platform="cisco_ios"
    )
    methods = {c.method for c in cands}
    assert methods == {"toon", "parsed"}
    assert {c.source for c in cands if c.method == "parsed"} == {
        "parsed:csv", "parsed:toon",
    }


def test_render_without_extra_equals_core_render(monkeypatch):
    _block_import(monkeypatch)
    via_ntc = ntc.render(
        IP_INT_BRIEF, command="show ip interface brief", platform="cisco_ios"
    )
    core = neterse.render(
        IP_INT_BRIEF, command="show ip interface brief", platform="cisco_ios"
    )
    assert via_ntc == core


def test_render_forwards_every_argument_to_core(monkeypatch):
    """Pin the exact core call — the equality tests alone can't see a
    dropped keyword when the fixture renders the same either way."""
    _install_fake(monkeypatch, lambda platform, command, data: ROWS)
    captured = {}

    def fake_render(raw, **kwargs):
        captured.update(kwargs, raw=raw)
        return []

    monkeypatch.setattr(neterse, "render", fake_render)
    ntc.render("raw text", command="show vlan", platform="arista_eos",
               profile="updown")
    assert captured == {
        "raw": "raw text", "command": "show vlan",
        "platform": "arista_eos", "parsed": ROWS, "profile": "updown",
    }


# Arista-style bare `show vlan` — parsed by spec:arista_eos/show_vlan,
# which a cisco_ios platform string must skip.
ARISTA_VLAN = (
    "VLAN  Name                             Status    Ports\n"
    "----- -------------------------------- --------- ----------------\n"
    "1     default                          active    Et1, Et2\n"
    "10    users                            active    Et3\n"
)


def test_render_platform_filter_stays_load_bearing(monkeypatch):
    """A body where the platform skip-filter changes the outcome: losing
    the platform forwarding would let the Arista vlan spec claim this
    output for a cisco_ios caller — a cross-family false match."""
    _block_import(monkeypatch)
    assert ntc.render(ARISTA_VLAN, command="show vlan",
                      platform="cisco_ios") == []
    eos = ntc.render(ARISTA_VLAN, command="show vlan", platform="arista_eos")
    assert eos and eos[0].source == "spec:arista_eos/show_vlan"


def test_render_passes_profile_through_to_the_parsed_tier(monkeypatch):
    _install_fake(monkeypatch, lambda platform, command, data: ROWS)
    cands = ntc.render(
        IP_INT_BRIEF, command="show ip interface brief",
        platform="cisco_ios", profile="updown",
    )
    parsed = [c for c in cands if c.method == "parsed"]
    assert parsed and all(c.profile == "updown" for c in parsed)
    assert all("ip" in c.dropped_fields for c in parsed)


def test_optimize_picks_smallest_across_both_tiers(monkeypatch):
    _install_fake(monkeypatch, lambda platform, command, data: ROWS)
    out = ntc.optimize(
        "show ip interface brief", IP_INT_BRIEF, platform="cisco_ios"
    )
    cands = ntc.render(
        IP_INT_BRIEF, command="show ip interface brief", platform="cisco_ios"
    )
    assert out == min(cands, key=lambda c: len(c.text)).text


def test_optimize_returns_raw_when_nothing_shrinks(monkeypatch):
    _block_import(monkeypatch)
    assert ntc.optimize("show whatever", "tiny", platform="cisco_ios") == "tiny"
    assert ntc.optimize("show whatever", "", platform="cisco_ios") == ""
