"""Delegation to the spec authors' own encoders (the ``toon``/``gcf`` extras).

Installed, ``toon-format`` and ``gcf-python`` SUPPLEMENT our stdlib
encoders — consulted only for a candidate we declined. What that buys is
the document forms a flat row table cannot express, above all the *named*
table: ``{"employees": [...]}`` is one row holding an array cell to us,
which both our encoders refuse, while the reference writes
``employees[3]{...}`` / ``## employees [3]{...}``.

What it must NOT buy is silent infidelity. Both packages coerce rather
than refuse — NaN becomes ``0``, an unsupported type becomes ``null`` —
so every delegated document is read back through the vendor's own decoder
and dropped unless it reproduces the payload exactly. A candidate
declaring ``dropped_fields == ()`` has to mean it (invariant 4).

Skipped wholesale when the extras are absent, which is the supported
configuration: the runtime dependency list is empty and everything here
fails open.
"""
from __future__ import annotations

import pytest

from neterse import render_parsed
from neterse.parsed import _columns, _gcf_encoded, _reference_encoded, encode

gcf = pytest.importorskip("gcf", reason="needs the `gcf` extra")
toon_format = pytest.importorskip("toon_format", reason="needs the `toon` extra")

WRAPPED = {
    "employees": [
        {"id": 1, "name": "Alice", "department": "Engineering", "salary": 95000},
        {"id": 2, "name": "Bob", "department": "Sales", "salary": 72000},
        {"id": 3, "name": "Carol", "department": "Marketing", "salary": 85000},
    ]
}
ROWS = WRAPPED["employees"]


def _encoded(parsed, profile="default"):
    return {source: text for text, source, _, _ in encode(parsed, profile)}


# ---------------------------------------------------------------------------
# The gap this closes
# ---------------------------------------------------------------------------

def test_a_key_wrapped_row_list_encodes_as_a_named_table():
    """The whole point. Our row model sees one row whose single column
    holds an array — unrepresentable in both specs' tabular forms — so
    before delegation this payload produced no spec candidate at all."""
    encoded = _encoded(WRAPPED)
    assert encoded["parsed:toon"] == (
        "employees[3]{id,name,department,salary}:\n"
        "  1,Alice,Engineering,95000\n"
        "  2,Bob,Sales,72000\n"
        "  3,Carol,Marketing,85000"
    )
    assert encoded["parsed:gcf"] == (
        "GCF profile=generic\n"
        "## employees [3]{id,name,department,salary}\n"
        "1|Alice|Engineering|95000\n"
        "2|Bob|Sales|72000\n"
        "3|Carol|Marketing|85000"
    )


def test_an_api_envelope_encodes_instead_of_declining():
    """A scalar beside the row list — every REST response ever. GCF
    writes the scalar as a preamble line and names the section."""
    envelope = {"totalCount": "2", "imdata": [{"id": 1}, {"id": 2}]}
    lines = _encoded(envelope)["parsed:gcf"].splitlines()
    assert lines[1] == 'totalCount="2"'
    assert lines[2] == "## imdata [2]{id}"


# ---------------------------------------------------------------------------
# Delegation must not disturb what already worked
# ---------------------------------------------------------------------------

def test_shapes_we_can_encode_stay_ours_byte_for_byte():
    """Supplement, not replace: a plain row list still comes from our
    encoder. The bytes agree with the reference anyway — that is what
    makes the rule invisible — but the row model's reading is the one
    that ships, so installing an extra never rewrites settled output."""
    ours = _gcf_encoded(ROWS, _columns(ROWS), ())
    assert _encoded(ROWS)["parsed:gcf"] == ours[0]
    assert ours[0].rstrip("\n") == gcf.encode_generic(ROWS).rstrip("\n")


def test_a_bare_dict_stays_a_one_row_table():
    """The reference would call this an OBJECT and emit `hostname: sw1`
    key-value lines; we call it one ROW. Ours wins, or every existing
    single-dict rendering would silently change shape."""
    row = {"hostname": "sw1", "version": "17.12.1", "uptime": "4w"}
    assert _encoded(row)["parsed:toon"].splitlines()[0] == (
        "[1]{hostname,version,uptime}:"
    )


@pytest.mark.parametrize("shape", [42, "text", ["a", "b"], [], {}, [[1, 2]]],
                         ids=repr)
def test_non_row_shapes_still_yield_nothing(shape):
    """Delegation is scoped to the parsed tier's own domain. The
    reference could encode a bare string list; widening render_parsed's
    contract is a separate decision, not a side effect of an extra."""
    assert render_parsed(shape) == []


# ---------------------------------------------------------------------------
# Fidelity: the vendors coerce, so we verify
# ---------------------------------------------------------------------------

def test_non_finite_floats_are_never_delegated():
    """Both encoders write NaN and ±inf as 0, silently."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert _reference_encoded({"rows": [{"v": bad}, {"v": 1.0}]}) == []


def test_unsupported_types_are_never_delegated():
    """toon-format logs 'Unsupported type ..., converting to null' and
    carries on. Our own encoders stringify instead, so the payload is
    still served — just not by the vendor."""
    class Odd:
        def __str__(self):
            return "odd"

    assert _reference_encoded({"rows": [{"v": Odd()}]}) == []


def test_a_document_that_cannot_be_read_back_is_dropped():
    """The general guard, stated directly: whatever the encoder does, the
    candidate survives only if the vendor's decoder reproduces the
    payload."""
    for text, source, dropped, _ in _reference_encoded(WRAPPED):
        decode = gcf.decode_generic if source == "parsed:gcf" else toon_format.decode
        assert decode(text) == WRAPPED
        assert dropped == ()


def test_an_applied_projection_still_declines():
    """A projection needs the omission marker declared in the document,
    and neither spec has anywhere to put it — delegating would launder a
    lossy rendering into an undeclared one."""
    projected = render_parsed(ROWS, profile="updown")
    assert projected and all(c.source == "parsed:csv" for c in projected)


def test_delegated_candidates_are_declared_lossless_and_gated():
    surviving = {c.source: c for c in render_parsed(WRAPPED)}
    assert {"parsed:toon", "parsed:gcf"} <= set(surviving)
    for candidate in surviving.values():
        assert candidate.dropped_fields == ()
        assert len(candidate.text) < len(
            __import__("json").dumps(WRAPPED, separators=(",", ":"))
        )
