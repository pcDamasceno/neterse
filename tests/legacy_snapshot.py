"""FROZEN Phase-0 parity baseline — DO NOT EDIT.

Verbatim copy of ``dbcli/services/token_optimizer.py (dbcli repo)`` as it stood before
the extraction into the terse package (the only edit is the
logger import swap noted below, which cannot affect return values). The
parity suite replays a corpus through this snapshot and through the
package and asserts byte-identical output; Phase 1's spec-engine
conversions are measured against this same baseline. If a compressor's
behavior must intentionally change, that is a new baseline decision —
record it, don't edit history.

Original module docstring follows.

TOON — Token-Optimized Output for Networks.

Compresses verbose CLI output into compact representations that preserve
all semantically relevant data while reducing LLM token consumption by
40-60%.  Inspired by the TOON approach from NetClaw.

Each compressor targets a specific ``show`` command family and converts
the tabular / free-form output into a dense CSV or YAML-style format
that LLMs parse easily.

Usage::

    from dbcli.services.token_optimizer import optimize

    compact = optimize(command="show ip route", raw_output=raw)
"""

from __future__ import annotations

import re
from typing import Callable, Optional

import logging

# The ONLY functional edit vs the original: stdlib logger instead of
# dbcli.core.get_logger, so the snapshot imports without the dbcli stack.
# logger.debug() return values are unused; this cannot change outputs.
logger = logging.getLogger("tests.legacy_snapshot")

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# A compressor takes raw CLI output and returns a (hopefully smaller) rendering.
Compressor = Callable[[str], str]

_COMPRESSORS: list[tuple[re.Pattern, Compressor]] = []


def _register(pattern: str):
    """Decorator — bind a compressor function to a command regex."""
    compiled = re.compile(pattern, re.IGNORECASE)

    def decorator(fn: Compressor) -> Compressor:
        _COMPRESSORS.append((compiled, fn))
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def optimize(command: str, raw_output: str) -> str:
    """Compress *raw_output* for the given CLI *command*.

    Every compressor whose pattern matches the command is tried, and the
    SMALLEST result that actually shrinks the output wins. Trying all matches
    (rather than stopping at the first) means a broad, older pattern can no
    longer shadow a newer, command-specific compressor — a real problem when
    IOS-shaped patterns overlap NX-OS command names. Each compressor is
    fail-open: an exception or a non-shrinking result simply drops it from the
    running, so the original output is never lost.
    """
    if not raw_output:
        return raw_output
    best = raw_output
    winner: Optional[str] = None
    for pattern, compressor in _COMPRESSORS:
        if not pattern.search(command):
            continue
        try:
            result = compressor(raw_output)
        except Exception:
            logger.debug(
                "TOON compressor %s failed for '%s', skipping",
                getattr(compressor, "__name__", compressor), command, exc_info=True,
            )
            continue
        if isinstance(result, str) and 0 < len(result) < len(best):
            best = result
            winner = getattr(compressor, "__name__", None)
    if winner is not None:
        saved = 100 * (1 - len(best) / len(raw_output))
        logger.debug(
            "TOON compressed '%s' via %s: %d -> %d chars (%.0f%% reduction)",
            command, winner, len(raw_output), len(best), saved,
        )
    return best


# ---------------------------------------------------------------------------
# Compressors
# ---------------------------------------------------------------------------

# ---- show ip route / show ip route vrf <name> ----------------------------

_ROUTE_LINE = re.compile(
    r"""
    ^[\s*>]*                          # selection markers
    ([A-Z*]\S*)\s+                    # protocol code (O, B, S, C, O IA, …)
    (\d+\.\d+\.\d+\.\d+/?\d*)\s+     # prefix
    (?:\[(\d+/\d+)\])?\s*             # admin/metric  [110/20]
    (?:via\s+(\S+))?                  # next-hop
    [,\s]*(?:(\S+))?                  # egress interface
    """,
    re.VERBOSE,
)


@_register(r"show\s+ip\s+route")
def _compress_ip_route(raw: str) -> str:
    lines = raw.splitlines()
    rows: list[str] = ["proto,prefix,ad/metric,next_hop,interface"]
    for line in lines:
        m = _ROUTE_LINE.match(line.strip())
        if m:
            proto, prefix, metric, nh, intf = m.groups()
            rows.append(
                f"{proto},{prefix},{metric or ''},{nh or ''},{intf or ''}"
            )
    if len(rows) < 2:
        return raw
    return "\n".join(rows)


