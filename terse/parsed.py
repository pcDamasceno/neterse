"""Parsed tier — compact encoders over rows other parsers already produced.

Per-command raw compressors re-do work the parsing ecosystems (Genie,
ntc-templates, TTP, NAPALM, gNMI) finished years ago. Once output is
*structured*, minimum-token rendering is a generic transform: project the
fields, emit the keys once, then one delimited line per row. This module
is that transform — it knows nothing about commands or vendors, so one
encoder covers every command those parsers handle.

``encode(parsed, profile)`` accepts a list of dicts (or a single dict —
one row) and returns encoder outputs as plain tuples; ``terse.render``
wraps them into :class:`~terse.Candidate` objects and applies the usual
shrink gate against the raw output. Two encodings are emitted and BOTH
are returned — candidates, not policy:

``parsed:csv``
    Header-once CSV. Nearly always the smallest faithful encoding of a
    flat uniform table.

``parsed:toon``
    TOON-style tabular block (``[N]{fields}:`` + indented rows). A few
    percent larger than CSV, but the explicit row count lets a consumer
    (or the model) detect truncation, which some policies value above
    minimum size. Uniform flat rows only — nested values are JSON-encoded
    into their cell, and rows with differing keys fall back to the
    unioned-column table with empty cells (a pragmatic extension of
    strict TOON; full spec compliance is a Phase-4 concern).

Faithfulness: the default profile projects nothing — every key of every
row appears (missing keys and JSON ``null`` both render as an empty
cell). Named profiles (:data:`PROFILES`) are declared-lossy field
projections keyed on field-NAME patterns, because parser schemas differ
per ecosystem; a profile that matches no fields (or all of them) falls
back to the complete encoding rather than guess. Applied projections
declare the dropped names and append the same inline omission marker the
spec tier uses.

Stdlib only, like everything else here.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Tuple

from .engine import omission_marker

# (text, source, dropped_fields, applied_profile)
Encoded = Tuple[str, str, Tuple[str, ...], str]

# Named projections over parsed-row FIELD NAMES. A field is kept when its
# name matches any pattern of the requested profile. Patterns are broad on
# purpose: they must hit ntc-templates, Genie and NAPALM spellings alike.
PROFILES = {
    # Interface liveness: which port, is it up, and why not.
    "updown": (
        re.compile(r"^(?:port|interface|intf|intf_name|name)$", re.IGNORECASE),
        re.compile(
            r"^(?:status|state|protocol|proto|link|link_status|line_protocol|"
            r"oper_state|admin_state|reason)$",
            re.IGNORECASE,
        ),
    ),
}


def _rows(parsed: Any) -> Optional[List[dict]]:
    """Normalize *parsed* to a non-empty list of str-keyed dicts, or None.

    Anything else — scalars, strings, mixed lists, exotic keys — is not
    row-shaped data we can encode faithfully, so the tier declines
    (fail-open: no candidate, never an exception).
    """
    if isinstance(parsed, dict):
        items = [parsed]
    elif isinstance(parsed, (list, tuple)):
        items = list(parsed)
    else:
        return None
    if not items or not all(isinstance(r, dict) for r in items):
        return None
    if not all(isinstance(k, str) for r in items for k in r):
        return None
    return items


def _columns(items: List[dict]) -> List[str]:
    """Union of row keys in first-seen order — the header."""
    cols: List[str] = []
    seen = set()
    for row in items:
        for key in row:
            if key not in seen:
                seen.add(key)
                cols.append(key)
    return cols


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, separators=(",", ":"), default=str)
    return str(value)


def _quote(s: str) -> str:
    if "," in s or '"' in s or "\n" in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def _project(cols: List[str], profile: str) -> Tuple[List[str], Tuple[str, ...]]:
    """(kept columns, dropped names) under *profile* — the full column set
    when the profile is unknown here or its patterns don't discriminate."""
    patterns = PROFILES.get(profile)
    if not patterns:
        return cols, ()
    kept = [c for c in cols if any(p.match(c) for p in patterns)]
    dropped = tuple(c for c in cols if c not in kept)
    if not kept or not dropped:
        return cols, ()
    return kept, dropped


def encode(parsed: Any, profile: str = "default") -> List[Encoded]:
    """Encode pre-parsed rows compactly; empty list when *parsed* isn't
    row-shaped. The caller owns the shrink gate and Candidate wrapping."""
    items = _rows(parsed)
    if items is None:
        return []
    cols = _columns(items)
    if not cols:
        return []
    if profile == "default":
        kept, dropped = cols, ()
    else:
        kept, dropped = _project(cols, profile)
    applied = profile if dropped else "default"

    header = ",".join(_quote(c) for c in kept)
    row_lines = [
        ",".join(_quote(_cell(row.get(c))) for c in kept) for row in items
    ]
    marker = omission_marker(dropped) if dropped else None

    csv_lines = [header] + row_lines
    toon_lines = [f"[{len(items)}]{{{header}}}:"] + [
        "  " + line for line in row_lines
    ]
    if marker:
        csv_lines.append(marker)
        toon_lines.append(marker)
    return [
        ("\n".join(csv_lines), "parsed:csv", dropped, applied),
        ("\n".join(toon_lines), "parsed:toon", dropped, applied),
    ]
