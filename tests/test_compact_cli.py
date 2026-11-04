"""CLI behavior at the stdin/stdout boundary, including audit automation."""
import io
import json

import pytest

from neterse.audit import main
from .corpus import ACL


def test_json_compaction_and_explanation_use_separate_streams(monkeypatch, capsys):
    rows = [{"interface": "eth1", "status": "up"}, {"interface": "eth2", "status": "down"}]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(rows)))
    assert main(["compact", "--input-format", "json", "--explain"]) == 0
    streams = capsys.readouterr()
    assert len(streams.out) < len(json.dumps(rows, separators=(",", ":")))
    report = json.loads(streams.err)
    assert report["source"].startswith("parsed:")
    assert report["dropped_fields"] == []
    assert report["output_chars"] == len(streams.out)


def test_lossless_only_keeps_raw_when_all_candidates_drop_fields(tmp_path, capsys):
    path = tmp_path / "capture.txt"
    path.write_text(ACL)
    args = ["compact", str(path), "--command", "show ip access-lists"]
    assert main(args) == 0
    assert len(capsys.readouterr().out) < len(ACL)
    assert main([*args, "--lossless-only"]) == 0
    assert capsys.readouterr().out == ACL


def test_raw_passthrough_preserves_crlf_and_final_newline(tmp_path, capsys):
    raw = "unknown output\r\nsecond line\r\n"
    path = tmp_path / "raw.txt"
    path.write_bytes(raw.encode())
    assert main(["compact", str(path)]) == 0
    assert capsys.readouterr().out == raw


def test_invalid_json_reports_an_error(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("{broken"))
    with pytest.raises(SystemExit, match="neterse compact:"):
        main(["compact", "--input-format", "json"])


def test_audit_json_stays_parseable_when_savings_gate_fails(tmp_path, capsys):
    path = tmp_path / "samples.jsonl"
    path.write_text(json.dumps({"command": "show clock", "raw": "secret capture text"}) + "\n")
    assert main(["audit", str(path), "--json", "--fail-under", "50"]) == 1
    streams = capsys.readouterr()
    report = json.loads(streams.out)
    assert report["totals"]["reduction_pct"] == 0
    assert "secret capture text" not in streams.out
    assert "FAIL" in streams.err


def test_empty_audit_does_not_pass_a_positive_savings_gate(tmp_path, capsys):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    assert main(["audit", str(path), "--json", "--fail-under", "1"]) == 1
    assert json.loads(capsys.readouterr().out)["samples"] == []
