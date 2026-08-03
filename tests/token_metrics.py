"""Shared helpers for the real-tokenizer savings regression (Phase 3).

Runtime neterse never touches a tokenizer — ``Candidate.est_tokens()`` is
chars/4 by decision 8. CI, however, measures the thing we actually claim
to save: tokens under a real, PINNED encoding. These helpers are shared
by the pytest gate (``test_token_savings.py``) and the baseline
regenerator (``scripts/update_token_baseline.py``) so the two can never
disagree about what is measured.

The measured corpus is every family diagonal: the in-module legacy
fixtures plus the file-per-fixture vendor corpus, one representative
(command, body) pair per family, compressed on the default path exactly
as ``optimize()`` ships it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

from neterse import optimize

from .corpus import COMMAND_FIXTURES
from .fixture_corpus import FILE_FIXTURES

ENCODING = "o200k_base"
BASELINE_PATH = Path(__file__).resolve().parent / "token_savings_baseline.json"


def families() -> Dict[str, Tuple[str, str]]:
    """{family label: (command, raw body)} — one diagonal pair each."""
    fams: Dict[str, Tuple[str, str]] = {
        label: (command, body) for label, command, body in COMMAND_FIXTURES
    }
    for f in FILE_FIXTURES:
        fams[f.label] = (f.commands[0], f.body)
    return fams


def measure(enc) -> Dict[str, Dict[str, int]]:
    """Token counts per family under *enc*: raw body vs optimize() output."""
    out: Dict[str, Dict[str, int]] = {}
    for label, (command, body) in sorted(families().items()):
        out[label] = {
            "raw_tokens": len(enc.encode(body)),
            "neterse_tokens": len(enc.encode(optimize(command, body))),
        }
    return out


def load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text())
