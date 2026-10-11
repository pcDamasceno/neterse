"""Shape normalizers — the vendor/API payload → canonical rows seam.

The registry mirrors :mod:`neterse.sources`: fail-open sniffers tried in
order, custom-first, each returning canonical rows (a non-empty list of
str-keyed dicts) or ``None`` for "not mine". These tests pin that contract
and every built-in shape; a new vendor module adds its cases here.
"""
from __future__ import annotations

from neterse import normalizers
from neterse.normalizers import (
    class_attributes,
    graphql_edges,
    iter_normalizers,
    keyed_dict,
    normalize,
    register_normalizer,
    toon_text,
)


# ---------------------------------------------------------------------------
# Generic keyed-dict ({name: {...}} — the dominant NAPALM getter shape)
# ---------------------------------------------------------------------------

def test_keyed_dict_flattens_name_keyed_mapping():
    rows = keyed_dict({
        "Eth1/1": {"is_up": True, "mtu": 1500},
        "Eth1/2": {"is_up": False, "mtu": 9216},
    })
    assert rows == [
        {"key": "Eth1/1", "is_up": True, "mtu": 1500},
        {"key": "Eth1/2", "is_up": False, "mtu": 9216},
    ]


def test_keyed_dict_declines_scalar_mixed_and_non_dict():
    assert keyed_dict({"hostname": "r1", "os": "9.3"}) is None  # scalar values
    assert keyed_dict({"a": {"x": 1}, "b": "scalar"}) is None   # mixed values
    assert keyed_dict({}) is None                               # empty
    assert keyed_dict([{"a": 1}]) is None                       # not a dict


def test_keyed_dict_key_column_dodges_inner_field():
    assert keyed_dict({"a": {"key": "X", "v": 1}}) == [
        {"_key": "a", "key": "X", "v": 1},
    ]


def test_keyed_dict_tolerates_non_string_outer_keys():
    assert keyed_dict({1: {"name": "default"}, 100: {"name": "data"}}) == [
        {"key": 1, "name": "default"},
        {"key": 100, "name": "data"},
    ]


# ---------------------------------------------------------------------------
# Cisco ACI ({class: {attributes: {...}}} — the APIC imdata object style)
# ---------------------------------------------------------------------------

ACI = [
    {"fabricNode": {"attributes": {"id": "101", "name": "leaf101"}}},
    {"fabricNode": {"attributes": {"id": "102", "name": "leaf102"}}},
]


def test_class_attributes_unwraps_imdata_objects():
    assert class_attributes(ACI) == [
        {"_class": "fabricNode", "id": "101", "name": "leaf101"},
        {"_class": "fabricNode", "id": "102", "name": "leaf102"},
    ]


def test_class_attributes_declines_objects_with_children():
    subtree = [{"fabricNode": {"attributes": {"id": "1"}, "children": []}}]
    assert class_attributes(subtree) is None


def test_class_attributes_declines_non_wrapped_empty_and_non_list():
    assert class_attributes([{"id": "1"}]) is None      # flat dicts, no wrapper
    assert class_attributes([]) is None                 # empty
    assert class_attributes({"imdata": ACI}) is None    # the envelope, not rows


def test_class_attributes_class_column_dodges_attribute():
    assert class_attributes([{"x": {"attributes": {"_class": "collide"}}}]) == [
        {"__class": "x", "_class": "collide"},
    ]


# ---------------------------------------------------------------------------
# Infrahub GraphQL ([{node: {field: {value: ...}}}] — Relay edges, enveloped fields)
# ---------------------------------------------------------------------------

EDGES = [
    {"node": {
        "name": {"value": "CE-CUSTC-01"},
        "serial": {"value": ""},
        "platform": {"node": {"display_label": "SRLINUX"}},
        "tenant": {"node": None},
        "interfaces": {"count": 1, "edges": [
            {"node": {"name": {"value": "ethernet-1/1"}, "mtu": {"value": 9232}}},
        ]},
    }},
    {"node": {
        "name": {"value": "CORE-RR-01"},
        "serial": {"value": None},
        "platform": {"node": {"name": {"value": "IOS"}, "id": "p-2"}},
        "tenant": {"node": {"display_label": "T1"}},
        "interfaces": {"count": 0, "edges": []},
    }},
]


def test_graphql_edges_unwraps_nodes_and_field_envelopes():
    rows = graphql_edges(EDGES)
    assert [r["name"] for r in rows] == ["CE-CUSTC-01", "CORE-RR-01"]
    assert rows[0]["serial"] == "" and rows[1]["serial"] is None  # kept apart
    assert rows[0]["platform"] == "SRLINUX"        # one-field peer: its value
    assert rows[1]["platform"] == {"name": "IOS", "id": "p-2"}  # richer peer: a dict
    assert rows[0]["tenant"] is None and rows[1]["tenant"] == "T1"
    assert rows[1]["interfaces"] == []


def test_graphql_edges_hands_a_nested_connection_back_as_claimable_edges():
    nested = graphql_edges(EDGES)[0]["interfaces"]
    assert graphql_edges(nested) == [{"name": "ethernet-1/1", "mtu": 9232}]


