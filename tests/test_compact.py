"""``neterse.compact`` — one verb, dispatch on shape (decision 32).

The same call must serve netmiko, scrapli, NAPALM-style getters and
raw text without per-library names. Neither library is a test
dependency: netmiko-shaped connections and scrapli-shaped responses are
fakes carrying exactly the attribute surface the dispatch reads, and the
ntc-templates seam is faked or blocked with the ``test_ntc`` helpers.
"""
from __future__ import annotations

import pytest

import neterse
from neterse import compact, optimize_parsed, sources
from neterse import ntc

from .corpus import IP_INT_BRIEF
from .test_ntc import ARISTA_VLAN, ROWS, _block_import, _install_fake


class FakeConn:
    """netmiko-shaped: send_command + device_type."""

    def __init__(self, output, device_type="cisco_ios_ssh"):
        self.output = output
        self.device_type = device_type
        self.calls = []

    def send_command(self, command_string, **kwargs):
        self.calls.append((command_string, kwargs))
        return self.output


class FakeResponse:
    """scrapli-shaped: result / channel_input / textfsm_platform /
    textfsm_parse_output()."""

    def __init__(self, result, channel_input, textfsm_platform="cisco_iosxe",
                 rows=None, parse_raises=False):
        self.result = result
        self.channel_input = channel_input
        self.textfsm_platform = textfsm_platform
        self._rows = rows
        self._parse_raises = parse_raises

    def textfsm_parse_output(self):
        if self._parse_raises:
            raise Exception("textfsm extra not installed")
        return self._rows


# ---------------------------------------------------------------------------
# Raw strings
# ---------------------------------------------------------------------------

def test_raw_string_uses_the_raw_tier(monkeypatch):
    _block_import(monkeypatch)
    out = compact(IP_INT_BRIEF, "show ip interface brief",
                  platform="cisco_ios")
    core = neterse.render(IP_INT_BRIEF, command="show ip interface brief",
                          platform="cisco_ios")
    assert out == min(core, key=lambda c: len(c.text)).text


def test_raw_string_parses_via_ntc_so_both_tiers_compete(monkeypatch):
    _install_fake(monkeypatch, lambda platform, command, data: ROWS)
    out = compact(IP_INT_BRIEF, "show ip interface brief",
                  platform="cisco_ios")
    both = ntc.render(IP_INT_BRIEF, command="show ip interface brief",
                      platform="cisco_ios")
    assert out == min(both, key=lambda c: len(c.text)).text


def test_raw_string_without_command_returns_unchanged(monkeypatch):
    _block_import(monkeypatch)
    assert compact(IP_INT_BRIEF) == IP_INT_BRIEF
    assert compact("") == ""


def test_raw_string_platform_filter_stays_load_bearing(monkeypatch):
    """A cisco_ios caller must not have the Arista vlan spec claim an
    Arista-shaped body — the filter must actually flow through."""
    _block_import(monkeypatch)
    assert compact(ARISTA_VLAN, "show vlan",
                   platform="cisco_ios") == ARISTA_VLAN
    eos = compact(ARISTA_VLAN, "show vlan", platform="arista_eos")
    assert eos != ARISTA_VLAN and eos.startswith("vlan,name,status,ports")


def test_raw_string_profile_marker(monkeypatch):
    _block_import(monkeypatch)
    out = compact(IP_INT_BRIEF, "show ip interface brief",
                  platform="cisco_ios", profile="updown")
    assert "[omitted:" in out


def test_nothing_shrinks_returns_raw(monkeypatch):
    _block_import(monkeypatch)
    assert compact("up", "show clock", platform="cisco_ios") == "up"


# ---------------------------------------------------------------------------
# Structured rows (netmiko use_textfsm, NAPALM getters, gNMI, plain data)
# ---------------------------------------------------------------------------

def test_rows_route_to_the_rows_only_path():
    assert compact(ROWS) == optimize_parsed(ROWS)


