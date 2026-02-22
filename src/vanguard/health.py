"""Startup preflight checks for Vanguard runtime."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import aiohttp
import asyncpg
from dotenv import load_dotenv

from .config import Settings


def validate_required_keys(settings: Settings) -> None:
    """Ensure mandatory keys for core runtime execution are present."""
    missing: list[str] = []
    required = {
        "DATABASE_URL": settings.database_url,
    }
    if settings.llm_provider == "gemini":
        required["GEMINI_API_KEY"] = settings.gemini_api_key

    for key_name, value in required.items():
        if not value.strip():
            missing.append(key_name)

    if missing:
        raise RuntimeError(f"Missing required environment values: {', '.join(missing)}")

    placeholder_keys: list[str] = []
    if settings.llm_provider == "gemini" and settings.gemini_api_key == "replace_me":
        placeholder_keys.append("GEMINI_API_KEY")
    if "://user:password@" in settings.database_url:
        placeholder_keys.append("DATABASE_URL")
    if placeholder_keys:
        raise RuntimeError(
            "Replace placeholder environment values before startup: "
            f"{', '.join(placeholder_keys)}"
        )


async def _check_database(database_url: str) -> None:
    try:
        conn = await asyncpg.connect(database_url, timeout=8)
        try:
            await conn.execute("SELECT 1")
        finally:
            await conn.close()
    except Exception as exc:
        raise RuntimeError(
            "Database check failed. Verify PostgreSQL is running and DATABASE_URL has valid "
            f"credentials: {exc}"
        ) from exc


async def _check_gemini(api_key: str) -> None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Gemini API reachability check failed ({resp.status}): {body[:120]}")


async def _check_ollama(base_url: str, model_name: str) -> None:
    base = base_url.rstrip("/")
    url = f"{base}/api/tags"
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Ollama connectivity check failed ({resp.status}): {body[:120]}")

            payload = await resp.json()
            names = {
                str(item.get("name", "")).split(":")[0]
                for item in payload.get("models", [])
                if isinstance(item, dict)
            }
            if model_name and model_name.split(":")[0] not in names:
                raise RuntimeError(
                    f"Ollama model '{model_name}' is not available. Run: ollama pull {model_name}"
                )


async def _check_sendgrid(api_key: str) -> None:
    url = "https://api.sendgrid.com/v3/user/account"
    timeout = aiohttp.ClientTimeout(total=10)
    headers = {"Authorization": f"Bearer {api_key}"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"SendGrid API reachability check failed ({resp.status}): {body[:120]}")


async def run_startup_health(settings: Settings) -> None:
    """Run full startup checks; raise on any failure."""
    validate_required_keys(settings)
    checks = [_check_database(settings.database_url)]
    if settings.llm_provider == "gemini":
        checks.append(_check_gemini(settings.gemini_api_key))
    elif settings.llm_provider == "ollama":
        checks.append(_check_ollama(settings.ollama_base_url, settings.ollama_model))

    if settings.sendgrid_api_key:
        checks.append(_check_sendgrid(settings.sendgrid_api_key))

    await asyncio.gather(*checks)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vanguard startup health checks")
    parser.add_argument("--check-only", action="store_true", help="Run preflight checks and exit")
    return parser


def main() -> None:
    _ = build_parser().parse_args()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    settings = Settings.from_env()
    asyncio.run(run_startup_health(settings))
    print("[HEALTH] startup checks passed")


if __name__ == "__main__":
    main()
