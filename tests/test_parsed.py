"""Phase-2 parsed tier: compact encoders over pre-parsed rows.

The acceptance rule comes from the first consumer's seam: it already
emits a competing
``json.dumps(rows)`` candidate, so the projection+encoder path must beat
it on multi-row output character-for-character or the tier is not worth
shipping. That comparison is pinned here, on realistic parser shapes.
"""
from __future__ import annotations

import json

from neterse import optimize, render

from .corpus import (
    IP_INT_BRIEF,
    PARSED_INTF_STATUS,
    PARSED_IP_INT_BRIEF,
    PARSED_NESTED_ROWS,
    STATUS,
)


def _parsed_only(candidates):
    return [c for c in candidates if c.method == "parsed"]


# ---------------------------------------------------------------------------
# Acceptance: beat json.dumps(rows) on multi-row output
# ---------------------------------------------------------------------------

def test_csv_encoder_beats_compact_json_on_multirow_output():
    """The consumer-side competitor is ``json.dumps(rows)`` with compact
    separators (key-per-row). Header-once CSV must undercut it."""
    for raw, rows in (
        (IP_INT_BRIEF, PARSED_IP_INT_BRIEF),
        (STATUS, PARSED_INTF_STATUS),
    ):
        json_len = len(json.dumps(rows, separators=(",", ":"), default=str))
        cands = _parsed_only(render(raw, command="whatever", parsed=rows))
        csv = next(c for c in cands if c.source == "parsed:csv")
        assert len(csv.text) < json_len, (
            f"parsed:csv ({len(csv.text)}) must beat json ({json_len})"
        )


def test_toon_encoder_also_beats_compact_json():
    json_len = len(json.dumps(PARSED_INTF_STATUS, separators=(",", ":")))
    cands = _parsed_only(render(STATUS, command="whatever", parsed=PARSED_INTF_STATUS))
    toon = next(c for c in cands if c.source == "parsed:toon")
    assert len(toon.text) < json_len


# ---------------------------------------------------------------------------
# Encoding shape
# ---------------------------------------------------------------------------

def test_csv_is_header_once_with_one_line_per_row():
    cands = _parsed_only(render(IP_INT_BRIEF, command="x", parsed=PARSED_IP_INT_BRIEF))
    csv = next(c for c in cands if c.source == "parsed:csv")
    lines = csv.text.splitlines()
    assert lines[0] == "interface,ip_address,status,proto"
    assert lines[1] == "GigabitEthernet0/1,10.0.0.1,up,up"
    assert len(lines) == 1 + len(PARSED_IP_INT_BRIEF)
    assert csv.method == "parsed"
    assert csv.dropped_fields == ()        # default profile projects nothing
    assert csv.profile == "default"


def test_toon_carries_explicit_row_count_and_indented_rows():
    cands = _parsed_only(render(IP_INT_BRIEF, command="x", parsed=PARSED_IP_INT_BRIEF))
    toon = next(c for c in cands if c.source == "parsed:toon")
    lines = toon.text.splitlines()
    assert lines[0] == "[3]{interface,ip_address,status,proto}:"
    assert lines[1] == "  GigabitEthernet0/1,10.0.0.1,up,up"
    assert len(lines) == 1 + len(PARSED_IP_INT_BRIEF)


def test_parsed_candidates_append_after_raw_tier_candidates():
    """Ordering contract: registry order first, then parsed — so default
    tie-breaks keep resolving to the raw tier, as always."""
    cands = render(
        IP_INT_BRIEF, command="show ip interface brief", parsed=PARSED_IP_INT_BRIEF
    )
    methods = [c.method for c in cands]
    assert "toon" in methods and "parsed" in methods
    assert methods.index("parsed") > methods.index("toon")
    # and the raw-tier prefix is exactly what render gives without parsed
    without = render(IP_INT_BRIEF, command="show ip interface brief")
    assert [c.text for c in cands[: len(without)]] == [c.text for c in without]


