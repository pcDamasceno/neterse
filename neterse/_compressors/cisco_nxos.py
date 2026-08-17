"""Code compressors for NX-OS-shaped output.

Split from the original single-module ``_compressors.py``
(decision 42) — function bodies are verbatim and remain pinned
by the parity suite and the fixture goldens. Only the standard
library may be imported. Registration order lives in
``registry.py``; nothing self-registers here.
"""

from __future__ import annotations

import re
from typing import Optional
from .helpers import _csv_row, _iface_block_header, _slug


# ---------------------------------------------------------------------------
# show interface counters errors (NX-OS)
# ---------------------------------------------------------------------------

_COUNTER_VAL_RE = re.compile(r"^(?:\d+|--)$")


def _compress_intf_counter_errors(raw: str) -> str:
    """``show interface counters errors`` (NX-OS) → only ports with a non-zero
    counter, per sub-table.

    NX-OS prints several wide tables (one row per port, often 250+ lines) that
    are almost entirely zeros. Keeping just each sub-table's header plus its
    non-zero rows is the difference between a truncated, partly-lost table and
    a complete, tiny one.
    """
    out: list = []
    cols: Optional[list] = None
    table_rows: list = []
    pending_tokens: list = []
    saw_table = False

    def _flush() -> None:
        nonlocal cols, table_rows, pending_tokens
        if cols is not None:
            header = ",".join(["port"] + cols[1:])
            if table_rows:
                out.append(header)
                out.extend(table_rows)
            else:
                out.append(header + "  (all zero)")
            out.append("")
        cols = None
        table_rows = []
        pending_tokens = []

    def _consume(tokens: list) -> bool:
        if (
            cols
            and len(tokens) == len(cols)
            and all(_COUNTER_VAL_RE.match(token) for token in tokens[1:])
        ):
            if any(token not in ("0", "--") for token in tokens[1:]):
                table_rows.append(",".join(tokens))
            return True
        return False

    for line in raw.splitlines():
        s = line.strip()
        if not s or set(s) <= {"-"}:
            continue
        toks = s.split()
        if pending_tokens:
            combined = pending_tokens + toks
            if _consume(combined):
                pending_tokens = []
                continue
            return raw
        if toks[0] == "Port":
            _flush()
            cols = toks
            saw_table = True
            continue
        if _consume(toks):
            continue
        if (
            cols
            and 1 < len(toks) < len(cols)
            and all(_COUNTER_VAL_RE.match(token) for token in toks[1:])
        ):
            pending_tokens = toks
    if pending_tokens:
        return raw
    _flush()
    if not saw_table:
        return raw
    body = "\n".join(out).rstrip()
    return "show interface counters errors (non-zero ports only; all others 0):\n" + body


# ---------------------------------------------------------------------------
# show interface [selector] transceiver (NX-OS inventory, not details)
# ---------------------------------------------------------------------------

_TRANSCEIVER_FIELD_RE = re.compile(r"^\s+(.+?)\s+is\s+(.+?)\s*$")


def _compress_transceiver_inventory(raw: str) -> str:
    rows: list = []
    current: Optional[dict] = None
    field_names: list = []

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        header = _iface_block_header(line)
        if header is not None:
            current = {"interface": header}
            rows.append(current)
            continue
        match = _TRANSCEIVER_FIELD_RE.match(line)
        if current is None or match is None:
            return raw
        key, value = match.groups()
        if key in current:
            return raw
        current[key] = value
        if key not in field_names:
            field_names.append(key)

    if not rows or not field_names or any(len(row) < 2 for row in rows):
        return raw

    normalized = [_slug(name) for name in field_names]
    if len(set(normalized)) != len(normalized):
        return raw
    out = [_csv_row(["interface"] + normalized)]
    out.extend(
        _csv_row([row["interface"]] + [row.get(name, "") for name in field_names])
        for row in rows
    )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# show port-channel summary (NX-OS)
# ---------------------------------------------------------------------------

