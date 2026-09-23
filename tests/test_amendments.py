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


def test_masak_kaliplari_buyuk_harfli_gecici_ve_baslik_ile_birlikte():
    recs, _ = extract_from_article("2", "MADDE 2 – Aynı Yönetmeliğin Geçici 1 inci maddesine aşağıdaki fıkra "
                                   "eklenmiştir.\n“(2) Yeni fıkra.”", "X")
    assert (recs[0].location.madde_type, recs[0].location.madde) == ("gecici", "1")
    recs, _ = extract_from_article("5", "MADDE 5 – Aynı Yönetmeliğin 16 ncı maddesi başlığı ile birlikte aşağıdaki "
                                   "şekilde değiştirilmiştir.\n“Uyum görevlisi\nMADDE 16 – (1) Yeni.”", "X")
    assert [(r.operation, r.unit, r.location.madde) for r in recs] == [("BIRIM_DEGISTIR", "madde", "16")]


def test_duz_tirnakli_alinti():
    from mevzuatradar.extract.amendments import extract_amendments
    text = ('B\nMADDE 2 – 1/1/2008 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan X Yönetmeliğin 33 üncü maddesi '
            'aşağıdaki şekilde değiştirilmiştir.\n"MADDE 33 – (1) Yeni yürürlük."\nMADDE 3 – Bu Yönetmelik yürürlüğe girer.')
    recs = extract_amendments(text)
    assert [(r.operation, r.location.madde, r.new_text) for r in recs] == [
        ("BIRIM_DEGISTIR", "33", "MADDE 33 – (1) Yeni yürürlük.")]


def _locs(recs):
    return [(r.operation, r.unit, r.location.madde, r.location.fikra, r.location.bent,
             r.location.alt_bent, r.location.cumle, r.new_text) for r in recs]


def test_alt_bent_listesi_ve_alintilarin_dagitimi():
    text = ("MADDE 4 – Aynı Yönetmeliğin 13 üncü maddesinin birinci fıkrasının (b) bendine aşağıdaki alt bentler "
            "eklenmiş ve aynı fıkranın (c) bendinin (2) ve (5) numaralı alt bentleri aşağıdaki şekilde değiştirilmiştir.\n"
            "“10) On,\n11) Onbir,”\n“2) İki,”\n“5) Beş,”")
    recs, _ = extract_from_article("4", text, "X")
    assert _locs(recs) == [
        ("BIRIM_EKLE", "alt_bent", "13", 1, "b", None, None, "10) On,\n11) Onbir,"),
        ("BIRIM_DEGISTIR", "alt_bent", "13", 1, "c", 2, None, "2) İki,"),
        ("BIRIM_DEGISTIR", "alt_bent", "13", 1, "c", 5, None, "5) Beş,"),
    ]


def test_bent_listesi_ve_fikra_listesi_kaldirma():
    text = ("MADDE 16- Aynı Yönetmeliğin 32 nci maddesinin ikinci fıkrasının (c) ve (ç) bentlerinde yer alan "
            "“bankalar ve” ibaresi yürürlükten kaldırılmış, aynı fıkraya aşağıdaki bent eklenmiş ve aynı maddenin "
            "beşinci ve yedinci fıkraları yürürlükten kaldırılmıştır.\n“e) Teminat tutarı.”")
    recs, _ = extract_from_article("16", text, "X")
    assert [(r.operation, r.location.fikra, r.location.bent) for r in recs] == [
        ("IBARE_KALDIR", 2, "c"), ("IBARE_KALDIR", 2, "ç"), ("BIRIM_EKLE", 2, None),
        ("BIRIM_KALDIR", 5, None), ("BIRIM_KALDIR", 7, None)]


def test_ortak_fiilli_ibare_eklemeleri_ve_alinti_icerigi_konumu_etkilemez():
    text = ("MADDE 24- Aynı Yönetmeliğin 61 inci maddesinin beşinci fıkrasında yer alan “15 inci maddenin” ibaresinden "
            "sonra gelmek üzere “ikinci fıkrasının (c) bendi, üçüncü fıkrasının (ç) bendi,” ibaresi, “sekizinci fıkrası” "
            "ibaresinden sonra gelmek üzere “ve dokuzuncu fıkrası” ibaresi eklenmiştir.")
    recs, _ = extract_from_article("24", text, "X")
    assert [(r.operation, r.location.madde, r.location.fikra, r.location.bent, r.anchor_text) for r in recs] == [
        ("IBARE_EKLE", "61", 5, None, "15 inci maddenin"), ("IBARE_EKLE", "61", 5, None, "sekizinci fıkrası")]


