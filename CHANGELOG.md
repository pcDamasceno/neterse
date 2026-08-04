# Changelog

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
