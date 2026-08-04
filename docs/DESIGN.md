# neterse — design, topology, and plan

*Status: Phase 3 shipped (0.4.0), and dbcli — the first consumer — has
executed its side of the Phase-4 cutover (commit-pinned git dependency);
the PyPI publish itself awaits the maintainer's tag (docs/RELEASING.md).
This document is the project's source of truth for architecture and
roadmap; decisions recorded here are binding until a new entry supersedes
them.*

## The problem

LLM network agents pay for every character a `show` command returns.
Vendor CLI output is built for humans on 80-column terminals: separator
dashes, static legends, wrapped headers, all-zero counter tables, keys
repeated per row. On big tables this noise doesn't just cost tokens — it
overflows tool-output caps, so the model sees a *truncated* table and
reasons over missing rows. neterse rewrites device output into the smallest
faithful representation before it enters model context.

## Topology

```
                       consumer (dbcli, NetClaw, your agent, …)
                                        │ raw CLI text, command,
                                        │ platform?, parsed rows?, profile?
                                        ▼
        ┌───────────────────────────── neterse ─────────────────────────────┐
        │                                                                 │
        │  registry.py — ONE canonical-order list of Entry:               │
        │    (command pattern, fn, platform scope?, dropped_fields?)      │
        │                                                                 │
        │  ┌── data tier ─────────────────┐  ┌── code tier ─────────────┐ │
        │  │ specs.py: plain-dict specs   │  │ _compressors.py: hand-   │ │
        │  │ engine.py: generic           │  │ written functions for    │ │
        │  │ strategies compile specs     │  │ genuinely stateful       │ │
        │  │ into compressors             │  │ formats (multi-line      │ │
        │  │  · line_regex_table          │  │ blocks, banner state     │ │
        │  │  · fixed_width_table         │  │ machines, multi-table    │ │
        │  │  · kv_extract                │  │ zero-row suppression)    │ │
        │  │  + named profile projections │  │                          │ │
        │  └──────────────────────────────┘  └──────────────────────────┘ │
        │  ┌── parsed tier ──────────────────────────────────────────────┐│
        │  │ parsed.py: rows Genie/ntc-templates/TTP/NAPALM already      ││
        │  │ produced → header-once encoders (parsed:csv, parsed:toon);  ││
        │  │ command-independent; profile projections by field name      ││
        │  └─────────────────────────────────────────────────────────────┘│
        │                                                                 │
        │  render() → [Candidate(text, method, source, dropped_fields,    │
        │             profile)]                                           │
        │  every path FAIL-OPEN · candidates only ever shrink             │
        │                                                                 │
        │  audit.py — `neterse audit` CLI: coverage/opportunity report      │
        │  over (command, platform?, raw) corpora, incl. lossiness review │
        └────────────────────────────────┬────────────────────────────────┘
                                         ▼
                     consumer policy: smallest-wins, ledgers,
                     metrics, caching — deliberately NOT ours
```

Two tiers, one contract. The **data tier** scales by contribution — a new
table-shaped command family is a spec dict plus fixtures, no parser code.
The **code tier** is the honest escape hatch: some formats (NX-OS splits
interface state across two lines; banners need a skip-until-sentinel state
machine) cannot be expressed by a flat spec without inventing a bad
programming language in data. TextFSM already exists; we don't re-invent
it badly.

## The API contract (frozen)

```python
render(raw, *, command, platform=None, parsed=None, profile="default")
    -> list[Candidate]
optimize(command, raw) -> str          # == min(render(...)) or raw
register(pattern, *, platforms=None, dropped_fields=None)   # plugin hatch
iter_compressors() / iter_entries()    # registry views
```

* `platform` (active since 0.2.0): skip-filter over declared platform
  scopes. It can only ever *skip* entries, never force a match — omitting
  it is always safe. This is the false-match killer: an NX-OS table spec
  no longer claims Arista output when the caller says
  `platform="arista_eos"`.
* `parsed` (active since 0.3.0): rows already produced by Genie /
  ntc-templates / TTP / NAPALM / gNMI — a list of dicts (or one dict) —
  re-encoded header-once as two candidates, `parsed:csv` and
  `parsed:toon` (`method="parsed"`), independent of any registry match.
  Both are emitted every time; smallest-wins is the consumer's call
  (decision 10). Non-row-shaped input yields no candidates.
