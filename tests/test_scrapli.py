"""``neterse.scrapli`` — the duck-typed scrapli drop-in (decision 31).

scrapli is never a test dependency: a fake carries the Response surface
the integration reads (``result``, ``channel_input``,
``textfsm_platform``, ``textfsm_parse_output()``). Contracts pinned
here: both tiers compete when the response parses, every parse-failure
mode degrades to the raw tier, the driver's platform string drives the
skip filter, and nothing ever enlarges.
"""
from __future__ import annotations

import neterse
from neterse import scrapli as integration

from .corpus import IP_INT_BRIEF
from .test_ntc import ARISTA_VLAN, ROWS


class FakeResponse:
    def __init__(
        self,
        result,
        channel_input,
        textfsm_platform="cisco_iosxe",
        rows=None,
        parse_raises=False,
    ):
        self.result = result
        self.channel_input = channel_input
        self.textfsm_platform = textfsm_platform
        self._rows = rows
        self._parse_raises = parse_raises

    def textfsm_parse_output(self):
        if self._parse_raises:
            raise Exception("textfsm extra not installed")
        return self._rows


def test_rows_of_accepts_row_shaped_output_only():
    ok = FakeResponse("x", "show x", rows=ROWS)
    assert integration.rows_of(ok) == ROWS
    for bad in (
        FakeResponse("x", "show x", rows=[]),          # scrapli's no-template value
        FakeResponse("x", "show x", rows="raw text"),
        FakeResponse("x", "show x", rows=[["a", "b"]]),  # to_dict=False shape
        FakeResponse("x", "show x", parse_raises=True),
        object(),                                       # no parse method at all
    ):
        assert integration.rows_of(bad) is None


def test_compact_lets_both_tiers_compete():
    response = FakeResponse(IP_INT_BRIEF, "show ip interface brief", rows=ROWS)
    candidates = integration.render(response)
    assert {c.method for c in candidates} == {"toon", "parsed"}
    assert integration.compact(response) == min(
        candidates, key=lambda c: len(c.text)
    ).text


def test_parse_failure_degrades_to_the_raw_tier():
    response = FakeResponse(
        IP_INT_BRIEF, "show ip interface brief", parse_raises=True
    )
    core = neterse.render(
        IP_INT_BRIEF, command="show ip interface brief",
        platform="cisco_iosxe",
    )
    assert integration.render(response) == core
    assert integration.compact(response) == min(
        core, key=lambda c: len(c.text)
    ).text


def test_textfsm_platform_drives_the_skip_filter():
    """cisco_iosxe must not be claimed by the Arista vlan spec; the same
    body under an arista_eos platform is."""
    wrong = FakeResponse(ARISTA_VLAN, "show vlan", textfsm_platform="cisco_iosxe")
    assert integration.render(wrong) == []
    assert integration.compact(wrong) == ARISTA_VLAN
    right = FakeResponse(ARISTA_VLAN, "show vlan", textfsm_platform="arista_eos")
    assert integration.compact(right).startswith("vlan,name,status,ports")


def test_empty_platform_means_try_everything():
    response = FakeResponse(
        IP_INT_BRIEF, "show ip interface brief", textfsm_platform=""
    )
    assert integration.render(response) == neterse.render(
        IP_INT_BRIEF, command="show ip interface brief"
    )


def test_response_without_parse_method_still_compacts():
    class Bare:
        result = IP_INT_BRIEF
        channel_input = "show ip interface brief"

    out = integration.compact(Bare())
    assert 0 < len(out) < len(IP_INT_BRIEF)


def test_profile_passes_through():
    response = FakeResponse(IP_INT_BRIEF, "show ip interface brief", rows=ROWS)
    candidates = integration.render(response, profile="updown")
    assert candidates, "profile request must not kill the candidates"
    for c in candidates:
        assert c.profile == "updown"
        assert "[omitted:" in c.text
    assert "[omitted:" in integration.compact(response, profile="updown")


def test_nothing_shrinks_returns_result_unchanged():
    assert integration.compact(FakeResponse("up", "show clock")) == "up"


def test_non_string_result_fails_open():
    assert integration.render(FakeResponse(None, "show x")) == []
    assert integration.compact(FakeResponse(None, "show x")) == ""
    assert integration.compact(FakeResponse("", "show x")) == ""
