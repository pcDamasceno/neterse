"""Generic strategies that turn declarative specs into compressors.

A *spec* is a plain dict (stdlib-only by design — no YAML/TOML dependency;
a YAML authoring front-end can layer on later without touching this
engine). ``build(spec)`` compiles it into the same ``Callable[[str], str]``
shape as a hand-written compressor, under the same fail-open contract: the
built function returns the raw input whenever it cannot produce a smaller,
faithful rendering.

Strategies:

``line_regex_table``
    One regex per data row (matched against each stripped line) → CSV.
    Spec keys: ``row`` (pattern), ``row_flags`` (int, optional),
    ``header`` (CSV header line), ``columns`` (1-based group indexes to
    emit; omit for all groups), ``strip_columns`` (group indexes whose
    value is ``.strip()``-ed), ``context_prefixes`` (lines starting with
    any of these are captured as a context line prepended to the table —
    e.g. the EIGRP process/VRF line), ``unindented_rows_only`` (bool:
    skip indented lines BEFORE stripping — for tables whose data rows
    start at column 0, so wrapped continuation lines can never
    false-match; e.g. IOS cdp wraps a long device ID onto its own line
    and indents the remaining columns).

``fixed_width_table``
    Offset-sliced fixed-width table → CSV, driven by the header keywords
    (see ``_compressors._fixed_width_rows``). Spec keys: ``keywords``,
    ``header``, and optionally ``row_match`` — a regex a data row's first
    column must match (default: the Cisco-family interface-name pattern;
    vendors with other port-name shapes, e.g. Arista ``Et1`` or Aruba
    ``1/1/1``, declare their own) — and ``first_col_wraps`` (bool): the
    first column's value may overflow its width and wrap onto its own
    line (IOS ``show cdp neighbors`` device IDs); rows are re-joined via
    ``_compressors._wrapped_first_col_rows``, with ``row_match``
    defaulting to a single-token pattern instead of interface names.

``kv_extract`` (Phase 2)
    First-match field scan → one ``key=value | key=value`` line. Spec
    keys: ``fields`` — a list of dicts each carrying ``key`` (output
    name), ``pattern`` (regex searched per line), and optionally
    ``flags`` (int), ``template`` (str.format string where ``{0}`` is the
    whole match and ``{1}``… are groups; default ``"{1}"``) and ``strip``
    (bool: ``.strip()`` each group before formatting) — plus optional
    ``joiner`` (default ``" | "``). Output order is the order in which
    fields first match while scanning lines top-to-bottom, byte-compatible
    with the historical hand-written ``show version`` compressor.

Profiles (Phase 2): a table spec may declare named, *declared-lossy*
column projections — ``"profiles": {"updown": {"keep": ["port",
"status"]}}``. ``build(spec, profile=name)`` compiles a variant that
emits only the kept columns and appends an inline omission marker
(``omission_marker``) naming what was withheld, so a model reading the
rendering knows data exists and how to recover it. Projections are
resolved by header name at build time; unknown names or a projection
that keeps everything (or nothing) fail loudly. The default build is
untouched — byte-parity lives on the default path.

Byte-compatibility note: these strategies reproduce the historical
hand-written compressors exactly (None groups render as empty fields, a
header with no data rows fails open, context lines prepend with a single
newline). The parity suite pins this — restructure freely, but outputs
must not move.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional, Tuple

Compressor = Callable[[str], str]

# (indexes to keep, projected header, dropped column names)
Projection = Tuple[list, str, Tuple[str, ...]]


def omission_marker(dropped: Tuple[str, ...]) -> str:
    """The inline marker appended to every non-default-profile rendering.

    Tells the model *that* data was withheld, *what*, and how to get it
    back (``full`` is an alias of the complete ``default`` profile).
    """
    return f"[omitted: {', '.join(dropped)} — re-query profile=full]"


def _projection(spec: Dict[str, Any], profile: str) -> Projection:
    """Resolve *profile* against the spec's header, loudly.

    A malformed projection (unknown column, keeps nothing, drops nothing)
    should fail the test run at build time, never ship a silently-wrong
    variant.
    """
    names = spec["header"].split(",")
    keep = list(spec["profiles"][profile]["keep"])
    unknown = [n for n in keep if n not in names]
    if unknown:
        raise ValueError(
            f"profile {profile!r} of spec {spec['id']!r} keeps unknown "
            f"columns {unknown} (header: {names})"
        )
    keep_idx = [i for i, n in enumerate(names) if n in keep]
    dropped = tuple(n for n in names if n not in keep)
    if not keep_idx or not dropped:
        raise ValueError(
            f"profile {profile!r} of spec {spec['id']!r} must keep at "
            "least one column and drop at least one"
        )
    header = ",".join(names[i] for i in keep_idx)
    return keep_idx, header, dropped


def _line_regex_table(
    spec: Dict[str, Any], projection: Optional[Projection] = None
) -> Compressor:
    row_re = re.compile(spec["row"], spec.get("row_flags", 0))
    header = spec["header"] if projection is None else projection[1]
    columns = spec.get("columns")
    strip_columns = set(spec.get("strip_columns", ()))
    context_prefixes = tuple(spec.get("context_prefixes", ()))
    unindented_only = bool(spec.get("unindented_rows_only"))

    def _compress(raw: str) -> str:
        context = None
        rows = [header]
        for line in raw.splitlines():
            if unindented_only and line[:1] in (" ", "\t"):
                continue
            stripped = line.strip()
            if context_prefixes and stripped.startswith(context_prefixes):
                context = stripped
                continue
            m = row_re.match(stripped)
            if not m:
                continue
            indexes = columns or range(1, len(m.groups()) + 1)
            values = []
            for i in indexes:
                value = m.group(i)
                if value is None:
                    value = ""
                elif i in strip_columns:
                    value = value.strip()
                values.append(value)
            if projection is not None:
                values = [values[i] for i in projection[0]]
            rows.append(",".join(values))
        if len(rows) < 2:
            return raw
        body = "\n".join(rows)
        if context_prefixes and context:
            body = f"{context}\n{body}"
        if projection is not None:
            body += "\n" + omission_marker(projection[2])
        return body

    return _compress


def _fixed_width_table(
    spec: Dict[str, Any], projection: Optional[Projection] = None
) -> Compressor:
    # Imported here (not at module top) to keep the leaf/helper dependency
    # direction obvious: engine consumes _compressors' helpers, never the
    # other way around.
    from ._compressors import _csv_row, _fixed_width_rows, _wrapped_first_col_rows

    keywords = list(spec["keywords"])
    header = spec["header"] if projection is None else projection[1]
    name_re = (
        re.compile(spec["row_match"], re.IGNORECASE)
        if spec.get("row_match") else None
    )
    first_col_wraps = bool(spec.get("first_col_wraps"))

    def _compress(raw: str) -> str:
        if first_col_wraps:
            rows = _wrapped_first_col_rows(
                raw, keywords, name_re or re.compile(r"^\S+$")
            )
        else:
            rows = _fixed_width_rows(raw, keywords, name_re)
        if not rows:
            return raw
        out = [header]
        if projection is not None:
            rows = [[r[i] for i in projection[0]] for r in rows]
        out.extend(_csv_row(r) for r in rows)
        body = "\n".join(out)
        if projection is not None:
            body += "\n" + omission_marker(projection[2])
        return body

    return _compress


def _kv_extract(
    spec: Dict[str, Any], projection: Optional[Projection] = None
) -> Compressor:
    if projection is not None:
        raise ValueError(
            f"kv_extract spec {spec['id']!r} does not support profiles"
        )
    fields = [
        (
            f["key"],
            re.compile(f["pattern"], f.get("flags", 0)),
            f.get("template", "{1}"),
            bool(f.get("strip", False)),
        )
        for f in spec["fields"]
    ]
    joiner = spec.get("joiner", " | ")

    def _compress(raw: str) -> str:
        found: dict = {}
        for line in raw.splitlines():
            for key, rx, template, strip in fields:
                if key in found:
                    continue
                m = rx.search(line)
                if m:
                    groups = [g if g is not None else "" for g in m.groups()]
                    if strip:
                        groups = [g.strip() for g in groups]
                    found[key] = template.format(m.group(0), *groups)
        if not found:
            return raw
        return joiner.join(f"{k}={v}" for k, v in found.items())

    return _compress


STRATEGIES: Dict[
    str, Callable[[Dict[str, Any], Optional[Projection]], Compressor]
] = {
    "line_regex_table": _line_regex_table,
    "fixed_width_table": _fixed_width_table,
    "kv_extract": _kv_extract,
}


def build(spec: Dict[str, Any], profile: Optional[str] = None) -> Compressor:
    """Compile *spec* into a compressor function.

    With ``profile``, compile the named declared-lossy column projection
    instead of the complete default rendering. Raises ``KeyError`` on an
    unknown strategy or profile, ``ValueError`` on a malformed projection
    — at import/registration time, deliberately: a bad spec should fail
    the test run, not silently produce a compressor that never fires.
    """
    projection = _projection(spec, profile) if profile else None
    fn = STRATEGIES[spec["strategy"]](spec, projection)
    suffix = f"@{profile}" if profile else ""
    fn.__name__ = f"spec:{spec['id']}{suffix}"
    fn.__doc__ = spec.get("doc", f"spec-built compressor {spec['id']}")
    return fn


def profile_drops(spec: Dict[str, Any], profile: str) -> Tuple[str, ...]:
    """Column names the named profile omits — the projection's addition to
    the entry's lossiness manifest."""
    return _projection(spec, profile)[2]
