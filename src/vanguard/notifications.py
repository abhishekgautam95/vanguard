"""Outbound notification service with SendGrid, deduplication, and retries."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

from .schemas import DecisionResult
from .storage import Storage

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
except ImportError:  # pragma: no cover - optional dependency for runtime only
    SendGridAPIClient = None
    Mail = None


class AlertService:
    """Dispatches risk alerts with idempotency and retry policy."""

    def __init__(
        self,
        storage: Storage,
        api_key: str,
        from_email: str,
        dedup_hours: int = 6,
        max_retries: int = 3,
    ):
        self.storage = storage
        self.api_key = api_key
        self.from_email = from_email
        self.dedup_hours = dedup_hours
        self.max_retries = max_retries

        if api_key and SendGridAPIClient is not None:
            self.client = SendGridAPIClient(api_key)
        else:
            self.client = None

    @staticmethod
    def _risk_bucket(score: float) -> str:
        if score >= 80:
            return "critical"
        if score >= 60:
            return "high"
        if score >= 40:
            return "medium"
        return "low"

    def _alert_key(self, result: DecisionResult, recipient: str) -> str:
        date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        risk_bucket = self._risk_bucket(result.final_risk)
        seed = f"{result.route}:{date_key}:{risk_bucket}:{recipient}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def format_html_report(self, result: DecisionResult) -> str:
        """Build concise email-safe HTML for risk decisions."""
        action = (result.recommended_action or "monitor").upper()
        color = "#d9534f" if "REROUTE" in action else "#f0ad4e"

        alternatives = "".join(f"<li>{item}</li>" for item in result.alternatives)
        cba_html = ""
        if result.cost_benefit:
            cba_html = (
                f"<p><b>Cost-Benefit Decision:</b> {result.cost_benefit.get('recommendation', 'n/a')}</p>"
                f"<p>{result.cost_benefit.get('rationale', '')}</p>"
            )

        return (
            "<html><body style='font-family:Arial,sans-serif;'>"
            f"<h2 style='color:{color};'>Vanguard Risk Alert: {result.route}</h2>"
            f"<p><b>Risk Score:</b> {result.final_risk}/100</p>"
            f"<p><b>Predicted Delay:</b> {result.predicted_delay_days} days</p>"
            f"<p><b>Recommendation:</b> <span style='font-weight:bold'>{action}</span></p>"
            "<hr/>"
            "<h4>AI Reasoning</h4>"
            f"<p>{result.reason}</p>"
            "<h4>Alternatives</h4>"
            f"<ul>{alternatives}</ul>"
            f"{cba_html}"
            "</body></html>"
        )

    async def _send_with_retries(self, to_email: str, result: DecisionResult) -> tuple[bool, str | None]:
        if self.client is None or Mail is None or not self.from_email:
            return False, "sendgrid_not_configured"

        message = Mail(
            from_email=self.from_email,
            to_emails=to_email,
            subject=f"Vanguard Alert: {result.route} risk {result.final_risk}/100",
            html_content=self.format_html_report(result),
        )

        delay = 1.0
        last_error: str | None = None
        for _ in range(self.max_retries):
            try:
                response = await asyncio.to_thread(self.client.send, message)
                code = getattr(response, "status_code", 500)
                if 200 <= code < 300:
                    message_id = getattr(response, "headers", {}).get("X-Message-Id")
                    return True, message_id
                last_error = f"http_status_{code}"
            except Exception as exc:  # broad to catch provider errors
                last_error = str(exc)

            await asyncio.sleep(delay)
            delay *= 2

        return False, last_error

    async def dispatch(self, recipients: list[str], result: DecisionResult, dry_run: bool = False) -> None:
        """Send deduplicated alerts to all recipients."""
        if not recipients:
            return

        risk_bucket = self._risk_bucket(result.final_risk)
        bypass_dedup = result.final_risk >= 90.0
        payload = result.model_dump()

        for recipient in recipients:
            alert_key = self._alert_key(result, recipient)

            if not bypass_dedup:
                already_sent = await self.storage.has_recent_alert(
                    alert_key=alert_key,
                    recipient=recipient,
                    lookback_hours=self.dedup_hours,
                )
                if already_sent:
                    continue

            if dry_run:
                await self.storage.log_alert_dispatch(
                    alert_key=alert_key,
                    route=result.route,
                    risk_bucket=risk_bucket,
                    recipient=recipient,
                    status="dry_run",
                    decision_payload=payload,
                )
                continue

            ok, provider_or_error = await self._send_with_retries(recipient, result)
            if ok:
                await self.storage.log_alert_dispatch(
                    alert_key=alert_key,
                    route=result.route,
                    risk_bucket=risk_bucket,
                    recipient=recipient,
                    status="sent",
                    decision_payload=payload,
                    provider_message_id=provider_or_error,
                )
            else:
                await self.storage.log_alert_dispatch(
                    alert_key=alert_key,
                    route=result.route,
                    risk_bucket=risk_bucket,
                    recipient=recipient,
                    status="failed",
                    decision_payload=payload,
                    error_message=provider_or_error,
                )

    async def retry_failed_dispatches(
        self,
        max_records: int = 50,
        lookback_hours: int = 24,
        dry_run: bool = False,
    ) -> int:
        """Retry failed alert sends from persistent dispatch log."""
        rows = await self.storage.get_retry_candidates(
            limit=max_records,
            lookback_hours=lookback_hours,
        )
        if not rows:
            return 0

        retried = 0
        for row in rows:
            recipient = str(row["recipient"])
            alert_key = str(row["alert_key"])
            risk_bucket = str(row["risk_bucket"])
            attempt_number = int(row.get("attempt_number") or 1) + 1

            try:
                result = DecisionResult.model_validate(row["decision_payload"])
            except Exception:
                await self.storage.log_alert_dispatch(
                    alert_key=alert_key,
                    route=str(row["route"]),
                    risk_bucket=risk_bucket,
                    recipient=recipient,
                    status="failed",
                    attempt_number=attempt_number,
                    error_message="invalid_decision_payload",
                )
                continue

            if dry_run:
                await self.storage.log_alert_dispatch(
                    alert_key=alert_key,
                    route=result.route,
                    risk_bucket=risk_bucket,
                    recipient=recipient,
                    status="dry_run",
                    decision_payload=result.model_dump(),
                    attempt_number=attempt_number,
                )
                retried += 1
                continue

            ok, provider_or_error = await self._send_with_retries(recipient, result)
            if ok:
                await self.storage.log_alert_dispatch(
                    alert_key=alert_key,
                    route=result.route,
                    risk_bucket=risk_bucket,
                    recipient=recipient,
                    status="sent",
                    decision_payload=result.model_dump(),
                    attempt_number=attempt_number,
                    provider_message_id=provider_or_error,
                )
                retried += 1
            else:
                await self.storage.log_alert_dispatch(
                    alert_key=alert_key,
                    route=result.route,
                    risk_bucket=risk_bucket,
                    recipient=recipient,
                    status="failed",
                    decision_payload=result.model_dump(),
                    attempt_number=attempt_number,
                    error_message=provider_or_error,
                )

        return retried
