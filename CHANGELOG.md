# Changelog

## Unreleased

### Corrected: `gcf-python` exists, and the original claim was right

The 0.3.0 notes and decision 35 stated that GCF ships no Python
implementation, and on that basis withdrew the Phase 6 commit's
"verified against gcf-python 2.4.0". **That was wrong**, so the
withdrawal is itself withdrawn — the original claim stands.

PyPI **`gcf-python` 2.4.0** (MIT, zero dependencies, requires-python
`>=3.9`) comes from `blackwell-systems/gcf-python`, the same org that
publishes the spec, and exports `encode_generic` / `decode_generic`. The
error came from testing PyPI for the name `gcf` — an unrelated Gadio
scraper stuck at `0.0.3.dev3` — and concluding from one name miss that
nothing existed.

Re-verified against the real package: `parsed:gcf` is identical to
`encode_generic` output modulo its trailing newline, and
`decode_generic` round-trips our documents exactly, matching what the
npm package already showed.

TOON likewise now has an official Python package (`toon-format`, 0.1.0
with a 0.9.0b1 beta, from `toon-format/toon-python`). Practical
consequence: conformance for both formats can be checked in-process, so
the differential harness no longer needs a Node hop. Neither package
affects the runtime — `dependencies = []` is unchanged, and both remain
verification-time tooling only.

## 0.3.1 — 2026-08-06

Tooling only. `scripts/` ships in neither the wheel nor the sdist, so the
installed package is byte-identical to 0.3.0 apart from the version
string — nothing to gain by upgrading unless you work from a checkout.

### `scripts/neterse_report.py` explains itself again

- **`declines()` walked one level; the encoders recurse.** A dict column
  can be legal at the top level (present in every row, non-empty,
  uniform sub-keys) and still decline because one of its *own* values
  holds an array — `_toon_columns` and `_gcf_leaf_paths` both descend
  into folded columns, and the flat check did not. The diagnosis came
  back empty, so the report printed `not emitted:` with no reason under
  it: the one outcome the function exists to prevent. It now mirrors the
  recursion and names the full dotted path (`'data.imdata': array cell
  -> BOTH decline`).
- **`--key` reached only top-level keys.** API responses nest their rows
  two or three levels down, so the subtree that actually encodes was
  unreachable from the CLI. Dotted paths now work (`--key data.imdata`),
  and a bad path reports which level failed and what keys were there.
- **Envelopes name their own way out.** When both spec formats decline,
  the report scans for nested lists-of-dicts and prints them as ready-to-
  run `--key` paths. Pointing at a wrapper — `{endpoint, method, data:
  {totalCount, imdata: [...]}}` — makes neterse see one row of request
  metadata, which is not a table and never will be; the rows are real
  and one level down. That mistake looks exactly like a broken encoder.

## 0.3.0 — 2026-08-06

Minor, not patch: this release adds a public extension point
(`neterse.normalizers`) and a new candidate (`parsed:gcf`), and it
**changes the bytes of candidates that already shipped** —
`parsed:toon` became spec-compliant and now declines shapes 0.2.0
encoded, and `parsed:sections` tabulates nested collections it used to
JSON-blob. A consumer pinned to those exact renderings is affected;
`parsed:csv` and the whole raw-text tier are untouched.

### Spec-compliant interop candidates: TOON 4.1 and GCF v3.4.1 (decision 35)

