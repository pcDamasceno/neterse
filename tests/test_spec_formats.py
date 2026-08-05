"""Spec-compliant interop candidates: ``parsed:toon`` and ``parsed:gcf``.

Both formats are pinned against their published specifications — TOON
(toon-format SPEC.md, Working Draft 4.1, §9.3 tabular form) and GCF
(blackwell-systems/gcf SPEC.md, v3.4.1, generic profile) — not against
what happens to be convenient to emit. The contract under test:

* an emitted document is CONFORMING (exact header forms, JSON-grammar
  quoting, canonical numbers, TOON ``null`` vs GCF ``-``/``~``);
* anything unrepresentable in a conforming document DECLINES the
  candidate instead of bending the spec (array cells, non-uniform
  nesting, applied projections — the omission marker has no in-document
  home in either format);
* the usual rules hold: shrink gate, dropped_fields declaration,
  fail-open on hostile values.

Decline/quoting semantics are asserted on ``encode()`` (pre-gate, so
document size can't mask them); gate behavior is asserted on
``render_parsed``.
"""
from __future__ import annotations

import json

from neterse import render_parsed
from neterse.parsed import (
    _gcf_encoded,
    _number_literal,
    _toon_encoded,
    encode,
)

ROWS = [
    {"interface": "GigabitEthernet0/0", "ip": "10.0.0.1", "status": "up"},
    {"interface": "GigabitEthernet0/1", "ip": "10.0.0.2", "status": "down"},
]


def _by_source(parsed, profile="default"):
    return {c.source: c for c in render_parsed(parsed, profile=profile)}


def _encoded(parsed):
    return {source: text for text, source, _, _ in encode(parsed, "default")}


# ---------------------------------------------------------------------------
# Conforming documents, pinned byte-for-byte
# ---------------------------------------------------------------------------

def test_toon_document_is_the_spec_root_tabular_form():
    toon = _by_source(ROWS)["parsed:toon"]
    assert toon.text == "\n".join([
        "[2]{interface,ip,status}:",
        "  GigabitEthernet0/0,10.0.0.1,up",
        "  GigabitEthernet0/1,10.0.0.2,down",
    ])
    assert toon.dropped_fields == () and toon.profile == "default"


def test_gcf_document_is_the_spec_generic_profile():
    gcf = _by_source(ROWS)["parsed:gcf"]
    assert gcf.text == "\n".join([
        "GCF profile=generic",
        "## [2]{interface,ip,status}",
        "GigabitEthernet0/0|10.0.0.1|up",
        "GigabitEthernet0/1|10.0.0.2|down",
    ])
    assert gcf.dropped_fields == () and gcf.profile == "default"


def test_toon_folds_nested_uniform_columns_into_field_groups():
    """§9.3 nested field groups: a column of uniform non-empty objects
    goes INTO the header, cells depth-first — the shape that used to be
    JSON-blobbed into one cell."""
    rows = [
        {"neighbor": "10.0.0.1", "as": 65001, "up": True,
         "address_family": {"ipv4 unicast": {"prefixes": 25}}},
        {"neighbor": "10.0.0.5", "as": 65002, "up": False,
         "address_family": {"ipv4 unicast": {"prefixes": 0}}},
    ]
    toon = _by_source(rows)["parsed:toon"]
    assert toon.text == "\n".join([
        '[2]{neighbor,as,up,address_family{"ipv4 unicast"{prefixes}}}:',
        "  10.0.0.1,65001,true,25",
        "  10.0.0.5,65002,false,0",
    ])


def test_gcf_flattens_nested_uniform_columns_into_path_columns():
    """§7.4.6: identical key sets with scalar leaves flatten into quoted
    ``parent>child`` path columns."""
    rows = [
        {"id": "ORD-1", "customer": {"name": "Ada", "tier": "gold"}},
        {"id": "ORD-2", "customer": {"name": "Bob", "tier": "basic"}},
    ]
    gcf = _by_source(rows)["parsed:gcf"]
    assert gcf.text == "\n".join([
        "GCF profile=generic",
        '## [2]{id,"customer>name","customer>tier"}',
        "ORD-1|Ada|gold",
        "ORD-2|Bob|basic",
    ])


def test_gcf_distinguishes_null_from_absent():
    """The one thing GCF represents MORE faithfully than our CSV, which
    renders both as an empty cell: ``-`` is null, ``~`` is a key the
    source row never had."""
    rows = [
        {"intf": "Gi0/1", "desc": None, "err": "crc"},
        {"intf": "Gi0/2", "desc": "uplink"},
    ]
    gcf = _encoded(rows)["parsed:gcf"]
    assert gcf.splitlines()[2:] == ["Gi0/1|-|crc", "Gi0/2|uplink|~"]