# ---- show ip interface brief / show ip int brief -------------------------

_INTF_BRIEF_LINE = re.compile(
    r"^(\S+)\s+"              # interface
    r"(\d+\.\d+\.\d+\.\d+|unassigned)\s+"  # IP
    r"(YES|NO)\s+"            # OK?
    r"(\S+)\s+"               # method
    r"(\S+)\s+"               # status
    r"(\S+)",                 # protocol
)


@_register(r"show\s+ip\s+int(?:erface)?\s+brief")
def _compress_intf_brief(raw: str) -> str:
    lines = raw.splitlines()
    rows: list[str] = ["interface,ip,status,protocol"]
    for line in lines:
        m = _INTF_BRIEF_LINE.match(line.strip())
        if m:
            intf, ip, _ok, _method, status, proto = m.groups()
            rows.append(f"{intf},{ip},{status},{proto}")
    if len(rows) < 2:
        return raw
    return "\n".join(rows)


# ---- show interfaces (full) ---------------------------------------------

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


@_register(
    # Per-interface DETAIL only. Exclude the sub-commands (status / brief /
    # counters / transceiver / ...) whose output is a table, not "X is up,
    # line protocol is up" blocks — those have their own compressors, and
    # letting this one claim them produced silent 0%% no-ops on NX-OS.
    r"^show\s+int(?:erface|erfaces)?"
    r"(?:\s+(?!status\b|brief\b|counters?\b|transceiver\b|switchport\b|"
    r"capabilities\b|description\b|trunk\b|mac\b|flowcontrol\b|storm\b|"
    r"snmp\b|purge\b)\S+)?\s*$"
)
def _compress_interfaces(raw: str) -> str:
    blocks: list[str] = []
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


# ---- show version --------------------------------------------------------

_VERSION_FIELDS = [
    (re.compile(r"Cisco\s+(IOS|NX-OS|IOS-XE|IOS XR)\s+Software.*Version\s+(\S+)", re.I), "os", lambda m: f"{m.group(1)} {m.group(2)}"),
    (re.compile(r"uptime is\s+(.+)", re.I), "uptime", lambda m: m.group(1).strip()),
    (re.compile(r"(\d+[KMG])\s+bytes of (?:physical\s+)?memory", re.I), "memory", lambda m: m.group(1)),
    (re.compile(r"[Pp]rocessor\s+board\s+ID\s+(\S+)"), "serial", lambda m: m.group(1)),
    (re.compile(r"[Mm]odel\s+number\s*:\s*(\S+)"), "model", lambda m: m.group(1)),
    (re.compile(r"[Ss]ystem\s+image\s+file\s+is\s+\"([^\"]+)\""), "image", lambda m: m.group(1)),
]


@_register(r"show\s+version")
def _compress_version(raw: str) -> str:
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        for regex, key, extractor in _VERSION_FIELDS:
            m = regex.search(line)
            if m and key not in fields:
                fields[key] = extractor(m)
    if not fields:
        return raw
    return " | ".join(f"{k}={v}" for k, v in fields.items())


# ---- show ip bgp summary ------------------------------------------------

_BGP_NEIGHBOR = re.compile(
    r"^(\d+\.\d+\.\d+\.\d+)\s+"    # neighbor
    r"(\d+)\s+"                      # AS
    r".*?\s+"                        # skip msg fields
    r"(\S+)\s*$",                    # state/pfxrcd
)


@_register(r"show\s+(?:ip\s+)?bgp\s+summary")
def _compress_bgp_summary(raw: str) -> str:
    rows: list[str] = ["neighbor,as,state_pfxrcd"]
    for line in raw.splitlines():
        m = _BGP_NEIGHBOR.match(line.strip())
        if m:
            rows.append(f"{m.group(1)},{m.group(2)},{m.group(3)}")
    if len(rows) < 2:
        return raw
    return "\n".join(rows)


# ---- show ip ospf neighbor -----------------------------------------------

