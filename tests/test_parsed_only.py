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
from neterse.parsed import encode, _flatten_keyed, _rows

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


# ---------------------------------------------------------------------------
# Keyed-dict flattening (the dominant NAPALM getter shape: {name: {...}})
# ---------------------------------------------------------------------------

# get_interfaces / get_optics / get_users all return this: a dict keyed by
# name whose values are uniform attribute dicts. Left as one mega-row it never
# shrinks; flattened it is an ordinary table.
KEYED_GETTER = {
    "Ethernet1/1": {"is_up": True, "description": "uplink", "mtu": 1500},
    "Ethernet1/2": {"is_up": False, "description": "", "mtu": 9216},
}


def test_keyed_dict_flattens_to_one_row_per_entry():
    candidates = render_parsed(KEYED_GETTER)
    assert {c.source for c in candidates} == {"parsed:csv", "parsed:toon"}
    csv = next(c for c in candidates if c.source == "parsed:csv")
    lines = csv.text.splitlines()
    assert lines[0] == "key,is_up,description,mtu"      # outer key leads
    assert lines[1] == "Ethernet1/1,true,uplink,1500"
    assert lines[2] == "Ethernet1/2,false,,9216"
    assert len(lines) == 1 + len(KEYED_GETTER)


def test_keyed_flatten_beats_the_nested_json_baseline_losslessly():
    baseline = _compact_json(KEYED_GETTER)
    best = optimize_parsed(KEYED_GETTER)
    assert 0 < len(best) < len(baseline)
    for c in render_parsed(KEYED_GETTER):
        assert c.dropped_fields == ()                   # key kept → lossless
        assert c.profile == "default"
    # every outer name and every inner value survives the round trip
    for name, attrs in KEYED_GETTER.items():
        assert name in best
        for val in attrs.values():
            if val not in (True, False, ""):
                assert str(val) in best


def test_scalar_or_mixed_valued_dict_stays_a_single_row():
    """get_facts / get_snmp_information shapes — not every value is a dict —
    must NOT be flattened; _rows keeps them as one row keyed by their own
    fields (asserted on the helper, since single-row CSV need not shrink)."""
    facts = {"hostname": "r1", "os": "9.3", "interface_list": ["Eth1/1"]}
    snmp = {"chassis_id": "abc", "community": {"public": {"mode": "ro"}}}
    for obj in (facts, snmp):
        assert _flatten_keyed(obj) is None
        assert _rows(obj) == [obj]


def test_flatten_handles_non_string_outer_keys():
    """VLAN ids arrive as ints; without flattening the tier declines
    (int keys aren't str-keyed rows), so this is pure upside."""
    vlans = {1: {"name": "default"}, 100: {"name": "data"}}
    candidates = render_parsed(vlans)
    assert candidates, "int-keyed dict should now flatten and shrink"
    csv = next(c for c in candidates if c.source == "parsed:csv")
    lines = csv.text.splitlines()
    assert lines[0] == "key,name"
    assert lines[1] == "1,default"
    assert lines[2] == "100,data"


def test_key_column_name_avoids_colliding_with_an_inner_field():
    keyed = {"a": {"key": "X", "v": 1}, "b": {"key": "Y", "v": 2}}
    csv = next(c for c in render_parsed(keyed) if c.source == "parsed:csv")
    lines = csv.text.splitlines()
    assert lines[0] == "_key,key,v"                     # underscore to dodge
    assert lines[1] == "a,X,1"


def test_dict_with_a_non_dict_or_exotic_value_is_not_flattened():
    """One non-dict value, or a dict with non-string inner keys, disqualifies
    the whole mapping from flattening — it falls back to the single-row
    path (asserted on the helpers, deterministic regardless of shrink)."""
    partial = {"a": {"x": 1}, "b": "scalar"}            # mixed value types
    assert _flatten_keyed(partial) is None
    assert _rows(partial) == [partial]                  # single row, not "key,x"
    exotic = {"a": {1: "int-key"}, "b": {2: "int-key"}}  # inner keys not str
    assert _flatten_keyed(exotic) is None
