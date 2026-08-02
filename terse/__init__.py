"""terse — the ``| brief`` the vendor never shipped.

Turns verbose network CLI output into the minimum-token representation
for LLM context. This is the Phase-0 cut of the standalone ``terse``
package, incubating inside dbcli until it is extracted to its own
repository and published to PyPI (the import path then becomes plain
``terse``; the code itself will not change).

Public API — frozen as of 0.1.0 so the signature survives to the
standalone release:

* :func:`render` — produce every shrinking :class:`Candidate` for a
  command's output. The library never picks a winner; policy (e.g.
  "smallest wins"), metrics, and caching belong to the consumer.
* :func:`optimize` — convenience wrapper preserving the historical
  dbcli behavior byte-for-byte: smallest candidate's text, or the raw
  output unchanged when nothing shrinks it.
* :func:`register` — plugin escape hatch: bind your own compressor
  function to a command regex.
* :func:`iter_compressors` — read-only view of the registry.

Reserved :func:`render` parameters (accepted today, active in later
phases): ``platform`` (platform-keyed dispatch), ``parsed`` (re-encoding
of already-parsed rows), ``profile`` (declared-lossiness projections).

Invariants — enforced here, relied on by every consumer:

1. Fail-open: a compressor that raises, returns a non-string, returns
   empty, or fails to shrink simply produces no candidate. Raw data is
   never lost and never enlarged.
2. Zero runtime dependencies: standard library only.
3. Candidates, not policy: this package never decides which
   representation a consumer must use.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ._compressors import _COMPRESSORS, _register

__version__ = "0.1.0"

__all__ = [
    "Candidate",
    "iter_compressors",
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

    ``dropped_fields`` is ``None`` when the producing compressor predates
    declared lossiness (all Phase-0 compressors) — meaning "undeclared",
    not "nothing dropped". Later phases populate it from spec manifests.
    """

    text: str
    method: str                                   # "toon" = raw-text compressor tier
    source: str                                   # producing compressor's name
    dropped_fields: Optional[tuple[str, ...]] = None

    @property
    def est_chars(self) -> int:
        return len(self.text)

    def est_tokens(self, chars_per_token: float = 4.0) -> int:
        """Cheap token estimate (chars/4 by default — the dbcli metric
        convention). Real tokenizers are a CI concern, never a runtime
        dependency."""
        return int(len(self.text) / chars_per_token) if chars_per_token else 0


def render(
    raw_output: str,
    *,
    command: str,
    platform: Optional[str] = None,
    parsed: Optional[Any] = None,
    profile: str = "default",
) -> list[Candidate]:
    """Return every candidate that strictly shrinks *raw_output*.

    Candidates appear in registry order; ``min(..., key=lambda c:
    len(c.text))`` therefore reproduces the historical "first smallest
    wins" selection exactly. An empty list means nothing shrank — send
    the raw output.

    ``platform``, ``parsed`` and ``profile`` are reserved (see module
    docstring); they are accepted so today's call sites survive the
    phases that activate them, and are currently ignored.
    """
    del platform, parsed, profile  # reserved — no effect in 0.1
    if not raw_output:
        return []
    candidates: list[Candidate] = []
    for pattern, compressor in _COMPRESSORS:
        if not pattern.search(command):
            continue
        try:
            result = compressor(raw_output)
        except Exception:
            logger.debug(
                "TOON compressor %s failed for '%s', skipping",
                getattr(compressor, "__name__", compressor), command, exc_info=True,
            )
            continue
        if isinstance(result, str) and 0 < len(result) < len(raw_output):
            candidates.append(
                Candidate(
                    text=result,
                    method="toon",
                    source=getattr(compressor, "__name__", str(compressor)),
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


def register(pattern: str) -> Callable:
    """Bind a compressor function to a command regex (plugin escape hatch).

    The function receives the raw output and must return a string; return
    the input unchanged when you cannot parse it (fail-open — the library
    additionally drops exceptions and non-shrinking results, so the worst
    a compressor can do is nothing).
    """
    return _register(pattern)


def iter_compressors() -> tuple:
    """Snapshot of the registry as ``(compiled_pattern, function)`` pairs."""
    return tuple(_COMPRESSORS)
