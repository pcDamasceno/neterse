"""Shared fixture corpus for the showbrief test + parity suites.

One realistic raw-output sample per compressor family (all 15 Phase-0
compressors are represented), plus edge inputs and a cross-matrix helper.
The parity suite replays every (command, body) combination through the
frozen legacy snapshot and the package, so these strings double as the
Phase-1 golden baseline inputs — extend freely, never trim.

Fixed-width tables are built with ``.ljust`` so column offsets stay exact
regardless of hand-authored spacing (same convention as the historical
test file).
"""
from __future__ import annotations

DASHES = "-" * 80


def _status_header() -> str:
    return (
        "Port".ljust(14) + "Name".ljust(19) + "Status".ljust(10)
        + "Vlan".ljust(10) + "Duplex".ljust(8) + "Speed".ljust(8) + "Type"
    )


def _status_row(port, name, status, vlan, duplex, speed, typ) -> str:
    return (
        port.ljust(14) + name.ljust(19) + status.ljust(10)
        + vlan.ljust(10) + duplex.ljust(8) + speed.ljust(8) + typ
    )


def _brief_header() -> str:
    return (
        "Ethernet".ljust(16) + "VLAN".ljust(8) + "Type".ljust(5) + "Mode".ljust(7)
        + "Status".ljust(8) + "Reason".ljust(23) + "Speed".ljust(10) + "Port"
    )


def _brief_row(intf, vlan, typ, mode, status, reason, speed, portch) -> str:
    return (
        intf.ljust(16) + vlan.ljust(8) + typ.ljust(5) + mode.ljust(7)
        + status.ljust(8) + reason.ljust(23) + speed.ljust(10) + portch
    )


COUNTERS_ERRORS = "\n".join([
    DASHES,
    "Port          Align-Err    FCS-Err   Xmit-Err    Rcv-Err  UnderSize OutDiscards",
    DASHES,
    "mgmt0                   0          0         --         --         --          --",
    "Eth1/1                  0          0          0          0          0           0",
    "Eth1/37                 0          6          0          6          0           0",
    "Eth1/39                 0       2064          0       2064          0           0",
    "",
    DASHES,
    "Port          Single-Col  Multi-Col   Late-Col  Exces-Col  Carri-Sen       Runts",
    DASHES,
    "mgmt0                   0          0          0          0         --          --",
    "Eth1/1                  0          0          0          0          0           0",
])

STATUS = "\n".join([
    DASHES,
    _status_header(),
    DASHES,
    _status_row("Eth1/11", "RSRFF206 Twe1/0/3", "connected", "routed", "full", "10G", "10Gbase-SR"),
    _status_row("Eth1/45", "RFRA3213-Eth1/48", "connected", "routed", "full", "10G", "10Gbase-LR"),
    "",
    DASHES,
    _status_header(),
    DASHES,
    _status_row("Po101", "MFS4163-Po101", "connected", "trunk", "full", "10G", "--"),
])

BRIEF = "\n".join([
    DASHES,
    _brief_header(),
    "Interface".ljust(16) + " " * 60 + "Ch #",  # wrapped continuation line
    DASHES,
    _brief_row("Eth1/9", "1", "eth", "access", "down", "Administratively down", "auto(D)", "--"),
    _brief_row("Eth1/11", "1", "eth", "routed", "up", "none", "10G(D)", "--"),
])

NXOS_INTF_DETAIL = """Ethernet1/45 is up
admin state is up, Dedicated Interface
  Hardware: 100/1000/10000/40000 Ethernet, address: 4874.1016.a8c1 (bia 4874.1016.a8b4)
  Description: RFRA3213-Eth1/48
  Internet Address is 192.168.110.9/31
  MTU 1500 bytes, BW 10000000 Kbit , DLY 10 usec
  reliability 255/255, txload 1/255, rxload 1/255
  Encapsulation ARPA, medium is broadcast
  full-duplex, 10 Gb/s, media type is 10G
  Beacon is turned off
  Auto-Negotiation is turned on  FEC mode is Auto
  Last link flapped 11week(s) 6day(s)
  Last clearing of "show interface" counters never
  1 interface resets
    30 seconds input rate 827664 bits/sec, 710 packets/sec
    30 seconds output rate 572280 bits/sec, 522 packets/sec
  RX
    2281689921 unicast packets  2276105 multicast packets  3 broadcast packets
    0 runts  0 giants  48 CRC  0 no buff
    0 input error  0 short frame  0 overrun   0 underrun  0 ignored
  TX
    0 output error  0 collision  0 deferred  0 late collision
"""

