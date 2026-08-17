"""Hand-written compressors — the code tier of the registry.

Since Phase 1, table-shaped command families live as declarative specs
(the YAML-authored ``specs/`` package) compiled by the engine — and
since Phase 2 the same is
true of ``show version``-style field scans (``kv_extract``). What remains
here is the small set of genuinely stateful formats a flat spec cannot
express faithfully — multi-line interface-detail blocks (NX-OS splits
state across lines), banner state machines, and multi-table zero-row
suppression — plus the fixed-width helpers the engine reuses.
Registration order lives in ``registry.py``; nothing self-registers here.

Only the standard library may be imported — this module stays the
zero-dependency leaf of the package. Function bodies are byte-parity
pinned against the pre-extraction baseline by the test suite.

Since decision 42 this is a PACKAGE — helpers plus one module per
vendor scope (``helpers``, ``shared``, ``cisco_ios``, ``cisco_nxos``)
— re-exporting every name, so ``registry.py``'s and ``engine.py``\'s
imports are unchanged.
"""

from __future__ import annotations

from .helpers import (  # noqa: F401
    _iface_block_header,
    _slug,
    _IFACE_NAME_RE,
    _csv_row,
    _header_positions,
    _fixed_width_rows,
    _wrapped_first_col_rows,
)

from .shared import (  # noqa: F401
    _INTF_HEADER,
    _INTF_NXOS_HEADER,
    _INTF_NXOS_ADMIN,
    _INTF_MTU,
    _INTF_BW,
    _INTF_DUPLEX,
    _INTF_INPUT_RATE,
    _INTF_OUTPUT_RATE,
    _INTF_INPUT_ERRORS,
    _INTF_OUTPUT_ERRORS,
    _INTF_CRC,
    _INTF_DESCRIPTION,
    _compress_interfaces,
    _compress_running_config,
    _compress_acl,
    _INV_NAME_RE,
    _INV_PID_RE,
    _compress_inventory,
    _SYSLOG_LINE_RE,
    _compress_syslog,
)

from .cisco_ios import (  # noqa: F401
    _PROCESS_MEMORY_ROW,
    _PROCESS_MEMORY_POOL,
    _compress_processes_memory_sorted,
    _VRF_HEADER_WORDS,
    _compress_show_vrf,
    _ROUTE_SUMMARY_NAME,
    _ROUTE_SUMMARY_MAX_PATHS,
    _ROUTE_SUMMARY_HEADER,
    _compress_ip_route_vrf_summary,
    _BGP_ALL_AF,
    _BGP_ALL_ROW,
    _BGP_ALL_HEADER_WORDS,
    _compress_bgp_all_summary,
    _IPPROTO_HEADER,
    _IPPROTO_SECTIONS,
    _IPPROTO_SECTION_HEADER,
    _IPPROTO_FILTER_NOT_SET,
    _IPPROTO_LINES,
    _compress_ip_protocols,
)

from .cisco_nxos import (  # noqa: F401
    _COUNTER_VAL_RE,
    _compress_intf_counter_errors,
    _TRANSCEIVER_FIELD_RE,
    _compress_transceiver_inventory,
    _compress_portchannel_summary,
    _HWERR_CATEGORY_RE,
    _HWERR_MOD_RE,
    _HWERR_INSTANCE_RE,
    _HWERR_VALUE_RE,
    _compress_hardware_internal_errors,
    _compress_environment,
    _XCVR_DETAIL_TITLE_RE,
    _XCVR_METRIC_RE,
    _XCVR_FAULT_RE,
    _compress_transceiver_details,
    _CAPABILITY_FIELD_RE,
    _compress_interface_capabilities,
)
