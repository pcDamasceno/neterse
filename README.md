# neterse

*Minimum-token renderings of network CLI output for LLM agents — the
`| brief` the vendor never shipped.*

LLM-driven network agents burn most of their context window on the noise in
`show`-command output: separator dashes, static legends, wrapped headers,
all-zero counter tables, and keys repeated on every row. **neterse** rewrites
that output into the smallest representation that preserves the semantics,
before it enters model context — so agents spend tokens on reasoning, not
formatting. Savings of 40–60% are typical on tabular output; on huge
mostly-zero tables, compression is the difference between a truncated tool
result and a complete one.

```python
from neterse import compact, render

# The one verb — smallest faithful text for whatever you're holding:
# a connection, a scrapli Response, raw text, or already-parsed rows
# (with neterse[textfsm] installed, TextFSM parsing competes too):
output = compact(conn, "show interface status")
output = compact(raw, "show interface status", platform="cisco_nxos")
output = compact(rows)

# Full API — every candidate that shrinks the output; policy is yours:
candidates = render(raw, command="show interface status", platform="cisco_nxos")
best = min(candidates, key=lambda c: len(c.text), default=None)

# Parsed tier — rows Genie/ntc-templates already produced, re-encoded
# header-once (beats json.dumps(rows) by ~45-50% on multi-row output):
candidates = render(raw, command="show ip int brief", parsed=rows)

# Opt-in declared-lossy projection; the rendering itself says what was
# withheld: "[omitted: name, vlan, ... — re-query profile=full]"
candidates = render(raw, command="show interface status", profile="updown")
```

```
Port      Name               Status   Vlan    Duplex  Speed  Type
--------------------------------------------------------------------------------
Eth1/11   RSRFF206 Twe1/0/3  connected routed  full    10G    10Gbase-SR
Eth1/45   RFRA3213-Eth1/48   connected routed  full    10G    10Gbase-LR
                    │
                    ▼  neterse
port,name,status,vlan,duplex,speed,type
Eth1/11,RSRFF206 Twe1/0/3,connected,routed,full,10G,10Gbase-SR
Eth1/45,RFRA3213-Eth1/48,connected,routed,full,10G,10Gbase-LR
```

## One verb for netmiko, scrapli — and whatever comes next

`compact` dispatches on the **shape** of what you hand it, never on the
producing library, so the call looks the same everywhere and neterse
never imports any runner library:

```python
from neterse import compact

# a connection — netmiko, scrapli, any work-alike with send_command
# (extra kwargs pass through to the library call):
output = compact(conn, "show interface status")

# a scrapli Response you already have:
output = compact(response)

# raw text from anywhere:
output = compact(raw, "show ip route", platform="cisco_ios")

# rows something already parsed — netmiko use_textfsm=True,
# NAPALM getters, gNMI, plain dicts/lists:
output = compact(rows)
```

The raw and TextFSM-parsed tiers compete whenever parsing is possible
(`pip install neterse[textfsm]`), and platform strings resolve the way
the ecosystem actually spells them — netmiko `device_type`s
(`cisco_ios_ssh`, `cisco_xe`), scrapli's `cisco_iosxe`, plain ntc names.
Everything stays fail-open: no template, no extra, nothing shrinkable —
you get the original back, byte-identical. scrapli's
`send_commands([...])` returns a `MultiResponse` carrying no per-command
info; map it: `[compact(r) for r in multi]`.

A future library is a small source adapter
(`neterse.sources.register_adapter`) — never a new API name.

## Install

```bash
pip install neterse                # zero dependencies, import name: neterse
pip install "neterse[textfsm]"     # + ntc-templates: parse & compress in one call
```

> Named **neterse** ("network terse") because the natural name `terse` is
> occupied on PyPI by an unrelated package abandoned in 2019. Distribution,
> import, and CLI all share the one name.

## Design in one paragraph

Two tiers, one contract. The **raw-text tier** compresses CLI output
directly — declarative specs, authored as one YAML file per
vendor/command (`neterse/specs/<vendor>/<family>.yaml`, compiled to
plain dicts so the runtime stays dependency-free), drive generic
strategies (fixed-width table → CSV, line-regex table → CSV, key-value
scan), with plain-Python compressors as the escape hatch for genuinely
stateful formats. The **parsed tier** re-encodes rows that Genie /
ntc-templates / TTP / NAPALM already parsed into compact header-once
form (`render(..., parsed=rows)` → CSV and TOON-style candidates that
undercut `json.dumps(rows)` by ~45–50%) — and the optional
`neterse.ntc` front-end (`pip install neterse[textfsm]`) runs
ntc-templates for you, so one call covers both tiers. Opt-in **profiles** (`profile="updown"`) narrow output to a
declared projection and say so inline
(`[omitted: … — re-query profile=full]`). Both tiers emit `Candidate`s;
the library **never picks a winner** — smallest-wins, ledgers, metrics,
and caching belong to the consumer. Full architecture:
[docs/DESIGN.md](docs/DESIGN.md).

## Invariants

