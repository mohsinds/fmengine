"""Env-first news provider with free RSS fallback (PIT-safe)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from fmtrader.config.settings import get_settings
from fmtrader.providers.contracts import (
    AlignmentStrategy,
    DateRange,
    FeatureSpec,
    PointInTimeRecord,
    ProviderCapabilities,
    ProviderHealth,
)
from fmtrader.providers.protocol import FeatureProvider
from fmtrader.system.logging import get_logger

log = get_logger(__name__)

# Free Google News RSS queries (no key). Publication time used as available_time floor.
_DEFAULT_RSS_QUERIES = (
    "XAUUSD OR gold price OR gold futures",
    "Federal Reserve interest rates",
)


class NewsFeedProvider(FeatureProvider):
    """Prefer NEWS_API_KEY (NewsAPI.org); else free RSS; else disabled."""

    name = "news_feed"
    kind = "news"
    optional = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        rss_queries: tuple[str, ...] = _DEFAULT_RSS_QUERIES,
        publication_lag: timedelta = timedelta(minutes=1),
        timeout_s: float = 15.0,
    ) -> None:
        settings = get_settings()
        self.api_key = (api_key if api_key is not None else settings.news_api_key) or ""
        self.rss_queries = rss_queries
        self.publication_lag = publication_lag
        self.timeout_s = timeout_s
        self._mode = "newsapi" if self.api_key else "rss"
        self._last_error: str | None = None
        self._disabled = False

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            symbols="*",
            asset_classes=["fx", "cfd", "metal", "equity", "future"],
            min_granularity="1m",
            has_revisions=False,
            typical_publication_lag=self.publication_lag,
            requires_credentials=bool(self.api_key),
            enforce_nonzero_lag=True,
        )

    def availability(self, symbol: str) -> DateRange | None:
        if self._disabled:
            return None
        now = datetime.now(tz=UTC)
        return DateRange(start=now - timedelta(days=7), end=now)

    def health(self) -> ProviderHealth:
        if self._disabled:
            return ProviderHealth(
                ok=False,
                detail=self._last_error or "news provider disabled",
                disable_reason=self._last_error or "unavailable",
            )
        return ProviderHealth(
            ok=True,
            detail=f"mode={self._mode}",
        )

    def feature_specs(self) -> list[FeatureSpec]:
        return [
            FeatureSpec(
                name="news_sentiment_polarity_last",
                dtype="float",
                alignment=AlignmentStrategy(strategy="last_known", value_field="polarity"),
                null_policy="null",
            ),
            FeatureSpec(
                name="news_count_60m",
                dtype="float",
                alignment=AlignmentStrategy(
                    strategy="count",
                    window=timedelta(minutes=60),
                    value_field="polarity",
                ),
                null_policy="zero",
            ),
        ]

    def fetch(self, symbol: str, start: datetime, end: datetime) -> Iterable[PointInTimeRecord]:
        if self._disabled:
            return []
        try:
            if self.api_key:
                return list(self._fetch_newsapi(symbol, start, end))
            return list(self._fetch_rss(symbol, start, end))
        except Exception as exc:
            self._last_error = str(exc)
            log.warning("news_feed_fetch_failed", error=str(exc), mode=self._mode)
            # Soft-disable for this process so compose can skip
            self._disabled = True
            return []

    def _fetch_newsapi(
        self, symbol: str, start: datetime, end: datetime
    ) -> Iterable[PointInTimeRecord]:
        q = quote_plus(f"{symbol} OR gold")
        url = (
            "https://newsapi.org/v2/everything?"
            f"q={q}&language=en&pageSize=50&sortBy=publishedAt"
            f"&from={start.astimezone(UTC).date().isoformat()}"
            f"&to={end.astimezone(UTC).date().isoformat()}"
        )
        req = Request(url, headers={"X-Api-Key": self.api_key, "User-Agent": "fmtrader/0.1"})
        with urlopen(req, timeout=self.timeout_s) as resp:
            import json

            payload = json.loads(resp.read().decode("utf-8"))
        articles = payload.get("articles") or []
        return self._articles_to_records(articles, start, end, source="newsapi")

    def _fetch_rss(
        self, symbol: str, start: datetime, end: datetime
    ) -> Iterable[PointInTimeRecord]:
        records: list[PointInTimeRecord] = []
        for q in self.rss_queries:
            url = (
                "https://news.google.com/rss/search?q="
                + quote_plus(q)
                + "&hl=en-US&gl=US&ceid=US:en"
            )
            req = Request(url, headers={"User-Agent": "fmtrader/0.1"})
            with urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read()
            root = ET.fromstring(raw)
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                pub = item.findtext("pubDate")
                link = (item.findtext("link") or "").strip()
                if not pub:
                    continue
                try:
                    event_t = parsedate_to_datetime(pub)
                    if event_t.tzinfo is None:
                        event_t = event_t.replace(tzinfo=UTC)
                    else:
                        event_t = event_t.astimezone(UTC)
                except Exception:
                    continue
                avail = event_t + self.publication_lag
                if avail < start.astimezone(UTC) or avail > end.astimezone(UTC):
                    continue
                polarity = _title_polarity(title)
                rid = sha256(f"{link}:{title}:{pub}".encode()).hexdigest()[:16]
                records.append(
                    PointInTimeRecord(
                        record_id=f"rss-{rid}",
                        event_time=event_t,
                        available_time=avail,
                        ingestion_time=avail + timedelta(seconds=1),
                        payload={
                            "title": title,
                            "polarity": polarity,
                            "source": "rss",
                            "symbol": symbol,
                        },
                    )
                )
        return records

    def _articles_to_records(
        self,
        articles: list[dict[str, Any]],
        start: datetime,
        end: datetime,
        *,
        source: str,
    ) -> list[PointInTimeRecord]:
        out: list[PointInTimeRecord] = []
        start_u = start.astimezone(UTC)
        end_u = end.astimezone(UTC)
        for art in articles:
            published = art.get("publishedAt") or art.get("published_at")
            if not published:
                continue
            try:
                event_t = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            except ValueError:
                continue
            if event_t.tzinfo is None:
                event_t = event_t.replace(tzinfo=UTC)
            avail = event_t + self.publication_lag
            if avail < start_u or avail > end_u:
                continue
            title = str(art.get("title") or "")
            polarity = _title_polarity(title)
            rid = sha256(f"{art.get('url')}:{title}".encode()).hexdigest()[:16]
            out.append(
                PointInTimeRecord(
                    record_id=f"{source}-{rid}",
                    event_time=event_t,
                    available_time=avail,
                    ingestion_time=avail + timedelta(seconds=1),
                    payload={
                        "title": title,
                        "polarity": polarity,
                        "source": source,
                    },
                )
            )
        return out


def _title_polarity(title: str) -> float:
    t = title.lower()
    pos = sum(w in t for w in ("rally", "surge", "gain", "rise", "bull", "high"))
    neg = sum(w in t for w in ("fall", "drop", "loss", "bear", "slump", "low", "crash"))
    if pos == neg == 0:
        return 0.0
    return (pos - neg) / float(pos + neg)
