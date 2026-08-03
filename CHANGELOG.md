# Changelog

## 0.3.0 — Phase 2: parsed tier, profiles, kv_extract

Outputs on the default path (no `parsed`, no `profile`, no `platform`)
remain byte-identical to 0.1.0 — pinned by the parity suite against the
frozen baseline. `optimize()` is untouched.

- **Parsed tier** (`terse/parsed.py`): `render(parsed=...)` is now ACTIVE.
  Pass rows another parser already produced (Genie / ntc-templates / TTP /
  NAPALM / gNMI — a list of dicts, or a single dict for one row) and the
  tier re-encodes them header-once, independent of any registry match.
  Two candidates are emitted (`method="parsed"`), and the consumer's
  smallest-wins picks, as ever:
  - `parsed:csv` — header-once CSV, the smallest faithful flat encoding;
    beats the `json.dumps(rows)` key-per-row competitor by ~45–50% on
    multi-row output (the Phase-2 acceptance rule, pinned in
    `tests/test_parsed.py`).
  - `parsed:toon` — TOON-style tabular block (`[N]{fields}:` + indented
    rows); a few percent larger than CSV but the explicit row count lets
    a policy (or the model) detect truncation.
  Nested values JSON-encode into their cell; missing keys and `null`
  render as empty cells over the unioned first-seen header; malformed
  input yields no candidates (fail-open). Both candidates pass the usual
  shrink gate against the raw output.
- **Profiles**: `render(profile=...)` is now ACTIVE. A profile is a named,
  opt-in, DECLARED-lossy projection — `"updown"` ships first (interface
  liveness: port/status(/reason/protocol)), declared on the three
  interface-state specs and, by field-name pattern, on the parsed tier.
  Projected renderings append an inline omission marker
  (`[omitted: name, vlan, … — re-query profile=full]`) so the model knows
  data was withheld and how to recover it; the omitted names join the
  candidate's `dropped_fields` manifest, and `Candidate` gains a
  `profile` field naming what was applied. Entries that don't declare the
  requested profile render their complete default — an unknown profile
  never loses data. `"full"` is an alias of `"default"` (the complete
  path), so the marker's re-query hint is directly actionable.
- **`kv_extract` strategy** (`terse/engine.py`): first-match field scans
  are now expressible as specs. `show version` moved from a hand-written
  function to `spec:cisco/show_version` — byte-identical output (the
  cross-matrix pins it); `Candidate.source` for that family changed from
  `_compress_version` to `spec:cisco/show_version`. Registry is now 10
  specs + 5 code compressors.

## 0.2.0 — Phase 1: spec engine, platform keying, declared lossiness

Outputs are byte-identical to 0.1.0 on the default path (no `platform`
argument) — pinned by the parity suite against the frozen baseline.

- Spec engine (`terse/engine.py`): generic strategies compile declarative
  dict specs into compressors. Shipped strategies: `line_regex_table`,
  `fixed_width_table`.
- 9 of the 15 families converted from hand-written functions to specs
  (`terse/specs.py`): ip route, ip interface brief, bgp summary, ospf
  neighbors, cdp/lldp, vlan brief, interface status, interface brief
  (NX-OS), eigrp neighbors. The 6 genuinely stateful families stay as
  code (`_compressors.py`): interface detail, version, running-config,
  access-lists, counters errors, port-channel summary.
- Registry (`terse/registry.py`): one canonical-order `Entry` list
  carrying pattern, function, platform scope, and lossiness manifest;
  `register()` gains optional `platforms=` and `dropped_fields=`.
- `render(platform=...)` is now ACTIVE: entries with a non-matching
  platform scope are skipped (kills cross-family false matches, e.g. an
  NX-OS table spec claiming Arista output). The filter only ever skips —
  no platform, or no declared scope, tries everything (the parity path).
- Lossiness manifests: every shipped entry declares `dropped_fields`
  (`()` = lossless; e.g. ip-interface-brief declares `("ok", "method")`,
  access-lists declares `("hit_counters",)`), surfaced verbatim on
  `Candidate.dropped_fields`. Inline omission markers arrive with
  Phase-2 profiles.

## 0.1.0

Initial standalone cut, ported verbatim from dbcli's TOON optimizer
(`dbcli/services/token_optimizer.py`, netclaw-inspired).

- 15 compressor families (IOS + NX-OS): ip route, ip interface brief,
  interface detail, version, bgp summary, ospf neighbors, running-config,
  cdp/lldp neighbors, vlan brief, access-lists, interface status,
  interface brief (NX-OS), interface counters errors, eigrp neighbors,
  port-channel summary.
- Frozen public API: `render(raw, command=..., platform/parsed/profile
  reserved) -> [Candidate]`, `optimize()` (historical smallest-wins
  behavior, byte-for-byte), `register()` plugin escape hatch,
  `iter_compressors()`.
- Byte-parity suite against the frozen pre-extraction baseline
  (`tests/legacy_snapshot.py`): full command x body cross-matrix incl.
  wrong-command pairings and edge inputs.
- Zero runtime dependencies (enforced in CI), `py.typed`, Apache-2.0.
