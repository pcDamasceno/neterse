"""terse — the ``| brief`` the vendor never shipped.

Turns verbose network CLI output into the minimum-token representation
for LLM context.

Public API (0.1.0 surface, unchanged; 0.2.0 activates ``platform`` and
adds registry metadata):

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

* ``platform`` (active since 0.2.0) — a platform string such as
  ``"cisco_nxos"``. Entries that declare a platform scope and don't match
  are skipped; entries with no declared scope are always tried. The
  filter can only skip work, never force a match — omitting it is always
  safe and reproduces the historical behavior exactly.
* ``parsed``, ``profile`` (reserved) — activate with the parsed tier and
  declared-lossiness profiles in later phases.

Invariants — enforced here, relied on by every consumer:

1. Fail-open: a compressor that raises, returns a non-string, returns
   empty, or fails to shrink simply produces no candidate. Raw data is
   never lost and never enlarged.
2. Zero runtime dependencies: standard library only.
3. Candidates, not policy: this package never decides which
   representation a consumer must use.
4. Declared lossiness: a rendering that omits data-bearing fields says so
   on ``Candidate.dropped_fields`` (``None`` = predates declaration).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from .registry import (  # noqa: F401  (re-exported)
    Entry,
    REGISTRY,
    iter_compressors,
    iter_entries,
    register,
)

__version__ = "0.2.0"

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

logger = logging.getLogger("terse")
logger.addHandler(logging.NullHandler())


@dataclass(frozen=True)
class Candidate:
    """One possible compact rendering of a command's output.

    ``dropped_fields`` is the producing entry's lossiness manifest:
    ``None`` means the compressor predates declaration ("undeclared", not
    "nothing dropped"); ``()`` means declared lossless; names list the
    data-bearing fields this rendering omits.
    """

    text: str
    method: str                                   # "toon" = raw-text tier
    source: str                                   # producing entry's name
    dropped_fields: Optional[Tuple[str, ...]] = None

    @property
    def est_chars(self) -> int:
        return len(self.text)

    def est_tokens(self, chars_per_token: float = 4.0) -> int:
        """Cheap token estimate (chars/4 by default). Real tokenizers are
        a CI concern, never a runtime dependency."""
        return int(len(self.text) / chars_per_token) if chars_per_token else 0


def render(
    raw_output: str,
    *,
    command: str,
    platform: Optional[str] = None,
    parsed: Optional[Any] = None,
    profile: str = "default",
) -> list:
    """Return every candidate that strictly shrinks *raw_output*.

    Candidates appear in registry order; ``min(..., key=lambda c:
    len(c.text))`` therefore reproduces the historical "first smallest
    wins" selection exactly. An empty list means nothing shrank — send
    the raw output.
    """
    del parsed, profile  # reserved — no effect yet
    if not raw_output:
        return []
    platform_key = platform.lower() if platform else None
    candidates: list = []
    for entry in REGISTRY:
        if not entry.pattern.search(command):
            continue
        if platform_key and entry.platforms and not entry.platforms.search(platform_key):
            continue
        try:
            result = entry.fn(raw_output)
        except Exception:
            logger.debug(
                "terse compressor %s failed for '%s', skipping",
                entry.name, command, exc_info=True,
            )
            continue
        if isinstance(result, str) and 0 < len(result) < len(raw_output):
            candidates.append(
                Candidate(
                    text=result,
                    method="toon",
                    source=entry.name,
                    dropped_fields=entry.dropped_fields,
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
