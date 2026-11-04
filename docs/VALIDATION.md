# Live validation — 2026-11-04

Validated the working-tree changes against the running DBCLI backend's
configured inventory and `network_infrahub` MCP connection. Device access used
DBCLI's normal inventory lookup, credential resolution, and connection drivers.
Only operational show commands and read-only Infrahub queries were issued.
No device configuration, Infrahub objects, or DBCLI deployment was changed.
Raw captures and access details remain outside this repository.

## Device results

The sweep attempted 25 inventory entries with at most three concurrent sessions.
Eighteen devices returned 76 captures from 87 command attempts.

| Platform | Responding devices | Captures | Input tokens | Output tokens |
| --- | ---: | ---: | ---: | ---: |
| Cisco IOS/IOS-XE inventory entries | 13 | 59 | 22,930 | 7,879 |
| Arista EOS | 2 | 12 | 2,072 | 1,793 |
| Nokia SR Linux | 2 | 4 | 2,128 | 2,128 |
| Palo Alto PAN-OS | 1 | 1 | 528 | 121 |
| **Total** | **18** | **76** | **27,658** | **11,921** |

Token counts use `o200k_base` with `tiktoken==0.13.0`: **56.9% fewer tokens**
and **66.6% fewer characters** across these captures. Sixty-two captures shrank;
fourteen passed through unchanged. These are default-profile results: raw
compressors and upstream TextFSM parsers can omit fields, as explained in
[the API guide](API.md#preservation-and-lossiness). Savings are not a claim
that every raw field was retained.

Checks completed:

- All 76 successful command responses completed compaction without expansion
  in either characters or tokens. Empty output and a device syntax-error
  response remained unchanged.
- An independent CSV reader and JSON cell decoder recovered all **477 rows
  across 62 TextFSM tables**, preserving values and their types. Response-object
  adaptation produced the same output as passing those rows directly.
- All **11 raw VLAN tables** matched independently extracted VLAN IDs, names,
  status, and complete port cells. Cisco port lists containing commas remained
  one CSV field.
- Nokia output passed through unchanged because these commands have no matching
  compressor/parser in this installation.

Seven inventory entries failed their first connection/read attempt (two
`OSError`, five `ConnectionError`). On responding devices, three VLAN commands
raised `CommandExecutionError` and one controller route command timed out.
These 11 unsuccessful attempts were excluded from the savings figures.
Some controller entries use the generic IOS-XE inventory label; that label
does not establish support for router commands.

## Infrahub MCP results

Compared direct HTTP reads with a separate `neterse-mcp` process forwarding
to the same live upstream. All six successful cases matched local compaction
of the original response. Independent decoders additionally checked all
154 fields in the two detailed node samples, labels, pagination metadata,
empty collections, boolean values, and GraphQL identifiers/names/counts.

| Read | Input tokens | Output tokens |
| --- | ---: | ---: |
| Five device labels | 59 | 62 |
| Five devices with attributes | 2,662 | 2,176 |
| Two-device page with attributes | 936 | 816 |
| Empty filtered result | 26 | 21 |
| GraphQL node query | 212 | 179 |
| Already formatted device schema | 830 | 830 |
| **Successful reads total** | **4,725** | **4,084** |

The successful reads used **13.6% fewer tokens** overall. Detailed device
attributes saved **18.3%**. The short labels response gained three tokens
despite shrinking in characters: selection minimizes characters, not tokens.
Already formatted non-JSON schema text passed through unchanged.

Additional live checks passed:

- All 12 tools retained their input schemas; the default proxy removed output
  schemas consistently with structured-content deduplication.
- `--keep-structured` preserved the original structured result.
- `--max-input-chars` passed an oversized result through intact.
- A nested Docker stdio upstream accepted `docker exec -i ... python -c ...`
  through the CLI's `--` separator and returned the expected result.
- An invalid-kind query remained an explicit error with its upstream detail.
  FastMCP converted the upstream JSON-RPC error to a tool-error response and
  added its error prefix; this case was excluded from savings calculations.

The configured upstream did not require authentication, so live credential
header authentication was not exercised. Header validation and environment
variable handling are covered by automated tests.

## Remaining validation and next steps

1. Resolve the seven DBCLI access failures and use platform-specific commands
   for controller inventory entries before repeating the device sweep.
2. Add live Aruba, Juniper, MikroTik, and NX-OS coverage when those platforms are
   available; their current checks use fixtures. Wrapped VLAN continuation
   handling was covered by regression tests, but did not occur in this sample.
3. Consider an optional token-based selection policy for workloads where small
   responses matter; retain the dependency-free character policy as the default.
4. Grow a sanitized, provenance-reviewed capture corpus and measure operational
   question-answer accuracy alongside size. The readback checks here establish
   preservation of tested values, not downstream model accuracy.

The corresponding local suite passed **2,185 tests** with **360 intentional
skips**; the core-only environment passed **2,160** with **363 skips**. Spec and
golden drift checks passed. The refreshed dependency lock audit reported no
known vulnerabilities at validation time. GitHub-hosted CI and publishing were
not run as part of this validation.
