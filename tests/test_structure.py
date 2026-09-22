from pathlib import Path

from mevzuatradar.parse.structure import parse_structure

SAMPLE = Path(__file__).parent.parent / "data/samples/ornek_yonetmelik.txt"


def doc():
    return parse_structure(SAMPLE.read_text(encoding="utf-8"))


def test_maddeler_ve_basliklar():
    d = doc()
    assert [m.key for m in d.maddeler] == ["1", "2", "3", "gecici:1"]
    assert d.get("3").title == "Bildirim süresi"
    assert d.get("gecici:1").title is None
    assert d.get("3").section.startswith("İKİNCİ BÖLÜM")


def test_fikra_bent_altbent_hiyerarsisi():
    m3 = doc().get("3")
    assert [f.num for f in m3.fikralar] == [1, 2, 3]
    f2 = m3.fikralar[1]
    assert [b.letter for b in f2.bentler] == ["a", "b"]
    assert [a.num for a in f2.bentler[1].alt_bentler] == [1, 2]


def test_degisiklik_notlari_ayri_tutulur():
    m3 = doc().get("3")
    f1 = m3.fikralar[0]
    assert f1.annotations[0].type == "Değişik"
    assert f1.annotations[0].source == "RG-15/3/2023-32134"
    assert "Değişik" not in f1.text
    assert m3.fikralar[2].annotations[0].type == "Mülga"


def test_alinti_bloklari_yapi_olarak_okunmaz():
    text = (
        "BAŞLIK\n"
        "MADDE 1 – Aynı Yönetmeliğe aşağıdaki geçici madde eklenmiştir.\n"
        "“Uyum\n"
        "GEÇİCİ MADDE 1 – (1) Metin.”\n"
        "MADDE 2 – Bu Yönetmelik yayımı tarihinde yürürlüğe girer.\n"
    )
    d = parse_structure(text)
    assert [m.key for m in d.maddeler] == ["1", "2"]
    assert "GEÇİCİ MADDE 1" in d.get("1").raw_text


def test_cok_satirli_belge_basligi():
    text = (
        "BANKALARIN BİLGİ SİSTEMLERİ VE ELEKTRONİK BANKACILIK\n"
        "HİZMETLERİ HAKKINDA YÖNETMELİK\n"
        "\n"
        "BİRİNCİ KISIM\n"
        "Başlangıç Hükümleri\n"
        "Amaç\n"
        "MADDE 1 – (1) Metin.\n"
    )
    d = parse_structure(text)
    assert d.title == "BANKALARIN BİLGİ SİSTEMLERİ VE ELEKTRONİK BANKACILIK HİZMETLERİ HAKKINDA YÖNETMELİK"
    assert d.maddeler[0].section == "BİRİNCİ KISIM – Başlangıç Hükümleri"


def test_dipnotlar_ve_baslik_notlari_ayrilir():
    text = (
        "KART YÖNETMELİĞİ\n"
        "Bilgi alışverişi kuruluşlarının iç kontrol sistemleri (Değişik başlık:RG-25/9/2020-31255)\n"
        "MADDE 26/A –(1) (1) Bilgi alışverişi kuruluşları iç kontrol sistemi kurar.\n"
        "(2) İç kontrol için;\n"
        "a) Görev ayrımı,\n"
        "(7) (5) Taksit süreleri Kurulca belirlenir.\n"
        "(8) Kart hamillerini bilgilendirirler.(3)\n"
        "Yürürlük\n"
        "MADDE 40 – (1) 19/10/2005 tarihli ve 5411 sayılı Kanun saklıdır.\n"
        "(1) 1/8/2009 tarihli ve 27306 sayılı Resmî Gazete’de yayımlanan Yönetmeliğin 3 üncü maddesiyle eklenmiştir.\n"
    )
    d = parse_structure(text)
    m = d.get("26/A")
    assert m.title == "Bilgi alışverişi kuruluşlarının iç kontrol sistemleri"
    assert ("Değişik", "RG-25/9/2020-31255") in [(a.type, a.source) for a in m.annotations]
    assert ("Dipnot", "dipnot:1") in [(a.type, a.source) for a in m.annotations]
    assert [f.num for f in m.fikralar] == [1, 2, 7, 8]
    assert m.fikralar[0].text.startswith("Bilgi alışverişi")
    assert m.fikralar[2].text == "Taksit süreleri Kurulca belirlenir."
    assert m.fikralar[3].text == "Kart hamillerini bilgilendirirler."
    # Tarihle başlayan gerçek fıkra korunur, dipnot tanımı yapıdan çıkarılır.
    assert d.get("40").fikralar[0].text.startswith("19/10/2005 tarihli")
    assert len(d.get("40").fikralar) == 1
    assert d.footnotes[1].startswith("1/8/2009 tarihli ve 27306")


def test_madde_satirinda_tek_basina_dipnot_ve_not_sonrasi_dipnot():
    text = ("Y\n"
            "Geçici hüküm\n"
            "MADDE 28/A –(4)\n"
            "(1) Geçici metin.\n"
            "MADDE 26 – (1) Birinci.\n"
            "(7) (Değişik:RG-11/1/2019-30652)(5) Mal veya hizmet.\n")
    d = parse_structure(text)
    m = d.get("28/A")
    assert [f.num for f in m.fikralar] == [1] and m.fikralar[0].text == "Geçici metin."
    assert ("Dipnot", "dipnot:4") in [(a.type, a.source) for a in m.annotations]
    f7 = d.get("26").fikralar[1]
    assert f7.text == "Mal veya hizmet."
    assert {a.type for a in f7.annotations} == {"Değişik", "Dipnot"}
