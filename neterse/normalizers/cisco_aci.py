"""Cisco ACI (APIC REST) payload shapes.

The APIC object model returns every managed object wrapped in its class
name — ``{class: {"attributes": {...}}}`` — collected under an ``imdata``
list. For tabular purposes that wrapper is pure envelope, but the class
name is data, so this normalizer unwraps the strict attributes-only form
into rows and keeps the class in a leading column.

Scoped deliberately: it claims ONLY a list whose every item is exactly
``{one class: {"attributes": {str-keyed dict}}}``. An object carrying
``children`` or other keys (a full MO subtree) is left untouched — that is
genuinely nested data, and forcing it into a flat row would lie. A future
ACI API version with a different envelope is a NEW normalizer (its own
function here, or a :func:`~neterse.normalizers.register_normalizer`
override out of tree), never an edit to this one.

Stdlib only, fail-open — like everything else here.
"""
from __future__ import annotations

from typing import Any, List, Optional


def class_attributes(value: Any) -> Optional[List[dict]]:
    """ACI ``imdata`` objects → rows, the class name kept as ``_class``.

    Declines (``None``) unless *value* is a non-empty list/tuple whose every
    item is the strict ``{class: {"attributes": {...}}}`` shape with
    string-keyed attributes. The ``_class`` column name gains leading
    underscores as needed so it never shadows an attribute.
    """
    if not isinstance(value, (list, tuple)) or not value:
        return None
    unwrapped = []
    attribute_keys = set()
    for item in value:
        if not isinstance(item, dict) or len(item) != 1:
            return None
        class_name, body = next(iter(item.items()))
        if (
            not isinstance(class_name, str)
            or not isinstance(body, dict)
            or set(body) != {"attributes"}
            or not isinstance(body["attributes"], dict)
            or not all(isinstance(key, str) for key in body["attributes"])
        ):
            return None
        unwrapped.append((class_name, body["attributes"]))
        attribute_keys.update(body["attributes"])
    class_col = "_class"
    while class_col in attribute_keys:
        class_col = "_" + class_col
    return [{class_col: name, **attrs} for name, attrs in unwrapped]
