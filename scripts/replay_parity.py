#!/usr/bin/env python3
"""Replay a corpus through the frozen baseline AND current neterse; report
any byte-level difference on the default path.

A port of the original replay_parity tool without the checkpointer
plumbing: samples come from the same sources the
audit tool reads (JSONL with command/raw fields, fixture directories,
stdin). This proves on real data what tests/test_parity.py proves on
fixtures. Diffs must be confined to command families you intentionally
changed — anything else is a regression.

This lives in scripts/, not in the package: the frozen baseline
(tests/legacy_snapshot.py) is a repo artifact and is deliberately not
shipped in the wheel. Run from the repo root:

    python scripts/replay_parity.py corpus.jsonl [--max-diffs 3]
    python scripts/replay_parity.py tests/fixtures
    some-exporter | python scripts/replay_parity.py -

Note on inputs (carried over verbatim): captured tool messages may hold
the representation that WON smallest-wins (raw, compressed, or parsed
JSON), not necessarily raw device text. That is fine for parity —
optimize() must behave identically on ANY input string — but a golden
RAW corpus must be captured with optimization disabled.

Exit status: 0 = parity everywhere, 1 = at least one diff (CI-friendly).
"""
from __future__ import annotations

import argparse
import difflib
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from neterse import optimize as current_optimize            # noqa: E402
from neterse.audit import load_samples                      # noqa: E402
from tests.legacy_snapshot import optimize as baseline_optimize  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "paths", nargs="+",
        help="JSONL file(s), fixture directory(ies), or - for stdin JSONL",
    )
    ap.add_argument("--command", help="command string for raw capture files")
    ap.add_argument("--max-diffs", type=int, default=3,
                    help="print a unified diff for the first N mismatches")
    args = ap.parse_args(argv)

    samples = load_samples(args.paths, args.command)
    print(f"replaying {len(samples)} samples through baseline and neterse")

    diffs = 0
    per_cmd: dict = defaultdict(int)
    for command, _platform, body in samples:
        # Parity is defined on the DEFAULT path — platform is a
        # post-baseline addition the baseline doesn't know; it must never
        # change bytes here, so it is deliberately not passed.
        base = baseline_optimize(command, body)
        cur = current_optimize(command, body)
        if base == cur:
            continue
        diffs += 1
        per_cmd[command] += 1
        if diffs <= args.max_diffs:
            print(f"\nDIFF #{diffs}  cmd={command!r}  "
                  f"baseline={len(base)}ch current={len(cur)}ch")
            for line in difflib.unified_diff(
                base.splitlines(), cur.splitlines(),
                "baseline", "current", lineterm="", n=2,
            ):
                print("  " + line)

    if diffs:
        print(f"\nPARITY FAILED: {diffs}/{len(samples)} outputs differ")
        for command, n in sorted(per_cmd.items(), key=lambda x: -x[1]):
            print(f"  {n:>4}x  {command}")
        return 1
    print(f"PARITY OK: {len(samples)}/{len(samples)} outputs byte-identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
