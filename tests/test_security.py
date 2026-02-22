"""Security utility tests."""

from vanguard.security import mask_secret, redact_env_snapshot


def test_mask_secret_long_value() -> None:
    masked = mask_secret("abcdef123456", visible_prefix=3, visible_suffix=2)
    assert masked.startswith("abc")
    assert masked.endswith("56")
    assert "1234" not in masked


def test_mask_secret_short_value() -> None:
    assert mask_secret("abcd", visible_prefix=3, visible_suffix=2) == "****"


def test_redact_env_snapshot() -> None:
    data = {
        "GEMINI_API_KEY": "secret_value",
        "ALERT_MAX_RETRIES": 3,
    }
    redacted = redact_env_snapshot(data)
    assert redacted["GEMINI_API_KEY"] != "secret_value"
    assert redacted["ALERT_MAX_RETRIES"] == 3
