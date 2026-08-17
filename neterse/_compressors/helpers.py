"""Shared fixed-width helpers — the leaf both tiers consume.

``engine.py``'s ``fixed_width_table`` strategy and several code
compressors import from here; nothing here imports the vendor
modules (the dependency direction is one-way, helpers outward).

Split from the original single-module ``_compressors.py``
(decision 42) — function bodies are verbatim and remain pinned
by the parity suite and the fixture goldens. Only the standard
library may be imported. Registration order lives in
``registry.py``; nothing self-registers here.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Shared helpers (used by code compressors AND the spec engine)
# ---------------------------------------------------------------------------

# Interface names across IOS / NX-OS / Catalyst — used to tell a data row from
# a header, legend or continuation line in a fixed-width table.
_IFACE_NAME_RE = re.compile(
    r"^(?:mgmt|eth(?:ernet)?|po(?:rt-channel)?|vlan|lo(?:opback)?|nve|"
    r"tun(?:nel)?|gi\w*|te\w*|twe\w*|fo\w*|hu\w*|fa\w*)\d",
    re.IGNORECASE,
)


def _slug(name: str) -> str:
    """Normalize a device-printed field label to a ``key=value`` key —
    ``Type (SFP capable)`` → ``type_sfp_capable``. Shared by the
    block-shaped families (interface capabilities, transceiver inventory
    and details); a ``block_kv`` strategy formalizing that shape is
    decision 45's recorded trigger."""
    return re.sub(r"\W+", "_", name.lower()).strip("_")


def _iface_block_header(line: str) -> Optional[str]:
    """The interface name when *line* opens a per-interface block — a
    line at column 0 whose first token is interface-shaped — else
    ``None``. The shared block-splitting test of the block-shaped
    families (see ``_slug``)."""
    if line[:1].isspace():
        return None
    s = line.strip()
    return s if _IFACE_NAME_RE.match(s) else None


def _csv_row(fields: list) -> str:
    """Join *fields* as one CSV row, quoting only when a field carries a comma
    or quote (device ``Name`` columns hold spaces but rarely commas)."""
    out = []
    for f in fields:
        if ("," in f) or ('"' in f):
            f = '"' + f.replace('"', '""') + '"'
        out.append(f)
    return ",".join(out)


def _header_positions(lines: list, keywords: list) -> "Tuple[Optional[list], int]":
    """Locate the header line containing every keyword at strictly
    increasing offsets; return (column start offsets, index of the first
    data line). ``(None, 0)`` when no such header exists."""
    for i, line in enumerate(lines):
        if not all(kw in line for kw in keywords):
            continue
        pos: list = []
        last = -1
        ok = True
        for kw in keywords:
            p = line.find(kw)
            if p <= last:
                ok = False
                break
            pos.append(p)
            last = p
        if ok:
            return pos, i + 1
    return None, 0


def _fixed_width_rows(raw: str, keywords: list, name_re: Optional[re.Pattern] = None) -> Optional[list]:
    """Parse a fixed-width table whose columns start at the ``keywords`` header.

    NX-OS status/brief tables pad columns and let a ``Name`` / ``Reason`` field
    carry spaces, so a plain whitespace split corrupts them. Instead we find the
    header line, record each column's start offset, and slice every data row at
    those offsets. Header, dashed-separator and wrapped-continuation lines are
    skipped; only lines whose first column matches ``name_re`` (default: the
    Cisco-family interface-name pattern — vendor specs whose port names differ,
    e.g. Arista ``Et1`` or Aruba ``1/1/1``, pass their own via the spec's
    ``row_match`` key) are kept. Returns ``None`` when the header is absent
    (caller falls back to raw).
    """
    if name_re is None:
        name_re = _IFACE_NAME_RE
    lines = raw.splitlines()
    positions, start = _header_positions(lines, keywords)
    if not positions:
        return None
    bounds = positions + [10 ** 6]
    rows: list = []
    for line in lines[start:]:
        if not line.strip() or set(line.strip()) <= {"-"}:
            continue
        head = line[bounds[0]:bounds[1]].split()
        if not head or not name_re.match(head[0]):
            continue
        rows.append([line[bounds[k]:bounds[k + 1]].strip() for k in range(len(positions))])
    return rows


def _wrapped_first_col_rows(raw: str, keywords: list, name_re: re.Pattern) -> Optional[list]:
    """``_fixed_width_rows`` for tables whose FIRST column value may
    overflow its width and wrap onto its own line — classic IOS
    ``show cdp neighbors``: a long device ID prints alone and the
    remaining columns follow on the next line with the first column
    blank. A single-token line matching *name_re* is held as the pending
    first-column value; the next row with an empty first column consumes
    it. Legend/summary lines (spaces inside the first column slice) and
    lines with nothing in the remaining columns are skipped. Returns
    ``None`` when the header is absent (caller falls back to raw).
    """
    lines = raw.splitlines()
    positions, start = _header_positions(lines, keywords)
    if not positions:
        return None
    bounds = positions + [10 ** 6]
    rows: list = []
    pending: Optional[str] = None
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or set(stripped) <= {"-"}:
            continue
        if " " not in stripped and name_re.match(stripped):
            pending = stripped        # wrapped first column; columns follow
            continue
        cols = [line[bounds[k]:bounds[k + 1]].strip() for k in range(len(positions))]
        if not any(cols[1:]):
            continue
        if not cols[0]:
            if pending is None:
                continue
            cols[0], pending = pending, None
        elif not name_re.match(cols[0]):
            continue
        rows.append(cols)
    return rows
