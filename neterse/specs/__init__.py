"""Declarative specs — the data-driven tier of the registry.

Specs are AUTHORED as YAML, one file per command family in this
directory — ``neterse/specs/<vendor>/<family>.yaml``, the layout
ntc-templates made familiar — and COMPILED by
``scripts/compile_specs.py`` into the generated, committed
``_compiled.py`` this package re-exports. YAML is an authoring-time
format only: the runtime imports plain Python dicts, so the
zero-dependency invariant holds (PyYAML lives in the ``test`` extra,
never in the core — decision 27).

Each spec is a plain dict the engine compiles into a compressor
(``engine.build``). Contributing a new table-shaped command family is
one YAML file plus fixtures — no parser code, and no registry edit:
specs without an explicit position in the canonical order self-append
after it (``registry.py``, decision 28). Genuinely stateful formats
(multi-line blocks, banner state machines) stay as code in
``_compressors.py``; the escape hatch is deliberate.

Field notes (the compiler validates all of this loudly):

``id``
    Derived from the file path (``<vendor>/<family>``) — never written
    in the YAML.

``platforms``
    Case-insensitive regex matched against the caller-supplied platform
    string (``render(..., platform=...)``). No platform given, or no
    ``platforms`` key → the spec is always tried (fail-open: filtering
    only ever *skips* work, it never forces a match). Declare broadly —
    the filter exists to kill cross-family false matches, not to gatekeep.

``dropped_fields``
    The lossiness manifest, REQUIRED: names of DATA-bearing fields this
    rendering omits, surfaced verbatim on ``Candidate.dropped_fields``
    so consumers can disclose omissions to the model. Pure noise —
    separators, static legends, repeated headers — is dropped freely and
    never declared. ``[]`` means "declared lossless".

``profiles``
    Named, opt-in, *declared-lossy* column projections:
    ``profiles: {updown: {keep: [port, status]}}``. Requested via
    ``render(..., profile="updown")``; the variant emits only the kept
    columns and appends an inline omission marker naming what was
    withheld. The omitted column names join the entry's manifest on the
    resulting candidates. Entries that don't declare a requested profile
    render their complete default — a profile can narrow output only
    where a spec explicitly said how.

``row_flags`` / ``fields[].flags``
    Symbolic regex flag names (``VERBOSE``, ``IGNORECASE``, …), resolved
    to ``re`` flags at compile time.

The row regexes are byte-for-byte the historical hand-written ones —
sole exception: ``show_ip_route``'s VERBOSE row, reformatted as a block
scalar (whitespace and comment layout a VERBOSE pattern ignores;
decision 27). The parity suite holds spec output identical to the
frozen baseline either way.
"""
from __future__ import annotations

from ._compiled import SPECS

__all__ = ["SPECS"]