def _compress_portchannel_summary(raw: str) -> str:
    """``show port-channel summary`` (NX-OS) → CSV. The ~10-line static Flags
    legend and dashed separators are pure boilerplate and dropped."""
    rows = ["group,port_channel,type,protocol,member_ports"]
    for line in raw.splitlines():
        s = line.strip()
        if not s or set(s) <= {"-"}:
            continue
        toks = s.split()
        if (
            toks[0].isdigit()
            and len(toks) >= 2
            and re.match(r"^(?:po|port-channel)\d", toks[1], re.IGNORECASE)
        ):
            group, po = toks[0], toks[1]
            typ = toks[2] if len(toks) > 2 else ""
            proto = toks[3] if len(toks) > 3 else ""
            members = " ".join(toks[4:]) if len(toks) > 4 else ""
            rows.append(_csv_row([group, po, typ, proto, members]))
    if len(rows) < 2:
        return raw
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# show hardware internal errors (NX-OS ASIC error counters)
# ---------------------------------------------------------------------------

_HWERR_CATEGORY_RE = re.compile(r"Device Statistics Category\s*::\s*(\S+)")
_HWERR_MOD_RE = re.compile(r"\bMod:\s*(\d+)")
_HWERR_INSTANCE_RE = re.compile(r"^Instance:\s*(\d+)\s*$")
_HWERR_VALUE_RE = re.compile(r"^[0-9A-Fa-f]{6,}$")


def _compress_hardware_internal_errors(raw: str) -> str:
    """``show hardware internal errors module N`` → nonzero counters, CSV.

    NX-OS prints one banner-boxed section per statistics category (ERROR,
    QOS, CONGESTION, …); each data row is ``ID Name <16-digit value> port``.
    The box-drawing banners and dashed rules are dropped, the zero-padded
    counter is reduced to its significant digits (lossless), and all-zero
    rows are suppressed with a per-section marker so an empty category
    stays explicit.
    """
    sections: list = []                       # [{"cat","mod","instance","rows","zeros"}]
    cur: Optional[dict] = None
    pending_mod: Optional[str] = None
    saw = False

    for line in raw.splitlines():
        s = line.strip().strip("|").strip()
        if not s or set(s) <= {"-", " "}:
            continue
        mm = _HWERR_MOD_RE.search(s)
        if mm and "Device:" in s:
            pending_mod = mm.group(1)
            continue
        cm = _HWERR_CATEGORY_RE.search(s)
        if cm:
            cur = {"cat": cm.group(1), "mod": pending_mod,
                   "instance": None, "rows": [], "zeros": 0}
            sections.append(cur)
            saw = True
            continue
        im = _HWERR_INSTANCE_RE.match(s)
        if im:
            if cur is not None:
                cur["instance"] = im.group(1)
            continue
        toks = s.split()
        if toks and toks[0] in ("ID", "Last", "Device"):
            continue                          # column header / residual banner
        if (
            cur is not None
            and len(toks) >= 3
            and toks[0].isdigit()
            and _HWERR_VALUE_RE.match(toks[2])
        ):
            value = toks[2].lstrip("0")
            if not value:
                cur["zeros"] += 1
                continue
            ports = " ".join(toks[3:])
            cur["rows"].append(_csv_row([toks[0], toks[1], value, ports]))
    if not saw:
        return raw

    out = ["show hardware internal errors (nonzero counters; padding stripped):"]
    for sec in sections:
        head = f"[{sec['cat']}]"
        if sec["mod"]:
            head += f" mod={sec['mod']}"
        if sec["instance"] is not None:
            head += f" instance={sec['instance']}"
        if sec["rows"]:
            if sec["zeros"]:
                head += f" (+{sec['zeros']} zero rows omitted)"
            out.append(head)
            out.append("id,name,value,ports")
            out.extend(sec["rows"])
        else:
            zeros = f" ({sec['zeros']} rows all zero)" if sec["zeros"] else " (none)"
            out.append(head + zeros)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# show environment (NX-OS power / fan / temperature)
# ---------------------------------------------------------------------------

