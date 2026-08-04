"""Drop-in compaction for netmiko users.

netmiko is how a huge share of network engineers already run commands;
this module puts the compact rendering one import away::

    from netmiko import ConnectHandler
    from neterse.netmiko import send_command

    conn = ConnectHandler(device_type="cisco_ios", host="10.0.0.1",
                          **credentials)
    compact = send_command(conn, "show interface status")

:func:`send_command` runs the command through the connection exactly as
netmiko would (positional command string, kwargs pass straight through)
and returns the smallest faithful rendering instead of the raw
80-column table. The raw-text tier always competes; with the ``textfsm``
extra installed (``pip install neterse[textfsm]``) ntc-templates parses
the output too, so the parsed tier competes as well — keyed the way
netmiko's own ``use_textfsm=True`` actually resolves templates: the
``device_type`` with its transport suffix stripped, then verbatim
(ntc-templates keys the WLC templates on ``cisco_wlc_ssh`` itself),
then netmiko's own ``cisco_xe`` → ``cisco_ios`` retry.

Already parsed the output yourself (``use_textfsm=True``)?
:func:`send_command` detects the non-string result and compacts the
structure instead (:func:`neterse.optimize_parsed`), and :func:`compact`
does the same for output you are already holding.

Everything here is duck-typed on the connection object — this module
never imports netmiko, so the core package stays zero-dependency, any
``BaseConnection`` work-alike is welcome, and every failure path
degrades toward returning the device output unchanged.
"""
from __future__ import annotations

from typing import Any, List, Optional

import neterse
from neterse import ntc

__all__ = ["compact", "platform_of", "send_command"]

# netmiko device_type transport suffixes that usually don't belong in an
# ntc-templates platform string ("cisco_ios_ssh" -> "cisco_ios").
_TRANSPORT_SUFFIXES = ("_ssh", "_telnet", "_serial")


def platform_of(conn: Any) -> Optional[str]:
    """The suffix-stripped ``device_type`` of a netmiko connection —
    handy for driving :func:`neterse.render`'s raw-tier filter yourself;
    ``None`` when the attribute is absent or empty. (:func:`compact` and
    :func:`send_command` key the PARSER on richer fallbacks — see
    ``_parse_keys`` — so hand them the verbatim ``device_type``.)"""
    device_type = getattr(conn, "device_type", None)
    if not isinstance(device_type, str) or not device_type:
        return None
    return _strip_transport(device_type)


def _strip_transport(platform: str) -> str:
    for suffix in _TRANSPORT_SUFFIXES:
        if platform.endswith(suffix):
            return platform[: -len(suffix)]
    return platform


def _parse_keys(platform: str) -> List[str]:
    """ntc-templates platform keys to try, in order, for a netmiko
    ``device_type``. Suffix-stripped first (the normal ntc keying — and
    strictly better than netmiko itself for ``_telnet``/``_serial``
    users), the verbatim string second (ntc keys every WLC template on
    ``cisco_wlc_ssh``), and netmiko's own documented retry last: it
    re-parses ``cisco_xe`` as ``cisco_ios`` because ntc-templates ships
    no ``cisco_xe`` templates at all."""
    stripped = _strip_transport(platform)
    keys = [stripped]
    if platform != stripped:
        keys.append(platform)
    if "cisco_xe" in stripped and "cisco_ios" not in keys:
        keys.append("cisco_ios")
    return keys


def compact(
    output: Any,
    *,
    command: str,
    platform: Optional[str] = None,
    profile: str = "default",
) -> str:
    """Smallest faithful rendering of whatever netmiko returned.

    A raw string goes through both tiers: *platform* — pass the
    connection's ``device_type`` verbatim; suffix stripping and
    netmiko's ``cisco_xe`` retry happen here — drives the raw-tier skip
    filter as given and keys the ntc-templates parse via
    ``_parse_keys`` when the ``textfsm`` extra is installed. A
    structured result (``use_textfsm=True`` rows) is re-encoded
    header-once against its compact-JSON baseline. Never raises for
    control flow, never enlarges: the fallback is the output's own
    representation.
    """
    if not isinstance(output, str):
        return neterse.optimize_parsed(output, profile=profile)
    parsed = None
    if platform:
        for key in _parse_keys(platform):
            parsed = ntc.parse(output, command=command, platform=key)
            if parsed is not None:
                break
    candidates = neterse.render(
        output,
        command=command,
        platform=platform,
        parsed=parsed,
        profile=profile,
    )
    if not candidates:
        return output
    return min(candidates, key=lambda c: len(c.text)).text


def send_command(
    conn: Any, command_string: str, *, profile: str = "default", **kwargs: Any
) -> str:
    """``conn.send_command(command_string, **kwargs)``, compacted.

    The netmiko call itself is untouched. Leave ``use_textfsm`` off and
    let neterse drive the parsing — that way the raw and parsed tiers
    both compete for the smallest rendering; with it on, the structured
    result is compacted instead (the raw text never reaches this side).
    """
    output = conn.send_command(command_string, **kwargs)
    device_type = getattr(conn, "device_type", None)
    return compact(
        output,
        command=command_string,
        platform=(
            device_type
            if isinstance(device_type, str) and device_type else None
        ),
        profile=profile,
    )
