"""MCP tool-result compaction — the parsed tier at the client's config seam.

Phase 8's first non-CLI surface. An MCP tool result is the same verbose
payload a runner hands back — JSON, usually pretty-printed — arriving
through a protocol instead of a connection object. The placement question
(decision 38) resolves on ownership: the application layer either already
has the verb (an agent loop you own calls :func:`neterse.compact` before
the result enters context) or cannot be modified at all (VS Code, Claude
Code); the server is editable only when you wrote it. The one seam the
consumer controls for EVERY server is the client's server config — so the
shipping artifact is a proxy, with a server-side middleware as the bonus
for servers you author. Three surfaces over one pure core:

* :func:`compact_text` — the seam itself. Claims a string only when it
  json-decodes to a container, routes it through :func:`neterse.compact`
  (normalizers → parsed tier → smallest-wins), and replaces it only when
  STRICTLY smaller than the original text. The original is the wire text,
  often pretty-printed, so the realized saving usually beats the
  compact-JSON gate inside ``optimize_parsed``.
* :func:`compact_result` — the wire shape: a ``tools/call`` result dict
  (``content`` / ``isError`` / ``structuredContent``). For raw JSON-RPC
  integrations and dependency-free tests. Pure — returns a new dict, the
  input is never mutated.
* :class:`CompactMiddleware` + :func:`main` — the fastmcp adapters
  (``pip install neterse[mcp]``): a FastMCP middleware for servers you
  author, and the ``neterse-mcp`` stdio proxy that wraps ANY upstream
  server (streamable-HTTP URL or stdio command line). Adoption is an
  edit to the client's ``mcp.json``, nothing else.

Everything not claimed passes through byte-identical: non-JSON text (the
raw tier is keyed on a CLI command string MCP does not carry — per-tool
hints are the recorded next step), JSON scalars, ``isError`` results,
non-text blocks, and ``tools/list``. ``structuredContent`` gets one
carve-out: FastMCP mirrors every tool return there, so a copy that
merely DUPLICATES the compacted text block follows it (the
``{"result": <text>}`` string mirror is rewritten, a deep-equal copy of
the decoded payload is dropped) — otherwise hosts that surface both
feed the model the original beside the compacted text and the saving is
negated. Structured data carrying anything of its own is never touched
(decision 38).

The core imports the standard library only; fastmcp is reached lazily so
``import neterse.mcp`` works without the extra and the adapters name the
missing dependency instead of failing to import. Fail-open — like
everything else here.
"""
from __future__ import annotations

import json
import sys
from typing import Any, List, Optional

from . import compact as _compact

__all__ = ["CompactMiddleware", "compact_result", "compact_text", "main"]


def compact_text(text: str) -> str:
    """The smallest faithful text for one MCP text block.

    Claims *text* only when it json-decodes to a list or dict — scalars
    re-encode to themselves and prose that happens to parse (``null``, a
    bare number) must never be touched. The decoded structure goes
    through :func:`neterse.compact`; the result replaces *text* only when
    strictly smaller. Everything else — non-JSON, scalars, a compaction
    that did not win — returns *text* unchanged.
    """
    if not isinstance(text, str):
        return text
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return text
    try:
        decoded = json.loads(stripped)
    except Exception:
        return text
    if not isinstance(decoded, (list, dict)):
        return text
    try:
        rendered = _compact(decoded)
    except Exception:                             # compact() never raises;
        return text                               # the seam still fails open
    return rendered if len(rendered) < len(text) else text


#: sentinel: "leave structuredContent exactly as it is"
_KEEP = object()


def _dedupe_structured(structured: Any, old_text: str, new_text: str) -> Any:
    """What ``structuredContent`` should become after *old_text* won
    compaction into *new_text*: the compacted text when it was FastMCP's
    ``{"result": <text>}`` string mirror (still schema-valid — any
    string is), ``None`` (drop) when it deep-equals what the text block
    decoded to — a byte-for-byte redundant copy that would hand the
    model the original anyway — and the sentinel ``_KEEP`` otherwise:
    independent structured data is never neterse's to touch."""
    if structured == {"result": old_text}:
        return {"result": new_text}
    try:
        if json.loads(old_text) == structured:
            return None
    except Exception:
        pass
    return _KEEP


