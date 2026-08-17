"""Code compressors for IOS/IOS-XE-shaped output.

Split from the original single-module ``_compressors.py``
(decision 42) — function bodies are verbatim and remain pinned
by the parity suite and the fixture goldens. Only the standard
library may be imported. Registration order lives in
``registry.py``; nothing self-registers here.
"""

from __future__ import annotations

import re
from typing import Optional
from .helpers import _csv_row, _header_positions


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
