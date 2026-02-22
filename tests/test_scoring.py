"""Scoring unit tests."""

from vanguard.schemas import BaselineScore
from vanguard.scoring import combine_baseline_and_llm, compute_baseline_risk


def test_compute_baseline_risk() -> None:
    components = BaselineScore(
        geopolitical=80.0,
        port_congestion=60.0,
        weather=40.0,
        historical_reliability=70.0,
    )
    score = compute_baseline_risk(components)
    assert score == 58.5


def test_combine_baseline_and_llm() -> None:
    score = combine_baseline_and_llm(baseline_risk=60.0, llm_risk=80, llm_confidence=0.75)
    assert 60.0 < score <= 80.0
