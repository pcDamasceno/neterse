"""Validate neterse against live NAPALM getters.

Connects to real devices, runs each requested NAPALM getter, and feeds the
returned structure through ``neterse.compact`` (the shape-dispatch entry the
README advertises for "rows something already parsed — NAPALM getters"). For
every getter we record:

* whether the getter ran (drivers implement different subsets),
* whether neterse raised (it must never — fail-open is invariant #1),
* the compact-JSON baseline size a consumer would otherwise send,
* the neterse output size and the resulting saving,
* whether neterse's output round-trips back to the SAME data as the baseline
  when it produced a shrunk CSV/TOON encoding (faithfulness spot-check).

Run:
    python scripts/validate_napalm.py
"""
from __future__ import annotations

import csv
import io
import json
import os
from typing import Any, Optional

import neterse
from neterse.normalizers import keyed_dict

DEVICES = [
    {
        "name": "nxos-3548X2",
        "driver": "nxos_ssh",
        "hostname": "10.80.255.43",
        "optional_args": {},
    },
    {
        "name": "eos-Metamako48LB-06",
        "driver": "eos",
        "hostname": "10.80.255.30",
        "optional_args": {"transport": "https"},
    },
]

USERNAME = os.environ.get("NAPALM_USER", "admin")
PASSWORD = os.environ.get("NAPALM_PASS", "admin")

GETTERS = [
    "get_arp_table",
    "get_bgp_config",
    "get_bgp_neighbors",
    "get_bgp_neighbors_detail",
    "get_config",
    "get_environment",
    "get_facts",
    "get_interfaces",
    "get_interfaces_counters",
    "get_interfaces_ip",
    "get_lldp_neighbors",
    "get_lldp_neighbors_detail",
    "get_mac_address_table",
    "get_network_instances",
    "get_ntp_peers",
    "get_ntp_servers",
    "get_ntp_stats",
    "get_optics",
    "get_route_to",
    "get_snmp_information",
    "get_users",
    "get_vlans",
]

# Getters whose signature needs an argument — pick a harmless probe value or
# skip if the device can't answer it. Left empty means call with no args.
GETTER_ARGS = {
    "get_route_to": {},  # returns full table when no destination given
}


def _baseline(obj: Any) -> str:
    """Compact JSON a consumer would otherwise drop into context."""
    return json.dumps(obj, separators=(",", ":"), default=str)


def _faithful_csv(shrunk: str, baseline_obj: Any) -> Optional[bool]:
    """Spot-check that a shrunk CSV encoding carries the same field values as
    the baseline. Returns True/False, or None when the check doesn't apply
    (output wasn't a flat CSV, e.g. TOON won or passthrough)."""
    # Normalise baseline to a list of str->value rows the way neterse does —
    # including the {name: {...}} -> rows flattening the parsed tier applies.
    if isinstance(baseline_obj, dict):
        flat = keyed_dict(baseline_obj)
        rows = flat if flat is not None else [baseline_obj]
    elif isinstance(baseline_obj, list) and all(isinstance(r, dict) for r in baseline_obj):
        rows = baseline_obj
    else:
        return None
    if not rows:
        return None
    first_line = shrunk.split("\n", 1)[0]
    if first_line.startswith("[") and "]{" in first_line:
        return None  # TOON, not CSV — skip this simple check
    try:
        parsed = list(csv.DictReader(io.StringIO(shrunk)))
    except Exception:
        return None
    if len(parsed) != len(rows):
        return False

    def _cell(val: Any) -> str:
        # Mirror neterse.parsed._cell so bool/None normalisation matches.
        if val is None:
            return ""
        if val is True:
            return "true"
        if val is False:
            return "false"
        return str(val)

    # Every original scalar cell must reappear verbatim in the CSV.
    for orig, got in zip(rows, parsed):
        for key, val in orig.items():
            if isinstance(val, (dict, list)):
                continue  # nested cells are JSON-encoded; skip in this simple check
            if _cell(val) != (got.get(key) or ""):
                return False
    return True


def run_device(spec: dict) -> list[dict]:
    import napalm

    driver = napalm.get_network_driver(spec["driver"])
    dev = driver(
        hostname=spec["hostname"],
        username=USERNAME,
        password=PASSWORD,
        optional_args=spec["optional_args"],
    )
    dev.open()
    results = []
    try:
        for name in GETTERS:
            row = {"getter": name}
            getter = getattr(dev, name, None)
            if getter is None:
                row["status"] = "no-attr"
                results.append(row)
                continue
            try:
                data = getter(**GETTER_ARGS.get(name, {}))
            except NotImplementedError:
                row["status"] = "not-implemented"
                results.append(row)
                continue
            except Exception as exc:  # device/driver error, not neterse's fault
                row["status"] = "getter-error"
                row["detail"] = f"{type(exc).__name__}: {exc}"[:100]
                results.append(row)
                continue

            baseline = _baseline(data)
            try:
                out = neterse.compact(data)
            except Exception as exc:
                row["status"] = "NETERSE-RAISED"
                row["detail"] = f"{type(exc).__name__}: {exc}"[:120]
                results.append(row)
                continue

            row["status"] = "ok"
            row["base_chars"] = len(baseline)
            row["out_chars"] = len(out)
            row["saved_pct"] = (
                round(100 * (1 - len(out) / len(baseline)), 1) if baseline else 0.0
            )
            row["shrank"] = len(out) < len(baseline)
            faithful = _faithful_csv(out, data) if row["shrank"] else None
            row["faithful"] = faithful
            results.append(row)
    finally:
        dev.close()
    return results


def print_report(name: str, rows: list[dict]) -> None:
    print(f"\n{'='*78}\n  {name}\n{'='*78}")
    hdr = f"{'getter':28} {'status':16} {'base':>7} {'out':>7} {'saved%':>7} {'faithful':>9}"
    print(hdr)
    print("-" * len(hdr))
    tot_base = tot_out = 0
    ok = shrank = 0
    for r in rows:
        if r["status"] == "ok":
            ok += 1
            tot_base += r["base_chars"]
            tot_out += r["out_chars"]
            shrank += 1 if r["shrank"] else 0
            faith = {True: "yes", False: "NO", None: "-"}[r["faithful"]]
            print(
                f"{r['getter']:28} {r['status']:16} {r['base_chars']:>7} "
                f"{r['out_chars']:>7} {r['saved_pct']:>7} {faith:>9}"
            )
        else:
            detail = r.get("detail", "")
            print(f"{r['getter']:28} {r['status']:16} {detail}")
    if tot_base:
        agg = round(100 * (1 - tot_out / tot_base), 1)
        print("-" * len(hdr))
        print(
            f"{'TOTAL (ran ok: %d, shrank: %d)' % (ok, shrank):28} "
            f"{'':16} {tot_base:>7} {tot_out:>7} {agg:>7}"
        )


def main() -> None:
    for spec in DEVICES:
        try:
            rows = run_device(spec)
        except Exception as exc:
            print(f"\n[{spec['name']}] CONNECTION FAILED: {type(exc).__name__}: {exc}")
            continue
        print_report(spec["name"], rows)


if __name__ == "__main__":
    main()
