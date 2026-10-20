"""Konsolide metinlerin dipnot aparatı: kırpma ve yayım tablosu okuma."""
from __future__ import annotations

import re

# Dipnot aparatının başladığı yeri gösteren işaretler.
# '___' : dipnotların başı. 'Eki için tıklayınız' : ek bağlantısı.
# 'Yayımlandığı Resmî Gazete' : yayım tabloları.
ISARETLER = re.compile(
    r"(?m)^[ \t]*_{3,}[ \t]*$"
    r"|Eki\s+için\s+tıklayınız"
    r"|Yayımlandı[ğg]ı\s+Resm[îi]\s*Gazete",
)

# "Tebliğin / Yönetmeliğin Yayımlandığı Resmî Gazete'nin" — ilk yayım tablosu.
# Çoğul biçim ("Tebliğlerin", "Yönetmeliklerin") değişiklik tablosuna aittir, buraya uymaz.
ORIJINAL_BASLIK = re.compile(
    r"(?:Yönetmeli[ğg]in|Tebli[ğg]in|Kararın|Kanunun)\s+Yayımlandı[ğg]ı\s+Resm[îi]\s*Gazete",
    re.I,
)
DEGISIKLIK_BASLIK = re.compile(
    r"Değişiklik\s+Yapan\s+[^\n]{0,80}?Yayımlandı[ğg]ı\s+Resm[îi]\s*Gazete",
    re.I,
)

_MUK = r"(?:[ \t]*(?:(?P<mk>\d)[ \t]*\.[ \t]*)?(?P<muk>Mükerrer))?"
# İlk yayım: "Tarihi / Sayısı" başlıklarından sonra tek bir tarih-sayı çifti.
ORIJINAL_CIFT = re.compile(rf"(?P<g>\d{{1,2}})/(?P<a>\d{{1,2}})/(?P<y>\d{{4}})\s+(?P<sayi>\d{{4,6}}){_MUK}")
# Değişiklik satırı: sıra numarası, tarih, sayı. Sıra numarası şartı tabloyu doğal olarak
# sınırlar; ekler içindeki tarihler yanlışlıkla toplanmaz.
DEGISIKLIK_SATIRI = re.compile(
    rf"(?P<sira>\d{{1,3}})[ \t]*\.\s+(?P<g>\d{{1,2}})/(?P<a>\d{{1,2}})/(?P<y>\d{{4}})\s+(?P<sayi>\d{{4,6}}){_MUK}"
)


def strip_apparatus(text: str) -> str:
    """Metni, dipnot aparatının başladığı yerden keser.

    Madde metinlerine uygulanır: son madde aparatı yutmuşsa kırpılır, diğerleri
    değişmeden döner. İşaret yoksa metin aynen döner.
    """
    m = ISARETLER.search(text)
    return text[: m.start()].rstrip() if m else text


def _ref(m: re.Match):
    from mevzuatradar.collect.rg_finder import RGRef

    muk = (int(m["mk"]) if m["mk"] else 1) if m["muk"] else 0
    return RGRef(int(m["y"]), int(m["a"]), int(m["g"]), m["sayi"], muk)


def yayim_tablosu(text: str):
    """Konsolide metnin yayım tablolarını okur.

    (ilk_yayim, degisiklikler) döndürür; ilk_yayim None olabilir, degisiklikler boş olabilir.
    Bu tablo düzenlemenin kendi beyanıdır ve YAYIM tarihlerini verir; madde içi notlar
    bazen yürürlük tarihi taşıdığı için çapraz kontrolde ölçüt olarak kullanılır.
    """
    ilk = None
    o = ORIJINAL_BASLIK.search(text)
    d = DEGISIKLIK_BASLIK.search(text)
    if o:
        son = d.start() if d and d.start() > o.start() else len(text)
        c = ORIJINAL_CIFT.search(text, o.end(), son)
        if c:
            ilk = _ref(c)
    degisiklikler = []
    if d:
        beklenen = 1
        for m in DEGISIKLIK_SATIRI.finditer(text, d.end()):
            if int(m["sira"]) != beklenen:
                break  # sıra kopunca tablo bitmiştir; sonrası ek metni olabilir
            degisiklikler.append(_ref(m))
            beklenen += 1
    return ilk, degisiklikler
