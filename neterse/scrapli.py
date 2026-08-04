"""Drop-in compaction for scrapli users.

A scrapli ``Response`` already carries everything neterse needs —
``result`` (the raw text), ``channel_input`` (the command),
``textfsm_platform`` (the driver's platform string) and
``textfsm_parse_output()`` (TextFSM rows via ntc-templates, when
``scrapli[textfsm]`` is installed) — so compaction is one call::

    from scrapli.driver.core import IOSXEDriver
    from neterse.scrapli import compact

    with IOSXEDriver(**device) as conn:
        response = conn.send_command("show interface status")
        print(compact(response))

:func:`compact` feeds all of it into :func:`neterse.render` so the
raw-text and parsed tiers compete for the smallest faithful rendering;
:func:`render` is the candidates-not-policy variant of the same call.

Everything here is duck-typed on the response object — this module
never imports scrapli, so the core package stays zero-dependency, any
``Response`` work-alike is welcome, and every failure path degrades
first to the raw-tier-only rendering and ultimately to
``response.result`` unchanged.

One deliberate limitation: :func:`compact`/:func:`render` operate on a
SINGLE ``Response``. The ``MultiResponse`` that ``send_commands([...])``
returns carries no ``channel_input``, so there is no command to dispatch
on — passing one in degrades safely to its joined raw ``result``,
uncompacted. Map over its elements instead::

    outputs = [compact(r) for r in conn.send_commands(commands)]
"""
from __future__ import annotations

from typing import Any, List, Optional

import neterse

__all__ = ["compact", "render", "rows_of"]


def rows_of(response: Any) -> "Optional[List[dict]]":
    """TextFSM rows for a scrapli response, or ``None`` — never an
    exception. ``None`` covers a missing ``textfsm_parse_output`` method,
    a parse failure (scrapli returns ``[]`` both when no template matches
    and when its ``textfsm`` extra is missing), non-row-shaped results
    (e.g. ``to_dict=False`` lists), and work-alikes that raise."""
    parse = getattr(response, "textfsm_parse_output", None)
    if not callable(parse):
        return None
    try:
        rows = parse()
    except Exception:
        return None
    if (
        isinstance(rows, list)
        and rows
        and all(isinstance(r, dict) for r in rows)
    ):
        return rows
    return None


def render(response: Any, *, profile: str = "default") -> list:
    """Every shrinking :class:`~neterse.Candidate` for a scrapli
    response, both tiers — the policy stays yours. Empty when the
    response carries no raw text or nothing shrinks it."""
    raw = getattr(response, "result", None)
    if not isinstance(raw, str) or not raw:
        return []
    command = getattr(response, "channel_input", "") or ""
    platform = getattr(response, "textfsm_platform", None) or None
    return neterse.render(
        raw,
        command=command,
        platform=platform,
        parsed=rows_of(response),
        profile=profile,
    )


def compact(response: Any, *, profile: str = "default") -> str:
    """Smallest faithful rendering of a scrapli response, or its raw
    ``result`` unchanged when nothing shrinks it."""
    candidates = render(response, profile=profile)
    if not candidates:
        raw = getattr(response, "result", None)
        return raw if isinstance(raw, str) else ""
    return min(candidates, key=lambda c: len(c.text)).text
