from pathlib import Path

from mevzuatradar.extract.amendments import ORDINALS, extract_amendments, extract_from_article
from mevzuatradar.extract.evaluate import evaluate, load_jsonl

SAMPLES = Path(__file__).parent.parent / "data/samples"


def test_sira_sayilari():
    assert ORDINALS["birinci"] == 1
    assert ORDINALS["onuncu"] == 10
    assert ORDINALS["on birinci"] == 11
    assert ORDINALS["yirmi üçüncü"] == 23


def test_ibare_degisikligi_ve_konum():
    text = ("MADDE 1 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Deneme Hakkında "
            "Yönetmeliğin 12 nci maddesinin on birinci fıkrasının (ç) bendinde yer alan "
            "“Kurum” ibaresi “Kurul” şeklinde değiştirilmiştir.")
    recs, reg = extract_from_article("1", text, None)
    assert reg == "Deneme Hakkında Yönetmelik"
    (r,) = recs
    assert (r.location.madde, r.location.fikra, r.location.bent) == ("12", 11, "ç")
    assert (r.old_text, r.new_text) == ("Kurum", "Kurul")


def test_ayni_yonetmelik_onceki_hedefi_kullanir():
    recs, reg = extract_from_article(
        "2", "MADDE 2 – Aynı Yönetmeliğin geçici 3 üncü maddesi yürürlükten kaldırılmıştır.", "X Yönetmelik")
    assert reg == "X Yönetmelik"
    assert recs[0].location.madde_type == "gecici"
    assert recs[0].unit == "madde"


def test_yururluk_maddeleri_kayit_uretmez():
    recs, _ = extract_from_article("8", "MADDE 8 – Bu Yönetmelik yayımı tarihinde yürürlüğe girer.", "X")
    assert recs == []


def test_baseline_skoru_ornek_sette():
    preds = [a.to_dict() for a in extract_amendments((SAMPLES / "ornek_degisiklik.txt").read_text(encoding="utf-8"))]
    res = evaluate(preds, load_jsonl(SAMPLES / "ornek_degisiklik.gold.jsonl"))
    # Çoklu hedefli değişiklik ("9 uncu ve 10 uncu maddelerinde") artık ayrı kayıtlara açılıyor.
    assert res["tp"] == 9 and res["n_pred"] == 9 and res["n_gold"] == 9


def test_harfli_madde_numarasi_baslik_ve_coklu_fikra():
    text = ("MADDE 17 – Aynı Yönetmeliğin 26/Ç maddesinin başlığı “İç denetim” şeklinde, birinci, "
            "dördüncü ve beşinci fıkralarında yer alan “A” ibareleri “B” şeklinde değiştirilmiştir.")
    recs, _ = extract_from_article("17", text, "X Yönetmelik")
    got = [(r.operation, r.location.madde, r.location.fikra) for r in recs]
    assert got == [("BASLIK_DEGISTIR", "26/Ç", None), ("IBARE_DEGISTIR", "26/Ç", 1),
                   ("IBARE_DEGISTIR", "26/Ç", 4), ("IBARE_DEGISTIR", "26/Ç", 5)]


def test_birden_fazla_alinti_blogu_siraya_gore_dagitilir():
    text = ("MADDE 1 – Aynı Yönetmeliğin 18 inci maddesinin ikinci fıkrası aşağıdaki şekilde değiştirilmiş "
            "ve maddeye ikinci fıkrasından sonra gelmek üzere aşağıdaki üçüncü fıkra eklenmiştir.\n"
            "“(2) Yeni ikinci fıkra.”\n“(3) Eklenen üçüncü fıkra.”")
    recs, _ = extract_from_article("1", text, "X Yönetmelik")
    assert [(r.operation, r.new_text) for r in recs] == [
        ("BIRIM_DEGISTIR", "(2) Yeni ikinci fıkra."), ("BIRIM_EKLE", "(3) Eklenen üçüncü fıkra.")]


def test_ile_baglanan_hedefler_kendi_alintisini_alir():
    text = ("MADDE 1 – 10/3/2007 tarihli ve 26458 sayılı Resmî Gazete’de yayımlanan Banka Kartları ve Kredi Kartları "
            "Hakkında Yönetmeliğin 17 nci maddesinin üçüncü fıkrasının (e) bendi ile beşinci fıkrasının (h) bendi "
            "aşağıdaki şekilde değiştirilmiştir.\n“e) Birinci yeni metin.”\n“h) İkinci yeni metin,”")
    recs, _ = extract_from_article("1", text, None)
    got = [(r.location.madde, r.location.fikra, r.location.bent, r.new_text) for r in recs]
    assert got == [("17", 3, "e", "e) Birinci yeni metin."), ("17", 5, "h", "h) İkinci yeni metin,")]


def test_asagida_yer_alan_ifadesi_ekleme_olarak_taninir():
    text = ("MADDE 1 – 10/3/2007 tarihli ve 26458 sayılı Resmî Gazete’de yayımlanan Banka Kartları ve Kredi Kartları "
            "Hakkında Yönetmeliğin 18 inci maddesinin ikinci fıkrası aşağıdaki şekilde değiştirilmiş, aynı maddeye "
            "aşağıda yer alan üçüncü fıkra eklenmiştir.\n“(2) Yeni iki.”\n“(3) Yeni üç.”")
    recs, _ = extract_from_article("1", text, None)
    assert [(r.operation, r.location.madde, r.location.fikra, r.new_text) for r in recs] == [
        ("BIRIM_DEGISTIR", "18", 2, "(2) Yeni iki."), ("BIRIM_EKLE", "18", None, "(3) Yeni üç.")]
