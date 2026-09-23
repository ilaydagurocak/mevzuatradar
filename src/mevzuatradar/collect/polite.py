"""Sitelere saygılı erişim: robots.txt kontrolü ve geri çekilmeli (backoff) yeniden deneme.

robots.txt yorumu RFC 9309'u izler:
- 2xx: kurallar okunur ve uygulanır.
- 4xx (ör. 404): site kural yayınlamamıştır; erişime izin verilir.
- 5xx veya ulaşılamıyor: sitenin tamamı kısıtlı kabul edilir (güvenli taraf).
"""
from __future__ import annotations

import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests


class RobotsChecker:
    def __init__(self, session: requests.Session, user_agent: str, timeout: int = 30):
        self.session, self.user_agent, self.timeout = session, user_agent, timeout
        self._cache: dict[str, RobotFileParser] = {}
        self.notes: dict[str, str] = {}  # site -> robots.txt durumu (raporlama için)

    def _load(self, base: str) -> RobotFileParser:
        rp = RobotFileParser()
        try:
            r = self.session.get(f"{base}/robots.txt", timeout=self.timeout)
            if r.status_code >= 500:
                rp.disallow_all = True
                self.notes[base] = f"robots.txt sunucu hatası ({r.status_code}): erişim kısıtlı sayıldı"
            elif r.status_code >= 400:
                rp.allow_all = True
                self.notes[base] = f"robots.txt yok ({r.status_code}): erişim serbest"
            else:
                rp.parse(r.text.splitlines())
                self.notes[base] = "robots.txt okundu ve uygulanıyor"
        except requests.RequestException as exc:
            rp.disallow_all = True
            self.notes[base] = f"robots.txt'ye ulaşılamadı ({type(exc).__name__}): erişim kısıtlı sayıldı"
        return rp

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._cache:
            self._cache[base] = self._load(base)
        return self._cache[base].can_fetch(self.user_agent, url)


def get_with_retry(session: requests.Session, url: str, timeout: int = 30,
                   retries: int = 2, backoff: float = 10.0) -> requests.Response:
    """Zaman aşımı, bağlantı hatası, 429 ve 503 yanıtlarında artan sürelerle bekleyip yeniden dener."""
    for attempt in range(retries + 1):
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code in (429, 503) and attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        except (requests.Timeout, requests.ConnectionError):
            if attempt == retries:
                raise
            time.sleep(backoff * (attempt + 1))
    raise requests.RequestException(f"{url}: yeniden denemeler tükendi")


def use_system_certs() -> bool:
    """Sistemin sertifika deposunu kullan (kurumsal ağlarda TLS hatalarını önler).
    truststore kurulu değilse sessizce normal sertifikalarla devam edilir."""
    try:
        import truststore
    except ImportError:
        return False
    truststore.inject_into_ssl()
    return True
