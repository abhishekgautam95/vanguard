CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS risk_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    geo_location TEXT NOT NULL,
    severity INTEGER NOT NULL CHECK (severity >= 0 AND severity <= 100),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    description TEXT NOT NULL,
    source TEXT NOT NULL,
    route TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reasoning_cache (
    cache_key TEXT PRIMARY KEY,
    response_json JSONB NOT NULL,
    embedding VECTOR(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS event_embeddings (
    event_id BIGINT PRIMARY KEY REFERENCES risk_events(id) ON DELETE CASCADE,
    embedding VECTOR(768) NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_dispatch_log (
    id BIGSERIAL PRIMARY KEY,
    alert_key TEXT NOT NULL,
    route TEXT NOT NULL,
    risk_bucket TEXT NOT NULL,
    recipient TEXT NOT NULL,
    status TEXT NOT NULL,
    decision_payload JSONB,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    provider_message_id TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_dispatch_log_key_time
    ON alert_dispatch_log (alert_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_risk_events_route_time
    ON risk_events (route, event_time DESC);
