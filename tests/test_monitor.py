"""Tests for the structured logging and performance monitoring module."""

from __future__ import annotations

import asyncio
import logging

import pytest

from vanguard.monitor import (
    ErrorTracker,
    PerformanceRecord,
    async_timed,
    get_logger,
    recovery_suggestion,
    timed,
)


# ---------------------------------------------------------------------------
# Logger tests
# ---------------------------------------------------------------------------

def test_get_logger_returns_logger() -> None:
    logger = get_logger("test_vanguard")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test_vanguard"


def test_get_logger_idempotent() -> None:
    """Calling get_logger twice with the same name returns the same instance."""
    l1 = get_logger("test_idempotent")
    l2 = get_logger("test_idempotent")
    assert l1 is l2


def test_get_logger_has_json_handler() -> None:
    logger = get_logger("test_handler_check")
    assert len(logger.handlers) >= 1


# ---------------------------------------------------------------------------
# PerformanceRecord tests
# ---------------------------------------------------------------------------

def test_performance_record_as_dict() -> None:
    rec = PerformanceRecord(
        component="ingestion",
        operation="news_fetch",
        elapsed_ms=123.456,
        success=True,
        extra={"route": "Red Sea -> India"},
    )
    d = rec.as_dict()
    assert d["component"] == "ingestion"
    assert d["operation"] == "news_fetch"
    assert d["elapsed_ms"] == 123.456
    assert d["success"] is True
    assert d["route"] == "Red Sea -> India"
    assert "recorded_at" in d


def test_performance_record_defaults() -> None:
    rec = PerformanceRecord(component="llm", operation="gemini_inference", elapsed_ms=500.0)
    assert rec.success is True
    assert rec.extra == {}


# ---------------------------------------------------------------------------
# timed context manager tests
# ---------------------------------------------------------------------------

def test_timed_records_elapsed() -> None:
    with timed("test_component", "test_op") as records:
        pass  # minimal work

    assert len(records) == 1
    assert records[0].component == "test_component"
    assert records[0].operation == "test_op"
    assert records[0].elapsed_ms >= 0
    assert records[0].success is True


def test_timed_marks_failure_on_exception() -> None:
    records: list[PerformanceRecord] = []
    with pytest.raises(ValueError):
        with timed("test_component", "failing_op") as records:
            raise ValueError("boom")

    assert len(records) == 1
    assert records[0].success is False


def test_async_timed_records_elapsed() -> None:
    async def _run() -> list[PerformanceRecord]:
        async with async_timed("test_component", "async_op") as records:
            await asyncio.sleep(0)
        return records

    records = asyncio.run(_run())
    assert len(records) == 1
    assert records[0].component == "test_component"
    assert records[0].elapsed_ms >= 0
    assert records[0].success is True


def test_async_timed_marks_failure_on_exception() -> None:
    async def _run() -> list[PerformanceRecord]:
        records: list[PerformanceRecord] = []
        try:
            async with async_timed("test_component", "failing_async_op") as records:
                raise RuntimeError("async boom")
        except RuntimeError:
            pass
        return records

    records = asyncio.run(_run())
    assert len(records) == 1
    assert records[0].success is False


# ---------------------------------------------------------------------------
# recovery_suggestion tests
# ---------------------------------------------------------------------------

def test_recovery_suggestion_timeout() -> None:
    exc = ConnectionError("request timeout exceeded")
    hint = recovery_suggestion(exc)
    assert "timeout" in hint.lower()


def test_recovery_suggestion_rate_limit() -> None:
    exc = Exception("429 Too Many Requests")
    hint = recovery_suggestion(exc)
    assert "rate" in hint.lower()


def test_recovery_suggestion_unknown() -> None:
    exc = Exception("something completely unknown")
    hint = recovery_suggestion(exc)
    assert hint  # must return a non-empty string


# ---------------------------------------------------------------------------
# ErrorTracker tests
# ---------------------------------------------------------------------------

def test_error_tracker_records_and_summarises() -> None:
    tracker = ErrorTracker()
    tracker.record("ingestion", ValueError("bad data"))
    tracker.record("ingestion", ValueError("bad data again"))
    tracker.record("database", RuntimeError("conn failed"))

    summary = tracker.summary()
    assert len(summary) == 2

    # highest count entry first
    assert summary[0]["count"] == 2
    assert summary[0]["component"] == "ingestion"
    assert summary[0]["error_type"] == "ValueError"

    assert summary[1]["count"] == 1
    assert summary[1]["component"] == "database"


def test_error_tracker_reset() -> None:
    tracker = ErrorTracker()
    tracker.record("x", Exception("err"))
    tracker.reset()
    assert tracker.summary() == []