def test_cumle_degisikligi_ve_adinda_ile_gecen_yonetmelik():
    text = ("MADDE 1- 1/12/2021 tarihli ve 31676 sayılı Resmî Gazete’de yayımlanan Ödeme Hizmetleri ve Elektronik Para "
            "İhracı ile Ödeme Hizmeti Sağlayıcıları Hakkında Yönetmeliğin 59 uncu maddesinin beşinci fıkrasının birinci "
            "cümlesi aşağıdaki şekilde değiştirilmiş ve aynı maddeye aşağıdaki fıkralar eklenmiştir.\n"
            "“Yeni birinci cümle.”\n“(8) Sekiz.”\n“(9) Dokuz.”")
    recs, reg = extract_from_article("1", text, None)
    assert reg.startswith("Ödeme Hizmetleri ve Elektronik Para İhracı ile")
    assert _locs(recs) == [
        ("BIRIM_DEGISTIR", "cumle", "59", 5, None, None, "1", "Yeni birinci cümle."),
        ("BIRIM_EKLE", "fikra", "59", None, None, None, None, "(8) Sekiz.\n(9) Dokuz."),
    ]


def test_ile_ile_bagli_cumle_ve_fikra():
    text = ("MADDE 2- Aynı Yönetmeliğin geçici 1 inci maddesinin dokuzuncu fıkrasının üçüncü ve dördüncü cümleleri "
            "ile on dokuzuncu fıkrası aşağıdaki şekilde değiştirilmiştir.\n“Üç. Dört.”\n“(19) Ondokuz.”")
    recs, _ = extract_from_article("2", text, "X")
    assert [(r.unit, r.location.madde_type, r.location.fikra, r.location.cumle, r.new_text) for r in recs] == [
        ("cumle", "gecici", 9, "3,4", "Üç. Dört."), ("fikra", "gecici", 19, None, "(19) Ondokuz.")]


def test_virgul_ve_ile_bagli_farkli_turde_hedefler():
    text = ("MADDE 10 – Aynı Yönetmeliğin 17 nci maddesinin birinci fıkrası, ikinci fıkrasının birinci cümlesi ve "
            "üçüncü fıkrasının birinci cümlesi aşağıdaki şekilde değiştirilmiştir.\n"
            "“(1) Bir.”\n“İki birinci cümle:”\n“Üç birinci cümle:”")
    recs, _ = extract_from_article("10", text, "X")
    assert [(r.unit, r.location.madde, r.location.fikra, r.location.cumle, r.new_text) for r in recs] == [
        ("fikra", "17", 1, None, "(1) Bir."), ("cumle", "17", 2, "1", "İki birinci cümle:"),
        ("cumle", "17", 3, "1", "Üç birinci cümle:")]


def test_ic_ice_tirnak():
    text = ("MADDE 3 – Aynı Yönetmeliğin 8 inci maddesinin üçüncü fıkrası aşağıdaki şekilde değiştirilmiştir.\n"
            "“(3) Bu Yönetmelik uyarınca “Beşinci Grup” altında sınıflandırılan krediler düşülür.”")
    recs, _ = extract_from_article("3", text, "X")
    assert recs[0].new_text == "(3) Bu Yönetmelik uyarınca “Beşinci Grup” altında sınıflandırılan krediler düşülür."


def test_maddeden_sonra_gereksiz_virgul_baglamdir():
    text = ("MADDE 1 – 10/3/2007 tarihli ve 26458 sayılı Resmî Gazete’de yayımlanan Banka Kartları ve Kredi Kartları "
            "Hakkında Yönetmeliğin 17 nci maddesinin, üçüncü fıkrasının (e) bendi ile beşinci fıkrasının (h) bendi "
            "aşağıdaki şekilde değiştirilmiştir.\n“e) Yeni e.”\n“h) Yeni h,”")
    recs, _ = extract_from_article("1", text, None)
    assert [(r.unit, r.location.madde, r.location.fikra, r.location.bent, r.new_text) for r in recs] == [
        ("bent", "17", 3, "e", "e) Yeni e."), ("bent", "17", 5, "h", "h) Yeni h,")]


