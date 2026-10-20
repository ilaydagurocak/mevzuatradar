"""Nottaki tarih yürürlük tarihi olduğunda değişikliğin geriye doğru bulunması.

Gerçek vaka: Finansal Tüketicilerden Alınacak Ücretlere İlişkin Tebliğ (Sayı: 2020/7).
Konsolide metin '(Mülga üçüncü cümle:RG-1/12/2023-32386)' der. 1/12/2023 sayfası açılır
ama o gün bu tebliği değiştiren bir şey yayımlanmamıştır: değişiklik 25/11/2023-32380'de
yayımlanıp 1/12/2023'te yürürlüğe girmiştir.
"""
import pytest
import requests

from mevzuatradar.collect import polite
from mevzuatradar.collect.rg_finder import (
    find_amendment_urls,
    parse_ref,
    sayi_from_index,
)

ANAHTAR = "Finansal Tüketicilerden Alınacak Ücretlere İlişkin"

SAYFALAR = {
    # Nottaki gün: sayfa var, ama ilgili başlık yok (başka tebliğler var).
    "https://www.resmigazete.gov.tr/eskiler/2023/12/20231201.htm": (
        "<html><body><p>1 Aralık 2023 CUMA &nbsp; Sayı : 32386</p>"
        "<a href='20231201-5.htm'>Altın Hesaplarından Türk Lirası Mevduat ve Katılma "
        "Hesaplarına Dönüşümün Desteklenmesi Hakkında Tebliğ (Sayı: 2021/16)’de "
        "Değişiklik Yapılmasına Dair Tebliğ</a></body></html>"
    ),
    # Gerçek yayım günü.
    "https://www.resmigazete.gov.tr/eskiler/2023/11/20231125.htm": (
        "<html><body><p>25 Kasım 2023 CUMARTESİ &nbsp; Sayı : 32380</p>"
        "<a href='20231125-31.htm'>Finansal Tüketicilerden Alınacak Ücretlere İlişkin "
        "Usûl ve Esaslar Hakkında Tebliğ (Sayı: 2020/7)’de Değişiklik Yapılmasına Dair "
        "Tebliğ (Sayı: 2023/33)</a></body></html>"
    ),
}


class _Resp:
    def __init__(self, html: str) -> None:
        self.content = html.encode("utf-8")


@pytest.fixture
def sahte_site(monkeypatch):
    istenen = []

    def fake_get(session, url, timeout=30):
        istenen.append(url)
        if url not in SAYFALAR:
            raise requests.RequestException("404")
        return _Resp(SAYFALAR[url])

    monkeypatch.setattr(polite, "get_with_retry", fake_get)
    return istenen


def test_geri_gun_kapaliysa_bulunamaz(sahte_site):
    (ref, links, err) = find_amendment_urls(
        None, [parse_ref("RG-1/12/2023-32386")], ANAHTAR, delay=0
    )[0]
    assert links == []
    assert err is None
    assert ref.label == "RG-1/12/2023-32386"


def test_geri_tarama_gercek_yayimi_bulur(sahte_site):
    (ref, links, err) = find_amendment_urls(
        None, [parse_ref("RG-1/12/2023-32386")], ANAHTAR, delay=0, geri_gun=10
    )[0]
    assert err is None
    assert len(links) == 1
    assert links[0][1].endswith("/2023/11/20231125-31.htm")
    # Sayı, sayfanın kendi başlığından düzeltilir: nottaki 32386 değil 32380.
    assert ref.label == "RG-25/11/2023-32380"


def test_geri_tarama_pencereyi_asmaz(sahte_site):
    (ref, links, _) = find_amendment_urls(
        None, [parse_ref("RG-1/12/2023-32386")], ANAHTAR, delay=0, geri_gun=3
    )[0]
    assert links == []  # 25 Kasım, 3 günlük pencerenin dışında
    assert ref.label == "RG-1/12/2023-32386"


def test_sayi_basliktan_okunur_teblig_sayisiyla_karismaz():
    html = (
        "<html><body><p>25 Kasım 2023 CUMARTESİ Sayı : 32380</p>"
        "<a href='x'>Tebliğ (Sayı: 2023/33)</a></body></html>"
    )
    assert sayi_from_index(html) == "32380"


def test_sayi_yeni_bicimde_de_okunur():
    html = "<html><body><p>27 Ağustos 2025 Tarihli ve 32999 Sayılı Resmî Gazete</p></body></html>"
    assert sayi_from_index(html) == "32999"
