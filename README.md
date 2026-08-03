# terse

*Minimum-token renderings of network CLI output for LLM agents — the
`| brief` the vendor never shipped.*

LLM-driven network agents burn most of their context window on the noise in
`show`-command output: separator dashes, static legends, wrapped headers,
all-zero counter tables, and keys repeated on every row. **terse** rewrites
that output into the smallest representation that preserves the semantics,
before it enters model context — so agents spend tokens on reasoning, not
formatting. Savings of 40–60% are typical on tabular output; on huge
mostly-zero tables, compression is the difference between a truncated tool
result and a complete one.

```python
from terse import render, optimize

# Full API — every candidate that shrinks the output; policy is yours:
candidates = render(raw, command="show interface status", platform="cisco_nxos")
best = min(candidates, key=lambda c: len(c.text), default=None)

# Convenience wrapper — smallest candidate's text, or raw unchanged:
compact = optimize("show interface status", raw)

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
                    ▼  terse
port,name,status,vlan,duplex,speed,type
Eth1/11,RSRFF206 Twe1/0/3,connected,routed,full,10G,10Gbase-SR
Eth1/45,RFRA3213-Eth1/48,connected,routed,full,10G,10Gbase-LR
```

## Install

```bash
pip install terse-net        # import name: terse
```

> The distribution is `terse-net` because the PyPI name `terse` is occupied
> by an unrelated package abandoned in 2019 (a PEP 541 transfer request may
> reclaim it eventually). The import is plain `import terse`.

## Design in one paragraph

Two tiers, one contract. The **raw-text tier** compresses CLI output
directly — declarative specs drive generic strategies (fixed-width
table → CSV, line-regex table → CSV, key-value scan), with plain-Python
compressors as the escape hatch for genuinely stateful formats. The
**parsed tier** re-encodes rows that Genie / ntc-templates / TTP / NAPALM
already parsed into compact header-once form (`render(..., parsed=rows)`
→ CSV and TOON-style candidates that undercut `json.dumps(rows)` by
~45–50%). Opt-in **profiles** (`profile="updown"`) narrow output to a
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
5. **Byte-parity discipline.** The pre-extraction dbcli implementation is
   frozen in-tree (`tests/legacy_snapshot.py`); the parity suite replays a
   cross-matrix corpus and pins today's outputs byte-for-byte. Engine
   refactors may change *how*, never *what*. Intentional output changes are
   recorded baseline decisions.

## Provenance & prior art

terse was extracted from [dbcli]'s TOON optimizer ("Token-Optimized Output
for Networks", inspired by [NetClaw]'s TOON serialization work) and turned
into a standalone, community-extensible library. It complements — not
competes with — the parsing ecosystems: [ntc-templates], [Genie/pyATS] and
[TTP] turn CLI text into structure; terse makes structure (and unparseable
raw text) *cheap to show to a model*. The tabular encoding aligns with
[TOON — Token-Oriented Object Notation]; emitting spec-compliant TOON for
uniform tables is on the roadmap.

[dbcli]: https://github.com/pcDamasceno/dbcli
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
| 3 | PyPI release, fixture-per-file contribution flow, `terse audit` coverage tool, multi-vendor expansion (Arista, Juniper, …) | ▢ |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: most new command
families are **a spec dict plus two fixtures** — no parser code. The
escape hatch for stateful formats is a plain function under the same
fail-open contract.

## License

Apache-2.0 — see [LICENSE](LICENSE).
