"""Real-tokenizer savings regression (CI gate; skips without tiktoken).

Character parity (test_parity.py) pins WHAT the renderings are; this
suite pins what they're FOR — token savings under a real, pinned
encoding must never silently regress. The baseline is a committed file;
CI installs the pinned tokenizer and compares. Regenerating the baseline
(scripts/update_token_baseline.py) is a recorded decision, exactly like
a byte-parity change.
"""
from __future__ import annotations

import pytest

tiktoken = pytest.importorskip("tiktoken")

from .token_metrics import (  # noqa: E402
    BASELINE_PATH,
    ENCODING,
    load_baseline,
    measure,
)

# Small slack for tokenizer-internal drift across patch releases; a real
# compressor regression moves numbers far more than this.
TOLERANCE = 0.02
TOTAL_SAVINGS_FLOOR = 0.35     # the library's headline claim, enforced


@pytest.fixture(scope="module")
def enc():
    return tiktoken.get_encoding(ENCODING)


@pytest.fixture(scope="module")
def baseline():
    assert BASELINE_PATH.is_file(), (
        "token baseline missing — run scripts/update_token_baseline.py"
    )
    b = load_baseline()
    assert b["encoding"] == ENCODING
    return b


def test_every_family_is_in_the_baseline(enc, baseline):
    measured = measure(enc)
    missing = sorted(set(measured) - set(baseline["families"]))
    stale = sorted(set(baseline["families"]) - set(measured))
    assert not missing, (
        f"families missing from baseline: {missing} — "
        "run scripts/update_token_baseline.py"
    )
    assert not stale, (
        f"baseline carries families the corpus no longer has: {stale}"
    )


def test_no_family_regresses_and_corpus_is_stable(enc, baseline):
    measured = measure(enc)
    for label, m in measured.items():
        b = baseline["families"][label]
        assert m["raw_tokens"] == b["raw_tokens"], (
            f"{label}: raw corpus drifted ({b['raw_tokens']} -> "
            f"{m['raw_tokens']} tokens) — corpus edits require a "
            "baseline regeneration (a recorded decision)"
        )
        allowed = int(b["neterse_tokens"] * (1 + TOLERANCE)) + 1
        assert m["neterse_tokens"] <= allowed, (
            f"{label}: token savings regressed — "
            f"{b['neterse_tokens']} -> {m['neterse_tokens']} tokens"
        )


def test_total_savings_hold_the_headline_floor(enc):
    measured = measure(enc)
    tot_raw = sum(m["raw_tokens"] for m in measured.values())
    tot_neterse = sum(m["neterse_tokens"] for m in measured.values())
    savings = 1 - tot_neterse / tot_raw
    assert savings >= TOTAL_SAVINGS_FLOOR, (
        f"aggregate savings {savings:.1%} fell below the "
        f"{TOTAL_SAVINGS_FLOOR:.0%} floor"
    )
