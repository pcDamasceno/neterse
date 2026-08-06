"""``neterse.mcp`` — tool-result compaction at the MCP seam (decision 38).

The pure core (``compact_text`` / ``compact_result``) is exercised
dependency-free on wire-shaped dicts. The fastmcp adapters are gated on
the ``mcp`` extra with importorskip and drive a real in-memory FastMCP
server through ``CompactMiddleware`` — asyncio.run keeps the suite free
of pytest-asyncio.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from neterse.mcp import compact_result, compact_text

# The shape the aci verification target returns: an APIC envelope whose
# imdata list the cisco_aci normalizer claims.
ENVELOPE = {
    "totalCount": "3",
    "imdata": [
        {
            "fvTenant": {
                "attributes": {
                    "name": name,
                    "dn": f"uni/tn-{name}",
                    "status": "",
                    "descr": "",
                }
            }
        }
        for name in ("common", "mgmt", "infra")
    ],
}
PRETTY = json.dumps(ENVELOPE, indent=2)

RAW_CLI = (
    "Interface              IP-Address      OK? Method Status   Protocol\n"
    "GigabitEthernet0/0     192.168.1.1     YES NVRAM  up       up\n"
)


# ---------------------------------------------------------------------------
# compact_text — the pure seam
# ---------------------------------------------------------------------------

def test_pretty_json_container_shrinks():
    out = compact_text(PRETTY)
    assert len(out) < len(PRETTY)
    # the win must also beat the compact-JSON reading of the same payload
    assert len(out) < len(json.dumps(ENVELOPE, separators=(",", ":")))


def test_rows_survive_in_the_compacted_form():
    out = compact_text(PRETTY)
    for name in ("common", "mgmt", "infra"):
        assert f"uni/tn-{name}" in out


def test_non_json_text_is_untouched():
    assert compact_text(RAW_CLI) is RAW_CLI


def test_json_scalars_are_never_claimed():
    for scalar in ("null", "42", '"hello"', "true", "  3.14  "):
        assert compact_text(scalar) is scalar


def test_broken_json_is_untouched():
    broken = '{"imdata": [unterminated'
    assert compact_text(broken) is broken


def test_empty_and_non_string_fail_open():
    assert compact_text("") == ""
    assert compact_text(None) is None          # type: ignore[arg-type]


def test_no_win_returns_the_original_text():
    # already minimal: compact JSON of a shape no candidate undercuts
    tiny = '{"a":{"b":[1,2,{"c":3}]}}'
    assert compact_text(tiny) == tiny


# ---------------------------------------------------------------------------
# compact_result — the wire shape
# ---------------------------------------------------------------------------

def _result(**overrides):
    base = {
        "content": [{"type": "text", "text": PRETTY}],
        "isError": False,
    }
    base.update(overrides)
    return base


def test_text_blocks_are_compacted():
    out = compact_result(_result())
    assert len(out["content"][0]["text"]) < len(PRETTY)


def test_input_is_never_mutated():
    result = _result()
    compact_result(result)
    assert result["content"][0]["text"] == PRETTY


def test_error_results_pass_through_identically():
    result = _result(isError=True)
    assert compact_result(result) is result


def test_non_text_blocks_are_untouched():
    image = {"type": "image", "data": "aGkh", "mimeType": "image/png"}
    out = compact_result(_result(content=[image, {"type": "text", "text": PRETTY}]))
    assert out["content"][0] is image
    assert len(out["content"][1]["text"]) < len(PRETTY)


def test_duplicate_structured_content_is_dropped():
    """FastMCP mirrors a dict return into structuredContent; a deep-equal
    copy of what the compacted text decoded to must not survive to hand
    the model the original anyway."""
    out = compact_result(_result(structuredContent=json.loads(PRETTY)))
    assert "structuredContent" not in out
    assert len(out["content"][0]["text"]) < len(PRETTY)


def test_result_mirror_structured_content_is_rewritten():
    """A str-returning FastMCP tool mirrors as {'result': <text>} — still
    a string after compaction, so rewrite instead of drop."""
    out = compact_result(_result(structuredContent={"result": PRETTY}))
    assert out["structuredContent"] == {"result": out["content"][0]["text"]}


def test_independent_structured_content_is_preserved_verbatim():
    extra = {"result": "something the text block does not carry"}
    out = compact_result(_result(structuredContent=extra))
    assert out["structuredContent"] is extra


def test_keep_structured_opts_out_of_the_dedupe():
    duplicate = json.loads(PRETTY)
    out = compact_result(
        _result(structuredContent=duplicate), dedupe_structured=False
    )
    assert out["structuredContent"] is duplicate


def test_structured_content_untouched_when_no_block_wins():
    duplicate = {"note": RAW_CLI}
    result = _result(
        content=[{"type": "text", "text": RAW_CLI}],
        structuredContent=duplicate,
    )
    assert compact_result(result) is result


def test_block_extras_survive_the_rewrite():
    block = {"type": "text", "text": PRETTY, "annotations": {"audience": ["assistant"]}}
    out = compact_result(_result(content=[block]))
    assert out["content"][0]["annotations"] == {"audience": ["assistant"]}


def test_unclaimed_results_return_the_same_object():
    for result in (
        "not a dict",
        {"content": "not a list"},
        {},
        _result(content=[{"type": "text", "text": RAW_CLI}]),
    ):
        assert compact_result(result) is result


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
        async with Client(server) as client:
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
        async with Client(server) as client:
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


def test_module_imports_and_placeholder_names_the_extra(monkeypatch):
    """Without fastmcp, ``import neterse.mcp`` must still succeed (the
    pure core is stdlib) and the middleware class must raise a
    pip-install pointer only when INSTANTIATED."""
    import importlib
    import sys

    import neterse.mcp as mcp_module

    # None in sys.modules makes the module-scope import raise
    # ImportError even though a real fastmcp is installed.
    monkeypatch.setitem(sys.modules, "fastmcp", None)
    monkeypatch.setitem(sys.modules, "fastmcp.server", None)
    monkeypatch.setitem(sys.modules, "fastmcp.server.middleware", None)
    try:
        importlib.reload(mcp_module)
        assert mcp_module.compact_text(PRETTY)      # core still works
        with pytest.raises(ImportError, match=r"neterse\[mcp\]"):
            mcp_module.CompactMiddleware()
    finally:
        monkeypatch.undo()
        importlib.reload(mcp_module)