- **`parsed:toon` is now real TOON** (toon-format SPEC.md 4.1, §9.3 root
  tabular form), not "TOON-style": strict eligibility (identical key
  sets, no array or empty-object cells), `null`/`true`/`false` literals,
  delimiter-aware JSON-grammar quoting — numeric-lookalike strings
  (TextFSM's entire output) quote so they decode back as strings —
  canonical number form, and nested-uniform columns folded into
  `field{sub,...}` header groups instead of JSON-blobbed cells.
- **New `parsed:gcf` candidate** (blackwell-systems GCF SPEC v3.4.1,
  generic profile): the required `GCF profile=generic` preamble,
  `## [N]{fields}` section header, pipe-delimited rows, `-` for null vs
  `~` for field-absent (a distinction our CSV's empty cell conflates),
  and nested-uniform dict columns flattened into quoted `parent>child`
  path columns under §7.4.6's strict preconditions.
- **Conformance beats coverage**: whatever a conforming document cannot
  represent DECLINES the candidate — array cells, non-uniform nesting,
  and applied profile projections (neither spec gives the omission
  marker an in-document home; TOON forbids encoder comments and
  trailing content outright), where previously `parsed:toon` emitted a
  pragmatic extension. Lossy projections stay CSV's business; CSV and
  `parsed:sections` are unchanged byte-for-byte, and `optimize_parsed`/
  `compact` winners are unaffected (CSV still undercuts both specs on
  flat tables — these candidates exist for consumer policies that value
  TOON's `[N]` truncation guardrails or GCF-ecosystem interop above
  minimum bytes).
- **Verified against the reference implementations locally** (CI stays
  dependency-free): every emitted TOON document decodes in
  `@toon-format/toon` 4.1.1 strict mode and every GCF document decodes
  in `@blackwell-systems/gcf` 2.4.0, both round-tripping exactly — over
  a corpus of dict/JSON/API shapes and 1900 randomized row-sets.
  Our output is byte-identical to both projects' own encoders modulo
  their trailing newline, with two known cosmetic divergences that
  round-trip either way: we leave commas unquoted where GCF quotes
  them, and emit `1e21` where both encoders emit `1e+21`.
- **Fixed: a `parsed:gcf` cell could forge a section header.** A row
  whose FIRST cell began with `##` emitted a line a conforming decoder
  reads as a new `## [N]{fields}` section, failing the document's own
  declared row count — reachable from real data (`## CORE UPLINK ##` is
  an interface-description idiom) and silent, since the candidate was
  handed on as faithful. A leading `#` now quotes, matching the
  reference encoder's `needsQuote()`. `parsed:toon` was never affected
  (it already quoted a leading `-`/`#`); regression-tested both ways in
  `tests/test_spec_formats.py`.
- Roadmap re-phased alongside (README/DESIGN): interop formats shipped
  as Phase 6, the MCP-middleware direction is Phase 8, and
  session/delta encoding is deliberately last as Phase 9 — stateful,
  needs per-command row-key definitions and extensive testing before
  any of it ships.

### Vendor/API payload shapes live in `neterse.normalizers` (decision 33)

- **New public extension point.** Controller APIs return a vendor
  *envelope*, not rows (Cisco ACI wraps every object as
  `{class: {attributes: {...}}}` under `imdata`; SD-WAN, Meraki and DNAC
  each differ, and shapes drift between API versions). That knowledge
  now lives in its own package instead of accreting inside the
  vendor-agnostic parsed tier — the same seam `neterse.sources` provides
  one level up for response objects.
- A **normalizer** is `Callable[[Any], Optional[list[dict]]]`: receive a
  decoded structure, return canonical rows or `None` for "not my shape"
  (raising also means "not mine"). `normalize()` tries them in order;
  **`neterse.normalizers.register_normalizer(fn)`** inserts custom ones
  ahead of the built-ins, so out-of-tree vendors *and* per-version
  overrides win without editing the tree.
- Built-ins ship one module per style: `_generic.keyed_dict` (the
  vendor-neutral `{name: {...}}` NAPALM/OpenConfig return) and
  `cisco_aci.class_attributes` (the `imdata` object style, class name
  kept as a leading `_class` column). `parsed.py` calls `normalize()`
  and names no vendor.
- Adding a vendor is one module plus one line in `NORMALIZERS` — see
  CONTRIBUTING. Extraction was byte-identical on the ACI captures.

### `parsed:sections` tabulates nested row-collections (decision 34)

- **Subtree responses stopped passing through at 0%.** ACI subtree
  shapes (`class_query` with `include_children`/`include_faults`,
  `dn_query` subtrees, `faults_detailed`) carry a heterogeneous
  `_children`/`_faults` list per object, which the flat encoders
  JSON-blobbed into a cell *larger* than compact JSON — so the shrink
  gate correctly rejected every candidate and the raw payload went to
  the model.
- A cell whose value `neterse.normalizers.normalize` claims is a table
  in disguise, so it now renders as an indented recursive sub-table
  under its row. Vendor-agnostic: the encoder asks what nests, it never
  names a vendor. Subtree captures go **0% → 38.2% chars / 27.3%
  tokens**.
- Rows with no such nesting fall through byte-for-byte, so already-good
  shapes are unchanged, and already-minimal JSON (help/summary dicts)
  still yields no candidate — correct fail-open.

### Packaging

- **Fixed: the 0.2.x wheel layout would have omitted
  `neterse.normalizers`.** The subpackage was added to the tree but
  never to pyproject's `[tool.setuptools] packages`, so it was absent
  from the built wheel — and since `parsed.py` imports it at module
  scope, plain `import neterse` raised `ImportError` in any clean
  install. Never published (0.2.0 predates the subpackage), and the
  release workflow's smoke test would have failed the build before
  PyPI, but it would have surfaced as a red tag.
- New `tests/test_packaging.py` checks the manifest against the tree on
  every commit: every subpackage under `neterse/` is declared, no
  declared package is stale, and the two version spellings stay in
  lockstep. The rest of the suite imports from the source checkout,
  where this whole class of error is invisible.

### Tooling

- **`scripts/neterse_report.py`** — every candidate for ONE payload:
  characters, `est_tokens()` beside a real `o200k_base` count, each
  rendering's declared lossiness, which one smallest-wins takes, the
  cheapest lossless alternative when that differs, and the column that
  made a spec format decline (those encoders are fail-open and
  otherwise silent). Reads JSON, stdin, or a raw capture; parses via
  ntc-templates when given `--command`/`--platform` so both tiers
  compete as `compact()` runs them. Lives in `scripts/`: it needs
  tiktoken and the tests' pinned encoding, neither of which the
  zero-dependency runtime may touch.

## 0.2.0 — 2026-08-05

### One verb across runner libraries: `neterse.compact` (decision 32)

- **`compact(source, command=None, *, platform=None, profile="default",
  **run_kwargs)`** dispatches on the SHAPE of what you hand it, never on
  the producing library: a **connection** (anything with `send_command`
  — netmiko, scrapli, work-alikes; extra kwargs pass through to the
  library call, the platform is read off the connection), a **response
  object** (scrapli's `Response` ships in the box via `neterse.sources`
  adapters — also covers nornir-style results), **raw text**
  (`compact(raw, "show ip route", platform=...)`), or **structured
  rows** (netmiko `use_textfsm=True`, NAPALM getters, gNMI — routed to
  the rows-only path). One name across every library; a future response
  object is one `neterse.sources.register_adapter()` call, never a new
  API name.
- **Platform spellings resolve the way the ecosystem writes them**:
  `ntc.parse` walks a ladder verified against the real ntc-templates
  index — transport suffix stripped first (`cisco_ios_ssh`), the
  verbatim string second (ntc keys every WLC template on
  `cisco_wlc_ssh` itself), known remaps last. The load-bearing remap is
  netmiko's own `cisco_xe` → `cisco_ios` retry (raw ntc genuinely
  rejects `cisco_xe`); `cisco_iosxe` → `cisco_ios` and `cisco_iosxr` →
  `cisco_xr` are defensive — current ntc resolves those via CliTable's
  regex platform matching, verified empirically.
- The integration layer is **duck-typed and imports no runner library**
  — the core stays zero-dependency, every failure path degrades toward
  returning the device output unchanged, and the test suite pins the
  contracts with fakes (no new test dependencies).

### Rows-only compaction (decision 30)

- **`neterse.render_parsed(rows)` / `neterse.optimize_parsed(rows)`** —
  for output that arrives ALREADY parsed (netmiko `use_textfsm=True`,
  scrapli `textfsm_parse_output()`, API/gNMI payloads) with no raw text
  in hand. Candidates are gated against the compact JSON a consumer
  would otherwise send (`json.dumps(rows, separators=(",", ":"),
  default=str)`);
  `optimize_parsed` returns the smallest of the two, so it never
  enlarges. Strings pass through byte-identical — netmiko's no-template
  fallback returns raw text, which belongs to `optimize`.
- **Keyed-dict getters now flatten and compress.** The dominant NAPALM /
  OpenConfig shape is a dict keyed by name whose values are all dicts
  (`get_interfaces`, `get_interfaces_counters`, `get_optics`,
  `get_users`, `get_vlans` → `{interface: {...}}`). The parsed tier now
  turns it into one row per entry, keeping the outer key as a leading
  `key` column (underscore-prefixed if it would shadow an inner field),
  so it encodes as a table instead of one unshrinkable mega-row —
  lossless (the key becomes a cell), no caller-side flattening needed.
  Scalar or mixed-valued dicts (`get_facts`, `get_config`,
  `get_snmp_information`) still stay a single row. Validated live against
  NX-OS and EOS: aggregate savings across the getter suite rose from
  ~2% to 22–28%, `get_interfaces_counters` reaching 77–83%.

### YAML spec authoring (decisions 27–28) — the contribution surface

- **Specs are now authored as YAML**, one file per command family under
  `neterse/specs/<vendor>/<family>.yaml` — the vendor/command layout
  ntc-templates made familiar. The spec's id is the path; regexes stay
  byte-for-byte what the dict tier declared, with the design notes
  preserved as YAML comments.
- **`scripts/compile_specs.py`** validates every source loudly (regexes
  must compile, header arity must match captured groups / keywords,
  profiles must project real columns, the `dropped_fields` manifest is
  mandatory, unknown keys are rejected) and generates the committed
  `neterse/specs/_compiled.py` the runtime imports — YAML never becomes
  a runtime dependency, preserving the zero-dep invariant. CI and the
  test suite both fail on drift between sources and the generated
  module (`compile_specs.py --check`).
- **No registry edit per contribution**: specs without an explicit
  position in the canonical order self-append after the full sequence in
  sorted-id order, so tie-breaks still resolve to the frozen baseline
  entries. A new command family is one YAML file plus two fixture files.
- Migration held byte-parity: the compiled dicts are deep-equal to the
  retired `specs.py` — sole exception: `show_ip_route`'s VERBOSE row,
  reformatted as a block scalar (whitespace and comment layout a VERBOSE
  pattern ignores; decision 27) — and the full parity cross-matrix is
  unchanged.

### ntc-templates front-end (decision 29)

- **`neterse.ntc`** — `pip install neterse[textfsm]` — drives
  ntc-templates/TextFSM itself: `ntc.parse(raw, command=..., platform=...)`
  returns the parsed rows (or `None`, fail-open), and
  `ntc.render`/`ntc.optimize` feed them straight into the parsed tier so
  one call covers both tiers across every template the community
  maintains. Without the extra — or when no template matches — behavior
  is byte-identical to the core API. The core never imports it.

### Packaging

- The `test` extra gains PyYAML (authoring/drift tooling only); the new
  `textfsm` extra pulls ntc-templates. Runtime dependencies remain zero,
  still enforced in CI. The YAML sources ship as package data for
  reference; the compiled module is what imports.

## 0.1.0 — first release

First public release: minimum-token renderings of network CLI output for
LLM agents. Distribution, import, and CLI all share the name `neterse`
("network terse") — the natural name `terse` is squatted on PyPI by an
abandoned 2019 package. Nothing was ever published under any earlier
working name.

### Core

- **Public API** (frozen): `render(raw, *, command, platform=None,
  parsed=None, profile="default") -> [Candidate]`, `optimize()`
  (smallest-wins convenience wrapper), `register()` plugin escape hatch,
  `iter_compressors()` / `iter_entries()` registry views.
- **Fail-open everywhere.** Exception, non-string, empty, or
  non-shrinking result yields no candidate. Raw is never lost and output
  is never enlarged.
- **Zero runtime dependencies** (enforced in CI), `py.typed`, Apache-2.0.
- **Registry** (`neterse/registry.py`): one canonical-order `Entry` list
  carrying pattern, function, platform scope, and lossiness manifest.
  20 spec families + 6 code compressors.
- **Spec engine** (`neterse/engine.py`): generic strategies compile
  declarative dict specs into compressors — `line_regex_table`,
  `fixed_width_table` (with an optional `row_match` key for non-Cisco
  port names such as `Et1` and `1/1/1`), and `kv_extract` for
  first-match field scans. The code tier (`_compressors.py`) stays for
  genuinely stateful formats: interface detail, running-config,
  access-lists, counters errors, port-channel summary, ip protocols.
- **Platform keying**: `render(platform=...)` skips entries whose
  declared scope doesn't match, killing cross-family false matches (an
  NX-OS table spec claiming Arista output). The filter only ever skips —
  no platform, or no declared scope, tries everything.
