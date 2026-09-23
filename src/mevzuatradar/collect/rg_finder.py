"""Konsolide metindeki değişiklik notlarından (ör. "RG-25/9/2020-31255") yola çıkarak
değişiklik yönetmeliklerinin Resmî Gazete bağlantılarını otomatik bulur.

Yöntem: her tarih için Resmî Gazete'nin günlük içindekiler sayfası açılır
(eskiler/YYYY/MM/YYYYMMDD.htm, mükerrer sayılar için ...M1.htm) ve başlığında hem
düzenlemenin adı hem de "değişiklik" geçen bağlantı seçilir.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

REF_RE = re.compile(
    r"(?P<g>\d{1,2})/(?P<a>\d{1,2})/(?P<y>\d{4})-(?P<sayi>\d+)"
    r"(?:\s*(?:(?P<mk>\d)\s*\.\s*)?(?P<muk>Mükerrer))?"
)
RG_BASE = "https://www.resmigazete.gov.tr/eskiler"


@dataclass(frozen=True, order=True)
class RGRef:
    year: int
    month: int
    day: int
    sayi: str
    mukerrer: int = 0  # 0: asıl sayı, 1: mükerrer, 2: 2. mükerrer ...

    @property
    def label(self) -> str:
        m = f" {self.mukerrer}. Mükerrer" if self.mukerrer > 1 else (" Mükerrer" if self.mukerrer else "")
        return f"RG-{self.day}/{self.month}/{self.year}-{self.sayi}{m}"

    @property
    def index_url(self) -> str:
        suffix = f"M{self.mukerrer}" if self.mukerrer else ""
        return f"{RG_BASE}/{self.year}/{self.month:02d}/{self.year}{self.month:02d}{self.day:02d}{suffix}.htm"


def parse_ref(source: str) -> RGRef | None:
    m = REF_RE.search(source)
    if not m:
        return None
    muk = (int(m["mk"]) if m["mk"] else 1) if m["muk"] else 0
    return RGRef(int(m["y"]), int(m["a"]), int(m["g"]), m["sayi"], muk)


def tr_upper(text: str) -> str:
    """Türkçe'ye uygun büyük harf dönüşümü (Python'un upper() i -> I yapar, İ yapmaz)."""
    return text.replace("i", "İ").replace("ı", "I").upper()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", tr_upper(text)).strip()


def keyword_from_name(name: str) -> str:
    """'X Hakkında Yönetmelik (2023)' -> 'X Hakkında'. Başlıktaki çekim eklerinden bağımsız eşleşme sağlar."""
    name = re.sub(r"\s*\(.*?\)", "", name).strip()
    return re.sub(r"\s+(Yönetmelik|Tebliğ|Yönetmeliği|Tebliği)$", "", name)


def find_links(html: str, base_url: str, keyword: str | list[str]) -> list[tuple[str, str]]:
    """Başlığında düzenlemenin adı (veya eski adlarından biri) ve 'değişiklik' geçen bağlantılar."""
    soup = BeautifulSoup(html, "html.parser")
    keys = [_norm(k) for k in ([keyword] if isinstance(keyword, str) else keyword)]
    hits = []
    for a in soup.find_all("a", href=True):
        text = _norm(a.get_text(" "))
        if any(key in text for key in keys) and "DEĞİŞİKLİK" in text:
            hits.append((a.get_text(" ").strip(" –-\n\t"), urljoin(base_url, a["href"])))
    return hits


def _decode(resp: requests.Response) -> str:
    try:
        return resp.content.decode("utf-8")
    except UnicodeDecodeError:
        return resp.content.decode("windows-1254", errors="replace")  # eski sayfalar


def collect_refs(sources: list[str]) -> list[RGRef]:
    return sorted({r for s in sources if (r := parse_ref(s))})


def find_amendment_urls(session: requests.Session, refs: list[RGRef], keyword: str | list[str],
                        delay: float = 3, timeout: int = 30,
                        robots=None) -> list[tuple[RGRef, list[tuple[str, str]], str | None]]:
    """Her referans için (ref, bulunan bağlantılar, hata mesajı) döndürür.
    robots verilirse (RobotsChecker), izin verilmeyen sayfalar istenmez."""
    from mevzuatradar.collect.polite import get_with_retry

    results, requested = [], 0
    for ref in refs:
        if robots is not None and not robots.allowed(ref.index_url):
            results.append((ref, [], "robots.txt bu sayfaya izin vermiyor"))
            continue
        if requested:
            time.sleep(delay)
        requested += 1
        try:
            resp = get_with_retry(session, ref.index_url, timeout=timeout)
            results.append((ref, find_links(_decode(resp), ref.index_url, keyword), None))
        except requests.RequestException as exc:
            results.append((ref, [], str(exc)))
    return results


def consolidated_annotation_sources(consolidated_path: str | Path) -> list[str]:
    from mevzuatradar.parse.structure import parse_structure
    from mevzuatradar.parse.text_extract import extract_text

    doc = parse_structure(extract_text(consolidated_path).text)
    out = []
    for m in doc.maddeler:
        units = [m] + m.fikralar
        units += [b for f in m.fikralar for b in f.bentler]
        units += [a for f in m.fikralar for b in f.bentler for a in b.alt_bentler]
        out.extend(ann.source for u in units for ann in u.annotations if ann.type != "Dipnot")
    # Dipnot tanımları: "1/8/2009 tarihli ve 27306 sayılı (Mükerrer) Resmî Gazete’de ..."
    for fn in doc.footnotes.values():
        m = re.match(r"(\d{1,2}/\d{1,2}/\d{4})\s+tarihli\s+ve\s+(\d+)\s+sayılı\s*(\(?\s*(?:\d\.\s*)?Mükerrer)?", fn)
        if m:
            out.append(f"RG-{m.group(1)}-{m.group(2)}" + (" Mükerrer" if m.group(3) else ""))
    return out


# "10/3/2007 tarihli ve 26458 sayılı Resmî Gazete'de yayımlanan <ad> Yönetmeliğin ..."
ORIGINAL_REF = re.compile(
    r"(?P<tarih>\d{1,2}/\d{1,2}/\d{4})\s+tarihli\s+ve\s+(?P<sayi>\d{4,6})\s+sayılı\s+"
    # devam ileriye bakışla okunur: pencere metni tüketmesin, sonraki atıflar da görülebilsin
    r"Resm[îi]\s*Gazete[’'`]?de\s+yayımlanan\s*(?=(?P<devam>.{0,160}))", re.S)


def original_ref(amendment_text: str, name: str) -> RGRef | None:
    """Değişiklik yönetmeliğinin ilk maddesinden, DEĞİŞTİRİLEN düzenlemenin ilk yayım tarihini bulur.
    Metinde birden çok atıf olabilir (ör. dayanak kanun); atfın ardından düzenlemenin adı geçen seçilir."""
    ipucu = _norm(" ".join(keyword_from_name(name).split()[:3]))
    ilk = None
    for m in ORIGINAL_REF.finditer(amendment_text):
        ref = parse_ref(f"RG-{m['tarih']}-{m['sayi']}")
        if ref is None:
            continue
        ilk = ilk or ref
        # Pencere bir sonraki atfa taşabilir; oradaki ad bu atfa ait değildir, kes.
        devam = re.split(r"\d{1,2}/\d{1,2}/\d{4}\s+tarihli", m["devam"])[0]
        if ipucu and ipucu in _norm(devam):
            return ref
    return ilk


def find_original_link(html: str, base_url: str, keyword: str | list[str]) -> list[tuple[str, str]]:
    """İçindekiler sayfasında düzenlemenin İLK yayımını arar: adı geçen ama 'değişiklik' geçmeyen bağlantı."""
    soup = BeautifulSoup(html, "html.parser")
    keys = [_norm(k) for k in ([keyword] if isinstance(keyword, str) else keyword)]
    hits = []
    for a in soup.find_all("a", href=True):
        text = _norm(a.get_text(" "))
        if any(key in text for key in keys) and "DEĞİŞİKLİK" not in text and "YÜRÜRLÜKTEN" not in text:
            hits.append((a.get_text(" ", strip=True), urljoin(base_url, a["href"])))
    return hits