* `profile` (active since 0.3.0): named, *declared-lossy* projections
  (`updown` ships first: interface liveness only). Renderings under a
  non-default profile append an inline omission marker
  (`[omitted: … — re-query profile=full]`) so the model knows data was
  withheld and can recover; the omitted names join the candidate's
  manifest and `Candidate.profile` says what was applied. Entries that
  don't declare the requested profile render their complete default
  (decision 11); `full` is an alias of `default` (decision 12). The
  default profile stays complete-but-compact.

## Invariants (enforced, not aspirational)

1. **Fail-open everywhere.** Exception, non-string, empty, or
   non-shrinking result → no candidate. Raw is never lost, output never
   enlarged. Enforced in `render()`, re-tested per compressor.
2. **Zero runtime dependencies.** Stdlib only; CI asserts the installed
   dist metadata carries no runtime requirements. This is why specs are
   plain dicts — no YAML/TOML parser at runtime. An optional authoring
   front-end (YAML → dict) may land later as an extra, feeding the same
   engine.
3. **Candidates, not policy.** Winner selection, savings ledgers,
   metrics, caching, and delta re-query logic belong to consumers (dbcli
   keeps its smallest-wins seam, Prometheus counters, and per-run ledger).
4. **Declared lossiness.** Noise (separators, legends, repeated headers,
   all-zero rows kept visible via `(all zero)` markers) is dropped
   freely. Anything data-bearing a rendering omits is declared on the
   entry's `dropped_fields` manifest and surfaced on every candidate.
   Manifest vocabulary so far: real field names (`ok`, `method`,
   `holdtime`, `msgrcvd`…) plus structural drops (`hit_counters`,
   `all_zero_rows`, `banner_bodies`, `unmatched_lines`,
   `zero_valued_error_counters`).
5. **Byte-parity discipline.** `tests/legacy_snapshot.py` freezes the
   pre-extraction implementation. The parity suite replays a corpus
   cross-matrix (every command × every body, wrong pairings included)
   and pins today's outputs byte-for-byte on the default path. Engine
   refactors change *how*, never *what*; an intentional output change is
   a recorded baseline decision in this file.

## Plan

| Phase | Contents | Status |
|---|---|---|
| 0 | Extract from dbcli verbatim; freeze API (`render`/`Candidate`/`optimize`/`register`); parity baseline + cross-matrix suite; zero-dep packaging | ✅ shipped |
| 1 | Spec engine (generic strategies over dict specs); 9/15 families converted; platform-keyed dispatch; lossiness manifests on every entry | ✅ shipped (0.2.0) |
| 2 | **Parsed tier**: `parsed=` accepts pre-parsed rows → field projection + compact encoders (`parsed:csv` beats `json.dumps(rows)` by ~45–50%; `parsed:toon` adds the explicit row count); opt-in `profile=` projections with inline omission markers (`updown` ships first); `kv_extract` strategy moved `show version` to a spec (10 specs + 5 code) | ✅ shipped (0.3.0) |
| 3 | **Community launch**: `neterse audit` coverage CLI + parity replay ports, fixture-per-file layout (`tests/fixtures/<platform>/<family>/`), CI token-savings regression (pinned `o200k_base`, committed baseline, 35% floor), 9 new families across Arista EOS / Junos / Aruba AOS-CX / MikroTik, release workflow via PyPI Trusted Publishing | ✅ shipped (0.4.0) — publish tag is a maintainer action ([RELEASING.md](RELEASING.md)) |
| 4 | dbcli (and other consumers) swap their vendored copy for the pip dependency; propose a "TOON profile for network data" upstream to toon-format | ◐ dbcli cutover executed 2026-08-04 (dbcli@5598e204: incubator + vendored tests deleted, shim kept, `neterse` commit-pinned as a git dependency — [CONSUMER-HANDOFF.md](CONSUMER-HANDOFF.md) §6); remaining: first PyPI publish, flip dbcli's pin to `neterse>=0.4`, toon-format proposal |

The inputs each of those phases needs from the consumer side — the seam
neterse plugs into, the parsed-tier acceptance test, the audit-tool port
spec, measurement conventions, field notes, and the cutover checklist —
are carried in **[CONSUMER-HANDOFF.md](CONSUMER-HANDOFF.md)** (§2, §2,
§4, §3, §5, §6 respectively). Read it before starting Phase 3; it exists
so this repository never has to reach back into dbcli. The Phase-2
acceptance rule from §2 — beat `json.dumps(rows)` on multi-row output or
don't ship the tier — is pinned permanently in `tests/test_parsed.py`.

