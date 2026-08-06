"""Packaging invariants — what a `pip install` actually gets.

Every other suite imports neterse from the source checkout, where the
whole tree is on ``sys.path`` and a missing entry in pyproject's
``packages`` list is invisible. It is not invisible to a wheel: a
subpackage left off that list is simply absent from the distribution,
and since ``neterse/parsed.py`` imports ``normalizers`` at module scope,
the omission turns into ``ImportError`` on plain ``import neterse`` —
the package does not load at all.

That is exactly what happened when ``neterse.normalizers`` was added
(the subpackage shipped in the repo, never in ``packages``), and the
full test suite stayed green throughout, because tests never install the
wheel. So this file checks the manifest against the tree instead.

Stdlib only, no build step: reading pyproject and walking the package
directory is enough to catch the whole class of error, and it runs in
milliseconds on every commit rather than only at tag time.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:                                             # 3.9/3.10 — optional
    tomllib = pytest.importorskip(
        "tomli", reason="needs tomllib (3.11+) or tomli to read pyproject"
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
PACKAGE_ROOT = REPO_ROOT / "neterse"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    if not PYPROJECT.is_file():
        pytest.skip("not running from a source checkout")
    return tomllib.loads(PYPROJECT.read_text())


def _declared(pyproject) -> set:
    return set(pyproject["tool"]["setuptools"]["packages"])


def _on_disk() -> set:
    """Every importable subpackage under neterse/ (has __init__.py)."""
    found = {"neterse"}
    for init in PACKAGE_ROOT.rglob("__init__.py"):
        rel = init.parent.relative_to(REPO_ROOT)
        found.add(".".join(rel.parts))
    return found


def test_every_subpackage_is_declared_for_the_wheel(pyproject):
    """The regression that shipped: neterse.normalizers existed in the
    tree and not in `packages`, so the wheel omitted it and `import
    neterse` raised ImportError in every clean install."""
    missing = _on_disk() - _declared(pyproject)
    assert not missing, (
        f"subpackage(s) {sorted(missing)} exist under neterse/ but are not "
        f"in pyproject's [tool.setuptools] packages — the wheel would omit "
        f"them and `pip install neterse` would fail to import. Add them."
    )


def test_no_declared_package_is_missing_from_the_tree(pyproject):
    """The other direction: a stale entry (a renamed or removed
    subpackage) makes setuptools fail the build."""
    stale = _declared(pyproject) - _on_disk()
    assert not stale, (
        f"pyproject declares package(s) {sorted(stale)} that do not exist "
        f"under neterse/ — a rename or deletion left the manifest behind"
    )


def test_version_is_in_lockstep(pyproject):
    """RELEASING.md step 1: the two spellings must match, and the release
    workflow refuses a tag that disagrees with them."""
    import neterse

    assert pyproject["project"]["version"] == neterse.__version__, (
        f"pyproject version {pyproject['project']['version']!r} != "
        f"neterse.__version__ {neterse.__version__!r}"
    )
