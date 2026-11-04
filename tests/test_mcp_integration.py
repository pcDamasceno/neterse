"""Optional FastMCP integration tests, bounded by request deadlines."""
from __future__ import annotations

import asyncio
import json
import pytest

from .test_mcp import ENVELOPE, PRETTY, RAW_CLI

# ---------------------------------------------------------------------------
# CompactMiddleware — through a real in-memory FastMCP server
# ---------------------------------------------------------------------------

fastmcp = pytest.importorskip("fastmcp", reason="needs the mcp extra")


def _server(ledger=False):
    from fastmcp import FastMCP

    from neterse.mcp import CompactMiddleware

    mcp = FastMCP("toy")

    @mcp.tool
    def tenants() -> str:
        return PRETTY

    # dict return + declared output schema: FastMCP mirrors the return
    # into structuredContent AND the server layer enforces that every
    # result carries structured output — the exact upstream shape that
    # both negated the savings and rejected a plain drop in the field
    @mcp.tool(output_schema={"type": "object", "additionalProperties": True})
    def tenants_obj() -> dict:
        return ENVELOPE

    @mcp.tool
    def freeform() -> str:
        return RAW_CLI

    @mcp.tool
    def broken() -> str:
        raise ValueError("upstream failure")

    mcp.add_middleware(CompactMiddleware(ledger=ledger))
    return mcp


def _call(server, tool):
    from fastmcp import Client

    async def scenario():
        async with asyncio.timeout(10), Client(server, timeout=5) as client:
            return await client.call_tool(tool, {}, raise_on_error=False)

    return asyncio.run(scenario())


def test_middleware_compacts_json_tool_results():
    result = _call(_server(), "tenants")
    text = result.content[0].text
    assert len(text) < len(PRETTY)
    assert "uni/tn-common" in text


def test_middleware_drops_the_structured_duplicate():
    """A dict-returning tool arrives with text + a structuredContent
    mirror; after compaction only the compacted text may remain, the
    call must not become an output-validation error, and the client must
    accept the result."""
    result = _call(_server(), "tenants_obj")
    assert not result.is_error, result.content[0].text
    assert len(result.content[0].text) < len(json.dumps(ENVELOPE, indent=2))
    assert result.structured_content is None


def test_listed_tools_shed_the_output_schema_while_dedupe_is_on():
    """Dropping structured output obliges the listing to stop promising
    it — otherwise the MCP server layer rejects the compacted result."""
    from fastmcp import Client

    async def scenario(server):
        async with asyncio.timeout(10), Client(server, timeout=5) as client:
            return {t.name: t.outputSchema for t in await client.list_tools()}

    schemas = asyncio.run(scenario(_server()))
    assert schemas["tenants_obj"] is None
    # opting out restores the upstream contract verbatim
    from neterse.mcp import CompactMiddleware
    from fastmcp import FastMCP

    mcp = FastMCP("toy2")

    @mcp.tool(output_schema={"type": "object", "additionalProperties": True})
    def tenants_obj() -> dict:
        return ENVELOPE

    mcp.add_middleware(CompactMiddleware(ledger=False, dedupe_structured=False))
    schemas = asyncio.run(scenario(mcp))
    assert schemas["tenants_obj"] is not None


def test_middleware_leaves_non_json_results_alone():
    result = _call(_server(), "freeform")
    assert result.content[0].text == RAW_CLI


def test_middleware_passes_errors_through():
    result = _call(_server(), "broken")
    assert result.is_error


def test_ledger_reports_the_win(capfd):
    _call(_server(ledger=True), "tenants")
    err = capfd.readouterr().err
    assert "[neterse] tenants:" in err and "chars" in err


def test_large_blocks_compact_off_the_event_loop_and_respect_budget(monkeypatch):
    import threading
    from fastmcp import FastMCP
    import neterse.mcp as module

    text = PRETTY + " " * 65536
    main_thread = threading.get_ident()
    workers = []
    original = module.compact_text

    def observe(value):
        workers.append(threading.get_ident())
        return original(value)

    monkeypatch.setattr(module, "compact_text", observe)
    for budget in (None, 10):
        server = FastMCP("large-response")
        @server.tool
        async def large() -> str:
            return text
        server.add_middleware(module.CompactMiddleware(ledger=False, max_input_chars=budget))
        result = _call(server, "large")
        if budget is None:
            assert len(result.content[0].text) < len(text)
        else:
            assert result.content[0].text == text
    assert len(workers) == 1 and workers[0] != main_thread
