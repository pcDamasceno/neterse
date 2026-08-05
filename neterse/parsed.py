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
    Spec-compliant TOON tabular form (SPEC.md §9.3: root
    ``[N]{fields}:`` header, comma delimiter, two-space rows,
    ``null``/``true``/``false`` literals, delimiter-aware quoting,
    nested-uniform columns folded into ``field{sub,...}`` groups). A few
    percent larger than CSV, but the explicit row count lets a consumer
    (or the model) detect truncation, and the document round-trips
    through any conforming TOON decoder. Emitted only when the rows are
    §9.3-eligible (identical key sets, no array cells, no empty
    objects) and no profile projection applied — a conforming document
    cannot carry the omission marker (encoders MUST NOT emit comments,
    nor trailing content after the root form), so lossy renderings stay
    CSV's business.

``parsed:gcf``
    Spec-compliant GCF generic profile (SPEC v3.4.1: the required
    ``GCF profile=generic`` preamble, a ``## [N]{fields}`` section
    header, pipe-delimited rows, ``-`` for null vs ``~`` for
    field-absent, JSON-grammar quoting, nested-uniform dict columns
    flattened into quoted ``parent>child`` path columns). Slightly
    larger than CSV on flat tables, but it distinguishes null from
    missing — which CSV's empty cell conflates — and interoperates with
    the GCF tooling ecosystem (MCP proxies, decoders in six languages).
    Emitted only when every cell is representable in a conforming
    generic-profile table (no array cells, no non-uniform nesting) and
    no profile projection applied, for the same reason as
    ``parsed:toon``.

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
from decimal import Decimal
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


# ---------------------------------------------------------------------------
# Spec-compliant interop encodings (parsed:toon / parsed:gcf)
#
# TOON (toon-format SPEC.md, Working Draft 4.1) and GCF
# (blackwell-systems/gcf SPEC.md, v3.4.1 Stable) share their scalar
# grammar: JSON-style quoted strings, lowercase true/false, canonical
# decimal numbers. They differ in structure (indented comma rows under a
# ``[N]{fields}:`` header vs pipe rows under a ``## [N]{fields}`` section)
# and in null/missing handling (TOON: ``null``, absent keys ineligible;
# GCF: ``-`` null vs ``~`` absent). Both are emitted ONLY when the result
# is a conforming document — anything unrepresentable declines, fail-open,
# and the CSV/sections candidates carry on.
# ---------------------------------------------------------------------------

_TOON_BARE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_GCF_BARE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# A string a decoder would read back as a number — must be quoted to stay
# a string (JSON number grammar, both specs).
_NUMBER_LIKE = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$")
# C0 + DEL + C1: both specs require these escaped inside quoted strings.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_TOON_UNSAFE = re.compile(r'[:"\\\[\]{}]')
_EXPONENT_FORM = re.compile(r"^(-?[0-9.]+)[eE]([+-]?)0*(\d+)$")

# Sentinel for a key absent from a row (GCF distinguishes it from null).
_ABSENT = object()


def _escaped(s: str) -> str:
    """JSON-grammar quoted string, shared by both specs: short escapes
    for the common controls, ``\\uXXXX`` for the rest (DEL/C1 included,
    which ``json.dumps`` leaves raw), other unicode literal."""
    body = json.dumps(s, ensure_ascii=False)[1:-1]
    return '"' + _CONTROL_CHARS.sub(
        lambda m: "\\u%04x" % ord(m.group()), body
    ) + '"'