- **Declared lossiness**: every shipped entry declares `dropped_fields`
  (`()` = lossless; ip-interface-brief declares `("ok", "method")`,
  access-lists declares `("hit_counters",)`), surfaced verbatim on
  `Candidate.dropped_fields`.

### Parsed tier and profiles

- **Parsed tier** (`neterse/parsed.py`): pass rows another parser already
  produced (Genie / ntc-templates / TTP / NAPALM / gNMI — a list of
  dicts, or a single dict for one row) and the tier re-encodes them
  header-once, independent of any registry match. Two candidates are
  emitted (`method="parsed"`), and the consumer's smallest-wins picks:
  - `parsed:csv` — header-once CSV, the smallest faithful flat encoding;
    beats the `json.dumps(rows)` key-per-row competitor by ~45–50% on
    multi-row output (the acceptance rule, pinned in
    `tests/test_parsed.py`).
  - `parsed:toon` — TOON-style tabular block (`[N]{fields}:` + indented
    rows); a few percent larger than CSV but the explicit row count lets
    a policy (or the model) detect truncation.

  Nested values JSON-encode into their cell; missing keys and `null`
  render as empty cells over the unioned first-seen header; malformed
  input yields no candidates. Both candidates pass the usual shrink gate.
- **Profiles**: a profile is a named, opt-in, DECLARED-lossy projection —
  `"updown"` ships first (interface liveness: port/status(/reason/
  protocol)), declared on the three interface-state specs and, by
  field-name pattern, on the parsed tier. Projected renderings append an
  inline omission marker (`[omitted: name, vlan, … — re-query
  profile=full]`) so the model knows data was withheld and how to recover
  it; the omitted names join `dropped_fields`, and `Candidate.profile`
  names what was applied. Entries that don't declare the requested
  profile render their complete default — an unknown profile never loses
  data. `"full"` is an alias of `"default"`.

