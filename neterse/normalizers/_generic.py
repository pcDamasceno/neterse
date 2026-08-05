"""Vendor-neutral shape normalizers.

Structural conventions that show up across ecosystems and are owned by no
single vendor. Genuinely vendor-specific envelopes live in their own
module (e.g. :mod:`neterse.normalizers.cisco_aci`); this file is only for
shapes many parsers share.

Stdlib only, fail-open — like everything else here.
"""
from __future__ import annotations

from typing import Any, List, Optional


def keyed_dict(value: Any) -> Optional[List[dict]]:
    """``{name: {...}}`` → one row per entry, the outer key kept as a column.

    The dominant NAPALM/OpenConfig getter shape (``get_interfaces``,
    ``get_optics``, ``get_vlans`` return a dict keyed by interface / VLAN /
    user whose values are uniform attribute dicts). Left whole it is one
    unshrinkable mega-row; here it becomes an ordinary table with the outer
    key in a leading ``key`` column.

    Declines (``None``) unless *value* is a non-empty dict whose EVERY value
    is a string-keyed dict — a scalar-or-mixed dict (``get_facts``,
    ``get_config``) is a single row, not a table, and must fall through. The
    outer keys themselves may be non-string (int VLAN ids are fine); the key
    becomes a cell, so the flattening is lossless. The ``key`` column name
    gains leading underscores as needed so it never shadows an inner field.
    """
    if not isinstance(value, dict) or not value:
        return None
    if not all(
        isinstance(v, dict) and all(isinstance(k, str) for k in v)
        for v in value.values()
    ):
        return None
    keycol = "key"
    inner = {k for v in value.values() for k in v}
    while keycol in inner:
        keycol = "_" + keycol
    return [{keycol: name, **attrs} for name, attrs in value.items()]
