"""HTML ve PDF dosyalarından düz metin çıkarır.

Metin katmanı olmayan (taranmış) PDF'ler 'needs_ocr' olarak işaretlenir; bunlar
ileride layout analizi + VLM modülüne yönlendirilecek.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import CData, Comment, Declaration, Doctype, ProcessingInstruction

# Satır sonu yalnızca bu blok elementlerinden sonra eklenir. Word'den dışa aktarılan
# HTML'de bir paragraf çok sayıda <span>'e bölündüğü için, her metin parçasını ayrı
# satıra koymak "MADDE 1 –" ile "(1) ..." kısmını birbirinden koparır.
BLOCK_TAGS = ["p", "div", "li", "tr", "table", "section", "article",
              "h1", "h2", "h3", "h4", "h5", "h6"]


@dataclass
class ExtractedText:
    text: str
    source_type: str  # html | pdf | txt
    needs_ocr: bool = False
    pages_without_text: int = 0


def _tidy(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]", "", text)  # görünmez karakterler
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    # Yorumlar (Word'ün "[if gte vml 1]" gibi koşullu blokları dahil) ve bildirimler metin değildir.
    # Aşağıdaki boşluk temizleme döngüsü bunları sıradan metne çevirmesin diye ÖNCE atılır.
    for node in list(soup.find_all(string=lambda t: isinstance(t, (Comment, Declaration, Doctype,
                                                                    ProcessingInstruction, CData)))):
        node.extract()
    # Üst simge dipnot işaretleri (<sup>1</sup>) metne karışmasın.
    for sup in soup.find_all("sup"):
        if re.fullmatch(r"\s*\(?\d{1,3}\)?\s*", sup.get_text()):
            sup.decompose()
    # HTML kaynağındaki satır kaydırmaları anlamsızdır: metin içindeki tüm boşlukları tekle.
    for s in list(soup.find_all(string=True)):
        s.replace_with(re.sub(r"\s+", " ", str(s)))
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(BLOCK_TAGS):
        block.insert_after("\n")
    return _tidy(soup.get_text())


def from_pdf(path: Path, min_chars_per_page: int = 50) -> ExtractedText:
    import pdfplumber

    texts, empty = [], 0
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if len(t.strip()) < min_chars_per_page:
                empty += 1
            texts.append(t)
        n = len(pdf.pages)
    return ExtractedText(_tidy("\n".join(texts)), "pdf", needs_ocr=n > 0 and empty / n > 0.5,
                         pages_without_text=empty)


def extract_text(path: str | Path) -> ExtractedText:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return from_pdf(path)
    raw = path.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("windows-1254", errors="replace")  # eski Türkçe sayfalar
    if suffix in (".html", ".htm"):
        return ExtractedText(from_html(content), "html")
    return ExtractedText(_tidy(content), "txt")
