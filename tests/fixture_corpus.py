"""Loader for the file-per-fixture corpus (Phase-3 contribution layout).

Layout: ``tests/fixtures/<platform>/<family>/`` containing

* ``raw.txt`` — one byte-exact raw capture (never normalize whitespace:
  fixed-width offsets are data);
* ``commands.txt`` — every command spelling agents actually type for it,
  one per line (``#`` comments allowed).

The platform string is the ``<platform>`` directory name, so a fixture
carries everything ``render()`` needs. The in-module corpus
(``corpus.py``) remains the frozen LEGACY baseline set replayed through
``legacy_snapshot`` by the parity suite; file fixtures cover the
POST-baseline families and are exercised behaviorally (shrink diagonal +
fail-open matrix) through neterse itself — see docs/DESIGN.md decision 15.
The audit CLI reads this same layout directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, NamedTuple, Tuple

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


class FileFixture(NamedTuple):
    label: str                  # "<platform>/<family>"
    platform: str
    commands: Tuple[str, ...]
    body: str


def load_fixtures(root: Path = FIXTURE_ROOT) -> List[FileFixture]:
    fixtures: List[FileFixture] = []
    for raw_path in sorted(root.rglob("raw.txt")):
        family_dir = raw_path.parent
        commands = tuple(
            line.strip()
            for line in (family_dir / "commands.txt").read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        fixtures.append(
            FileFixture(
                label=f"{family_dir.parent.name}/{family_dir.name}",
                platform=family_dir.parent.name,
                commands=commands,
                body=raw_path.read_text(),
            )
        )
    return fixtures


FILE_FIXTURES: List[FileFixture] = load_fixtures()
