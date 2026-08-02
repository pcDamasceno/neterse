"""Byte-parity with the frozen pre-extraction baseline.

``legacy_snapshot.py`` is the dbcli module the terse package was extracted
from, frozen at extraction time. This suite replays the full corpus — every
command x every body, including bodies deliberately paired with the wrong
command, plus edge inputs — through the baseline and through ``terse``, and
asserts byte-identical results on the default path (no ``platform`` given).

This is the standing acceptance rule for engine work: spec-engine
conversions may restructure HOW a rendering is produced, never WHAT it is.
An intentional output change for a command family is a new baseline
decision — record it in docs/DESIGN.md, don't quietly edit the snapshot.
"""
from __future__ import annotations

import pytest

from terse import optimize as terse_optimize
from terse import render

from . import legacy_snapshot
from .corpus import ALL_BODIES, ALL_COMMANDS, COMMAND_FIXTURES

CROSS_MATRIX = [
    pytest.param(cmd, body, id=f"c{ci:02d}-b{bi:02d}")
    for ci, cmd in enumerate(ALL_COMMANDS)
    for bi, body in enumerate(ALL_BODIES)
]


@pytest.mark.parametrize("command,body", CROSS_MATRIX)
def test_optimize_byte_parity(command, body):
    assert terse_optimize(command, body) == legacy_snapshot.optimize(command, body)


@pytest.mark.parametrize("command,body", CROSS_MATRIX)
def test_render_is_coherent_with_optimize(command, body):
    """Candidates only ever shrink, and min(render) reproduces optimize."""
    candidates = render(body, command=command)
    for c in candidates:
        assert isinstance(c.text, str)
        assert 0 < len(c.text) < len(body)
    expected = (
        min(candidates, key=lambda c: len(c.text)).text if candidates else body
    )
    assert terse_optimize(command, body) == expected


@pytest.mark.parametrize(
    "label,command,body",
    [pytest.param(*f, id=f[0]) for f in COMMAND_FIXTURES],
)
def test_corpus_diagonal_actually_compresses(label, command, body):
    """Guards corpus liveness: every fixture paired with its own command must
    genuinely shrink, and identically on both sides of the extraction."""
    out = terse_optimize(command, body)
    assert out != body
    assert len(out) < len(body)
    assert out == legacy_snapshot.optimize(command, body)


def test_every_legacy_family_still_covered():
    """Every command the baseline compresses must still find at least one
    matching compressor in terse (count parity is asserted family-by-family
    through the diagonal test; this guards outright loss of a family)."""
    from terse import iter_compressors

    for label, command, _body in COMMAND_FIXTURES:
        assert any(p.search(command) for p, _ in iter_compressors()), (
            f"no terse compressor matches {command!r} ({label})"
        )
