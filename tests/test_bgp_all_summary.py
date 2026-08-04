from neterse import optimize


BGP_ALL_SUMMARY = """\
For address family: VPNv4 Unicast
BGP router identifier 10.79.1.80, local AS number 12625
BGP table version is 12286, main routing table version 12286
284 network entries using 72704 bytes of memory
BGP using 183358 total bytes of memory
BGP activity 1279/995 prefixes, 10697/10047 paths, scan interval 60 secs

Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State
/PfxRcd
10.20.3.46      4        65509 3033830 3034048    12286    0    0 15w2d
  1
10.79.0.1       4        12625 27763232 25447114    12286    0    0 2y24w
  112
"""


def test_bgp_all_summary_rejoins_wrapped_state_and_preserves_metadata():
    out = optimize("show bgp all summary", BGP_ALL_SUMMARY)
    assert out == """\
address_family=VPNv4 Unicast
BGP router identifier 10.79.1.80, local AS number 12625
BGP table version is 12286, main routing table version 12286
284 network entries using 72704 bytes of memory
BGP using 183358 total bytes of memory
BGP activity 1279/995 prefixes, 10697/10047 paths, scan interval 60 secs
neighbor,v,as,msg_rcvd,msg_sent,tbl_ver,in_q,out_q,up_down,state_pfx_rcd
10.20.3.46,4,65509,3033830,3034048,12286,0,0,15w2d,1
10.79.0.1,4,12625,27763232,25447114,12286,0,0,2y24w,112"""
    assert len(out) < len(BGP_ALL_SUMMARY)


def test_bgp_all_summary_accepts_unwrapped_state_and_multiple_families():
    second = BGP_ALL_SUMMARY.replace(
        "VPNv4 Unicast", "IPv4 Unicast"
    ).replace("15w2d\n  1", "15w2d Idle")
    raw = BGP_ALL_SUMMARY + "\n" + second
    out = optimize("show bgp all summary", raw)
    assert out.count("address_family=") == 2
    assert "15w2d,Idle" in out


def test_bgp_all_summary_missing_continuation_fails_open():
    raw = BGP_ALL_SUMMARY.rsplit("\n  112", 1)[0]
    assert optimize("show bgp all summary", raw) == raw


def test_bgp_all_summary_truncation_fails_open():
    raw = BGP_ALL_SUMMARY + "[TRUNCATED - middle omitted]\n"
    assert optimize("show bgp all summary", raw) == raw