_OSPF_NBR = re.compile(
    r"^(\d+\.\d+\.\d+\.\d+)\s+"    # neighbor ID
    r"(\d+)\s+"                      # priority
    r"(\S+)\s+"                      # state
    r"(\S+)\s+"                      # dead time
    r"(\d+\.\d+\.\d+\.\d+)\s+"     # address
    r"(\S+)",                        # interface
)


@_register(r"show\s+ip\s+ospf\s+neigh")
def _compress_ospf_neighbor(raw: str) -> str:
    rows: list[str] = ["neighbor_id,priority,state,dead_time,address,interface"]
    for line in raw.splitlines():
        m = _OSPF_NBR.match(line.strip())
        if m:
            rows.append(",".join(m.groups()))
    if len(rows) < 2:
        return raw
    return "\n".join(rows)


# ---- show running-config -------------------------------------------------

@_register(r"show\s+run")
def _compress_running_config(raw: str) -> str:
    lines = raw.splitlines()
    out: list[str] = []
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


# ---- show cdp neighbors / show lldp neighbors ----------------------------

_CDP_LINE = re.compile(
    r"^(\S+)\s+"       # device ID
    r"(\S+)\s+"        # local intf
    r"\d+\s+"          # holdtime
    r"(\S.*\S)\s+"     # capability
    r"(\S+)\s+"        # platform
    r"(\S+)\s*$",      # port ID
)


@_register(r"show\s+(?:cdp|lldp)\s+neigh")
def _compress_cdp_neighbors(raw: str) -> str:
    rows: list[str] = ["device,local_intf,capability,platform,remote_port"]
    for line in raw.splitlines():
        m = _CDP_LINE.match(line.strip())
        if m:
            rows.append(f"{m.group(1)},{m.group(2)},{m.group(3).strip()},{m.group(4)},{m.group(5)}")
    if len(rows) < 2:
        return raw
    return "\n".join(rows)


# ---- show vlan brief -----------------------------------------------------

_VLAN_LINE = re.compile(
    r"^(\d+)\s+"         # VLAN ID
    r"(\S+)\s+"          # name
    r"(active|act/unsup|sus)\s*"  # status
    r"(.*)?$",           # ports
)


@_register(r"show\s+vlan\s+brief")
def _compress_vlan_brief(raw: str) -> str:
    rows: list[str] = ["vlan,name,status,ports"]
    for line in raw.splitlines():
        m = _VLAN_LINE.match(line.strip())
        if m:
            ports = m.group(4).strip() if m.group(4) else ""
            rows.append(f"{m.group(1)},{m.group(2)},{m.group(3)},{ports}")
    if len(rows) < 2:
        return raw
    return "\n".join(rows)


# ---- show access-lists ---------------------------------------------------

@_register(r"show\s+(?:ip\s+)?access-lists?")
def _compress_acl(raw: str) -> str:
    lines = raw.splitlines()
    out: list[str] = []
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
# NX-OS / Nexus command families
# ---------------------------------------------------------------------------
# The fleet these agents drive is predominantly Cisco NX-OS, whose table and
# detail formats differ from IOS. The compressors below target the NX-OS
# ``show`` output shapes seen most often in agent gather loops.

# Interface names across IOS / NX-OS / Catalyst — used to tell a data row from
# a header, legend or continuation line in a fixed-width table.
_IFACE_NAME_RE = re.compile(
    r"^(?:mgmt|eth(?:ernet)?|po(?:rt-channel)?|vlan|lo(?:opback)?|nve|"
    r"tun(?:nel)?|gi\w*|te\w*|twe\w*|fo\w*|hu\w*|fa\w*)\d",
    re.IGNORECASE,
)


def _csv_row(fields: list[str]) -> str:
    """Join *fields* as one CSV row, quoting only when a field carries a comma
    or quote (device ``Name`` columns hold spaces but rarely commas)."""
    out = []
    for f in fields:
        if ("," in f) or ('"' in f):
            f = '"' + f.replace('"', '""') + '"'
        out.append(f)
    return ",".join(out)