### Vendor coverage

- **Cisco IOS / NX-OS**: ip route, ip interface brief, interface detail,
  version, bgp summary, ospf neighbors, running-config, cdp/lldp
  neighbors, vlan brief, access-lists, interface status, interface brief
  (NX-OS), interface counters errors, eigrp neighbors, port-channel
  summary, cdp neighbors (IOS fixed-width), ip protocols.
- **Arista EOS**: interfaces status, ip arp, vlan.
- **Juniper Junos**: interfaces terse, ospf neighbor.
- **Aruba AOS-CX**: interface brief, vlan.
- **MikroTik RouterOS**: `/ip address print`, `/interface print`.

### Live-lab verification

Verified against real devices (containerlab `cisco_iol`, IOS 17.12.1 —
an OSPF summarization lab and a BGP fundamentals lab). The audit on live
traffic proved the original baseline wrong three times; each fix is a
recorded baseline decision in `docs/DESIGN.md`:

- **`show ip route` rewritten (decision 20).** The legacy regex silently
  dropped every route with a two-token protocol code (`O IA`, `O E2`,
  `D EX`, …) — on the lab that was 9 of 19 routes, i.e. every learned
  route — rendered `is` as the interface of connected routes, and leaked
  route-age into other columns, all declared lossless. Now every route
  row survives with clean columns; remaining drops are declared
  (`route_age`, `ecmp_alternate_paths`, `subnet_group_headers`). Honest
  side effect: the family's reduction is now ~70%, not 93% — the
  difference was deleted data.
