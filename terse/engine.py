"""Generic strategies that turn declarative specs into compressors.

A *spec* is a plain dict (stdlib-only by design — no YAML/TOML dependency;
a YAML authoring front-end can layer on later without touching this
engine). ``build(spec)`` compiles it into the same ``Callable[[str], str]``
shape as a hand-written compressor, under the same fail-open contract: the
built function returns the raw input whenever it cannot produce a smaller,
faithful rendering.

Strategies (Phase 1):

``line_regex_table``
    One regex per data row (matched against each stripped line) → CSV.
    Spec keys: ``row`` (pattern), ``row_flags`` (int, optional),
    ``header`` (CSV header line), ``columns`` (1-based group indexes to
    emit; omit for all groups), ``strip_columns`` (group indexes whose
    value is ``.strip()``-ed), ``context_prefixes`` (lines starting with
    any of these are captured as a context line prepended to the table —
    e.g. the EIGRP process/VRF line).

``fixed_width_table``
    Offset-sliced fixed-width table → CSV, driven by the header keywords
    (see ``_compressors._fixed_width_rows``). Spec keys: ``keywords``,
    ``header``.

Byte-compatibility note: these strategies reproduce the historical
hand-written compressors exactly (None groups render as empty fields, a
header with no data rows fails open, context lines prepend with a single
newline). The parity suite pins this — restructure freely, but outputs
must not move.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict

Compressor = Callable[[str], str]


def _line_regex_table(spec: Dict[str, Any]) -> Compressor:
    row_re = re.compile(spec["row"], spec.get("row_flags", 0))
    header = spec["header"]
    columns = spec.get("columns")
    strip_columns = set(spec.get("strip_columns", ()))
    context_prefixes = tuple(spec.get("context_prefixes", ()))

    def _compress(raw: str) -> str:
        context = None
        rows = [header]
        for line in raw.splitlines():
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
            rows.append(",".join(values))
        if len(rows) < 2:
            return raw
        body = "\n".join(rows)
        if context_prefixes and context:
            return f"{context}\n{body}"
        return body

    return _compress


def _fixed_width_table(spec: Dict[str, Any]) -> Compressor:
    # Imported here (not at module top) to keep the leaf/helper dependency
    # direction obvious: engine consumes _compressors' helpers, never the
    # other way around.
    from ._compressors import _csv_row, _fixed_width_rows

    keywords = list(spec["keywords"])
    header = spec["header"]

    def _compress(raw: str) -> str:
        rows = _fixed_width_rows(raw, keywords)
        if not rows:
            return raw
        out = [header]
        out.extend(_csv_row(r) for r in rows)
        return "\n".join(out)

    return _compress


STRATEGIES: Dict[str, Callable[[Dict[str, Any]], Compressor]] = {
    "line_regex_table": _line_regex_table,
    "fixed_width_table": _fixed_width_table,
}


def build(spec: Dict[str, Any]) -> Compressor:
    """Compile *spec* into a compressor function.

    Raises ``KeyError`` on an unknown strategy — at import/registration
    time, deliberately: a malformed spec should fail the test run, not
    silently produce a compressor that never fires.
    """
    fn = STRATEGIES[spec["strategy"]](spec)
    fn.__name__ = f"spec:{spec['id']}"
    fn.__doc__ = spec.get("doc", f"spec-built compressor {spec['id']}")
    return fn
