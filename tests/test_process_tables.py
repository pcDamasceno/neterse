"""Regression coverage for large IOS process tables seen in agent runs."""
from __future__ import annotations

from neterse import optimize, render


CPU = """CPU utilization for five seconds: 3%/0%; one minute: 2%; five minutes: 2%
 PID Runtime(ms)     Invoked      uSecs   5Sec   1Min   5Min TTY Process
 326      534035     8702027         61  0.39%  0.07%  0.06%   0 IGMPSN
 123     2543956    89830339         28  0.31%  0.24%  0.24%   0 IOSD ipc task
  13          37        9530          3  0.00%  0.00%  0.00%   0 WATCH_AFS
"""

MEMORY = """Processor Pool Total: 2684897564 Used:  424488928 Free: 2260408636
reserve P Pool Total:     102404 Used:         88 Free:     102316
 lsmpi_io Pool Total:    6295128 Used:    6294296 Free:        832

 PID TTY  Allocated      Freed    Holding    Getbufs    Retbufs Process
   0   0  386258096   83172144  275108352          0          0 *Init*
 326   0  515163064  470436120   23036248          0          0 IGMPSN
 123   0  187809048  151136512    1988696          0          0 IOS-XE Punt Service
"""


def test_process_cpu_sorted_preserves_context_and_every_row():
    out = optimize("show processes cpu sorted 5sec", CPU)
    assert out.splitlines() == [
        "CPU utilization for five seconds: 3%/0%; one minute: 2%; five minutes: 2%",
        "pid,runtime_ms,invoked,usecs,cpu_5sec,cpu_1min,cpu_5min,tty,process",
        "326,534035,8702027,61,0.39%,0.07%,0.06%,0,IGMPSN",
        "123,2543956,89830339,28,0.31%,0.24%,0.24%,0,IOSD ipc task",
        "13,37,9530,3,0.00%,0.00%,0.00%,0,WATCH_AFS",
    ]


def test_process_memory_sorted_preserves_pool_context_and_every_row():
    out = optimize("show processes memory sorted", MEMORY)
    assert out.splitlines() == [
        "Processor Pool Total: 2684897564 Used:  424488928 Free: 2260408636",
        "reserve P Pool Total:     102404 Used:         88 Free:     102316",
        "lsmpi_io Pool Total:    6295128 Used:    6294296 Free:        832",
        "pid,tty,allocated,freed,holding,getbufs,retbufs,process",
        "0,0,386258096,83172144,275108352,0,0,*Init*",
        "326,0,515163064,470436120,23036248,0,0,IGMPSN",
        "123,0,187809048,151136512,1988696,0,0,IOS-XE Punt Service",
    ]


def test_process_tables_are_declared_lossless_and_fail_open():
    for command, raw in (
        ("show processes cpu sorted 5sec", CPU),
        ("show processes memory sorted", MEMORY),
    ):
        candidates = render(raw, command=command, platform="cisco_iosxe")
        assert candidates
        assert min(candidates, key=lambda candidate: len(candidate.text)).dropped_fields == ()
        assert optimize(command, "unexpected output") == "unexpected output"