def test_tekil_yazilmis_fikra_listesi():
    text = ("MADDE 1 – 10/3/2007 tarihli ve 26458 sayılı Resmî Gazete’de yayımlanan Banka Kartları ve Kredi Kartları "
            "Hakkında Yönetmeliğin 26 ncı maddesinin yedinci ve sekizinci fıkrası aşağıdaki şekilde değiştirilmiştir.\n"
            "“(7) Yedi.”\n“(8) Sekiz.”")
    recs, _ = extract_from_article("1", text, None)
    assert [(r.unit, r.location.madde, r.location.fikra, r.new_text) for r in recs] == [
        ("fikra", "26", 7, "(7) Yedi."), ("fikra", "26", 8, "(8) Sekiz.")]


def test_olarak_ve_seklide_yazim_hatasi():
    recs, _ = extract_from_article("27", "MADDE 27- Aynı Yönetmeliğin 73 üncü maddesinde yer alan “üçyüz” ibareleri "
                                   "“bin” olarak, “Üçyüz” ibaresi “Bin” olarak, “beşyüz” ibareleri “ikibinyediyüzelli” "
                                   "olarak değiştirilmiştir.", "X")
    assert [(r.location.madde, r.old_text, r.new_text) for r in recs] == [
        ("73", "üçyüz", "bin"), ("73", "Üçyüz", "Bin"), ("73", "beşyüz", "ikibinyediyüzelli")]
    recs, _ = extract_from_article("8", "MADDE 8- Aynı Yönetmeliğin 30 uncu maddesinde yer alan “(a), (b) ve (c)” "
                                   "ibaresi “(a), (b), (c) ve (e)” şeklide değiştirilmiştir.", "X")
    assert [(r.location.madde, r.location.bent, r.new_text) for r in recs] == [("30", None, "(a), (b), (c) ve (e)")]


def test_ekler():
    recs, _ = extract_from_article("30", "MADDE 30- Aynı Yönetmeliğin EK-1, EK-11-A, EK-18 ve EK-19’u ekteki şekilde "
                                   "değiştirilmiştir.", "X")
    assert [(r.operation, r.location.madde) for r in recs] == [
        ("EK_DEGISTIR", "EK-1"), ("EK_DEGISTIR", "EK-11-A"), ("EK_DEGISTIR", "EK-18"), ("EK_DEGISTIR", "EK-19")]
    recs, _ = extract_from_article("24", "MADDE 24 – Aynı Yönetmeliğe ekte yer alan Ek-1/A, Ek-1/B ve Ek-2 eklenmiştir.", "X")
    assert [(r.operation, r.location.madde) for r in recs] == [("EK_EKLE", "EK-1/A"), ("EK_EKLE", "EK-1/B"), ("EK_EKLE", "EK-2")]
    recs, _ = extract_from_article("21", "MADDE 21 – Aynı Yönetmeliğin ekine ekte yer alan Ek-5 eklenmiştir.", "X")
    assert [(r.operation, r.location.madde) for r in recs] == [("EK_EKLE", "EK-5")]


def test_liste_halinde_fikra_ekleme():
    text = ("MADDE 1 – 22/6/2016 tarihli ve 29750 sayılı Resmî Gazete’de yayımlanan Örnek Hakkında Yönetmeliğin 8 inci "
            "maddesine aşağıdaki üçüncü, dördüncü ve beşinci fıkralar eklenmiştir.\n“(3) Üç.”\n“(4) Dört.”\n“(5) Beş.”")
    recs, _ = extract_from_article("1", text, None)
    assert [(r.operation, r.unit, r.location.madde, r.new_text) for r in recs] == [
        ("BIRIM_EKLE", "fikra", "8", "(3) Üç.\n(4) Dört.\n(5) Beş.")]