def test_rows_keep_the_requested_profile():
    out = compact(ROWS, profile="updown")
    assert out == optimize_parsed(ROWS, profile="updown")
    assert "[omitted:" in out


def test_napalm_style_getter_dict_routes_to_rows_path():
    getter = {
        "GigabitEthernet0/0": {"is_up": True, "speed": 1000},
        "GigabitEthernet0/1": {"is_up": False, "speed": 1000},
    }
    assert compact(getter) == optimize_parsed(getter)


def test_napalm_keyed_getter_flattens_and_shrinks():
    """The dominant NAPALM getter shape ``{name: {...}}`` (get_interfaces,
    get_optics, get_users) must compress end-to-end with no caller-side
    flattening: the outer key becomes a leading ``key`` column."""
    getter = {
        "Ethernet1/1": {"is_up": True, "description": "uplink", "mtu": 1500},
        "Ethernet1/2": {"is_up": False, "description": "core", "mtu": 9216},
    }
    import json

    baseline = json.dumps(getter, separators=(",", ":"), default=str)
    out = compact(getter)
    assert len(out) < len(baseline)                     # actually shrinks now
    assert out.splitlines()[0].startswith("key,")       # key-led table
    for name in getter:
        assert name in out                              # nothing dropped


# ---------------------------------------------------------------------------
# Connections (anything with send_command)
# ---------------------------------------------------------------------------

def test_connection_runs_the_command_and_passes_kwargs(monkeypatch):
    _block_import(monkeypatch)
    conn = FakeConn(IP_INT_BRIEF)
    out = compact(conn, "show ip interface brief",
                  read_timeout=30, strip_prompt=False)
    assert conn.calls == [
        ("show ip interface brief",
         {"read_timeout": 30, "strip_prompt": False}),
    ]
    # device_type flowed through as the platform (ios matches _ssh form)
    core = neterse.render(IP_INT_BRIEF, command="show ip interface brief",
                          platform="cisco_ios_ssh")
    assert out == min(core, key=lambda c: len(c.text)).text


def test_connection_device_type_reaches_the_ntc_ladder(monkeypatch):
    tried = []

    def fake_parse(platform, command, data):
        tried.append(platform)
        if platform == "cisco_wlc_ssh":
            return ROWS
        raise Exception("No template found")

    _install_fake(monkeypatch, fake_parse)
    conn = FakeConn("boot text " * 30, device_type="cisco_wlc_ssh")
    out = compact(conn, "show boot")
    assert tried == ["cisco_wlc", "cisco_wlc_ssh"]
    assert out == optimize_parsed(ROWS)     # the parsed tier won


def test_connection_requires_a_command():
    with pytest.raises(TypeError, match="needs the command"):
        compact(FakeConn(""))


def test_run_kwargs_without_a_connection_raise():
    with pytest.raises(TypeError, match="only apply when source is a connection"):
        compact("raw text", "show clock", read_timeout=30)


def test_connection_returning_rows_routes_to_rows_path(monkeypatch):
    _block_import(monkeypatch)
    conn = FakeConn(ROWS)                   # use_textfsm=True style
    out = compact(conn, "show ip interface brief", profile="updown")
    assert out == optimize_parsed(ROWS, profile="updown")
    assert "[omitted:" in out


def test_scrapli_style_connection_returns_a_response(monkeypatch):
    """A scrapli driver's send_command hands back a Response — the
    recursion must land in the response path with both tiers."""
    class ScrapliConn:
        textfsm_platform = "cisco_iosxe"

        def send_command(self, command, **kwargs):
            return FakeResponse(IP_INT_BRIEF, command, rows=ROWS)

    _block_import(monkeypatch)
    out = compact(ScrapliConn(), "show ip interface brief")
    resp = FakeResponse(IP_INT_BRIEF, "show ip interface brief", rows=ROWS)
    assert out == compact(resp)


# ---------------------------------------------------------------------------
# Response objects (via the sources adapters)
# ---------------------------------------------------------------------------

