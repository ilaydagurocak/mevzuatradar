from mevzuatradar.version.apply import apply_record, apply_records

METIN = """ÖRNEK YÖNETMELİK
Tanımlar
MADDE 3 – (1) Bu Yönetmelikte geçen;
a) Kurum: Bankacılık Düzenleme ve Denetleme Kurumunu,
b) Kanun: 5411 sayılı Kanunu,
ifade eder.
Başvuru
MADDE 5 – (1) Başvurular yazılı yapılır.
(2) Kurum otuz gün içinde karar verir.
GEÇİCİ MADDE 1 – (1) Bu madde geçicidir.
"""


def uygula(rec):
    return apply_record(METIN, rec)


def test_ibare_degistirme():
    yeni, res = uygula({"operation": "IBARE_DEGISTIR", "unit": "ibare", "old_text": "otuz",
                        "new_text": "altmış", "location": {"madde": "5", "fikra": 2}})
    assert res.status == "uygulandi"
    assert "altmış gün içinde" in yeni and "otuz gün" not in yeni
    assert "Başvurular yazılı yapılır." in yeni          # diğer fıkra dokunulmadı


def test_ibare_yanlis_fikrada_aranmaz():
    _, res = uygula({"operation": "IBARE_DEGISTIR", "unit": "ibare", "old_text": "otuz", "new_text": "altmış",
                     "location": {"madde": "5", "fikra": 1}})
    assert res.status == "metin_bulunamadi"


def test_ibare_ekleme_capadan_sonra():
    yeni, res = uygula({"operation": "IBARE_EKLE", "unit": "ibare", "anchor_text": "yazılı",
                        "anchor_position": "sonra", "new_text": "veya elektronik ortamda",
                        "location": {"madde": "5", "fikra": 1}})
    assert res.status == "uygulandi" and "yazılı veya elektronik ortamda yapılır" in yeni


def test_ibare_kaldirma():
    yeni, res = uygula({"operation": "IBARE_KALDIR", "unit": "ibare", "old_text": " ve Denetleme",
                        "location": {"madde": "3", "bent": "a"}})
    assert res.status == "uygulandi" and "Bankacılık Düzenleme Kurumunu" in yeni


def test_fikra_degistirme():
    yeni, res = uygula({"operation": "BIRIM_DEGISTIR", "unit": "fikra",
                        "new_text": "(2) Kurum kırk beş gün içinde karar verir.",
                        "location": {"madde": "5", "fikra": 2}})
    assert res.status == "uygulandi"
    assert "kırk beş gün" in yeni and "otuz gün" not in yeni
    assert "GEÇİCİ MADDE 1" in yeni                       # sonraki madde bozulmadı


def test_madde_degistirme_numara_korunur():
    yeni, res = uygula({"operation": "BIRIM_DEGISTIR", "unit": "madde",
                        "new_text": "(1) Başvurular yalnızca elektronik ortamda yapılır.",
                        "location": {"madde": "5"}})
    assert res.status == "uygulandi"
    assert "MADDE 5 – (1) Başvurular yalnızca elektronik ortamda yapılır." in yeni
    assert "Kurum otuz gün" not in yeni


def test_gecici_madde_hedefleme():
    yeni, res = uygula({"operation": "IBARE_DEGISTIR", "unit": "ibare", "old_text": "geçicidir",
                        "new_text": "süreklidir", "location": {"madde_type": "gecici", "madde": "1"}})
    assert res.status == "uygulandi" and "Bu madde süreklidir." in yeni


def test_fikra_ekleme_maddenin_sonuna():
    yeni, res = uygula({"operation": "BIRIM_EKLE", "unit": "fikra", "new_text": "(3) Karara itiraz edilebilir.",
                        "location": {"madde": "5"}})
    assert res.status == "uygulandi"
    satirlar = yeni.split("\n")
    assert satirlar[satirlar.index("(3) Karara itiraz edilebilir.") - 1] == "(2) Kurum otuz gün içinde karar verir."


