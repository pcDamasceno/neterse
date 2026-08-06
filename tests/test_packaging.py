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

import re
import tomllib
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# The `all` aggregate — the other manifest that can silently fall behind
# ---------------------------------------------------------------------------

#: Extras `all` deliberately omits: for working ON neterse, not with it.
DEV_ONLY = {"test"}
#: Aggregates are the thing being checked, so they don't check themselves.
AGGREGATES = {"all", "full"}

_SELF_REF = re.compile(r"^neterse\s*\[([^\]]+)\]", re.IGNORECASE)


def _extras(pyproject) -> dict:
    return pyproject["project"]["optional-dependencies"]


def _expand(name: str, extras: dict, seen=None) -> set:
    """Extra name -> every extra it pulls in, following `neterse[...]`."""
    seen = seen if seen is not None else set()
    if name in seen:
        return seen
    seen.add(name)
    for requirement in extras.get(name, []):
        match = _SELF_REF.match(requirement)
        if match:
            for referenced in match.group(1).split(","):
                _expand(referenced.strip(), extras, seen)
    return seen


def test_the_all_extra_covers_every_capability_extra(pyproject):
    """`pip install neterse[all]` has to mean all of it.

    An aggregate extra is a hand-maintained copy of the extras list, so
    it decays the moment someone adds a capability and doesn't think to
    edit two places. The failure is silent — `[all]` installs, just
    without the thing that was added — so nothing but a test catches it.
    """
    extras = _extras(pyproject)
    expected = set(extras) - DEV_ONLY - AGGREGATES
    missing = expected - _expand("all", extras)
    assert not missing, (
        f"extra(s) {sorted(missing)} exist but are not reachable from "
        f"`all` — `pip install neterse[all]` would silently skip them. "
        f"Add them to the `all` list (or to DEV_ONLY here, if they are "
        f"tooling for working on neterse rather than a capability)."
    )


def test_full_is_an_alias_of_all(pyproject):
    """Two spellings, one set of packages — README promises both."""
    extras = _extras(pyproject)
    assert _expand("full", extras) - {"full"} == _expand("all", extras)


def test_every_self_reference_names_an_extra_that_exists(pyproject):
    """A typo in `neterse[tokns]` is not an error at build time: pip
    warns about an unknown extra and installs the rest, so the miss only
    shows up as a missing package much later."""
    extras = _extras(pyproject)
    for name, requirements in extras.items():
        for requirement in requirements:
            match = _SELF_REF.match(requirement)
            if not match:
                continue
            for referenced in (r.strip() for r in match.group(1).split(",")):
                assert referenced in extras, (
                    f"extra {name!r} requires neterse[{referenced}], which "
                    f"is not declared — pip would warn and skip it"
                )


def test_no_extra_is_reachable_from_itself(pyproject):
    """Self-referential extras are the mechanism here; a cycle among them
    is a resolver problem, not a clever one."""
    extras = _extras(pyproject)
    for name in extras:
        direct = set()
        for requirement in extras[name]:
            match = _SELF_REF.match(requirement)
            if match:
                direct |= {r.strip() for r in match.group(1).split(",")}
        assert name not in _expand_from(direct, extras), (
            f"extra {name!r} pulls in itself, transitively"
        )


def _expand_from(names, extras) -> set:
    seen = set()
    for name in names:
        _expand(name, extras, seen)
    return seen
