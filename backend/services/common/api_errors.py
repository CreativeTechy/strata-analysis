"""Stable, parameterized API error codes.

Existing endpoints raise `HTTPException(status_code=..., detail="Some English
sentence.")` throughout this codebase, and that stays as-is - retrofitting
every call site would be a large, unrelated change and would risk breaking
whatever already parses those plain-string responses (CLAUDE.md: "Maintain
backward compatibility with existing API responses where required"). This
module is additive: new endpoints that need to be localizable on the frontend
(starting with locale validation - see services/i18n/locales.py) raise
`api_error()` instead, which puts a stable machine-readable `code` plus
interpolation `params` in `detail` rather than a hardcoded English message.
main.py's global HTTPException handler already reshapes every raised
exception's `detail` into `{"error": detail}` on the wire - api_error()'s
`{code, params}` dict rides inside that existing envelope unchanged, so the
client sees `{"error": {"code": ..., "params": {...}}}`. The frontend's
error-code catalog (dashboard/src/lib/apiError.js) translates `code` with
`params` interpolated in; a client that doesn't recognize the code can still
fall back to showing it plus the raw params.
"""

from __future__ import annotations

from fastapi import HTTPException


def api_error(status_code: int, code: str, params: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "params": params or {}})
