# Contributing to neterse

Most contributions are **a spec dict plus fixtures — no parser code.**
The bar is deliberately low; the CI gates are deliberately strict.

## Add a table-shaped command family (the common case)

1. **Write the spec** in `neterse/specs.py`:

```python
{
    "id": "arista_eos/show_ip_arp",
    "command": r"show\s+ip\s+arp",          # scope tightly; exclude sibling subcommands
    "platforms": r"eos",                     # regex over the caller's platform string; declare broadly
    "strategy": "line_regex_table",          # or fixed_width_table
    "row": r"^(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s+(\S+)\s+(\S+)",
    "header": "address,age,mac,interface",
    "dropped_fields": (),                    # REQUIRED: the lossiness manifest
},
```

2. **Register it** at the END of `REGISTRY` in `neterse/registry.py` —
   post-baseline entries always append after the legacy sequence, so
   equal-length ties keep resolving to the baseline (decision 15).

3. **Add fixture files** under
   `tests/fixtures/<platform>/<family>/`:
   - `raw.txt` — one byte-exact real capture. Never normalize
     whitespace; fixed-width column offsets are data. Capture with
     optimization disabled (or from a snapshot sink) so it is genuinely
     raw.
   - `commands.txt` — every command spelling agents actually type for
     it, one per line (abbreviations and per-target variants included).

4. **Run `pytest`.** The suite auto-covers anything in `tests/fixtures/`:
   the diagonal asserts your family genuinely shrinks (with and without
   the platform argument) and that the winner is your spec — not a false
   match; the cross-matrix asserts it fails open against every other
   family's output and the edge inputs; the manifest test rejects specs
   without `dropped_fields`. If the token CI job flags a missing
   baseline entry, run `python scripts/update_token_baseline.py` and
   commit the diff.

That's the whole contribution. In the PR description, paste the
before/after character counts — `neterse audit tests/fixtures` prints them.

Found the gap in a real agent run? `neterse audit run.jsonl --show 3`
ranks uncovered families by wasted volume and dumps the head of each, so
the format can be read before the spec is written.

## Rules the CI enforces (and reviewers care about)

- **Fail-open, always.** Unparseable or non-shrinking input returns raw.
  Never raise for control flow.
- **Preserve semantically relevant data.** Drop noise freely (separators,
  legends, repeated/wrapped headers, all-zero rows — keep an explicit
  `(all zero)` marker so absence stays visible). Never drop real values
  silently: anything data-bearing your rendering omits goes in
  `dropped_fields`.
- **Scope the command regex tightly.** Exclude sibling subcommands with a
  negative lookahead rather than relying on smallest-wins to save you
  (see the interface-detail entry in `registry.py`).
- **Zero dependencies.** The package imports the standard library only.
  If your idea needs a parser or tokenizer, it belongs in an optional
  extra or in Phase-2/3 tooling — open an issue first.
- **Byte-parity discipline.** Don't edit `tests/legacy_snapshot.py`, ever.
  If you believe an existing family's *output* should change, that's a
  baseline decision: propose it in an issue; if accepted it gets a
  decision-log entry in `docs/DESIGN.md` alongside the code change. The
  same applies to `tests/token_savings_baseline.json` — regenerating it
  to green a build without a recorded decision defeats the gate.
- **New families never claim legacy pairs.** The parity cross-matrix
  runs your entry against every legacy (command, body) combination
  automatically; if your regex changes any legacy result, tighten it
  (identical-output ties are fine — registry order resolves them).

## When a spec genuinely can't express it

Formats that carry state across lines (multi-line detail blocks, banner
delimiters, multi-sub-table output) go in `neterse/_compressors.py` as a
plain function, registered in **canonical order** in `registry.py` with an
explicit `dropped_fields` manifest. Look at `_compress_interfaces` (NX-OS
splits interface state across two lines) for the pattern. If you find
yourself proposing a new spec key that amounts to "run this little
program" — it's a code compressor.

Out-of-tree/private compressors don't need a PR at all:

```python
from neterse import register

@register(r"^show\s+my\s+thing", platforms=r"myvendor", dropped_fields=())
def _compress_my_thing(raw: str) -> str:
    ...
    return compact_or_raw
```

## Development setup

```bash
git clone https://github.com/pcDamasceno/neterse && cd neterse
pip install -e ".[test]"
pytest            # ~2000 tests, a couple of seconds, no network
```
