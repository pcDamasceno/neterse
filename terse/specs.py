"""Declarative specs — the data-driven tier of the registry.

Each spec is a plain dict the engine compiles into a compressor
(``engine.build``). Contributing a new table-shaped command family is one
spec here plus fixtures in ``tests/corpus.py`` — no parser code. Genuinely
stateful formats (multi-line blocks, banner state machines) stay as code
in ``_compressors.py``; the escape hatch is deliberate.

Field notes:

``platforms``
    Case-insensitive regex matched against the caller-supplied platform
    string (``render(..., platform=...)``). No platform given, or no
    ``platforms`` key → the spec is always tried (fail-open: filtering
    only ever *skips* work, it never forces a match). Declare broadly —
    the filter exists to kill cross-family false matches, not to gatekeep.

``dropped_fields``
    The lossiness manifest: names of DATA-bearing fields this rendering
    omits, surfaced verbatim on ``Candidate.dropped_fields`` so consumers
    can disclose omissions to the model. Pure noise — separators, static
    legends, repeated headers — is dropped freely and never declared.
    ``()`` means "declared lossless"; ``None`` (absent) means
    "undeclared" (legacy code compressors only).

``profiles``
    Named, opt-in, *declared-lossy* column projections (Phase 2):
    ``{"updown": {"keep": ["port", "status"]}}``. Requested via
    ``render(..., profile="updown")``; the variant emits only the kept
    columns and appends an inline omission marker naming what was
    withheld. The omitted column names join the entry's manifest on the
    resulting candidates. Entries that don't declare a requested profile
    render their complete default — a profile can narrow output only
    where a spec explicitly said how.

The row regexes below are byte-for-byte the historical hand-written ones;
the parity suite holds spec output identical to the frozen baseline.
"""

from __future__ import annotations

import re