def _fixed_width_rows(raw: str, keywords: list[str]) -> Optional[list[list[str]]]:
    """Parse a fixed-width table whose columns start at the ``keywords`` header.

    NX-OS status/brief tables pad columns and let a ``Name`` / ``Reason`` field
    carry spaces, so a plain whitespace split corrupts them. Instead we find the
    header line, record each column's start offset, and slice every data row at
    those offsets. Header, dashed-separator and wrapped-continuation lines are
    skipped; only lines whose first column is an interface name are kept.
    Returns ``None`` when the header is absent (caller falls back to raw).
    """
    lines = raw.splitlines()
    positions: Optional[list[int]] = None
    start = 0
    for i, line in enumerate(lines):
        if not all(kw in line for kw in keywords):
            continue
        pos: list[int] = []
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
            positions = pos
            start = i + 1
            break
    if not positions:
        return None
    bounds = positions + [10 ** 6]
    rows: list[list[str]] = []
    for line in lines[start:]:
        if not line.strip() or set(line.strip()) <= {"-"}:
            continue
        head = line[bounds[0]:bounds[1]].split()
        if not head or not _IFACE_NAME_RE.match(head[0]):
            continue
        rows.append([line[bounds[k]:bounds[k + 1]].strip() for k in range(len(positions))])
    return rows


# ---- show interface status (NX-OS / Catalyst) ----------------------------

@_register(r"^show\s+int(?:erface|erfaces)?(?:\s+\S+)?\s+status\s*$")
def _compress_intf_status(raw: str) -> str:
    """``show interface status`` → CSV, dropping the repeated 80-char dashed
    separators and the per-block ``Port Name Status ...`` headers."""
    rows = _fixed_width_rows(
        raw, ["Port", "Name", "Status", "Vlan", "Duplex", "Speed", "Type"]
    )
    if not rows:
        return raw
    out = ["port,name,status,vlan,duplex,speed,type"]
    out.extend(_csv_row(r) for r in rows)
    return "\n".join(out)


# ---- show interface brief (NX-OS) ----------------------------------------

@_register(r"^show\s+int(?:erface|erfaces)?(?:\s+\S+)?\s+brief\s*$")
def _compress_intf_brief_nxos(raw: str) -> str:
    """``show interface brief`` (NX-OS) → CSV. The two-line wrapped header
    ('Ethernet Interface' / 'Port Ch #') and dashed separators are dropped."""
    rows = _fixed_width_rows(
        raw, ["Ethernet", "VLAN", "Type", "Mode", "Status", "Reason", "Speed", "Port"]
    )
    if not rows:
        return raw
    out = ["interface,vlan,type,mode,status,reason,speed,port_ch"]
    out.extend(_csv_row(r) for r in rows)
    return "\n".join(out)


# ---- show interface counters errors (NX-OS) ------------------------------

_COUNTER_VAL_RE = re.compile(r"^(?:\d+|--)$")


@_register(r"show\s+int(?:erface|erfaces)?\s+counters?\s+err")
def _compress_intf_counter_errors(raw: str) -> str:
    """``show interface counters errors`` (NX-OS) → only ports with a non-zero
    counter, per sub-table.

    NX-OS prints several wide tables (one row per port, often 250+ lines) that
    are almost entirely zeros. Keeping just each sub-table's header plus its
    non-zero rows is the difference between a truncated, partly-lost table and
    a complete, tiny one.
    """
    out: list[str] = []
    cols: Optional[list[str]] = None
    table_rows: list[str] = []
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


# ---- show ip eigrp neighbors ---------------------------------------------

_EIGRP_ROW = re.compile(
    r"^(\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)"
)


@_register(r"show\s+ip\s+eigrp\s+neigh")
def _compress_eigrp_neighbors(raw: str) -> str:
    """``show ip eigrp neighbors`` → CSV, dropping the two-line wrapped column
    header while keeping the process/VRF context line."""
    context = None
    rows = ["h,address,interface,hold,uptime,srtt,rto,q,seq"]
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("IP-EIGRP neighbors") or s.startswith("EIGRP-IPv4"):
            context = s
            continue
        m = _EIGRP_ROW.match(s)
        if m:
            rows.append(",".join(m.groups()))
    if len(rows) < 2:
        return raw
    body = "\n".join(rows)
    return f"{context}\n{body}" if context else body


# ---- show port-channel summary (NX-OS) -----------------------------------

@_register(r"show\s+(?:ether(?:channel)?|port-channel)\s+sum")
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
