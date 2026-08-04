# Consumer handoff — everything neterse needs from dbcli

*The plan lives in [DESIGN.md](DESIGN.md); Phases 2–4 are executed **here**.
But the facts that drive them — the seam neterse plugs into, how savings and
opportunities are measured, what real agent runs revealed, and what the
cutover actually costs — were learned in dbcli, neterse's first consumer.
This document carries them across so no future work in this repository
needs dbcli access.*

**Captured** 2026-08-03 from dbcli branch
`claude/token-optimization-scope-vv06oq` (commits `8cfe5909` NX-OS
compressors, `f436a88a` token-optimization skill + run analyzer,
`962c3a8a` per-run savings ledger, `3095000b` Phase-0 extraction).

**Updated** 2026-08-04: the Phase-4 cutover in §6 has been **executed**
on dbcli `main` (dbcli@5598e204, merged as 2300ac50). §1 describes the
pre-cutover state and stays as history; §6 records how the checklist
actually landed.

---

## 1. Consumer state at capture time — and the divergence (historical)

Until the Phase-4 cutover (§6), dbcli vendored the **Phase-0 cut** as
`dbcli/_incubator/showbrief` (package name `showbrief`, version 0.1.0),
reached through the re-export shim `dbcli/services/token_optimizer.py` —
the import path every call site, script, and historical test uses.
Phase 1 (spec engine, platform keying, lossiness manifests) landed
**here only** and was never back-ported.

| there (dbcli) | here (neterse) | state |
|---|---|---|
| `dbcli/_incubator/showbrief/__init__.py` | `neterse/__init__.py` | diverged: 0.1.0 vs 0.2.0 API surface (`register(platforms=, dropped_fields=)`, `iter_entries`) |
| `dbcli/_incubator/showbrief/_compressors.py` (21 KB, 15 families) | `neterse/_compressors.py` (13 KB, 6 families) + `specs.py` + `engine.py` + `registry.py` | diverged: 9 families became specs |
| `tests/showbrief/corpus.py` | `tests/corpus.py` | **byte-identical** |
| `tests/showbrief/legacy_snapshot.py` | `tests/legacy_snapshot.py` | identical but for the module docstring + logger name |
| `tests/showbrief/test_showbrief.py`, `test_parity.py` | `tests/test_neterse.py`, `test_parity.py` | ported |

**The divergence is a maintenance fact, not a correctness risk.** 0.2.0's
default path (no `platform=` argument) is byte-identical to the frozen
baseline — that is exactly what `tests/test_parity.py` pins, and both
repos freeze the *same* pre-extraction module as that baseline. dbcli can
therefore adopt neterse ≥ 0.2.0 without re-baselining anything, and there
is no reason to back-port Phase 1 into the vendored copy: it would be
work whose only outcome is a second copy to keep in sync until Phase 4
deleted it — as it now has.

---

## 2. The seam neterse plugs into (drives Phase 2)

`dbcli/modules/agents/tools/network_tools._optimize_show_output` — every
`execute_show_command` / `run_validation_command` result passes through
it on its way into LLM context:

```python
best, method = raw, None

if settings.agents.token_optimization:                 # default on
    toon = toon_optimize(command, raw)                 # ← neterse.optimize()
    if isinstance(toon, str) and len(toon) < len(best):
        best, method = toon, "toon"

if settings.agents.structured_tool_output:             # default on
    rows = svc.parse_raw_output(device.platform, command, raw)   # Genie → ntc-templates, offline
    if rows:
        payload = rows[0] if len(rows) == 1 else rows
        candidate = f"PARSED({command}) JSON:\n" + json.dumps(payload, separators=(",", ":"), default=str)
        if len(candidate) < len(best):
            best, method = candidate, "parse"

if method is not None:
    record_tool_output_savings(method, len(raw) - len(best))      # Prometheus, chars/4
record_show_optimization(command, len(raw), len(best), method)    # per-run ledger, §3
return best
```

What this tells us, and what it obliges:

- **Invariant 3 holds in the field.** The consumer owns smallest-wins,
  the metric, and the ledger. neterse must keep returning candidates and
  never selecting — Phase 2 does not get to change this shape.
- **The parsed tier already has a live competitor to beat.** dbcli's
  `"parse"` candidate is `json.dumps` over Genie/ntc-templates rows — a
  key-per-row encoding, which is precisely the shape neterse's parsed tier
  (project fields → header-once table) is meant to undercut.
  **Phase-2 acceptance test:** replay real parsed rows through both and
  compare characters; if the projection+encoder path does not beat
  `json.dumps(rows)` on multi-row output, the tier is not worth shipping.
  Note also that dbcli parses *offline* from raw text it already has —
  no second device round-trip — so neterse's `parsed=` argument is fed
  cheaply, and both tiers are always available for the same call.