NXOS_INTF_DOWN = """Ethernet1/9 is down (Administratively down)
admin state is down, Dedicated Interface
  Hardware: 100/1000/10000/40000 Ethernet, address: 4874.1016.a890 (bia 4874.1016.a890)
  Description: FREE
  MTU 1500 bytes, BW 40000000 Kbit , DLY 10 usec
  Port mode is access
  auto-duplex, auto-speed, media type is 10G
"""

IOS_INTF_DETAIL = (
    "GigabitEthernet0/1 is up, line protocol is up\n"
    "  Description: uplink\n"
    "  MTU 1500 bytes, BW 1000000 Kbit\n"
    "  Full-duplex, 1000Mb/s\n"
    "  5 minute input rate 1000 bits/sec\n"
    "  10 input errors, 2 CRC\n"
)

EIGRP = """IP-EIGRP neighbors for process 190 VRF default
H   Address                 Interface       Hold  Uptime  SRTT   RTO  Q  Seq
                                            (sec)         (ms)       Cnt Num
5   192.168.13.85           Eth1/38         11   11w6d     1    50    0   549000
12  192.168.110.0           Eth1/47         12   11w6d     1    50    0   22666
11  192.168.110.4           Eth1/46         10   11w6d     1    50    0   21533
"""

PORTCHANNEL = """Flags:  D - Down        P - Up in port-channel (members)
        I - Individual  H - Hot-standby (LACP only)
        s - Suspended   r - Module-removed
        b - BFD Session Wait
        S - Switched    R - Routed
        U - Up (port-channel)
        M - Not in use. Min-links not met
--------------------------------------------------------------------------------
Group Port-       Type     Protocol  Member Ports
      Channel
--------------------------------------------------------------------------------
101   Po101(SU)   Eth      LACP      Eth1/42(P)   Eth1/43(P)
"""

IP_ROUTE = (
    "Codes: C - connected, S - static, O - OSPF\n"
    "O    10.1.1.0/24 [110/20] via 10.0.0.1, GigabitEthernet0/1\n"
    "O    10.1.2.0/24 [110/30] via 10.0.0.1, GigabitEthernet0/1\n"
    "C    10.0.0.0/24 is directly connected, GigabitEthernet0/0\n"
    "S*   0.0.0.0/0 [1/0] via 192.168.1.1\n"
)

IP_INT_BRIEF = (
    "Interface              IP-Address      OK? Method Status                Protocol\n"
    "GigabitEthernet0/1     10.0.0.1        YES NVRAM  up                    up\n"
    "GigabitEthernet0/2     unassigned      YES unset  down                  down\n"
    "Loopback0              192.168.255.1   YES NVRAM  up                    up\n"
)

SHOW_VERSION = (
    "Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 15.2(4)E10, "
    "RELEASE SOFTWARE (fc2)\n"
    "Technical Support: http://www.cisco.com/techsupport\n"
    "Copyright (c) 1986-2020 by Cisco Systems, Inc.\n"
    "\n"
    "sw-access-01 uptime is 5 weeks, 3 days, 2 hours\n"
    "System returned to ROM by power-on\n"
    'System image file is "flash:c2960-lanbasek9-mz.152-4.E10.bin"\n'
    "\n"
    "512K bytes of physical memory.\n"
    "Processor board ID FOC1234X0Y1\n"
    "Model number                    : WS-C2960-24TT-L\n"
)

BGP_SUMMARY = (
    "BGP router identifier 10.255.0.1, local AS number 65001\n"
    "Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd\n"
    "10.0.0.1        4        65001    1000    1200      150    0    0 4d12h          25\n"
    "10.0.0.5        4        65002     900     950      150    0    0 2d01h          Idle\n"
)

OSPF_NEIGHBOR = (
    "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
    "1.1.1.1           1   FULL/DR         00:00:35    10.0.0.1        GigabitEthernet0/1\n"
    "2.2.2.2           1   FULL/BDR        00:00:33    10.0.0.5        GigabitEthernet0/2\n"
)

