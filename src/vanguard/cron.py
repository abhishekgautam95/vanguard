"""Autonomous monitoring loop for Vanguard."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from .config import Settings
from .engine import VanguardEngine
from .health import run_startup_health
from .ingestion import ingest_all
from .monitor import async_timed, error_tracker, get_logger
from .notifications import AlertService
from .reasoning import VanguardReasoner
from .storage import Storage

_log = get_logger("vanguard.cron")


async def _persist_perf(storage: Storage, records: list) -> None:
    """Persist the first PerformanceRecord from a timed context manager result."""
    if records:
        await storage.save_performance_log(**records[0].as_dict())


async def process_route(
    route: str,
    settings: Settings,
    engine: VanguardEngine,
    storage: Storage,
    alert_service: AlertService,
    dry_run: bool,
) -> None:
    """Run ingestion, reasoning, and notifications for a single route."""
    async with async_timed("ingestion", "ingest_all", extra={"route": route}) as rec:
        events = await ingest_all(route, openweather_api_key=settings.openweather_api_key)
    await _persist_perf(storage, rec)

    if not dry_run:
        async with async_timed("database", "save_events", extra={"route": route}) as rec:
            await storage.save_events(events)
        await _persist_perf(storage, rec)

    async with async_timed("engine", "evaluate_route", extra={"route": route}) as rec:
        result = await engine.evaluate_route(route=route, events=events)
    await _persist_perf(storage, rec)

    _log.info(
        "route_evaluated",
        extra={
            "_vg_route": route,
            "_vg_risk": result.final_risk,
            "_vg_delay": result.predicted_delay_days,
            "_vg_action": result.recommended_action,
        },
    )
    print(
        f"[ROUTE] {route} | risk={result.final_risk} | "
        f"delay={result.predicted_delay_days} | action={result.recommended_action}"
    )

    if result.requires_escalation:
        async with async_timed("notifications", "alert_dispatch", extra={"route": route}) as rec:
            await alert_service.dispatch(
                recipients=settings.alert_recipients,
                result=result,
                dry_run=dry_run,
            )
        await _persist_perf(storage, rec)


async def run_once(settings: Settings, dry_run: bool = False) -> int:
    """Execute one monitoring cycle across all configured routes."""
    embedder = None
    if settings.enable_embeddings:
        from .embeddings import GeminiEmbedder

        embedder = GeminiEmbedder(settings.gemini_api_key)
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
    alert_service = AlertService(
        storage=storage,
        api_key=settings.sendgrid_api_key,
        from_email=settings.sender_email,
        dedup_hours=settings.alert_dedup_hours,
        max_retries=settings.alert_max_retries,
    )

    await storage.connect()
    try:
        await asyncio.gather(
            *(
                process_route(
                    route=route,
                    settings=settings,
                    engine=engine,
                    storage=storage,
                    alert_service=alert_service,
                    dry_run=dry_run,
                )
                for route in settings.monitor_routes
            )
        )

        retried = await alert_service.retry_failed_dispatches(
            max_records=settings.retry_batch_size,
            lookback_hours=settings.retry_lookback_hours,
            dry_run=dry_run,
        )
        print(f"[RETRY] processed={retried}")
        return 0
    finally:
        await storage.close()


async def monitoring_loop(dry_run: bool = False) -> int:
    """Continuously run monitoring cycles at configured intervals."""
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    settings = Settings.from_env()

    print(
        "Vanguard Monitoring Active | "
        f"routes={len(settings.monitor_routes)} | "
        f"interval={settings.monitor_interval_seconds}s"
    )
    print(f"[CONFIG] {settings.redacted_snapshot()}")

    while True:
        try:
            await run_once(settings=settings, dry_run=dry_run)
            await asyncio.sleep(settings.monitor_interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error_tracker.record("monitoring_loop", exc)
            print(f"[LOOP_ERROR] {exc}")
            await asyncio.sleep(300)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project Vanguard autonomous runner")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Do not send live emails")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    settings = Settings.from_env()
    asyncio.run(run_startup_health(settings))

    if args.once:
        raise SystemExit(asyncio.run(run_once(settings=settings, dry_run=args.dry_run)))

    raise SystemExit(asyncio.run(monitoring_loop(dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
