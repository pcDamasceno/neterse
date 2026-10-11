"""Infrahub GraphQL payload shapes.

Infrahub's GraphQL API returns every node list as a Relay connection —
``{"count": N, "edges": [{"node": {...}}, ...]}`` — and wraps every field
of a node in its own envelope:

* an attribute is ``{"value": X}`` (``name { value }`` in the query);
* a cardinality-one relationship is ``{"node": {...}}``, or
  ``{"node": null}`` when no peer is set (``platform { node { ... } }``);
* a cardinality-many relationship is a nested connection,
  ``{"count": N, "edges": [{"node": {...}}, ...]}``.

For tabular purposes those wrappers are pure envelope: the field names
inside them (``value``, ``node``, ``edges``) are the query's own
projection, echoed back, and the agent that wrote the query already
knows them. This normalizer unwraps the edges list into one row per node
and each field into its value; a nested connection is handed back as its
edges list, which this normalizer claims again one level down, so
``parsed:sections`` renders it as an indented sub-table under its row
(decision 34's recursion).

Scoped deliberately: it claims ONLY a list whose every item is exactly
``{"node": {str-keyed dict}}``. An edge carrying anything else (Relay
``cursor``, Infrahub relationship ``properties``) is left untouched —
that is data, and dropping it would lie. Inside a node, a field is
unwrapped only when its envelope is exact; anything richer (an attribute
queried with ``value`` AND ``is_protected``, a nested connection whose
``count`` differs from its edges because it was paginated) stays as it
came. Unwrapping removes envelope keys and never a value, so the rows are
lossless.

Stdlib only, fail-open — like everything else here.
"""
from __future__ import annotations

from typing import Any, List, Optional


def _is_edges(value: Any) -> bool:
    """True for a non-empty list of exact ``{"node": {...}}`` edges."""
    return (
        isinstance(value, (list, tuple))
        and bool(value)
        and all(
            isinstance(edge, dict)
            and set(edge) == {"node"}
            and isinstance(edge["node"], dict)
            and all(isinstance(key, str) for key in edge["node"])
            for edge in value
        )
    )


def _field(value: Any) -> Any:
    """One node field with its Infrahub envelope removed, or *value*
    itself when the envelope is not exactly one this module knows."""
    if not isinstance(value, dict):
        return value
    keys = set(value)
    if keys == {"value"}:                       # attribute
        return value["value"]
    if keys == {"node"}:                        # cardinality-one peer
        peer = value["node"]
        if peer is None:
            return None
        if not isinstance(peer, dict) or not all(isinstance(k, str) for k in peer):
            return value
        peer = _node(peer)
        if len(peer) == 1:                      # one requested field: its value
            return next(iter(peer.values()))
        return peer
    if "edges" in keys and keys <= {"edges", "count"}:   # cardinality-many
        edges = value["edges"]
        if isinstance(edges, list) and (
            "count" not in value or value["count"] == len(edges)
        ):
            # The edges list itself: this normalizer claims it again when
            # the sections encoder reaches the cell. An empty list stays
            # an empty list. A count equal to the edge count is implied
            # by the sub-table's own rows; any other count is kept whole.
            return edges
    return value


def _node(node: dict) -> dict:
    return {key: _field(value) for key, value in node.items()}


def graphql_edges(value: Any) -> Optional[List[dict]]:
    """Infrahub GraphQL ``edges`` list → one row per node, fields unwrapped.

    Declines (``None``) unless *value* is a non-empty list/tuple whose
    every item is exactly ``{"node": {str-keyed dict}}``.
    """
    if not _is_edges(value):
        return None
    return [_node(edge["node"]) for edge in value]
