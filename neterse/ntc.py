"""Optional ntc-templates (TextFSM) front-end — parse, then render.

The parsed tier (``neterse.parsed``) re-encodes rows ANY parser already
produced; this module closes the loop for the most common stack by
driving ntc-templates itself: give it raw CLI text plus the
``(platform, command)`` pair ntc-templates keys its TextFSM templates
on, and it feeds the resulting rows straight into :func:`neterse.render`
— one call, both tiers, thousands of vendor/command families covered by
templates the community already maintains.

Install the extra to activate it::

    pip install neterse[textfsm]

Everything here is fail-open, like the rest of the package: without the
extra installed — or when no template exists for the pair, or the
template doesn't match the output — :func:`parse` returns ``None`` and
:func:`render`/:func:`optimize` behave exactly like their core
counterparts on the raw-text tier alone. Importing this module never
requires ntc-templates; the import happens lazily per call, so the core
package keeps its zero-runtime-dependency invariant (decision 29).
"""
from __future__ import annotations

import logging
from typing import List, Optional

import neterse

__all__ = ["parse", "platform_keys", "render", "optimize"]

logger = logging.getLogger("neterse")

# Transport suffixes runner libraries append to platform strings
# ("cisco_ios_ssh" is a netmiko device_type, not an ntc platform).
_TRANSPORT_SUFFIXES = ("_ssh", "_telnet", "_serial")

# Platform spellings the ecosystem uses that ntc-templates' index does
# not key (verified against the real index): netmiko types every IOS-XE
# box `cisco_xe` and itself retries as `cisco_ios` (ntc ships zero
# cisco_xe templates); scrapli's IOSXEDriver stamps `cisco_iosxe`, and
# its XR sibling spelling appears in the wild too. Remaps are tried
# LAST — only after the caller's own spelling failed — so they can only
# ever recover a parse, never change one.
_PLATFORM_REMAPS = {
    "cisco_xe": "cisco_ios",
    "cisco_iosxe": "cisco_ios",
    "cisco_iosxr": "cisco_xr",
}


def platform_keys(platform: str) -> "List[str]":
    """Template keys to try, in order, for a caller's platform string —
    plain ntc names, netmiko ``device_type``s and scrapli
    ``textfsm_platform``s all resolve. Suffix-stripped first (ntc's
    normal keying — and strictly better than netmiko's own verbatim
    keying for ``_telnet``/``_serial`` users), the verbatim string
    second (ntc keys every WLC template on ``cisco_wlc_ssh`` itself),
    a known remap last."""
    stripped = platform
    for suffix in _TRANSPORT_SUFFIXES:
        if platform.endswith(suffix):
            stripped = platform[: -len(suffix)]
            break
    keys = [stripped]
    if platform != stripped:
        keys.append(platform)
    remap = _PLATFORM_REMAPS.get(stripped)
    if remap and remap not in keys:
        keys.append(remap)
    return keys


def parse(
    raw_output: str, *, command: str, platform: str
) -> "Optional[List[dict]]":
    """Rows ntc-templates parses from *raw_output*, or ``None``.

    ``None`` — never an exception — when the ``textfsm`` extra is not
    installed, ntc-templates has no template for ``(platform, command)``,
    the template fails to match, or the result is not row-shaped. The
    platform string may be anything the ecosystem hands you — an ntc
    spelling (``cisco_ios``), a netmiko ``device_type``
    (``cisco_ios_ssh``, ``cisco_xe``), a scrapli ``textfsm_platform``
    (``cisco_iosxe``) — the :func:`platform_keys` ladder tries what
    actually resolves.
    """
    try:
        from ntc_templates.parse import parse_output
    except ImportError:
        logger.debug(
            "neterse.ntc: ntc-templates not installed "
            "(pip install neterse[textfsm]); skipping the parsed tier"
        )
        return None
    for key in platform_keys(platform):
        try:
            rows = parse_output(platform=key, command=command, data=raw_output)
        except Exception:
            logger.debug(
                "neterse.ntc: no template match for (%s, '%s'), skipping",
                key, command, exc_info=True,
            )
            continue
        if (
            isinstance(rows, list)
            and rows
            and all(isinstance(r, dict) for r in rows)
        ):
            return rows
    return None


def render(
    raw_output: str,
    *,
    command: str,
    platform: str,
    profile: str = "default",
) -> list:
    """:func:`neterse.render` with ``parsed=`` auto-supplied by
    ntc-templates. Identical to the core call when parsing yields
    nothing; ``platform`` is required because ntc-templates keys its
    templates on it (and it drives the raw-tier skip filter as usual).
    """
    return neterse.render(
        raw_output,
        command=command,
        platform=platform,
        parsed=parse(raw_output, command=command, platform=platform),
        profile=profile,
    )


def optimize(command: str, raw_output: str, *, platform: str) -> str:
    """Smallest candidate across BOTH tiers (ntc-parsed included), or
    *raw_output* unchanged — :func:`neterse.optimize` with the parser in
    the loop."""
    if not raw_output:
        return raw_output
    candidates = render(raw_output, command=command, platform=platform)
    if not candidates:
        return raw_output
    return min(candidates, key=lambda c: len(c.text)).text
