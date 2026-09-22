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
