#!/usr/bin/env python3
"""Regenerate tests/token_savings_baseline.json under the pinned encoding.

Run this ONLY when the change to the numbers is intentional — a new
family, a corpus extension, or a recorded baseline decision that changes
a family's output (docs/DESIGN.md). CI compares against the committed
file; regenerating to make a red build green without a recorded decision
defeats the gate.

    pip install tiktoken
    python scripts/update_token_baseline.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tiktoken  # noqa: E402

from tests.token_metrics import BASELINE_PATH, ENCODING, measure  # noqa: E402


def main() -> int:
    enc = tiktoken.get_encoding(ENCODING)
    fams = measure(enc)
    tot_raw = sum(m["raw_tokens"] for m in fams.values())
    tot_terse = sum(m["terse_tokens"] for m in fams.values())
    baseline = {
        "encoding": ENCODING,
        "tiktoken_version": tiktoken.__version__,
        "total_raw_tokens": tot_raw,
        "total_terse_tokens": tot_terse,
        "families": fams,
    }
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + "\n")
    print(f"wrote {BASELINE_PATH}")
    print(f"{len(fams)} families: {tot_raw} raw -> {tot_terse} terse tokens "
          f"({100 * (1 - tot_terse / tot_raw):.1f}% saved, {ENCODING})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