- **`show ip bgp summary` AS fix (decision 24).** The legacy regex
  captured the V column (BGP version, constant `4`) under the `as` header
  and silently dropped the real AS — eBGP and iBGP neighbors were
  indistinguishable. Every neighbor row now carries its actual AS;
  `version` joins the declared drops.
- **IOS `show cdp neighbors` covered (decision 25).** The legacy cdp/lldp
  entry expects single-token row values and fails open on real IOS output
  (`Eth 0/2`, `Linux Uni` — 547–623 chars/call straight to the model). A
  new fixed-width spec parses it (58% fewer chars), with engine support
  for IOS's wrapped-device-ID lines (`first_col_wraps`). The legacy entry
  gains `unindented_rows_only`: its stripped-line matching let indented
  continuation/counter lines false-match into corrupt rows that could WIN
  smallest-wins.
- **`show ip protocols` covered (decision 26).** Block-structured IOS
  output no table strategy fits — a code compressor renders one line per
  routing-protocol block (`proto "bgp 200": filters=none | neighbors=… |
  distance=…`), 56–61% fewer chars (996–1557 chars/call reached the model
  raw before). Known boilerplate collapses to key=value, list sections
  join their items, and every unrecognized line survives verbatim —
  format drift degrades compression, never faithfulness.