def test_toon_requires_identical_key_sets():
    """§9.3: differing key sets disqualify tabular form. We DECLINE
    rather than fall back to the (larger) list form — materializing a
    missing key as ``null`` would fabricate data. GCF's ``~`` handles
    absence natively, so it still renders."""
    rows = [{"a": "x", "b": "y"}, {"a": "z"}]
    sources = _encoded(rows)
    assert "parsed:toon" not in sources
    assert sources["parsed:gcf"].splitlines()[2:] == ["x|y", "z|~"]


# ---------------------------------------------------------------------------
# Scalar grammar: quoting, escaping, canonical numbers
# ---------------------------------------------------------------------------

def test_strings_a_decoder_would_mistype_are_quoted():
    """Both specs: a string matching the number grammar or a keyword
    must be quoted to come back as a string. TextFSM emits ONLY strings,
    so this is the common case, not the corner."""
    rows = [{"vlan": "80", "mode": "true", "state": "null", "cost": "1e3"}]
    encoded = _encoded(rows)
    assert encoded["parsed:toon"] == (
        '[1]{vlan,mode,state,cost}:\n  "80","true","null","1e3"'
    )
    # GCF's null token is "-", so the STRING "null" needs no quoting there
    assert encoded["parsed:gcf"].splitlines()[2] == '"80"|"true"|null|"1e3"'


def test_each_formats_own_keywords_quote_and_no_others():
    """GCF's structural tokens (``-``/``~``/``^``) are plain strings in
    TOON; TOON's ``null`` keyword is a plain string in GCF. Each format
    quotes exactly its own."""
    marks = [{"a": "-", "b": "~", "c": "^", "d": "null"}]
    encoded = _encoded(marks)
    assert encoded["parsed:gcf"].splitlines()[2] == '"-"|"~"|"^"|null'
    assert encoded["parsed:toon"].splitlines()[1] == '  "-",~,^,"null"'


def test_delimiter_and_structural_characters_quote_and_escape():
    rows = [{
        "name": "a,b",              # TOON delimiter
        "pipe": "c|d",              # GCF delimiter
        "colon": "e:f",             # TOON structural
        "quote": 'g"h',             # both: JSON escape
        "nl": "i\nj",               # both: control escape
        "dash": "--",               # TOON: leading hyphen
    }]
    encoded = _encoded(rows)
    assert encoded["parsed:toon"].splitlines()[1] == (
        '  "a,b",c|d,"e:f","g\\"h","i\\nj","--"'
    )
    assert encoded["parsed:gcf"].splitlines()[2] == (
        'a,b|"c|d"|e:f|"g\\"h"|"i\\nj"|--'
    )


def test_field_names_follow_each_specs_bare_key_grammar():
    rows = [{"ok_name": "1", "has space": "2", "dotted.name": "3"}] * 2
    encoded = _encoded(rows)
    #                        TOON bare keys allow dots; spaces quote
    assert encoded["parsed:toon"].splitlines()[0] == (
        '[2]{ok_name,"has space",dotted.name}:'
    )
    #                        GCF bare keys do NOT allow dots
    assert encoded["parsed:gcf"].splitlines()[1] == (
        '## [2]{ok_name,"has space","dotted.name"}'
    )


def test_numbers_encode_canonically():
    assert _number_literal(42) == "42"
    assert _number_literal(-7) == "-7"
    assert _number_literal(3.0) == "3"              # zero fraction → integer
    assert _number_literal(-0.0) == "0"
    assert _number_literal(3.14) == "3.14"
    assert _number_literal(1.5e-5) == "0.000015"    # in range → no exponent
    assert _number_literal(1e16) == "10000000000000000"
    assert _number_literal(1.25e-7) == "1.25e-7"    # out of range → exponent
    assert _number_literal(1e21) == "1e21"
    assert _number_literal(float("nan")) is None    # caller maps to its null
    assert _number_literal(float("inf")) is None


def test_non_finite_floats_become_each_formats_null():
    rows = [{"v": float("nan"), "w": 1.0}]
    encoded = _encoded(rows)
    assert encoded["parsed:toon"] == "[1]{v,w}:\n  null,1"
    assert encoded["parsed:gcf"].splitlines()[2] == "-|1"


def test_true_booleans_and_null_are_bare_literals():
    rows = [{"up": True, "fast": False, "why": None}]
    encoded = _encoded(rows)
    assert encoded["parsed:toon"] == "[1]{up,fast,why}:\n  true,false,null"
    assert encoded["parsed:gcf"].splitlines()[2] == "true|false|-"