def test_parsed_tier_is_command_independent():
    """One encoder covers every command the parsing ecosystems handle —
    no registry entry needs to match."""
    cands = render(
        IP_INT_BRIEF, command="show some command neterse has never heard of",
        parsed=PARSED_IP_INT_BRIEF,
    )
    assert {c.source for c in cands} == {"parsed:csv", "parsed:toon"}


# ---------------------------------------------------------------------------
# Cell semantics
# ---------------------------------------------------------------------------

def test_nested_values_and_scalars_encode_faithfully():
    raw = "x" * 400  # roomy enough for the shrink gate
    cands = _parsed_only(render(raw, command="x", parsed=PARSED_NESTED_ROWS))
    csv = next(c for c in cands if c.source == "parsed:csv")
    lines = csv.text.splitlines()
    assert lines[0] == "neighbor,as,up,address_family"
    # int → bare, bool → true/false, nested dict → compact JSON cell
    # (quoted, because it carries commas and quotes)
    assert lines[1].startswith("10.0.0.1,65001,true,")
    assert '""ipv4 unicast""' in lines[1]
    assert json.loads(
        lines[1].split("true,", 1)[1][1:-1].replace('""', '"')
    ) == {"ipv4 unicast": {"prefixes": 25}}


def test_missing_keys_and_none_render_as_empty_cells():
    rows = [
        {"interface": "Gi0/1", "status": "up", "description": None},
        {"interface": "Gi0/2", "status": "down", "reason": "admin"},
    ]
    cands = _parsed_only(render("y" * 300, command="x", parsed=rows))
    csv = next(c for c in cands if c.source == "parsed:csv")
    lines = csv.text.splitlines()
    assert lines[0] == "interface,status,description,reason"  # unioned, first-seen order
    assert lines[1] == "Gi0/1,up,,"
    assert lines[2] == "Gi0/2,down,,admin"


def test_cells_with_commas_quotes_and_newlines_are_quoted():
    rows = [{"name": 'a,"b"', "note": "two\nlines"}]
    cands = _parsed_only(render("z" * 200, command="x", parsed=rows))
    csv = next(c for c in cands if c.source == "parsed:csv")
    assert '"a,""b"""' in csv.text
    assert '"two\nlines"' in csv.text


def test_single_dict_is_a_one_row_table():
    row = {"hostname": "sw-access-01", "os": "IOS 15.2(4)E10"}
    cands = _parsed_only(render("w" * 200, command="x", parsed=row))
    toon = next(c for c in cands if c.source == "parsed:toon")
    assert toon.text.splitlines()[0] == "[1]{hostname,os}:"


# ---------------------------------------------------------------------------
# Fail-open
# ---------------------------------------------------------------------------

def test_malformed_parsed_yields_no_candidates_and_never_raises():
    raw = "some raw output that nothing compresses"
    for bad in (
        "a string", 42, 3.14, True,
        [], {},                                  # empty
        ["a", "b"], [{"k": 1}, "not a dict"],    # mixed
        [{1: "non-string key"}],
        object(),
    ):
        assert render(raw, command="no match", parsed=bad) == []


def test_parsed_candidates_respect_the_shrink_gate():
    """Candidates only ever shrink: when the raw output is already smaller
    than any encoding of the rows, the parsed tier stays silent."""
    tiny_raw = "up"
    assert render(tiny_raw, command="x", parsed=PARSED_IP_INT_BRIEF) == []


def test_optimize_is_untouched_by_the_parsed_tier():
    """optimize() takes no parsed rows — its byte-parity contract cannot
    move (the full cross-matrix in test_parity.py pins this too)."""
    assert optimize("show ip interface brief", IP_INT_BRIEF) == \
        min(
            render(IP_INT_BRIEF, command="show ip interface brief"),
            key=lambda c: len(c.text),
        ).text