- **Ordering gotcha with real consequences.** Compression runs *before*
  the downstream output cap (`agents.output_compaction_enabled` /
  `tool_output_max_chars`). Shrinking a 220-line
  `show interface counters errors` can turn a **truncated** tool result
  into a complete one — a correctness win, not merely a token win. Any
  future "is this family worth covering?" judgement must weigh
  truncation-flip, not just percentage saved.
- **Only the LLM copy is compressed.** The device, the GAIT audit trail,
  and snapshot capture all see raw text from their own seams. Nothing in
  neterse may assume it is the only reader of the output.
- Settings are read at process start: a compressor change needs a
  backend **and** celery worker restart on a running deployment.
- Fleet metric:
  `dbcli_agent_tool_output_tokens_saved_total{method=parse|toon|compact|delta}`,
  chars/4 — the same divisor `Candidate.est_tokens()` uses (decision 8).

---

## 3. The per-run ledger — where "opportunities" come from

`dbcli/modules/agents/token_economy_ledger.py` (stdlib-only leaf, a
ContextVar accumulator installed at the run edge) records **every**
outcome — winners *and* no-ops, the latter being exactly the signal that
a command reached the model un-shrunk. Its summary is persisted as
`agent_runs.token_optimization` (JSONB, alembic 025) and rendered in the
Agent History run detail:

```jsonc
{
  "totals": { "commands": 7, "calls": 12, "raw_chars": 48210, "optimized_chars": 21044,
              "saved_chars": 27166, "est_tokens_saved": 6791, "reduction_pct": 56.4 },
  "by_method": { "toon": { "calls": 9, "saved_chars": 24880 },
                 "parse": { "calls": 3, "saved_chars": 2286 } },
  "optimized":     [ { "command": …, "calls": …, "raw_chars": …, "optimized_chars": …,
                       "saved_chars": …, "reduction_pct": …, "method": "toon" } ],
  "opportunities": [ { "command": …, "calls": …, "raw_chars": …, "reduction_pct": 0.0 } ]
}
```

Conventions worth inheriting verbatim in `neterse audit` (§4), because
consumers already display them and a second definition would disagree
with the first:

| convention | value | why |
|---|---|---|
| chars per token | 4 | matches the Prometheus counter and `est_tokens()` |
| "opportunity" threshold | reduction **< 5%** | below that, a match is indistinguishable from no match |
| ranking | by total `raw_chars`, descending | biggest uncovered volume = next compressor's ROI |
| aggregation | per command string, across all calls in the run | one row per family, not per invocation |
| row caps | 20 optimized + 20 opportunities, command ≤ 120 chars | bounds a persisted report |

---

## 4. `neterse audit` — port spec (Phase 3)

The reference implementation is
[`docs/reference/dbcli_analyze_run.py`](reference/dbcli_analyze_run.py)
(verbatim copy; dbcli-coupled — Postgres + LangGraph + sqlalchemy). Port
the *report*, not the plumbing.

**Inputs.** dbcli's version reads a run's full tool-message history from
the LangGraph checkpointer (`checkpoint_blobs.channel='messages'`,
msgpack) because the run row's `ooda_phases[*].observation.raw_data`
truncates each result to 500 chars — sizes read from there under-report.
neterse has no database: take a corpus of `(command, platform?, raw)`
samples from files/directories/JSONL/stdin. Stdlib only, like everything
else here.

**Output — keep these columns, they earned their keep:**

```
  n     raw    neterse  red%   entry                        command
  3   18244     6120   66%   ios/show_ip_route            show ip route
  1    9877     9877    0%   -                            show ip ospf database
--------------------------------------------------------------------------------
TOTAL device output: raw=…  neterse=…  reduction=…%
covered-by-an-entry=…  uncovered=…

OPPORTUNITIES (>=5% reduction not achieved), largest first:
     9877 chars  NO COMPRESSOR              show ip ospf database
     4102 chars  false-match:_compress_…    show interface transceiver
```

**Heuristics to preserve:** representative sample per command =
the *longest* one; `NO COMPRESSOR` = no entry pattern matched;
`false-match:<entry>` = a pattern matched but reduction < 5% (harmless
under smallest-wins, but it hides the gap and means the regex is too
broad); `--show N` dumps the head of the N largest gaps so the format can
be read before a spec is written.

