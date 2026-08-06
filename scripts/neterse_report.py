#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "gcf-python>=2.4",
#     "toon-format>=0.9.0b1",
#     "tiktoken",
# ]
# ///
# ^ PEP 723 inline metadata, so `uv run scripts/neterse_report.py …` gets
# the reference encoders and the tokenizer without a prepared
# environment. `uv run` otherwise builds an env from pyproject, where
# `dependencies = []` is a deliberate invariant — the report then runs but
# silently reports no parsed:toon/parsed:gcf and no real token counts,
# which reads as a broken tool rather than a bare environment.
#
# neterse itself is NOT declared: the sys.path insert below pins it to
# this checkout, which is the point of a repo-local report tool. Python
# >=3.10 is toon-format's floor, above the package's own >=3.9.
"""Every candidate neterse can produce for one input, with token accounting.

The library returns candidates, not policy (invariant 3), and
``optimize``/``compact`` collapse that to ``min(..., key=len)`` — so the
winner alone tells you nothing about what was rejected, what it cost, or
what it dropped. This prints the whole option space for a payload you are
holding, which is what you want when deciding how to feed a source into
context, or when checking that a change did what you meant:

    python scripts/neterse_report.py payload.json
    python scripts/neterse_report.py payload.json --key events --show
    python scripts/neterse_report.py payload.json --profile updown
    curl -s https://apic/api/class/fvTenant.json | python scripts/neterse_report.py -
    python scripts/neterse_report.py capture.txt --raw \
        --command "show ip interface brief" --platform cisco_ios

Two things it exists to make visible:

* **The right baseline.** ``render()`` competes against the raw device
  text; ``render_parsed()`` competes against the compact JSON a consumer
  would otherwise paste. A percentage against the wrong denominator is
  meaningless, so the header always names the one in use.
* **Why a spec format declined.** ``parsed:toon`` / ``parsed:gcf`` are
  fail-open: an unrepresentable shape yields no candidate and no
  explanation. This re-walks the eligibility rules and NAMES the
  disqualifying column.

Token columns show ``est`` (``Candidate.est_tokens()`` — chars/4, what the
library uses at runtime, decision 8) beside ``real`` (the encoding
``tests/token_metrics.py`` pins for CI). They diverge a lot on compressed
output: est routinely overstates savings by ~20 points, because dense
delimited text tokenizes far worse per character than the verbose text it
replaced. ``saved`` is therefore computed on real tokens whenever
tiktoken is importable, and falls back to characters when it is not.

This lives in scripts/, not the package: it depends on tiktoken and on
the tests' pinned encoding, neither of which the zero-dependency runtime
may touch.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from neterse import render, render_parsed                     # noqa: E402
# Private, and used ONLY to explain declines: if these move, the report
# still works and just loses its diagnosis.
from neterse.parsed import _columns, _rows                    # noqa: E402

try:
    import tiktoken
    from tests.token_metrics import ENCODING     # one encoding, shared with CI
    _ENC = tiktoken.get_encoding(ENCODING)
except Exception:                                # optional, never required
    _ENC, ENCODING = None, None

SPEC_FORMATS = ("parsed:toon", "parsed:gcf")


def _installed(module: str) -> bool:
    try:
        __import__(module)
    except Exception:
        return False
    return True


def tokens(text: str):
    """Real token count under the pinned encoding, or None without tiktoken."""
    return len(_ENC.encode(text)) if _ENC else None


def _column_reasons(items: list, keys: list, path: tuple = ()) -> list:
    """One pass of the eligibility walk, recursing where the encoders do.

    Mirrors ``_toon_columns`` (§9.3) and ``_gcf_leaf_paths`` (§7.4.6).
    The recursion is the whole point: a dict column can be perfectly
    legal at the top level and still decline because one of its *own*
    sub-values holds an array. A flat check passes such a column and then
    finds nothing to report, so the report prints "not emitted" with no
    reason underneath — the single outcome this function exists to
    prevent. Names the full dotted path, not just the outermost key.
    """
    reasons = []
    for key in keys:
        where = ".".join(path + (key,))
        present = [row[key] for row in items if key in row]
        dicts = [v for v in present if isinstance(v, dict)]
        if len(present) != len(items):
            reasons.append(
                f"{where!r}: missing from {len(items) - len(present)}/"
                f"{len(items)} rows -> TOON declines (§9.3 needs identical "
                f"key sets); GCF encodes it as '~'"
            )
        if any(isinstance(v, (list, tuple)) for v in present):
            reasons.append(f"{where!r}: array cell -> BOTH decline")
        if ">" in key:
            reasons.append(
                f"{where!r}: contains '>' -> GCF declines (reserved for path "
                f"columns); TOON quotes the key and carries on")
        if not dicts:
            continue
        if len(dicts) != len(present):
            reasons.append(
                f"{where!r}: mixes objects with scalars -> BOTH decline")
        elif len(present) != len(items):
            reasons.append(
                f"{where!r}: object column absent in some rows -> GCF "
                f"declines (§7.4.6 needs the parent in every row)")
        elif any(not v for v in dicts):
            reasons.append(f"{where!r}: empty-object cell -> BOTH decline")
        elif any(set(v) != set(dicts[0]) for v in dicts):
            reasons.append(
                f"{where!r}: non-uniform nested keys -> BOTH decline "
                f"(folding requires identical sub-key sets)")
        else:
            # Legal so far, so the encoders fold it and keep walking.
            # So do we — the real disqualifier usually lives down here.
            reasons += _column_reasons(dicts, _columns(dicts), path + (key,))
    return reasons


def declines(parsed) -> list:
    """Why the spec-compliant formats refused this payload, per column.

    Reporting only — it never changes what is emitted.
    """
    rows = _rows(parsed)
    if rows is None:
        return ["not row-shaped: no normalizer claimed it and it is neither "
                "a dict nor a list of str-keyed dicts — only parsed:sections "
                "can apply"]
    return _column_reasons(rows, _columns(rows))


def row_lists(node, path=(), out=None) -> list:
    """Dotted paths to every nested list-of-dicts, biggest first.

    By far the most common reason both spec formats decline is that the
    document is an *envelope*: the rows are real and perfectly tabular,
    but they sit two or three levels down while the top level is a single
    row of metadata that no tabular encoder can do anything with. Naming
    the path turns a dead end into a working ``--key``.
    """
    if out is None:
        out = []
    if isinstance(node, list):
        if node and all(isinstance(v, dict) for v in node):
            out.append((".".join(path), len(node)))
    elif isinstance(node, dict):
        for key, value in node.items():
            row_lists(value, path + (key,), out)
    return sorted(out, key=lambda p: -p[1])


def report(
    parsed=None,
    *,
    raw=None,
    command: str = "",
    platform=None,
    profile: str = "default",
    show: bool = False,
    label: str = "",
) -> list:
    """Print every candidate for one input against the correct baseline."""
    if raw is not None:
        baseline = raw
        what = f"raw output of {command!r}"
        candidates = render(raw, command=command, platform=platform,
                            parsed=parsed, profile=profile)
    else:
        baseline = json.dumps(parsed, separators=(",", ":"), default=str)
        what = "compact JSON of the input (what you would otherwise paste)"
        candidates = render_parsed(parsed, profile=profile)

    b_chars, b_tokens = len(baseline), tokens(baseline)
    print(f"\n{'=' * 78}\n{label or 'neterse report'}\n{'=' * 78}")
    print(f"baseline: {what}")
    print(f"          {b_chars} chars | {b_chars // 4} est tok"
          + (f" | {b_tokens} real tok ({ENCODING})" if b_tokens else
             " | real tokens unavailable (pip install 'neterse[tokens]')"))
    print(f"profile:  {profile}\n")

    if not candidates:
        print("  NO CANDIDATE SHRINKS THE BASELINE — send it as-is.")
    else:
        # Registry entry names run long (spec:<vendor>/<family>); size the
        # column to the widest one so the table never collides.
        width = max(20, max(len(c.source) for c in candidates) + 2)
        print(f"  {'candidate':<{width}}{'tier':<8}{'chars':>7}{'est':>6}"
              f"{'real':>6}{'saved':>8}  lossiness")
        print(f"  {'-' * (width + 54)}")
        for c in sorted(candidates, key=lambda c: len(c.text)):
            real = tokens(c.text)
            saved = ((1 - real / b_tokens) if (real and b_tokens)
                     else (1 - c.est_chars / b_chars))
            lossiness = (
                "lossless" if c.dropped_fields == ()
                else "UNDECLARED (compressor predates declaration)"
                if c.dropped_fields is None
                else f"DROPS {','.join(c.dropped_fields)}"
            )
            print(f"  {c.source:<{width}}{c.method:<8}{c.est_chars:>7}"
                  f"{c.est_tokens():>6}{(real if real else '-'):>6}"
                  f"{saved:>7.1%}  {lossiness}")

        best = min(candidates, key=lambda c: len(c.text))
        print(f"\n  smallest-wins -> {best.source}   "
              f"(what optimize()/optimize_parsed()/compact() returns)")
        lossless = [c for c in candidates if c.dropped_fields == ()]
        if lossless:
            cheapest = min(lossless, key=lambda c: len(c.text))
            if cheapest.source != best.source:
                # Smallest-wins is size-only: it will take a declared-lossy
                # rendering over a lossless one for a handful of bytes.
                print(f"  cheapest LOSSLESS -> {cheapest.source} "
                      f"({len(cheapest.text)} chars, "
                      f"+{len(cheapest.text) - len(best.text)} over the winner)")

    if raw is None:
        missing = set(SPEC_FORMATS) - {c.source for c in candidates}
        if missing:
            print(f"\n  not emitted: {', '.join(sorted(missing))}")
            for reason in declines(parsed):
                print(f"    - {reason}")
            # The commonest reason by far is simply that the extras are
            # absent: our own encoders decline these shapes on purpose,
            # and the spec authors' encoders — which do not — are opt-in.
            # Saying so here beats making the reader infer it from a
            # decline reason that is accurate but not actionable.
            uninstalled = [extra for extra, module in
                           (("toon", "toon_format"), ("gcf", "gcf"))
                           if f"parsed:{extra}" in missing
                           and not _installed(module)]
            if uninstalled:
                print(f"\n  the reference encoders are not installed — they "
                      f"cover shapes we decline\n    pip install "
                      f"'neterse[{','.join(uninstalled)}]'")
            # An envelope declines for a reason that reads as a flaw in the
            # payload when it is really a flaw in where you pointed.
            nested = [p for p in row_lists(parsed) if p[0]]
            if nested:
                print("\n  the rows are nested — point at them directly:")
                for where, count in nested[:3]:
                    print(f"    --key {where}    ({count} objects)")

    if show:
        for c in sorted(candidates, key=lambda c: len(c.text)):
            print(f"\n  --- {c.source} ({c.est_chars} chars) ---")
            for line in c.text.splitlines():
                print(f"  {line}")
    return candidates


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="Everything this reads is optional and named in one place: "
               "pip install 'neterse[all]'. Without a tokenizer 'saved' "
               "falls back to characters, which overstates token savings; "
               "without the encoder extras, fewer shapes produce a "
               "parsed:toon/parsed:gcf candidate at all.",
    )
    ap.add_argument("path", help="JSON file, raw capture, or - for stdin")
    ap.add_argument("--key", help="also report on this subtree alone, dotted "
                                  "for nesting (e.g. data.imdata) — an array "
                                  "cell declines both spec formats, so the "
                                  "subtree usually does far better")
    ap.add_argument("--profile", default="default",
                    help="named projection, e.g. 'updown' (declared-lossy)")
    ap.add_argument("--show", action="store_true",
                    help="print each rendering in full")
    ap.add_argument("--raw", action="store_true",
                    help="treat the input as raw CLI text, not JSON")
    ap.add_argument("--command", default="",
                    help="command string (with --raw)")
    ap.add_argument("--platform", help="platform key, e.g. cisco_ios")
    args = ap.parse_args(argv)

    text = sys.stdin.read() if args.path == "-" else Path(args.path).read_text()

    if args.raw:
        # Parse when we can, so BOTH tiers compete exactly as compact()
        # runs them — otherwise the raw tier looks unopposed and the
        # lossy-vs-lossless comparison below can never fire. Fail-open:
        # no extra installed, or no template for the pair, means None.
        rows = None
        if args.command and args.platform:
            from neterse import ntc
            rows = ntc.parse(text, command=args.command,
                             platform=args.platform)
            if rows is None:
                print("note: no ntc-templates parse for "
                      f"({args.platform}, {args.command!r}) — raw tier only",
                      file=sys.stderr)
        report(rows, raw=text, command=args.command, platform=args.platform,
               profile=args.profile, show=args.show,
               label=f"{args.path} (raw, {args.command!r})")
        return 0

    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise SystemExit(f"{args.path}: not JSON ({exc}) — use --raw for "
                         f"raw CLI captures")
    report(parsed, profile=args.profile, show=args.show,
           label=f"{args.path} — whole document")
    if args.key:
        node, walked = parsed, []
        for part in args.key.split("."):
            if not isinstance(node, dict) or part not in node:
                raise SystemExit(
                    f"--key {args.key!r}: {'.'.join(walked) or '<root>'} has "
                    f"no key {part!r}"
                    + (f" (available: {', '.join(map(repr, node))})"
                       if isinstance(node, dict) else
                       f" — it is a {type(node).__name__}, not an object"))
            node = node[part]
            walked.append(part)
        report(node, profile=args.profile, show=args.show,
               label=f"{args.path}[{args.key!r}] — the subtree alone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