SPECS: list = [
    {
        "id": "cisco/show_ip_route",
        "command": r"show\s+ip\s+route",
        "platforms": r"ios|xe|xr|nx",
        "strategy": "line_regex_table",
        "row": r"""
    ^[\s*>]*                          # selection markers
    ([A-Z*]\S*)\s+                    # protocol code (O, B, S, C, O IA, …)
    (\d+\.\d+\.\d+\.\d+/?\d*)\s+     # prefix
    (?:\[(\d+/\d+)\])?\s*             # admin/metric  [110/20]
    (?:via\s+(\S+))?                  # next-hop
    [,\s]*(?:(\S+))?                  # egress interface
    """,
        "row_flags": re.VERBOSE,
        "header": "proto,prefix,ad/metric,next_hop,interface",
        "dropped_fields": (),
    },
    {
        "id": "cisco_ios/show_ip_interface_brief",
        "command": r"show\s+ip\s+int(?:erface)?\s+brief",
        "platforms": r"ios|xe|xr|nx",
        "strategy": "line_regex_table",
        "row": (
            r"^(\S+)\s+"                            # interface
            r"(\d+\.\d+\.\d+\.\d+|unassigned)\s+"  # IP
            r"(YES|NO)\s+"                          # OK?
            r"(\S+)\s+"                             # method
            r"(\S+)\s+"                             # status
            r"(\S+)"                                # protocol
        ),
        "header": "interface,ip,status,protocol",
        "columns": [1, 2, 5, 6],
        "dropped_fields": ("ok", "method"),
        "profiles": {"updown": {"keep": ["interface", "status", "protocol"]}},
    },
    {
        "id": "cisco/show_version",
        "command": r"show\s+version",
        "platforms": r"ios|xe|xr|nx",
        "strategy": "kv_extract",
        # Field order is the scan order per line; OUTPUT order is the order
        # fields first match top-to-bottom (byte-parity with the historical
        # hand-written compressor). Patterns are byte-for-byte the legacy ones.
        "fields": [
            {
                "key": "os",
                "pattern": r"Cisco\s+(IOS|NX-OS|IOS-XE|IOS XR)\s+Software.*Version\s+(\S+)",
                "flags": re.IGNORECASE,
                "template": "{1} {2}",
            },
            {
                "key": "uptime",
                "pattern": r"uptime is\s+(.+)",
                "flags": re.IGNORECASE,
                "strip": True,
            },
            {
                "key": "memory",
                "pattern": r"(\d+[KMG])\s+bytes of (?:physical\s+)?memory",
                "flags": re.IGNORECASE,
            },
            {"key": "serial", "pattern": r"[Pp]rocessor\s+board\s+ID\s+(\S+)"},
            {"key": "model", "pattern": r"[Mm]odel\s+number\s*:\s*(\S+)"},
            {"key": "image", "pattern": r"[Ss]ystem\s+image\s+file\s+is\s+\"([^\"]+)\""},
        ],
        "dropped_fields": ("unmatched_lines",),
        "doc": "show version -> one key=value line (os, uptime, memory, "
               "serial, model, image); everything unmatched is dropped.",
    },
    {
        "id": "cisco/show_ip_bgp_summary",
        "command": r"show\s+(?:ip\s+)?bgp\s+summary",
        "platforms": r"ios|xe|xr|nx",
        "strategy": "line_regex_table",
        "row": (
            r"^(\d+\.\d+\.\d+\.\d+)\s+"  # neighbor
            r"(\d+)\s+"                    # AS
            r".*?\s+"                      # skip msg fields
            r"(\S+)\s*$"                   # state/pfxrcd
        ),
        "header": "neighbor,as,state_pfxrcd",
        "dropped_fields": ("msgrcvd", "msgsent", "tblver", "inq", "outq", "up_down"),
    },
    {
        "id": "cisco/show_ip_ospf_neighbor",
        "command": r"show\s+ip\s+ospf\s+neigh",
        "platforms": r"ios|xe|xr|nx",
        "strategy": "line_regex_table",
        "row": (
            r"^(\d+\.\d+\.\d+\.\d+)\s+"  # neighbor ID
            r"(\d+)\s+"                    # priority
            r"(\S+)\s+"                    # state
            r"(\S+)\s+"                    # dead time
            r"(\d+\.\d+\.\d+\.\d+)\s+"   # address
            r"(\S+)"                       # interface
        ),
        "header": "neighbor_id,priority,state,dead_time,address,interface",
        "dropped_fields": (),
    },
    {
        "id": "cisco/show_cdp_lldp_neighbors",
        "command": r"show\s+(?:cdp|lldp)\s+neigh",
        "platforms": r"ios|xe|xr|nx",
        "strategy": "line_regex_table",
        "row": (
            r"^(\S+)\s+"       # device ID
            r"(\S+)\s+"        # local intf
            r"\d+\s+"          # holdtime
            r"(\S.*\S)\s+"     # capability
            r"(\S+)\s+"        # platform
            r"(\S+)\s*$"       # port ID
        ),
        "header": "device,local_intf,capability,platform,remote_port",
        "strip_columns": [3],
        "dropped_fields": ("holdtime",),
    },
    {
        "id": "cisco/show_vlan_brief",
        "command": r"show\s+vlan\s+brief",
        "platforms": r"ios|xe|nx",
        "strategy": "line_regex_table",
        "row": (
            r"^(\d+)\s+"                   # VLAN ID
            r"(\S+)\s+"                    # name
            r"(active|act/unsup|sus)\s*"   # status
            r"(.*)?$"                      # ports
        ),
        "header": "vlan,name,status,ports",
        "strip_columns": [4],
        "dropped_fields": (),
    },
    {
        "id": "cisco/show_interface_status",
        "command": r"^show\s+int(?:erface|erfaces)?(?:\s+\S+)?\s+status\s*$",
        "platforms": r"ios|xe|nx",
        "strategy": "fixed_width_table",
        "keywords": ["Port", "Name", "Status", "Vlan", "Duplex", "Speed", "Type"],
        "header": "port,name,status,vlan,duplex,speed,type",
        "dropped_fields": (),
        "profiles": {"updown": {"keep": ["port", "status"]}},
        "doc": "show interface status (NX-OS / Catalyst) -> CSV; drops the "
               "repeated dashed separators and per-block column headers.",
    },
    {
        "id": "cisco_nxos/show_interface_brief",
        "command": r"^show\s+int(?:erface|erfaces)?(?:\s+\S+)?\s+brief\s*$",
        "platforms": r"nx",
        "strategy": "fixed_width_table",
        "keywords": ["Ethernet", "VLAN", "Type", "Mode", "Status", "Reason", "Speed", "Port"],
        "header": "interface,vlan,type,mode,status,reason,speed,port_ch",
        "dropped_fields": (),
        "profiles": {"updown": {"keep": ["interface", "status", "reason"]}},
        "doc": "show interface brief (NX-OS) -> CSV; the two-line wrapped "
               "header and dashed separators are dropped.",
    },
    {
        "id": "cisco/show_ip_eigrp_neighbors",
        "command": r"show\s+ip\s+eigrp\s+neigh",
        "platforms": r"ios|xe|nx",
        "strategy": "line_regex_table",
        "row": r"^(\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
        "header": "h,address,interface,hold,uptime,srtt,rto,q,seq",
        "context_prefixes": ["IP-EIGRP neighbors", "EIGRP-IPv4"],
        "dropped_fields": (),
    },
]