**Additions the 0.2.0 registry makes possible** (dbcli's version predates
them): report entries **skipped by the platform filter** for each sample
(a false match that platform scoping already kills is not a gap), and
print each matched entry's declared `dropped_fields` so an audit doubles
as a lossiness review.

**Also port the parity replay** —
[`docs/reference/dbcli_replay_parity.py`](reference/dbcli_replay_parity.py):
run a corpus through `tests/legacy_snapshot.py` and through current
`neterse`, exit 1 on any byte difference. This proves on real data what the
fixture suite proves on fixtures; from Phase 1 on, diffs must be
**confined to the family you intentionally changed**. One caveat carried
over verbatim: checkpointed tool messages hold the representation that
*won* smallest-wins (raw, compressed, or parsed JSON), not necessarily
raw device text. That is fine for parity — `optimize()` must behave
identically on any input string — but a golden **raw** corpus must be
captured with optimization disabled, or from GAIT/snapshot sinks.

---

## 5. Field notes from real runs

Learned by analyzing production agent runs; they are why several specs
look the way they do, and they are the checklist for multi-vendor
expansion:

- **NX-OS vs IOS is not cosmetic.** `Ethernet1/x` naming; interface state
  split across two lines (`… is up` then `admin state is up`); lowercase
  `full-duplex`; different column sets in otherwise same-named tables.
  Add a variant, never force one shape onto both.
- **Per-interface parsers claim table subcommands** unless the regex
  excludes them (`status|brief|counters|transceiver|…` negative
  lookahead). Smallest-wins makes the false match harmless, but it
  reports as coverage that does not exist.
- **The big win is mostly-zero tables.** `show interface counters errors`
  at 220+ lines is the canonical truncation-flip case (§2) — suppress
  all-zero rows, keep an explicit `(all zero)` marker so absence stays
  visible.
- Commands agents actually type are not the canonical spellings —
  abbreviations, `| include` pipes, and per-interface variants all show
  up. Fixtures should pair a raw body with *every* spelling seen
  (`COMMAND_FIXTURES` already does this).

---

## 6. Phase-4 cutover checklist (dbcli side)

**Executed** 2026-08-04 in dbcli@5598e204 (merged as 2300ac50), exactly
as written below — with one refinement to step 1: until the first PyPI
release the dependency is **commit-pinned** as a git requirement
(`neterse @ git+https://github.com/pcDamasceno/neterse.git@<commit>`);
it becomes `neterse>=0.4` once published. Step 6 (restart) is a
per-deployment action, not a repo change.

No alembic migration, no deployment topology change — the package ships
inside the image via pip, where it previously shipped inside `dbcli/`.

1. Add `neterse>=0.2.0` to `requirements.txt` (+ `requirements.lock`).
2. Flip the shim body in `dbcli/services/token_optimizer.py` to
   `from neterse import optimize, render, register, iter_compressors, Candidate`.
   **Keep the shim** — every call site, the analyzer scripts, and the
   historical tests import through it.
3. Delete `dbcli/_incubator/showbrief/`.
4. Tests: delete `tests/showbrief/` (neterse's CI owns those suites now) but
   keep `tests/services/test_token_optimizer.py` as the shim guard and
   `tests/agents/test_structured_show_output.py` as the seam guard — they
   are the consumer-side contract, and they are what would catch a bad
   pip upgrade.
5. Update `.claude/skills/token-optimization/SKILL.md` paths (Step 3 edits
   move to a neterse PR) and the analyzer's import.
6. Restart backend + celery workers.

Consumers keep the ledger, the Prometheus counter, the run-detail UI, and
the smallest-wins policy. None of that comes here (invariant 3).

---

## 7. Pointers, if dbcli access is ever available again

| what | where in dbcli |
|---|---|
| the seam | `dbcli/modules/agents/tools/network_tools.py::_optimize_show_output` |
| per-run ledger | `dbcli/modules/agents/token_economy_ledger.py` |
| shim consumers import | `dbcli/services/token_optimizer.py` |
| vendored Phase-0 copy | deleted in the Phase-4 cutover (dbcli@5598e204); the dependency pin lives in `requirements.txt` |
| the working loop, written down | `.claude/skills/token-optimization/SKILL.md` |
| run analyzer | `.claude/skills/token-optimization/scripts/analyze_run.py` (the parity replay now lives here only: `scripts/replay_parity.py`) |
| seam + ledger tests | `tests/agents/test_structured_show_output.py`, `tests/agents/test_token_economy_ledger.py` |
