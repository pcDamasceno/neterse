"""The `terse audit` CLI: corpus loading, opportunity tags, exit codes.

The fixture-directory ingestion path is covered in
test_fixture_corpus.py (it doubles as the contribution-flow smoke test);
this file pins the JSONL path, the three opportunity tags, and the CLI
contract.
"""
from __future__ import annotations

import io
import json

import pytest

from terse.audit import load_samples, main, run_report

from .corpus import ACL, IP_ROUTE, STATUS


def _jsonl(tmp_path, rows, name="samples.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(p)


def _report(samples):
    buf = io.StringIO()
    red = run_report(samples, show=0, out=buf)
    return red, buf.getvalue()


def test_jsonl_loading_accepts_output_alias_and_platform(tmp_path):
    path = _jsonl(tmp_path, [
        {"command": "show ip route", "raw": IP_ROUTE, "platform": "cisco_ios"},
        {"command": "show ip access-lists", "output": ACL},
    ])
    samples = load_samples([path], command=None)
    assert samples == [
        ("show ip route", "cisco_ios", IP_ROUTE),
        ("show ip access-lists", None, ACL),
    ]


def test_jsonl_rejects_malformed_lines(tmp_path):
    path = _jsonl(tmp_path, [{"command": "x"}])   # no raw
    with pytest.raises(SystemExit):
        load_samples([path], command=None)


def test_raw_capture_file_needs_command(tmp_path):
    p = tmp_path / "capture.txt"
    p.write_text(STATUS)
    with pytest.raises(SystemExit):
        load_samples([str(p)], command=None)
    assert load_samples([str(p)], command="show interface status") == [
        ("show interface status", None, STATUS)
    ]


def test_report_tags_no_compressor_and_false_match():
    samples = [
        ("show interface status", None, STATUS),                 # covered
        ("show ip ospf database", None, "x y z\n" * 100),        # no pattern
        ("show ip route", None, "nothing route-shaped here " * 30),  # pattern, no shrink
    ]
    red, report = _report(samples)
    assert "NO COMPRESSOR" in report
    assert "false-match:spec:cisco/show_ip_route" in report
    assert "covered-by-an-entry=" in report
    assert 0 < red < 100


def test_report_tags_platform_skip_separately():
    """A pattern match killed by the platform filter is scoping doing its
    job, not a coverage gap — the report must say which."""
    samples = [("show interface ethernet1/9 brief", "arista_eos",
                "no nxos table here " * 20)]
    _, report = _report(samples)
    assert "platform-skip:spec:cisco_nxos/show_interface_brief" in report
    assert "NO COMPRESSOR" not in report


def test_report_prints_lossiness_review():
    _, report = _report([("show ip access-lists", None, ACL)])
    assert "DECLARED DROPS" in report
    assert "hit_counters" in report


def test_cli_fail_under_gates_exit_code(tmp_path, capsys):
    path = _jsonl(tmp_path, [
        {"command": "show ip route", "raw": IP_ROUTE},
    ])
    assert main(["audit", path]) == 0
    assert main(["audit", path, "--fail-under", "99"]) == 1
    assert main(["audit", path, "--fail-under", "10"]) == 0
    capsys.readouterr()


def test_cli_show_dumps_gap_heads(tmp_path, capsys):
    path = _jsonl(tmp_path, [
        {"command": "show ip ospf database", "raw": "lsa " * 200},
    ])
    assert main(["audit", path, "--show", "1"]) == 0
    out = capsys.readouterr().out
    assert "OPPORTUNITIES" in out
    assert "head (20 lines" in out
