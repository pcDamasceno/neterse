#!/usr/bin/env python3
"""Compile the YAML spec sources into ``neterse/specs/_compiled.py``.

The YAML files under ``neterse/specs/<vendor>/<family>.yaml`` are the
authoring format for the data tier — one file per command family, the
layout ntc-templates made familiar. This script validates them (every
regex must compile, headers must match capture/keyword arity, profiles
must project real columns, the lossiness manifest is mandatory) and
emits the deterministic, committed ``_compiled.py`` module the package
imports at runtime. YAML therefore never becomes a runtime dependency —
PyYAML is needed only here and in the test suite (decision 27 in
docs/DESIGN.md).

Usage, from the repo root:

    python scripts/compile_specs.py            # regenerate _compiled.py
    python scripts/compile_specs.py --check    # CI drift gate: exit 1 on any
                                               # difference, print the diff

Validation is deliberately loud: a malformed spec must fail THIS step
(and the test suite, which re-runs the same validation), never ship a
compressor that silently misparses. Exit status: 0 = compiled/UP-TO-DATE,
1 = drift (--check), 2 = validation error.
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard, not logic
    sys.exit(
        "compile_specs.py needs PyYAML (authoring-time only, never a runtime "
        "dependency of neterse). Install it with:  pip install pyyaml"
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_ROOT = REPO_ROOT / "neterse" / "specs"
COMPILED = SPEC_ROOT / "_compiled.py"

# Symbolic regex flags a YAML source may name. Deliberately short: these
# are the ones table/kv patterns legitimately need.
FLAG_NAMES = ("ASCII", "DOTALL", "IGNORECASE", "MULTILINE", "VERBOSE")

# Canonical key order of the emitted dicts — stable output, stable diffs.
KEY_ORDER = [
    "id", "command", "platforms", "strategy",
    "row", "row_flags", "keywords", "fields",
    "header", "columns", "strip_columns", "context_prefixes",
    "unindented_rows_only", "row_match", "first_col_wraps", "joiner",
    "dropped_fields", "profiles", "doc",
]

COMMON_KEYS = {"id", "command", "platforms", "strategy", "dropped_fields", "doc"}
STRATEGY_KEYS: Dict[str, Dict[str, set]] = {
    "line_regex_table": {
        "required": {"row", "header"},
        "optional": {"row_flags", "columns", "strip_columns",
                     "context_prefixes", "unindented_rows_only", "profiles"},
    },
    "fixed_width_table": {
        "required": {"keywords", "header"},
        "optional": {"row_match", "first_col_wraps", "profiles"},
    },
    # kv_extract takes no header and (engine-enforced) no profiles.
    "kv_extract": {
        "required": {"fields"},
        "optional": {"joiner"},
    },
}
FIELD_KEYS = {"key", "pattern", "flags", "template", "strip"}


class SpecError(ValueError):
    """A YAML source failed validation; the message names file and field."""


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys. PyYAML's default is
    silent last-wins — a second ``header:`` line would quietly discard the
    first, exactly the silent misparse this script exists to prevent."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _value in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"found duplicate key {key!r}", key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep)


def _fail(path: Path, msg: str) -> None:
    try:
        shown: Path = path.relative_to(REPO_ROOT)
    except ValueError:      # a root outside the repo (tests, tooling)
        shown = path
    raise SpecError(f"{shown}: {msg}")


def _require(cond: bool, path: Path, msg: str) -> None:
    if not cond:
        _fail(path, msg)


def _flags(value: Any, path: Path, where: str) -> List[str]:
    """Normalize a flags entry to a sorted list of valid symbolic names."""
    if isinstance(value, str):
        value = [value]
    _require(
        isinstance(value, list) and value
        and all(isinstance(f, str) for f in value),
        path, f"{where} must be a flag name or non-empty list of flag names",
    )
    for f in value:
        _require(f in FLAG_NAMES, path,
                 f"{where}: unknown flag {f!r} (allowed: {', '.join(FLAG_NAMES)})")
    return sorted(set(value))


def _flag_value(names: List[str]) -> "re.RegexFlag":
    out = re.RegexFlag(0)
    for n in names:
        out |= getattr(re, n)
    return out


def _compile(pattern: Any, flag_names: List[str], path: Path, where: str) -> "re.Pattern":
    _require(isinstance(pattern, str) and pattern, path,
             f"{where} must be a non-empty string")
    try:
        return re.compile(pattern, _flag_value(flag_names))
    # OverflowError: re raises it (not re.error) for absurd repetition
    # counts like (a){99999999999} — still "does not compile" to a user.
    except (re.error, OverflowError) as exc:
        _fail(path, f"{where} does not compile: {exc}")
    raise AssertionError("unreachable")


def _str_list(value: Any, path: Path, where: str) -> List[str]:
    _require(
        isinstance(value, list)
        and all(isinstance(v, str) and v for v in value),
        path, f"{where} must be a list of non-empty strings",
    )
    return list(value)


def _header_names(spec: Dict[str, Any], path: Path) -> List[str]:
    header = spec.get("header")
    _require(isinstance(header, str) and header, path,
             "header must be a non-empty comma-separated string")
    names = header.split(",")
    _require(all(names), path, "header has an empty column name")
    _require(len(names) == len(set(names)), path, "header repeats a column name")
    return names


def validate(path: Path, data: Any) -> Dict[str, Any]:
    """Validate one YAML source; return the canonical authoring dict
    (flags still symbolic — resolved at emit/runtime time)."""
    _require(isinstance(data, dict) and all(isinstance(k, str) for k in data),
             path, "top level must be a mapping with string keys")
    spec: Dict[str, Any] = dict(data)

    derived_id = f"{path.parent.name}/{path.stem}"
    _require(spec.get("id", derived_id) == derived_id, path,
             f"id {spec.get('id')!r} contradicts the file path "
             f"(derived id: {derived_id!r}); omit the id key")
    spec["id"] = derived_id

    strategy = spec.get("strategy")
    _require(strategy in STRATEGY_KEYS, path,
             f"strategy must be one of {sorted(STRATEGY_KEYS)}, got {strategy!r}")
    keys = STRATEGY_KEYS[strategy]
    allowed = COMMON_KEYS | keys["required"] | keys["optional"]
    unknown = set(spec) - allowed
    _require(not unknown, path, f"unknown keys for {strategy}: {sorted(unknown)}")
    missing = keys["required"] - set(spec)
    _require(not missing, path, f"missing required keys: {sorted(missing)}")

    _compile(spec.get("command"), [], path, "command")
    if "platforms" in spec:
        _compile(spec["platforms"], [], path, "platforms")

    _require("dropped_fields" in spec, path,
             "dropped_fields is required — the lossiness manifest; use [] "
             "to declare the rendering lossless")
    _require(
        isinstance(spec["dropped_fields"], list)
        and all(isinstance(v, str) and v for v in spec["dropped_fields"]),
        path, "dropped_fields must be a list of field names ([] = lossless)",
    )
    if "doc" in spec:
        _require(isinstance(spec["doc"], str) and spec["doc"], path,
                 "doc must be a non-empty string")

    if strategy == "line_regex_table":
        names = _header_names(spec, path)
        if "row_flags" in spec:
            spec["row_flags"] = _flags(spec["row_flags"], path, "row_flags")
        row = _compile(spec.get("row"), spec.get("row_flags", []), path, "row")
        emitted = list(range(1, row.groups + 1))
        if "columns" in spec:
            _require(
                isinstance(spec["columns"], list) and spec["columns"]
                and all(isinstance(c, int) and 1 <= c <= row.groups
                        for c in spec["columns"]),
                path, f"columns must be 1-based group indexes within 1..{row.groups}",
            )
            emitted = list(spec["columns"])
        _require(
            len(names) == len(emitted), path,
            f"header names {len(names)} columns but the row emits "
            f"{len(emitted)} groups",
        )
        if "strip_columns" in spec:
            _require(
                isinstance(spec["strip_columns"], list)
                and all(isinstance(c, int) and c in emitted
                        for c in spec["strip_columns"]),
                path, f"strip_columns must name emitted group indexes {emitted}",
            )
        if "context_prefixes" in spec:
            _str_list(spec["context_prefixes"], path, "context_prefixes")
        if "unindented_rows_only" in spec:
            _require(isinstance(spec["unindented_rows_only"], bool), path,
                     "unindented_rows_only must be a boolean")

    elif strategy == "fixed_width_table":
        names = _header_names(spec, path)
        keywords = _str_list(spec.get("keywords"), path, "keywords")
        _require(
            len(names) == len(keywords), path,
            f"header names {len(names)} columns but keywords declares "
            f"{len(keywords)}",
        )
        if "row_match" in spec:
            _compile(spec["row_match"], [], path, "row_match")
        if "first_col_wraps" in spec:
            _require(isinstance(spec["first_col_wraps"], bool), path,
                     "first_col_wraps must be a boolean")

    else:  # kv_extract
        fields = spec.get("fields")
        _require(isinstance(fields, list) and fields, path,
                 "fields must be a non-empty list")
        seen = set()
        for i, field in enumerate(fields):
            where = f"fields[{i}]"
            _require(isinstance(field, dict), path, f"{where} must be a mapping")
            unknown = set(field) - FIELD_KEYS
            _require(not unknown, path, f"{where}: unknown keys {sorted(unknown)}")
            key = field.get("key")
            _require(isinstance(key, str) and key, path,
                     f"{where}.key must be a non-empty string")
            _require(key not in seen, path, f"duplicate field key {key!r}")
            seen.add(key)
            if "flags" in field:
                field["flags"] = _flags(field["flags"], path, f"{where}.flags")
            rx = _compile(field.get("pattern"), field.get("flags", []),
                          path, f"{where}.pattern")
            template = field.get("template", "{1}")
            _require(isinstance(template, str), path,
                     f"{where}.template must be a string")
            try:
                template.format(*[""] * (rx.groups + 1))
            except (IndexError, KeyError):
                _fail(path, f"{where}.template references more groups than "
                            f"the pattern captures ({rx.groups})")
            except ValueError as exc:   # e.g. a lone "{" or a "{1:d}" spec
                _fail(path, f"{where}.template is not a valid format "
                            f"string: {exc}")
            if "strip" in field:
                _require(isinstance(field["strip"], bool), path,
                         f"{where}.strip must be a boolean")
        if "joiner" in spec:
            _require(isinstance(spec["joiner"], str), path,
                     "joiner must be a string")

    if "profiles" in spec:
        names = _header_names(spec, path)
        profiles = spec["profiles"]
        _require(isinstance(profiles, dict) and profiles, path,
                 "profiles must be a non-empty mapping")
        for pname, proj in profiles.items():
            _require(isinstance(pname, str) and pname, path,
                     "profile names must be non-empty strings")
            _require(isinstance(proj, dict) and set(proj) == {"keep"}, path,
                     f"profile {pname!r} must be a mapping with exactly "
                     f"the 'keep' key")
            keep = _str_list(proj["keep"], path, f"profile {pname!r}.keep")
            bad = [c for c in keep if c not in names]
            _require(not bad, path,
                     f"profile {pname!r} keeps unknown columns {bad} "
                     f"(header: {names})")
            _require(0 < len(set(keep)) < len(names), path,
                     f"profile {pname!r} must keep at least one column and "
                     f"drop at least one")

    return spec


def load_sources(root: Path = SPEC_ROOT) -> List[Tuple[Path, Dict[str, Any]]]:
    """All validated YAML sources, sorted by spec id (deterministic).

    Discovery is recursive ON PURPOSE: a spec file at the wrong depth or
    with a ``.yml`` extension is a misfiled contribution, and silently
    skipping it would report "up to date" while the spec never ships —
    so it fails loudly instead.
    """
    paths = sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml"))
    if not paths:
        raise SpecError(f"no YAML spec sources found under {root}")
    out = []
    for path in paths:
        _require(path.suffix == ".yaml", path, "use the .yaml extension")
        _require(path.parent.parent == root and path.parent != root, path,
                 "spec files live exactly one level deep: "
                 "<vendor>/<family>.yaml")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _fail(path, f"unreadable as UTF-8: {exc}")
        try:
            data = yaml.load(text, Loader=_StrictLoader)
        except yaml.YAMLError as exc:
            _fail(path, f"not parseable as YAML: {exc}")
        out.append((path, validate(path, data)))
    out.sort(key=lambda item: item[1]["id"])
    ids = [spec["id"] for _, spec in out]
    if len(ids) != len(set(ids)):
        raise SpecError(f"duplicate spec ids: {sorted(set(i for i in ids if ids.count(i) > 1))}")
    return out


def to_runtime(spec: Dict[str, Any]) -> Dict[str, Any]:
    """The runtime dict shape the engine consumes — symbolic flags become
    ``re`` flag values, the manifest becomes a tuple. Mirrors exactly what
    the emitted module evaluates to (the drift test relies on this)."""
    out = dict(spec)
    out["dropped_fields"] = tuple(out["dropped_fields"])
    if "row_flags" in out:
        out["row_flags"] = _flag_value(out["row_flags"])
    if "fields" in out:
        fields = []
        for field in out["fields"]:
            field = dict(field)
            if "flags" in field:
                field["flags"] = _flag_value(field["flags"])
            fields.append(field)
        out["fields"] = fields
    return out


# ---------------------------------------------------------------------------
# Code emission
# ---------------------------------------------------------------------------

MODULE_HEADER = '''\
"""AUTO-GENERATED — DO NOT EDIT BY HAND.

