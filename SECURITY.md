# Security policy

Security fixes are maintained on `main` and included in subsequent releases.
Keep optional dependencies current; the zero-dependency core does not imply
that the MCP, TextFSM, or reference-encoder extras have no dependencies.

## Report a vulnerability

Use the repository's [private vulnerability reporting page](https://github.com/pcDamasceno/neterse/security/advisories/new)
when available. If private reporting is unavailable, open an issue asking
for a private contact without including exploit details, credentials, or
device captures. Include the neterse version, dependency versions, affected
entry point, and a sanitized reproducer in the private report.

## Trust boundaries

- Compression is not redaction. Running configurations, API responses, and
  raw fallbacks can contain secrets. Apply your own redaction before sending
  output to a model or sharing a fixture. Preserve column widths when
  sanitizing fixed-width captures.
- MCP upstreams execute with their configured privileges. The stdio proxy
  forwards its environment for compatibility with existing client configs;
  launch it with only the credentials that upstream needs.
- Prefer `--header-env Name=VARIABLE` to literal credentials in `--header`.
  Environment values still require protection, but are not command-line
  arguments. Use the client's secret store where possible. Use HTTPS for
  authenticated remote connections.
- Tool output remains untrusted content, even after compression. Compaction
  does not remove prompt injection or authorize actions suggested by a tool.
- Configure `--max-input-chars` when you need a bound on compaction work.
  Oversized text blocks pass through intact. The upstream has already
  delivered them, so this does not bound transport memory or response size.

## Dependency and release checks

The optional MCP extra requires patched FastMCP 3.x and MCP SDK 1.x versions.
`uv.lock` records the tested dependency set; `uv sync --locked --all-extras`
reproduces it. CI audits this graph on pull requests, main pushes, and a
weekly schedule. A passing audit is a point-in-time result, not a guarantee
that every future advisory is already known.

To refresh and audit it locally:

```bash
uv lock --upgrade
uv sync --locked --all-extras
uv run --no-sync pytest
uv export --locked --all-extras --no-emit-project --output-file /tmp/neterse-requirements.txt
pip-audit --no-deps --disable-pip -r /tmp/neterse-requirements.txt
```

Install `pip-audit` in a separate tooling environment. The repository pins
the benchmark tokenizer independently of dependency upgrades so security
maintenance does not silently change token baselines. Releases require the
tagged commit's CI checks before publishing, and the workflow actions are
pinned to immutable commits.
