# Reference material — not shipped, not imported, not tested

Verbatim copies of tooling from **dbcli**, neterse's first consumer, kept
here as source material for work planned in
[../CONSUMER-HANDOFF.md](../CONSUMER-HANDOFF.md).

Nothing in this directory is part of the `neterse` package (`pyproject.toml`
packages `neterse` only), is collected by pytest (`testpaths = ["tests"]`),
or respects the zero-dependency invariant — these scripts import
sqlalchemy and langgraph and talk to a Postgres database.

| file | what it is | ported to |
|---|---|---|
| `dbcli_analyze_run.py` | Measures what the optimizer did to every device command in one agent run: per-command reduction table, covered-vs-uncovered split, ranked `NO COMPRESSOR` / `false-match:` opportunities. | `neterse audit` (Phase 3) — spec in CONSUMER-HANDOFF.md §4 |
| `dbcli_replay_parity.py` | Replays a real run's tool outputs through the frozen baseline *and* the current implementation, exits 1 on any byte difference. | `neterse audit --replay` (Phase 3) — same section |

Read them for the report shape and the heuristics (longest sample per
command, the 5% false-match threshold, ranking by raw chars). The
plumbing — Postgres queries, msgpack checkpoint decoding, the 500-char
`ooda_phases` caveat — is consumer-specific and does not port.
