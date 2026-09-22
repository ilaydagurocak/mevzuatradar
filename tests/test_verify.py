from mevzuatradar.extract.amendments import extract_amendments
from mevzuatradar.extract.verify import verify

KONSOLIDE = """ÖRNEK YÖNETMELİK
Tanımlar
MADDE 3 – (1) Bu Yönetmelikte geçen;
a) Kurul: Bankacılık Düzenleme ve Denetleme Kurulunu,
(2) (Mülga:RG-1/1/2022-1)
Yürürlük
MADDE 46 – (Değişik:RG-20/6/2020-31161)
(1) Bu Yönetmelik 1/1/2021 tarihinde yürürlüğe girer.
"""

DEGISIKLIK = """ÖRNEK YÖNETMELİKTE DEĞİŞİKLİK YAPILMASINA DAİR YÖNETMELİK
MADDE 1 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin 46 ncı maddesi aşağıdaki şekilde değiştirilmiştir.
“MADDE 46 – (1) Bu Yönetmelik 1/1/2021 tarihinde yürürlüğe girer.”
MADDE 2 – Aynı Yönetmeliğin 3 üncü maddesinin birinci fıkrasının (a) bendinde yer alan “Kurum” ibaresi “Kurul” şeklinde değiştirilmiştir.
MADDE 3 – Aynı Yönetmeliğin 3 üncü maddesinin ikinci fıkrası yürürlükten kaldırılmıştır.
MADDE 4 – Aynı Yönetmeliğin 7 nci maddesinin birinci fıkrasında yer alan “x” ibaresi “y” şeklinde değiştirilmiştir.
"""


def test_konsolide_ile_dogrulama():
    recs = [a.to_dict() for a in extract_amendments(DEGISIKLIK)]
    statuses = [res.status for _, res in verify(recs, KONSOLIDE)]
    assert statuses == ["uyumlu", "uyumlu", "uyumlu", "hedef_bulunamadi"]


def test_sonradan_degisen_birim_hata_sayilmaz():
    from mevzuatradar.extract.verify import verify_chronological
    ilk = extract_amendments(
        "B\nMADDE 1 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin 46 ncı maddesi "
        "aşağıdaki şekilde değiştirilmiştir.\n“MADDE 46 – (1) Eski hal.”")
    sonra = extract_amendments(
        "B\nMADDE 1 – 1/1/2021 tarihli ve 2 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin 46 ncı maddesi "
        "aşağıdaki şekilde değiştirilmiştir.\n“MADDE 46 – (1) Bu Yönetmelik 1/1/2021 tarihinde yürürlüğe girer.”")
    res = verify_chronological([[a.to_dict() for a in ilk], [a.to_dict() for a in sonra]], KONSOLIDE)
    assert [r.status for _, _, r in res] == ["sonradan_degisti", "uyumlu"]


def test_baslik_ve_madde_ekleme_kontrolu():
    kons = KONSOLIDE + "İç denetim\nMADDE 47 – (1) Yeni madde.\n"
    recs = [a.to_dict() for a in extract_amendments(
        "B\nMADDE 1 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin 46 ncı maddesinin "
        "başlığı “Yürürlük” şeklinde değiştirilmiştir.\n"
        "MADDE 2 – Aynı Yönetmeliğe aşağıdaki madde eklenmiştir.\n“İç denetim\nMADDE 47 – (1) Yeni madde.”")]
    assert [r.status for _, r in verify(recs, kons)] == ["uyumlu", "uyumlu"]


def test_eklenen_madde_sonradan_degisirse_hata_sayilmaz():
    from mevzuatradar.extract.verify import verify_chronological
    kons = KONSOLIDE + "MADDE 27/A – (1) Güncel –PCI– metni.\n"
    ekle = extract_amendments("B\nMADDE 1 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Örnek "
                              "Yönetmeliğe aşağıdaki madde eklenmiştir.\n“MADDE 27/A – (1) Eski metin.”")
    degistir = extract_amendments("B\nMADDE 1 – 1/1/2021 tarihli ve 2 sayılı Resmî Gazete’de yayımlanan Örnek "
                                  "Yönetmeliğin 27/A maddesinin birinci fıkrası aşağıdaki şekilde değiştirilmiştir.\n"
                                  "“(1) Güncel -PCI- metni.”")
    res = verify_chronological([[a.to_dict() for a in ekle], [a.to_dict() for a in degistir]], kons)
    assert [r.status for _, _, r in res] == ["sonradan_degisti", "uyumlu"]


def test_tek_alintida_iki_fikra():
    kons = "Y\nMADDE 18 – (1) Bir.\n(2) Yeni iki.\n(3) Yeni üç.\n"
    recs = [a.to_dict() for a in extract_amendments(
        "B\nMADDE 1 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin 18 inci maddesinin "
        "ikinci fıkrası aşağıdaki şekilde değiştirilmiştir.\n“(2) Yeni iki.\n(3) Yeni üç.”")]
    assert [r.status for _, r in verify(recs, kons)] == ["uyumlu"]


def test_alt_bent_ve_cumle_dogrulama():
    kons = ("Y\nMADDE 13 – (1) Teminatlar;\nb) İkinci grup;\n10) On,\nc) Üçüncü grup;\n2) Yeni iki,\n"
            "MADDE 59 – (1) Bir.\n(5) Yeni birinci cümle. Eski ikinci cümle.\n")
    recs = [a.to_dict() for a in extract_amendments(
        "B\nMADDE 1 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin 13 üncü maddesinin "
        "birinci fıkrasının (c) bendinin (2) numaralı alt bendi aşağıdaki şekilde değiştirilmiştir.\n“2) Yeni iki,”\n"
        "MADDE 2 – Aynı Yönetmeliğin 59 uncu maddesinin beşinci fıkrasının birinci cümlesi aşağıdaki şekilde "
        "değiştirilmiştir.\n“Yeni birinci cümle.”")]
    assert [r.status for _, r in verify(recs, kons)] == ["uyumlu", "uyumlu"]


def test_tek_alintida_iki_bent():
    kons = "Y\nMADDE 11 – (1) Bir.\n(4) Belgeler;\nf) Yeni ef (EK-4),\ng) Yeni ge (EK-5),\n"
    recs = [a.to_dict() for a in extract_amendments(
        "B\nMADDE 6 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin 11 inci maddesinin "
        "dördüncü fıkrasının (f) ve (g) bentleri aşağıdaki şekilde değiştirilmiştir.\n“f) Yeni ef (EK-4),\ng) Yeni ge (EK-5),”")]
    assert [(r["location"]["bent"], res.status) for r, res in verify(recs, kons)] == [("f", "uyumlu"), ("g", "uyumlu")]


def test_ek_ici_degisiklik_kapsam_disi():
    recs = [a.to_dict() for a in extract_amendments(
        "B\nMADDE 2 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin ekinde yer alan "
        "Ek-1’in 40 ıncı fıkrası aşağıdaki şekilde değiştirilmiştir.\n“40. Yeni.”")]
    assert [r.status for _, r in verify(recs, KONSOLIDE)] == ["kontrol_edilemedi"]
