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
    iter_normalizers,
    keyed_dict,
    normalize,
    register_normalizer,
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
