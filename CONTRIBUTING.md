# Contributing to neterse

Most contributions are **one YAML file plus fixtures — no parser code,
no registry edit.** The bar is deliberately low; the CI gates are
deliberately strict.

## Add a table-shaped command family (the common case)

1. **Write the spec** as `neterse/specs/<platform>/<family>.yaml` — the
   vendor/command layout ntc-templates made familiar. The spec's id IS
   the path (`arista_eos/show_ip_arp`); don't write an `id` key.

```yaml
# show ip arp (Arista EOS) -> CSV.
command: 'show\s+ip\s+arp'    # scope tightly; exclude sibling subcommands
platforms: 'eos|arista'       # regex over the caller's platform string; declare broadly
strategy: line_regex_table    # or fixed_width_table / kv_extract
#      1: address   2: age   3: MAC   4: interface(s)
row: '^(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s+(\S+)\s+(\S+)'
header: address,age,mac,interface
dropped_fields: []            # REQUIRED: the lossiness manifest ([] = lossless)
```

   Quote regexes with **single quotes** (or a `|-` block scalar for
   multi-line `VERBOSE` patterns — see `cisco/show_ip_route.yaml`) so
   backslashes stay literal; YAML double quotes would reject `\s`. The
   existing files under `neterse/specs/` are the reference for every
   field, including `profiles`, `row_flags`, `columns`,
   `context_prefixes` and the `fixed_width_table` / `kv_extract`
   strategies.

2. **Compile it**: run

   ```bash
   python scripts/compile_specs.py
   ```

   This validates the spec **loudly** — the command/row regexes must
   compile, header arity must match the captured groups (or `keywords`),
   profiles must keep real columns and drop at least one, the manifest
   is mandatory, unknown keys are rejected — and regenerates
   `neterse/specs/_compiled.py`, the plain-Python module the runtime
   imports (YAML never becomes a runtime dependency). Commit the YAML
   **and** the regenerated file together; CI diff-gates them
   (`compile_specs.py --check`), and so does the test suite.

   No registry edit needed: specs without an explicit position in the
   canonical order self-append after it, in sorted-id order
   (decision 28).

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
   family's output and the edge inputs; the spec tests re-validate every
   YAML source and reject undeclared manifests. If the token CI job
   flags a missing baseline entry, run
   `python scripts/update_token_baseline.py` and commit the diff.

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
- **Zero runtime dependencies.** The package imports the standard library
  only — which is exactly why the YAML sources are compiled to
  `_compiled.py` instead of parsed at import time. PyYAML lives in the
  `test` extra; parsers (ntc-templates) live in the `textfsm` extra. If
  your idea needs another dependency, open an issue first.
- **Byte-parity discipline.** Don't edit the *code* in
  `tests/legacy_snapshot.py`, ever, and don't hand-edit the *generated*
  `neterse/specs/_compiled.py` — it gets regenerated over you.
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
pip install -e ".[test]"      # pytest + PyYAML (spec authoring/drift gate)
pytest                        # ~2000 tests, a couple of seconds, no network
```