Compiled from the YAML spec sources in this directory
(``neterse/specs/<vendor>/<family>.yaml``) by ``scripts/compile_specs.py``.
Edit the YAML, then regenerate:

    python scripts/compile_specs.py

CI fails when this module drifts from its sources
(``python scripts/compile_specs.py --check``). The YAML is the authoring
format; this generated module is what the package imports, so the runtime
keeps its zero-dependency invariant — no YAML parser at import time
(decision 27 in docs/DESIGN.md).
"""
from __future__ import annotations

import re

SPECS: list = [
'''

MODULE_FOOTER = "]\n"


def _emit_flags(names: List[str]) -> str:
    return " | ".join(f"re.{n}" for n in names)


def _emit_value(key: str, value: Any, indent: str) -> str:
    if key in ("row_flags", "flags"):
        return _emit_flags(value)
    if key == "dropped_fields":
        if not value:
            return "()"
        inner = ", ".join(repr(v) for v in value)
        return f"({inner},)" if len(value) == 1 else f"({inner})"
    if key == "profiles":
        lines = ["{"]
        for pname in value:
            keep = ", ".join(repr(c) for c in value[pname]["keep"])
            lines.append(f'{indent}    {pname!r}: {{"keep": [{keep}]}},')
        lines.append(indent + "}")
        return "\n".join(lines)
    if key == "fields":
        lines = ["["]
        for field in value:
            lines.append(indent + "    {")
            for fkey in ("key", "pattern", "flags", "template", "strip"):
                if fkey in field:
                    lines.append(
                        f"{indent}        {fkey!r}: "
                        f"{_emit_value(fkey, field[fkey], indent + '        ')},"
                    )
            lines.append(indent + "    },")
        lines.append(indent + "]")
        return "\n".join(lines)
    if isinstance(value, list):
        return "[" + ", ".join(repr(v) for v in value) + "]"
    return repr(value)


def emit_module(specs: List[Dict[str, Any]]) -> str:
    chunks = [MODULE_HEADER]
    for spec in specs:
        chunks.append("    {\n")
        for key in KEY_ORDER:
            if key in spec:
                rendered = _emit_value(key, spec[key], "        ")
                chunks.append(f"        {key!r}: {rendered},\n")
        chunks.append("    },\n")
    chunks.append(MODULE_FOOTER)
    return "".join(chunks)


def compile_text(root: Path = SPEC_ROOT) -> str:
    return emit_module([spec for _, spec in load_sources(root)])


def main(argv: "List[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="verify _compiled.py matches the YAML sources; "
                             "exit 1 and print a diff on drift")
    args = parser.parse_args(argv)

    try:
        text = compile_text()
    except SpecError as exc:
        print(f"spec validation failed: {exc}", file=sys.stderr)
        return 2

    current = COMPILED.read_text(encoding="utf-8") if COMPILED.exists() else ""
    if args.check:
        if text == current:
            print(f"{COMPILED.relative_to(REPO_ROOT)} is up to date "
                  f"({text.count(chr(10) + '    {')} specs).")
            return 0
        diff = difflib.unified_diff(
            current.splitlines(keepends=True), text.splitlines(keepends=True),
            fromfile=str(COMPILED.relative_to(REPO_ROOT)),
            tofile="regenerated from YAML sources",
        )
        sys.stdout.writelines(diff)
        print("\ncompiled specs drifted from their YAML sources — run:\n"
              "    python scripts/compile_specs.py", file=sys.stderr)
        return 1

    if text == current:
        print(f"{COMPILED.relative_to(REPO_ROOT)} already up to date.")
        return 0
    COMPILED.write_text(text, encoding="utf-8")
    print(f"wrote {COMPILED.relative_to(REPO_ROOT)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
