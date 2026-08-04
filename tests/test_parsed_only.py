"""The rows-only entry points: ``render_parsed`` / ``optimize_parsed``.

For output that arrives ALREADY parsed there is no raw string to gate
against, so the baseline is the compact JSON a consumer would otherwise
send (decision 30). These tests pin that gate, the string passthrough
(netmiko's no-template fallback), and fail-open on every non-row shape.
"""
from __future__ import annotations

import json

import pytest

from neterse import optimize_parsed, render_parsed
from neterse.parsed import encode

ROWS = [
    {"interface": "GigabitEthernet0/0", "ip": "10.0.0.1", "status": "up"},
    {"interface": "GigabitEthernet0/1", "ip": "10.0.0.2", "status": "down"},
    {"interface": "GigabitEthernet0/2", "ip": "unassigned", "status": "down"},
]


def _compact_json(value) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def test_candidates_undercut_the_compact_json_baseline():
    baseline = _compact_json(ROWS)
    candidates = render_parsed(ROWS)
    assert {c.source for c in candidates} == {"parsed:csv", "parsed:toon"}
    for c in candidates:
        assert c.method == "parsed"
        assert 0 < len(c.text) < len(baseline)
        assert c.dropped_fields == ()
        assert c.profile == "default"


def test_texts_are_exactly_the_parsed_tier_encodings():
    by_source = {c.source: c.text for c in render_parsed(ROWS)}
    expected = {source: text for text, source, _, _ in encode(ROWS, "default")}
    assert by_source == expected


def test_optimize_parsed_returns_the_smallest_candidate():
    candidates = render_parsed(ROWS)
    assert optimize_parsed(ROWS) == min(
        candidates, key=lambda c: len(c.text)
    ).text


def test_strings_pass_through_untouched():
    """netmiko's use_textfsm returns the RAW STRING when no template
    matches — it must come back byte-identical, never JSON-quoted."""
    raw = "Interface    IP-Address    Status\nGi0/0    10.0.0.1    up\n"
    assert optimize_parsed(raw) == raw
    assert render_parsed(raw) == []
    assert optimize_parsed("") == ""


@pytest.mark.parametrize(
    "shape",
    [42, 3.5, True, ["a", "b"], [{"k": 1}, "not a row"], [], {}, [[1, 2]]],
    ids=repr,
)
def test_non_row_shapes_fall_back_to_compact_json(shape):
    assert render_parsed(shape) == []
    assert optimize_parsed(shape) == _compact_json(shape)


def test_none_yields_no_candidates():
    assert render_parsed(None) == []
    # json baseline of None is "null" — still the faithful fallback text
    assert optimize_parsed(None) == "null"


def test_single_dict_counts_as_one_row():
    row = {"hostname": "r1", "version": "17.12.1", "uptime": "4 weeks"}
    candidates = render_parsed(row)
    assert candidates, "one row should still undercut its JSON"
    assert optimize_parsed(row) == min(
        candidates, key=lambda c: len(c.text)
    ).text


def test_the_gate_actually_gates():
    """An input where one encoding LOSES to compact JSON: for a tiny
    single row the TOON block's ``[1]{...}:`` overhead exceeds the
    9-char baseline, so only the CSV candidate may survive."""
    row = {"a": "b"}
    baseline = _compact_json(row)
    candidates = render_parsed(row)
    assert [c.source for c in candidates] == ["parsed:csv"]
    assert all(0 < len(c.text) < len(baseline) for c in candidates)


def test_unserializable_values_stringify_via_default_str():
    class Odd:
        def __str__(self):
            return "odd"

    rows = [{"k": Odd()}, {"k": Odd()}]
    candidates = render_parsed(rows)
    assert candidates, "default=str must keep Odd-valued rows encodable"
    for c in candidates:
        assert "odd" in c.text
    assert optimize_parsed(rows) == min(
        candidates, key=lambda c: len(c.text)
    ).text


def test_hostile_objects_never_raise():
    """Fail-open holds even when the input's own __str__/__repr__ raise
    or repr recursion explodes — the netmiko/scrapli drop-ins route
    arbitrary parser output through here and promise not to raise."""
    class BadStr:
        def __str__(self):
            raise RuntimeError("boom from __str__")

    out = optimize_parsed(BadStr())
    assert isinstance(out, str) and "BadStr" in out    # repr still works
    assert render_parsed(BadStr()) == []

    class BadBoth:
        def __str__(self):
            raise RuntimeError("boom str")

        def __repr__(self):
            raise RuntimeError("boom repr")

    out = optimize_parsed([{"k": BadBoth()}])
    assert isinstance(out, str) and out               # object.__repr__ guard

    deep: list = []
    node = deep
    for _ in range(5000):
        node.append([])
        node = node[0]
    assert isinstance(optimize_parsed(deep), str)     # RecursionError path


def test_circular_structures_fail_open():
    loop: dict = {}
    loop["self"] = loop
    assert render_parsed([loop]) == []
    # repr survives recursion; it is the only faithful text left
    assert optimize_parsed([loop]) == str([loop])


def test_profile_projection_declares_and_marks():
    candidates = render_parsed(ROWS, profile="updown")
    assert candidates
    for c in candidates:
        assert c.profile == "updown"
        assert c.dropped_fields == ("ip",)
        assert "[omitted: ip" in c.text


def test_unknown_profile_degrades_to_complete_default():
    assert [c.text for c in render_parsed(ROWS, profile="nope")] == [
        c.text for c in render_parsed(ROWS)
    ]
