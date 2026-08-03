"""Behavioral suite over the file-per-fixture corpus (post-baseline families).

These families postdate the frozen baseline, so byte-parity does not
apply (decision 15); what IS enforced, automatically, for every fixture
that lands in ``tests/fixtures/``:

* the diagonal genuinely shrinks — with the fixture's platform and on
  the default path alike;
* the family's own spec produces the winning candidate (no accidental
  coverage via a false match);
* a wrong platform can only ever remove the family's candidates, never
  corrupt them;
* the full command x body cross-matrix (including the legacy corpus
  bodies and edge inputs) stays fail-open through terse itself.

The legacy parity cross-matrix in ``test_parity.py`` separately polices
that these post-baseline entries never change a legacy pair's result.
"""
from __future__ import annotations

import pytest

from terse import render

from .corpus import ALL_BODIES, EDGE_INPUTS
from .fixture_corpus import FILE_FIXTURES, FIXTURE_ROOT

DIAGONAL = [
    pytest.param(f, cmd, id=f"{f.label}:{cmd}")
    for f in FILE_FIXTURES
    for cmd in f.commands
]

ALL_FIXTURE_COMMANDS = sorted({cmd for f in FILE_FIXTURES for cmd in f.commands})
ALL_FIXTURE_BODIES = [f.body for f in FILE_FIXTURES]


def test_layout_is_well_formed():
    assert FIXTURE_ROOT.is_dir(), "tests/fixtures/ missing"
    assert len(FILE_FIXTURES) >= 9
    labels = [f.label for f in FILE_FIXTURES]
    assert len(labels) == len(set(labels)), "duplicate fixture families"
    for f in FILE_FIXTURES:
        assert f.commands, f"{f.label}: empty commands.txt"
        assert f.body.strip(), f"{f.label}: empty raw.txt"
        assert (FIXTURE_ROOT / f.label / "commands.txt").is_file()


@pytest.mark.parametrize("fixture,command", DIAGONAL)
def test_diagonal_shrinks_with_platform_and_without(fixture, command):
    for platform in (fixture.platform, None):
        candidates = render(fixture.body, command=command, platform=platform)
        assert candidates, (
            f"{fixture.label}: no candidate for {command!r} "
            f"(platform={platform!r})"
        )
        best = min(candidates, key=lambda c: len(c.text))
        assert 0 < len(best.text) < len(fixture.body)


@pytest.mark.parametrize("fixture,command", DIAGONAL)
def test_diagonal_winner_is_the_familys_own_spec(fixture, command):
    """Coverage must come from the family's own vendor entry, not a false
    match that happens to shrink — that would report coverage that
    doesn't survive a platform filter or a format drift. Matching is by
    vendor stem: a cisco_ios fixture may be won by `spec:cisco/...` or
    `spec:cisco_ios/...` alike."""
    vendor = fixture.platform.split("_")[0]
    candidates = render(fixture.body, command=command, platform=fixture.platform)
    best = min(candidates, key=lambda c: len(c.text))
    assert best.source.startswith(f"spec:{vendor}"), (
        f"{fixture.label}: winner was {best.source}"
    )


def test_wrong_platform_removes_the_vendor_candidates():
    for f in FILE_FIXTURES:
        vendor = f.platform.split("_")[0]
        wrong = "cisco_ios" if vendor != "cisco" else "juniper_junos"
        for cmd in f.commands:
            for c in render(f.body, command=cmd, platform=wrong):
                assert not c.source.startswith(f"spec:{vendor}"), (
                    f"{f.label}: {c.source} survived platform={wrong}"
                )


@pytest.mark.parametrize(
    "command", ALL_FIXTURE_COMMANDS, ids=lambda c: c.replace(" ", "_")
)
def test_cross_matrix_stays_failopen(command):
    """Every fixture command against every body in BOTH corpora (and the
    edge inputs): never raise, and any candidate strictly shrinks."""
    for body in ALL_FIXTURE_BODIES + ALL_BODIES + EDGE_INPUTS:
        for c in render(body, command=command):
            assert isinstance(c.text, str)
            assert 0 < len(c.text) < len(body)


def test_audit_tool_reads_this_layout():
    """The audit CLI ingests the fixture tree directly and reports full
    coverage over it — the contribution flow's smoke test."""
    import io

    from terse.audit import load_samples, run_report

    samples = load_samples([str(FIXTURE_ROOT)], command=None)
    assert len(samples) >= sum(len(f.commands) for f in FILE_FIXTURES)
    buf = io.StringIO()
    total_red = run_report(samples, show=0, out=buf)
    report = buf.getvalue()
    assert total_red > 20.0
    assert "NO COMPRESSOR" not in report
    assert "false-match" not in report
