"""``neterse audit`` — coverage report over a corpus of real command outputs.

A port of the original run analyzer: the *report* without the plumbing.
That version read a LangGraph checkpointer;
neterse has no database — feed it ``(command, platform?, raw)`` samples
from JSONL files, fixture directories, or stdin, and it shows what the
registry does with each family and, more importantly, what it misses:

* ``NO COMPRESSOR`` — no entry pattern matches the command at all.
* ``false-match:<entry>`` — a pattern matched but reduction stayed under
  5% (harmless under smallest-wins, but it reports as coverage that does
  not exist and means the regex is too broad).
* ``platform-skip:<entry>`` — patterns matched but the platform filter
  skipped every one of them (a false match that scoping already kills is
  not a gap).

Conventions inherited verbatim from the first consumer's ledger so both
ends agree: chars/4 per token,
opportunity threshold = reduction < 5%, ranked by total raw chars
descending, aggregated per command string.

Inputs (mix freely; ``-`` = stdin JSONL):

* ``*.jsonl`` — one object per line: ``{"command": ..., "raw": ...,
  "platform": ...?}`` (``output`` accepted as an alias of ``raw``).
* a directory — the fixture layout: ``<platform>/<family>/commands.txt``
  (one spelling per line) + ``raw.txt`` (byte-exact body).
* any other file with ``--command`` — audit one raw capture directly.

``--show N`` prints the head of the N largest gaps so the format can be
read before a spec is written; ``--fail-under PCT`` makes the exit code
CI-friendly. Stdlib only, like everything else here.

``neterse coverage`` answers the question BEFORE any capture exists —
"is show X on vendor Y covered?" — by listing every registry entry
(spec- and code-tier alike) with its command pattern, platform scope,
profiles, and declared drops, in canonical order.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from . import __version__, render, render_parsed
from .registry import iter_entries

# (command, platform or None, raw)
Sample = Tuple[str, Optional[str], str]

OPPORTUNITY_PCT = 5.0        # below this, a match is indistinguishable from none
CHARS_PER_TOKEN = 4          # ledger/Prometheus convention (decision 8)
WIDTH = 100


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

def _iter_jsonl(lines: Iterable[str], origin: str) -> Iterable[Sample]:
    for n, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError as exc:
            raise SystemExit(f"{origin}:{n}: not JSON: {exc}")
        if not isinstance(obj, dict):
            raise SystemExit(f"{origin}:{n}: expected an object per line")
        command = obj.get("command")
        raw = obj.get("raw", obj.get("output"))
        if not isinstance(command, str) or not command.strip() or not isinstance(raw, str):
            raise SystemExit(
                f"{origin}:{n}: need string fields 'command' and 'raw' (or 'output')"
            )
        platform = obj.get("platform")
        if platform is not None and not isinstance(platform, str):
            raise SystemExit(f"{origin}:{n}: 'platform' must be a string or null")
        platform_key = platform.strip() or None if platform is not None else None
        yield command.strip(), platform_key, raw


def _iter_fixture_dir(root: Path) -> Iterable[Sample]:
    found = False
    for raw_path in sorted(root.rglob("raw.txt")):
        cmds_path = raw_path.parent / "commands.txt"
        if not cmds_path.is_file():
            continue
        found = True
        # fixtures/<platform>/<family>/raw.txt → platform from the grandparent
        platform = raw_path.parent.parent.name or None
        raw = raw_path.read_text()
        for command in cmds_path.read_text().splitlines():
            command = command.strip()
            if command and not command.startswith("#"):
                yield command, platform, raw
    if not found:
        raise SystemExit(
            f"{root}: no <platform>/<family>/commands.txt + raw.txt pairs found"
        )


def load_samples(paths: List[str], command: Optional[str]) -> List[Sample]:
    samples: List[Sample] = []
    for spec in paths:
        if spec == "-":
            samples.extend(_iter_jsonl(sys.stdin, "stdin"))
            continue
        p = Path(spec)
        if p.is_dir():
            samples.extend(_iter_fixture_dir(p))
        elif p.suffix == ".jsonl":
            with p.open() as fh:
                samples.extend(_iter_jsonl(fh, str(p)))
        elif p.is_file():
            if not command:
                raise SystemExit(
                    f"{p}: raw capture files need --command 'show ...'"
                )
            samples.append((command, None, p.read_text()))
        else:
            raise SystemExit(f"{spec}: no such file or directory")
    return samples


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _match_names(command: str, platform: Optional[str]) -> Tuple[List[str], List[str]]:
    """(entries whose pattern matches, the subset the platform filter skips)."""
    plat = platform.lower() if platform else None
    matched: List[str] = []
    skipped: List[str] = []
    for e in iter_entries():
        if not e.pattern.search(command):
            continue
        matched.append(e.name)
        if plat and e.platforms and not e.platforms.search(plat):
            skipped.append(e.name)
    return matched, skipped


def _best_len(command: str, platform: Optional[str], raw: str) -> Tuple[int, Optional[str], Optional[Tuple[str, ...]]]:
    """(winning length, winning entry name, its dropped_fields) — first
    smallest wins, or raw when nothing shrinks (optimize() semantics)."""
    best = None
    for c in render(raw, command=command, platform=platform):
        if best is None or len(c.text) < len(best.text):
            best = c
    if best is None:
        return len(raw), None, None
    return len(best.text), best.source, best.dropped_fields


def run_report(samples: List[Sample], show: int, out=None) -> float:
    """Print the coverage report; return the total reduction percentage."""
    # Resolve stdout at call time — a def-time default would bypass
    # redirected/captured streams.
    w = (out if out is not None else sys.stdout).write

    fam: dict = {}
    for command, platform, raw in samples:
        fam.setdefault((command, platform), []).append(raw)

    w("=" * WIDTH + "\n")
    w(f"neterse {__version__} audit: {len(samples)} samples, "
      f"{len(fam)} command families\n")
    w("=" * WIDTH + "\n")
    w(f"{'n':>3} {'raw':>8} {'neterse':>8} {'red%':>5}  "
      f"{'entry':<38} command\n")
    w("-" * WIDTH + "\n")

    tot_raw = tot_new = cov = unc = 0
    opportunities: list = []
    drops_seen: dict = {}
    heads: dict = {}

    ordered = sorted(
        fam.items(), key=lambda kv: -sum(len(o) for o in kv[1])
    )
    for (command, platform), outs in ordered:
        rep = max(outs, key=len)
        raw_len = len(rep)
        new_len, entry, dropped = _best_len(command, platform, rep)
        red = 100 * (1 - new_len / raw_len) if raw_len else 0.0
        matched, skipped = _match_names(command, platform)
        effective = [m for m in matched if m not in skipped]
        total_raw = sum(len(o) for o in outs)
        for o in outs:
            tot_raw += len(o)
            tot_new += _best_len(command, platform, o)[0]
        if effective:
            cov += total_raw
        else:
            unc += total_raw
        if entry and dropped:
            drops_seen[entry] = dropped
        label = command if not platform else f"{command}  [{platform}]"
        if red < OPPORTUNITY_PCT:
            if not matched:
                tag = "NO COMPRESSOR"
            elif not effective:
                tag = f"platform-skip:{skipped[0]}"
            else:
                tag = f"false-match:{effective[0]}"
            opportunities.append((total_raw, label, tag))
            heads[label] = rep
        w(f"{len(outs):>3} {raw_len:>8} {new_len:>8} {red:>4.0f}%  "
          f"{(entry or '-'):<38} {label[:44]}\n")

    w("-" * WIDTH + "\n")
    total_red = 100 * (1 - tot_new / tot_raw) if tot_raw else 0.0
    if tot_raw:
        w(f"TOTAL device output: raw={tot_raw}  neterse={tot_new}  "
          f"reduction={total_red:.0f}%  "
          f"(~{(tot_raw - tot_new) // CHARS_PER_TOKEN} tokens saved at "
          f"chars/{CHARS_PER_TOKEN})\n")
        w(f"covered-by-an-entry={cov}  uncovered={unc}\n")

    if drops_seen:
        w("\nDECLARED DROPS (winning entries — the lossiness review):\n")
        for entry in sorted(drops_seen):
            w(f"  {entry:<44} {', '.join(drops_seen[entry])}\n")

    opportunities.sort(key=lambda t: (-t[0], t[1]))
    if opportunities:
        w(f"\nOPPORTUNITIES (>={OPPORTUNITY_PCT:.0f}% reduction not achieved), "
          "largest first:\n")
        for total_raw, label, tag in opportunities:
            w(f"  {total_raw:>8} chars  {tag:<40} {label[:120]}\n")
        for total_raw, label, tag in opportunities[:show]:
            rep = heads[label]
            w("\n" + "#" * 78 + "\n")
            w(f"# {label}   ({tag})   head (20 lines of "
              f"{len(rep.splitlines())}):\n")
            w("#" * 78 + "\n")
            w("\n".join(rep.splitlines()[:20]) + "\n")
    return total_red


def run_coverage(out=None) -> None:
    """List every registry entry — the "what's covered?" answer that
    needs no captures (README's Coverage prose, generated instead of
    hand-maintained)."""
    w = (out if out is not None else sys.stdout).write

    entries = iter_entries()
    specs = sum(1 for e in entries if e.name.startswith("spec:"))
    w(f"neterse {__version__}: {len(entries)} command families "
      f"({specs} specs, {len(entries) - specs} code compressors)\n")
    w(f"{'entry':<46} {'platforms':<28} {'profiles':<10} "
      "dropped_fields\n")
    w("-" * WIDTH + "\n")
    for e in entries:
        platforms = e.platforms.pattern if e.platforms else "(any)"
        profiles = ",".join(sorted(e.profiles)) if e.profiles else "-"
        if e.dropped_fields is None:
            drops = "(undeclared)"
        elif not e.dropped_fields:
            drops = "lossless"
        else:
            drops = ", ".join(e.dropped_fields)
        w(f"{e.name:<46} {platforms:<28} {profiles:<10} {drops}\n")
        w(f"    command ~ {e.pattern.pattern}\n")


def _audit_json(samples: List[Sample]) -> dict:
    """Machine-readable savings and omissions, without capture contents."""
    results = []
    total_raw = total_new = 0
    for command, platform, raw in samples:
        size, source, dropped = _best_len(command, platform, raw)
        total_raw += len(raw)
        total_new += size
        results.append({
            "command": command, "platform": platform,
            "raw_chars": len(raw), "output_chars": size,
            "source": source, "dropped_fields": dropped,
        })
    return {
        "version": __version__,
        "samples": results,
        "totals": {
            "raw_chars": total_raw, "output_chars": total_new,
            "saved_chars": total_raw - total_new,
            "reduction_pct": 100 * (1 - total_new / total_raw) if total_raw else 0.0,
        },
    }


def _compact_capture(args: argparse.Namespace) -> int:
    """Compact one capture; explanation is metadata on stderr only."""
    try:
        if args.path == "-":
            content = getattr(sys.stdin, "buffer", sys.stdin).read()
            raw = content.decode("utf-8") if isinstance(content, bytes) else content
        else:
            with Path(args.path).open(encoding="utf-8", newline="") as stream:
                raw = stream.read()
        if args.input_format == "json":
            value = json.loads(raw)
            baseline = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
            candidates = render_parsed(value, profile=args.profile)
            fallback = "json"
        else:
            from . import ntc

            rows = ntc.parse(raw, command=args.command, platform=args.platform) if (
                args.command and args.platform
            ) else None
            baseline = raw
            candidates = render(
                raw, command=args.command or "", platform=args.platform,
                parsed=rows, profile=args.profile,
            )
            fallback = "raw"
    except (OSError, UnicodeError, ValueError) as exc:
        raise SystemExit(f"neterse compact: {exc}") from None
    eligible = [c for c in candidates if not args.lossless_only or c.dropped_fields == ()]
    best = min(eligible, key=lambda c: len(c.text), default=None)
    output = best.text if best is not None else baseline
    sys.stdout.write(output)
    if args.explain:
        print(json.dumps({
            "source": best.source if best else fallback,
            "profile": best.profile if best else "default",
            "dropped_fields": best.dropped_fields if best else [],
            "raw_chars": len(raw), "output_chars": len(output),
            "candidates": [
                {"source": c.source, "chars": len(c.text), "dropped_fields": c.dropped_fields}
                for c in candidates
            ],
        }), file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="neterse",
        description="Minimum-token renderings of network CLI output "
                    "for LLM agents.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="subcommand", required=True)

    compact = sub.add_parser("compact", help="compact a raw CLI or JSON capture (stdin by default)")
    compact.add_argument("path", nargs="?", default="-", help="UTF-8 capture file, or - for stdin")
    compact.add_argument("--command", help="command that produced a raw CLI capture")
    compact.add_argument("--platform", help="platform used for raw compression and optional TextFSM parsing")
    compact.add_argument("--input-format", choices=("raw", "json"), default="raw")
    compact.add_argument("--profile", default="default")
    compact.add_argument("--lossless-only", action="store_true", help="select only candidates declaring no dropped fields")
    compact.add_argument("--explain", action="store_true", help="write selection and omission metadata as JSON to stderr")

    audit = sub.add_parser(
        "audit",
        help="coverage report over a corpus of (command, platform?, raw) samples",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    audit.add_argument(
        "--json", action="store_true", help="emit a JSON report without raw capture contents",
    )
    audit.add_argument(
        "paths", nargs="+",
        help="JSONL file(s), fixture directory(ies), raw capture file "
             "(with --command), or - for stdin JSONL",
    )
    audit.add_argument(
        "--command",
        help="command string for plain raw capture files",
    )
    audit.add_argument(
        "--show", type=int, default=0, metavar="N",
        help="print the head of the N largest uncovered outputs",
    )
    audit.add_argument(
        "--fail-under", type=float, default=None, metavar="PCT",
        help="exit 1 when the total reduction falls below PCT",
    )
    sub.add_parser(
        "coverage",
        help="list every covered command family (no captures needed): "
             "entry, command pattern, platform scope, profiles, declared drops",
    )
    args = parser.parse_args(argv)

    if args.subcommand == "compact":
        return _compact_capture(args)

    if args.subcommand == "coverage":
        # `neterse coverage | head` closing the pipe early is normal use,
        # not an error. Scoped to the listing ONLY: the audit path's
        # --fail-under exists for its exit code, and swallowing EPIPE
        # there would flip a failing gate to passing.
        try:
            run_coverage()
        except BrokenPipeError:
            # Detach stdout so interpreter shutdown doesn't print a
            # secondary complaint while flushing.
            import os

            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0

    samples = load_samples(args.paths, args.command)
    if args.json:
        report = _audit_json(samples)
        print(json.dumps(report, indent=2))
        total_red = report["totals"]["reduction_pct"]
    elif not samples:
        print("No samples found.")
        total_red = 0.0
    else:
        total_red = run_report(samples, show=args.show)
    if args.fail_under is not None and total_red < args.fail_under:
        print(f"\nFAIL: total reduction {total_red:.1f}% "
              f"< --fail-under {args.fail_under:.1f}%",
              file=sys.stderr if args.json else sys.stdout)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