def test_bent_ekleme_belirli_bentten_sonra():
    yeni, res = uygula({"operation": "BIRIM_EKLE", "unit": "bent", "insert_after": "a",
                        "new_text": "b) Kurul: Bankacılık Düzenleme ve Denetleme Kurulunu,",
                        "location": {"madde": "3", "fikra": 1}})
    assert res.status == "uygulandi"
    satirlar = [s for s in yeni.split("\n") if s.startswith(("a)", "b)"))]
    assert satirlar[0].startswith("a) Kurum") and satirlar[1].startswith("b) Kurul")


def test_fikra_kaldirma():
    yeni, res = uygula({"operation": "BIRIM_KALDIR", "unit": "fikra", "location": {"madde": "5", "fikra": 2}})
    assert res.status == "uygulandi" and "Kurum otuz gün" not in yeni and "MADDE 5" in yeni


def test_bulunmayan_madde():
    _, res = uygula({"operation": "IBARE_DEGISTIR", "unit": "ibare", "old_text": "a", "new_text": "b",
                     "location": {"madde": "99"}})
    assert res.status == "hedef_bulunamadi"


def test_kayitlar_sirayla_uygulanir():
    kayitlar = [
        {"operation": "IBARE_DEGISTIR", "unit": "ibare", "old_text": "otuz", "new_text": "altmış",
         "location": {"madde": "5", "fikra": 2}},
        {"operation": "IBARE_DEGISTIR", "unit": "ibare", "old_text": "altmış", "new_text": "doksan",
         "location": {"madde": "5", "fikra": 2}},
    ]
    yeni, sonuclar = apply_records(METIN, kayitlar)
    assert [r.status for r in sonuclar] == ["uygulandi", "uygulandi"]
    assert "doksan gün" in yeni                            # ikinci değişiklik birincinin üzerine geldi


def test_normalize_notlari_ve_dipnotlari_yoksayar():
    from mevzuatradar.version.build import _normalize
    a = "MADDE 5 – (Değişik:RG-1/1/2020-31000) (1) Başvurular  yazılı yapılır.(3)"
    b = "MADDE 5 – (1) Başvurular yazılı yapılır."
    assert _normalize(a) == _normalize(b)


BASLIKLI = """ÖRNEK YÖNETMELİK
Başvuru
MADDE 5 – (1) Başvurular yazılı yapılır.
(2) Kurum otuz gün içinde karar verir.
Denetim
MADDE 6 – (1) Denetim yıllık yapılır.
"""


def test_madde_satirindaki_birinci_fikra_degisince_madde_kaybolmaz():
    yeni, res = apply_record(BASLIKLI, {"operation": "BIRIM_DEGISTIR", "unit": "fikra",
                                        "new_text": "(1) Başvurular elektronik ortamda yapılır.",
                                        "location": {"madde": "5", "fikra": 1}})
    assert res.status == "uygulandi"
    assert "MADDE 5 – (1) Başvurular elektronik ortamda yapılır." in yeni
    assert "(2) Kurum otuz gün içinde karar verir." in yeni and "MADDE 6" in yeni


def test_baslik_degistirme_sadece_baslik_satirini_degistirir():
    yeni, res = apply_record(BASLIKLI, {"operation": "BASLIK_DEGISTIR", "unit": "baslik",
                                        "new_text": "Başvuru ve değerlendirme", "location": {"madde": "5"}})
    assert res.status == "uygulandi"
    assert "Başvuru ve değerlendirme\nMADDE 5 – (1) Başvurular yazılı yapılır." in yeni
    assert "Denetim" in yeni


def test_basligiyla_birlikte_degistirme():
    yeni, res = apply_record(BASLIKLI, {"operation": "BIRIM_DEGISTIR", "unit": "baslik",
                                        "new_text": "Yeni başlık\nMADDE 5 – (1) Yepyeni metin.",
                                        "location": {"madde": "5"}})
    assert res.status == "uygulandi"
    assert "Yeni başlık\nMADDE 5 – (1) Yepyeni metin." in yeni
    assert "Başvuru\n" not in yeni and "MADDE 6" in yeni


def test_ekler_kapsam_disi():
    _, res = apply_record(BASLIKLI, {"operation": "EK_EKLE", "unit": "ek", "new_text": "x",
                                     "location": {"madde_type": "ek_belge", "madde": "EK-1"}})
    assert res.status == "desteklenmiyor" and "ek" in res.detail.lower()


