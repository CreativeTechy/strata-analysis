"""JSON parsing helpers shared by any stage that asks a model for JSON:
strip code fences, extract the JSON substring from a chatty response, repair
minor formatting mistakes, and validate against a small hand-rolled schema
(no jsonschema dependency - the schemas here are simple enough not to need it).
"""

from __future__ import annotations

import json
import re

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_SMART_QUOTES = {
    "‘": "'", "’": "'",
    "“": '"', "”": '"',
}


def strip_code_fences(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
    return raw.strip()


def _extract_json_substring(raw: str) -> str:
    """If the model wrapped the JSON in prose, pull out the first balanced
    {...} or [...] block instead of failing on the surrounding text."""
    raw = raw.strip()
    if not raw:
        return raw
    if raw[0] in "{[":
        return raw

    for open_char, close_char in (("{", "}"), ("[", "]")):
        start = raw.find(open_char)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == open_char:
                depth += 1
            elif raw[i] == close_char:
                depth -= 1
                if depth == 0:
                    return raw[start:i + 1]
    return raw


def repair_json_text(raw: str) -> str:
    """Best-effort fixups for minor JSON formatting mistakes models commonly
    make. Not a full JSON5 parser - just the handful of issues seen in
    practice: code fences, trailing prose, trailing commas, smart quotes."""
    text = strip_code_fences(raw)
    text = _extract_json_substring(text)
    text = _TRAILING_COMMA.sub(r"\1", text)
    for smart, straight in _SMART_QUOTES.items():
        text = text.replace(smart, straight)
    return text.strip()


class JSONParseError(ValueError):
    """Raised when a model response could not be parsed as JSON even after repair."""


def parse_json_response(raw: str):
    """Parse a model's JSON response, repairing minor formatting issues first.

    Raises JSONParseError (never a bare json.JSONDecodeError) so callers have
    one exception type to catch regardless of which parse attempt failed.
    """
    if raw is None:
        raise JSONParseError("empty response")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass

    repaired = repair_json_text(raw)
    try:
        return json.loads(repaired)
    except (json.JSONDecodeError, TypeError) as exc:
        raise JSONParseError(f"could not parse JSON even after repair: {exc}") from exc


def validate_schema(payload, schema: dict) -> list[str]:
    """Minimal structural validator. Returns a list of human-readable error
    strings; an empty list means `payload` matches `schema`.

    Supported schema shape (only what the analysis stages need):
      {"type": "object", "required": [...], "properties": {key: subschema}}
      {"type": "array", "items": subschema}
      {"type": "string" | "number" | "boolean"}
    A subschema may omit "type" to allow anything.
    """
    errors: list[str] = []
    _validate_node(payload, schema, "$", errors)
    return errors


_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "boolean": bool,
}


def _validate_node(value, schema: dict, path: str, errors: list[str]) -> None:
    expected_type = schema.get("type")
    if expected_type:
        py_type = _TYPE_MAP.get(expected_type)
        if py_type and not isinstance(value, py_type):
            errors.append(f"{path}: expected {expected_type}, got {type(value).__name__}")
            return

    if expected_type == "object" and isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required field missing")
        properties = schema.get("properties") or {}
        for key, subschema in properties.items():
            if key in value:
                _validate_node(value[key], subschema, f"{path}.{key}", errors)
    elif expected_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(value):
                _validate_node(item, item_schema, f"{path}[{i}]", errors)
