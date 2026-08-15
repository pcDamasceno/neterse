# Spec authoring reference

Every field of the YAML spec format, in one place. The machine truth is
`scripts/compile_specs.py` (its validator runs on every compile and in
the test suite); `tests/test_spec_docs.py` fails when a key exists there
that this document doesn't mention, so the two cannot drift silently.
For the end-to-end contribution flow (fixtures, goldens, CI), see
[CONTRIBUTING.md](../CONTRIBUTING.md).

A spec is one YAML file per command family:

```
neterse/specs/<vendor>/<family>.yaml
```

`python scripts/compile_specs.py` validates it loudly and regenerates
`neterse/specs/_compiled.py`, the plain-Python module the runtime
imports (YAML never becomes a runtime dependency — decision 27). Commit
the YAML **and** the regenerated module together; CI diff-gates them.

## The naming contract

Four names must line up, and nothing infers one from another — get them
consistent up front (`scripts/new_spec.py` generates them consistent by
construction):

1. **Spec path** — `neterse/specs/<vendor>/<family>.yaml`. The spec's
   `id` IS the path (`arista_eos/show_ip_arp`); never write an `id` key
   in the YAML (the compiler rejects a contradicting one).
2. **Fixture directory** — `tests/fixtures/<platform>/<family>/`. The
   `<platform>` directory name doubles as the platform string the test
   suite passes to `render()` — it is not just a label.
3. **The spec's `platforms` regex must match that platform string**, or
   the shrink diagonal fails with "no candidate" (the filter skipped
   your own spec on your own fixture).
4. **The spec's `<vendor>` directory must start with the platform
   string's pre-underscore stem** — a `cisco_ios` fixture may be won by
   `spec:cisco/...` or `spec:cisco_ios/...`, an `aruba_aoscx` fixture
   by `spec:aruba_aoscx/...` — or the winner-identity test fails
   (`tests/test_fixture_corpus.py`).

Cisco directories: `cisco/` holds the legacy families whose one spec
covers IOS/IOS-XE/NX-OS alike. New Cisco families go in `cisco_ios/` or
`cisco_nxos/`; use `cisco/` only when one spec genuinely parses both
platforms' output.

## Common keys (every strategy)