### Why the parsed tier is the coverage unlock

Per-command raw compressors re-do work the parsing ecosystems finished
years ago. ntc-templates and Genie ship thousands of per-vendor/command
parsers; once output is *structured*, minimum-token rendering is a
generic transform (project fields → header-once table). One good encoder
instantly covers every command those parsers handle, across vendors,
with zero per-command work here. The raw tier then serves the
unparseable tail — piped/filtered commands, platforms without templates,
and outputs where parsed JSON is *bigger* than compressed raw (common:
JSON repeats keys per row). Both tiers emit candidates; the consumer's
smallest-wins picks per call. This is why neterse complements rather than
competes with the parser projects.

## Decision log

| # | Decision | Rationale |
|---|---|---|
| 1 | Name: repo/import `terse`, distribution `terse-net` | PyPI `terse` is squatted by an abandoned 2019 package; PEP 541 transfer is a later option. "TOON"-adjacent names rejected — toon-format owns that word. **Superseded by decision 23.** |
| 2 | Apache-2.0 | Parity with the ecosystem we lean on (ntc-templates, pyATS); patent grant. Swappable until the first external contribution. |
| 3 | Specs are plain Python dicts, not YAML | Zero-dep invariant beats authoring aesthetics. A YAML front-end can compile to dicts later as an optional extra without touching the engine. |
| 4 | Code tier is a feature, not debt | Stateful formats expressed "declaratively" just re-invent TextFSM in worse syntax. The escape hatch keeps specs honest and small. |
| 5 | Platform filter can only skip, never force | Fail-open: a wrong/unknown platform string degrades to "try everything", never to "lose data". Declare scopes broadly. |
| 6 | Manifests are metadata in Phase 1; inline markers wait for profiles | Appending marker text today would break byte-parity with the baseline for zero consumer benefit; markers become meaningful when opt-in lossy profiles exist. |
| 7 | Canonical registry order frozen to the legacy sequence | Winner ties (equal-length candidates) resolve to the first entry; frozen order makes byte-parity unconditional instead of probabilistic. |
| 8 | Tokenizers are CI-only, never runtime | `est_tokens()` is chars/4 by convention (matches dbcli's metric). Real tokenizer savings-regression lands in Phase 3 CI. |
| 9 | Baseline corpus lives in `tests/corpus.py` as strings | One import, no I/O in unit tests. File-per-fixture layout arrives with the Phase-3 contribution flow and the audit tool that generates them. |
| 10 | Parsed tier always emits BOTH `parsed:csv` and `parsed:toon` | CSV is nearly always smaller on flat tables; TOON's explicit `[N]` row count lets a policy detect truncation. Choosing between size and self-describing structure is policy — invariant 3 says that's the consumer's call, so both candidates ship every time. |
| 11 | Profile fallback is the complete default rendering, not a skip | An entry that doesn't declare the requested profile renders in full. Skipping would turn a profile request into data loss on uncovered families — the exact failure mode fail-open exists to prevent. Corollary: an unknown profile string behaves as `default` everywhere. |
| 12 | `full` is an alias of `default` | The omission marker tells the model `re-query profile=full`; that spelling must actually work. Aliasing beats renaming the default (which would move bytes) and beats a marker pointing at a profile that doesn't exist. |
| 13 | `show version` conversion may change `Candidate.source`, never text | Byte-parity governs rendering text; entry names are consumer-visible telemetry, not payload. `_compress_version` → `spec:cisco/show_version` is the recorded precedent. |
| 14 | Parsed-tier profiles project by field-NAME pattern | Parser schemas differ per ecosystem (ntc: `intf`/`status`; Genie: `oper_state`…), so a name-pattern table is the only command-independent way to project. A profile whose patterns keep nothing (or everything) falls back to complete — it never guesses. |
| 15 | The parity cross-matrix is CLOSED at the legacy corpus | Post-baseline families (Phase 3+) can't be byte-compared against a snapshot that predates them. They are covered behaviorally instead (diagonal shrink, winner-is-own-spec, wrong-platform skip, fail-open matrix through neterse itself), register strictly AFTER the legacy sequence, and the legacy matrix automatically polices that they never change a legacy pair's result — identical-output ties are permitted and resolve to the earlier (baseline) entry. |
| 16 | Fixture layout: `tests/fixtures/<platform>/<family>/commands.txt` + `raw.txt` | Byte-exact raw bodies (fixed-width offsets are data), reviewable diffs, platform carried by the path, and the audit CLI ingests the same tree — one layout for contribution, testing, and coverage measurement. The in-module `corpus.py` stays as the frozen legacy baseline set (decision 9). |
| 17 | The audit CLI ships in the package; the parity replay does not | `neterse audit` needs only the public registry — it is the consumer-facing coverage story (`neterse audit run.jsonl`). The replay compares against `tests/legacy_snapshot.py`, a repo artifact deliberately excluded from the wheel, so it lives in `scripts/`. |
| 18 | Token regression: pinned tokenizer, committed baseline, 35% aggregate floor | CI measures the actual claim (tokens under `o200k_base`, `tiktoken==0.13.0`) per family against `tests/token_savings_baseline.json`; regeneration is a recorded decision. Runtime keeps chars/4 (decision 8) — the tokenizer never becomes a dependency. |
| 19 | `fixed_width_table` grows a `row_match` spec key | Arista (`Et1`) and Aruba (`1/1/1`) port names don't fit the shared Cisco interface-name pattern. A per-spec row matcher keeps the strategy generic; the DEFAULT stays the Cisco pattern so every legacy rendering is untouched. |
| 20 | **Baseline change** — `cisco/show_ip_route` rewritten for faithfulness | Live-lab verification (containerlab cisco_iol r1–r4, IOS 17.12.1, 2026-08-03) proved the legacy regex silently dropped EVERY two-token-code route (`O IA`, `O E2`, `D EX`, …— 9 of 19 routes on r1, i.e. all learned routes on an OSPF lab), rendered the literal `is` as the interface of connected routes, and leaked route-age tokens into the next-hop/interface columns — all while declaring `()` lossless. Invariant 4 outranks invariant 5: the family diverges from the frozen snapshot via the parity suite's `INTENTIONAL_DIVERGENCES` registry, its new output is pinned by goldens on the legacy fixture and the real capture, and the remaining drops are declared (`route_age`, `ecmp_alternate_paths`, `subnet_group_headers`). Real captures live in `tests/fixtures/cisco_ios/`. |
| 21 | `cisco_ios/show_ip_interface_brief` status regex made admin-down-aware | Same verification: `administratively down` split across the status AND protocol columns, and the true protocol column was never read. Fix is additive (`(?:administratively )?`) — byte-identical on the frozen corpus, so no parity exemption needed; behavior on real bodies is pinned by the real-capture golden. |
| 22 | `updown` parsed-tier status patterns widened (`protocol_status`, `oper_status`, `admin_status`) | Parsed-tier verification against r1 with the actual parser stack (netmiko + ntc-templates/TextFSM, 2026-08-03): ntc's `show interfaces` schema names the line-protocol field `protocol_status`, which the status patterns missed — so the interface-LIVENESS profile projected the line-protocol state away (declared in the manifest, hence not silent loss, but semantically self-defeating). The docstring's own goal ("must hit ntc-templates, Genie and NAPALM spellings alike") decides it: the `_status` spellings join the `_state` ones. Additive — profiles are post-baseline (decision 15) and the default path is untouched; pinned in `test_profiles.py` on the real ntc field names. Same verification confirmed the tier end-to-end on 12 live families: cell-for-cell CSV faithfulness (independently decoded), TOON row counts, shrink-gate honesty (`show clock` correctly gated out), string-typed `parsed` declining cleanly, and parsed-tier coverage of all five raw-tier gap families (ospf database 65%, cdp detail 70%, interfaces description 69%). |
| 23 | **Renamed to `neterse`** ("network terse") — distribution, import, and CLI all share the name | Supersedes decision 1's split naming (`terse` import / `terse-net` distribution): PyPI `terse` is squatted, `neterse` was verified free (2026-08-03), and one matching name beats both the split and a PEP 541 gamble. Renamed before the first publish, so no compatibility shim is owed. Out of scope on purpose: the frozen `tests/legacy_snapshot.py` (its docstring's "terse" is historical fact), and the Junos `show interfaces terse` family, whose name derives from the device command. |
| 24 | **Baseline change** — `cisco/show_ip_bgp_summary` reads the real AS column | BGP-lab verification (r1–r3, 2026-08-03): the legacy regex captured the first number after the neighbor IP — the V column (BGP version, constant 4) — under the `as` header, silently dropping the real AS; on the lab, the eBGP neighbor (AS 100) was indistinguishable from the iBGP ones (AS 200), and the legacy fixture itself proves it (AS 65001 and 65002 both rendered `4`). The regex now skips V and captures AS; `version` joins the declared drops. Parity-exempt via `INTENTIONAL_DIVERGENCES` (like decision 20), pinned by goldens on the legacy fixture and the real r2 capture (`tests/fixtures/cisco_ios/show_ip_bgp_summary/`); token baseline regenerated (38 families, 44.0%). |
| 25 | **IOS cdp table covered; legacy cdp row-matching anchored to column 0** | Live-lab gap (bgp_fundamentals r1–r3, 2026-08-04): IOS `show cdp neighbors` is a fixed-width table whose values carry spaces (`Eth 0/2`, `Linux Uni`), so the legacy line-regex entry fails open and the family reached the model raw (547–623 chars/call). New `cisco_ios/show_cdp_neighbors` fixed-width spec (keyed on the IOS `Holdtme` header spelling vs NX-OS `Hldtme`, so the entries never compete), engine key `first_col_wraps` re-joins IOS's wrapped long device IDs, and `row_match` generalizes to single-token first columns. Fixing the wrap exposed a smallest-wins hazard: the legacy entry's stripped-line matching false-matched INDENTED lines (wrapped-ID continuations; NX-OS interface-detail counter lines in the parity cross-matrix) into corrupt rows that can be SMALLER than the faithful rendering — corruption must not be able to win, so the legacy entry gains `unindented_rows_only` (data rows start at column 0 on every platform it knows). On-format output is byte-identical (pinned by golden in test_cisco_real_captures.py); the command family is parity-exempt via `INTENTIONAL_DIVERGENCES`. Token baseline regenerated (39 families, 43.9%). |
| 26 | **`show ip protocols` as a post-baseline CODE compressor** | Live-lab gap (bgp_fundamentals r1–r3, 2026-08-04): 996–1557 chars/call reached the model raw. The output is block-structured (one `Routing Protocol is …` block per process) — no table strategy fits, and inventing a generic block strategy for one family is speculative generality; the registry's code tier exists precisely for stateful formats. Faithfulness contract: known boilerplate → key=value, list sections join items, and every UNRECOGNIZED line is preserved verbatim (whitespace-collapsed) — drift degrades compression, never data. Declared drops: empty list sections, static sub-table column headers. Test citizenship: the family lives in the fixture tree so the shrink diagonal, cross-matrix, audit smoke and token gate all cover it; `CODE_FAMILY_WINNERS` in test_fixture_corpus.py declares its expected winner (the winner test's `spec:` requirement was a proxy for "the family's own entry", not a spec-only rule). Not in the parity matrix (post-baseline command). 56–61% on the lab captures; token baseline regenerated (40 families, 43.7%). |

