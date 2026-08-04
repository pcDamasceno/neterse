"""``neterse.netmiko`` — the duck-typed netmiko drop-in (decision 31).

netmiko itself is never a test dependency: a fake connection object
carries the two things the integration reads (``device_type`` and
``send_command``), and the ntc-templates seam is faked or blocked with
the same helpers ``test_ntc`` uses. Contracts pinned here: kwargs pass
through untouched, the transport suffix is stripped off ``device_type``,
both tiers compete when parsing is available, structured results route
to the rows-only path, and nothing ever enlarges.
"""
from __future__ import annotations

import neterse
from neterse import netmiko as integration
from neterse import ntc

from .corpus import IP_INT_BRIEF
from .test_ntc import ROWS, _block_import, _install_fake


class FakeConn:
    def __init__(self, output, device_type="cisco_ios_ssh"):
        self.output = output
        self.device_type = device_type
        self.calls = []

    def send_command(self, command_string, **kwargs):
        self.calls.append((command_string, kwargs))
        return self.output


def test_platform_of_strips_transport_suffixes():
    for device_type, expected in [
        ("cisco_ios_ssh", "cisco_ios"),
        ("cisco_ios_telnet", "cisco_ios"),
        ("cisco_ios_serial", "cisco_ios"),
        ("arista_eos", "arista_eos"),
        ("juniper_junos", "juniper_junos"),
    ]:
        assert integration.platform_of(FakeConn("", device_type)) == expected
    assert integration.platform_of(object()) is None
    assert integration.platform_of(FakeConn("", device_type="")) is None
    assert integration.platform_of(FakeConn("", device_type=None)) is None


def test_send_command_passes_kwargs_through_and_compacts(monkeypatch):
    _block_import(monkeypatch)
    conn = FakeConn(IP_INT_BRIEF)
    out = integration.send_command(
        conn, "show ip interface brief", read_timeout=30, strip_prompt=False
    )
    assert conn.calls == [
        ("show ip interface brief", {"read_timeout": 30, "strip_prompt": False}),
    ]
    core = neterse.render(
        IP_INT_BRIEF, command="show ip interface brief", platform="cisco_ios"
    )
    assert out == min(core, key=lambda c: len(c.text)).text
    assert len(out) < len(IP_INT_BRIEF)


def test_send_command_lets_both_tiers_compete(monkeypatch):
    captured = {}

    def fake_parse(platform, command, data):
        captured.update(platform=platform, command=command)
        return ROWS

    _install_fake(monkeypatch, fake_parse)
    conn = FakeConn(IP_INT_BRIEF)
    out = integration.send_command(conn, "show ip interface brief")
    # ntc-templates was keyed on the SUFFIX-STRIPPED device_type
    assert captured == {
        "platform": "cisco_ios", "command": "show ip interface brief",
    }
    both = ntc.render(
        IP_INT_BRIEF, command="show ip interface brief", platform="cisco_ios"
    )
    assert out == min(both, key=lambda c: len(c.text)).text


def test_parse_keys_mirror_how_netmiko_actually_resolves_templates():
    """Stripped first, verbatim second (ntc keys WLC templates on
    cisco_wlc_ssh itself), netmiko's cisco_xe -> cisco_ios retry last."""
    assert integration._parse_keys("cisco_ios") == ["cisco_ios"]
    assert integration._parse_keys("cisco_ios_ssh") == [
        "cisco_ios", "cisco_ios_ssh",
    ]
    assert integration._parse_keys("cisco_wlc_ssh") == [
        "cisco_wlc", "cisco_wlc_ssh",
    ]
    assert integration._parse_keys("cisco_xe") == ["cisco_xe", "cisco_ios"]
    assert integration._parse_keys("cisco_xe_telnet") == [
        "cisco_xe", "cisco_xe_telnet", "cisco_ios",
    ]
    assert integration._parse_keys("arista_eos") == ["arista_eos"]


def test_wlc_falls_back_to_the_verbatim_suffixed_key(monkeypatch):
    """ntc-templates keys every WLC template on cisco_wlc_ssh — the
    stripped key must not be the end of the road."""
    tried = []

    def fake_parse(platform, command, data):
        tried.append(platform)
        if platform == "cisco_wlc_ssh":
            return ROWS
        raise Exception("No template found")

    _install_fake(monkeypatch, fake_parse)
    conn = FakeConn("boot text " * 30, device_type="cisco_wlc_ssh")
    out = integration.send_command(conn, "show boot")
    assert tried == ["cisco_wlc", "cisco_wlc_ssh"]
    assert out == neterse.optimize_parsed(ROWS)   # parsed tier won


def test_cisco_xe_retries_as_cisco_ios_like_netmiko_does(monkeypatch):
    tried = []

    def fake_parse(platform, command, data):
        tried.append(platform)
        if platform == "cisco_ios":
            return ROWS
        raise Exception("No template found")

    _install_fake(monkeypatch, fake_parse)
    conn = FakeConn("arp text " * 40, device_type="cisco_xe")
    out = integration.send_command(conn, "show ip arp")
    assert tried == ["cisco_xe", "cisco_ios"]
    assert out == neterse.optimize_parsed(ROWS)


def test_send_command_with_structured_result_routes_to_rows_path(monkeypatch):
    _block_import(monkeypatch)
    conn = FakeConn(ROWS)          # what use_textfsm=True hands back
    out = integration.send_command(conn, "show ip interface brief")
    assert out == neterse.optimize_parsed(ROWS)


def test_structured_result_keeps_the_requested_profile(monkeypatch):
    _block_import(monkeypatch)
    conn = FakeConn(ROWS)
    out = integration.send_command(
        conn, "show ip interface brief", profile="updown"
    )
    assert out == neterse.optimize_parsed(ROWS, profile="updown")
    assert "[omitted:" in out


def test_send_command_returns_raw_when_nothing_shrinks(monkeypatch):
    _block_import(monkeypatch)
    conn = FakeConn("up")
    assert integration.send_command(conn, "show clock") == "up"


def test_send_command_profile_reaches_the_raw_tier(monkeypatch):
    _block_import(monkeypatch)
    conn = FakeConn(IP_INT_BRIEF)
    out = integration.send_command(
        conn, "show ip interface brief", profile="updown"
    )
    assert "[omitted:" in out


def test_compact_without_platform_uses_the_core_raw_tier(monkeypatch):
    _block_import(monkeypatch)
    out = integration.compact(
        IP_INT_BRIEF, command="show ip interface brief", platform=None
    )
    core = neterse.render(IP_INT_BRIEF, command="show ip interface brief")
    assert out == min(core, key=lambda c: len(c.text)).text


def test_compact_platform_filter_stays_load_bearing(monkeypatch):
    """An Arista-shaped body must not be claimed by the Arista spec when
    the connection says cisco_ios — the filter must actually flow."""
    from .test_ntc import ARISTA_VLAN

    _block_import(monkeypatch)
    assert integration.compact(
        ARISTA_VLAN, command="show vlan", platform="cisco_ios"
    ) == ARISTA_VLAN
    eos = integration.compact(
        ARISTA_VLAN, command="show vlan", platform="arista_eos"
    )
    assert eos != ARISTA_VLAN and eos.startswith("vlan,name,status,ports")