def _number_literal(value) -> Optional[str]:
    """Canonical number under both specs' shared rules: plain decimal
    (integer form when the fraction is zero) inside ``[1e-6, 1e21)``,
    exponent form outside, never a leading/trailing zero. ``None`` for
    non-finite values — the caller maps those to its null."""
    if isinstance(value, int):
        return str(value)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    if value == int(value) and abs(value) < 1e21:
        return str(int(value))
    text = repr(value)
    match = _EXPONENT_FORM.match(text)
    if match and 1e-6 <= abs(value) < 1e21:
        text = format(Decimal(text), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
    elif match:
        text = match.group(1) + "e" + (
            "-" if match.group(2) == "-" else ""
        ) + match.group(3)
    return text


def _toon_string(s: str) -> str:
    if (
        not s
        or s != s.strip()
        or s in ("true", "false", "null")
        or _NUMBER_LIKE.match(s)
        or "," in s
        or _TOON_UNSAFE.search(s)
        or _CONTROL_CHARS.search(s)
        or s[0] in "-#"
    ):
        return _escaped(s)
    return s


def _toon_scalar(value: Any) -> Optional[str]:
    """One encoded TOON cell, or ``None`` when *value* has no primitive
    encoding (the whole array then declines tabular form)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        literal = _number_literal(value)
        return "null" if literal is None else literal
    if isinstance(value, str):
        return _toon_string(value)
    if isinstance(value, (dict, list, tuple)):
        return None
    try:
        return _toon_string(str(value))     # datetime & friends, like _cell
    except Exception:
        return None


def _toon_columns(
    items: List[dict], keys: List[str]
) -> Optional[Tuple[str, List[Tuple[str, ...]]]]:
    """§9.3 eligibility walk: the encoded header field list and the
    depth-first leaf paths, or ``None`` when the rows disqualify (a key
    missing from some row, an array or empty-object cell, a column mixing
    objects with anything else — recursively for nested field groups)."""
    fields: List[str] = []
    paths: List[Tuple[str, ...]] = []
    for key in keys:
        if any(key not in row for row in items):
            return None
        values = [row[key] for row in items]
        if all(isinstance(v, dict) for v in values):
            if any(not v for v in values):
                return None                     # empty object cell
            subkeys = list(values[0])
            if not all(isinstance(k, str) for k in subkeys):
                return None
            if any(set(v) != set(subkeys) for v in values):
                return None                     # non-uniform nesting
            sub = _toon_columns(values, subkeys)
            if sub is None:
                return None
            subfields, subpaths = sub
            fields.append(
                (key if _TOON_BARE_KEY.match(key) else _escaped(key))
                + "{" + subfields + "}"
            )
            paths.extend((key,) + p for p in subpaths)
        else:
            if any(isinstance(v, (dict, list, tuple)) for v in values):
                return None                     # array cell / mixed column
            fields.append(key if _TOON_BARE_KEY.match(key) else _escaped(key))
            paths.append((key,))
    return ",".join(fields), paths


def _toon_encoded(
    items: List[dict], kept: List[str], dropped: Tuple[str, ...]
) -> Optional[Encoded]:
    """Spec-compliant TOON root tabular document, or ``None``. Declines
    under an applied projection: a conforming encoder may emit neither
    comment lines nor trailing content after the root form, so there is
    no way to carry the omission marker in-document."""
    if dropped:
        return None
    columns = _toon_columns(items, kept)
    if columns is None:
        return None
    fields, paths = columns
    lines = [f"[{len(items)}]{{{fields}}}:"]
    for row in items:
        cells = []
        for path in paths:
            value: Any = row
            for step in path:
                value = value[step]
            cell = _toon_scalar(value)
            if cell is None:
                return None
            cells.append(cell)
        lines.append("  " + ",".join(cells))
    return "\n".join(lines), "parsed:toon", (), "default"


def _gcf_string(s: str) -> str:
    if (
        not s
        or s != s.strip()
        or s in ("-", "~", "^", "true", "false")
        or _NUMBER_LIKE.match(s)
        or "|" in s
        or '"' in s
        or "\\" in s
        or _CONTROL_CHARS.search(s)
    ):
        return _escaped(s)
    return s


def _gcf_scalar(value: Any) -> Optional[str]:
    """One encoded GCF cell (``-`` null, ``~`` absent), or ``None`` when
    *value* cannot appear in a conforming generic-profile row."""
    if value is _ABSENT:
        return "~"
    if value is None:
        return "-"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        literal = _number_literal(value)
        return "-" if literal is None else literal
    if isinstance(value, str):
        return _gcf_string(value)
    if isinstance(value, (dict, list, tuple)):
        return None
    try:
        return _gcf_string(str(value))
    except Exception:
        return None


def _gcf_leaf_paths(
    items: List[dict], keys: List[str]
) -> Optional[List[Tuple[str, ...]]]:
    """Column paths for the generic profile, flattening nested-uniform
    dict columns into ``parent>child`` paths (§7.4.6: identical key sets
    and scalar leaves only — encoders MUST NOT flatten anything else).
    ``None`` when any column is unrepresentable: an array cell, a dict
    column that is absent somewhere or non-uniform, a source field name
    containing the reserved ``>``."""
    paths: List[Tuple[str, ...]] = []
    for key in keys:
        if ">" in key:
            return None                         # reserved for path columns
        present = [row[key] for row in items if key in row]
        if any(isinstance(v, dict) for v in present):
            if len(present) != len(items):
                return None                     # parent absent in some row
            if not all(isinstance(v, dict) and v for v in present):
                return None
            subkeys = list(present[0])
            if not all(isinstance(k, str) for k in subkeys):
                return None
            if any(set(v) != set(subkeys) for v in present):
                return None
            sub = _gcf_leaf_paths(present, subkeys)
            if sub is None:
                return None
            paths.extend((key,) + p for p in sub)
        elif any(isinstance(v, (list, tuple)) for v in present):
            return None
        else:
            paths.append((key,))
    return paths


def _gcf_encoded(
    items: List[dict], kept: List[str], dropped: Tuple[str, ...]
) -> Optional[Encoded]:
    """Spec-compliant GCF generic-profile document, or ``None``. Declines
    under an applied projection for the same reason as TOON: nothing in a
    conforming document can carry the omission marker."""
    if dropped:
        return None
    paths = _gcf_leaf_paths(items, kept)
    if paths is None or not paths:
        return None
    names = []
    for path in paths:
        name = ">".join(path)
        names.append(name if _GCF_BARE_KEY.match(name) else _escaped(name))
    lines = [
        "GCF profile=generic",
        "## [%d]{%s}" % (len(items), ",".join(names)),
    ]
    for row in items:
        cells = []
        for path in paths:
            value: Any = row
            for step in path:
                if not isinstance(value, dict) or step not in value:
                    value = _ABSENT
                    break
                value = value[step]
            cell = _gcf_scalar(value)
            if cell is None:
                return None
            cells.append(cell)
        lines.append("|".join(cells))
    return "\n".join(lines), "parsed:gcf", (), "default"


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
            csv_lines = [header] + row_lines
            if dropped:
                csv_lines.append(omission_marker(dropped))
            encoded.append(("\n".join(csv_lines), "parsed:csv", dropped, applied))
            toon = _toon_encoded(items, kept, dropped)
            if toon is not None:
                encoded.append(toon)
            gcf = _gcf_encoded(items, kept, dropped)
            if gcf is not None:
                encoded.append(gcf)
    sections = _encode_sections(parsed, profile)
    if sections is not None:
        encoded.append(sections)
    return encoded