- **`show ip interface brief` admin-down fix (decision 21, additive).**
  `administratively down` split across the status and protocol columns
  with the real protocol column never read.
- **Parsed-tier verification** (netmiko `use_textfsm=True`, i.e.
  ntc-templates/TextFSM — the tier's real consumer stack): 12 live
  families verified cell-for-cell faithful (CSV independently decoded and
  compared to the parser's rows), TOON row counts exact, shrink gate
  honest (`show clock` correctly yields no candidate), and a string-typed
  `parsed` (netmiko's no-template fallback) declining cleanly. One fix
  (decision 22): the `updown` status patterns missed ntc's
  `protocol_status` spelling, so the liveness profile dropped the
  line-protocol column on `show interfaces`;
  `protocol_status`/`oper_status`/`admin_status` now match.

Real captures are committed under `tests/fixtures/cisco_ios/` with
goldens in `tests/test_cisco_real_captures.py`.

### Tooling and testing

- **`neterse audit`** (`neterse/audit.py`, console script `neterse` /
  `python -m neterse`): the coverage tool. Feed it
  `(command, platform?, raw)` samples — JSONL files, fixture
  directories, raw captures with `--command`, or stdin — and it reports
  per-family reduction, totals (chars/4 token estimate), covered/
  uncovered volume, and the OPPORTUNITIES list (`NO COMPRESSOR`,
  `false-match:<entry>`, `platform-skip:<entry>`), plus each winning
  entry's declared `dropped_fields` so an audit doubles as a lossiness
  review. `--show N` dumps the heads of the largest gaps;
  `--fail-under PCT` gates CI.
- **Byte-parity suite** against the frozen baseline
  (`tests/legacy_snapshot.py`): full command × body cross-matrix
  including wrong-command pairings and edge inputs. Families whose output
  intentionally changed are exempt via `INTENTIONAL_DIVERGENCES` and
  pinned by their own goldens instead. New vendor families are
  post-baseline: covered behaviorally, never allowed to change a legacy
  result (decision 15).
- **Parity replay** (`scripts/replay_parity.py`): replay any corpus
  through the frozen baseline and current neterse, unified-diff and exit
  1 on byte differences. Repo-side by design — the baseline isn't
  shipped.
- **Fixture-per-file contribution layout**:
  `tests/fixtures/<platform>/<family>/{commands.txt,raw.txt}` — the audit
  CLI reads the same layout. Every fixture dropped there is auto-covered
  by the suite: diagonal shrink (with and without platform),
  winner-is-own-spec, wrong-platform skip, and a fail-open cross-matrix.
- **Token-savings regression** (`tests/test_token_savings.py`, CI job):
  savings measured with a real, pinned tokenizer (`tiktoken==0.13.0`,
  `o200k_base`) against a committed per-family baseline (40 families,
  43.7% saved) with a 35% aggregate floor. Skips locally without
  tiktoken; runtime stays chars/4 (decision 8). Regenerate with
  `scripts/update_token_baseline.py` — a recorded decision, like
  byte-parity changes.
- **Release machinery**: `release.yml` publishes to PyPI via Trusted
  Publishing on a `v*` tag (tag/version lockstep check + wheel smoke
  test); human steps in `docs/RELEASING.md`.