# ---------------------------------------------------------------------------
# Declines: conformance beats coverage
# ---------------------------------------------------------------------------

def test_array_cells_decline_both_spec_formats():
    """Neither §9.3 nor the generic profile can hold a list in a cell
    (TOON: disqualifies tabular; GCF: needs attachment syntax we don't
    emit). CSV keeps covering the shape with its JSON-blobbed cell."""
    rows = [{"intf": "Gi0/1", "members": ["Gi0/2", "Gi0/3"]}]
    assert set(_encoded(rows)) == {"parsed:csv"}


def test_non_uniform_nesting_declines_folding_formats():
    for rows in (
        [{"id": "1", "meta": {"a": "x"}}, {"id": "2", "meta": {"b": "y"}}],
        [{"id": "1", "meta": {"a": "x"}}, {"id": "2", "meta": None}],
    ):
        assert set(_encoded(rows)) == {"parsed:csv"}


def test_empty_object_cells_decline_both():
    rows = [{"id": "1", "meta": {}}] * 2
    assert set(_encoded(rows)) == {"parsed:csv"}


def test_reserved_path_character_in_a_field_name_declines_gcf_only():
    rows = [{"a>b": "x"}] * 2
    sources = _encoded(rows)
    assert "parsed:gcf" not in sources
    # TOON just quotes the key — still a conforming document
    assert sources["parsed:toon"].splitlines()[0] == '[2]{"a>b"}:'


def test_applied_projection_declines_both():
    """dropped_fields must be declared IN the rendering (invariant 4),
    and neither spec gives the marker an in-document home — TOON forbids
    encoder comments and trailing content outright. So under a profile
    that actually drops fields, only CSV renders."""
    projected = render_parsed(ROWS, profile="updown")
    assert projected and all(c.source == "parsed:csv" for c in projected)
    # ...but a profile that drops NOTHING is the complete default
    # encoding, and both spec formats render as usual.
    assert set(_by_source(ROWS, profile="nonexistent")) == {
        "parsed:csv", "parsed:toon", "parsed:gcf",
    }


def test_the_shrink_gate_still_gates_the_spec_formats():
    """A tiny single row: both spec documents exceed the 9-char compact
    JSON baseline and must not surface from render_parsed."""
    assert [c.source for c in render_parsed({"a": "b"})] == ["parsed:csv"]


def test_single_row_gcf_never_beats_compact_json_and_stays_gated():
    """On one row the generic profile re-spells JSON's per-object keys
    as a header AND pays the preamble — it cannot shrink, and the gate
    must keep it out of render_parsed even though encode() emits it."""
    row = {"hostname": "sw1", "version": "17.12.1", "uptime": "4w"}
    assert "parsed:gcf" in _encoded([row])
    assert "parsed:gcf" not in _by_source([row])


# ---------------------------------------------------------------------------
# Fail-open
# ---------------------------------------------------------------------------

def test_hostile_cell_values_decline_instead_of_raising():
    class BadStr:
        def __str__(self):
            raise RuntimeError("boom")

    rows = [{"k": BadStr()}]
    assert _toon_encoded(rows, ["k"], ()) is None
    assert _gcf_encoded(rows, ["k"], ()) is None


def test_stringifiable_exotics_encode_like_the_csv_cell():
    class Odd:
        def __str__(self):
            return "odd"

    encoded = _encoded([{"k": Odd()}])
    assert encoded["parsed:toon"].splitlines()[1] == "  odd"
    assert encoded["parsed:gcf"].splitlines()[2] == "odd"


def test_encode_output_stays_decodable_as_data():
    """Belt-and-braces: the TOON rows and GCF rows must carry exactly the
    source values (order preserved), read back with a minimal split —
    the quoting rules above guarantee the split is unambiguous for these
    plain cells."""
    encoded = _encoded(ROWS)
    toon_body = [line.strip() for line in encoded["parsed:toon"].splitlines()[1:]]
    assert [cell for line in toon_body for cell in line.split(",")] == [
        v for row in ROWS for v in row.values()
    ]
    gcf_body = encoded["parsed:gcf"].splitlines()[2:]
    assert [cell for line in gcf_body for cell in line.split("|")] == [
        v for row in ROWS for v in row.values()
    ]


def test_surfaced_candidates_undercut_the_compact_json_baseline():
    """Whenever the spec formats surface from render_parsed they are
    strictly smaller than the baseline — pinned explicitly so a future
    header change can't silently regress."""
    baseline = len(json.dumps(ROWS, separators=(",", ":")))
    surfaced = render_parsed(ROWS)
    assert {c.source for c in surfaced} >= {"parsed:toon", "parsed:gcf"}
    for c in surfaced:
        assert 0 < len(c.text) < baseline
