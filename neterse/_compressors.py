"""Hand-written compressors — the code tier of the registry.

Since Phase 1, table-shaped command families live as declarative specs
(the YAML-authored ``specs/`` package) compiled by the engine — and
since Phase 2 the same is
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
        if not line[:1].isspace() and _IFACE_NAME_RE.match(stripped):
            current = {"interface": stripped}
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

    normalized = [re.sub(r"\W+", "_", name.lower()).strip("_") for name in field_names]
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
# show processes memory sorted (IOS/IOS-XE)
# ---------------------------------------------------------------------------

_PROCESS_MEMORY_ROW = re.compile(
    r"^(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.+)$"
)
_PROCESS_MEMORY_POOL = re.compile(r"^\s*\S(?:.*\s)?Pool Total:")


def _compress_processes_memory_sorted(raw: str) -> str:
    """Render every pool total and process row without alignment padding."""
    pools: list = []
    rows = ["pid,tty,allocated,freed,holding,getbufs,retbufs,process"]
    for line in raw.splitlines():
        if _PROCESS_MEMORY_POOL.match(line):
            pools.append(line.strip())
            continue
        match = _PROCESS_MEMORY_ROW.match(line.strip())
        if match:
            rows.append(_csv_row(list(match.groups())))
    if not pools or len(rows) < 2:
        return raw
    return "\n".join(pools + rows)


# ---------------------------------------------------------------------------
# show vrf / show ip route vrf * summary (IOS/IOS-XE)
# ---------------------------------------------------------------------------

_VRF_HEADER_WORDS = ["Name", "Default RD", "Protocols", "Interfaces"]


def _compress_show_vrf(raw: str) -> str:
    """Collapse wrapped interface rows into one lossless CSV row per VRF."""
    lines = raw.splitlines()
    positions, start = _header_positions(lines, _VRF_HEADER_WORDS)
    if not positions:
        return raw
    bounds = positions + [10 ** 6]
    records: list = []
    current: Optional[list] = None
    platform_records: list = []
    platform_current: Optional[list] = None
    platform_bounds: Optional[list] = None
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or set(stripped) <= {"-"}:
            continue
        if stripped.startswith("Platform iVRF Name"):
            platform_positions = [
                line.find(word)
                for word in ("Platform iVRF Name", "iVRF Id", "Interfaces")
            ]
            if platform_positions != sorted(platform_positions) or platform_positions[0] < 0:
                return raw
            platform_bounds = platform_positions + [10 ** 6]
            continue
        if platform_bounds is not None:
            cols = [
                line[platform_bounds[i]:platform_bounds[i + 1]].strip()
                for i in range(3)
            ]
            if cols[0]:
                if not cols[1]:
                    return raw
                platform_current = [cols[0], cols[1], []]
                platform_records.append(platform_current)
            elif platform_current is None or not cols[2]:
                return raw
            if platform_current is not None and cols[2]:
                platform_current[2].append(cols[2])
            continue
        cols = [line[bounds[i]:bounds[i + 1]].strip() for i in range(len(positions))]
        if cols[0]:
            if not cols[1] or not cols[2]:
                return raw
            current = [cols[0], cols[1], cols[2], []]
            records.append(current)
        elif current is not None and cols[3]:
            current[3].append(cols[3])
        else:
            return raw
        if current is not None and cols[3] and not current[3]:
            current[3].append(cols[3])
    if not records:
        return raw
    out = ["name,default_rd,protocols,interfaces"]
    for name, rd, protocols, interfaces in records:
        out.append(_csv_row([name, rd, protocols, ";".join(interfaces)]))
    if platform_records:
        out.append("platform_ivrf_name,ivrf_id,interfaces")
        for name, ivrf_id, interfaces in platform_records:
            out.append(_csv_row([name, ivrf_id, ";".join(interfaces)]))
    return "\n".join(out)


_ROUTE_SUMMARY_NAME = re.compile(
    r"^IP routing table name is (.+?) \((0x[0-9A-Fa-f]+)\)$"
)
_ROUTE_SUMMARY_MAX_PATHS = re.compile(r"^IP routing table maximum-paths is (\d+)$")
_ROUTE_SUMMARY_HEADER = [
    "Route Source", "Networks", "Subnets", "Replicates", "Overhead", "Memory (bytes)",
]


def _compress_ip_route_vrf_summary(raw: str) -> str:
    """Render each complete per-VRF route-source summary as compact CSV."""
    if "[TRUNCATED" in raw:
        return raw
    out: list = []
    current_vrf: Optional[str] = None
    positions: Optional[list] = None
    row_count = 0
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _ROUTE_SUMMARY_NAME.match(stripped)
        if match:
            current_vrf = match.group(1)
            positions = None
            out.append(f"vrf={current_vrf},id={match.group(2)}")
            continue
        match = _ROUTE_SUMMARY_MAX_PATHS.match(stripped)
        if match and current_vrf:
            out[-1] += f",max_paths={match.group(1)}"
            continue
        if all(word in line for word in _ROUTE_SUMMARY_HEADER):
            positions = [line.find(word) for word in _ROUTE_SUMMARY_HEADER]
            if positions != sorted(positions) or positions[0] < 0:
                return raw
            out.append("source,networks,subnets,replicates,overhead,memory_bytes")
            continue
        if current_vrf is None or positions is None:
            return raw
        if line[:1].isspace():
            out.append("detail," + re.sub(r"\s+", " ", stripped))
            continue
        bounds = positions + [10 ** 6]
        cols = [line[bounds[i]:bounds[i + 1]].strip() for i in range(len(positions))]
        if not cols[0] or not any(cols[1:]):
            return raw
        out.append(_csv_row(cols))
        row_count += 1
    if row_count == 0:
        return raw
    return "\n".join(out)


# ---------------------------------------------------------------------------
# show bgp all summary (IOS/IOS-XE)
# ---------------------------------------------------------------------------

_BGP_ALL_AF = re.compile(r"^For address family:\s*(.+)$")
_BGP_ALL_ROW = re.compile(
    r"^(\S+)\s+"             # neighbor
    r"(\d+)\s+"              # version
    r"(\d+(?:\.\d+)?)\s+"  # AS (plain or asdot)
    r"(\d+)\s+"              # messages received
    r"(\d+)\s+"              # messages sent
    r"(\d+)\s+"              # table version
    r"(\d+)\s+"              # input queue
    r"(\d+)\s+"              # output queue
    r"(\S+)"                  # up/down
    r"(?:\s+(.+?))?\s*$"     # state/prefixes, when not wrapped
)
_BGP_ALL_HEADER_WORDS = (
    "Neighbor", "V", "AS", "MsgRcvd", "MsgSent", "TblVer", "InQ", "OutQ",
    "Up/Down", "State",
)


def _compress_bgp_all_summary(raw: str) -> str:
    """Rejoin wrapped State/PfxRcd cells and preserve all summary metadata."""
    if "[TRUNCATED" in raw:
        return raw
    out: list = []
    pending: Optional[list] = None
    saw_family = False
    in_table = False
    row_count = 0

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if pending is not None:
            if line[:1].isspace() and stripped:
                out.append(_csv_row(pending + [stripped]))
                pending = None
                row_count += 1
                continue
            return raw

        family = _BGP_ALL_AF.match(stripped)
        if family:
            saw_family = True
            in_table = False
            out.append(f"address_family={family.group(1)}")
            continue
        if not saw_family:
            return raw
        if all(word in line for word in _BGP_ALL_HEADER_WORDS):
            if in_table:
                return raw
            in_table = True
            out.append(
                "neighbor,v,as,msg_rcvd,msg_sent,tbl_ver,in_q,out_q,up_down,state_pfx_rcd"
            )
            continue
        if in_table and stripped == "/PfxRcd":
            continue
        if in_table:
            match = _BGP_ALL_ROW.match(stripped)
            if match is None:
                return raw
            fields = list(match.groups())
            state = fields.pop()
            if state is None:
                pending = fields
            else:
                out.append(_csv_row(fields + [state]))
                row_count += 1
            continue
        out.append(stripped)

    if pending is not None or not saw_family or row_count == 0:
        return raw
    return "\n".join(out)


# ---- show ip protocols (IOS/IOS-XE) ---------------------------------------
# Block-structured output — one "Routing Protocol is ..." block per process
# — that no table strategy fits. Known boilerplate collapses to key=value
# parts; list sections (networks / sources / neighbors / passive) join
# their items; ANY unrecognized line inside a block is preserved verbatim
# (whitespace-collapsed), so format drift degrades compression, never
# faithfulness.

_IPPROTO_HEADER = re.compile(r'^Routing Protocol is "([^"]+)"')
_IPPROTO_SECTIONS = {
    "Routing for Networks:": "networks",
    "Routing Information Sources:": "sources",
    "Neighbor(s):": "neighbors",
    "Passive Interface(s):": "passive",
}
# Static column headers inside list sections — presentation, not data.
_IPPROTO_SECTION_HEADER = re.compile(
    r"^(?:Gateway\s+Distance\s+Last Update"
    r"|Address\s+FiltIn\s+FiltOut\s+DistIn\s+DistOut\s+Weight\s+RouteMap)$"
)
_IPPROTO_FILTER_NOT_SET = re.compile(
    r"^(Outgoing|Incoming) update filter list for all interfaces is not set$"
)
_IPPROTO_LINES = [
    (re.compile(r"^Sending updates every (\d+) seconds$"), "updates_every={0}s"),
    (re.compile(r"^Invalid after (\d+) seconds, hold down (\d+), flushed after (\d+)$"),
     "invalid={0} holddown={1} flushed={2}"),
    (re.compile(r"^IGP synchronization is (\S+)$"), "igp_sync={0}"),
    (re.compile(r"^Automatic route summarization is (\S+)$"), "auto_summary={0}"),
    (re.compile(r"^Automatic network summarization is (.+)$"), "net_summary={0}"),
    (re.compile(r"^Router ID (\S+)$"), "router_id={0}"),
    (re.compile(r"^Number of areas in this router is (.+)$"), "areas={0}"),
    (re.compile(r"^Maximum path: (\d+)$"), "max_path={0}"),
    (re.compile(r"^Distance: \(default is (\d+)\)$"), "distance=default {0}"),
    (re.compile(r"^Distance: (.+)$"), "distance={0}"),
]


def _compress_ip_protocols(raw: str) -> str:
    """``show ip protocols`` (IOS) → one line per routing-protocol block.

    ``proto "bgp 200": filters=none | igp_sync=disabled | neighbors=… |
    distance=external 20 internal 200 local 200``. Empty list sections
    are omitted and static sub-table column headers dropped (both
    declared); every unrecognized block line survives verbatim.
    """
    lines = raw.splitlines()
    out: list = []
    parts: Optional[list] = None      # None while in the preamble
    filters: set = set()
    filter_slot = -1
    section: Optional[str] = None
    section_indent = 0
    section_items: list = []

    def _flush_section() -> None:
        nonlocal section, section_items
        if section and section_items:
            parts.append(f"{section}=" + "; ".join(section_items))
        section, section_items = None, []

    def _flush_block() -> None:
        nonlocal parts, filters, filter_slot
        if parts is None:
            return
        _flush_section()
        if filters:
            label = (
                "filters=none" if len(filters) == 2
                else f"{next(iter(filters)).lower()}_filter=none"
            )
            parts[filter_slot] = label
        rendered = [p for p in parts if p is not None]
        head, rest = rendered[0], rendered[1:]
        out.append(f"{head}: " + " | ".join(rest) if rest else head)
        parts, filters, filter_slot = None, set(), -1

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if parts is not None:
                _flush_section()
            continue
        m = _IPPROTO_HEADER.match(stripped)
        if m:
            _flush_block()
            parts = [f'proto "{m.group(1)}"']
            continue
        if parts is None:
            out.append(stripped)                     # preamble, verbatim
            continue
        indent = len(line) - len(line.lstrip())
        if section is not None:
            if indent > section_indent:
                if not _IPPROTO_SECTION_HEADER.match(stripped):
                    section_items.append(re.sub(r"\s+", " ", stripped))
                continue
            _flush_section()                         # dedent: normal line again
        if stripped in _IPPROTO_SECTIONS:
            section = _IPPROTO_SECTIONS[stripped]
            section_indent = indent
            continue
        fm = _IPPROTO_FILTER_NOT_SET.match(stripped)
        if fm:
            if filter_slot < 0:
                filter_slot = len(parts)
                parts.append(None)                   # placeholder, filled at flush
            filters.add(fm.group(1))
            continue
        for rx, template in _IPPROTO_LINES:
            lm = rx.match(stripped)
            if lm:
                parts.append(template.format(*lm.groups()))
                break
        else:
            parts.append(re.sub(r"\s+", " ", stripped))   # unknown: keep verbatim
    _flush_block()
    if not any(p.startswith('proto "') for p in out):
        return raw
    return "\n".join(out)


# ---------------------------------------------------------------------------
# show inventory (IOS / NX-OS)
# ---------------------------------------------------------------------------

_INV_NAME_RE = re.compile(r'^NAME:\s*"(.*?)"\s*,\s*DESCR:\s*"(.*?)"\s*$')
_INV_PID_RE = re.compile(
    r"^PID:\s*(.*?)\s*,\s*VID:\s*(.*?)\s*,\s*SN:\s*(.*?)\s*$"
)


def _compress_inventory(raw: str) -> str:
    """``show inventory`` → one CSV row per component.

    Each entry is a ``NAME: "…", DESCR: "…"`` line followed by a heavily
    space-padded ``PID: … , VID: … , SN: …`` line; the padding and the
    two-line split are pure presentation. Fail-open unless at least one
    complete entry parses.
    """
    rows = [["name", "descr", "pid", "vid", "sn"]]
    pending: Optional[tuple] = None
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        nm = _INV_NAME_RE.match(s)
        if nm:
            if pending is not None:          # NAME with no PID line before it
                return raw
            pending = nm.groups()
            continue
        pm = _INV_PID_RE.match(s)
        if pm and pending is not None:
            rows.append([pending[0], pending[1], pm.group(1), pm.group(2), pm.group(3)])
            pending = None
            continue
        return raw                            # unexpected line: fail-open
    if pending is not None or len(rows) < 2:
        return raw
    return "\n".join(_csv_row(r) for r in rows)


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
        if not line[:1].isspace() and _IFACE_NAME_RE.match(s):
            _open(s)
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
                key = re.sub(r"\W+", "_", fault.group(1).strip().lower()).strip("_")
                current.append(key + "=" + fault.group(2))
                continue
            metric = _XCVR_METRIC_RE.match(s)
            if metric:
                key = re.sub(r"\W+", "_", metric.group(1).strip().lower()).strip("_")
                value = re.sub(r"\s+", " ", metric.group(2))
                current.append(key + "=" + value)
                saw_field = True
            continue
        fm = _TRANSCEIVER_FIELD_RE.match(line)   # "    type is 10Gbase-LR"
        if fm:
            key = re.sub(r"\W+", "_", fm.group(1).strip().lower()).strip("_")
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
# show logging (logfile / last N) — syslog
# ---------------------------------------------------------------------------

_SYSLOG_LINE_RE = re.compile(
    r"^(?P<ts>.+?)\s+(?P<host>\S+)\s+(?P<msg>%[\w-]+:.*)$"
)


def _compress_syslog(raw: str) -> str:
    """``show logging {logfile,last N,…}`` → the same log with the constant
    device hostname factored out of every message line.

    Every NX-OS/IOS syslog record repeats ``<timestamp> <host>
    %FACILITY-SEV-MNEMONIC: …``; when a single host owns all of them the
    hostname is pure redundancy and is stated once in a header instead.
    Lossless: lines that are not standard facility records (log headers,
    truncation markers, process messages) pass through untouched, and the
    compressor fails open unless one host owns every matched record.
    """
    lines = raw.splitlines()
    matched = [(i, m) for i, m in
               ((i, _SYSLOG_LINE_RE.match(ln)) for i, ln in enumerate(lines)) if m]
    if len(matched) < 3:
        return raw
    hosts = {m.group("host") for _, m in matched}
    if len(hosts) != 1:
        return raw
    host = next(iter(hosts))
    factored = {i for i, _ in matched}
    out = [f"host {host}; syslog (host column elided from facility records):"]
    for i, line in enumerate(lines):
        if i in factored:
            m = _SYSLOG_LINE_RE.match(line)
            out.append(m.group("ts") + " " + m.group("msg"))
        else:
            out.append(line)
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
        if not line[:1].isspace() and _IFACE_NAME_RE.match(s):
            current = []
            blocks.append((s, current))
            continue
        m = _CAPABILITY_FIELD_RE.match(line)
        if current is None or m is None:
            return raw
        key = re.sub(r"\W+", "_", m.group(1).strip().lower()).strip("_")
        current.append(key + "=" + m.group(2))
    if not blocks or any(not fields for _, fields in blocks):
        return raw
    return "\n".join(f"{name}: " + " ".join(fields) for name, fields in blocks)
