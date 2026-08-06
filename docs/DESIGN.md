# neterse — design, topology, and plan

*Status: 0.5.0 cut, phase 8 opened — Phase 6 (spec-compliant TOON and GCF
generic-profile interop candidates in the parsed tier) plus the
`neterse.normalizers` seam, nested-collection sections, and delegation to
the spec authors' own encoders behind the `gcf`/`toon` extras
(decision 36), the capability set now installable as one `neterse[all]`
(decision 37). Phase 8's MCP surface has landed: `neterse.mcp` — the
`neterse-mcp` proxy and `CompactMiddleware` behind the `mcp` extra
(decision 38). Published on PyPI through 0.4.1; each version's publish
awaits the maintainer's tag (docs/RELEASING.md).
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
                       consumer (NetClaw, your agent, …)
                                        │ raw CLI text, command,
                                        │ platform?, parsed rows?, profile?
                                        ▼
        ┌───────────────────────────── neterse ─────────────────────────────┐
        │                                                                 │
        │  registry.py — ONE canonical-order list of Entry:               │
        │    (command pattern, fn, platform scope?, dropped_fields?)      │
        │                                                                 │
        │  ┌── data tier ─────────────────┐  ┌── code tier ─────────────┐ │
        │  │ specs/<vendor>/<family>.yaml │  │ _compressors.py: hand-   │ │
        │  │ (authoring) → compiled by    │  │ written functions for    │ │
        │  │ scripts/compile_specs.py     │  │ genuinely stateful       │ │
        │  │ into specs/_compiled.py      │  │ formats (multi-line      │ │
        │  │ engine.py: generic           │  │ blocks, banner state     │ │
        │  │ strategies compile specs     │  │ machines, multi-table    │ │
        │  │ into compressors             │  │ zero-row suppression)    │ │
        │  │  · line_regex_table          │  │                          │ │
        │  │  · fixed_width_table         │  │                          │ │
        │  │  · kv_extract                │  │                          │ │
        │  │  + named profile projections │  │                          │ │
        │  └──────────────────────────────┘  └──────────────────────────┘ │
        │  ┌── parsed tier ──────────────────────────────────────────────┐│
        │  │ parsed.py: rows Genie/ntc-templates/TTP/NAPALM already      ││
        │  │ produced → header-once encoders (parsed:csv, spec-conform-  ││
        │  │ ing parsed:toon/parsed:gcf, parsed:sections); command-      ││
        │  │ independent; profiles by field.                             ││
        │  │ normalizers/<vendor>.py: vendor/API envelopes (ACI imdata,  ││
        │  │ SD-WAN, Meraki, …) → canonical rows BEFORE encoding, so     ││
        │  │ parsed.py stays vendor-agnostic (register_normalizer hatch).││
        │  │ ntc.py (extra: neterse[textfsm]) drives ntc-templates       ││
        │  │ itself: parse + render in one call, fail-open without it.   ││
        │  │ compact(): ONE front door for conns/responses/raw/rows —    ││
        │  │ sources.py adapters translate foreign response objects      ││
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
table-shaped command family is one YAML spec file plus fixtures, no
parser code and no registry edit.
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

# rows-only (already-parsed output, no raw text in hand) — decision 30:
render_parsed(parsed, *, profile="default") -> list[Candidate]
optimize_parsed(parsed, *, profile="default") -> str   # min or compact JSON

# optional extra (pip install neterse[textfsm]) — decision 29:
neterse.ntc.parse(raw, *, command, platform) -> list[dict] | None
neterse.ntc.render(raw, *, command, platform, profile="default")
neterse.ntc.optimize(command, raw, *, platform) -> str

# the universal front door — decision 32: ONE verb, dispatch on shape;
# source = connection | response object | raw str | parsed rows:
compact(source, command=None, *, platform=None, profile="default", **run_kw)
    -> str
