"""Adversarial input checks: savings must not erase data or its type."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from neterse import compact, render, render_parsed
from neterse.parsed import encode


def _decode_csv(text):
    """Independent reader of the typed-cell contract in docs/API.md."""
    records = iter(csv.reader(io.StringIO(text, newline=""), strict=True))
    columns = next(records)
    result = []
    for cells in records:
        assert len(cells) == len(columns)
        row = {}
        for column, cell in zip(columns, cells):
            if cell == "":
                continue
            try:
                row[column] = json.loads(cell)
            except ValueError:
                row[column] = cell
        result.append(row)
    return result


def test_csv_round_trips_types_missing_values_and_escaping():
    values = [
        None, True, False, 0, 1, -0.0, 1.5, "", "null", "true", "false",
        "0", "1", "-0.0", "1e3", " 1 ", "001", "NaN", "Infinity",
        "[1]", '{"x":1}', '"text"', "plain", "a,b", 'a"b',
        "two\nlines", "carriage\rreturn", "\t", "日本語", [], {},
        {"nested": [True, None, "", "1"]}, [1, "1", False],
    ]
    rows = [{"id": index, "value": value} for index, value in enumerate(values)]
    rows.append({"id": len(rows)})
    text = next(text for text, source, _, _ in encode(rows) if source == "parsed:csv")
    # JSON comparison also distinguishes boolean True from integer 1.
    assert json.dumps(_decode_csv(text)) == json.dumps(rows)


def test_single_column_missing_row_is_not_a_blank_record():
    rows = [{"value": "first"}, {}, {"value": ""}, {"value": None}]
    text = next(text for text, source, _, _ in encode(rows) if source == "parsed:csv")
    assert _decode_csv(text) == rows


def test_empty_column_name_is_a_csv_field_not_a_blank_header():
    rows = [{"": "first"}, {"": ""}, {}]
    text = next(text for text, source, _, _ in encode(rows) if source == "parsed:csv")
    assert _decode_csv(text) == rows


@pytest.mark.parametrize("left,right", [(True, "true"), (1, "1"), ([], "[]"), (None, "null")])
def test_compact_does_not_conflate_values(left, right):
    def rows(value):
        return [{"interface": "eth1", "status": value}, {"interface": "eth2", "status": "up"}]
    assert compact(rows(left)) != compact(rows(right))


def test_missing_and_empty_remain_distinct_even_in_constant_folding():
    missing = [{"name": f"eth{i}"} for i in range(12)]
    empty = [{**row, "status": ""} for row in missing]
    assert compact(missing) != compact(empty)
    mixed = [{"name": f"eth{i}", **({"status": ""} if i % 2 else {})} for i in range(12)]
    for candidate in render_parsed(mixed):
        if candidate.source == "parsed:fold":
            assert "each: status=" not in candidate.text


@pytest.mark.parametrize("platform,family,command", [
    ("arista_eos", "show_vlan", "show vlan"),
    ("aruba_aoscx", "show_vlan", "show vlan"),
])
def test_vlan_csv_has_matching_header_and_row_widths(platform, family, command):
    raw = (Path(__file__).parent / "fixtures" / platform / family / "raw.txt").read_text()
    best = min(render(raw, command=command, platform=platform), key=lambda c: len(c.text))
    records = list(csv.reader(io.StringIO(best.text)))
    assert all(len(row) == len(records[0]) for row in records[1:])


@pytest.mark.parametrize("platform,command", [
    ("arista_eos", "show vlan"), ("cisco_ios", "show vlan brief"),
])
def test_wrapped_vlan_ports_fail_open(platform, command):
    raw = (
        "VLAN  Name                             Status    Ports\n"
        "----- -------------------------------- --------- -------------------\n"
        "10    USERS                            active    Et4, Et5\n"
        "                                                 Et7, Et8\n"
    )
    assert render(raw, command=command, platform=platform) == []


def test_cisco_vlan_golden_keeps_the_port_list_in_one_cell():
    from .corpus import VLAN_BRIEF

    candidates = render(VLAN_BRIEF, command="show vlan brief", platform="cisco_ios")
    assert min(candidates, key=lambda c: len(c.text)).text == (
        'vlan,name,status,ports\n1,default,active,"Gi0/3, Gi0/4"\n'
        '10,USERS,active,Gi0/5\n99,MGMT,active,'
    )


def test_supported_tables_do_not_load_optional_encoders(monkeypatch):
    from neterse import parsed

    imports = []
    def forbidden_import(name):
        imports.append(name)
        raise AssertionError("supported rows should use the stdlib encoders")
    monkeypatch.setattr(parsed, "import_module", forbidden_import)
    result = encode([{"name": "eth1", "status": True}, {"name": "eth2", "status": False}])
    assert {source for _, source, _, _ in result} >= {"parsed:toon", "parsed:gcf"}
    assert imports == []
