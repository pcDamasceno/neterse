#!/usr/bin/env python3
"""Replay a real agent run's device-command tool outputs through the frozen
Phase-0 baseline (tests/showbrief/legacy_snapshot.py) AND the current
optimizer (dbcli/_incubator/showbrief via the dbcli.services.token_optimizer
shim), and report any byte-level difference.

Purpose: prove on production data what the in-repo parity suite proves on
fixtures. During Phase 0 (verbatim extraction) any diff is a porting bug.
From Phase 1 on (spec-engine conversions), run it per-change: diffs must be
confined to the command family you intentionally changed.

Note on inputs: checkpointed ToolMessages hold the representation that WON
the smallest-wins selection (raw, TOON, or parsed JSON) — not always raw
device text. That is fine for parity: optimize() must behave identically on
ANY input string. For golden RAW corpora, capture with token_optimization
disabled or from GAIT/snapshots instead.

Read-only. Run from the repo root:

    DATABASE_URL=postgresql+asyncpg://dbcli:dbcli@localhost:15432/dbcli \\
      PYTHONPATH=. .venv/bin/python \\
      .claude/skills/token-optimization/scripts/replay_parity.py [--run-id UUID]
      [--thread-id UUID] [--max-diffs 3]

Exit status: 0 = parity everywhere, 1 = at least one diff (CI-friendly).
"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import os
import sys
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from dbcli.services.token_optimizer import optimize as current_optimize
from tests.showbrief.legacy_snapshot import optimize as baseline_optimize

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://dbcli:dbcli@localhost:15432/dbcli"
)
SERDE = JsonPlusSerializer()
DEVICE_TOOLS = ("execute_show_command", "run_validation_command")


def _content_str(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(
            (b.get("text") or "") if isinstance(b, dict) else str(b) for b in c
        )
    return str(c)


async def _load(run_id, thread_id):
    eng = create_async_engine(DB_URL)
    meta: dict = {}
    async with eng.connect() as c:
        if not thread_id:
            where = "WHERE id = :rid" if run_id else ""
            row = (
                await c.execute(
                    text(
                        "SELECT id, thread_id, timestamp, user_message "
                        f"FROM agent_runs {where} "
                        "ORDER BY timestamp DESC LIMIT 1"
                    ),
                    {"rid": run_id} if run_id else {},
                )
            ).mappings().first()
            if not row:
                await eng.dispose()
                return None, None
            thread_id = row["thread_id"]
            meta = dict(row)
        else:
            meta = {"thread_id": thread_id}
        blob = (
            await c.execute(
                text(
                    "SELECT blob FROM checkpoint_blobs WHERE thread_id=:t "
                    "AND channel='messages' AND type='msgpack' "
                    "ORDER BY octet_length(blob) DESC LIMIT 1"
                ),
                {"t": thread_id},
            )
        ).scalar()
    await eng.dispose()
    return meta, blob


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", help="agent_runs.id (default: newest run)")
    ap.add_argument("--thread-id", help="skip agent_runs; read this thread directly")
    ap.add_argument("--max-diffs", type=int, default=3,
                    help="print a unified diff for the first N mismatches")
    args = ap.parse_args()

    meta, blob = await _load(args.run_id, args.thread_id)
    if not blob:
        print("No run / messages blob found.")
        return 0
    msgs = SERDE.loads_typed(("msgpack", blob))

    call: dict = {}
    for m in msgs:
        for tc in (getattr(m, "tool_calls", None) or []):
            call[tc.get("id")] = {"name": tc.get("name"), "args": tc.get("args") or {}}

    pairs: list[tuple[str, str]] = []
    for m in msgs:
        if m.__class__.__name__ != "ToolMessage":
            continue
        mc = call.get(getattr(m, "tool_call_id", None), {})
        if (mc.get("name") or getattr(m, "name", "")) in DEVICE_TOOLS:
            cmd = (mc.get("args", {}).get("command") or "").strip()
            pairs.append((cmd, _content_str(getattr(m, "content", ""))))

    print(f"run {meta.get('id', meta.get('thread_id'))}: "
          f"replaying {len(pairs)} device tool outputs")
    diffs = 0
    per_cmd: dict[str, int] = defaultdict(int)
    for i, (cmd, body) in enumerate(pairs):
        base = baseline_optimize(cmd, body)
        cur = current_optimize(cmd, body)
        if base == cur:
            continue
        diffs += 1
        per_cmd[cmd] += 1
        if diffs <= args.max_diffs:
            print(f"\nDIFF #{diffs}  cmd={cmd!r}  "
                  f"baseline={len(base)}ch current={len(cur)}ch")
            for line in difflib.unified_diff(
                base.splitlines(), cur.splitlines(),
                "baseline", "current", lineterm="", n=2,
            ):
                print("  " + line)

    if diffs:
        print(f"\nPARITY FAILED: {diffs}/{len(pairs)} outputs differ")
        for cmd, n in sorted(per_cmd.items(), key=lambda x: -x[1]):
            print(f"  {n:>4}x  {cmd}")
        return 1
    print(f"PARITY OK: {len(pairs)}/{len(pairs)} outputs byte-identical")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
