"""Hand-written compressors — the code tier of the registry.

Since Phase 1, table-shaped command families live as declarative specs
(``specs.py``) compiled by the engine — and since Phase 2 the same is
true of ``show version``-style field scans (``kv_extract``). What remains
here is the small set of genuinely stateful formats a flat spec cannot
express faithfully — multi-line interface-detail blocks (NX-OS splits
state across lines), banner state machines, and multi-table zero-row
suppression — plus the fixed-width helpers the engine reuses.
Registration order lives in ``registry.py``; nothing self-registers here.

Only the standard library may be imported — this module stays the
zero-dependency leaf of the package. Function bodies are byte-parity
pinned against the pre-extraction baseline by the test suite.
"""

from __future__ import annotations

import re
from typing import Optional

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


# ---------------------------------------------------------------------------
# show interfaces (per-interface detail, IOS + NX-OS)
# ---------------------------------------------------------------------------

_INTF_HEADER = re.compile(r"^(\S+)\s+is\s+(administratively\s+)?(up|down),\s+line protocol is\s+(up|down)")
# NX-OS splits the IOS one-liner across two lines: "EthX is up" (oper/link
# state) followed by "admin state is up, ..." on the next line. A down port
# carries a reason in parens: "EthX is down (Administratively down)".
_INTF_NXOS_HEADER = re.compile(r"^(\S+)\s+is\s+(up|down)(?:\s+\(([^)]+)\))?\s*$")
_INTF_NXOS_ADMIN = re.compile(r"admin state is\s+(up|down)")
_INTF_MTU = re.compile(r"MTU\s+(\d+)\s+bytes")
_INTF_BW = re.compile(r"BW\s+(\d+)\s+(Kbit|Mbit|Gbit)")
# NX-OS renders duplex lower-case ("full-duplex, 10 Gb/s"); match either case.
_INTF_DUPLEX = re.compile(r"(Full|Half|Auto)-duplex,\s*(\S+)", re.IGNORECASE)
_INTF_INPUT_RATE = re.compile(r"input rate\s+(\d+)\s+bits/sec")
_INTF_OUTPUT_RATE = re.compile(r"output rate\s+(\d+)\s+bits/sec")
# NX-OS uses the singular ("0 input error"); IOS the plural ("0 input errors").
_INTF_INPUT_ERRORS = re.compile(r"(\d+)\s+input errors?")
_INTF_OUTPUT_ERRORS = re.compile(r"(\d+)\s+output errors?")
_INTF_CRC = re.compile(r"(\d+)\s+CRC")
_INTF_DESCRIPTION = re.compile(r"Description:\s+(.+)")


def _compress_interfaces(raw: str) -> str:
    blocks: list = []
    current: dict = {}

    def _flush():
        if current.get("name"):
            parts = [
                current["name"],
                f"status={current.get('status', '?')}/{current.get('proto', '?')}",
            ]
            if current.get("reason"):
                parts.append(f'reason="{current["reason"]}"')
            if current.get("desc"):
                parts.append(f'desc="{current["desc"]}"')
            if current.get("mtu"):
                parts.append(f"mtu={current['mtu']}")
            if current.get("bw"):
                parts.append(f"bw={current['bw']}")
            if current.get("duplex"):
                parts.append(f"duplex={current['duplex']}")
            if current.get("in_rate"):
                parts.append(f"in_bps={current['in_rate']}")
            if current.get("out_rate"):
                parts.append(f"out_bps={current['out_rate']}")
            if current.get("in_err") and current["in_err"] != "0":
                parts.append(f"in_errors={current['in_err']}")
            if current.get("out_err") and current["out_err"] != "0":
                parts.append(f"out_errors={current['out_err']}")
            if current.get("crc") and current["crc"] != "0":
                parts.append(f"crc={current['crc']}")
            blocks.append(" | ".join(parts))

    for line in raw.splitlines():
        stripped = line.strip()
        m = _INTF_HEADER.match(stripped)
        if m:
            _flush()
            current = {
                "name": m.group(1),
                "status": "admin-down" if m.group(2) else m.group(3),
                "proto": m.group(4),
            }
            continue
        m = _INTF_NXOS_HEADER.match(stripped)
        if m:
            _flush()
            oper = m.group(2)
            # status <- admin state (filled by the next line); proto <- oper.
            current = {"name": m.group(1), "status": oper, "proto": oper}
            if m.group(3):
                current["reason"] = m.group(3)
            continue
        m = _INTF_NXOS_ADMIN.search(stripped)
        if m and current:
            current["status"] = m.group(1)
            continue
        for regex, key in [
            (_INTF_MTU, "mtu"), (_INTF_INPUT_RATE, "in_rate"),
            (_INTF_OUTPUT_RATE, "out_rate"), (_INTF_INPUT_ERRORS, "in_err"),
            (_INTF_OUTPUT_ERRORS, "out_err"), (_INTF_CRC, "crc"),
        ]:
            mm = regex.search(stripped)
            if mm:
                current[key] = mm.group(1)
        mm = _INTF_BW.search(stripped)
        if mm:
            current["bw"] = f"{mm.group(1)}{mm.group(2)}"
        mm = _INTF_DUPLEX.search(stripped)
        if mm:
            current["duplex"] = f"{mm.group(1)}/{mm.group(2)}"
        mm = _INTF_DESCRIPTION.search(stripped)
        if mm:
            current["desc"] = mm.group(1).strip()

    _flush()
    if not blocks:
        return raw
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# show running-config
# ---------------------------------------------------------------------------

def _compress_running_config(raw: str) -> str:
    lines = raw.splitlines()
    out: list = []
    skip_banners = False
    for line in lines:
        stripped = line.strip()
        # Skip empty lines, comments, timestamps, building-config notice
        if not stripped:
            continue
        if stripped.startswith("!"):
            continue
        if stripped.startswith("Building configuration"):
            continue
        if stripped.startswith("Current configuration"):
            continue
        if stripped.startswith("end"):
            continue
        # Collapse banner blocks
        if stripped.startswith("banner "):
            out.append(stripped.split("\n")[0] + " ...")
            skip_banners = True
            continue
        if skip_banners:
            if stripped in ("^C", "EOF", "^"):
                skip_banners = False
            continue
        out.append(line.rstrip())
    if not out:
        return raw
    return "\n".join(out)


# ---------------------------------------------------------------------------
# show access-lists
# ---------------------------------------------------------------------------

def _compress_acl(raw: str) -> str:
    lines = raw.splitlines()
    out: list = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Remove hit counters to save tokens
        stripped = re.sub(r"\s*\(\d+\s+match(?:es)?\)", "", stripped)
        out.append(stripped)
    if not out:
        return raw
    return "\n".join(out)


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
    saw_table = False

    def _flush() -> None:
        nonlocal cols, table_rows
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

    for line in raw.splitlines():
        s = line.strip()
        if not s or set(s) <= {"-"}:
            continue
        toks = s.split()
        if toks[0] == "Port":
            _flush()
            cols = toks
            saw_table = True
            continue
        if (
            cols
            and len(toks) == len(cols)
            and all(_COUNTER_VAL_RE.match(t) for t in toks[1:])
        ):
            if any(t not in ("0", "--") for t in toks[1:]):
                table_rows.append(",".join(toks))
    _flush()
    if not saw_table:
        return raw
    body = "\n".join(out).rstrip()
    return "show interface counters errors (non-zero ports only; all others 0):\n" + body


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
