#!/usr/bin/env python3
"""Regenerate every fixture family's ``expected.txt`` golden.

The golden is the WINNING rendering of ``raw.txt`` (smallest candidate on
the default path, the fixture's platform supplied) — the content check
``tests/test_fixture_corpus.py`` pins byte-for-byte. Run this ONLY when
the change is intentional: a new family, or a recorded baseline decision
that changes a family's output (docs/DESIGN.md). Regenerating to make a
red build green without a recorded decision defeats the gate — the whole
point of the golden is that a reviewer eyeballs the rendering.

    python scripts/update_goldens.py            # write all goldens
    python scripts/update_goldens.py --check    # exit 1 on any drift

Every command spelling in ``commands.txt`` must produce the same winning
text; a family whose spellings disagree is an error (the spellings are
supposed to be aliases of one format).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from neterse import render  # noqa: E402

from tests.fixture_corpus import FIXTURE_ROOT, load_fixtures  # noqa: E402


def winning_text(fixture) -> str:
    texts = set()
    for command in fixture.commands:
        candidates = render(
            fixture.body, command=command, platform=fixture.platform
        )
        if not candidates:
            raise SystemExit(
                f"{fixture.label}: no candidate for {command!r} — "
                "cannot golden an uncovered family"
            )
        texts.add(min(candidates, key=lambda c: len(c.text)).text)
    if len(texts) != 1:
        raise SystemExit(
            f"{fixture.label}: command spellings disagree on the winning "
            "rendering — commands.txt entries must be aliases of one format"
        )
    return texts.pop()


def main(argv=None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    drifted = []
    for fixture in load_fixtures():
        text = winning_text(fixture)
        path = FIXTURE_ROOT / fixture.label / "expected.txt"
        if fixture.expected == text:
            continue
        if check:
            drifted.append(fixture.label)
            continue
        path.write_text(text)
        verb = "updated" if fixture.expected is not None else "wrote"
        print(f"{verb} {path.relative_to(REPO_ROOT)}")
    if drifted:
        print(
            "goldens drifted (run scripts/update_goldens.py and review "
            "the diff): " + ", ".join(sorted(drifted))
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
