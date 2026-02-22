"""Async ingestion layer with zero-cost RSS + weather adapters."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
import xml.etree.ElementTree as et

import aiohttp

from .schemas import RiskEvent

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
_BAB_EL_MANDEB = {"lat": 12.7, "lon": 43.3}
_USER_AGENT = "VanguardIngestor/1.0"


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _parse_rfc_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)

    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _severity_from_keywords(text: str, keyword_map: dict[str, int], default: int) -> int:
    lowered = text.lower()
    matched = [score for keyword, score in keyword_map.items() if keyword in lowered]
    if not matched:
        return default
    return min(100, max(matched))


class NewsIngestor:
    """Ingest geopolitical disruptions using Google News RSS search."""

    def __init__(self, route: str):
        self.route = route

    def _build_query(self) -> str:
        return (
            "maritime security OR houthi OR suez OR bab el mandeb "
            f"shipping disruption delay congestion {self.route} when:2d"
        )

    async def fetch(self, session: aiohttp.ClientSession) -> list[RiskEvent]:
        params = {
            "q": self._build_query(),
            "hl": "en-IN",
            "gl": "IN",
            "ceid": "IN:en",
        }
        query = "&".join(f"{key}={quote_plus(str(value))}" for key, value in params.items())
        url = f"{_GOOGLE_NEWS_RSS}?{query}"

        async with session.get(url, timeout=15) as response:
            response.raise_for_status()
            xml_body = await response.text()

        root = et.fromstring(xml_body)
        events: list[RiskEvent] = []
        keyword_map = {
            "attack": 90,
            "missile": 92,
            "blocked": 86,
            "closure": 80,
            "strike": 85,
            "sanction": 75,
            "tension": 72,
            "delay": 70,
        }

        for item in root.findall("./channel/item")[:8]:
            title = _normalize_text(item.findtext("title", default=""))
            description = _normalize_text(item.findtext("description", default=""))
            text = f"{title} {description}"
            severity = _severity_from_keywords(text, keyword_map=keyword_map, default=60)
            if severity < 60:
                continue

            events.append(
                RiskEvent(
                    event_type="Geopolitical",
                    geo_location="Red Sea / Suez",
                    severity=severity,
                    confidence=0.72,
                    description=title,
                    source=item.findtext("link", default="google_news_rss"),
                    route=self.route,
                    event_time=_parse_rfc_datetime(item.findtext("pubDate")),
                )
            )

        return events


class PortIngestor:
    """Ingest port delay signals from open RSS search queries."""

    def __init__(self, route: str):
        self.route = route

    async def fetch(self, session: aiohttp.ClientSession) -> list[RiskEvent]:
        terms = [
            "Mundra port congestion delay when:2d",
            "JNPT congestion vessel queue delay when:2d",
            f"{self.route} container delay port congestion when:2d",
        ]

        events: list[RiskEvent] = []
        keyword_map = {
            "queue": 72,
            "congestion": 75,
            "berth": 70,
            "delay": 68,
            "backlog": 78,
            "turnaround": 65,
        }

        for term in terms:
            url = (
                f"{_GOOGLE_NEWS_RSS}?q={quote_plus(term)}"
                "&hl=en-IN&gl=IN&ceid=IN:en"
            )
            async with session.get(url, timeout=15) as response:
                response.raise_for_status()
                xml_body = await response.text()

            root = et.fromstring(xml_body)
            for item in root.findall("./channel/item")[:3]:
                title = _normalize_text(item.findtext("title", default=""))
                description = _normalize_text(item.findtext("description", default=""))
                text = f"{title} {description}"
                severity = _severity_from_keywords(text, keyword_map=keyword_map, default=58)

                if severity < 62:
                    continue

                events.append(
                    RiskEvent(
                        event_type="PortCongestion",
                        geo_location="Mundra/JNPT",
                        severity=severity,
                        confidence=0.68,
                        description=title,
                        source=item.findtext("link", default="google_news_rss"),
                        route=self.route,
                        event_time=_parse_rfc_datetime(item.findtext("pubDate")),
                    )
                )

        dedup: dict[str, RiskEvent] = {}
        for event in events:
            dedup[event.description.lower()] = event
        return list(dedup.values())


class WeatherIngestor:
    """Ingest weather risk from OpenWeather current conditions."""

    def __init__(self, route: str, api_key: str | None):
        self.route = route
        self.api_key = api_key or ""

    @staticmethod
    def _map_weather_to_severity(payload: dict[str, Any]) -> tuple[int, str]:
        wind_speed = float(payload.get("wind", {}).get("speed", 0.0))
        weather_text = " ".join(w.get("description", "") for w in payload.get("weather", []))
        weather_text = _normalize_text(weather_text) or "normal conditions"

        severity = 20
        if wind_speed >= 20:
            severity = 90
        elif wind_speed >= 15:
            severity = 76
        elif wind_speed >= 10:
            severity = 60
        elif "storm" in weather_text.lower() or "squall" in weather_text.lower():
            severity = 70

        reason = f"Wind speed {wind_speed:.1f} m/s, weather: {weather_text}"
        return severity, reason

    async def fetch(self, session: aiohttp.ClientSession) -> list[RiskEvent]:
        if not self.api_key:
            return []

        params = {
            "lat": _BAB_EL_MANDEB["lat"],
            "lon": _BAB_EL_MANDEB["lon"],
            "appid": self.api_key,
            "units": "metric",
        }
        query = "&".join(f"{key}={quote_plus(str(value))}" for key, value in params.items())
        url = f"https://api.openweathermap.org/data/2.5/weather?{query}"

        async with session.get(url, timeout=15) as response:
            response.raise_for_status()
            payload = await response.json()

        severity, reason = self._map_weather_to_severity(payload)

        return [
            RiskEvent(
                event_type="Weather",
                geo_location="Bab-el-Mandeb",
                severity=severity,
                confidence=0.80,
                description=reason,
                source="openweathermap",
                route=self.route,
                event_time=datetime.now(timezone.utc),
            )
        ]


async def ingest_all(route: str, openweather_api_key: str | None = None) -> list[RiskEvent]:
    """Parallel ingestion across geopolitical news, ports, and weather."""
    weather_api_key = (openweather_api_key or os.getenv("OPENWEATHER_API_KEY", "")).strip()

    async with aiohttp.ClientSession(headers={"User-Agent": _USER_AGENT}) as session:
        news_task = NewsIngestor(route).fetch(session)
        ports_task = PortIngestor(route).fetch(session)
        weather_task = WeatherIngestor(route, weather_api_key).fetch(session)

        news, ports, weather = await asyncio.gather(
            news_task,
            ports_task,
            weather_task,
            return_exceptions=True,
        )

    events: list[RiskEvent] = []
    for result in (news, ports, weather):
        if isinstance(result, Exception):
            continue
        events.extend(result)

    if events:
        return events

    return [
        RiskEvent(
            event_type="Other",
            geo_location="Global",
            severity=20,
            confidence=0.40,
            description="No high-signal live events retrieved; fallback low-risk state.",
            source="ingestion_fallback",
            route=route,
            event_time=datetime.now(timezone.utc),
        )
    ]