def compact_result(result: Any, *, dedupe_structured: bool = True) -> Any:
    """A ``tools/call`` result (wire-shaped dict) with every text block
    compacted through :func:`compact_text`.

    Anything that is not a successful result carrying a content list —
    ``isError`` results, protocol errors, unexpected shapes — comes back
    as-is; so does the untouched input object itself when no block
    shrank. Non-text blocks are never altered. ``structuredContent``
    that merely DUPLICATES a compacted text block (FastMCP mirrors every
    tool return there) follows it: the ``{"result": <text>}`` string
    mirror is rewritten, a deep-equal copy of the decoded payload is
    dropped — otherwise the model reads the original beside the
    compacted text and the saving is negated. Structured data that
    carries anything of its own is untouched; *dedupe_structured=False*
    keeps even pure duplicates.
    """
    if not isinstance(result, dict) or result.get("isError"):
        return result
    content = result.get("content")
    if not isinstance(content, list):
        return result
    compacted: List[tuple] = []
    new_content: List[Any] = []
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ):
            new_text = compact_text(block["text"])
            if new_text != block["text"]:
                compacted.append((block["text"], new_text))
                block = {**block, "text": new_text}
        new_content.append(block)
    if not compacted:
        return result
    out = {**result, "content": new_content}
    structured = out.get("structuredContent")
    # one winning block is the only case where the duplicate is
    # attributable; anything else stays conservative
    if dedupe_structured and structured is not None and len(compacted) == 1:
        replacement = _dedupe_structured(structured, *compacted[0])
        if replacement is None:
            del out["structuredContent"]
        elif replacement is not _KEEP:
            out["structuredContent"] = replacement
    return out


def _ledger(tool: str, before: int, after: int) -> None:
    """One stderr line per compacted call. stderr is the host's log
    channel (stdout carries the protocol); tokens are chars/4 by the
    ledger convention (decision 8)."""
    saved = 100 - round(100 * after / before) if before else 0
    print(
        f"[neterse] {tool}: {before:,} -> {after:,} chars "
        f"(~{before // 4:,} -> ~{after // 4:,} tok, -{saved}%)",
        file=sys.stderr,
        flush=True,
    )


try:
    from fastmcp.server.middleware import Middleware as _FastMCPMiddleware
except ImportError:                               # extra not installed
    _FastMCPMiddleware = None


