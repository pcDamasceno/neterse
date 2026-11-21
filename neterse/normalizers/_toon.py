"""TOON text embedded in a JSON string — a pre-formatted table, unread.

Some MCP servers TOON-encode their rows themselves and return the result
as one string field of a JSON envelope: infrahub-mcp's ``get_nodes``
answers ``{"nodes": "[5]:\\n  - index: ...", "count": 5, ...}``. To neterse
that is one row with one enormous string cell; the records inside it, and
the redundancy between them (twenty empty relationship lists repeated on
every node), stay invisible. This normalizer reads the string back into
rows so the parsed tier can fold and tabulate them like any other rows.

It reads the two ROOT-ARRAY forms the ``toonify`` encoder (the Python
``toon`` package, which infrahub-mcp uses) writes for a list of flat
records:

* the list form — ``[N]:`` then one ``- key: value`` item per record,
  its other fields indented beneath it;
* the tabular form — ``[N]{f1,f2}:`` then one comma-delimited row per
  record.

Values are kept as the text the server wrote, with only three literals
and quoted strings decoded: ``null`` (so null stays apart from an empty
string, decision 46), ``true``/``false``, and ``"..."`` (JSON escapes, so
``""`` is the empty string and ``\\n`` a newline). Everything else —
numbers, the inline ``[a,b]`` lists toonify writes, bare words — stays
the exact text that arrived: ``toonify`` writes the string ``"3"`` and
the number ``3`` alike, so reading a type into it would invent one.

Strict, because a string that merely LOOKS like a table must stay a
string: the header must match, every line must parse, indentation must be
exact, the item count must equal ``N``, and any nested object or array
(a field with no inline value) declines the whole document. An empty
array is not rows and declines too. Fail-open: a ``None`` here leaves the
string untouched.

Stdlib only — like everything else here.
"""
from __future__ import annotations

import json
import re
from importlib import import_module
from typing import Any, List, Optional

_LIST_HEADER = re.compile(r"^\[(\d+)\]:$")
_TABLE_HEADER = re.compile(r"^\[(\d+)\]\{(.+)\}:$")
_ITEM_START = "  - "
_ITEM_FIELD = "    "
_TABLE_ROW = "  "
_LITERALS = {"null": None, "true": True, "false": False}


def _scalar(token: str) -> Any:
    """One value token: a literal, a quoted string, or the verbatim text."""
    if token in _LITERALS:
        return _LITERALS[token]
    if token.startswith('"'):
        decoded = json.loads(token)             # raises unless one whole string
        if not isinstance(decoded, str):
            raise ValueError("not a string")
        return decoded
    return token


def _field(line: str) -> tuple:
    """``key: value`` → (key, value). A field with no inline value is a
    nested object or array, which this reader does not take."""
    key, sep, token = line.partition(": ")
    if not sep or not key or not token or key != key.strip() or token != token.strip():
        raise ValueError("not a flat field")
    return key, _scalar(token)


def _split_row(line: str) -> List[str]:
    """Comma-split a tabular row, honouring double-quoted cells."""
    tokens: List[str] = []
    i, n = 0, len(line)
    while True:
        if i < n and line[i] == '"':
            j = i + 1
            while j < n and line[j] != '"':
                j += 2 if line[j] == "\\" else 1
            if j >= n:
                raise ValueError("unterminated string")
            tokens.append(line[i:j + 1])
            i = j + 1
            if i < n and line[i] != ",":
                raise ValueError("text after a quoted cell")
        else:
            j = line.find(",", i)
            j = n if j < 0 else j
            tokens.append(line[i:j])
            i = j
        if i >= n:
            return tokens
        i += 1                                  # the comma


def _list_rows(lines: List[str]) -> List[dict]:
    rows: List[dict] = []
    for line in lines:
        if line.startswith(_ITEM_START):
            rows.append({})
            body = line[len(_ITEM_START):]
        elif line.startswith(_ITEM_FIELD) and rows:
            body = line[len(_ITEM_FIELD):]
        else:
            raise ValueError("unexpected line")
        if body.startswith(" "):
            raise ValueError("deeper indentation")
        key, value = _field(body)
        if key in rows[-1]:
            raise ValueError("duplicate key")
        rows[-1][key] = value
    return rows


def _table_rows(fields: List[str], lines: List[str]) -> List[dict]:
    rows: List[dict] = []
    for line in lines:
        if not line.startswith(_TABLE_ROW) or line.startswith(_TABLE_ROW + " "):
            raise ValueError("unexpected indentation")
        tokens = _split_row(line[len(_TABLE_ROW):])
        if len(tokens) != len(fields):
            raise ValueError("row width")
        rows.append({f: _scalar(t) for f, t in zip(fields, tokens)})
    return rows


def toon_text(value: Any) -> Optional[List[dict]]:
    """TOON root-array text (toonify's list or tabular form) → rows.

    Declines (``None``) for anything that is not a string holding exactly
    one such document with at least one record.
    """
    if not isinstance(value, str) or not value.startswith("["):
        return None
    lines = value.rstrip("\n").split("\n")
    header, body = lines[0], lines[1:]
    try:
        match = _LIST_HEADER.match(header)
        if match:
            rows = _list_rows(body)
        else:
            match = _TABLE_HEADER.match(header)
            if not match:
                return None
            fields = match.group(2).split(",")
            if len(set(fields)) != len(fields) or not all(fields):
                return None
            rows = _table_rows(fields, body)
    except ValueError:
        return None
    if not rows or len(rows) != int(match.group(1)):
        return None
    return rows


# A line that opens a TOON array: ``key[N]:`` or ``key[N]{fields}:``. A
# document without one is plain ``key: value`` lines — nothing an encoder
# here could say in fewer bytes, and easy to confuse with ordinary text.
_ARRAY_OPENER = re.compile(r"^\s*[^\s:\[\]]*\[\d+\](?:\{[^}]*\})?:", re.MULTILINE)


def toon_document(text: Any) -> Optional[dict]:
    """A bare TOON OBJECT document, read back into the object it encodes.

    Some MCP servers answer with a whole TOON document as the tool result
    instead of JSON: infrahub-mcp's ``get_schema`` returns ``kind: ...`` /
    ``attributes[8]{name,kind,optional}:`` / ``relationships[9]:`` with a
    nested ``peer_schema`` object under every relationship. To a consumer
    that is one opaque string, so the constant columns inside its tables
    and the nesting stay unreadable to the parsed tier (decision 52).

    Unlike :func:`toon_text` this does not carry its own reader: nested
    objects, list items holding objects and tables, quoting and key
    folding are the whole TOON grammar, and the spec authors' decoder
    (the ``toon`` extra, ``toon_format``) already implements it. Without
    the extra this declines every string.

    The reading is proven before it is returned: the decoded object is
    encoded again and must reproduce *text* byte for byte. A string that
    merely looks like TOON, a document written by an encoder with other
    conventions, a duplicate key the decoder merged, a number it
    normalized — any of these fails the comparison and the string stays a
    string. Fail-open: ``None`` leaves the caller's text untouched.
    """
    if not isinstance(text, str) or "\n" not in text or not _ARRAY_OPENER.search(text):
        return None
    try:
        codec = import_module("toon_format")
        document = codec.decode(text)
        if not isinstance(document, dict) or not document:
            return None
        if not all(isinstance(key, str) for key in document):
            return None
        if codec.encode(document) != text.rstrip("\n"):
            return None
    except Exception:
        return None
    return document
