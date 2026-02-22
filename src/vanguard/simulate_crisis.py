"""Manual crisis simulation utility for safe response testing."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from .actions import draft_alert_email
from .config import Settings
from .embeddings import GeminiEmbedder
from .engine import VanguardEngine
from .health import run_startup_health
from .notifications import AlertService
from .reasoning import VanguardReasoner
from .schemas import RiskEvent
from .storage import Storage

_EVENT_TYPES = ["Geopolitical", "Weather", "PortCongestion", "Other"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inject a synthetic crisis and inspect agent response")
    parser.add_argument("--route", required=True, help="Route label, e.g. 'Singapore Strait -> India'")
    parser.add_argument("--headline", required=True, help="Synthetic event headline/description")
    parser.add_argument(
        "--event-type",
        default="Geopolitical",
        choices=_EVENT_TYPES,
        help="Synthetic event type",
    )
    parser.add_argument("--geo-location", default="Simulated", help="Location label for event")
    parser.add_argument("--severity", type=int, default=88, help="Severity score (0-100)")
    parser.add_argument("--confidence", type=float, default=0.90, help="Confidence score (0-1)")
    parser.add_argument(
        "--source",
        default="manual_simulation",
        help="Source tag saved with event",
    )
    parser.add_argument(
        "--hours-ago",
        type=float,
        default=0.0,
        help="Backdate event timestamp by N hours",
    )
    parser.add_argument(
        "--dispatch-live",
        action="store_true",
        help="Send live alerts when escalation triggers (default: dry-run only)",
    )
    return parser


def _build_simulated_event(args: argparse.Namespace) -> RiskEvent:
    event_time = datetime.now(timezone.utc) - timedelta(hours=max(0.0, args.hours_ago))
    return RiskEvent(
        event_type=args.event_type,
        geo_location=args.geo_location,
        severity=args.severity,
        confidence=args.confidence,
        description=args.headline,
        source=args.source,
        route=args.route,
        event_time=event_time,
    )


async def run_simulation(args: argparse.Namespace) -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    settings = Settings.from_env()
    await run_startup_health(settings)

    event = _build_simulated_event(args)
    embedder = GeminiEmbedder(settings.gemini_api_key) if settings.enable_embeddings else None
    storage = Storage(settings.database_url, embedder=embedder)
    reasoner = VanguardReasoner(
        api_key=settings.gemini_api_key,
        llm_provider=settings.llm_provider,
        ollama_model=settings.ollama_model,
        ollama_base_url=settings.ollama_base_url,
    )
    engine = VanguardEngine(
        reasoner=reasoner,
        storage=storage,
        llm_trigger_threshold=settings.llm_trigger_threshold,
    )

    await storage.connect()
    try:
        await storage.save_events([event])
        result = await engine.evaluate_route(route=args.route, events=[event])
        print("[SIMULATION] injected event:")
        print(event.model_dump_json(indent=2))
        print("\n[SIMULATION] decision result:")
        print(result.model_dump_json(indent=2))
        print("\n--- Alert Draft ---\n")
        print(draft_alert_email(result))

        if result.requires_escalation:
            alert_service = AlertService(
                storage=storage,
                api_key=settings.sendgrid_api_key,
                from_email=settings.sender_email,
                dedup_hours=settings.alert_dedup_hours,
                max_retries=settings.alert_max_retries,
            )
            await alert_service.dispatch(
                recipients=settings.alert_recipients,
                result=result,
                dry_run=not args.dispatch_live,
            )
            print(
                "\n--- Dispatch Status ---\n"
                f"Triggered: yes | Mode: {'live' if args.dispatch_live else 'dry-run'} | "
                f"Recipients configured: {len(settings.alert_recipients)}"
            )
        else:
            print("\n--- Dispatch Status ---\nTriggered: no (no escalation)")

        return 0
    finally:
        await storage.close()


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(run_simulation(args)))


if __name__ == "__main__":
    main()
