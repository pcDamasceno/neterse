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
— re-exporting the names ``registry.py``, ``engine.py`` and the tests
import from it.
"""

from __future__ import annotations

from .helpers import (  # noqa: F401
    _csv_row,
    _fixed_width_rows,
    _wrapped_first_col_rows,
)

from .shared import (  # noqa: F401
    _compress_interfaces,
    _compress_running_config,
    _compress_acl,
    _compress_inventory,
    _compress_syslog,
)

from .cisco_ios import (  # noqa: F401
    _compress_processes_memory_sorted,
    _compress_show_vrf,
    _compress_ip_route_vrf_summary,
    _compress_bgp_all_summary,
    _compress_ip_protocols,
)

from .cisco_nxos import (  # noqa: F401
    _compress_intf_counter_errors,
    _compress_transceiver_inventory,
    _compress_portchannel_summary,
    _compress_hardware_internal_errors,
    _compress_environment,
    _compress_transceiver_details,
    _compress_interface_capabilities,
)
