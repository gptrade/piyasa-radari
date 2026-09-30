"""HTTP yardımcıları: nazik User-Agent, zaman aşımı, tekrar deneme."""
from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger("radar.http")

DEFAULT_UA = "Mozilla/5.0 (compatible; piyasa-radari/1.0; +https://github.com)"
# SEC, iletişim e-postası içeren bir User-Agent ister: SEC_USER_AGENT secret'ında tanımla.
SEC_UA = os.environ.get("SEC_USER_AGENT") or "piyasa-radari research bot (set SEC_USER_AGENT)"

_session = requests.Session()

# Bu çalıştırmada başarısız olan istekler (panelde "Kaynak durumu" altında gösterilir).
FAILURES: list[tuple[str, str]] = []


def note_failure(url: str, reason: str) -> None:
    from urllib.parse import urlparse
    FAILURES.append((urlparse(url).netloc or url[:60], reason))


def get(url: str, *, headers: dict | None = None, params: dict | None = None,
        timeout: int = 20, retries: int = 2) -> requests.Response | None:
    return _request("GET", url, headers=headers, params=params, timeout=timeout, retries=retries)


def post(url: str, *, json: dict | None = None, headers: dict | None = None,
         timeout: int = 30, retries: int = 2) -> requests.Response | None:
    return _request("POST", url, headers=headers, json=json, timeout=timeout, retries=retries)


def _request(method: str, url: str, retries: int, **kw) -> requests.Response | None:
    headers = {"User-Agent": DEFAULT_UA, "Accept-Language": "tr,en;q=0.8"}
    headers.update(kw.pop("headers", None) or {})
    for attempt in range(retries + 1):
        try:
            r = _session.request(method, url, headers=headers, **kw)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            log.warning("%s %s -> HTTP %s", method, url[:120], r.status_code)
            note_failure(url, f"HTTP {r.status_code}")
            return None
        except requests.RequestException as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            log.warning("%s %s -> %s", method, url[:120], e)
            note_failure(url, type(e).__name__)
    return None