CDP_NEIGHBORS = (
    "Capability Codes: R - Router, S - Switch, I - IGMP\n"
    "Device ID       Local Intrfce   Hldtme   Capability   Platform      Port ID\n"
    "SW2             Eth1/1          155      S I          N9K-C93180    Eth1/2\n"
    "RTR1            Eth1/48         120      R            ISR4451       Gi0/0/0\n"
)

VLAN_BRIEF = (
    "VLAN Name                             Status    Ports\n"
    "---- -------------------------------- --------- -------------------------------\n"
    "1    default                          active    Gi0/3, Gi0/4\n"
    "10   USERS                            active    Gi0/5\n"
    "99   MGMT                             active    \n"
)

ACL = (
    "Extended IP access list INBOUND-EDGE\n"
    "    10 permit tcp any any eq 22 (123 matches)\n"
    "    20 permit udp any any eq 161 (8 matches)\n"
    "    30 deny ip any any (54211 matches)\n"
)

RUNNING_CONFIG = (
    "Building configuration...\n"
    "\n"
    "Current configuration : 1234 bytes\n"
    "!\n"
    "hostname R1\n"
    "!\n"
    "banner motd ^C\n"
    "Unauthorized access prohibited\n"
    "^C\n"
    "!\n"
    "interface GigabitEthernet0/1\n"
    " description uplink\n"
    " ip address 10.0.0.1 255.255.255.0\n"
    "!\n"
    "end\n"
)

# (label, command, body) — every Phase-0 compressor family exercised with
# the command spelling(s) agents actually issue.
COMMAND_FIXTURES: list[tuple[str, str, str]] = [
    ("counters-errors", "show interface counters errors", COUNTERS_ERRORS),
    ("intf-status", "show interface status", STATUS),
    ("intf-status-single", "show interface ethernet1/11 status", STATUS),
    ("intf-brief-nxos", "show interface ethernet1/9 brief", BRIEF),
    ("intf-detail-nxos", "show interface ethernet1/45", NXOS_INTF_DETAIL),
    ("intf-detail-down", "show interface ethernet1/9", NXOS_INTF_DOWN),
    ("intf-detail-ios", "show interfaces GigabitEthernet0/1", IOS_INTF_DETAIL),
    ("eigrp", "show ip eigrp neighbors", EIGRP),
    ("eigrp-vrf", "show ip eigrp neighbors vrf all", EIGRP),
    ("portchannel", "show port-channel summary", PORTCHANNEL),
    ("etherchannel", "show etherchannel summary", PORTCHANNEL),
    ("ip-route", "show ip route", IP_ROUTE),
    ("ip-route-vrf", "show ip route vrf CUSTOMER", IP_ROUTE),
    ("ip-int-brief", "show ip interface brief", IP_INT_BRIEF),
    ("ip-int-brief-abbrev", "show ip int brief", IP_INT_BRIEF),
    ("version", "show version", SHOW_VERSION),
    ("bgp-summary", "show ip bgp summary", BGP_SUMMARY),
    ("bgp-summary-bare", "show bgp summary", BGP_SUMMARY),
    ("ospf-neighbor", "show ip ospf neighbor", OSPF_NEIGHBOR),
    ("cdp", "show cdp neighbors", CDP_NEIGHBORS),
    ("lldp", "show lldp neighbors", CDP_NEIGHBORS),
    ("vlan-brief", "show vlan brief", VLAN_BRIEF),
    ("acl", "show ip access-lists", ACL),
    ("running-config", "show running-config", RUNNING_CONFIG),
    ("run-abbrev", "show run", RUNNING_CONFIG),
]

# Inputs that must always fail open (and must never raise anywhere).
EDGE_INPUTS: list[str] = [
    "",
    " ",
    "\n\n\n",
    "x",
    "0",
    "-" * 500,
    "no structure here at all",
    "héllo wörld ⚡ ↑↓ 你好",
    "\x1b[31mANSI colored line\x1b[0m\n\x1b[1mbold\x1b[0m",
    "line one\r\nline two\r\n",
    ("Port Name Status\n" + "x" * 79 + "\n") * 50,
]

ALL_COMMANDS: list[str] = sorted({cmd for _, cmd, _ in COMMAND_FIXTURES}) + [
    "show something weird",
    "show tech-support",
]

ALL_BODIES: list[str] = [body for _, _, body in COMMAND_FIXTURES] + EDGE_INPUTS
