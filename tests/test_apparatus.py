"""Konsolide metinlerin dipnot aparatı: kırpma ve yayım tablosu."""
from mevzuatradar.parse.apparatus import strip_apparatus, yayim_tablosu

# tcmb_ft_ucret_teblig konsolide metninin sonu (olduğu gibi).
TEBLIG_SONU = """ Yürütme
 MADDE 17 – (1) Bu Tebliğ hükümlerini Türkiye Cumhuriyet Merkez Bankası Başkanı yürütür.
 ___
 (1) 31/12/2020 tarihli ve 31351 sayılı Resmî Gazete’de yayımlanan değişiklik ile Yönetmeliğin 4 üncü maddesinin birinci fıkrasına (ç) bendinden sonra gelmek üzere bent eklenmiş ve diğer bentler buna göre teselsül ettirilmiştir.
 (2) 13/11/2021 tarihli ve 31658 sayılı Resmî Gazete’de yayımlanan değişiklikle fıkraya (f) bendinden sonra gelmek üzere (g) bendi eklenmiş ve diğer bentler buna göre teselsül ettirilmiştir.
 (3) Bu değişiklik 1/12/2023 tarihinde yürürlüğe girer.
 (4) Bu değişiklik 4/1/2024 tarihinde yürürlüğe girer.

 Eki için tıklayınız.

 Tebliğin Yayımlandığı Resmî Gazete’nin

 Tarihi
 Sayısı

 7/3/2020
 31061

 Tebliğde Değişiklik Yapan Tebliğlerin Yayımlandığı Resmî Gazetelerin

 Tarihi
 Sayısı

 1.
 31/12/2020
 31351

 2.
 9/8/2021
 31563

 3.
 13/11/2021
 31658

 4.
 25/11/2023
 32380

 5.
 22/12/2023
 32407
"""


def test_kirpma_maddeyi_birakir_aparati_atar():
    kirpik = strip_apparatus(TEBLIG_SONU)
    assert kirpik.endswith("Merkez Bankası Başkanı yürütür.")
    assert "Eki için tıklayınız" not in kirpik
    assert "31351" not in kirpik


def test_kirpma_isaret_yoksa_metni_degistirmez():
    t = "MADDE 5 – (1) Kuruluşlar bildirim yapar. (2) Süre bir aydır."
    assert strip_apparatus(t) == t


def test_tablo_ilk_yayimi_okur():
    ilk, _ = yayim_tablosu(TEBLIG_SONU)
    assert ilk is not None
    assert ilk.label == "RG-7/3/2020-31061"


def test_tablo_degisiklikleri_sirayla_okur():
    _, deg = yayim_tablosu(TEBLIG_SONU)
    assert [d.label for d in deg] == [
        "RG-31/12/2020-31351",
        "RG-9/8/2021-31563",
        "RG-13/11/2021-31658",
        "RG-25/11/2023-32380",
        "RG-22/12/2023-32407",
    ]


def test_tablo_madde_ici_notla_celisirse_tablo_yayimi_verir():
    """Asıl bulgu: madde içi not RG-1/12/2023-32386 (yürürlük) derken tablo 25/11/2023-32380
    (yayım) diyor. Kaynak kendi kendisiyle çelişiyor; tablo yayımı bildirir."""
    _, deg = yayim_tablosu(TEBLIG_SONU)
    etiketler = [d.label for d in deg]
    assert "RG-25/11/2023-32380" in etiketler
    assert "RG-1/12/2023-32386" not in etiketler


def test_tablo_disindaki_tarihler_toplanmaz():
    """Tablodan sonra ek metni gelebilir; sıra numarası kopunca okuma durur."""
    metin = TEBLIG_SONU + """
 EK-1
 Bilgi Formu
 7. 10/2/2020 31035
 BDDK Yetki Tarihi 1/1/2019 12345
"""
    _, deg = yayim_tablosu(metin)
    assert len(deg) == 5


def test_tablo_yoksa_bos_doner():
    ilk, deg = yayim_tablosu("MADDE 1 – (1) Bu Yönetmelik ... yürürlüğe girer.")
    assert ilk is None and deg == []


def test_mukerrer_sayi_tanninir():
    metin = """ Yönetmelikte Değişiklik Yapan Yönetmeliklerin Yayımlandığı Resmî Gazetelerin

 Tarihi
 Sayısı

 1.
 31/12/2020
 31351 Mükerrer
"""
    _, deg = yayim_tablosu(metin)
    assert len(deg) == 1 and deg[0].mukerrer == 1