def _compress_environment(raw: str) -> str:
    """``show environment`` → the same tables without decorative rules or
    column-alignment padding.

    Every dashed separator line is dropped and each remaining line has its
    runs of whitespace collapsed to a single space (device fields here are
    space-free, so no column is corrupted). No data is dropped.
    """
    out: list = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or set(s) <= {"-", " "}:
            continue
        out.append(re.sub(r"\s{2,}", " ", s))
    if not out:
        return raw
    return "\n".join(out)


# ---------------------------------------------------------------------------
# show interface [selector] transceiver details (NX-OS DOM / optical)
# ---------------------------------------------------------------------------

_XCVR_DETAIL_TITLE_RE = re.compile(r"Detail Diagnostics", re.IGNORECASE)
_XCVR_METRIC_RE = re.compile(r"^([A-Za-z][A-Za-z ]*?)\s+(-?\d[\d.]*\s+\S+)\b")
_XCVR_FAULT_RE = re.compile(r"^(.*?)\s*=\s*(\S+)\s*$")


def _compress_transceiver_details(raw: str) -> str:
    """``show interface … transceiver details`` (NX-OS) → per-interface
    key=value header fields plus only the *current* DOM measurement.

    DECLARED LOSSY: the static per-optic alarm/warning threshold columns
    (high/low alarm and warning) are dropped — they are fixed properties of
    the SFP type, not live state — along with the diagnostics title, the
    column-header rows, the dashed rules and the notation legend. Fail-open
    unless at least one interface block with fields parses.
    """
    blocks: list = []                         # [(iface, [field lines])]
    current: Optional[list] = None
    in_dom = False
    saw_field = False

    def _open(name: str) -> None:
        nonlocal current, in_dom
        current = []
        in_dom = False
        blocks.append((name, current))

    for line in raw.splitlines():
        s = line.strip()
        if not s or set(s) <= {"-"}:
            continue
        header = _iface_block_header(line)
        if header is not None:
            _open(header)
            continue
        if current is None:
            return raw
        if _XCVR_DETAIL_TITLE_RE.search(s):
            in_dom = True
            continue
        if in_dom:
            if s.startswith("Note:") or s.startswith(("Current", "Measurement", "High", "Low")):
                continue
            fault = _XCVR_FAULT_RE.match(s)     # "Transmit Fault Count = 0"
            if fault:
                key = _slug(fault.group(1))
                current.append(key + "=" + fault.group(2))
                continue
            metric = _XCVR_METRIC_RE.match(s)
            if metric:
                key = _slug(metric.group(1))
                value = re.sub(r"\s+", " ", metric.group(2))
                current.append(key + "=" + value)
                saw_field = True
            continue
        fm = _TRANSCEIVER_FIELD_RE.match(line)   # "    type is 10Gbase-LR"
        if fm:
            key = _slug(fm.group(1))
            current.append(key + "=" + fm.group(2).strip())
            saw_field = True
            continue
        # Unrecognized non-blank line inside a block -> fail-open (don't lose it).
        return raw

    if not blocks or not saw_field:
        return raw
    out = ["show interface transceiver details "
           "(current DOM only; alarm/warning thresholds omitted):"]
    for name, fields in blocks:
        if not fields:
            return raw
        out.append(f"{name}: " + " ".join(fields))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# show interface [selector] capabilities (NX-OS)
# ---------------------------------------------------------------------------

_CAPABILITY_FIELD_RE = re.compile(r"^\s+(.+?):\s+(.*\S)\s*$")


def _compress_interface_capabilities(raw: str) -> str:
    """``show interface … capabilities`` (NX-OS) → one ``key=value`` line per
    interface, dropping the colon-alignment padding.

    Each interface is a header at column 0 followed by indented
    ``Field:            value`` rows; only the padding is presentation.
    Fail-open unless at least one interface with fields parses.
    """
    blocks: list = []
    current: Optional[list] = None
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        header = _iface_block_header(line)
        if header is not None:
            current = []
            blocks.append((header, current))
            continue
        m = _CAPABILITY_FIELD_RE.match(line)
        if current is None or m is None:
            return raw
        key = _slug(m.group(1))
        current.append(key + "=" + m.group(2))
    if not blocks or any(not fields for _, fields in blocks):
        return raw
    return "\n".join(f"{name}: " + " ".join(fields) for name, fields in blocks)
