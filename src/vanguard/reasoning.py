"""LLM reasoning with provider support and strict output validation."""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import ValidationError

from .schemas import LLMRiskResponse, RiskEvent

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - optional runtime provider
    genai = None

try:
    from ollama import AsyncClient
except ImportError:  # pragma: no cover - optional runtime provider
    AsyncClient = None


class ReasoningError(RuntimeError):
    """Raised when model response is invalid."""


class VanguardReasoner:
    """LLM wrapper around configurable providers."""

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-1.5-pro",
        llm_provider: str | None = None,
        ollama_model: str | None = None,
        ollama_base_url: str | None = None,
    ):
        self.llm_provider = (llm_provider or os.getenv("LLM_PROVIDER", "gemini")).strip().lower()
        self.ollama_model = (ollama_model or os.getenv("OLLAMA_MODEL", "llama3")).strip() or "llama3"
        self.ollama_base_url = (
            ollama_base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ).strip() or "http://localhost:11434"

        if self.llm_provider not in {"gemini", "ollama"}:
            raise ValueError("LLM_PROVIDER must be either 'gemini' or 'ollama'.")

        self.model = None
        self.ollama_client = None

        if self.llm_provider == "gemini":
            if not api_key:
                raise ValueError("Missing GEMINI_API_KEY for Gemini provider.")
            if genai is None:
                raise ValueError("google-generativeai package is not installed.")
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(model_name)
            return

        if AsyncClient is None:
            raise ValueError("ollama package is not installed. Install it via requirements.")
        self.ollama_client = AsyncClient(host=self.ollama_base_url)

    @staticmethod
    def _build_prompt(route: str, events: list[RiskEvent], baseline_risk: float) -> str:
        bullet_list = "\n".join(
            f"- [{e.event_type}] {e.geo_location} | severity={e.severity} "
            f"confidence={e.confidence:.2f} | {e.description}"
            for e in events
        )

        return f"""
Role: Senior Supply Chain Risk Analyst
Domain: Indian textile exports
Route: {route}
BaselineRisk: {baseline_risk}

Recent Events:
{bullet_list}

Task:
1) Assess route disruption risk (0-100)
2) Predict delay in days
3) Suggest 2 reroute/logistics alternatives
4) Give concise reasoning grounded in events only
5) Provide confidence score between 0 and 1

Output constraints:
- Return JSON only
- No markdown, no extra keys

Schema:
{{
  "risk_score": int,
  "predicted_delay_days": float,
  "alternatives": ["string", "string"],
  "reasoning": "string",
  "confidence_score": float
}}
""".strip()

    @staticmethod
    def build_cache_payload(
        route: str,
        events: list[RiskEvent],
        baseline_risk: float,
    ) -> dict[str, Any]:
        """Build deterministic cache payload for semantic reuse."""
        return {
            "route": route,
            "event_count": len(events),
            "baseline_risk": baseline_risk,
            "event_fingerprints": [f"{e.event_type}:{e.geo_location}:{e.severity}" for e in events],
        }

    async def evaluate(
        self,
        route: str,
        events: list[RiskEvent],
        baseline_risk: float,
    ) -> tuple[LLMRiskResponse, dict[str, Any]]:
        """Return validated LLM output and prompt payload for caching."""
        prompt = self._build_prompt(route=route, events=events, baseline_risk=baseline_risk)
        payload = self.build_cache_payload(route=route, events=events, baseline_risk=baseline_risk)
        raw_text = ""

        if self.llm_provider == "gemini":
            raw = self.model.generate_content(prompt)
            raw_text = getattr(raw, "text", "") or ""
        else:
            response = await self.ollama_client.chat(
                model=self.ollama_model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
            )
            raw_text = str((response.get("message") or {}).get("content") or "")

        try:
            parsed = json.loads(raw_text)
            validated = LLMRiskResponse.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError, AttributeError) as exc:
            raise ReasoningError(f"Invalid model response: {exc}") from exc

        return validated, payload
