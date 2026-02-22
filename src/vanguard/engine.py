"""Main orchestration engine."""

from __future__ import annotations

from .actions import build_cost_benefit_analysis, should_trigger_reroute
from .reasoning import VanguardReasoner
from .schemas import DecisionResult, LLMRiskResponse
from .scoring import combine_baseline_and_llm, compute_baseline_components, compute_baseline_risk
from .storage import Storage


class VanguardEngine:
    """Coordinates ingestion, scoring, reasoning, and caching."""

    def __init__(
        self,
        reasoner: VanguardReasoner,
        storage: Storage,
        llm_trigger_threshold: float = 45.0,
    ):
        self.reasoner = reasoner
        self.storage = storage
        self.llm_trigger_threshold = llm_trigger_threshold

    async def evaluate_route(self, route: str, events: list) -> DecisionResult:
        components = compute_baseline_components(events)
        baseline_risk = compute_baseline_risk(components)

        if baseline_risk < self.llm_trigger_threshold:
            llm_result = LLMRiskResponse(
                risk_score=round(baseline_risk),
                predicted_delay_days=max(0.5, round(baseline_risk / 20, 2)),
                alternatives=["Continue normal route monitoring", "Increase supplier lead-time buffer"],
                reasoning="Baseline risk below LLM trigger threshold; deterministic policy applied.",
                confidence_score=0.60,
            )
        else:
            prompt_payload = self.reasoner.build_cache_payload(route, events, baseline_risk)
            key = self.storage.cache_key(route, prompt_payload)
            cached = await self.storage.get_cached_reasoning(key)
            if cached:
                llm_result = cached
            else:
                llm_result, _ = await self.reasoner.evaluate(route, events, baseline_risk)
                await self.storage.set_cached_reasoning(key, llm_result)

        final_risk = combine_baseline_and_llm(
            baseline_risk=baseline_risk,
            llm_risk=llm_result.risk_score,
            llm_confidence=llm_result.confidence_score,
        )

        escalation = llm_result.confidence_score < 0.55
        reroute = should_trigger_reroute(final_risk, llm_result.predicted_delay_days)
        cba = build_cost_benefit_analysis() if final_risk > 75 else None
        recommended_action = "monitor" if not reroute else (cba or {}).get("recommendation", "reroute_now")

        return DecisionResult(
            route=route,
            baseline_risk=baseline_risk,
            llm_risk=llm_result.risk_score,
            final_risk=final_risk,
            predicted_delay_days=llm_result.predicted_delay_days,
            alternatives=llm_result.alternatives,
            reason=llm_result.reasoning,
            confidence=llm_result.confidence_score,
            requires_escalation=escalation or reroute,
            recommended_action=str(recommended_action),
            cost_benefit=cba,
        )