1. **Fail-open, always.** A compressor that raises, returns a non-string,
   returns empty, or fails to shrink produces no candidate. Raw data is
   never lost and never enlarged.
2. **Zero runtime dependencies.** Standard library only — enforced in CI.
   Tokenizers are a CI concern; `Candidate.est_tokens()` is a chars/4
   estimate by design.
3. **Candidates, not policy.** Consumers decide what to send to the model.
4. **Preserve semantically relevant data; declare every drop.** Noise
   (separators, legends, all-zero rows — kept visible via explicit
   `(all zero)` markers) is dropped freely; anything else a rendering omits
   must be declared machine-readably on the candidate
   (`Candidate.dropped_fields`).
5. **Byte-parity discipline.** The original implementation is
   frozen in-tree (`tests/legacy_snapshot.py`); the parity suite replays a
   cross-matrix corpus and pins today's outputs byte-for-byte. Engine
   refactors may change *how*, never *what*. Intentional output changes are
   recorded baseline decisions.

## Provenance & prior art

neterse grew out of a TOON optimizer ("Token-Optimized Output for
Networks", inspired by [NetClaw]'s TOON serialization work) built for a
network agent, and is now a standalone, community-extensible library. It
complements — not competes with — the parsing ecosystems: [ntc-templates],
[Genie/pyATS] and [TTP] turn CLI text into structure; neterse makes
structure (and unparseable raw text) *cheap to show to a model*. The
tabular encoding aligns with
[TOON — Token-Oriented Object Notation]; emitting spec-compliant TOON for
uniform tables is on the roadmap.

[NetClaw]: https://github.com/automateyournetwork/netclaw
[ntc-templates]: https://github.com/networktocode/ntc-templates
[Genie/pyATS]: https://developer.cisco.com/docs/pyats/
[TTP]: https://github.com/dmulyalin/ttp
[TOON — Token-Oriented Object Notation]: https://github.com/toon-format/toon

## Roadmap

| Phase | Contents | Status |
|---|---|---|
| 0 | API frozen (`render`/`Candidate`/`optimize`/`register`); 15 compressor families extracted verbatim; byte-parity baseline | ✅ |
| 1 | Spec engine (generic strategies over declarative specs), platform-keyed dispatch, declared-lossiness manifests | ✅ |
| 2 | Parsed tier: field projection + compact encoders (CSV/TOON) over pre-parsed rows; opt-in profiles with inline omission markers; `kv_extract` strategy | ✅ |
| 3 | `neterse audit` coverage tool, fixture-per-file contribution flow, CI token-savings regression (pinned tokenizer), multi-vendor expansion (Arista EOS, Junos, Aruba AOS-CX, MikroTik), PyPI release machinery | ✅ |
| 4 | Contributor scale-out: YAML spec authoring (one `specs/<vendor>/<family>.yaml` per family, compiled — never parsed — at runtime), registry self-append, `neterse[textfsm]` extra driving ntc-templates end-to-end | ✅ |
| 5 | Runner integration: the universal `compact()` verb (shape dispatch over connections / responses / raw / rows; source adapters for future libraries) + rows-only `render_parsed`/`optimize_parsed` for already-parsed output | ✅ |
| 6 | Consumers swap vendored copies for the pip dependency; propose a TOON profile for network data upstream | ▢ |
| 7 | Beyond the CLI: the same candidates contract for MCP tool results, API responses, and generic JSON payloads | ▢ |

## Coverage

Command families ship for **Cisco IOS/IOS-XE/NX-OS** (15 legacy families:
routes, interfaces, BGP/OSPF/EIGRP neighbors, CDP/LLDP, VLANs, ACLs,
counters, port-channels, version, running-config), **Arista EOS**
(interfaces status, ip arp, vlan), **Juniper Junos** (interfaces terse,
ospf neighbor), **Aruba AOS-CX** (interface brief, vlan) and **MikroTik
RouterOS** (`/ip address print`, `/interface print`) — and the parsed
tier covers anything your parser already handles, on any platform.

Measure coverage over your own agent's traffic with the bundled CLI:

```bash
neterse audit run.jsonl --show 3      # {"command":..., "platform":..., "raw":...} per line
neterse audit tests/fixtures          # or point it at a fixture tree
```

It reports per-family reduction, what reached the model uncompressed
(`NO COMPRESSOR` / `false-match` / `platform-skip`), and each winning
entry's declared drops — the gaps it prints are, in order, the next
specs worth contributing.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: most new command
families are **one YAML spec file plus two fixture files** —
`neterse/specs/<platform>/<family>.yaml` (the vendor/command layout
ntc-templates made familiar) and
`tests/fixtures/<platform>/<family>/{commands.txt,raw.txt}` — no parser
code, no registry edit, and the suite auto-covers anything dropped
there. `python scripts/compile_specs.py` validates the spec loudly and
regenerates the zero-dependency runtime module. The escape hatch for
stateful formats is a plain function under the same fail-open contract.

## License

Apache-2.0 — see [LICENSE](LICENSE).
