"""Configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .security import redact_env_snapshot


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    gemini_api_key: str
    database_url: str
    openweather_api_key: str
    enable_embeddings: bool
    llm_trigger_threshold: float
    llm_provider: str
    ollama_model: str
    ollama_base_url: str
    sendgrid_api_key: str
    sender_email: str
    alert_recipients: list[str]
    alert_dedup_hours: int
    alert_max_retries: int
    monitor_routes: list[str]
    monitor_interval_seconds: int
    retry_lookback_hours: int
    retry_batch_size: int
    dashboard_password: str

    def redacted_snapshot(self) -> dict[str, object]:
        """Return safe-to-log config snapshot with sensitive values masked."""
        return redact_env_snapshot(
            {
                "GEMINI_API_KEY": self.gemini_api_key,
                "DATABASE_URL": self.database_url,
                "OPENWEATHER_API_KEY": self.openweather_api_key,
                "ENABLE_EMBEDDINGS": self.enable_embeddings,
                "LLM_TRIGGER_THRESHOLD": self.llm_trigger_threshold,
                "LLM_PROVIDER": self.llm_provider,
                "OLLAMA_MODEL": self.ollama_model,
                "OLLAMA_BASE_URL": self.ollama_base_url,
                "SENDGRID_API_KEY": self.sendgrid_api_key,
                "SENDER_EMAIL": self.sender_email,
                "ALERT_RECIPIENTS": self.alert_recipients,
                "ALERT_DEDUP_HOURS": self.alert_dedup_hours,
                "ALERT_MAX_RETRIES": self.alert_max_retries,
                "MONITOR_ROUTES": self.monitor_routes,
                "MONITOR_INTERVAL_SECONDS": self.monitor_interval_seconds,
                "RETRY_LOOKBACK_HOURS": self.retry_lookback_hours,
                "RETRY_BATCH_SIZE": self.retry_batch_size,
                "DASHBOARD_PASSWORD": self.dashboard_password,
            }
        )

    @classmethod
    def from_env(cls) -> "Settings":
        gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        database_url = os.getenv("DATABASE_URL", "").strip()
        openweather_api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
        enable_embeddings = os.getenv("ENABLE_EMBEDDINGS", "false").strip().lower() == "true"
        llm_trigger_threshold = float(os.getenv("LLM_TRIGGER_THRESHOLD", "45"))
        llm_provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower() or "gemini"
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3").strip() or "llama3"
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
        if not ollama_base_url:
            ollama_base_url = "http://localhost:11434"
        sendgrid_api_key = os.getenv("SENDGRID_API_KEY", "").strip()
        sender_email = os.getenv("SENDER_EMAIL", "").strip()
        alert_recipients = [
            email.strip()
            for email in os.getenv("ALERT_RECIPIENTS", "").split(",")
            if email.strip()
        ]
        alert_dedup_hours = int(os.getenv("ALERT_DEDUP_HOURS", "6"))
        alert_max_retries = int(os.getenv("ALERT_MAX_RETRIES", "3"))
        monitor_routes = [
            route.strip()
            for route in os.getenv(
                "MONITOR_ROUTES",
                "Red Sea -> India,Singapore Strait -> India",
            ).split(",")
            if route.strip()
        ]
        monitor_interval_seconds = int(os.getenv("MONITOR_INTERVAL_SECONDS", "3600"))
        retry_lookback_hours = int(os.getenv("RETRY_LOOKBACK_HOURS", "24"))
        retry_batch_size = int(os.getenv("RETRY_BATCH_SIZE", "50"))
        dashboard_password = os.getenv("DASHBOARD_PASSWORD", "").strip()

        if llm_provider not in {"gemini", "ollama"}:
            raise ValueError("LLM_PROVIDER must be either 'gemini' or 'ollama'.")
        if llm_provider == "gemini" and not gemini_api_key:
            raise ValueError("Missing GEMINI_API_KEY in environment for Gemini provider.")

        if not database_url:
            raise ValueError("Missing DATABASE_URL in environment.")
        if not 0 <= llm_trigger_threshold <= 100:
            raise ValueError("LLM_TRIGGER_THRESHOLD must be between 0 and 100.")
        if alert_dedup_hours < 1:
            raise ValueError("ALERT_DEDUP_HOURS must be at least 1.")
        if alert_max_retries < 1:
            raise ValueError("ALERT_MAX_RETRIES must be at least 1.")
        if monitor_interval_seconds < 60:
            raise ValueError("MONITOR_INTERVAL_SECONDS must be at least 60.")
        if retry_lookback_hours < 1:
            raise ValueError("RETRY_LOOKBACK_HOURS must be at least 1.")
        if retry_batch_size < 1:
            raise ValueError("RETRY_BATCH_SIZE must be at least 1.")

        return cls(
            gemini_api_key=gemini_api_key,
            database_url=database_url,
            openweather_api_key=openweather_api_key,
            enable_embeddings=enable_embeddings,
            llm_trigger_threshold=llm_trigger_threshold,
            llm_provider=llm_provider,
            ollama_model=ollama_model,
            ollama_base_url=ollama_base_url,
            sendgrid_api_key=sendgrid_api_key,
            sender_email=sender_email,
            alert_recipients=alert_recipients,
            alert_dedup_hours=alert_dedup_hours,
            alert_max_retries=alert_max_retries,
            monitor_routes=monitor_routes,
            monitor_interval_seconds=monitor_interval_seconds,
            retry_lookback_hours=retry_lookback_hours,
            retry_batch_size=retry_batch_size,
            dashboard_password=dashboard_password,
        )
