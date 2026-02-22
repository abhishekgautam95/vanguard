"""Deterministic scoring logic."""

from __future__ import annotations

from .schemas import BaselineScore, RiskEvent


def compute_baseline_components(events: list[RiskEvent]) -> BaselineScore:
    """Aggregate events into normalized scoring dimensions."""
    if not events:
        return BaselineScore(
            geopolitical=0.0,
            port_congestion=0.0,
            weather=0.0,
            historical_reliability=80.0,
        )

    geo_values = [e.severity * e.confidence for e in events if e.event_type == "Geopolitical"]
    port_values = [e.severity * e.confidence for e in events if e.event_type == "PortCongestion"]
    weather_values = [e.severity * e.confidence for e in events if e.event_type == "Weather"]

    geopolitical = min(100.0, sum(geo_values) / max(len(geo_values), 1))
    port_congestion = min(100.0, sum(port_values) / max(len(port_values), 1))
    weather = min(100.0, sum(weather_values) / max(len(weather_values), 1))

    disruption_count = len([e for e in events if e.severity >= 70])
    historical_reliability = max(20.0, 90.0 - disruption_count * 5.0)

    return BaselineScore(
        geopolitical=geopolitical,
        port_congestion=port_congestion,
        weather=weather,
        historical_reliability=historical_reliability,
    )


def compute_baseline_risk(components: BaselineScore) -> float:
    """Weighted baseline formula from product design."""
    return round(
        0.35 * components.geopolitical
        + 0.30 * components.port_congestion
        + 0.20 * components.weather
        + 0.15 * (100.0 - components.historical_reliability),
        2,
    )


def combine_baseline_and_llm(
    baseline_risk: float,
    llm_risk: int,
    llm_confidence: float,
) -> float:
    """Blend deterministic and LLM risk; cap at [0, 100]."""
    llm_weight = 0.2 + (0.4 * llm_confidence)
    baseline_weight = 1.0 - llm_weight
    score = baseline_weight * baseline_risk + llm_weight * llm_risk
    return round(max(0.0, min(100.0, score)), 2)