## Provenance

neterse began as dbcli's TOON optimizer ("Token-Optimized Output for
Networks", `dbcli/services/token_optimizer.py`, inspired by NetClaw's
TOON serialization work) and was extracted in two recorded steps: Phase 0
froze the API and proved byte-equivalence against the in-tree
implementation; this repository's `tests/legacy_snapshot.py` is that
frozen module and remains the standing acceptance baseline.

dbcli vendored the **Phase-0** copy (`dbcli/_incubator/showbrief`, 0.1.0)
until 2026-08-04, when it executed the Phase-4 cutover exactly as
[CONSUMER-HANDOFF.md](CONSUMER-HANDOFF.md) §6 prescribed (dbcli@5598e204):
the incubator and its vendored test suites are deleted, the
`dbcli/services/token_optimizer.py` shim remains as the import path every
call site uses — now re-exporting this package — and `neterse` is a
commit-pinned git dependency in dbcli's requirements until the first PyPI
release (then `neterse>=0.4`). The bet that the swap would need no
re-baselining held: the default path stayed byte-identical to the shared
baseline throughout Phases 1–3, apart from the recorded divergences
(decisions 20, 24, 25), each pinned by its own goldens. The pre-cutover
divergence detail in [CONSUMER-HANDOFF.md](CONSUMER-HANDOFF.md) §1 is
retained as history.