def test_alt_maddeli_duzenlemeler():
    text = ("MADDE 5- Aynı Yönetmeliğin 17 nci maddesinde aşağıdaki düzenlemeler yapılmıştır:\n"
            "a) Birinci fıkrasının (c) bendinde yer alan “2499 sayılı Kanunun” ibaresi “6362 sayılı Kanunun” olarak, "
            "(d) bendinde yer alan “veya uzman” ibaresi “veya Hazine ve Maliye Uzmanı” olarak değiştirilmiştir.\n"
            "b) Birinci fıkrasına (d) bendinden sonra gelmek üzere aşağıdaki bent eklenmiş ve diğer bentler buna göre "
            "teselsül ettirilmiştir.\n“e) Uyum görevlisi siciline kayıtlı olmak,”\n"
            "c) Aynı maddeye aşağıdaki fıkra eklenmiştir.\n“(2) Başkanlıkta çalışmış olanlar yetkilendirilir.”")
    recs, _ = extract_from_article("5", text, "X")
    assert [(r.operation, r.location.madde, r.location.fikra, r.location.bent, r.new_text) for r in recs] == [
        ("IBARE_DEGISTIR", "17", 1, "c", "6362 sayılı Kanunun"),
        ("IBARE_DEGISTIR", "17", 1, "d", "veya Hazine ve Maliye Uzmanı"),
        ("BIRIM_EKLE", "17", 1, None, "e) Uyum görevlisi siciline kayıtlı olmak,"),
        ("BIRIM_EKLE", "17", None, None, "(2) Başkanlıkta çalışmış olanlar yetkilendirilir."),
    ]
    assert recs[2].insert_after == "d"


def test_cok_harfli_bent_hedefi():
    text = ("MADDE 1- 1/12/2021 tarihli ve 31676 sayılı Resmî Gazete’de yayımlanan Ödeme Hizmetleri ve Elektronik "
            "Para İhracı ile Ödeme Hizmeti Sağlayıcıları Hakkında Yönetmeliğin 3 üncü maddesinin birinci fıkrasının "
            "(c) bendinde yer alan “doğrulaması yapılmamış,” ibaresinden sonra gelmek üzere “parasal sınırlar "
            "dahilinde kalan,” ibaresi eklenmiş, (ss) bendinde yer alan “tüzel kişiyi” ibaresi “organını” olarak "
            "değiştirilmiş ve aynı fıkraya aşağıdaki bentler eklenmiştir.\n“zz) Dijital cüzdan,\naaa) Kartlı sistem,”")
    recs, _ = extract_from_article("1", text, None)
    assert [(r.operation, r.location.madde, r.location.fikra, r.location.bent) for r in recs] == [
        ("IBARE_EKLE", "3", 1, "c"), ("IBARE_DEGISTIR", "3", 1, "ss"), ("BIRIM_EKLE", "3", 1, None)]


def test_ek_ici_degisiklik():
    text = ("MADDE 3 – Aynı Yönetmeliğin ekinde yer alan EK-1’in Birinci Bölümünün 45 inci fıkrasının (c) bendinin "
            "ikinci cümlesi aşağıdaki şekilde değiştirilmiştir.\n“Yeni cümle.”")
    recs, _ = extract_from_article("3", text, "X")
    assert [(r.location.madde_type, r.location.madde, r.location.bent) for r in recs] == [("ek_belge", "EK-1", "c")]
    recs, _ = extract_from_article("2", "MADDE 2 – Aynı Yönetmeliğin ekinde yer alan Ek-1’in 40 ıncı fıkrası aşağıdaki "
                                   "şekilde değiştirilmiştir.\n“40. Yeni.”", "X")
    assert (recs[0].location.madde_type, recs[0].location.madde) == ("ek_belge", "EK-1")


def test_alintilar_fikra_isaretlerine_gore_dagitilir():
    text = ("MADDE 1 – 1/11/2006 tarihli ve 26333 sayılı Resmî Gazete’de yayımlanan Örnek Hakkında Yönetmeliğin 14 üncü "
            "maddesinin birinci, beşinci, altıncı ve yedinci fıkraları aşağıdaki şekilde değiştirilmiştir.\n"
            "“(1) Bir.”\n“(5) Beş.\n(6) Altı.\n(7) Yedi.”")
    recs, _ = extract_from_article("1", text, None)
    assert [(r.location.fikra, r.new_text) for r in recs] == [(1, "(1) Bir."), (5, "(5) Beş."), (6, "(6) Altı."), (7, "(7) Yedi.")]


def test_dogrudan_madde_ile_baslayan_metin():
    from mevzuatradar.extract.amendments import extract_amendments
    # API'ye tek bir madde yapıştırıldığında ilk satır başlık sanılmamalı
    metin = ("MADDE 1 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin 3 üncü "
             "maddesinin birinci fıkrasında yer alan “Kurum” ibaresi “Kurul” şeklinde değiştirilmiştir.")
    recs = extract_amendments(metin)
    assert [(r.operation, r.location.madde, r.old_text, r.new_text) for r in recs] == [
        ("IBARE_DEGISTIR", "3", "Kurum", "Kurul")]
