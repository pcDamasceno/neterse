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
        # Rewritten after live-lab verification (decision 20): the legacy
        # regex silently dropped every two-token protocol code (O IA,
        # O E2, D EX, ...) and rendered `is`/route-age tokens into the
        # next-hop and interface columns.
        "row": r"""
    ^([A-Za-z*+%&][A-Za-z0-9*]{0,4}                # protocol code (C, L, S*, O, i, O*E2, ...)
    (?:\s(?:IA|EX|E[12]|N[12]|L[12]|su|ia))?)      # two-token codes: O IA, O E2, D EX, i L1, ...
    \s+
    (\d+\.\d+\.\d+\.\d+(?:/\d+)?)                  # prefix (mask may live on the group header)
    (?:\s+\[(\d+/\d+)\])?                           # [admin/metric]
    (?:\s+via\s+(\d+\.\d+\.\d+\.\d+))?             # next-hop IP, comma excluded
    (?:,\s*\d[\w:.]*)*                              # route age — dropped, declared
    (?:\s+is\s+directly\s+connected)?               # connected-route phrasing
    (?:,\s*(\S+))?                                  # egress interface
    \s*$
    """,
        "row_flags": re.VERBOSE,
        "header": "proto,prefix,ad/metric,next_hop,interface",
        "dropped_fields": ("route_age", "ecmp_alternate_paths",
                           "subnet_group_headers"),
        "doc": "show ip route (IOS/IOS-XE) -> CSV; drops the Codes legend, "
               "subnet-grouping headers, route-age fields and ECMP "
               "continuation lines (all declared).",
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
            # `administratively down` is one status value; without the
            # optional prefix it split across the status AND protocol
            # columns, and the real protocol column was never read
            # (found in live-lab verification, decision 21).
            r"((?:administratively )?\S+)\s+"       # status
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
        # Decision 24: the first number after the neighbor IP is the V
        # column (BGP version, constant 4), NOT the AS — the legacy regex
        # captured it as "as", hiding which neighbors are eBGP.
        "row": (
            r"^(\d+\.\d+\.\d+\.\d+)\s+"  # neighbor
            r"\d+\s+"                      # V (BGP version) — dropped, declared
            r"(\d+)\s+"                    # AS
            r".*?\s+"                      # skip msg fields
            r"(\S+)\s*$"                   # state/pfxrcd
        ),
        "header": "neighbor,as,state_pfxrcd",
        "dropped_fields": (
            "version", "msgrcvd", "msgsent", "tblver", "inq", "outq", "up_down",
        ),
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
        # Data rows start at column 0 on every platform this entry knows;
        # without this guard the stripped IOS *continuation* line of a
        # wrapped device ID ("<spaces>Eth 0/0  165  R ...") false-matches
        # the row regex and yields a corrupt row that can WIN smallest-
        # wins over the faithful fixed-width entry (decision 25).
        "unindented_rows_only": True,
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
    # -----------------------------------------------------------------------
    # Phase-3 multi-vendor expansion. Fixtures live per-file under
    # tests/fixtures/<platform>/<family>/. These entries register AFTER the
    # legacy families (registry.py), so equal-length ties keep resolving to
    # the baseline — and the parity cross-matrix polices that none of them
    # ever claims a legacy (command, body) pair with a different result.
    # -----------------------------------------------------------------------
    {
        "id": "arista_eos/show_interfaces_status",
        "command": r"^show\s+int(?:erface|erfaces)?(?:\s+\S+)?\s+status\s*$",
        "platforms": r"eos|arista",
        "strategy": "fixed_width_table",
        "keywords": ["Port", "Name", "Status", "Vlan", "Duplex", "Speed", "Type"],
        "header": "port,name,status,vlan,duplex,speed,type",
        # EOS ports: Et1, Et3/1, Po10, Ma1, Vlan10, Lo0, Tu0 (also matches
        # Cisco Eth1/1 — identical output to the Cisco entry there, and the
        # earlier entry wins the tie).
        "row_match": r"^(?:et|po|ma|vl|lo|tu)\w*\d",
        "dropped_fields": (),
        "profiles": {"updown": {"keep": ["port", "status"]}},
        "doc": "show interfaces status (Arista EOS) -> CSV.",
    },
    {
        "id": "arista_eos/show_ip_arp",
        "command": r"show\s+ip\s+arp",
        "platforms": r"eos|arista",
        "strategy": "line_regex_table",
        "row": (
            r"^(\d+\.\d+\.\d+\.\d+)\s+"                              # address
            r"([\d:]+)\s+"                                             # age
            r"([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4})\s+"  # MAC
            r"(.+)$"                                                   # interface(s)
        ),
        "header": "address,age,mac,interface",
        "strip_columns": [4],
        "dropped_fields": (),
    },
    {
        "id": "arista_eos/show_vlan",
        # bare `show vlan` — the Cisco family spells it `show vlan brief`
        "command": r"^show\s+vlan\s*$",
        "platforms": r"eos|arista",
        "strategy": "line_regex_table",
        "row": (
            r"^(\d+)\s+"                   # VLAN ID
            r"(\S+)\s+"                    # name
            r"(active|act/unsup|sus\S*)\s*"  # status
            r"(.*)?$"                      # ports
        ),
        "header": "vlan,name,status,ports",
        "strip_columns": [4],
        "dropped_fields": (),
    },
    {
        "id": "juniper_junos/show_interfaces_terse",
        "command": r"^show\s+int(?:erfaces?)?\s+terse(?:\s+\S+)?\s*$",
        "platforms": r"junos|juniper",
        "strategy": "line_regex_table",
        "row": (
            r"^(\S+)\s+"           # interface / unit
            r"(up|down)\s+"        # admin
            r"(up|down)"           # link
            r"(?:\s+(\S+))?"       # proto (inet, inet6, eth-switch, ...)
            r"(?:\s+(.+))?$"       # local [+ remote]
        ),
        "header": "interface,admin,link,proto,address",
        "strip_columns": [5],
        "dropped_fields": (),
        "profiles": {"updown": {"keep": ["interface", "admin", "link"]}},
        "doc": "show interfaces terse (Junos) -> CSV; local+remote merge "
               "into the address column.",
    },
    {
        "id": "juniper_junos/show_ospf_neighbor",
        # `show ospf neighbor` — the Cisco family requires `show ip ospf`
        "command": r"^show\s+ospf\s+neigh(?:bor)?\s*$",
        "platforms": r"junos|juniper",
        "strategy": "line_regex_table",
        "row": (
            r"^(\d+\.\d+\.\d+\.\d+)\s+"  # address
            r"(\S+)\s+"                    # interface
            r"(\S+)\s+"                    # state
            r"(\d+\.\d+\.\d+\.\d+)\s+"   # neighbor ID
            r"(\d+)\s+"                    # priority
            r"(\d+)$"                      # dead
        ),
        "header": "address,interface,state,neighbor_id,priority,dead",
        "dropped_fields": (),
    },
    {
        "id": "aruba_aoscx/show_interface_brief",
        # bare `show interface brief` — NX-OS spells per-interface variants
        # and its table has an `Ethernet` keyword header, so the two
        # fixed-width specs can never both parse the same body.
        "command": r"^show\s+int(?:erface|erfaces)?\s+brief\s*$",
        "platforms": r"aruba|aoscx|aos_cx|procurve",
        "strategy": "fixed_width_table",
        "keywords": ["Port", "Native", "Mode", "Type", "Enabled", "Status",
                     "Reason", "Speed", "Description"],
        "header": "port,native_vlan,mode,type,enabled,status,reason,speed,description",
        "row_match": r"^\d+/\d+/\d+",     # AOS-CX member/slot/port names
        "dropped_fields": (),
        "profiles": {"updown": {"keep": ["port", "status", "reason"]}},
        "doc": "show interface brief (Aruba AOS-CX) -> CSV; wrapped header "
               "and separators dropped.",
    },
    {
        "id": "aruba_aoscx/show_vlan",
        "command": r"^show\s+vlan\s*$",
        "platforms": r"aruba|aoscx|aos_cx|procurve",
        "strategy": "line_regex_table",
        # AOS-CX status is up/down (the Arista/Cisco family says `active`),
        # which keeps the two bare-`show vlan` specs from cross-parsing.
        "row": (
            r"^(\d+)\s+"       # VLAN ID
            r"(\S+)\s+"        # name
            r"(up|down)\s+"    # status
            r"(\S+)\s+"        # reason
            r"(\S+)\s*"        # type
            r"(.*)?$"          # interfaces
        ),
        "header": "vlan,name,status,reason,type,interfaces",
        "strip_columns": [6],
        "dropped_fields": (),
    },
    {
        "id": "mikrotik_routeros/ip_address_print",
        "command": r"^/ip\s+address\s+print",
        "platforms": r"mikrotik|routeros",
        "strategy": "line_regex_table",
        "row": (
            r"^(\d+)\s+"                       # item number
            r"(?:([A-Z]{1,3})\s+)?"            # flags (D, X, I, ...)
            r"(\d+\.\d+\.\d+\.\d+/\d+)\s+"   # address
            r"(\d+\.\d+\.\d+\.\d+)\s+"       # network
            r"(\S+)$"                          # interface
        ),
        "header": "num,flags,address,network,interface",
        "dropped_fields": (),
        "doc": "/ip address print (MikroTik RouterOS) -> CSV; the Flags "
               "legend line is dropped.",
    },
    {
        "id": "mikrotik_routeros/interface_print",
        "command": r"^/interface\s+print",
        "platforms": r"mikrotik|routeros",
        "strategy": "line_regex_table",
        "row": (
            r"^(\d+)\s+"             # item number
            r"(?:([A-Z]{1,3})\s+)?"  # flags (R running, D dynamic, X disabled)
            r"(\S+)\s+"              # name
            r"(\S+)\s+"              # type
            r"(\d+)"                 # actual-mtu
            r"(?:\s+(\d+))?$"        # l2mtu
        ),
        "header": "num,flags,name,type,mtu,l2mtu",
        "dropped_fields": (),
    },
    {
        # IOS/IOS-XE `show cdp neighbors` is a fixed-width table whose
        # values carry spaces (`Eth 0/0`, `Linux Uni`) — the legacy
        # line-regex entry (cisco/show_cdp_lldp_neighbors, NX-OS-shaped
        # single-token rows) fails open on it, which is exactly how the
        # bgp_fundamentals lab surfaced this gap (decision 25). Keyed on
        # the IOS header spelling `Holdtme` (NX-OS prints `Hldtme`), so
        # the two entries never compete on the same body. Long device IDs
        # wrap onto their own line; `first_col_wraps` re-joins them.
        "id": "cisco_ios/show_cdp_neighbors",
        "command": r"show\s+cdp\s+neigh(?:bors?)?\s*$",
        "platforms": r"ios|xe",
        "strategy": "fixed_width_table",
        "keywords": ["Device ID", "Local Intrfce", "Holdtme",
                     "Capability", "Platform", "Port ID"],
        "row_match": r"^\S+$",
        "first_col_wraps": True,
        "header": "device,local_intf,holdtime,capability,platform,remote_port",
        "dropped_fields": ("entry_count",),
        "doc": "show cdp neighbors (IOS fixed-width) -> CSV; capability "
               "legend and the derivable 'Total cdp entries' line are "
               "dropped, holdtime is kept (the legacy entry drops it).",
    },
]