def test_baslikla_birlikte_fikra_degisimi_maddeyi_korur():
    # Gerçek vaka: "başlığı ... ve yedinci fıkrası aşağıdaki şekilde değiştirilmiştir"
    metin = ("Eski başlık\nMADDE 26 – (1) Birinci fıkra.\n(7) Eski yedinci fıkra.\n"
             "Denetim\nMADDE 27 – (1) Denetim yıllık yapılır.\n")
    yeni, res = apply_record(metin, {"operation": "BIRIM_DEGISTIR", "unit": "baslik",
                                     "new_text": "Yeni başlık\n(7) Yeni yedinci fıkra.",
                                     "location": {"madde": "26"}})
    assert res.status == "uygulandi"
    assert "Yeni başlık\nMADDE 26 – (1) Birinci fıkra." in yeni      # madde ve 1. fıkra yerinde
    assert "(7) Yeni yedinci fıkra." in yeni and "Eski yedinci" not in yeni
    assert "MADDE 27" in yeni


def test_harfli_yeni_madde_numarasina_gore_yerlesir():
    metin = ("MADDE 28 – (1) Yirmi sekizinci madde.\nMADDE 29 – (1) Yirmi dokuzuncu madde.\n")
    yeni, res = apply_record(metin, {"operation": "BIRIM_EKLE", "unit": "madde",
                                     "new_text": "MADDE 28/A – (1) Yeni madde.",
                                     "location": {"madde": "28/A"}})
    assert res.status == "uygulandi"
    satirlar = [s for s in yeni.split("\n") if s.startswith("MADDE")]
    assert satirlar == ["MADDE 28 – (1) Yirmi sekizinci madde.", "MADDE 28/A – (1) Yeni madde.",
                        "MADDE 29 – (1) Yirmi dokuzuncu madde."]


def test_cumle_degistirme():
    metin = "MADDE 5 – (1) Birinci cümle. İkinci cümle. Üçüncü cümle.\n(2) Başka fıkra.\n"
    yeni, res = apply_record(metin, {"operation": "BIRIM_DEGISTIR", "unit": "cumle",
                                     "new_text": "Yepyeni ikinci cümle.",
                                     "location": {"madde": "5", "fikra": 1, "cumle": "2"}})
    assert res.status == "uygulandi"
    assert "MADDE 5 – (1) Birinci cümle. Yepyeni ikinci cümle. Üçüncü cümle." in yeni
    assert "(2) Başka fıkra." in yeni


def test_olmayan_fikrayi_kaldirma_maddeyi_silmez():
    metin = "MADDE 26 – (1) Birinci fıkra.\n(2) İkinci fıkra.\nMADDE 27 – (1) Yirmi yedi.\n"
    yeni, res = apply_record(metin, {"operation": "BIRIM_KALDIR", "unit": "fikra",
                                     "location": {"madde": "26", "fikra": 8}})
    assert res.status == "hedef_bulunamadi" and "8. fıkra yok" in res.detail
    assert yeni == metin                                   # metne dokunulmadı


def test_olmayan_fikrayi_degistirme_maddeyi_ezmez():
    metin = "MADDE 26 – (1) Birinci fıkra.\n(2) İkinci fıkra.\n"
    yeni, res = apply_record(metin, {"operation": "BIRIM_DEGISTIR", "unit": "fikra",
                                     "new_text": "(8) Sekizinci fıkra.",
                                     "location": {"madde": "26", "fikra": 8}})
    assert res.status == "hedef_bulunamadi" and yeni == metin


def test_yeni_metin_madde_satirini_iceriyorsa_numara_tekrarlanmaz():
    metin = "MADDE 28 – (1) Eski metin.\nMADDE 29 – (1) Yirmi dokuz.\n"
    yeni, res = apply_record(metin, {"operation": "BIRIM_DEGISTIR", "unit": "madde",
                                     "new_text": "MADDE 28 – (1) Yeni metin.", "location": {"madde": "28"}})
    assert res.status == "uygulandi"
    assert "MADDE 28 – (1) Yeni metin." in yeni and "MADDE 28 – MADDE 28" not in yeni
    # numara tekrarlanmadığı için fıkra yapısı bozulmaz
    yeni2, res2 = apply_record(yeni, {"operation": "BIRIM_DEGISTIR", "unit": "fikra",
                                      "new_text": "(1) Daha da yeni.", "location": {"madde": "28", "fikra": 1}})
    assert res2.status == "uygulandi" and "MADDE 28 – (1) Daha da yeni." in yeni2