if _FastMCPMiddleware is not None:

    class CompactMiddleware(_FastMCPMiddleware):
        """FastMCP middleware: every ``tools/call`` result through
        :func:`compact_text`. One line in a server you author
        (``mcp.add_middleware(CompactMiddleware())``); the ``neterse-mcp``
        proxy attaches it to servers you do not.

        *ledger* writes a per-call savings line to stderr whenever a
        block shrank (silent on pass-through — signal, not noise).
        *dedupe_structured* (default on) makes ``structuredContent`` that
        merely duplicated the compacted text block follow it — rewritten
        for the ``{"result": <text>}`` mirror, dropped for a deep-equal
        copy — so hosts that surface both never feed the model the
        original beside the compacted text. Independent structured data
        is untouched either way. Dropping obliges a matching change in
        ``tools/list``: the MCP server layer rejects any result whose
        tool declares ``outputSchema`` but carries no structured output,
        so while dedupe is on, listed tools shed ``output_schema`` — the
        contract this middleware actually provides is "the text block is
        the payload" (input schemas are untouched; structured content
        that survives dedupe still flows, just unvalidated).
        """

        def __init__(
            self, *, ledger: bool = True, dedupe_structured: bool = True
        ) -> None:
            self.ledger = ledger
            self.dedupe_structured = dedupe_structured

        async def on_list_tools(self, context: Any, call_next: Any) -> Any:
            tools = await call_next(context)
            if not self.dedupe_structured:
                return tools
            try:
                return [
                    tool.model_copy(update={"output_schema": None})
                    if getattr(tool, "output_schema", None) is not None
                    else tool
                    for tool in tools
                ]
            except Exception:                     # fail-open: an unlisted
                return tools                      # schema beats no listing

        async def on_call_tool(self, context: Any, call_next: Any) -> Any:
            result = await call_next(context)
            try:
                if getattr(result, "is_error", False):
                    return result
                blocks = list(getattr(result, "content", None) or [])
                before = after = 0
                compacted = []
                for i, block in enumerate(blocks):
                    text = getattr(block, "text", None)
                    if getattr(block, "type", None) != "text" or not isinstance(
                        text, str
                    ):
                        continue
                    new_text = compact_text(text)
                    before += len(text)
                    after += len(new_text)
                    if new_text != text:
                        blocks[i] = block.model_copy(update={"text": new_text})
                        compacted.append((text, new_text))
                if not compacted:
                    return result
                update: dict = {"content": blocks}
                structured = getattr(result, "structured_content", None)
                if (
                    self.dedupe_structured
                    and structured is not None
                    and len(compacted) == 1
                ):
                    replacement = _dedupe_structured(
                        structured, *compacted[0]
                    )
                    if replacement is not _KEEP:
                        update["structured_content"] = replacement
                if self.ledger:
                    tool = getattr(
                        getattr(context, "message", None), "name", "?"
                    )
                    _ledger(tool, before, after)
                return result.model_copy(update=update)
            except Exception:                     # fail-open: the upstream
                return result                     # result is never lost

else:

    class CompactMiddleware:  # type: ignore[no-redef]
        """Placeholder that names the missing extra instead of an
        ImportError at ``import neterse.mcp`` time."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "CompactMiddleware needs fastmcp — "
                "pip install 'neterse[mcp]'"
            )


def main(argv: Optional[List[str]] = None) -> int:
    """``neterse-mcp`` — a stdio proxy that compacts any MCP server's
    tool results. The upstream is a streamable-HTTP URL or the stdio
    command line that would have been the client's server entry."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="neterse-mcp",
        description=(
            "MCP proxy: forwards every request to the upstream server and "
            "compacts tools/call results (neterse parsed tier, "
            "smallest-wins, fail-open). Point your client's server config "
            "here instead of at the upstream."
        ),
    )
    parser.add_argument(
        "upstream",
        nargs="+",
        help=(
            "streamable-HTTP URL (https://host/mcp) or the stdio command "
            "line that starts the upstream server (docker run ... / npx ...)"
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress the per-call savings ledger on stderr",
    )
    parser.add_argument(
        "--keep-structured",
        action="store_true",
        help=(
            "leave structuredContent alone even when it merely duplicates "
            "a compacted text block (default: rewrite the {'result': text} "
            "mirror, drop a deep-equal copy)"
        ),
    )
    args = parser.parse_args(argv)

    try:
        from fastmcp.server import create_proxy
    except ImportError:
        try:                                      # pre-3.3 spelling
            from fastmcp import FastMCP
        except ImportError:
            parser.error(
                "the proxy needs fastmcp — pip install 'neterse[mcp]'"
            )
        create_proxy = FastMCP.as_proxy

    upstream = args.upstream
    if len(upstream) == 1 and upstream[0].startswith(("http://", "https://")):
        backend: Any = upstream[0]
    else:
        import os

        from fastmcp.client.transports import StdioTransport

        # The host applied the config's env block to THIS process; the
        # MCP SDK's default child env is a scrubbed allowlist that would
        # starve a `docker run -e VAR` upstream, so forward all of it.
        backend = StdioTransport(
            command=upstream[0], args=upstream[1:], env=dict(os.environ)
        )

    proxy = create_proxy(backend, name="neterse-mcp")
    proxy.add_middleware(
        CompactMiddleware(
            ledger=not args.quiet,
            dedupe_structured=not args.keep_structured,
        )
    )
    proxy.run(show_banner=False)
    return 0


if __name__ == "__main__":                        # python -m neterse.mcp
    sys.exit(main())