neterse.sources.register_adapter(fn)   # future response objects plug in here
neterse.normalizers.register_normalizer(fn)  # future vendor/API shapes plug in here
```

* `platform`: skip-filter over declared platform
  scopes. It can only ever *skip* entries, never force a match — omitting
  it is always safe. This is the false-match killer: an NX-OS table spec
  no longer claims Arista output when the caller says
  `platform="arista_eos"`.
* `parsed`: rows already produced by Genie /
  ntc-templates / TTP / NAPALM / gNMI — a list of dicts (or one dict) —
  re-encoded header-once (`method="parsed"`), independent of any
  registry match. `parsed:csv` is emitted whenever the input is
  row-shaped; the spec-compliant `parsed:toon` and `parsed:gcf` are
  emitted only when a *conforming* document can represent those rows and
  DECLINE otherwise (decision 35) — with the `gcf`/`toon` extras
  installed, the spec authors' own encoders then cover much of what we
  decline, above all a row list wrapped in a key
  (`employees[3]{…}`, decision 36); `parsed:sections` covers mixed
  tool/API responses. Whichever are emitted, smallest-wins is the
  consumer's call (decision 10). Non-row-shaped input yields no
  candidates.
* `profile`: named, *declared-lossy* projections
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
   dist metadata carries no runtime requirements. Specs are AUTHORED as
   YAML (`neterse/specs/<vendor>/<family>.yaml`) but COMPILED at
   development time into the generated, committed
   `specs/_compiled.py` the runtime imports — no YAML parser at import
   time, ever (decision 27; PyYAML lives in the `test` extra,
   ntc-templates in the `textfsm` extra).
3. **Candidates, not policy.** Winner selection, savings ledgers,
   metrics, caching, and delta re-query logic belong to consumers (a
   consumer keeps its own smallest-wins seam, metrics counters, and
   per-run ledger).
4. **Declared lossiness.** Noise (separators, legends, repeated headers,
   all-zero rows kept visible via `(all zero)` markers) is dropped
   freely. Anything data-bearing a rendering omits is declared on the
   entry's `dropped_fields` manifest and surfaced on every candidate.
   Manifest vocabulary so far: real field names (`ok`, `method`,
   `holdtime`, `msgrcvd`…) plus structural drops (`hit_counters`,
   `all_zero_rows`, `banner_bodies`, `unmatched_lines`,
   `zero_valued_error_counters`).
5. **Byte-parity discipline.** `tests/legacy_snapshot.py` freezes the
   original implementation. The parity suite replays a corpus
   cross-matrix (every command × every body, wrong pairings included)
   and pins today's outputs byte-for-byte on the default path. Engine
   refactors change *how*, never *what*; an intentional output change is
   a recorded baseline decision in this file.

## Plan

| Phase | Contents | Status |
|---|---|---|
| 0 | Freeze API (`render`/`Candidate`/`optimize`/`register`); parity baseline + cross-matrix suite; zero-dep packaging | ✅ shipped |
| 1 | Spec engine (generic strategies over dict specs); 9/15 families converted; platform-keyed dispatch; lossiness manifests on every entry | ✅ shipped |
| 2 | **Parsed tier**: `parsed=` accepts pre-parsed rows → field projection + compact encoders (`parsed:csv` beats `json.dumps(rows)` by ~45–50%; `parsed:toon` adds the explicit row count); opt-in `profile=` projections with inline omission markers (`updown` ships first); `kv_extract` strategy moved `show version` to a spec (10 specs + 5 code) | ✅ shipped |
| 3 | **Community launch**: `neterse audit` coverage CLI + parity replay ports, fixture-per-file layout (`tests/fixtures/<platform>/<family>/`), CI token-savings regression (pinned `o200k_base`, committed baseline, 35% floor), 9 new families across Arista EOS / Junos / Aruba AOS-CX / MikroTik, release workflow via PyPI Trusted Publishing | ✅ shipped (0.1.0) — publish tag is a maintainer action ([RELEASING.md](RELEASING.md)) |
| 4 | **Contributor scale-out**: YAML spec authoring — one `neterse/specs/<vendor>/<family>.yaml` per family, validated + compiled to the committed `_compiled.py` (decision 27, CI drift gate); registry self-append for unlisted specs (decision 28: a contribution is one YAML file + fixtures); `neterse.ntc` extra drives ntc-templates end-to-end (decision 29, `pip install neterse[textfsm]`) | ✅ shipped |
| 5 | **Runner integration**: the universal `compact(source, command=None, ...)` verb — shape dispatch over connections / response objects / raw text / parsed rows, with `neterse.sources` adapters as the extension point (decision 32, superseding decision 31's per-library modules); rows-only `render_parsed`/`optimize_parsed` gated against compact JSON (decision 30); the platform-spelling ladder in `ntc.parse` (netmiko `device_type`s, scrapli `textfsm_platform`s) | ✅ shipped |
| 6 | **Interop format candidates**: `parsed:toon` upgraded to spec-compliant TOON (SPEC.md 4.1 §9.3 — the `[N]{fields}` declarations double as truncation guardrails) and `parsed:gcf` added (GCF SPEC v3.4.1 generic profile — `-` null vs `~` absent, `parent>child` flattening); both decline rather than bend their spec (decision 35). Comprehension benchmarking considered alongside and dropped — smallest-wins already arbitrates empirically per payload | ✅ shipped |
| 7 | Consumers swap any vendored copy for the pip dependency; propose a "TOON profile for network data" upstream to toon-format | ◐ remaining: first PyPI publish, toon-format proposal |
| 8 | **Beyond the CLI**: the same candidates contract for other verbose-payload surfaces an agent reads — MCP tool results (including an MCP middleware that compacts any server's responses, the gcf-proxy-shaped adoption vector), REST/API responses, generic JSON documents. The parsed tier is the seam (structured rows are already command-independent); what's new is dispatch keyed on something other than a CLI command string | ◐ MCP surface shipped: `neterse.mcp` — `neterse-mcp` proxy + `CompactMiddleware` behind the `mcp` extra (decision 38); remaining: per-tool hints for raw-CLI results, REST/API responses, generic JSON documents |
| 9 | **Session/delta encoding**: a polling agent re-reads mostly-identical tables (`show interface status` every N minutes); rendering only what changed since the last render of the same command would dwarf every notation-level saving. Deliberately LAST: it is stateful and correctness-sensitive — it needs per-command-family row-key definitions (what identifies a row across polls) and extensive testing before any of it can ship; how commands declare their keys is an open design question | ▢ deferred by design |

The Phase-2 acceptance rule — beat `json.dumps(rows)` on multi-row output
or don't ship the tier — is pinned permanently in `tests/test_parsed.py`.

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
| 2 | Apache-2.0 | Parity with the ecosystem we lean on (ntc-templates, pyATS); patent grant. Swappable until the first external contribution. |
| 3 | Specs are plain Python dicts, not YAML | Zero-dep invariant beats authoring aesthetics. A YAML front-end can compile to dicts later as an optional extra without touching the engine. |
| 4 | Code tier is a feature, not debt | Stateful formats expressed "declaratively" just re-invent TextFSM in worse syntax. The escape hatch keeps specs honest and small. |
| 5 | Platform filter can only skip, never force | Fail-open: a wrong/unknown platform string degrades to "try everything", never to "lose data". Declare scopes broadly. |
| 6 | Manifests are metadata in Phase 1; inline markers wait for profiles | Appending marker text today would break byte-parity with the baseline for zero consumer benefit; markers become meaningful when opt-in lossy profiles exist. |
| 7 | Canonical registry order frozen to the legacy sequence | Winner ties (equal-length candidates) resolve to the first entry; frozen order makes byte-parity unconditional instead of probabilistic. |
| 8 | Tokenizers are CI-only, never runtime | `est_tokens()` is chars/4 by convention (matches the consumer-side ledger metric). Real tokenizer savings-regression lands in Phase 3 CI. |
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
| 24 | **Baseline change** — `cisco/show_ip_bgp_summary` reads the real AS column | BGP-lab verification (r1–r3, 2026-08-03): the legacy regex captured the first number after the neighbor IP — the V column (BGP version, constant 4) — under the `as` header, silently dropping the real AS; on the lab, the eBGP neighbor (AS 100) was indistinguishable from the iBGP ones (AS 200), and the legacy fixture itself proves it (AS 65001 and 65002 both rendered `4`). The regex now skips V and captures AS; `version` joins the declared drops. Parity-exempt via `INTENTIONAL_DIVERGENCES` (like decision 20), pinned by goldens on the legacy fixture and the real r2 capture (`tests/fixtures/cisco_ios/show_ip_bgp_summary/`); token baseline regenerated (38 families, 44.0%). |
| 25 | **IOS cdp table covered; legacy cdp row-matching anchored to column 0** | Live-lab gap (bgp_fundamentals r1–r3, 2026-08-04): IOS `show cdp neighbors` is a fixed-width table whose values carry spaces (`Eth 0/2`, `Linux Uni`), so the legacy line-regex entry fails open and the family reached the model raw (547–623 chars/call). New `cisco_ios/show_cdp_neighbors` fixed-width spec (keyed on the IOS `Holdtme` header spelling vs NX-OS `Hldtme`, so the entries never compete), engine key `first_col_wraps` re-joins IOS's wrapped long device IDs, and `row_match` generalizes to single-token first columns. Fixing the wrap exposed a smallest-wins hazard: the legacy entry's stripped-line matching false-matched INDENTED lines (wrapped-ID continuations; NX-OS interface-detail counter lines in the parity cross-matrix) into corrupt rows that can be SMALLER than the faithful rendering — corruption must not be able to win, so the legacy entry gains `unindented_rows_only` (data rows start at column 0 on every platform it knows). On-format output is byte-identical (pinned by golden in test_cisco_real_captures.py); the command family is parity-exempt via `INTENTIONAL_DIVERGENCES`. Token baseline regenerated (39 families, 43.9%). |
| 26 | **`show ip protocols` as a post-baseline CODE compressor** | Live-lab gap (bgp_fundamentals r1–r3, 2026-08-04): 996–1557 chars/call reached the model raw. The output is block-structured (one `Routing Protocol is …` block per process) — no table strategy fits, and inventing a generic block strategy for one family is speculative generality; the registry's code tier exists precisely for stateful formats. Faithfulness contract: known boilerplate → key=value, list sections join items, and every UNRECOGNIZED line is preserved verbatim (whitespace-collapsed) — drift degrades compression, never data. Declared drops: empty list sections, static sub-table column headers. Test citizenship: the family lives in the fixture tree so the shrink diagonal, cross-matrix, audit smoke and token gate all cover it; `CODE_FAMILY_WINNERS` in test_fixture_corpus.py declares its expected winner (the winner test's `spec:` requirement was a proxy for "the family's own entry", not a spec-only rule). Not in the parity matrix (post-baseline command). 56–61% on the lab captures; token baseline regenerated (40 families, 43.7%). |
| 27 | **YAML authoring front-end — compiled at development time, never parsed at runtime** | The front-end decision 3 deferred, landed on the compile side: specs are authored as one YAML file per command family (`neterse/specs/<vendor>/<family>.yaml`, the vendor/command layout ntc-templates made familiar; the id IS the path), and `scripts/compile_specs.py` validates them loudly (regexes must compile, header arity must match captured groups / keywords, profiles must keep real columns and drop at least one, `dropped_fields` is mandatory, unknown keys rejected) and emits the deterministic, committed `neterse/specs/_compiled.py` the runtime imports. Zero-dep invariant intact — PyYAML lives in the `test` extra only. Drift between sources and the generated module fails CI (`--check`) and the suite (`test_specs_yaml.py`), the same regenerate-and-commit flow as the token baseline (decision 18). Migration held byte-parity: the compiled dicts are deep-equal to the retired `specs.py` (sole exception: `show_ip_route`'s VERBOSE row reformatted as a block scalar — whitespace/comment changes a VERBOSE pattern ignores; the parity suite pins output). Regex authoring rule: single-quoted scalars or `\|-` blocks — YAML double quotes reject `\s`, loudly. |
| 28 | **Unlisted specs self-append after the canonical order** | Contributing a family used to mean editing `specs.py` AND `registry.py`. The explicit canonical list stays (tie-break order is load-bearing — decision 7), but every spec id absent from it now appends strictly AFTER the full sequence in sorted-id order: deterministic without a registry edit, ties still resolve to the earlier entries, and post-baseline discipline (decision 15) is preserved by construction. A contribution is now one YAML file plus fixtures; the explicit list remains the override when a position genuinely matters. |
| 29 | **`neterse.ntc`: optional ntc-templates front-end** (`pip install neterse[textfsm]`) | The parsed tier's thesis says the parsing ecosystems already did the per-command work — but the caller still had to run them. `neterse.ntc.parse/render/optimize` drive `ntc_templates.parse.parse_output` themselves (import is lazy, per call): with the extra installed, one call feeds TextFSM rows into `render(parsed=...)` and both tiers compete; without it — or when no template exists / the template doesn't match / the result isn't row-shaped — everything fails open to exactly the core behavior. The core package never imports it, so zero-dep holds; the tests fake the module rather than depend on it. |
| 30 | **Rows-only entry points: `render_parsed`/`optimize_parsed`, gated against compact JSON** | The runner libraries hand back ALREADY-parsed structures (netmiko `use_textfsm=True`, scrapli `textfsm_parse_output()`), leaving no raw string for the usual shrink gate. The honest competitor is what a consumer would otherwise put in context: `json.dumps(rows, separators=(",", ":"), default=str)` (the `default=str` matters — parser rows legitimately carry datetimes and address objects). Candidates must strictly undercut it; when nothing does — or the input isn't row-shaped — `optimize_parsed` returns that compact JSON itself, so the API never enlarges and never loses. Strings pass through untouched: netmiko's no-template fallback returns raw text, and JSON-quoting it would corrupt the one input every user eventually feeds this API (compact raw text with `optimize`). Truly unencodable input (circular refs) falls back to `repr`, the only faithful text left. |
| 31 | **Runner integrations are duck-typed and import nothing** | `neterse.netmiko` and `neterse.scrapli` read only the public attribute surface (`device_type` + `send_command`; `result`/`channel_input`/`textfsm_platform`/`textfsm_parse_output()`), so neither library is ever imported: zero-dep holds, the contract is testable with fakes instead of heavyweight dependencies, and any work-alike object is welcome. Platform flows from what the library already knows — netmiko's `device_type`, scrapli's `textfsm_platform` — feeding the raw-tier skip filter verbatim, while the netmiko-path ntc-templates keying tries what actually resolves: the suffix-stripped spelling first (`_ssh`/`_telnet`/`_serial` — strictly better than netmiko's own verbatim keying for telnet users), the verbatim `device_type` second (ntc-templates keys every WLC template on `cisco_wlc_ssh` itself), and netmiko's documented `cisco_xe` → `cisco_ios` retry last (ntc-templates ships zero `cisco_xe` templates). Every failure mode degrades stepwise: parsed tier drops out, then raw tier, then the device output returns unchanged. Verified against the real libraries locally (real ntc-templates parses of fixture captures; a real constructed `scrapli.response.Response`); CI stays on the fakes. |
| 32 | **One verb: `compact(source, command=None, ...)` — shape dispatch; per-library modules retired before ever shipping** | Decision 31's `neterse.netmiko`/`neterse.scrapli` created one name per library — exactly the surface that cannot scale to NAPALM, nornir, or whatever comes next. The duck-typing rationale survives; the NAMES collapse into a single front door: strings are raw CLI text, list/dict structures are parsed rows, anything with `send_command` is a connection to run (extra kwargs pass through to the library call; misuse raises `TypeError` — there is no data to fail open with), and response objects are translated by small adapters (`neterse.sources`; the scrapli `Response` shape ships in the box, and `register_adapter` is the extension point — a future library is an adapter, never a new API name). Library knowledge migrated to the seams where it is generic: the platform-spelling ladder (transport-suffix strip, verbatim `cisco_wlc_ssh`, `cisco_xe`/`cisco_iosxe` → `cisco_ios`, `cisco_iosxr` → `cisco_xr`) moved into `ntc.parse` and is verified against the real ntc-templates index — the load-bearing remap is netmiko's own `cisco_xe` → `cisco_ios` retry (raw ntc genuinely rejects `cisco_xe`); the `iosxe`/`iosxr` remaps are defensive, since current ntc resolves those spellings itself via CliTable's regex platform matching (verified empirically). The compact() raw path also gives OUR ntc front-end a second chance whenever a response object's own parse yielded nothing. NAPALM needs no adapter at all: its getters return plain structures, which are already the rows path. Removed while unreleased — no deprecation debt. |
| 33 | **Vendor/API payload shapes live in `neterse/normalizers/`, one module per style — never inside the parsed tier** | The parsed tier's thesis is that it is vendor-AGNOSTIC: once output is rows, header-once encoding is a generic transform. But controller APIs don't hand back rows — they hand back a vendor *envelope* (Cisco ACI wraps every object as `{class: {attributes: {...}}}` under `imdata`; SD-WAN, Meraki, DNAC each differ, and the shape drifts between API versions). The first ACI support inlined that unwrapping straight into `parsed.py`, which would force every future vendor to accrete there — the exact coupling decision 32 removed one level up for response objects. So the same seam is applied here: a *normalizer* is `Callable[[Any], Optional[list[dict]]]` — receive a decoded structure, return canonical rows (non-empty list of str-keyed dicts) or `None` for "not mine" (raising = "not mine", fail-open). `neterse.normalizers.normalize` tries them in order and `register_normalizer` inserts custom ones ahead of the built-ins (so out-of-tree vendors AND per-version overrides win without editing the tree). Built-ins ship one file per style: `_generic.py` (the vendor-neutral `{name: {...}}` keyed-dict NAPALM/OpenConfig return) and `cisco_aci.py` (the `imdata` object style). `parsed.py` calls `normalize()` and knows nothing else; `_rows`/`_section_lines`/`_encode_sections` are unchanged in behavior (the extraction is byte-identical on the ACI captures: node-status 44.4%, triage 32.9% chars; 29.1%/25.6% tokens under `o200k_base`). Contributing a vendor is one module in `neterse/normalizers/`, one line in its `NORMALIZERS` list, and a case in `tests/test_normalizers.py` — the CONTRIBUTING.md path mirrors the specs one. Stdlib only; zero-dep holds. |
| 34 | **`parsed:sections` tabulates nested row-collections recursively (subtree responses)** | Validation of the broader ACI MCP tool surface (2026-08-05, live fabric) found the common shapes shrink 25–50% under `o200k_base` (flat tables, raw `imdata`, capacity's category-keyed sub-lists, mixed triage reports), but ONE class passed through at 0%: subtree responses (`class_query(include_children=True)`/`include_faults`, `dn_query` subtrees, `faults_detailed`), where every object carries a heterogeneous `_children`/`_faults` list. The flat encoders JSON-blob that list into one quoted cell, which is LARGER than compact JSON, so the shrink gate correctly rejected it — no data lost, but no help either. Fix stays in the sections encoder and stays vendor-agnostic: a cell whose value `neterse.normalizers.normalize` claims (an ACI `_children` list of wrapped MOs, a keyed sub-map — anything a normalizer recognizes) is a table in disguise, so `_table_lines` renders it as an indented sub-table under each row, recursively, instead of blobbing it. Rows with no such nesting fall through to `_table_csv` byte-for-byte, so the 6 already-good shapes are unchanged (re-benchmarked identical); the subtree case goes 0% → 38.2% chars / 27.3% tokens (5475 → 3978 tok on the 6-EPG `include_children` capture). `operations_summary`-style help dicts (string-lists already at minimal JSON) still return unchanged — correct fail-open, not a defect. Pinned in `tests/test_parsed_only.py`. |
| 35 | **Spec-compliant interop candidates: `parsed:toon` (TOON 4.1 §9.3) and `parsed:gcf` (GCF v3.4.1 generic profile) — conformance beats coverage** | Survey of the token-format ecosystem (2026-08-05: toon-format SPEC.md 4.1, blackwell-systems GCF SPEC v3.4.1) reframed the competition: TOON and GCF are wire formats, neterse is the layer that removes semantic noise and emits *candidates* — so the right move is to EMIT their formats, not fight them. `parsed:toon` sheds its "TOON-style, spec compliance later" caveat: real §9.3 eligibility (identical key sets, no array/empty-object cells), `null`/`true`/`false` literals, delimiter-aware JSON-grammar quoting (numeric-lookalike strings — TextFSM's entire output — quote to survive decoding as strings), canonical number form, nested-uniform columns folded into `field{sub}` header groups. `parsed:gcf` lands beside it: the required `GCF profile=generic` preamble, `## [N]{fields}` section header, pipe rows, `-` null vs `~` field-absent (the one place GCF is MORE faithful than our CSV, which conflates the two as an empty cell), nested-uniform dicts flattened to quoted `parent>child` path columns (§7.4.6's strict preconditions). The binding rule both share: anything a conforming document cannot represent DECLINES the candidate instead of bending the spec — array cells, non-uniform nesting, and applied profile projections (TOON encoders may emit neither comments nor trailing content, so the omission marker has no in-document home; an undeclared drop would violate invariant 4 — lossy renderings stay CSV's business). Neither typically wins smallest (CSV undercuts both on flat tables; the gate keeps them honest) — they exist because candidates-not-policy says the CONSUMER may value `[N]` truncation guardrails or GCF-ecosystem interop above minimum bytes. Verified against the reference implementations locally (re-verified 2026-08-06; CI stays dependency-free): every TOON document decodes in `@toon-format/toon` 4.1.1 STRICT mode and every GCF document in `@blackwell-systems/gcf` 2.4.0, both round-tripping exactly across a dict/JSON/API corpus and 1900 randomized row-sets. Both formats also ship official Python implementations — PyPI `gcf-python` 2.4.0 (`blackwell-systems/gcf-python`, MIT, zero-dep, exports `encode_generic`/`decode_generic`) and `toon-format` — so conformance is checkable in-process without a Node hop; a note here previously claimed GCF had no Python package and withdrew the original `gcf-python 2.4.0` verification claim, which was an error (PyPI `gcf` is an unrelated project; the package is named `gcf-python`). Output is byte-identical to both projects' own encoders modulo their trailing newline, with two cosmetic divergences that round-trip either way (unquoted commas where GCF quotes; `1e21` vs their `1e+21`). That differential pass also caught a real defect the unit tests could not: a GCF cell beginning with `##` in column 1 forged a section header and broke the document's declared row count — silent, and reachable from `## CORE UPLINK ##`-style descriptions. Fixed by quoting a leading `#` (what the reference `needsQuote()` does); the lesson is that conformance claims need the vendor's own decoder in the loop, not our reading of the spec. Weighed and dropped alongside: comprehension benchmarking (smallest-wins arbitrates per payload empirically); session/delta encoding deferred to phase 9 (stateful, needs per-command row keys — see plan). |
| 36 | **The spec authors' own encoders as optional extras (`neterse[gcf]`, `neterse[toon]`) — supplement, never replace** | Decision 35 re-implemented both specs in stdlib, and re-implementing means implementing only the forms we thought to write: the ANONYMOUS root table. Both specs also define a NAMED one, so `{"employees": [...]}` — a single row whose one column holds an array, to the row model — produced no spec candidate at all, though the payload is as tabular as data gets. Every API response wraps its rows in a key, so this was the common case, not an edge. `gcf-python` and `toon-format` (both official, both zero-dep) are now consulted for any candidate we declined: named tables, whole envelopes (`totalCount="2"` beside `## imdata [2]{id}`), ragged rows, array cells — about half the shapes we refuse. SUPPLEMENT is the load-bearing word: the row model and the reference read a bare dict differently (one ROW vs an OBJECT — `[1]{hostname,os}:` vs `hostname: sw1`), so preferring the vendor would silently reshape the commonest input in the library, and there is nothing to win by it now that both agree byte-for-byte wherever both apply (4000 randomized row-sets, zero divergences — which required fixing three of ours: comma quoting, `-0`, `1e+21`). Installing an extra adds candidates; it never rewrites one. Delegated documents are VERIFIED, not trusted: both packages coerce rather than refuse (NaN and ±inf to `0`, unsupported types to `null` with a warning, ragged gaps materialized), so each is read back through that vendor's decoder and dropped unless it reproduces the payload — invariant 4 is not delegable. Shapes the tier declines outright (scalars, bare string lists) stay declined; widening `render_parsed`'s contract is its own decision. `dependencies = []` stands, and every failure path yields no candidate rather than an exception. |
| 37 | **`neterse[all]` (alias `neterse[full]`): one extra for the whole capability set, gated by a test** | Four optional extras is where "install what you need" turns into "go read the docs to find out what there is", and the fourth had no name at all — `tiktoken` was documented as a bare `pip install tiktoken` beside the package, so it is now the `tokens` extra (naming it changes nothing at runtime: `est_tokens()` stays chars/4 by decision 8 and the package imports no tokenizer). `all` is `textfsm,gcf,toon,tokens` — capabilities only; `test` (pytest, PyYAML) is for working ON neterse and stays out, which is the one judgement call here and is asserted rather than assumed. An aggregate extra is a hand-maintained copy of the extras list whose decay is SILENT — add an extra, forget to list it, and `[all]` still installs, just without it — so `tests/test_packaging.py` fails when a non-dev extra is unreachable from `all`, when `full` and `all` disagree, or when a `neterse[...]` self-reference names an extra that does not exist (pip only warns and skips). Self-reference is also what keeps the version floors singular: `test` requires `neterse[gcf,toon]` rather than restating `toon-format>=0.9.0b1`, so CI cannot test a version users do not resolve. `dependencies = []` is untouched — `[all]` installs nothing the library imports, and every extra stays fail-open, so the aggregate buys candidates and measurements, never a required package. |
| 38 | **MCP compaction lives at the client's config seam: the `neterse-mcp` stdio proxy, plus a FastMCP middleware for servers you author — never in the application** | Phase 8's placement question has three candidate homes, and two fail on ownership grounds. The application layer either already has the verb — an agent loop you own calls `compact()` on the result before it enters context, which phase 5 shipped — or cannot be modified at all (VS Code, Claude Code, Cursor). The server is editable only when you wrote it. The one seam the CONSUMER controls for every server regardless of author is the client's server config, so the shipping artifact is a proxy: `neterse-mcp <url-or-command>` speaks stdio to the host, forwards to the upstream (streamable-HTTP or stdio), and rewrites `tools/call` results on the way back — adoption is an edit to `mcp.json`, the gcf-proxy adoption vector as planned. One pure, stdlib-only seam under both surfaces: `compact_text` claims a text block only when it json-decodes to a CONTAINER (scalars re-encode to themselves; prose that happens to parse must never be touched), routes it through `compact()` (normalizers → parsed tier → smallest-wins), and replaces it only when strictly smaller than the original wire text — often pretty-printed, so the realized saving typically beats the compact-JSON gate (APIC-shaped fixtures: −68…75%). Everything else passes through byte-identical: non-JSON text (the raw tier is keyed on a CLI command string MCP does not carry — per-tool `{tool: (command, platform)}` hints are the recorded next step), JSON scalars, `isError` results, non-text blocks, and input schemas. `structuredContent` was initially left untouched and OPEN; the field answered within the day — FastMCP mirrors every tool return there, VS Code surfaces both copies, and the model read the 9.8 KB original beside the 3.5 KB compacted text, negating the saving — so the resolution is DEDUPE, on by default (`--keep-structured` opts out): a `{"result": <text>}` string mirror is rewritten with the compacted text (any string satisfies its schema), a copy that deep-equals what the compacted block decoded to is dropped, and anything carrying information of its own is never touched. Dropping obliged a matching listing change: the MCP server layer inside the proxy rejects any result whose tool declares `outputSchema` but returns no structured output (the low-level SDK validates against its `tools/list` cache, which is fed through the middleware chain), so while dedupe is on, listed tools shed `output_schema` — the proxy's honest contract is "the text block is the payload". That interaction was invisible to the in-memory suite (a bare `-> dict` tool gets no inferred schema in fastmcp 3) and surfaced only through the live proxy; the fixture now declares an explicit `output_schema`, the same lesson as decision 35's vendor-decoder differential: the enforcement path, not our reading of it, is the test. fastmcp (`>=3`, marker-gated to Python 3.10+ so `neterse[all]` still resolves on 3.9) is the `mcp` extra and powers only the adapters; `import neterse.mcp` works without it and `CompactMiddleware` names the missing extra at instantiation instead. The stdio upstream inherits the proxy's FULL environment: the host applied the config's `env` block to the proxy process, and the MCP SDK's default child env is a scrubbed allowlist that would starve a `docker run -e` upstream. Weighed and dropped: teaching `compact()` itself to sniff JSON strings (parity-safe — corpus raw text never json-decodes — but widening the one verb's contract is its own decision); compacting `resources/read` (same seam, later). |

## Provenance

neterse began as a TOON optimizer ("Token-Optimized Output for
Networks", inspired by NetClaw's TOON serialization work) built inside a
network agent, and was extracted into this standalone package: Phase 0
froze the API and proved byte-equivalence against that original
implementation; this repository's `tests/legacy_snapshot.py` is that
frozen module and remains the standing acceptance baseline.

The default path stayed byte-identical to that baseline throughout
Phases 1–3, apart from the recorded divergences (decisions 20, 24, 25),
each pinned by its own goldens.