def test_baslik_kaydindaki_yeni_numarali_blok_eklenir():
    # "başlığı ... değiştirilmiş ve aynı maddeye aşağıdaki yedinci fıkra eklenmiştir" vakası
    metin = "Eski başlık\nMADDE 26 – (1) Bir.\n(2) İki.\nDenetim\nMADDE 27 – (1) Yirmi yedi.\n"
    yeni, res = apply_record(metin, {"operation": "BIRIM_DEGISTIR", "unit": "baslik",
                                     "new_text": "Yeni başlık\n(7) Yedinci fıkra.",
                                     "location": {"madde": "26"}})
    assert res.status == "uygulandi"
    assert "Yeni başlık" in yeni and "(1) Bir." in yeni and "(2) İki." in yeni
    satirlar = yeni.split("\n")
    assert satirlar[satirlar.index("(7) Yedinci fıkra.") + 1] == "Denetim"   # maddenin sonuna eklendi


def test_madde_bazinda_karsilastirma(tmp_path):
    from mevzuatradar.version.build import compare_by_article
    kons = tmp_path / "kaynak"; kons.mkdir()
    (kons / "konsolide_x.txt").write_text(
        "BAŞLIK\nMADDE 1 – (1) Aynı metin.\nMADDE 2 – (1) Resmi metin farklı.\nMADDE 3 – (1) Sadece resmide.\n",
        encoding="utf-8")
    bizimki = "BAŞLIK\nMADDE 1 – (1) Aynı metin.\nMADDE 2 – (1) Bizim metin başka.\nMADDE 4 – (1) Sadece bizde.\n"
    d = {x.madde: x.durum for x in compare_by_article("kaynak", bizimki, str(tmp_path))}
    assert d == {"1": "ayni", "2": "farkli", "3": "bizde_yok", "4": "resmide_yok"}


def test_bent_degisince_fikranin_kapanis_cumlesi_korunur():
    metin = ("MADDE 16 – (1) Atanacak kişiler ile ilgili olarak;\n"
             "a) Müflis olmadıklarına ilişkin belge,\n"
             "d) Lisans diplomasının onaylı örneği,\n"
             "atama işleminden önce Kuruma gönderilmesi zorunludur.\n"
             "MADDE 17 – (1) Sonraki madde.\n")
    yeni, res = apply_record(metin, {"operation": "BIRIM_DEGISTIR", "unit": "bent",
                                     "new_text": "d) Lisans ve lisansüstü diplomalarının onaylı örneği,",
                                     "location": {"madde": "16", "fikra": 1, "bent": "d"}})
    assert res.status == "uygulandi"
    assert "d) Lisans ve lisansüstü diplomalarının onaylı örneği," in yeni
    assert "atama işleminden önce Kuruma gönderilmesi zorunludur." in yeni   # kapanış cümlesi duruyor
    assert "a) Müflis" in yeni and "MADDE 17" in yeni


def test_fikra_eklemesi_bolum_basliginin_onune_gelir():
    metin = ("Yönetim\nMADDE 16 – (1) Birinci fıkra.\n(4) Dördüncü fıkra.\n\n"
             "DÖRDÜNCÜ BÖLÜM\nSözleşme Şekli\nSözleşme şartları\nMADDE 17 – (1) Onyedinci madde.\n")
    yeni, res = apply_record(metin, {"operation": "BIRIM_EKLE", "unit": "fikra",
                                     "new_text": "(5) Beşinci fıkra.", "location": {"madde": "16"}})
    assert res.status == "uygulandi"
    satirlar = [s for s in yeni.split("\n") if s.strip()]
    i5 = satirlar.index("(5) Beşinci fıkra.")
    assert satirlar[i5 - 1] == "(4) Dördüncü fıkra."          # maddenin sonuna
    assert satirlar[i5 + 1] == "DÖRDÜNCÜ BÖLÜM"                # bölüm başlığından önce


