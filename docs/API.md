# API, formats, and troubleshooting

## Choose an entry point

| Entry point | Input | Return and fallback |
| --- | --- | --- |
| `compact(source, command=None, *, platform=None, profile="default", **run_kwargs)` | Raw text, parsed data, a response object, or a synchronous connection | Smallest candidate's text. Raw text passes through when nothing shrinks; structured data falls back to compact JSON. Connection kwargs reach `send_command`. |
| `render(raw, *, command, platform=None, parsed=None, profile="default")` | Raw CLI text, optionally with pre-parsed rows | A list of shrinking `Candidate` objects; an empty list means use raw text. This function does not run TextFSM itself. |
| `render_parsed(data, *, profile="default")` | Structured data | Candidates smaller than compact JSON. Strings yield no candidates. |
| `optimize_parsed(data, *, profile="default")` | Structured data | The smallest parsed candidate or compact JSON; strings pass through. |
| `optimize(command, raw)` | Raw CLI text | Historical convenience wrapper; smallest raw-tier candidate or raw text. |

`compact` runs TextFSM when command and platform are available and the
`textfsm` extra is installed. Response adapters preserve dictionaries,
lists, empty collections, and scalars in `.result`; `None` means no result.
The connection API is synchronous. Await an async runner yourself and pass
the resulting response or data to `compact`.

`Candidate` exposes `text`, `source`, `method`, `profile`, `dropped_fields`,
`est_chars`, and `est_tokens()`. Selection uses character length, not a
tokenizer. `est_tokens()` is a chars/4 estimate; actual token savings depend
on the model's tokenizer. Use `scripts/neterse_report.py` for real counts.
Shorter text can use more tokens; see the measured examples in
[live validation](VALIDATION.md).

## Preservation and lossiness

Raw CLI compressors may omit fields even under the default profile.
`dropped_fields == ()` declares no omitted fields; a nonempty tuple names
omissions; `None` means undeclared. `compact()` returns text and does not
include this metadata. To require a declared-lossless raw candidate:

```python
from neterse import render

def compact_without_drops(raw, command, platform=None):
    candidates = render(raw, command=command, platform=platform)
    eligible = [candidate for candidate in candidates if candidate.dropped_fields == ()]
    best = min(eligible, key=lambda candidate: len(candidate.text), default=None)
    return best.text if best else raw
```

`profile="updown"` requests a field projection, with an inline omission
marker. `full` is an alias of `default`; it does not restore fields a raw
compressor inherently omits. Unknown profiles use the default rendering.

Parsed encodings preserve canonical row values. Vendor normalizers can
unwrap envelopes and relationships, so compact text is not a replacement
for the original JSON object in a machine API. Non-JSON Python objects
follow the JSON baseline's `default=str` convention. Compressor/encoder
failures fall back; connection failures still propagate because no device
result exists to return. Invalid connection arguments raise `TypeError`.

## Typed CSV cells

Starting with decision 50, `parsed:csv` distinguishes absent keys, empty
strings, null, booleans, numbers, JSON-looking strings, and nested JSON.
Its outer syntax is standard CSV. Read it with `csv.reader`, not `split(',')`.
After CSV decoding each data cell:

1. An empty cell means the key is absent.
2. A valid JSON literal is decoded with `json.loads`.
3. Any other cell is a string, preserved verbatim.

Strings resembling JSON literals are JSON-quoted before CSV escaping.
For example, boolean `true` is `true` on the wire; string `"true"` is
`"""true"""`; an empty string is `""""""`; null is `null`. Nested objects
and arrays use compact JSON inside their CSV cell. Headers are ordinary
CSV strings. Raw CLI tables are string-valued and do not use this typed-cell
convention.

This intentionally changes previously ambiguous CSV output. Fold markers
and tables inside `parsed:sections` use the same value encoding, with their
own surrounding layout. Projected CSV also carries an omission marker after
the table. For a standardized structured interchange format, select a
`parsed:toon` or `parsed:gcf` candidate and use its matching decoder.

## CLI

```bash
neterse compact capture.txt --command 'show interface status' --platform cisco_nxos
neterse compact response.json --input-format json --explain
neterse compact capture.txt --command 'show ip route' --lossless-only
neterse audit captures.jsonl --json --fail-under 20
neterse coverage
```

`compact` reads UTF-8 from a file or stdin (`-`). Raw pass-through preserves
line endings and the final newline. JSON input is parsed and may fall back
to compact JSON instead of preserving its original whitespace. `--explain`
prints JSON metadata to stderr, keeping stdout usable in a pipeline.

`audit --json` reports per-sample source, omissions, character counts, and
aggregate savings without including capture contents. A failing
`--fail-under` exits 1 and writes its message to stderr. Empty input cannot
satisfy a positive savings threshold. Invalid input reports its file and
line rather than a Python traceback. `--show` applies to text reports.

## MCP troubleshooting

| Symptom | Check |
| --- | --- |
| Proxy executable or FastMCP missing | Install `pip install 'neterse[mcp,gcf]'` in the environment used by the client. |
| Upstream flags are swallowed or rejected | Use `neterse-mcp --quiet -- docker run -i ...`; proxy options precede the command. URL options can also follow the URL. |
| Authentication fails | Use `--header-env Authorization=MCP_AUTHORIZATION`; the variable must contain the whole value, including `Bearer `. |
| No compression | Non-JSON text, scalars, errors, and already-small results pass through. Try the `gcf` extra for nested JSON and inspect `--explain` on a saved JSON payload. |
| A machine consumer needs structured output or output schemas | Use `--keep-structured`; by default duplicate structured content is removed or rewritten and output schemas are stripped. |
| Very large responses consume too much CPU/memory | Set `--max-input-chars N` to pass oversized blocks through unchanged. This is not truncation. |

Savings are logged on stderr; `--quiet` suppresses them. The proxy inherits
and forwards the host environment to stdio upstreams. Trust that executable
with those credentials. No connection or request to a live device is needed
to run the fixture and in-memory integration tests.

Large MCP text blocks run in a worker thread. Custom normalizers registered
in a middleware process must therefore be safe to call from multiple threads.
