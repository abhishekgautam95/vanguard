"""Database migration runner for Vanguard."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

from .config import Settings


def _split_sql_statements(sql_text: str) -> list[str]:
    return [stmt.strip() for stmt in sql_text.split(";") if stmt.strip()]


async def run_migrations(database_url: str, sql_path: Path) -> None:
    if not sql_path.exists():
        raise FileNotFoundError(f"Migration file not found: {sql_path}")

    sql_text = sql_path.read_text(encoding="utf-8")
    statements = _split_sql_statements(sql_text)

    conn = await asyncpg.connect(database_url)
    try:
        try:
            for stmt in statements:
                await conn.execute(stmt)
        except asyncpg.FeatureNotSupportedError as exc:
            message = str(exc).lower()
            if "extension \"vector\" is not available" in message:
                raise RuntimeError(
                    "pgvector extension is not installed on PostgreSQL. "
                    "Install pgvector, then run: "
                    "sudo -u postgres psql -d vanguard -c \"CREATE EXTENSION IF NOT EXISTS vector;\""
                ) from exc
            raise

        # Forward-compatible table updates for existing installs.
        await conn.execute(
            """
            ALTER TABLE alert_dispatch_log
            ADD COLUMN IF NOT EXISTS decision_payload JSONB,
            ADD COLUMN IF NOT EXISTS attempt_number INTEGER NOT NULL DEFAULT 1
            """
        )
    finally:
        await conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vanguard database migration runner")
    parser.add_argument(
        "--sql",
        default=str(Path(__file__).resolve().parents[2] / "sql" / "init.sql"),
        help="Path to SQL migration file",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    settings = Settings.from_env()
    asyncio.run(run_migrations(settings.database_url, Path(args.sql)))
    print("[MIGRATE] completed")


if __name__ == "__main__":
    main()
