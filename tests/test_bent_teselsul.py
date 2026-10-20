"""Bent teselsülü: araya bent eklenince sonraki bentlerin harfleri kayar.

Resmi metinler bunu "diğer bentler buna göre teselsül ettirilmiştir" notuyla belirtir.
Buradaki ilk iki test, tcmb_ft_ucret_teblig'in 4. maddesinde gerçekten olan iki
değişikliği sırayla yeniden üretir.
"""
import re

from mevzuatradar.version.apply import apply_record

TANIMLAR = """Tanımlar
MADDE 4 – (1) Bu Tebliğde geçen;
a) ATM: Otomatik para çekme cihazlarını,
b) Banka: Bankaları,
c) Birlikler: Birlikleri,
ç) EFT işlemleri: EFT ile yapılan ödemeleri,
d) Finansal tüketici: Tüketiciyi,
e) Hesap: Mevduat hesabını,
f) Kalıcı veri saklayıcısı: Kalıcı veri saklayıcısını,
ifade eder.
Ücretler
MADDE 5 – (1) Ücretler şunlardır;
a) Ücret: Her türlü parasal tutarı,
ifade eder.
"""

BENT = re.compile(r"^(?P<harf>[a-zçğıöşü]{1,3})\)\s*(?P<ad>.*)$")


def bentler(metin: str, madde: str = "MADDE 4") -> list[tuple[str, str]]:
    """İstenen maddenin bentlerini (harf, ilk kelime) olarak sırayla verir."""
    icinde, out = False, []
    for satir in metin.split("\n"):
        if satir.startswith("MADDE "):
            icinde = satir.startswith(madde)
            continue
        if icinde and (m := BENT.match(satir.strip())):
            out.append((m["harf"], m["ad"].split(":")[0]))
    return out


def test_araya_bent_eklenince_sonrakiler_kayar():
    """31/12/2020: (ç) bendinden sonra FAST eklenmiş, diğerleri teselsül ettirilmiş."""
    yeni, res = apply_record(TANIMLAR, {
        "operation": "BIRIM_EKLE", "unit": "bent", "insert_after": "ç",
        "new_text": "d) FAST işlemleri: FAST ile yapılan ödemeleri,",
        "location": {"madde": "4", "fikra": 1}})
    assert res.status == "uygulandi"
    assert bentler(yeni) == [
        ("a", "ATM"), ("b", "Banka"), ("c", "Birlikler"), ("ç", "EFT işlemleri"),
        ("d", "FAST işlemleri"), ("e", "Finansal tüketici"), ("f", "Hesap"),
        ("g", "Kalıcı veri saklayıcısı"),
    ]


def test_iki_ekleme_ustuste_resmi_metni_uretir():
    """13/11/2021 değişikliği "(f) bendinden sonra" diyor. İlk ekleme teselsül
    ettirilmemişse (f) yanlış bende denk gelir ve hata birikir."""
    ara, _ = apply_record(TANIMLAR, {
        "operation": "BIRIM_EKLE", "unit": "bent", "insert_after": "ç",
        "new_text": "d) FAST işlemleri: FAST ile yapılan ödemeleri,",
        "location": {"madde": "4", "fikra": 1}})
    yeni, res = apply_record(ara, {
        "operation": "BIRIM_EKLE", "unit": "bent", "insert_after": "f",
        "new_text": "g) Hesaptan hesaba işyeri ödemeleri: İşyeri ödemelerini,",
        "location": {"madde": "4", "fikra": 1}})
    assert res.status == "uygulandi"
    # Resmi konsolide metindeki sıra ve harfler.
    assert bentler(yeni)[-4:] == [
        ("e", "Finansal tüketici"), ("f", "Hesap"),
        ("g", "Hesaptan hesaba işyeri ödemeleri"), ("ğ", "Kalıcı veri saklayıcısı"),
    ]
    assert [h for h, _ in bentler(yeni)] == sorted(
        [h for h, _ in bentler(yeni)], key="abcçdefgğhıijk".index)


def test_teselsul_baska_maddeye_dokunmaz():
    yeni, _ = apply_record(TANIMLAR, {
        "operation": "BIRIM_EKLE", "unit": "bent", "insert_after": "a",
        "new_text": "b) Araç: Araçları,", "location": {"madde": "4", "fikra": 1}})
    assert bentler(yeni, "MADDE 5") == [("a", "Ücret")]


def test_sona_eklenen_bent_kaydirma_yapmaz():
    yeni, res = apply_record(TANIMLAR, {
        "operation": "BIRIM_EKLE", "unit": "bent", "insert_after": "f",
        "new_text": "g) Onay: Açık kabulü,", "location": {"madde": "4", "fikra": 1}})
    assert res.status == "uygulandi"
    assert bentler(yeni)[-2:] == [("f", "Kalıcı veri saklayıcısı"), ("g", "Onay")]


def test_cok_harfli_bent_taban_harfi_kayar():
    metin = ("MADDE 9 – (1) Şunlar;\n"
             "aa) Birinci: Birinciyi,\n"
             "bb) İkinci: İkinciyi,\n"
             "ifade eder.\n")
    yeni, res = apply_record(metin, {
        "operation": "BIRIM_EKLE", "unit": "bent", "insert_after": "aa",
        "new_text": "bb) Araya: Arayı,", "location": {"madde": "9", "fikra": 1}})
    assert res.status == "uygulandi"
    assert bentler(yeni, "MADDE 9") == [("aa", "Birinci"), ("bb", "Araya"), ("cc", "İkinci")]


def test_alfabe_tukenirse_bent_oldugu_gibi_kalir():
    """Uydurulmuş harf yazmaktansa kaydırmayı yapmamak yeğlenir; çökmemesi yeter."""
    metin = ("MADDE 9 – (1) Şunlar;\n"
             "y) Yetki: Yetkiyi,\n"
             "z) Zorunluluk: Zorunluluğu,\n"
             "ifade eder.\n")
    yeni, res = apply_record(metin, {
        "operation": "BIRIM_EKLE", "unit": "bent", "insert_after": "y",
        "new_text": "z) Zabıt: Zabtı,", "location": {"madde": "9", "fikra": 1}})
    assert res.status == "uygulandi"
    assert "Zorunluluk" in yeni and "Zabıt" in yeni


def test_fikra_eklemede_teselsul_calismaz():
    metin = "MADDE 5 – (1) Birinci fıkra.\n(2) İkinci fıkra.\na) Bent: Bendi,\n"
    yeni, res = apply_record(metin, {
        "operation": "BIRIM_EKLE", "unit": "fikra",
        "new_text": "(3) Üçüncü fıkra.", "location": {"madde": "5"}})
    assert res.status == "uygulandi"
    assert "a) Bent" in yeni  # bent harfi fıkra eklemesinden etkilenmez