def _zincir_ortami(tmp_path):
    """İlk metin + iki değişiklik + konsolide metin içeren küçük bir kaynak."""
    d = tmp_path / "ornek"
    d.mkdir(parents=True)
    (d / "orijinal_x.txt").write_text(
        "ÖRNEK YÖNETMELİK\nSüre\nMADDE 5 – (1) Başvurular otuz gün içinde sonuçlandırılır.\n", encoding="utf-8")
    (d / "degisiklik00_a.txt").write_text(
        "DEĞİŞİKLİK\nMADDE 1 – 1/1/2010 tarihli ve 27000 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin "
        "5 inci maddesinin birinci fıkrasında yer alan “otuz” ibaresi “altmış” şeklinde değiştirilmiştir.\n",
        encoding="utf-8")
    (d / "degisiklik01_b.txt").write_text(
        "DEĞİŞİKLİK\nMADDE 1 – Aynı Yönetmeliğin 5 inci maddesinin birinci fıkrasında yer alan “altmış” ibaresi "
        "“doksan” şeklinde değiştirilmiştir.\n", encoding="utf-8")
    (d / "konsolide_x.txt").write_text(
        "ÖRNEK YÖNETMELİK\nSüre\nMADDE 5 – (1) (Değişik ibare:RG-1/6/2015-29400) (Değişik ibare:RG-1/3/2020-31000) "
        "Başvurular doksan gün içinde sonuçlandırılır.\n", encoding="utf-8")
    return str(tmp_path)


def test_tarihe_gore_madde_metni(tmp_path):
    from datetime import date

    from mevzuatradar.version.build import madde_at
    raw = _zincir_ortami(tmp_path)
    # ilk değişiklik 1/6/2015, ikincisi 1/3/2020 (konsolide metnin notlarından okunur)
    metin, surum = madde_at("ornek", "5", date(2016, 1, 1), raw)
    assert "altmış gün" in metin and "doksan" not in metin
    metin, _ = madde_at("ornek", "5", date(2021, 1, 1), raw)
    assert "doksan gün" in metin
    metin, _ = madde_at("ornek", "5", date(2014, 1, 1), raw)
    assert "otuz gün" in metin          # hiçbir değişiklik yürürlüğe girmemişken


def test_var_olan_numarali_fikra_eklenmez_degistirilir():
    # "aynı maddeye aşağıdaki fıkralar eklenmiştir" dese de numara zaten varsa değiştirme yapılır
    metin = "MADDE 26 – (1) Bir.\n(7) Eski yedi.\n(8) Eski sekiz.\nMADDE 27 – (1) Yirmi yedi.\n"
    yeni, res = apply_record(metin, {"operation": "BIRIM_EKLE", "unit": "fikra",
                                     "new_text": "(7) Yeni yedi.\n(8) Yeni sekiz.",
                                     "location": {"madde": "26"}})
    assert res.status == "uygulandi"
    numaralar = [s.strip()[:3] for s in yeni.split("\n") if s.strip().startswith("(")]
    assert numaralar == ["(7)", "(8)"]                     # tekrar yok
    assert "Yeni yedi." in yeni and "Eski yedi." not in yeni and "Yeni sekiz." in yeni


def test_kismen_var_olan_fikralar_hem_degistirilir_hem_eklenir():
    metin = "MADDE 26 – (1) Bir.\n(7) Eski yedi.\nMADDE 27 – (1) Yirmi yedi.\n"
    yeni, res = apply_record(metin, {"operation": "BIRIM_EKLE", "unit": "fikra",
                                     "new_text": "(7) Yeni yedi.\n(8) Yepyeni sekiz.",
                                     "location": {"madde": "26"}})
    assert res.status == "uygulandi"
    assert "Yeni yedi." in yeni and "Eski yedi." not in yeni
    satirlar = [s for s in yeni.split("\n") if s.strip()]
    assert satirlar.index("(8) Yepyeni sekiz.") < satirlar.index("MADDE 27 – (1) Yirmi yedi.")


def test_ek_ici_hedef_net_mesaj_verir():
    _, res = apply_record("MADDE 1 – (1) Metin.\n", {"operation": "BIRIM_DEGISTIR", "unit": "fikra",
                                                     "new_text": "(1) Yeni.",
                                                     "location": {"madde_type": "ek_belge", "madde": "EK-1"}})
    assert res.status == "hedef_bulunamadi" and "ek içi" in res.detail
