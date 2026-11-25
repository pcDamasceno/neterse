"""Decision 53: device layouts the synthetic corpus never had.

``tests/corpus.py`` builds every table left-aligned, one table per
output. Real devices right-align some columns, print several tables in one
output, wrap long lists onto indented lines and write one-line banners.
Each sample below is written in that vendor's layout; none is a device
capture, so a real capture should replace it when one is available.
"""
from __future__ import annotations

import pytest

from neterse import compact, render


def _text(raw: str, command: str, platform: str, source: str):
    """The text of *source*'s candidate, or None when it declined."""
    texts = [c.text for c in render(raw, command=command, platform=platform)
             if c.source == source]
    return texts[0] if texts else None


# -- show running-config: banners and lines that start with "end" -----------

def test_running_config_keeps_lines_after_a_one_line_ios_banner():
    raw = (
        "Building configuration...\n\nCurrent configuration : 1200 bytes\n!\n"
        "hostname r1\n!\n"
        "banner login ^CAuthorized access only^C\n!\n"
        "interface GigabitEthernet1\n ip address 10.0.0.1 255.255.255.0\n!\n"
        "endpoint-tracker t1\n endpoint-ip 8.8.8.8\n!\n"
        "line vty 0 4\n transport input ssh\n!\nend\n"
    )
    assert _text(raw, "show running-config", "cisco_ios", "_compress_running_config") == (
        "hostname r1\n"
        "banner login ^CAuthorized access only^C ...\n"
        "interface GigabitEthernet1\n ip address 10.0.0.1 255.255.255.0\n"
        "endpoint-tracker t1\n endpoint-ip 8.8.8.8\n"
        "line vty 0 4\n transport input ssh"
    )


def test_running_config_ends_an_nxos_banner_at_its_own_delimiter():
    raw = (
        "!Command: show running-config\n"
        "version 9.3(8)\nhostname leaf1\n"
        "banner motd #Nexus 9000v is a demo version of the Nexus Operating System\n#\n\n"
        "feature bgp\ninterface Ethernet1/1\n  ip address 10.1.1.1/30\n"
    )
    assert _text(raw, "show running-config", "cisco_nxos", "_compress_running_config") == (
        "version 9.3(8)\nhostname leaf1\n"
        "banner motd #Nexus 9000v is a demo version of the Nexus Operating System ...\n"
        "feature bgp\ninterface Ethernet1/1\n  ip address 10.1.1.1/30"
    )


def test_running_config_ends_an_eos_banner_at_eof():
    raw = (
        "hostname eos1\nbanner login\nAuthorized access only\nEOF\n!\n"
        "interface Ethernet1\n   description uplink\n"
    )
    assert _text(raw, "show running-config", "arista_eos", "_compress_running_config") == (
        "hostname eos1\nbanner login ...\ninterface Ethernet1\n   description uplink"
    )


# -- IOS show interfaces status: right-aligned Duplex/Speed, mGig ports -----

def _ios_status_line(port, name, status, vlan, duplex, speed, typ):
    # IOS right-aligns Duplex and Speed: "a-1000" starts one character
    # left of the "Speed" header.
    return (port.ljust(10) + name.ljust(19) + status.ljust(13) + vlan.ljust(10)
            + duplex.rjust(7) + speed.rjust(7) + " " + typ)


IOS_STATUS = "\n".join([
    _ios_status_line("Port", "Name", "Status", "Vlan", "Duplex", "Speed", "Type"),
    _ios_status_line("Gi1/0/1", "uplink core", "connected", "trunk", "a-full", "a-1000", "10/100/1000BaseTX"),
    _ios_status_line("Gi1/0/2", "", "notconnect", "1", "auto", "auto", "10/100/1000BaseTX"),
    _ios_status_line("Tw1/0/3", "", "connected", "10", "a-full", "a-1000", "100/1000/2.5GBaseTX"),
    _ios_status_line("Fi1/0/4", "", "notconnect", "1", "auto", "auto", "100/1000/2.5G/5GBaseTX"),
    _ios_status_line("Ap1/0/1", "", "connected", "1", "a-full", "a-1000", "App-hosting port"),
    _ios_status_line("Te1/1/1", "", "connected", "trunk", "full", "10G", "SFP-10GBase-SR"),
]) + "\n"


