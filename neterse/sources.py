"""Source adapters — how :func:`neterse.compact` reads foreign objects.

One verb must serve every library without per-library names
(decision 32). ``compact()`` dispatches on SHAPE: strings are raw CLI
text, list/dict structures are parsed rows, anything with
``send_command`` is a connection to run — and everything else is offered
to the adapters here, small sniffers that translate a response-like
object into the one shape neterse understands:

* ``raw`` — the raw CLI text (``None`` when only structure exists)
* ``command`` — the command that produced it (``""`` when unknown)
* ``platform`` — a platform string for the skip filter / parser keying
* ``rows`` — structured rows another parser already produced

The shipped adapter reads the scrapli ``Response`` surface (``result`` /
``channel_input`` / ``textfsm_platform`` / ``textfsm_parse_output()``),
which also covers its async twin, ``MultiResponse`` (degrades to the
joined raw result — map ``compact`` over the elements instead) and
nornir-style results whose ``result`` holds structured rows. Libraries
whose getters return plain structures — NAPALM, gNMI — need no adapter
at all: ``compact()`` takes those directly. A future response object is
one :func:`register_adapter` call away; the public API never grows a
new name for it.

Stdlib only, no library imports, fail-open — like everything else here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

__all__ = ["Source", "register_adapter", "coerce"]


@dataclass(frozen=True)
class Source:
    """What neterse needs from any foreign object."""

    raw: Optional[str] = None
    command: str = ""
    platform: Optional[str] = None
    rows: Optional[Any] = None


# An adapter receives an arbitrary object and returns a Source, or None
# for "not mine". An adapter that raises counts as "not mine".
Adapter = Callable[[Any], Optional[Source]]


def _row_shaped(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(r, dict) for r in value)
    )


def _response_like(obj: Any) -> Optional[Source]:
    """Anything carrying a ``result`` attribute — scrapli's ``Response``
    (sync and async), ``MultiResponse``, nornir-style results, and
    work-alikes. Command, platform and pre-parsed rows ride along when
    the object has them."""
    if not hasattr(obj, "result"):
        return None
    raw = obj.result
    rows = None
    parse = getattr(obj, "textfsm_parse_output", None)
    if callable(parse):
        try:
            parsed = parse()
        except Exception:
            parsed = None
        if _row_shaped(parsed):
            rows = parsed
    if rows is None and _row_shaped(raw):
        rows = raw                    # nornir-style: result IS the rows
    command = getattr(obj, "channel_input", "")
    platform = getattr(obj, "textfsm_platform", None)
    return Source(
        raw=raw if isinstance(raw, str) else None,
        command=command if isinstance(command, str) else "",
        platform=(
            platform if isinstance(platform, str) and platform else None
        ),
        rows=rows,
    )


ADAPTERS: List[Adapter] = [_response_like]


def register_adapter(adapter: Adapter) -> Adapter:
    """Teach :func:`neterse.compact` a new response object.

    *adapter* receives the object and returns a :class:`Source` — or
    ``None`` for "not mine". Registered adapters are tried before the
    built-ins, an adapter that raises counts as "not mine", and nothing
    else about the public API changes: that is the point (decision 32).
    Usable as a decorator.
    """
    ADAPTERS.insert(0, adapter)
    return adapter


def coerce(obj: Any) -> Optional[Source]:
    """The :class:`Source` for *obj*, or ``None`` when no adapter
    claims it."""
    for adapter in ADAPTERS:
        try:
            source = adapter(obj)
        except Exception:
            source = None
        if source is not None:
            return source
    return None
