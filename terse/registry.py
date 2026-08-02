"""The compressor registry — canonical order, both tiers.

One ordered list of :class:`Entry` interleaving spec-built compressors
(``specs.py`` via ``engine.build``) and hand-written code compressors
(``_compressors.py``), in exactly the registration order of the
pre-extraction implementation. Order is load-bearing only for tie-breaks
(equal-length candidates: first wins); keeping it frozen makes byte-parity
with the baseline unconditional rather than probabilistic.

``platforms`` on an entry is a *skip filter*: when the caller supplies a
platform string and the entry declares platforms that don't match, the
entry is skipped — killing cross-family false matches. It can only ever
skip work; with no platform given (or none declared) everything is tried,
which is the byte-parity path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from . import _compressors as _c
from .engine import build
from .specs import SPECS

Compressor = Callable[[str], str]


@dataclass(frozen=True)
class Entry:
    pattern: re.Pattern
    fn: Compressor
    name: str
    platforms: Optional[re.Pattern] = None
    # None = undeclared (pre-manifest legacy); () = declared lossless;
    # non-empty = data-bearing fields this rendering omits.
    dropped_fields: Optional[Tuple[str, ...]] = None


def _spec_entry(spec: dict) -> Entry:
    return Entry(
        pattern=re.compile(spec["command"], re.IGNORECASE),
        fn=build(spec),
        name=f"spec:{spec['id']}",
        platforms=(
            re.compile(spec["platforms"], re.IGNORECASE)
            if spec.get("platforms") else None
        ),
        dropped_fields=(
            tuple(spec["dropped_fields"])
            if spec.get("dropped_fields") is not None else None
        ),
    )


def _code_entry(
    pattern: str,
    fn: Compressor,
    dropped_fields: Optional[Tuple[str, ...]] = None,
) -> Entry:
    return Entry(
        pattern=re.compile(pattern, re.IGNORECASE),
        fn=fn,
        name=getattr(fn, "__name__", str(fn)),
        platforms=None,           # code compressors are always tried (fail-open)
        dropped_fields=dropped_fields,
    )


_BY_ID = {s["id"]: s for s in SPECS}

# Canonical order — mirrors the pre-extraction registration sequence.
REGISTRY: List[Entry] = [
    _spec_entry(_BY_ID["cisco/show_ip_route"]),
    _spec_entry(_BY_ID["cisco_ios/show_ip_interface_brief"]),
    _code_entry(
        # Per-interface DETAIL only; sibling table subcommands have their
        # own compressors (see the negative lookahead).
        r"^show\s+int(?:erface|erfaces)?"
        r"(?:\s+(?!status\b|brief\b|counters?\b|transceiver\b|switchport\b|"
        r"capabilities\b|description\b|trunk\b|mac\b|flowcontrol\b|storm\b|"
        r"snmp\b|purge\b)\S+)?\s*$",
        _c._compress_interfaces,
        dropped_fields=("unmatched_lines", "zero_valued_error_counters"),
    ),
    _code_entry(
        r"show\s+version",
        _c._compress_version,
        dropped_fields=("unmatched_lines",),
    ),
    _spec_entry(_BY_ID["cisco/show_ip_bgp_summary"]),
    _spec_entry(_BY_ID["cisco/show_ip_ospf_neighbor"]),
    _code_entry(
        r"show\s+run",
        _c._compress_running_config,
        dropped_fields=("banner_bodies",),
    ),
    _spec_entry(_BY_ID["cisco/show_cdp_lldp_neighbors"]),
    _spec_entry(_BY_ID["cisco/show_vlan_brief"]),
    _code_entry(
        r"show\s+(?:ip\s+)?access-lists?",
        _c._compress_acl,
        dropped_fields=("hit_counters",),
    ),
    _spec_entry(_BY_ID["cisco/show_interface_status"]),
    _spec_entry(_BY_ID["cisco_nxos/show_interface_brief"]),
    _code_entry(
        r"show\s+int(?:erface|erfaces)?\s+counters?\s+err",
        _c._compress_intf_counter_errors,
        dropped_fields=("all_zero_rows",),
    ),
    _spec_entry(_BY_ID["cisco/show_ip_eigrp_neighbors"]),
    _code_entry(
        r"show\s+(?:ether(?:channel)?|port-channel)\s+sum",
        _c._compress_portchannel_summary,
        dropped_fields=(),
    ),
]


def register(
    pattern: str,
    *,
    platforms: Optional[str] = None,
    dropped_fields: Optional[Tuple[str, ...]] = None,
):
    """Bind a compressor function to a command regex (plugin escape hatch).

    The function receives raw output and must return a string; return the
    input unchanged when you cannot parse it. ``platforms`` (optional
    regex) scopes it to matching platform strings; ``dropped_fields``
    declares any data-bearing omissions (the lossiness manifest).
    """
    compiled = re.compile(pattern, re.IGNORECASE)
    plat = re.compile(platforms, re.IGNORECASE) if platforms else None

    def decorator(fn: Compressor) -> Compressor:
        REGISTRY.append(
            Entry(
                pattern=compiled,
                fn=fn,
                name=getattr(fn, "__name__", str(fn)),
                platforms=plat,
                dropped_fields=(
                    tuple(dropped_fields) if dropped_fields is not None else None
                ),
            )
        )
        return fn

    return decorator


def iter_entries() -> Tuple[Entry, ...]:
    """Snapshot of the full registry with metadata."""
    return tuple(REGISTRY)


def iter_compressors() -> tuple:
    """Snapshot as ``(compiled_pattern, function)`` pairs (0.1 API shape)."""
    return tuple((e.pattern, e.fn) for e in REGISTRY)
