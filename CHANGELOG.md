# Changelog

## 0.1.0

Initial standalone cut, ported verbatim from dbcli's TOON optimizer
(`dbcli/services/token_optimizer.py`, netclaw-inspired).

- 15 compressor families (IOS + NX-OS): ip route, ip interface brief,
  interface detail, version, bgp summary, ospf neighbors, running-config,
  cdp/lldp neighbors, vlan brief, access-lists, interface status,
  interface brief (NX-OS), interface counters errors, eigrp neighbors,
  port-channel summary.
- Frozen public API: `render(raw, command=..., platform/parsed/profile
  reserved) -> [Candidate]`, `optimize()` (historical smallest-wins
  behavior, byte-for-byte), `register()` plugin escape hatch,
  `iter_compressors()`.
- Byte-parity suite against the frozen pre-extraction baseline
  (`tests/legacy_snapshot.py`): full command x body cross-matrix incl.
  wrong-command pairings and edge inputs.
- Zero runtime dependencies (enforced in CI), `py.typed`, Apache-2.0.
