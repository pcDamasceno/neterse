#!/usr/bin/env python3
"""Regenerate tests/token_savings_baseline.json under the pinned encoding.

Run this ONLY when the change to the numbers is intentional — a new
family, a corpus extension, or a recorded baseline decision that changes
a family's output (docs/DESIGN.md). CI compares against the committed
file; regenerating to make a red build green without a recorded decision
defeats the gate.

    pip install tiktoken==0.13.0    # the version the committed baseline pins
    python scripts/update_token_baseline.py

A different tiktoken version would rewrite every count in the baseline
(and the recorded ``tiktoken_version``) — a suspicious PR diff for what
should be an additive change — so the script refuses a mismatched
version unless ``--tokenizer-upgrade`` says the bump itself is the
intended, recorded change.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tiktoken  # noqa: E402

from tests.token_metrics import BASELINE_PATH, ENCODING, measure  # noqa: E402


def main(argv=None) -> int:
    upgrade = "--tokenizer-upgrade" in (
        argv if argv is not None else sys.argv[1:]
    )
    if BASELINE_PATH.is_file() and not upgrade:
        pinned = json.loads(BASELINE_PATH.read_text()).get("tiktoken_version")
        if pinned and tiktoken.__version__ != pinned:
            print(
                f"installed tiktoken {tiktoken.__version__} != baseline's "
                f"pinned {pinned} — regenerating would rewrite every count "
                f"in the file. Install tiktoken=={pinned} (what CI runs), "
                "or pass --tokenizer-upgrade if bumping the tokenizer IS "
                "the intended, recorded change (update the CI pin too).",
                file=sys.stderr,
            )
            return 2
    enc = tiktoken.get_encoding(ENCODING)
    fams = measure(enc)
    tot_raw = sum(m["raw_tokens"] for m in fams.values())
    tot_neterse = sum(m["neterse_tokens"] for m in fams.values())
    baseline = {
        "encoding": ENCODING,
        "tiktoken_version": tiktoken.__version__,
        "total_raw_tokens": tot_raw,
        "total_neterse_tokens": tot_neterse,
        "families": fams,
    }
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + "\n")
    print(f"wrote {BASELINE_PATH}")
    print(f"{len(fams)} families: {tot_raw} raw -> {tot_neterse} neterse tokens "
          f"({100 * (1 - tot_neterse / tot_raw):.1f}% saved, {ENCODING})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