def test_ios_interface_status_keeps_right_aligned_values_and_mgig_ports():
    assert IOS_STATUS.splitlines()[1].endswith("a-full a-1000 10/100/1000BaseTX")
    assert _text(IOS_STATUS, "show interfaces status", "cisco_ios",
                 "spec:cisco/show_interface_status") == (
        "port,name,status,vlan,duplex,speed,type\n"
        "Gi1/0/1,uplink core,connected,trunk,a-full,a-1000,10/100/1000BaseTX\n"
        "Gi1/0/2,,notconnect,1,auto,auto,10/100/1000BaseTX\n"
        "Tw1/0/3,,connected,10,a-full,a-1000,100/1000/2.5GBaseTX\n"
        "Fi1/0/4,,notconnect,1,auto,auto,100/1000/2.5G/5GBaseTX\n"
        "Ap1/0/1,,connected,1,a-full,a-1000,App-hosting port\n"
        "Te1/1/1,,connected,trunk,full,10G,SFP-10GBase-SR"
    )


# -- NX-OS show interface brief: one table per interface type ----------------

DASHES = "-" * 80


def _brief_line(intf, vlan, typ, mode, status, reason, speed, port):
    return (intf.ljust(14) + vlan.ljust(8) + typ.ljust(5) + mode.ljust(7)
            + status.ljust(8) + reason.ljust(25) + speed.ljust(10) + port)


ETHERNET_TABLE = [
    DASHES,
    _brief_line("Ethernet", "VLAN", "Type", "Mode", "Status", "Reason", "Speed", "Port"),
    "Interface".ljust(77) + "Ch #",
    DASHES,
    _brief_line("Eth1/1", "--", "eth", "routed", "up", "none", "10G(D)", "--"),
    _brief_line("Eth1/2", "1", "eth", "access", "down", "XCVR not inserted", "auto(D)", "--"),
]

MGMT_TABLE = [
    DASHES,
    "Port   VRF          Status IP Address                              Speed    MTU",
    DASHES,
    "mgmt0  --           up     172.16.1.10                             1000     1500",
    "",
]

LOOPBACK_TABLE = [
    "",
    DASHES,
    "Interface     Status     Description",
    DASHES,
    "Lo0           up         --",
]


def test_nxos_brief_slices_a_lone_ethernet_table():
    raw = "\n".join(ETHERNET_TABLE) + "\n"
    assert _text(raw, "show interface ethernet1/1-2 brief", "cisco_nxos",
                 "spec:cisco_nxos/show_interface_brief") == (
        "interface,vlan,type,mode,status,reason,speed,port_ch\n"
        "Eth1/1,--,eth,routed,up,none,10G(D),--\n"
        "Eth1/2,1,eth,access,down,XCVR not inserted,auto(D),--"
    )


def test_nxos_brief_with_other_tables_stays_raw():
    below = "\n".join(ETHERNET_TABLE + LOOPBACK_TABLE) + "\n"
    above = "\n".join(MGMT_TABLE + ETHERNET_TABLE) + "\n"
    for raw in (below, above):
        assert _text(raw, "show interface brief", "cisco_nxos",
                     "spec:cisco_nxos/show_interface_brief") is None


