"""Process-wide logging configuration.

Every module gets its logger the normal way (`logging.getLogger(__name__)`)
and just logs - this module's only job is to configure *how* those records
are rendered (one dictConfig, applied once from main.py at startup) and to
carry two correlation ids through them:

- `request_id` - one per inbound HTTP request, set by main.py's middleware.
- `run_id` - one per analysis run, set by reanalyze_article() (the point
  where both the pipeline's worker threads and single-article background
  tasks actually execute) so it is present regardless of which caller
  started the work.

Both live in contextvars rather than being threaded through every function
signature. contextvars are not inherited by threads spawned directly (e.g.
concurrent.futures.ThreadPoolExecutor workers), so anything that fans work
out across threads must set the value again inside the worker itself -
reanalyze_article() does exactly that.
"""

from __future__ import annotations

import contextvars
import logging
import logging.config
import os

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")


class _ContextFilter(logging.Filter):
    """Stamps every record with the current request_id/run_id."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.run_id = run_id_var.get()
        return True


def set_request_id(request_id: str | None) -> contextvars.Token:
    return request_id_var.set(request_id or "-")


def reset_request_id(token: contextvars.Token) -> None:
    request_id_var.reset(token)


def set_run_id(run_id: str | None) -> contextvars.Token:
    return run_id_var.set(run_id or "-")


def reset_run_id(token: contextvars.Token) -> None:
    run_id_var.reset(token)


LOG_LEVEL = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper() or "INFO"

DICT_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "context": {"()": _ContextFilter},
    },
    "formatters": {
        "default": {
            "format": (
                "%(asctime)s %(levelname)s [request_id=%(request_id)s run_id=%(run_id)s] "
                "%(name)s: %(message)s"
            ),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "filters": ["context"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    # uvicorn installs its own handlers on these loggers before main.py runs;
    # routing them through the same console handler keeps access/error lines
    # in the same format (and carrying the same request_id) as app logs.
    "loggers": {
        "uvicorn": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "uvicorn.error": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "uvicorn.access": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

_configured = False


def configure_logging() -> None:
    """Idempotent: safe to call once at import time and again at startup."""
    global _configured
    logging.config.dictConfig(DICT_CONFIG)
    _configured = True