def test_response_lets_both_tiers_compete(monkeypatch):
    _block_import(monkeypatch)
    response = FakeResponse(IP_INT_BRIEF, "show ip interface brief",
                            rows=ROWS)
    out = compact(response)
    both = neterse.render(IP_INT_BRIEF, command="show ip interface brief",
                          platform="cisco_iosxe", parsed=ROWS)
    assert {c.method for c in both} == {"toon", "parsed"}
    assert out == min(both, key=lambda c: len(c.text)).text


def test_response_parse_failure_falls_back_to_our_own_ntc(monkeypatch):
    """When a response's OWN parse yields nothing (no scrapli textfsm
    extra, template miss), compact's raw path gives our ntc front-end a
    second chance — and the ladder resolves the platform spelling."""
    tried = []

    def fake_parse(platform, command, data):
        tried.append(platform)
        if platform == "cisco_ios":
            return ROWS
        raise Exception("No template found")

    _install_fake(monkeypatch, fake_parse)
    response = FakeResponse(IP_INT_BRIEF, "show ip interface brief",
                            parse_raises=True)
    out = compact(response)
    assert tried == ["cisco_iosxe", "cisco_ios"]
    assert out == min(
        neterse.render(IP_INT_BRIEF, command="show ip interface brief",
                       platform="cisco_iosxe", parsed=ROWS),
        key=lambda c: len(c.text),
    ).text


def test_response_platform_filter_stays_load_bearing(monkeypatch):
    _block_import(monkeypatch)
    wrong = FakeResponse(ARISTA_VLAN, "show vlan",
                         textfsm_platform="cisco_iosxe")
    assert compact(wrong) == ARISTA_VLAN
    right = FakeResponse(ARISTA_VLAN, "show vlan",
                         textfsm_platform="arista_eos")
    assert compact(right).startswith("vlan,name,status,ports")


def test_response_explicit_arguments_override(monkeypatch):
    _block_import(monkeypatch)
    response = FakeResponse(ARISTA_VLAN, "show vlan",
                            textfsm_platform="cisco_iosxe")
    assert compact(response,
                   platform="arista_eos").startswith("vlan,name,status")


def test_response_profile_marker(monkeypatch):
    _block_import(monkeypatch)
    response = FakeResponse(IP_INT_BRIEF, "show ip interface brief",
                            rows=ROWS)
    assert "[omitted:" in compact(response, profile="updown")


def test_response_edge_shapes_fail_open(monkeypatch):
    _block_import(monkeypatch)

    class Bare:
        result = IP_INT_BRIEF
        channel_input = "show ip interface brief"

    assert 0 < len(compact(Bare())) < len(IP_INT_BRIEF)
    assert compact(FakeResponse("up", "show clock")) == "up"
    assert compact(FakeResponse("", "show x")) == ""
    assert compact(FakeResponse(None, "show x")) == ""


def test_nornir_style_structured_result_routes_to_rows():
    class Nornirish:
        result = ROWS

    assert compact(Nornirish()) == optimize_parsed(ROWS)


# ---------------------------------------------------------------------------
# The adapter extension point
# ---------------------------------------------------------------------------

def test_register_adapter_wins_over_builtins():
    class Exotic:
        payload = IP_INT_BRIEF

    def adapter(obj):
        if not isinstance(obj, Exotic):
            return None
        return sources.Source(raw=obj.payload,
                              command="show ip interface brief",
                              platform="cisco_ios")

    sources.register_adapter(adapter)
    try:
        out = compact(Exotic())
        assert 0 < len(out) < len(IP_INT_BRIEF)
    finally:
        sources.ADAPTERS.remove(adapter)


def test_raising_adapter_counts_as_not_mine():
    def bad_adapter(obj):
        raise RuntimeError("adapter bug")

    sources.register_adapter(bad_adapter)
    try:
        assert compact(ROWS) == optimize_parsed(ROWS)
        response = FakeResponse("up", "show clock")
        assert compact(response) == "up"
    finally:
        sources.ADAPTERS.remove(bad_adapter)