def test_graphql_edges_keeps_envelopes_it_cannot_prove_redundant():
    rows = graphql_edges([{"node": {
        "name": {"value": "r1", "is_protected": True},              # richer attribute
        "peers": {"count": 7, "edges": [{"node": {"id": "a"}}]},    # paginated
    }}])
    assert rows == [{
        "name": {"value": "r1", "is_protected": True},
        "peers": {"count": 7, "edges": [{"node": {"id": "a"}}]},
    }]


def test_graphql_edges_declines_edges_with_data_of_their_own():
    assert graphql_edges([{"node": {"id": "a"}, "cursor": "Y3Vy"}]) is None
    assert graphql_edges([{"node": {"id": "a"}, "properties": {"is_protected": True}}]) is None
    assert graphql_edges([{"node": None}]) is None
    assert graphql_edges([]) is None
    assert graphql_edges({"edges": [{"node": {"id": "a"}}]}) is None   # the list, not the connection


def test_keyed_dict_no_longer_claims_a_graphql_node():
    # graphql_edges sits ahead of keyed_dict, so a node's {field: {...}}
    # map is never misread as a name-keyed table of fields.
    assert normalize(EDGES)[0]["name"] == "CE-CUSTC-01"


# ---------------------------------------------------------------------------
# TOON text inside a JSON string (toonify's root-array forms)
# ---------------------------------------------------------------------------

# Exactly what toonify (the encoder infrahub-mcp uses) writes for these rows.
TOON_LIST = """[2]:
  - index: u1
    name: r1
    serial: 3
    tags: []
    interfaces: [e1,e2]
    tenant: null
    desc: ""
  - index: u2
    name: r2
    serial: ab
    tags: [x]
    interfaces: []
    tenant: T
    desc: "a, b\\nline two"
"""

TOON_TABLE = """[3]{name,mtu,up,note}:
  r1,1500,true,"x: y"
  r2,9000,false,"say \\"hi\\""
  r3,1500,true,"null"
"""


def test_toon_text_reads_the_list_form():
    assert toon_text(TOON_LIST) == [
        {"index": "u1", "name": "r1", "serial": "3", "tags": "[]",
         "interfaces": "[e1,e2]", "tenant": None, "desc": ""},
        {"index": "u2", "name": "r2", "serial": "ab", "tags": "[x]",
         "interfaces": "[]", "tenant": "T", "desc": "a, b\nline two"},
    ]


def test_toon_text_reads_the_tabular_form():
    assert toon_text(TOON_TABLE) == [
        {"name": "r1", "mtu": "1500", "up": True, "note": "x: y"},
        {"name": "r2", "mtu": "9000", "up": False, "note": 'say "hi"'},
        {"name": "r3", "mtu": "1500", "up": True, "note": "null"},  # quoted: a string
    ]


def test_toon_text_declines_nested_documents():
    # A field with no inline value is a nested object or array.
    assert toon_text("[1]:\n  - name: r1\n    meta:\n      a: 1\n") is None
    assert toon_text("[1]:\n  - name: r1\n    ifs[2]{n}:\n      e1\n      e2\n") is None


def test_toon_text_declines_anything_short_of_a_whole_document():
    assert toon_text("[]") is None                                   # no records
    assert toon_text("[3]:\n  - name: r1\n") is None                 # count mismatch
    assert toon_text("[1]{a,b}:\n  1,2,3\n") is None                 # row width
    assert toon_text("[1]{a,b}:\n  1,\"open\n") is None              # unterminated
    assert toon_text("[1]:\n - name: r1\n") is None                  # indentation
    assert toon_text("[1]:\n  - name: r1\nTrailing prose\n") is None
    assert toon_text("[1] is the first footnote") is None            # prose
    assert toon_text("[1]{a,a}:\n  1,2\n") is None                   # duplicate field
    assert toon_text(["[1]:"]) is None                               # not a string


# ---------------------------------------------------------------------------
# The registry itself
# ---------------------------------------------------------------------------

def test_normalize_dispatches_to_the_first_claiming_shape():
    assert normalize(ACI)[0]["_class"] == "fabricNode"
    assert normalize({"Eth1": {"up": True}})[0]["key"] == "Eth1"
    assert normalize("not structured") is None
    assert normalize(42) is None
    assert normalize([]) is None


def test_register_normalizer_wins_over_builtins():
    sentinel = [{"claimed": "by-custom"}]

    @register_normalizer
    def _mine(value):
        return sentinel if value == {"marker": 1} else None

    try:
        assert normalize({"marker": 1}) == sentinel
        assert iter_normalizers()[0] is _mine            # custom tried first
        assert normalize(ACI)[0]["_class"] == "fabricNode"  # built-ins still reached
    finally:
        normalizers.NORMALIZERS.remove(_mine)


def test_a_raising_normalizer_counts_as_not_mine():
    @register_normalizer
    def _boom(value):
        raise RuntimeError("boom")

    try:
        assert normalize(ACI)[0]["_class"] == "fabricNode"  # raiser skipped
        assert normalize("nope") is None
    finally:
        normalizers.NORMALIZERS.remove(_boom)


def test_non_canonical_normalizer_output_is_ignored():
    @register_normalizer
    def _bad(value):
        return [{"ok": 1}, "not a dict"]                 # not canonical rows

    try:
        assert normalize({"x": 1}) is None               # skipped; nothing claims it
    finally:
        normalizers.NORMALIZERS.remove(_bad)
