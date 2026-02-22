"""Notification service behavior tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from vanguard.notifications import AlertService
from vanguard.schemas import DecisionResult


@dataclass
class FakeStorage:
    """Minimal async storage stub for notification tests."""

    recent_alert: bool

    def __post_init__(self) -> None:
        self.logged: list[dict] = []
        self.has_recent_calls = 0

    async def has_recent_alert(self, alert_key: str, recipient: str, lookback_hours: int = 6) -> bool:
        self.has_recent_calls += 1
        return self.recent_alert

    async def log_alert_dispatch(self, **kwargs) -> None:
        self.logged.append(kwargs)

    async def get_retry_candidates(self, limit: int = 50, lookback_hours: int = 24):
        return []


def _decision(final_risk: float) -> DecisionResult:
    return DecisionResult(
        route="Red Sea -> India",
        baseline_risk=70,
        llm_risk=80,
        final_risk=final_risk,
        predicted_delay_days=7,
        alternatives=["A", "B"],
        reason="test",
        confidence=0.8,
        requires_escalation=True,
        recommended_action="reroute_now",
    )


def test_dedup_blocks_non_critical_alert() -> None:
    storage = FakeStorage(recent_alert=True)
    service = AlertService(storage=storage, api_key="", from_email="", dedup_hours=6, max_retries=1)

    asyncio.run(service.dispatch(["ops@example.com"], _decision(75), dry_run=True))

    assert storage.has_recent_calls == 1
    assert len(storage.logged) == 0


def test_critical_alert_bypasses_dedup() -> None:
    storage = FakeStorage(recent_alert=True)
    service = AlertService(storage=storage, api_key="", from_email="", dedup_hours=6, max_retries=1)

    asyncio.run(service.dispatch(["ops@example.com"], _decision(95), dry_run=True))

    assert storage.has_recent_calls == 0
    assert len(storage.logged) == 1
    assert storage.logged[0]["status"] == "dry_run"
