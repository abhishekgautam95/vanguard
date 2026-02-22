"""CLI entrypoint for Project Vanguard MVP."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from .actions import draft_alert_email
from .config import Settings
from .embeddings import GeminiEmbedder
from .engine import VanguardEngine
from .health import run_startup_health
from .ingestion import ingest_all
from .notifications import AlertService
from .reasoning import ReasoningError, VanguardReasoner
from .storage import Storage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project Vanguard Phase-1")
    parser.add_argument("--route", required=True, help="Shipping route label")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip database writes for local validation",
    )
    return parser


async def run(route: str, dry_run: bool) -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    settings = Settings.from_env()
    await run_startup_health(settings)

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

    if not dry_run:
        await storage.connect()

    try:
        events = await ingest_all(route, openweather_api_key=settings.openweather_api_key)
        if not dry_run:
            await storage.save_events(events)

        result = await engine.evaluate_route(route=route, events=events)
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
                dry_run=dry_run,
            )
            print(
                "\n--- Alert Dispatch ---\n"
                f"Recipients: {len(settings.alert_recipients)} | "
                f"Mode: {'dry-run' if dry_run else 'live'}"
            )
        return 0
    except (ReasoningError, ValueError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        return 1
    finally:
        if not dry_run:
            await storage.close()


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(run(route=args.route, dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
