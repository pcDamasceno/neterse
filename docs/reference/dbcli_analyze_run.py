#!/usr/bin/env python3
"""Analyze a dbcli agent run's device-command tool outputs and measure what the
TOON optimizer does with each one (the incubated showbrief package at
dbcli/_incubator/showbrief, imported via the dbcli.services.token_optimizer
shim).

Read-only. Surfaces compression opportunities: commands with NO compressor,
commands where a compressor matches but yields ~0% (format mismatch / false
match), and the covered-vs-uncovered split for the run.

Run with the dbcli venv from the repo root:

    DATABASE_URL=postgresql+asyncpg://dbcli:dbcli@localhost:15432/dbcli \\
      PYTHONPATH=. .venv/bin/python \\
      .claude/skills/token-optimization/scripts/analyze_run.py [--run-id UUID] [--show 3]

Data sources:
  * agent_runs        — newest row (or --run-id) -> thread_id
  * checkpoint_blobs  — channel 'messages' (msgpack) for that thread = the FULL
                        tool-message history. (ooda_phases.raw_data truncates to
                        500 chars/tool, so use the checkpointer for real sizes.)
"""
from __future__ import annotations

import argparse
import asyncio
import os
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from dbcli.services.token_optimizer import optimize, _COMPRESSORS

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://dbcli:dbcli@localhost:15432/dbcli"
)
SERDE = JsonPlusSerializer()
DEVICE_TOOLS = ("execute_show_command", "run_validation_command")


def _content_str(c) -> str:
    """Coerce a ToolMessage.content (str or Anthropic block list) to text."""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(
            (b.get("text") or "") if isinstance(b, dict) else str(b) for b in c
        )
    return str(c)


def _matched(cmd: str) -> list[str]:
    """Names of every registered compressor whose pattern matches *cmd*."""
    return [fn.__name__ for pat, fn in _COMPRESSORS if pat.search(cmd)]


async def _load(run_id, thread_id):
    eng = create_async_engine(DB_URL)
    meta: dict = {}
    async with eng.connect() as c:
        if not thread_id:
            where = "WHERE id = :rid" if run_id else ""
            row = (
                await c.execute(
                    text(
                        "SELECT id, thread_id, timestamp, user_message, total_tokens, "
                        f"llm_call_count FROM agent_runs {where} "
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


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", help="agent_runs.id (default: newest run)")
    ap.add_argument("--thread-id", help="skip agent_runs; read this thread directly")
    ap.add_argument("--show", type=int, default=0,
                    help="print the head of the N largest uncovered outputs")
    args = ap.parse_args()

    meta, blob = await _load(args.run_id, args.thread_id)
    if not blob:
        print("No run / messages blob found.")
        return
    msgs = SERDE.loads_typed(("msgpack", blob))

    # tool_call_id -> {name, args}
    call: dict = {}
    for m in msgs:
        for tc in (getattr(m, "tool_calls", None) or []):
            call[tc.get("id")] = {"name": tc.get("name"), "args": tc.get("args") or {}}

    fam: dict[str, list[str]] = defaultdict(list)
    tool_counts: dict[str, int] = defaultdict(int)
    for m in msgs:
        if m.__class__.__name__ != "ToolMessage":
            continue
        mc = call.get(getattr(m, "tool_call_id", None), {})
        name = mc.get("name") or getattr(m, "name", "unknown")
        tool_counts[name] += 1
        if name in DEVICE_TOOLS:
            cmd = (mc.get("args", {}).get("command") or "").strip()
            fam[cmd].append(_content_str(getattr(m, "content", "")))

    print("=" * 92)
    print("RUN", meta.get("id", meta.get("thread_id")))
    if meta.get("timestamp"):
        print("when   :", meta["timestamp"])
    if meta.get("user_message"):
        print("ask    :", str(meta["user_message"])[:120])
    print("tokens :", meta.get("total_tokens"), " llm_calls:", meta.get("llm_call_count"))
    print("tools  :", dict(tool_counts))
    print("=" * 92)

    if not fam:
        print("No execute_show_command / run_validation_command outputs in this run.")
        return

    print(f"{'n':>3} {'raw':>7} {'toon':>7} {'red%':>5}  {'compressor':<28} command")
    print("-" * 92)
    tot_raw = tot_new = cov = unc = 0
    opportunities: list[tuple[int, str, str]] = []
    for cmd, outs in sorted(fam.items(), key=lambda x: -sum(len(o) for o in x[1])):
        rep = max(outs, key=len)
        raw = len(rep)
        new = len(optimize(cmd, rep))
        red = 100 * (1 - new / raw) if raw else 0
        comps = _matched(cmd)
        comp = comps[0] if comps else "-"
        total_raw = sum(len(o) for o in outs)
        for o in outs:
            tot_raw += len(o)
            tot_new += len(optimize(cmd, o))
        if comps:
            cov += total_raw
        else:
            unc += total_raw
        if red < 5:
            opportunities.append((total_raw, cmd, comp))
        print(f"{len(outs):>3} {raw:>7} {new:>7} {red:>4.0f}%  {comp:<28} {cmd[:42]}")

    print("-" * 92)
    if tot_raw:
        print(f"TOTAL device output: raw={tot_raw}  toon={tot_new}  "
              f"reduction={100 * (1 - tot_new / tot_raw):.0f}%")
        print(f"covered-by-a-compressor={cov}  uncovered={unc}")

    opportunities.sort(reverse=True)
    if opportunities:
        print("\nOPPORTUNITIES (>=5% reduction not achieved), largest first:")
        for total_raw, cmd, comp in opportunities:
            tag = "NO COMPRESSOR" if comp == "-" else f"false-match:{comp}"
            print(f"  {total_raw:>7} chars  {tag:<26} {cmd}")
        for total_raw, cmd, comp in opportunities[: args.show]:
            tag = "NO COMPRESSOR" if comp == "-" else f"false-match:{comp}"
            rep = max(fam[cmd], key=len)
            print("\n" + "#" * 78)
            print(f"# {cmd}   ({tag})   head (20 lines of {len(rep.splitlines())}):")
            print("#" * 78)
            print("\n".join(rep.splitlines()[:20]))


if __name__ == "__main__":
    asyncio.run(main())
