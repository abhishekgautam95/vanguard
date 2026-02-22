"""Security helpers for secret redaction and safe logging."""

from __future__ import annotations

from typing import Any


def mask_secret(value: str, visible_prefix: int = 4, visible_suffix: int = 2) -> str:
    """Mask a secret value for logs while keeping short boundary context."""
    secret = (value or "").strip()
    if not secret:
        return ""

    if len(secret) <= visible_prefix + visible_suffix:
        return "*" * len(secret)

    return f"{secret[:visible_prefix]}{'*' * (len(secret) - visible_prefix - visible_suffix)}{secret[-visible_suffix:]}"


def redact_env_snapshot(env_map: dict[str, Any], secret_keys: set[str] | None = None) -> dict[str, Any]:
    """Return redacted copy of selected env/settings keys."""
    sensitive = secret_keys or {
        "GEMINI_API_KEY",
        "SENDGRID_API_KEY",
        "OPENWEATHER_API_KEY",
        "DATABASE_URL",
        "DASHBOARD_PASSWORD",
    }

    redacted: dict[str, Any] = {}
    for key, value in env_map.items():
        if key in sensitive and isinstance(value, str):
            redacted[key] = mask_secret(value)
        else:
            redacted[key] = value
    return redacted
