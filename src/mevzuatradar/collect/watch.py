"""Resmî Gazete'nin günlük sayısını tarar ve takip edilen düzenlemelerdeki değişiklikleri bildirir.

Akış:
  1. Belirtilen günün içindekiler sayfası açılır.
  2. Başlığında takip edilen bir düzenlemenin adı (eski adları dahil) ve "değişiklik" geçen
     bağlantılar seçilir.
  3. Bulunan değişiklik indirilir, kayıtlar çıkarılır ve elimizdeki güncel metinle doğrulanır:
     "bu değişiklik mevcut metne oturuyor mu?" Oturuyorsa çıkarım büyük olasılıkla doğrudur.
  4. Daha önce bildirilen değişiklikler tekrar bildirilmez (data/watch_state.json).
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import asdict, dataclass, field
import re
from datetime import date, timedelta
from pathlib import Path

from mevzuatradar.collect.rg_finder import RGRef, _decode, find_links, keyword_from_name
from mevzuatradar.extract.amendments import extract_amendments
from mevzuatradar.extract.verify import verify
from mevzuatradar.parse.text_extract import extract_text, from_html


@dataclass
class Hit:
    source_id: str
    source_name: str
    rg_label: str
    url: str
    title: str
    record_count: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    records: list[dict] = field(default_factory=list)
    error: str | None = None


def refs_for_range(gun: date, days: int = 1) -> list[RGRef]:
    """Taranacak günler (bugünden geriye doğru). Mükerrer sayılar da denenir."""
    out = []
    for k in range(days):
        d = gun - timedelta(days=k)
        out.append(RGRef(d.year, d.month, d.day, sayi="?"))
    return out


# Gerçek biçim: "27 Ağustos 2025 Tarihli ve 32999 Sayılı Resmî Gazete".
# Sayfada "Karar Sayısı: 10258" gibi tuzaklar olduğu için desen "Tarihli ve ... Sayılı" bağlamını şart koşar.
SAYI_RE = re.compile(r"Tarihli\s+ve\s+(?P<sayi>\d{4,6})\s+Sayılı", re.I)


def sayi_from_page(html: str) -> str | None:
    """İçindekiler sayfasının başlığındaki Resmî Gazete sayı numarasını okur
    (sayfayı tarihten kurduğumuz için sayı baştan bilinmez)."""
    duz = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html[:8000]))
    m = SAYI_RE.search(duz)
    return m["sayi"] if m else None


def _consolidated_text(source_id: str, raw_dir: str) -> str | None:
    files = glob.glob(f"{raw_dir}/{source_id}/konsolide_*")
    return extract_text(max(files, key=os.path.getmtime)).text if files else None


def scan_day(session, ref: RGRef, sources: list[dict], raw_dir: str = "data/raw",
             timeout: int = 30, robots=None) -> tuple[list[Hit], str | None]:
    """Bir günün içindekiler sayfasını tarar. Dönüş: (bulgular, hata)."""
    if robots is not None and not robots.allowed(ref.index_url):
        return [], "robots.txt izin vermiyor"
    resp = session.get(ref.index_url, timeout=timeout)
    if resp.status_code == 404:
        return [], None                     # o gün sayı yayımlanmamış (hafta sonu/tatil)
    resp.raise_for_status()
    html = _decode(resp)
    sayi = sayi_from_page(html)
    etiket = ref.label.replace("-?", f"-{sayi}") if sayi else ref.label

    hits = []
    for src in sources:
        adlar = [src["name"], *(src.get("former_names") or [])]
        links = find_links(html, ref.index_url, [keyword_from_name(a) for a in adlar])
        for baslik, url in links:
            hit = Hit(src["id"], src["name"], etiket, url, " ".join(baslik.split()))
            try:
                if robots is not None and not robots.allowed(url):
                    hit.error = "robots.txt izin vermiyor"
                else:
                    sayfa = session.get(url, timeout=timeout)
                    sayfa.raise_for_status()
                    kayitlar = [a.to_dict() for a in extract_amendments(from_html(_decode(sayfa)))]
                    hit.record_count = len(kayitlar)
                    kons = _consolidated_text(src["id"], raw_dir)
                    if kons and kayitlar:
                        for rec, res in verify(kayitlar, kons):
                            hit.statuses[res.status] = hit.statuses.get(res.status, 0) + 1
                    hit.records = kayitlar
            except Exception as exc:                       # ağ/ayrıştırma hatası bildirimi engellemesin
                hit.error = f"{type(exc).__name__}: {exc}"
            hits.append(hit)
    return hits, None


def load_state(path: str) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")).get("seen_urls", []))


def save_state(path: str, seen: set[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"seen_urls": sorted(seen)}, ensure_ascii=False, indent=1), encoding="utf-8")


def write_report(path: str, hits: list[Hit]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for h in hits:
            f.write(json.dumps(asdict(h), ensure_ascii=False) + "\n")
