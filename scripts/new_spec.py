#!/usr/bin/env python3
"""Scaffold a new command-family contribution — names consistent by
construction.

    python scripts/new_spec.py <platform>/<family> [--strategy S] [--from CAPTURE]

e.g.

    python scripts/new_spec.py fortinet_fortios/get_system_interface
    python scripts/new_spec.py cisco_nxos/show_ip_route --from capture.txt

Creates, refusing to overwrite anything that exists:

* ``neterse/specs/<platform>/<family>.yaml`` — a commented, VALID
  skeleton for the chosen strategy (placeholder row/header you edit);
* ``tests/fixtures/<platform>/<family>/commands.txt`` — seeded with the
  spelling derived from the family name;
* ``tests/fixtures/<platform>/<family>/raw.txt`` — only with
  ``--from CAPTURE`` (otherwise you paste your byte-exact capture there;
  the fixture suite ignores the family until raw.txt exists).

The one directory name is used for the spec's vendor directory AND the
fixture platform directory, so the naming contract in docs/SPECS.md
(fixture dir = platform string = matched by ``platforms`` = shares the
spec dir's vendor stem) holds automatically. Then follow the printed
loop: fill in the spec, compile, eyeball the rendering, golden it, test.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_ROOT = REPO_ROOT / "neterse" / "specs"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures"

STRATEGIES = ("line_regex_table", "fixed_width_table", "kv_extract")

_COMMON = """\
# {command_text} ({platform}) -> {target}.
#
# Field reference: docs/SPECS.md. Scope the command regex tightly
# (negative lookaheads for sibling subcommands) and declare platforms
# broadly — the filter kills cross-family false matches, nothing more.
command: '{command_re}'
platforms: '{platforms_re}'
strategy: {strategy}
"""

_BODIES = {
    "line_regex_table": """\
# One regex per data row, matched against each STRIPPED line; capture
# groups become the CSV columns. PLACEHOLDER — replace with your rows'
# real shape (single quotes: YAML double quotes reject \\s).
row: '^(\\S+)\\s+(\\S+)$'
# Comma-separated string, one name per emitted group, no spaces.
header: col1,col2
""",
    "fixed_width_table": """\
# The device's header tokens, in order (quote multi-word ones); each
# keyword's offset defines a column slice. PLACEHOLDER — replace with
# your table's real header words.
keywords: [Col1, Col2]
# Comma-separated string, one name per keyword, no spaces.
header: col1,col2
# Regex the first column of a data row must match (default: the Cisco
# interface-name pattern — most non-Cisco tables need their own).
row_match: '^\\S+$'
""",
    "kv_extract": """\
# First match per field wins; output is one `key=value | key=value`
# line in first-match order. PLACEHOLDER — replace with your fields.
fields:
  - key: example
    pattern: 'Example\\s+(\\S+)'
""",
}

_MANIFEST = """\
# REQUIRED lossiness manifest: name every DATA-bearing field the
# rendering omits; [] declares it lossless. Noise (separators, legends,
# repeated headers) is dropped freely and never declared.
dropped_fields: []
doc: >-
  {command_text} ({platform}) -> {target}.
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec_id", metavar="<platform>/<family>",
                        help="e.g. fortinet_fortios/get_system_interface")
    parser.add_argument("--strategy", choices=STRATEGIES,
                        default="line_regex_table")
    parser.add_argument("--from", dest="capture", metavar="CAPTURE",
                        help="byte-exact raw capture to install as raw.txt")
    args = parser.parse_args(argv)

    if not re.fullmatch(r"[a-z0-9_]+/[a-z0-9_]+", args.spec_id):
        parser.error(
            "spec id must be <platform>/<family> in [a-z0-9_] "
            f"(got {args.spec_id!r})"
        )
    platform, family = args.spec_id.split("/")

    spec_path = SPEC_ROOT / platform / f"{family}.yaml"
    fixture_dir = FIXTURE_ROOT / platform / family
    for existing in (spec_path, fixture_dir / "commands.txt",
                     fixture_dir / "raw.txt"):
        if existing.exists():
            raise SystemExit(f"refusing to overwrite {existing}")

    command_text = family.replace("_", " ")
    command_re = re.sub(r"\s+", r"\\s+", re.escape(command_text))
    vendor_stem = platform.split("_")[0]
    platforms_re = (
        vendor_stem if vendor_stem == platform
        else f"{vendor_stem}|{platform}"
    )
    target = "one key=value line" if args.strategy == "kv_extract" else "CSV"
    fill = dict(
        command_text=command_text, command_re=command_re,
        platforms_re=platforms_re, platform=platform,
        strategy=args.strategy, target=target,
    )

    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        _COMMON.format(**fill) + _BODIES[args.strategy]
        + _MANIFEST.format(**fill)
    )
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / "commands.txt").write_text(command_text + "\n")
    raw_path = fixture_dir / "raw.txt"
    if args.capture:
        raw_path.write_bytes(Path(args.capture).read_bytes())

    rel = lambda p: p.relative_to(REPO_ROOT)  # noqa: E731
    print(f"wrote {rel(spec_path)}")
    print(f"wrote {rel(fixture_dir / 'commands.txt')}")
    if args.capture:
        print(f"wrote {rel(raw_path)} (from {args.capture})")
    else:
        print(f"next: paste one byte-exact capture at {rel(raw_path)}")
        print("      (scrub secrets with SAME-LENGTH replacements — "
              "fixed-width offsets are data)")
    print(f"""
then iterate:
    1. edit {rel(spec_path)} (docs/SPECS.md is the field reference)
    2. python scripts/compile_specs.py          # validate + regenerate
    3. python scripts/neterse_report.py {rel(raw_path)} --raw \\
           --command '{command_text}' --platform {platform} --show
    4. python scripts/update_goldens.py         # commit expected.txt too
    5. pytest
    6. python scripts/update_token_baseline.py  # if the token gate asks
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
