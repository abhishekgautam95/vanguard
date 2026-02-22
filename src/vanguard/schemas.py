"""Data schemas for Vanguard."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


EventType = Literal["Geopolitical", "Weather", "PortCongestion", "Other"]


class RiskEvent(BaseModel):
    """Normalized external event used by risk engine."""

    event_type: EventType
    geo_location: str
    severity: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    description: str
    source: str
    route: str
    event_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BaselineScore(BaseModel):
    """Deterministic score components."""

    geopolitical: float = Field(ge=0.0, le=100.0)
    port_congestion: float = Field(ge=0.0, le=100.0)
    weather: float = Field(ge=0.0, le=100.0)
    historical_reliability: float = Field(ge=0.0, le=100.0)


class LLMRiskResponse(BaseModel):
    """Strictly validated LLM response payload."""

    risk_score: int = Field(ge=0, le=100)
    predicted_delay_days: float = Field(ge=0.0)
    alternatives: list[str]
    reasoning: str
    confidence_score: float = Field(ge=0.0, le=1.0)


class DecisionResult(BaseModel):
    """Final decision output consumed by action pipeline."""

    route: str
    baseline_risk: float = Field(ge=0.0, le=100.0)
    llm_risk: int = Field(ge=0, le=100)
    final_risk: float = Field(ge=0.0, le=100.0)
    predicted_delay_days: float = Field(ge=0.0)
    alternatives: list[str]
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    requires_escalation: bool
    recommended_action: str | None = None
    cost_benefit: dict[str, object] | None = None
