"""Parse AoH3 relaxed JSON-like documents into Python values."""

from __future__ import annotations

import ast
import json
import re
from typing import Any


_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_UNQUOTED_KEY = re.compile(r'(?P<prefix>[{,]\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:')
_BARE_IDENT = re.compile(
    r'(?P<prefix>[:\[,]\s*)(?P<ident>[A-Za-z_][A-Za-z0-9_]*)(?P<suffix>\s*[,}\]])'
)


def parse_aoh_json(text: str) -> Any:
    """Parse AoH3 config/data text that is almost-JSON but not strict JSON.

    Handles:
    - unquoted keys
    - trailing commas
    - bare identifiers used as values (mapped to strings)
    - optional outer Age_of_History wrappers
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty AoH JSON document")

    # Fast path for already-valid JSON.
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    normalized = stripped
    # Remove // comments if present.
    normalized = re.sub(r"//.*?$", "", normalized, flags=re.MULTILINE)
    # Quote unquoted object keys.
    normalized = _UNQUOTED_KEY.sub(r'\g<prefix>"\g<key>":', normalized)
    # Quote bare identifier values (but leave true/false/null alone).
    def _quote_ident(match: re.Match[str]) -> str:
        ident = match.group("ident")
        if ident in {"true", "false", "null"}:
            return match.group(0)
        return f'{match.group("prefix")}"{ident}"{match.group("suffix")}'

    normalized = _BARE_IDENT.sub(_quote_ident, normalized)
    # Strip trailing commas before } or ].
    prev = None
    while prev != normalized:
        prev = normalized
        normalized = _TRAILING_COMMA.sub(r"\1", normalized)

    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        # Last-resort: Python literal eval after true/false/null mapping.
        py_text = (
            normalized.replace("true", "True")
            .replace("false", "False")
            .replace("null", "None")
        )
        return ast.literal_eval(py_text)
