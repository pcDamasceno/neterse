#!/usr/bin/env python3
"""Repeatable compaction latency/memory benchmark; JSON output, stdlib only."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
from pathlib import Path
import statistics
import sys
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from neterse import compact  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, nargs="+", default=[1000, 10000])
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()
    if args.repeat < 1 or any(size < 1 for size in args.rows):
        parser.error("row counts and repeat must be positive")
    extras = {}
    for name in ("gcf-python", "toon-format"):
        try:
            extras[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            extras[name] = None
    results = []
    for size in args.rows:
        rows = [{
            "name": f"eth{i}", "status": "up", "description": f"uplink to switch {i}",
            "vlan": i % 4094, "mtu": 9000,
        } for i in range(size)]
        compact(rows)  # warm imports and caches outside the measurement
        samples = []
        for _ in range(args.repeat):
            start = time.perf_counter()
            output = compact(rows)
            samples.append(time.perf_counter() - start)
        tracemalloc.start()
        compact(rows)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        results.append({
            "rows": size, "input_chars": len(json.dumps(rows, separators=(",", ":"))),
            "output_chars": len(output), "median_seconds": statistics.median(samples),
            "peak_traced_bytes": peak,
        })
    print(json.dumps({"python": platform.python_version(), "extras": extras, "results": results}, indent=2))


if __name__ == "__main__":
    main()
