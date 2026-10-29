"""Polite HTTP client shared by every adapter.

* Clear User-Agent naming the tool.
* At most 1 request/second per host (blocking wait, thread-safe).
* Short-lived response cache so repeated reads in one refresh do not re-hit a site.
* Detects Cloudflare / Turnstile challenges and raises ``SourceBlocked`` instead of
  retrying or trying to get round them.

Tests inject an ``httpx.MockTransport`` so CI never touches the network.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from ..config import settings


class SourceBlocked(Exception):
    """The site answered with a bot challenge or a hard block (403/429/Turnstile)."""


class SourceUnavailable(Exception):
    """Network failure or 5xx after retries."""


# Text that only appears on a challenge / block page itself.
CHALLENGE_MARKERS = (
    "<title>just a moment",
    "cf_chl_opt",
    "cf-chl-widget",
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "verify you are human",
)
# Text that can also sit on a normal page: Cloudflare adds a "challenge-platform" script to
# ordinary pages and sites embed a Turnstile widget on their own login forms. Only counted
# as a challenge when the status code is a refusal (403/429/503).
WEAK_MARKERS = ("challenge-platform", "cf-turnstile", "turnstile", "just a moment")


def challenge_evidence(resp: httpx.Response) -> str | None:
    """Why this response is a bot challenge / block, or None if it is a normal answer."""
    refused = resp.status_code in (403, 429, 503)
    cf = "cloudflare" in resp.headers.get("server", "").lower() or "cf-ray" in resp.headers
    if resp.headers.get("cf-mitigated", "").lower() == "challenge":
        return "Cloudflare challenge (cf-mitigated header)"
    ctype = resp.headers.get("content-type", "")
    head = resp.text[:6000].lower() if ("html" in ctype or not ctype) else ""
    strong = next((m for m in CHALLENGE_MARKERS if m in head), None)
    if strong:
        return f"challenge page ({strong!r})"
    if refused:
        weak = next((m for m in WEAK_MARKERS if m in head), None)
        if weak:
            return f"challenge page ({weak!r})"
        if cf:
            return "refused by Cloudflare"
    return None


def looks_like_challenge(resp: httpx.Response) -> bool:
    return challenge_evidence(resp) is not None


def _server(resp: httpx.Response) -> str:
    sv = resp.headers.get("server", "")
    return f", server {sv}" if sv else ""


@dataclass
class CachedResponse:
    at: float
    status: int
    text: str
    headers: dict


class PoliteClient:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        min_interval: float | None = None,
        cache_seconds: float = 30.0,
        sleep=time.sleep,
        retries: int = 2,
    ):
        self._client = httpx.Client(
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en-ZA,en;q=0.8"},
            timeout=httpx.Timeout(20.0),
            follow_redirects=True,
            transport=transport,
        )
        self.min_interval = settings.min_host_interval if min_interval is None else min_interval
        self.cache_seconds = cache_seconds
        self._sleep = sleep
        self._retries = retries
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}
        self._cache: dict[str, CachedResponse] = {}
        self.request_log: list[str] = []  # for tests and the Sources screen
        self.on_response = None  # optional callback(url, status, text) for raw-payload capture

    def _host_lock(self, host: str) -> threading.Lock:
        with self._lock:
            return self._host_locks.setdefault(host, threading.Lock())

    def _throttle(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = time.monotonic()

    def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        use_cache: bool = True,
    ) -> httpx.Response:
        key = str(httpx.URL(url, params=params)) + "|" + repr(sorted((headers or {}).items()))
        if use_cache and self.cache_seconds > 0:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit.at < self.cache_seconds:
                return httpx.Response(hit.status, text=hit.text, headers=hit.headers)
        host = urlsplit(url).netloc
        attempt = 0
        with self._host_lock(host):
            while True:
                self._throttle(host)
                self.request_log.append(key.split("|")[0])
                try:
                    resp = self._client.get(url, params=params, headers=headers)
                except httpx.HTTPError as exc:
                    if attempt >= self._retries:
                        raise SourceUnavailable(f"{host}: {exc}") from exc
                    attempt += 1
                    self._sleep(2**attempt)
                    continue
                why = challenge_evidence(resp)
                if why:
                    raise SourceBlocked(f"{host}: {why}, HTTP {resp.status_code}{_server(resp)} — "
                                        f"{urlsplit(url).path or '/'}")
                if resp.status_code in (401, 403):
                    raise SourceBlocked(f"{host}: HTTP {resp.status_code}{_server(resp)} (access refused) — "
                                        f"{urlsplit(url).path or '/'}")
                if resp.status_code == 429:
                    raise SourceBlocked(f"{host}: rate limited (HTTP 429)")
                if resp.status_code >= 500 and attempt < self._retries:
                    attempt += 1
                    self._sleep(2**attempt)
                    continue
                break
        if self.on_response is not None:
            try:
                self.on_response(str(resp.request.url), resp.status_code, resp.text)
            except Exception:
                pass
        if resp.status_code < 400 and use_cache:
            self._cache[key] = CachedResponse(
                time.monotonic(), resp.status_code, resp.text, {"content-type": resp.headers.get("content-type", "")}
            )
        return resp

    def get_text(self, url: str, **kw) -> str:
        resp = self.get(url, **kw)
        if resp.status_code >= 400:
            raise SourceUnavailable(f"{url}: HTTP {resp.status_code}")
        return resp.text

    def get_json(self, url: str, **kw):
        resp = self.get(url, **kw)
        if resp.status_code >= 400:
            raise SourceUnavailable(f"{url}: HTTP {resp.status_code}")
        return resp.json()

    def close(self) -> None:
        self._client.close()