| key | required | meaning |
| --- | --- | --- |
| `command` | yes | Regex over the CLI command string (compiled case-insensitive). Scope it **tightly** — exclude sibling subcommands with a negative lookahead rather than relying on smallest-wins. |
| `strategy` | yes | `line_regex_table`, `fixed_width_table`, or `kv_extract`. |
| `dropped_fields` | yes | The lossiness manifest: names of **data-bearing** fields the rendering omits, surfaced on every candidate. `[]` declares the rendering lossless. Pure noise (separators, legends, repeated headers) is dropped freely and never declared. |
| `platforms` | no | Case-insensitive regex `search()`-ed against the caller's (lowercased) platform string. A **skip filter only**: no platform given, or no key declared, and the spec is always tried. Declare broadly (`'eos|arista'`) — it exists to kill cross-family false matches, not to gatekeep. |
| `profiles` | no | Named declared-lossy column projections — see [Profiles](#profiles). Table strategies only. |
| `doc` | no | One-line description; becomes the built compressor's docstring. |
| `id` | never | Derived from the file path; writing it is a validation error. |

## `line_regex_table`

One regex per data row → CSV. The pattern is `match()`-ed against each
**stripped** line; every non-matching line is dropped; unmatched groups
render as empty cells. Fails open (returns the input) when no line
matches.

| key | required | meaning |
| --- | --- | --- |
| `row` | yes | The row pattern. Its capture groups become the CSV columns. |
| `header` | yes | The CSV header, a **comma-separated string** (not a YAML list). Names must be unique; a name can never contain a comma. Arity must equal the emitted group count. |
| `row_flags` | no | Symbolic regex flag name(s) for `row` — see [Flags](#flags). |
| `columns` | no | **1-based regex group indexes** to emit, in order (not output positions). Omit to emit every group. |
| `strip_columns` | no | Group indexes (again 1-based, and they must be *emitted* ones) whose value is `.strip()`-ed. |
| `context_prefixes` | no | Lines starting with any of these (after stripping) are captured as a context line prepended above the header — e.g. the EIGRP process/VRF line. The last one seen wins. |
| `unindented_rows_only` | no | Boolean: skip indented lines *before* stripping. For tables whose data rows start at column 0 — wrapped continuation lines can then never false-match (decision 25). |

## `fixed_width_table`

Offset-sliced fixed-width table → CSV. The header line is located by its
column keywords; each keyword's character offset defines a column slice,
and every subsequent line whose first column passes the row gate is
sliced at those offsets (values may contain spaces — the reason a line
regex can't parse these tables). Fails open when no header or no rows.

| key | required | meaning |
| --- | --- | --- |
| `keywords` | yes | The header tokens, in order, as they appear on the device (`[Port, Name, Status]`; quote multi-word ones: `'Device ID'`). Arity must equal `header`'s. |
| `header` | yes | The emitted CSV header (comma-separated string, same rules as above). |
| `row_match` | no | Regex the first column of a data row must match. Default: the shared Cisco interface-name pattern — vendors with other port-name shapes declare their own (Arista `'^Et'`, Aruba `'^\d+/\d+/\d+'`). |
| `first_col_wraps` | no | Boolean: the first column's value may overflow its width and wrap onto its own line (IOS `show cdp neighbors` device IDs); rows are re-joined, and `row_match` defaults to a single-token pattern instead of interface names. |

## `kv_extract`

First-match field scan → one `key=value | key=value` line. Fields are
tried per line, top to bottom; each field's **first** match wins; output
order is the order in which fields first matched. No `header`, and
`profiles` are not supported (there are no columns to project). Fails
open when nothing matches.

| key | required | meaning |
| --- | --- | --- |
| `fields` | yes | Non-empty list of field mappings — keys below. |
| `joiner` | no | Separator between `key=value` pairs (default `" | "`). |

Each entry of `fields`:

| key | required | meaning |
| --- | --- | --- |
| `key` | yes | Output name (must be unique within the spec). |
| `pattern` | yes | Regex `search()`-ed per line. |
| `flags` | no | Symbolic regex flag name(s) — see [Flags](#flags). |
| `template` | no | `str.format` string where `{0}` is the whole match and `{1}`… are capture groups (default `"{1}"`). Note the indexing differs from `columns`: format indexes, not group selections. |
| `strip` | no | Boolean: `.strip()` each group before formatting. |

## Profiles

A table spec may declare named, opt-in, **declared-lossy** column
projections:

```yaml
profiles:
  updown:
    keep: [port, status, reason]
```

Requested via `render(..., profile="updown")`. The variant emits only
the kept columns and appends an inline omission marker naming what was
withheld — `[omitted: name, vlan — re-query profile=full]` — so a model
reading the rendering knows data exists and how to recover it. The
omitted column names join the entry's `dropped_fields` manifest on the
resulting candidates.

Rules (validated at compile time):

* `keep` names resolve against `header` by exact spelling; unknown names
  are an error.
* A profile must keep at least one column **and** drop at least one.
* Entries that don't declare a requested profile render their complete
  default — a profile narrows output only where a spec explicitly said
  how (decision 11). An unknown profile string behaves as `default`.
* `full` is an alias of `default` (decision 12) — the marker's re-query
  hint must actually work.
* `kv_extract` specs cannot declare profiles.

## Flags

`row_flags` and `fields[].flags` take a symbolic regex flag name or list
of names, resolved to `re` flags at compile time. Allowed: `ASCII`,
`DOTALL`, `IGNORECASE`, `MULTILINE`, `VERBOSE`. (`command` and
`platforms` are always compiled case-insensitive; no flags key applies
to them.)

## YAML quoting

Quote regexes with **single quotes** — YAML double quotes reject `\s`
loudly. Multi-line `VERBOSE` patterns use a `|-` block scalar (see
`cisco/show_ip_route.yaml`). Whitespace and `#` comments inside a
`VERBOSE` pattern are ignored by the regex engine, so block-scalar
reformatting never moves output.

## The compile loop

```bash
python scripts/compile_specs.py            # validate + regenerate _compiled.py
python scripts/compile_specs.py --check    # CI drift gate (exit 1 + diff)
```

Validation is deliberately loud — every regex must compile, header arity
must match the emitted group / keyword count, `columns` must be in
range, templates are dry-run formatted, profiles must keep real columns,
the manifest is mandatory, unknown and duplicate keys are rejected, and
misfiled paths (`.yml`, wrong depth) fail instead of being skipped. Exit
status: 0 = compiled/up-to-date, 1 = drift (`--check`), 2 = validation
error.

## Worked examples in the tree

* `neterse/specs/arista_eos/show_ip_arp.yaml` — minimal
  `line_regex_table`.
* `neterse/specs/cisco/show_ip_route.yaml` — `VERBOSE` block-scalar row
  pattern.
* `neterse/specs/cisco_ios/show_cdp_neighbors.yaml` —
  `fixed_width_table` with `first_col_wraps` and a custom `row_match`.
* `neterse/specs/cisco/show_version.yaml` — `kv_extract` with templates
  and flags.
* `neterse/specs/aruba_aoscx/show_interface_brief.yaml` — a profile in
  three lines.

When no strategy fits — the format carries state across lines
(multi-line blocks, banner delimiters, multi-sub-table output) — the
family is a plain-Python compressor, not a new spec key: see
[CONTRIBUTING.md](../CONTRIBUTING.md#when-a-spec-genuinely-cant-express-it).
