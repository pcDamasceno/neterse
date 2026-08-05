"""Parsed tier — compact encoders over rows other parsers already produced.

Per-command raw compressors re-do work the parsing ecosystems (Genie,
ntc-templates, TTP, NAPALM, gNMI) finished years ago. Once output is
*structured*, minimum-token rendering is a generic transform: project the
fields, emit the keys once, then one delimited line per row. This module
is that transform — it knows nothing about commands or vendors, so one
encoder covers every command those parsers handle.

``encode(parsed, profile)`` accepts a list of dicts, a single dict (one
row), or a dict keyed by name whose values are all dicts — the
NAPALM/OpenConfig ``{interface: {...}}`` shape, flattened to one row per
entry with the outer key kept as a leading column — and returns encoder
outputs as plain tuples; ``neterse.render`` wraps them into
:class:`~neterse.Candidate` objects and applies the usual shrink gate
against the raw output. Two encodings are emitted and BOTH are
returned — candidates, not policy:

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

``parsed:sections``
    A hierarchy-preserving document for tool/API responses that mix scalar
    metadata, nested mappings and multiple row collections. Section names and
    scalar values remain in place while each row collection becomes a compact
    header-once table — including collections nested INSIDE a row (an ACI
    ``_children``/``_faults`` subtree), which are tabulated recursively as
    indented sub-tables rather than JSON-blobbed.

Vendor/API envelopes (ACI ``imdata``, NAPALM keyed getters, future
SD-WAN / Meraki styles) are turned into canonical rows by
:mod:`neterse.normalizers` BEFORE they reach these encoders, so this module
stays vendor-agnostic: it encodes rows, it does not know who produced them.

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

from . import normalizers
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
            r"protocol_status|oper_state|oper_status|admin_state|admin_status|"
            r"reason)$",
            re.IGNORECASE,
        ),
    ),
}


def _rows(parsed: Any) -> Optional[List[dict]]:
    """Normalize *parsed* to a non-empty list of str-keyed dicts, or None.

    A recognized vendor/API shape (:mod:`neterse.normalizers`) is turned
    into rows; any other dict is a single row; a list/tuple is taken
    as-is. Anything else — scalars, strings, mixed lists, exotic keys — is
    not row-shaped data we can encode faithfully, so the tier declines
    (fail-open: no candidate, never an exception).
    """
    rows = normalizers.normalize(parsed)
    if rows is not None:
        return rows
    if isinstance(parsed, dict):
        items: List[dict] = [parsed]
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


def _table_csv(items: List[dict], profile: str) -> Tuple[List[str], Tuple[str, ...]]:
    cols = _columns(items)
    if profile == "default":
        kept, dropped = cols, ()
    else:
        kept, dropped = _project(cols, profile)
    lines = [",".join(_quote(c) for c in kept)] + [
        ",".join(_quote(_cell(row.get(c))) for c in kept) for row in items
    ]
    if dropped:
        lines.append(omission_marker(dropped))
    return lines, dropped


def _table_lines(
    items: List[dict], profile: str
) -> Tuple[List[str], Tuple[str, ...]]:
    """Header-once table for *items*, but with any nested row-collection
    tabulated as an indented sub-table instead of a JSON-blobbed cell.

    A cell whose value another normalizer claims (an ACI ``_children`` /
    ``_faults`` list of wrapped objects, a keyed sub-map — anything
    :func:`neterse.normalizers.normalize` recognizes) is a whole table in
    disguise; flattening it to one JSON string is exactly what loses to
    compact JSON on subtree responses. Here such cells become their own
    indented sub-table under each row, recursively. Rows with NO such
    nesting fall through to :func:`_table_csv` byte-for-byte, so the common
    flat-table case is untouched. Vendor-agnostic: it asks ``normalize``
    what nests, it never names a vendor.
    """
    flats: List[dict] = []
    nested_per_row: List[List[Tuple[str, List[dict]]]] = []
    any_nested = False
    for row in items:
        flat: dict = {}
        nested: List[Tuple[str, List[dict]]] = []
        for key, value in row.items():
            sub = (
                normalizers.normalize(value)
                if isinstance(value, (list, tuple, dict)) else None
            )
            if sub is not None:
                nested.append((key, sub))
                any_nested = True
            else:
                flat[key] = value
        flats.append(flat)
        nested_per_row.append(nested)
    if not any_nested:
        return _table_csv(items, profile)

    cols = _columns(flats)
    if profile == "default":
        kept, dropped = cols, ()
    else:
        kept, dropped = _project(cols, profile)
    dropped_all: List[str] = list(dropped)
    lines = [",".join(_quote(c) for c in kept)]
    for flat, nested in zip(flats, nested_per_row):
        lines.append(",".join(_quote(_cell(flat.get(c))) for c in kept))
        for key, subrows in nested:
            sub_lines, sub_dropped = _table_lines(subrows, profile)
            lines.append("  " + _section_label(key) + ":")
            lines.extend("    " + line for line in sub_lines)
            for field in sub_dropped:
                if field not in dropped_all:
                    dropped_all.append(field)
    if dropped:
        lines.append(omission_marker(dropped))
    return lines, tuple(dropped_all)


def _section_label(key: str) -> str:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_.-]*$", key):
        return key
    return json.dumps(key, separators=(",", ":"))


def _section_lines(
    mapping: dict, profile: str, depth: int = 0
) -> Optional[Tuple[List[str], List[str]]]:
    if not all(isinstance(key, str) for key in mapping):
        return None
    indent = "  " * depth
    lines: List[str] = []
    dropped_fields: List[str] = []
    for key, value in mapping.items():
        label = _section_label(key)
        table_items: Optional[List[dict]] = None
        if isinstance(value, (list, tuple)):
            table_items = _rows(value)
        elif isinstance(value, dict):
            table_items = normalizers.normalize(value)
        if table_items:
            table, dropped = _table_lines(table_items, profile)
            lines.append(f"{indent}{label}:")
            lines.extend(f"{indent}  {line}" for line in table)
            for field in dropped:
                if field not in dropped_fields:
                    dropped_fields.append(field)
            continue
        if isinstance(value, dict) and value:
            nested = _section_lines(value, profile, depth + 1)
            if nested is None:
                return None
            nested_lines, nested_drops = nested
            lines.append(f"{indent}{label}:")
            lines.extend(nested_lines)
            for field in nested_drops:
                if field not in dropped_fields:
                    dropped_fields.append(field)
            continue
        encoded = json.dumps(value, separators=(",", ":"), default=str)
        lines.append(f"{indent}{label}:{encoded}")
    return lines, dropped_fields


def _encode_sections(parsed: Any, profile: str) -> Optional[Encoded]:
    """Encode a mixed mapping as named scalar and tabular sections.

    Tool responses commonly combine metadata with several row collections.
    Treating that shape as one CSV row escapes the collections back into JSON,
    so preserve the hierarchy and encode each collection header-once instead.
    Row-collections nested INSIDE a row (an ACI ``_children``/``_faults``
    subtree) are tabulated recursively rather than JSON-blobbed, via
    :func:`_table_lines`.
    """
    if (
        not isinstance(parsed, dict)
        or not parsed
        or normalizers.normalize(parsed) is not None
        or not any(isinstance(value, (dict, list, tuple)) for value in parsed.values())
    ):
        return None
    sectioned = _section_lines(parsed, profile)
    if sectioned is None:
        return None
    lines, dropped = sectioned
    applied = profile if dropped else "default"
    return "\n".join(lines), "parsed:sections", tuple(dropped), applied


def encode(parsed: Any, profile: str = "default") -> List[Encoded]:
    """Encode pre-parsed rows compactly; empty list when *parsed* isn't
    row-shaped. The caller owns the shrink gate and Candidate wrapping."""
    encoded: List[Encoded] = []
    items = _rows(parsed)
    if items is not None:
        cols = _columns(items)
        if cols:
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
            encoded.extend([
                ("\n".join(csv_lines), "parsed:csv", dropped, applied),
                ("\n".join(toon_lines), "parsed:toon", dropped, applied),
            ])
    sections = _encode_sections(parsed, profile)
    if sections is not None:
        encoded.append(sections)
    return encoded
