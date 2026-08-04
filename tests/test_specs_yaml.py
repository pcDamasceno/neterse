"""The YAML authoring tier: sources ↔ compiled module ↔ runtime SPECS.

Three contracts (decision 27):

* the committed, generated ``neterse/specs/_compiled.py`` matches its
  YAML sources byte-for-byte (the drift gate — CI also runs
  ``scripts/compile_specs.py --check``);
* what the runtime imports is exactly what the sources declare (flags
  resolved, manifests tupled);
* the compiler is LOUD: malformed specs — bad regexes, arity mismatches,
  undeclared manifests, typo'd keys — fail compilation, never ship a
  silently-wrong compressor.

Plus the decision-28 registration contract: every spec id appears in the
registry exactly once, and specs without an explicit canonical position
self-append after the full sequence in sorted-id order.

PyYAML comes from the ``test`` extra; if it is genuinely absent the
source-reading tests skip (CI always has it).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from neterse import iter_entries
from neterse.specs import SPECS
from neterse import registry

yaml = pytest.importorskip("yaml", reason="PyYAML ships in the test extra")

REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "compile_specs", REPO_ROOT / "scripts" / "compile_specs.py"
)
compile_specs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compile_specs)

# A path shape validate() accepts; the file never needs to exist.
FAKE_PATH = compile_specs.SPEC_ROOT / "acme_os" / "show_widgets.yaml"

MINIMAL = {
    "command": r"show\s+widgets",
    "strategy": "line_regex_table",
    "row": r"^(\S+)\s+(\d+)$",
    "header": "widget,count",
    "dropped_fields": [],
}


def _reject(data, match):
    with pytest.raises(compile_specs.SpecError, match=match):
        compile_specs.validate(FAKE_PATH, data)


# ---------------------------------------------------------------------------
# Sources ↔ compiled ↔ runtime
# ---------------------------------------------------------------------------

def test_compiled_module_matches_yaml_sources():
    """The committed generated module is exactly what the sources compile
    to — edit YAML without regenerating and this (and CI's --check) fails."""
    assert compile_specs.COMPILED.read_text(encoding="utf-8") == (
        compile_specs.compile_text()
    ), "run: python scripts/compile_specs.py"


def test_runtime_specs_equal_validated_sources():
    """What ``neterse.specs.SPECS`` serves at runtime is deep-equal to the
    validated YAML sources under the documented normalization (symbolic
    flags → re flags, manifest list → tuple)."""
    compiled = [
        compile_specs.to_runtime(spec)
        for _, spec in compile_specs.load_sources()
    ]
    assert compiled == SPECS


def test_ids_derive_from_vendor_and_family_paths():
    for path, spec in compile_specs.load_sources():
        assert spec["id"] == f"{path.parent.name}/{path.stem}"
        assert path.parent.parent == compile_specs.SPEC_ROOT


def test_minimal_spec_validates_and_emits():
    spec = compile_specs.validate(FAKE_PATH, dict(MINIMAL))
    assert spec["id"] == "acme_os/show_widgets"
    runtime = compile_specs.to_runtime(spec)
    assert runtime["dropped_fields"] == ()
    # the emitted literal must evaluate back to the runtime dict
    module = compile_specs.emit_module([spec])
    namespace: dict = {}
    exec(compile(module, "<generated>", "exec"), namespace)
    assert namespace["SPECS"] == [runtime]


# ---------------------------------------------------------------------------
# The compiler is loud
# ---------------------------------------------------------------------------

def test_rejects_unknown_strategy():
    _reject({**MINIMAL, "strategy": "clever_new_idea"}, "strategy must be one of")


def test_rejects_missing_manifest():
    bad = dict(MINIMAL)
    del bad["dropped_fields"]
    _reject(bad, "dropped_fields is required")


def test_rejects_typoed_key():
    _reject({**MINIMAL, "droped_fields": []}, "unknown keys")


def test_rejects_id_contradicting_path():
    _reject({**MINIMAL, "id": "acme_os/other_family"}, "contradicts the file path")


def test_rejects_uncompilable_row():
    _reject({**MINIMAL, "row": r"^(\S+"}, "row does not compile")


def test_rejects_header_group_arity_mismatch():
    _reject({**MINIMAL, "header": "widget,count,extra"}, "header names 3 columns")


def test_rejects_columns_out_of_range():
    _reject({**MINIMAL, "header": "widget", "columns": [3]},
            "columns must be 1-based group indexes")


def test_rejects_strip_of_unemitted_group():
    _reject({**MINIMAL, "strip_columns": [7]}, "strip_columns must name emitted")


def test_rejects_unknown_flag_name():
    _reject({**MINIMAL, "row_flags": ["VERY_VERBOSE"]}, "unknown flag")


def test_rejects_profile_keeping_unknown_or_all_columns():
    _reject(
        {**MINIMAL, "profiles": {"p": {"keep": ["nope"]}}},
        "keeps unknown columns",
    )
    _reject(
        {**MINIMAL, "profiles": {"p": {"keep": ["widget", "count"]}}},
        "drop at least one",
    )


def test_rejects_fixed_width_keyword_arity_mismatch():
    _reject(
        {
            "command": "show x",
            "strategy": "fixed_width_table",
            "keywords": ["A", "B"],
            "header": "a,b,c",
            "dropped_fields": [],
        },
        "keywords declares",
    )


def test_rejects_malformed_template_format_string():
    _reject(
        {
            "command": "show x",
            "strategy": "kv_extract",
            "fields": [{"key": "k", "pattern": r"(\d+)", "template": "{"}],
            "dropped_fields": [],
        },
        "not a valid format string",
    )


def test_rejects_regex_the_re_module_rejects_without_re_error():
    # re raises OverflowError (not re.error) here — must still be a loud
    # SpecError, not a traceback with the drift exit code.
    _reject({**MINIMAL, "header": "widget", "row": "(a){99999999999}"},
            "row does not compile")


def test_rejects_kv_template_overreaching_groups():
    _reject(
        {
            "command": "show x",
            "strategy": "kv_extract",
            "fields": [{"key": "k", "pattern": r"(\d+)", "template": "{1} {2}"}],
            "dropped_fields": [],
        },
        "references more groups",
    )


def test_rejects_profiles_on_kv_extract():
    _reject(
        {
            "command": "show x",
            "strategy": "kv_extract",
            "fields": [{"key": "k", "pattern": r"(\d+)"}],
            "dropped_fields": [],
            "profiles": {"p": {"keep": ["k"]}},
        },
        "unknown keys",
    )


# ---------------------------------------------------------------------------
# Source discovery is loud too (misfiled contributions must not vanish)
# ---------------------------------------------------------------------------

MINIMAL_YAML = (
    "command: 'show\\s+widgets'\n"
    "strategy: line_regex_table\n"
    "row: '^(\\S+)\\s+(\\d+)$'\n"
    "header: widget,count\n"
    "dropped_fields: []\n"
)


def _tree(tmp_path, name="show_widgets.yaml", text=MINIMAL_YAML):
    vendor = tmp_path / "acme_os"
    vendor.mkdir(exist_ok=True)
    (vendor / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_external_root_loads_and_fails_as_spec_error(tmp_path):
    sources = compile_specs.load_sources(_tree(tmp_path))
    assert [s["id"] for _, s in sources] == ["acme_os/show_widgets"]
    bad = _tree(tmp_path, text=MINIMAL_YAML.replace(
        "line_regex_table", "no_such_strategy"))
    with pytest.raises(compile_specs.SpecError, match="strategy must be"):
        compile_specs.load_sources(bad)


def test_rejects_duplicate_yaml_keys(tmp_path):
    with pytest.raises(compile_specs.SpecError, match="duplicate key"):
        compile_specs.load_sources(
            _tree(tmp_path, text=MINIMAL_YAML + "header: second\n")
        )


def test_rejects_misfiled_spec_depth(tmp_path):
    root = _tree(tmp_path)
    (root / "orphan.yaml").write_text(MINIMAL_YAML, encoding="utf-8")
    with pytest.raises(compile_specs.SpecError, match="one level deep"):
        compile_specs.load_sources(root)
    (root / "orphan.yaml").unlink()
    nested = root / "acme_os" / "sub"
    nested.mkdir()
    (nested / "deep.yaml").write_text(MINIMAL_YAML, encoding="utf-8")
    with pytest.raises(compile_specs.SpecError, match="one level deep"):
        compile_specs.load_sources(root)


def test_rejects_yml_extension(tmp_path):
    with pytest.raises(compile_specs.SpecError, match=r"\.yaml extension"):
        compile_specs.load_sources(_tree(tmp_path, name="show_widgets.yml"))


def test_rejects_non_utf8_source(tmp_path):
    root = _tree(tmp_path)
    (root / "acme_os" / "latin.yaml").write_bytes(b"command: sh\xffow\n")
    with pytest.raises(compile_specs.SpecError, match="unreadable as UTF-8"):
        compile_specs.load_sources(root)


# ---------------------------------------------------------------------------
# Registration (decision 28)
# ---------------------------------------------------------------------------

def test_every_spec_registers_exactly_once():
    names = [e.name for e in iter_entries()]
    for spec in SPECS:
        assert names.count(f"spec:{spec['id']}") == 1, spec["id"]


def test_explicit_order_set_is_exactly_the_shipped_spec_ids():
    """Today every shipped spec has an explicit canonical position, so the
    auto-append is a no-op — and the real ordered-id set must say so."""
    assert registry._EXPLICITLY_ORDERED == {s["id"] for s in SPECS}


def test_unlisted_specs_self_append_in_sorted_id_order():
    fakes = [
        {**MINIMAL, "id": "zvendor/family_b", "dropped_fields": []},
        {**MINIMAL, "id": "avendor/family_a", "dropped_fields": []},
    ]
    entries = registry._auto_appended(
        SPECS + fakes, registry._EXPLICITLY_ORDERED
    )
    assert [e.name for e in entries] == [
        "spec:avendor/family_a", "spec:zvendor/family_b",
    ]
    # everything explicitly ordered → nothing to append (today's registry)
    assert registry._auto_appended(SPECS, registry._EXPLICITLY_ORDERED) == []


def test_auto_append_wires_into_the_real_registry(monkeypatch):
    """End-to-end over the import-time wiring, not just the helper: a spec
    id absent from the canonical order must appear in the rebuilt
    REGISTRY, strictly last, with the sequence before it unchanged."""
    import importlib

    import neterse
    from neterse import specs as specs_pkg

    fake = {**MINIMAL, "id": "zzz_vendor/fake_family"}
    before = [e.name for e in registry.REGISTRY]
    monkeypatch.setattr(specs_pkg, "SPECS", list(specs_pkg.SPECS) + [fake])
    try:
        names = [e.name for e in importlib.reload(registry).REGISTRY]
        assert names == before + ["spec:zzz_vendor/fake_family"]
    finally:
        # Rebuild the registry from the restored SPECS, then re-export the
        # rebuilt objects through the package so no stale binding leaks
        # into later tests.
        monkeypatch.undo()
        importlib.reload(registry)
        importlib.reload(neterse)
