"""Structured logging and performance monitoring for Vanguard."""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Generator


# ---------------------------------------------------------------------------
# Log level configuration
# ---------------------------------------------------------------------------

def _resolve_log_level(raw: str) -> int:
    """Convert a string log level to a logging constant."""
    mapping = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }
    return mapping.get(raw.strip().lower(), logging.INFO)


# ---------------------------------------------------------------------------
# JSON structured handler
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Merge any custom fields attached via `extra`
        for key, value in record.__dict__.items():
            if key.startswith("_vg_"):
                payload[key[4:]] = value
        return json.dumps(payload, default=str)


def get_logger(name: str = "vanguard") -> logging.Logger:
    """Return a logger configured with JSON structured output."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    log_level_raw = os.getenv("LOG_LEVEL", "INFO")
    logger.setLevel(_resolve_log_level(log_level_raw))

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


# ---------------------------------------------------------------------------
# Performance timing helpers
# ---------------------------------------------------------------------------

class PerformanceRecord:
    """Container for a single timed operation."""

    def __init__(
        self,
        component: str,
        operation: str,
        elapsed_ms: float,
        success: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.component = component
        self.operation = operation
        self.elapsed_ms = elapsed_ms
        self.success = success
        self.extra = extra or {}
        self.recorded_at = datetime.now(timezone.utc)

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "operation": self.operation,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "success": self.success,
            "recorded_at": self.recorded_at.isoformat(),
            **self.extra,
        }


@contextmanager
def timed(
    component: str,
    operation: str,
    logger: logging.Logger | None = None,
    extra: dict[str, Any] | None = None,
) -> Generator[list[PerformanceRecord], None, None]:
    """Synchronous context manager that records elapsed time.

    Yields a mutable list so the caller can inspect the record after the block.
    """
    records: list[PerformanceRecord] = []
    _logger = logger or get_logger()
    start = time.perf_counter()
    success = True
    try:
        yield records
    except Exception:
        success = False
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        record = PerformanceRecord(
            component=component,
            operation=operation,
            elapsed_ms=elapsed_ms,
            success=success,
            extra=extra,
        )
        records.append(record)
        _logger.info(
            "perf",
            extra={
                "_vg_component": component,
                "_vg_operation": operation,
                "_vg_elapsed_ms": round(elapsed_ms, 3),
                "_vg_success": success,
            },
        )


@asynccontextmanager
async def async_timed(
    component: str,
    operation: str,
    logger: logging.Logger | None = None,
    extra: dict[str, Any] | None = None,
) -> AsyncGenerator[list[PerformanceRecord], None]:
    """Async context manager that records elapsed time."""
    records: list[PerformanceRecord] = []
    _logger = logger or get_logger()
    start = time.perf_counter()
    success = True
    try:
        yield records
    except Exception:
        success = False
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        record = PerformanceRecord(
            component=component,
            operation=operation,
            elapsed_ms=elapsed_ms,
            success=success,
            extra=extra,
        )
        records.append(record)
        _logger.info(
            "perf",
            extra={
                "_vg_component": component,
                "_vg_operation": operation,
                "_vg_elapsed_ms": round(elapsed_ms, 3),
                "_vg_success": success,
            },
        )


# ---------------------------------------------------------------------------
# Error tracker
# ---------------------------------------------------------------------------

# Mapping from error keyword fragments to auto-recovery suggestions.
_RECOVERY_HINTS: list[tuple[str, str]] = [
    ("connection", "Check DATABASE_URL and ensure PostgreSQL is reachable."),
    ("timeout", "Increase request timeout or check network connectivity."),
    ("api_key", "Verify GEMINI_API_KEY / SENDGRID_API_KEY values in .env."),
    ("401", "Authentication failed – rotate the relevant API key."),
    ("429", "Rate limit hit – reduce polling frequency or wait before retrying."),
    ("dns", "DNS resolution failed – verify network and hostname configuration."),
    ("ssl", "TLS/SSL error – check certificate validity or disable SSL if in dev mode."),
    ("json", "Malformed JSON from LLM – the model may be returning non-JSON output."),
    ("validation", "Schema validation failed – inspect LLM prompt/output alignment."),
    ("pool", "Database connection pool exhausted – increase max_size or investigate leaks."),
]


def recovery_suggestion(error: Exception) -> str:
    """Return an auto-recovery hint based on the error message."""
    msg = str(error).lower()
    for keyword, hint in _RECOVERY_HINTS:
        if keyword in msg:
            return hint
    return "No specific recovery suggestion available; inspect the full traceback."


class ErrorTracker:
    """Lightweight in-process error frequency tracker."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or get_logger()
        # {(component, error_type): count}
        self._counts: dict[tuple[str, str], int] = {}

    def record(
        self,
        component: str,
        error: Exception,
        severity: str = "error",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record an error occurrence and emit a structured log entry."""
        error_type = type(error).__name__
        key = (component, error_type)
        self._counts[key] = self._counts.get(key, 0) + 1
        suggestion = recovery_suggestion(error)

        log_fn = getattr(self._logger, severity, self._logger.error)
        log_fn(
            "error_event",
            extra={
                "_vg_component": component,
                "_vg_error_type": error_type,
                "_vg_error_msg": str(error)[:300],
                "_vg_occurrence": self._counts[key],
                "_vg_suggestion": suggestion,
                **({"_vg_extra": extra} if extra else {}),
            },
        )

    def summary(self) -> list[dict[str, Any]]:
        """Return a list of error frequency records sorted by count descending."""
        return [
            {"component": comp, "error_type": etype, "count": cnt}
            for (comp, etype), cnt in sorted(
                self._counts.items(), key=lambda x: x[1], reverse=True
            )
        ]

    def reset(self) -> None:
        self._counts.clear()


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

logger: logging.Logger = get_logger("vanguard")
error_tracker: ErrorTracker = ErrorTracker(logger)
