"""Phase-1/2 spec-engine specifics: strategies, platform keying, manifests.

Byte-parity of spec-built compressors with their hand-written ancestors is
covered exhaustively by ``test_parity.py`` (the default, no-platform path
must match the frozen baseline everywhere — including the Phase-2
``kv_extract`` conversion of ``show version``). This file pins the NEW
behavior the spec engine introduces on top; profile projections are
pinned in ``test_profiles.py``, the parsed tier in ``test_parsed.py``.
"""
from __future__ import annotations

import pytest

from neterse import iter_entries, optimize, register, render
from neterse import registry
from neterse.engine import STRATEGIES, build
from neterse.specs import SPECS

from .corpus import ACL, BRIEF, COMMAND_FIXTURES, IP_INT_BRIEF, IP_ROUTE


# ---------------------------------------------------------------------------
# Spec plumbing
# ---------------------------------------------------------------------------

def test_every_spec_builds_and_declares():
    """Specs must compile, use known strategies, and carry a manifest —
    a spec without ``dropped_fields`` would silently regress to
    'undeclared', losing exactly the vocabulary Phase 1 exists to add."""
    assert len(SPECS) == 20
    ids = [s["id"] for s in SPECS]
    assert len(ids) == len(set(ids)), "duplicate spec ids"
    for spec in SPECS:
        assert spec["strategy"] in STRATEGIES
        assert "dropped_fields" in spec, f"{spec['id']} missing manifest"
        fn = build(spec)
        assert callable(fn)
        assert fn.__name__ == f"spec:{spec['id']}"
        # fail-open on garbage, like every compressor
        assert fn("garbage that matches nothing") == "garbage that matches nothing"
        # every declared profile must also compile (and fail loudly on typos)
        for name in spec.get("profiles", ()):
            variant = build(spec, profile=name)
            assert callable(variant)
            assert variant.__name__ == f"spec:{spec['id']}@{name}"
            assert variant("garbage that matches nothing") == "garbage that matches nothing"


def test_unknown_strategy_fails_loudly_at_build_time():
    with pytest.raises(KeyError):
        build({"id": "x/y", "strategy": "no_such_strategy"})


def test_registry_interleaves_specs_and_code_in_canonical_order():
    names = [e.name for e in iter_entries()]
    assert names[0] == "spec:cisco/show_ip_route"
    assert names[2] == "_compress_interfaces"       # code stays 3rd, as in legacy
    assert names[3] == "spec:cisco/show_version"    # kv_extract conversion, Phase 2
    # the legacy sequence stays contiguous and ordered; Phase-3 vendor
    # entries append strictly AFTER it so ties keep resolving to baseline
    assert names[14] == "_compress_portchannel_summary"
    legacy = set(names[:15])
    assert all(
        "/" in n and n not in legacy for n in names[15:]
    ), "post-baseline entries must follow the legacy sequence"
    assert sum(1 for n in names if n.startswith("spec:")) == 20
    assert sum(1 for n in names if not n.startswith("spec:")) == 5


# ---------------------------------------------------------------------------
# Platform keying (active since 0.2.0)
# ---------------------------------------------------------------------------

def test_platform_match_and_mismatch_on_spec_entry():
    cmd = "show interface ethernet1/9 brief"
    # matching platform → the NX-OS spec fires
    assert optimize(cmd, BRIEF) != BRIEF
    matched = render(BRIEF, command=cmd, platform="cisco_nxos")
    assert matched and matched[0].source == "spec:cisco_nxos/show_interface_brief"
    # mismatching platform → spec skipped, nothing else claims it → no candidates
    assert render(BRIEF, command=cmd, platform="arista_eos") == []


def test_platform_never_forces_and_none_means_try_everything():
    for label, command, body in COMMAND_FIXTURES:
        default = render(body, command=command)
        assert render(body, command=command, platform=None) == default


def test_code_entries_ignore_platform_filter():
    """Code compressors declare no platform scope and must always run —
    the filter can only skip scoped entries, never scope-less ones."""
    out = render(ACL, command="show ip access-lists", platform="junos")
    assert out and out[0].source == "_compress_acl"


def test_unknown_platform_string_is_harmless_on_broad_specs():
    # 'cisco_iosxe' style strings hit the broad ios|xe|xr|nx scopes
    cands = render(IP_ROUTE, command="show ip route", platform="cisco_xe")
    assert cands and cands[0].source == "spec:cisco/show_ip_route"


# ---------------------------------------------------------------------------
# Lossiness manifests on candidates
# ---------------------------------------------------------------------------

def test_declared_drops_flow_onto_candidates():
    brief = render(IP_INT_BRIEF, command="show ip interface brief")
    assert brief[0].dropped_fields == ("ok", "method")

    acl = render(ACL, command="show ip access-lists")
    assert acl[0].dropped_fields == ("hit_counters",)

    route = render(IP_ROUTE, command="show ip route")
    assert route[0].dropped_fields == (             # decision 20: declared drops
        "route_age", "ecmp_alternate_paths", "subnet_group_headers"
    )


def test_every_registry_entry_declares_a_manifest():
    """Phase-1 exit criterion: no entry left 'undeclared' (None). Plugins
    registered without a manifest may be None — the shipped registry may not."""
    for entry in iter_entries():
        assert entry.dropped_fields is not None, f"{entry.name} undeclared"


def test_register_accepts_platforms_and_manifest():
    saved = list(registry.REGISTRY)
    try:
        @register(r"^plugin\s+cmd$", platforms=r"junos", dropped_fields=("foo",))
        def _p(raw: str) -> str:
            return "P"

        assert render("x" * 50, command="plugin cmd", platform="cisco_ios") == []
        got = render("x" * 50, command="plugin cmd", platform="junos_mx")
        assert got and got[0].dropped_fields == ("foo",)
    finally:
        registry.REGISTRY[:] = saved