def test_nxos_brief_with_other_tables_is_read_by_the_textfsm_extra():
    """The spec declines the full output, but ntc-templates reads every
    table, so ``neterse[textfsm]`` still compacts it with every interface."""
    pytest.importorskip("ntc_templates", reason="needs the `textfsm` extra")
    raw = "\n".join(MGMT_TABLE + ETHERNET_TABLE + LOOPBACK_TABLE) + "\n"
    out = compact(raw, "show interface brief", platform="cisco_nxos")
    assert len(out) < len(raw)
    for name in ("mgmt0", "Eth1/1", "Eth1/2", "Lo0", "XCVR not inserted"):
        assert name in out


# -- port-channel / etherchannel summary ---------------------------------------

NXOS_PORTCHANNEL = """Flags:  D - Down        P - Up in port-channel (members)
        I - Individual  H - Hot-standby (LACP only)
--------------------------------------------------------------------------------
Group Port-       Type     Protocol  Member Ports
      Channel
--------------------------------------------------------------------------------
1     Po1(SU)     Eth      LACP      Eth1/1(P)    Eth1/2(P)    Eth1/3(P)
                                     Eth1/4(P)    Eth1/5(P)
10    Po10(SU)    Eth      LACP      Eth1/49(P)   Eth1/50(P)
"""

IOS_ETHERCHANNEL = """Flags:  D - down        P - bundled in port-channel
        I - stand-alone s - suspended
Number of channel-groups in use: 2
Number of aggregators:           2

Group  Port-channel  Protocol    Ports
------+-------------+-----------+-----------------------------------------------
1      Po1(SU)         LACP      Gi1/0/1(P)  Gi1/0/2(P)  Gi1/0/3(P)
                                 Gi1/0/4(P)
2      Po2(SU)          -        Gi1/0/5(P)
"""


def test_nxos_port_channel_summary_joins_wrapped_members():
    assert _text(NXOS_PORTCHANNEL, "show port-channel summary", "cisco_nxos",
                 "_compress_portchannel_summary") == (
        "group,port_channel,type,protocol,member_ports\n"
        "1,Po1(SU),Eth,LACP,Eth1/1(P) Eth1/2(P) Eth1/3(P) Eth1/4(P) Eth1/5(P)\n"
        "10,Po10(SU),Eth,LACP,Eth1/49(P) Eth1/50(P)"
    )


def test_ios_etherchannel_summary_has_no_type_column():
    assert _text(IOS_ETHERCHANNEL, "show etherchannel summary", "cisco_ios",
                 "_compress_portchannel_summary") == (
        "group,port_channel,type,protocol,member_ports\n"
        "1,Po1(SU),,LACP,Gi1/0/1(P) Gi1/0/2(P) Gi1/0/3(P) Gi1/0/4(P)\n"
        "2,Po2(SU),,-,Gi1/0/5(P)"
    )


def test_port_channel_summary_keeps_an_unknown_indented_line_by_staying_raw():
    raw = NXOS_PORTCHANNEL + "      Note: member list truncated\n"
    assert _text(raw, "show port-channel summary", "cisco_nxos",
                 "_compress_portchannel_summary") is None


# -- show ip bgp summary: state reason and local AS ----------------------------

BGP_SUMMARY = """BGP router identifier 10.0.0.1, local AS number 65001
BGP table version is 5, main routing table version 5

Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.0.0.2        4        65002      10      12        5    0    0 00:05:01        3
10.0.0.3        4        65003       0       0        1    0    0 never    Idle (Admin)
10.0.0.4        4        65004       0       0        1    0    0 00:00:12 Idle (PfxCt)
"""


def test_bgp_summary_keeps_the_state_reason_and_the_local_as():
    assert _text(BGP_SUMMARY, "show ip bgp summary", "cisco_ios",
                 "spec:cisco/show_ip_bgp_summary") == (
        "BGP router identifier 10.0.0.1, local AS number 65001\n"
        "neighbor,as,state_pfxrcd\n"
        "10.0.0.2,65002,3\n"
        "10.0.0.3,65003,Idle (Admin)\n"
        "10.0.0.4,65004,Idle (PfxCt)"
    )
