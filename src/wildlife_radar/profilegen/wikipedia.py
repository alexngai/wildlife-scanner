"""English Wikipedia articles as extraction sources, pinned to a revision.

Article text is CC BY-SA 4.0. It is used only as input to extraction and cached locally under
``data/`` (never committed); profiles keep structured values plus a revision id and character
range, never the sentences (licensing.md).

Wikimedia's robot policy requires a User-Agent with contact information. The default
``wildlife-radar/<version>`` carries none, so operators set ``WILDLIFE_RADAR_USER_AGENT``
(e.g. ``wildlife-radar/0.1 (https://example.org/contact; you@example.org)``) to use this.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict

from wildlife_radar.connectors.base import USER_AGENT_ENV, ConnectorError, RateLimiter, make_client

API_URL = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_LICENSE = "CC-BY-SA-4.0"


class Article(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    revid: int | None = None
    text: str
    license: str = WIKIPEDIA_LICENSE
    retrieved: date | None = None
    source: str = "enwiki"

    @property
    def url(self) -> str:
        base = f"https://en.wikipedia.org/w/index.php?title={self.title.replace(' ', '_')}"
        return f"{base}&oldid={self.revid}" if self.revid else base

    @property
    def citation(self) -> str:
        return f"{self.source}:{self.title}" + (f"@{self.revid}" if self.revid else "")


class WikipediaClient:
    def __init__(
        self,
        cache_dir: Path | str | None = None,
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.client = client or make_client()
        self.limiter = limiter if limiter is not None else RateLimiter(1.0)

    def _cache_path(self, title: str) -> Path | None:
        if self.cache_dir is None:
            return None
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in title)
        return self.cache_dir / f"{safe}.json"

    def fetch(self, title: str, *, refresh: bool = False) -> Article:
        path = self._cache_path(title)
        if path and path.exists() and not refresh:
            return Article.model_validate_json(path.read_text(encoding="utf-8"))
        self.limiter.wait()
        params = {
            "action": "query",
            "prop": "extracts|revisions",
            "explaintext": 1,
            "rvprop": "ids",
            "titles": title,
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
        }
        try:
            resp = self.client.get(API_URL, params=params)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Wikipedia request failed: {exc}") from exc
        if resp.status_code == 403:
            raise ConnectorError(
                "Wikipedia refused the request (HTTP 403). Wikimedia's robot policy requires a "
                f"User-Agent with contact information: set {USER_AGENT_ENV}."
            )
        if resp.status_code >= 400:
            raise ConnectorError(f"Wikipedia returned HTTP {resp.status_code}")
        pages = resp.json().get("query", {}).get("pages") or []
        if not pages or pages[0].get("missing") or not pages[0].get("extract"):
            raise ConnectorError(f"no Wikipedia article {title!r}")
        page = pages[0]
        revisions = page.get("revisions") or [{}]
        article = Article(
            title=page["title"],
            revid=revisions[0].get("revid"),
            text=page["extract"],
            retrieved=date.today(),
        )
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(article.model_dump(mode="json")), encoding="utf-8")
        return article
