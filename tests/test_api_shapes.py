"""The vendor API-shape corpus: real controller payloads, auto-covered.

``tests/fixtures/api_shapes/<vendor>/<name>.json`` holds tool/API
responses exactly as a controller's MCP server or REST client returned
them (RFC1918 lab fabrics — no credentials, no public addresses).
Every file dropped here is asserted against the whole promise chain with
no per-vendor test code:

* it SHRINKS — the smallest candidate strictly undercuts the compact
  JSON a consumer would otherwise put in context;
* it stays LOSSLESS — the winner declares ``dropped_fields == ()`` and
  every identity value (names, dns, addresses) from the payload appears
  verbatim in the rendering;
* it FAILS OPEN — ``optimize_parsed`` never raises, whatever the shape.

This is the contribution path for a new vendor (decision 40): drop a
capture, run pytest. The generic engine — recursive sections encoding,
:mod:`neterse.normalizers`, constant-column folding — covers most
envelopes with zero vendor code (the SD-WAN files here needed none);
when the assertions fail or the shrink disappoints, and only then, write
a normalizer (see CONTRIBUTING.md).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from neterse import optimize_parsed, render_parsed

FIXTURES = Path(__file__).parent / "fixtures" / "api_shapes"
CAPTURES = sorted(FIXTURES.glob("*/*.json"))

#: keys whose string values identify objects — the data an agent acts on,
#: so the data whose loss would be catastrophic rather than cosmetic.
IDENTITY_KEYS = {"name", "dn", "host-name", "hostname", "system-ip", "uuid"}


def _identity_values(node, out: set) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in IDENTITY_KEYS and isinstance(value, str) and value:
                out.add(value)
            _identity_values(value, out)
    elif isinstance(node, list):
        for value in node:
            _identity_values(value, out)


def _ids(name: str) -> str:
    return f"{name}"


@pytest.fixture(params=CAPTURES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def capture(request):
    return json.loads(request.param.read_text())


def test_corpus_is_not_empty():
    assert CAPTURES, "the api_shapes corpus vanished"


def test_every_capture_shrinks_below_its_compact_json(capture):
    baseline = json.dumps(capture, separators=(",", ":"), default=str)
    best = optimize_parsed(capture)
    assert len(best) < len(baseline), "capture no longer shrinks"


def test_the_winner_is_declared_lossless(capture):
    candidates = render_parsed(capture)
    assert candidates
    winner = min(candidates, key=lambda c: len(c.text))
    assert winner.dropped_fields == ()
    assert winner.profile == "default"


def test_every_identity_value_survives_verbatim(capture):
    """Object names, dns and addresses must appear in the rendering
    byte-for-byte. Values CSV-quoting would rewrite (embedded quotes or
    newlines) are excluded — the quoting is reversible, but 'verbatim'
    would be the wrong assertion for them."""
    wanted: set = set()
    _identity_values(capture, wanted)
    assert wanted, "fixture carries no identity values to check"
    best = optimize_parsed(capture)
    missing = {
        value for value in wanted
        if '"' not in value and "\n" not in value and value not in best
    }
    assert not missing, f"identity values lost in rendering: {sorted(missing)}"
