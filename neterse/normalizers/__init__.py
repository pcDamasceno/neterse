"""Shape normalizers — vendor/API payload styles → neterse's canonical rows.

Parsers hand neterse rows, but a growing set of SOURCES hand it a
vendor-shaped *envelope* instead: Cisco ACI wraps every object as
``{class: {attributes: {...}}}`` under an ``imdata`` list; other
controllers (SD-WAN, Meraki, DNAC) each have their own — and the shape can
change between API versions. Teaching the generic parsed tier
(:mod:`neterse.parsed`) about any one of them would tie a vendor-agnostic
transform to a vendor. This package is the seam that keeps them apart.

A *normalizer* is a small, fail-open sniffer::

    Callable[[Any], Optional[List[dict]]]

It receives an already-decoded structure and returns neterse's canonical
row shape — a non-empty list of string-keyed dicts, one dict per row — or
``None`` for "not my shape". Raising also means "not mine". This mirrors
:mod:`neterse.sources` exactly, one level down: sources adapt foreign
*response objects* into text/rows; normalizers claim the *structured
payloads* those and other callers carry.

:func:`normalize` tries every registered normalizer in order and returns
the first CANONICAL result; :func:`register_normalizer` puts a custom one
ahead of the built-ins, so out-of-tree vendors and per-version overrides
win without editing this file. Built-ins ship one module per style:

* :mod:`neterse.normalizers._generic` — vendor-neutral shapes every
  ecosystem uses (the ``{name: {...}}`` keyed-dict NAPALM/OpenConfig
  return).
* :mod:`neterse.normalizers.cisco_aci` — the ACI ``imdata`` object style.

Contributing a vendor is one file plus one line in ``NORMALIZERS`` below
(see ``CONTRIBUTING.md``). Stdlib only, fail-open — like everything else.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

from ._generic import keyed_dict
from .cisco_aci import class_attributes

__all__ = [
    "Normalizer",
    "class_attributes",
    "iter_normalizers",
    "keyed_dict",
    "normalize",
    "register_normalizer",
]

# A normalizer receives an arbitrary decoded structure and returns the
# canonical row shape (a non-empty list of str-keyed dicts) or None for
# "not my shape". A normalizer that raises also counts as "not mine".
Normalizer = Callable[[Any], Optional[List[dict]]]

# Canonical order: most specific (vendor) shapes first, vendor-neutral
# shapes last, so a vendor style is never pre-empted by a generic one.
# register_normalizer inserts ahead of all of these. Add a new vendor by
# importing its normalizer above and listing it here.
NORMALIZERS: List[Normalizer] = [
    class_attributes,   # cisco_aci: {class: {attributes: {...}}}
    keyed_dict,         # generic:  {name: {...}}
]


def _is_canonical(rows: Any) -> bool:
    """The single definition every normalizer's output is held to: a
    non-empty list of string-keyed dicts. Lets :func:`normalize` trust
    whatever a normalizer returns (or discard it) without re-checking
    downstream."""
    return (
        isinstance(rows, list)
        and bool(rows)
        and all(
            isinstance(row, dict) and all(isinstance(key, str) for key in row)
            for row in rows
        )
    )


def register_normalizer(normalizer: Normalizer) -> Normalizer:
    """Teach neterse a new vendor/API payload shape.

    *normalizer* receives a decoded structure and returns canonical rows (a
    non-empty list of str-keyed dicts) — or ``None`` for "not mine".
    Registered normalizers are tried BEFORE the built-ins, so this is also
    how you override a shipped shape for a new API version. A normalizer
    that raises counts as "not mine". Usable as a decorator.
    """
    NORMALIZERS.insert(0, normalizer)
    return normalizer


def normalize(value: Any) -> Optional[List[dict]]:
    """Canonical rows for *value* under the first normalizer that claims its
    shape, or ``None`` when none do (the caller then treats *value* as a
    single row, or declines). Fail-open: a normalizer that raises or returns
    a non-canonical result is skipped, never propagated."""
    for normalizer in NORMALIZERS:
        try:
            rows = normalizer(value)
        except Exception:
            rows = None
        if rows is not None and _is_canonical(rows):
            return rows
    return None


def iter_normalizers() -> tuple:
    """Snapshot of the active normalizers, custom-first then built-in — the
    order :func:`normalize` tries them."""
    return tuple(NORMALIZERS)
