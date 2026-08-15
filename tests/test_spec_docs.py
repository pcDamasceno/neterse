"""docs/SPECS.md cannot drift from the validator's schema tables.

The authoring reference documents every spec key; the compiler's
``COMMON_KEYS`` / ``STRATEGY_KEYS`` / ``FIELD_KEYS`` / ``FLAG_NAMES``
tables ARE the schema. A key added to the validator without a matching
backtick-quoted mention in the doc fails here, so "the existing files
are the reference" never quietly becomes true again.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="PyYAML ships in the test extra")

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "compile_specs_for_docs", REPO_ROOT / "scripts" / "compile_specs.py"
)
compile_specs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compile_specs)

DOC = REPO_ROOT / "docs" / "SPECS.md"


def _doc_text() -> str:
    assert DOC.is_file(), "docs/SPECS.md missing — the authoring reference"
    return DOC.read_text(encoding="utf-8")


def test_every_schema_key_is_documented():
    text = _doc_text()
    names = set(compile_specs.COMMON_KEYS)
    for strategy, keys in compile_specs.STRATEGY_KEYS.items():
        names.add(strategy)
        names |= keys["required"] | keys["optional"]
    names |= set(compile_specs.FIELD_KEYS)
    names |= set(compile_specs.FLAG_NAMES)
    undocumented = sorted(n for n in names if f"`{n}`" not in text)
    assert not undocumented, (
        f"docs/SPECS.md does not mention: {undocumented} — every key in "
        "compile_specs.py's schema tables needs a backtick-quoted entry "
        "in the authoring reference"
    )


def test_doc_names_no_stale_strategies():
    text = _doc_text()
    for line in text.splitlines():
        if line.startswith("## `"):
            name = line[len("## `"):].split("`", 1)[0]
            assert name in compile_specs.STRATEGY_KEYS, (
                f"docs/SPECS.md documents strategy {name!r} which the "
                "compiler does not know"
            )
