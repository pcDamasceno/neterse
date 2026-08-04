"""neterse — the ``| brief`` the vendor never shipped.

Turns verbose network CLI output into the minimum-token representation
for LLM context.

Public API:

* :func:`render` — produce every shrinking :class:`Candidate` for a
  command's output. The library never picks a winner; policy (e.g.
  "smallest wins"), metrics, and caching belong to the consumer.
* :func:`optimize` — convenience wrapper preserving the historical
  behavior byte-for-byte: smallest candidate's text, or the raw output
  unchanged when nothing shrinks it.
* :func:`register` — plugin escape hatch: bind your own compressor to a
  command regex, optionally scoped by ``platforms`` and carrying a
  ``dropped_fields`` manifest.
* :func:`iter_compressors` / :func:`iter_entries` — registry views
  (pattern/function pairs, or full :class:`Entry` metadata).

``render`` parameters:

* ``platform`` — a platform string such as
  ``"cisco_nxos"``. Entries that declare a platform scope and don't match
  are skipped; entries with no declared scope are always tried. The
  filter can only skip work, never force a match — omitting it is always
  safe and reproduces the historical behavior exactly.
* ``parsed`` — rows another parser (Genie,
  ntc-templates, TTP, NAPALM, gNMI) already produced for this output: a
  list of dicts (or a single dict — one row). The parsed tier re-encodes
  them header-once (``parsed:csv`` and ``parsed:toon`` candidates,
  ``method="parsed"``), independent of any registry match. Malformed or
  non-row-shaped input yields no parsed candidates — fail-open, like
  everything else.
* ``profile`` — a named, opt-in, DECLARED-lossy
  projection (e.g. ``"updown"``: interface liveness only). Entries and
  parsed encodings that know the profile emit only the kept fields and
  append an inline omission marker naming what was withheld; everything
  else falls back to its complete default rendering. ``"default"`` (and
  its alias ``"full"``, the spelling the marker suggests for re-query)
  is the complete-but-compact path — byte-identical to omitting the
  argument. An unknown profile name never loses data.

Invariants — enforced here, relied on by every consumer:

1. Fail-open: a compressor that raises, returns a non-string, returns
   empty, or fails to shrink simply produces no candidate. Raw data is
   never lost and never enlarged.
2. Zero runtime dependencies: standard library only.
3. Candidates, not policy: this package never decides which
   representation a consumer must use.
4. Declared lossiness: a rendering that omits data-bearing fields says so
   on ``Candidate.dropped_fields`` (``None`` = predates declaration), and
   non-default profiles additionally say so INLINE in the rendering
   itself, so the model knows data was withheld and how to recover it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from . import parsed as _parsed_tier
from .registry import (  # noqa: F401  (re-exported)
    Entry,
    REGISTRY,
    iter_compressors,
    iter_entries,
    register,
)

__version__ = "0.1.0"

__all__ = [
    "Candidate",
    "Entry",
    "iter_compressors",
    "iter_entries",
    "optimize",
    "register",
    "render",
    "__version__",
]

logger = logging.getLogger("neterse")
logger.addHandler(logging.NullHandler())


@dataclass(frozen=True)
class Candidate:
    """One possible compact rendering of a command's output.

    ``method`` is the producing tier: ``"toon"`` = raw-text tier,
    ``"parsed"`` = parsed tier. ``dropped_fields`` is the lossiness
    manifest: ``None`` means the compressor predates declaration
    ("undeclared", not "nothing dropped"); ``()`` means declared
    lossless; names list the data-bearing fields this rendering omits.
    ``profile`` names the projection actually applied — ``"default"``
    unless a requested non-default profile took effect, in which case the
    text also carries the inline omission marker.
    """

    text: str
    method: str
    source: str                                   # producing entry/encoder
    dropped_fields: Optional[Tuple[str, ...]] = None
    profile: str = "default"

    @property
    def est_chars(self) -> int:
        return len(self.text)

    def est_tokens(self, chars_per_token: float = 4.0) -> int:
        """Cheap token estimate (chars/4 by default). Real tokenizers are
        a CI concern, never a runtime dependency."""
        return int(len(self.text) / chars_per_token) if chars_per_token else 0


def _profile_key(profile: Optional[str]) -> str:
    """Normalize the requested profile; ``full`` is an alias of the
    complete ``default`` (it's the spelling the omission marker tells the
    model to re-query with)."""
    key = (profile or "default").lower()
    return "default" if key == "full" else key


def render(
    raw_output: str,
    *,
    command: str,
    platform: Optional[str] = None,
    parsed: Optional[Any] = None,
    profile: str = "default",
) -> list:
    """Return every candidate that strictly shrinks *raw_output*.

    Raw-text-tier candidates appear first, in registry order, then
    parsed-tier candidates; ``min(..., key=lambda c: len(c.text))``
    therefore reproduces the historical "first smallest wins" selection
    exactly on the default path. An empty list means nothing shrank —
    send the raw output.
    """
    if not raw_output:
        return []
    platform_key = platform.lower() if platform else None
    profile_key = _profile_key(profile)
    candidates: list = []
    for entry in REGISTRY:
        if not entry.pattern.search(command):
            continue
        if platform_key and entry.platforms and not entry.platforms.search(platform_key):
            continue
        fn, drops, applied = entry.fn, entry.dropped_fields, "default"
        if profile_key != "default" and entry.profiles and profile_key in entry.profiles:
            variant = entry.profiles[profile_key]
            fn, drops, applied = variant.fn, variant.dropped_fields, profile_key
        try:
            result = fn(raw_output)
        except Exception:
            logger.debug(
                "neterse compressor %s failed for '%s', skipping",
                entry.name, command, exc_info=True,
            )
            continue
        if isinstance(result, str) and 0 < len(result) < len(raw_output):
            candidates.append(
                Candidate(
                    text=result,
                    method="toon",
                    source=entry.name,
                    dropped_fields=drops,
                    profile=applied,
                )
            )
    if parsed is not None:
        try:
            encoded = _parsed_tier.encode(parsed, profile_key)
        except Exception:
            logger.debug(
                "neterse parsed tier failed for '%s', skipping",
                command, exc_info=True,
            )
            encoded = []
        for text, source, drops, applied in encoded:
            if isinstance(text, str) and 0 < len(text) < len(raw_output):
                candidates.append(
                    Candidate(
                        text=text,
                        method="parsed",
                        source=source,
                        dropped_fields=drops,
                        profile=applied,
                    )
                )
    return candidates


def optimize(command: str, raw_output: str) -> str:
    """Compress *raw_output* for the given CLI *command*.

    Every compressor whose pattern matches the command is tried, and the
    SMALLEST result that actually shrinks the output wins. Trying all matches
    (rather than stopping at the first) means a broad, older pattern can no
    longer shadow a newer, command-specific compressor — a real problem when
    IOS-shaped patterns overlap NX-OS command names. Each compressor is
    fail-open: an exception or a non-shrinking result simply drops it from the
    running, so the original output is never lost.
    """
    if not raw_output:
        return raw_output
    best: Optional[Candidate] = None
    for candidate in render(raw_output, command=command):
        if best is None or len(candidate.text) < len(best.text):
            best = candidate
    if best is None:
        return raw_output
    saved = 100 * (1 - len(best.text) / len(raw_output))
    logger.debug(
        "TOON compressed '%s' via %s: %d -> %d chars (%.0f%% reduction)",
        command, best.source, len(raw_output), len(best.text), saved,
    )
    return best.text
