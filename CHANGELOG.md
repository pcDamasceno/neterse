# Changelog

## 0.4.0 — Phase 3: community launch

Default-path outputs for all legacy families remain byte-identical to
the frozen baseline (parity cross-matrix). New vendor families are
post-baseline: covered behaviorally, never allowed to change a legacy
result (decision 15).

- **`terse audit`** (`terse/audit.py`, console script `terse` /
  `python -m terse`): the coverage tool, ported from dbcli's run
  analyzer. Feed it `(command, platform?, raw)` samples — JSONL files,
  fixture directories, raw captures with `--command`, or stdin — and it
  reports per-family reduction, totals (chars/4 token estimate),
  covered/uncovered volume, and the OPPORTUNITIES list (`NO COMPRESSOR`,
  `false-match:<entry>`, and the 0.2.0-registry addition
  `platform-skip:<entry>`), plus each winning entry's declared
  `dropped_fields` so an audit doubles as a lossiness review. `--show N`
  dumps the heads of the largest gaps; `--fail-under PCT` gates CI.
- **Parity replay** (`scripts/replay_parity.py`): replay any corpus
  through the frozen baseline and current terse, unified-diff and exit 1
  on byte differences. Repo-side by design — the baseline isn't shipped.
- **Fixture-per-file contribution layout**:
  `tests/fixtures/<platform>/<family>/{commands.txt,raw.txt}` — the
  audit CLI reads the same layout. Every fixture dropped there is
  auto-covered by the suite: diagonal shrink (with and without
  platform), winner-is-own-spec, wrong-platform skip, and a fail-open
  cross-matrix through terse itself.
- **Multi-vendor expansion** (9 new spec families, registered strictly
  after the legacy sequence): Arista EOS (interfaces status, ip arp,
  vlan), Juniper Junos (interfaces terse, ospf neighbor), Aruba AOS-CX
  (interface brief, vlan), MikroTik RouterOS (/ip address print,
  /interface print). `fixed_width_table` gains an optional `row_match`
  spec key for non-Cisco port names (`Et1`, `1/1/1`); the default stays
  the Cisco pattern, preserving byte-parity. Registry: 19 specs + 5
  code compressors.
- **Token-savings regression** (`tests/test_token_savings.py`, CI job):
  savings measured with a real, pinned tokenizer (`tiktoken==0.13.0`,
  `o200k_base`) against a committed per-family baseline
  (34 families: 3833 → 2313 tokens, 39.7% saved) with a 35% aggregate
  floor. Skips locally without tiktoken; runtime stays chars/4
  (decision 8). Regenerate with `scripts/update_token_baseline.py` —
  a recorded decision, like byte-parity changes.
- **Release machinery**: `release.yml` publishes `terse-net` to PyPI via
  Trusted Publishing on a `v*` tag (tag/version lockstep check + wheel
  smoke test); human steps in `docs/RELEASING.md`, including the PEP 541
  plan for the `terse` name.

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
