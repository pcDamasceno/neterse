"""Code compressors whose format spans Cisco platforms (IOS/IOS-XE
and NX-OS alike): interface detail blocks, running-config, ACLs,
inventory, syslog.

Split from the original single-module ``_compressors.py``
(decision 42) — function bodies are verbatim and remain pinned
by the parity suite and the fixture goldens. Only the standard
library may be imported. Registration order lives in
``registry.py``; nothing self-registers here.
"""

from __future__ import annotations

import re
from typing import Optional
from .helpers import _csv_row


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
