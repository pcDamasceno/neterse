# Changelog

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
