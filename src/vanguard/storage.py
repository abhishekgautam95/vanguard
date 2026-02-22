"""Persistence and semantic cache helpers for PostgreSQL + pgvector."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from .embeddings import Embedder
from .schemas import LLMRiskResponse, RiskEvent


class Storage:
    """Thin async storage wrapper."""

    def __init__(self, database_url: str, embedder: Embedder | None = None):
        self._database_url = database_url
        self._embedder = embedder
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=5)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def save_events(self, events: list[RiskEvent]) -> None:
        if not events:
            return
        if self._pool is None:
            return

        insert_event = """
            INSERT INTO risk_events (
                event_type,
                geo_location,
                severity,
                confidence,
                description,
                source,
                route,
                event_time
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
        """
        insert_embedding = """
            INSERT INTO event_embeddings (event_id, embedding)
            VALUES ($1, $2::vector)
            ON CONFLICT (event_id) DO UPDATE
            SET embedding = EXCLUDED.embedding
        """

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for event in events:
                    event_id = await conn.fetchval(
                        insert_event,
                        event.event_type,
                        event.geo_location,
                        event.severity,
                        event.confidence,
                        event.description,
                        event.source,
                        event.route,
                        event.event_time,
                    )

                    if self._embedder is None:
                        continue

                    try:
                        embedding = self._embedder.embed_text(
                            f"{event.event_type} {event.geo_location} {event.description}"
                        )
                        if not embedding:
                            continue
                        vector_value = "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"
                        await conn.execute(insert_embedding, event_id, vector_value)
                    except Exception:
                        # Embedding failures should not stop ingestion pipeline.
                        continue

    @staticmethod
    def cache_key(route: str, prompt_payload: dict[str, Any]) -> str:
        blob = json.dumps({"route": route, "payload": prompt_payload}, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    async def get_cached_reasoning(self, key: str) -> LLMRiskResponse | None:
        if self._pool is None:
            return None

        query = """
            SELECT response_json
            FROM reasoning_cache
            WHERE cache_key = $1 AND expires_at > NOW()
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, key)

        if not row:
            return None
        return LLMRiskResponse.model_validate(row["response_json"])

    async def set_cached_reasoning(
        self,
        key: str,
        response: LLMRiskResponse,
        ttl_minutes: int = 60,
    ) -> None:
        if self._pool is None:
            return

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        query = """
            INSERT INTO reasoning_cache (cache_key, response_json, expires_at)
            VALUES ($1, $2::jsonb, $3)
            ON CONFLICT (cache_key)
            DO UPDATE SET
                response_json = EXCLUDED.response_json,
                expires_at = EXCLUDED.expires_at
        """
        async with self._pool.acquire() as conn:
            await conn.execute(query, key, response.model_dump_json(), expires_at)

    async def has_recent_alert(
        self,
        alert_key: str,
        recipient: str,
        lookback_hours: int = 6,
    ) -> bool:
        """Check if same alert key was recently sent to recipient."""
        if self._pool is None:
            return False

        query = """
            SELECT 1
            FROM alert_dispatch_log
            WHERE alert_key = $1
              AND recipient = $2
              AND status = 'sent'
              AND created_at > NOW() - ($3::text || ' hours')::interval
            LIMIT 1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, alert_key, recipient, str(lookback_hours))
        return row is not None

    async def log_alert_dispatch(
        self,
        alert_key: str,
        route: str,
        risk_bucket: str,
        recipient: str,
        status: str,
        decision_payload: dict[str, Any] | None = None,
        attempt_number: int = 1,
        provider_message_id: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Persist outbound alert attempt status."""
        if self._pool is None:
            return

        query = """
            INSERT INTO alert_dispatch_log (
                alert_key,
                route,
                risk_bucket,
                recipient,
                status,
                decision_payload,
                attempt_number,
                provider_message_id,
                error_message
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                query,
                alert_key,
                route,
                risk_bucket,
                recipient,
                status,
                json.dumps(decision_payload) if decision_payload is not None else None,
                attempt_number,
                provider_message_id,
                error_message,
            )

    async def get_retry_candidates(
        self,
        limit: int = 50,
        lookback_hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Fetch latest failed dispatch records per alert/recipient."""
        if self._pool is None:
            return []

        query = """
            WITH latest_per_alert AS (
                SELECT DISTINCT ON (alert_key, recipient)
                    id,
                    alert_key,
                    route,
                    risk_bucket,
                    recipient,
                    status,
                    decision_payload,
                    attempt_number,
                    error_message,
                    created_at
                FROM alert_dispatch_log
                WHERE created_at > NOW() - ($1::text || ' hours')::interval
                ORDER BY alert_key, recipient, created_at DESC
            )
            SELECT
                id,
                alert_key,
                route,
                risk_bucket,
                recipient,
                status,
                decision_payload,
                attempt_number,
                error_message,
                created_at
            FROM latest_per_alert
            WHERE status = 'failed'
              AND decision_payload IS NOT NULL
            ORDER BY created_at DESC
            LIMIT $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, str(lookback_hours), limit)

        return [dict(row) for row in rows]
