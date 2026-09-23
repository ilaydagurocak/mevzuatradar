from mevzuatradar.extract.supersede import find_evidence


def kayit(madde, eski=None, yeni=None, capa=None, madde_no="5"):
    return {"operation": "IBARE_DEGISTIR", "amending_article": madde, "old_text": eski,
            "new_text": yeni, "anchor_text": capa, "location": {"madde_type": "normal", "madde": madde_no}}


def test_sonraki_degisiklik_onceki_ibareyi_alintilarsa_kanit_sayilir():
    kayitlar = [(0, kayit("1", eski="Bankacılık Kurumu", yeni="Düzenleme Kurulu")),
                (3, kayit("2", eski="Düzenleme Kurulu", yeni="Kurum Başkanlığı"))]
    kanit = find_evidence(kayitlar, 0)
    assert kanit is not None and kanit.amendment_index == 3 and kanit.amending_article == "2"


def test_baska_maddedeki_alinti_kanit_sayilmaz():
    kayitlar = [(0, kayit("1", eski="Bankacılık Kurumu", yeni="Düzenleme Kurulu", madde_no="5")),
                (3, kayit("2", eski="Düzenleme Kurulu", yeni="Kurum Başkanlığı", madde_no="9"))]
    assert find_evidence(kayitlar, 0) is None


def test_onceki_degisiklik_kanit_sayilmaz():
    # kanıt SONRAKİ değişiklikten gelmeli; öncekinden gelen eşleşme sayılmaz
    kayitlar = [(3, kayit("2", eski="Düzenleme Kurulu", yeni="Kurum Başkanlığı")),
                (0, kayit("1", eski="Bankacılık Kurumu", yeni="Düzenleme Kurulu"))]
    assert find_evidence(kayitlar, 0) is None


def test_kisa_ibareler_rastlantisal_eslesmez():
    kayitlar = [(0, kayit("1", eski="on", yeni="yirmi")), (3, kayit("2", eski="yirmi", yeni="otuz"))]
    assert find_evidence(kayitlar, 0) is None


def test_resmi_metnin_degisiklik_notu_kanit_sayilir():
    from mevzuatradar.extract.supersede import note_evidence
    from mevzuatradar.parse.structure import parse_structure
    doc = parse_structure("YÖNETMELİK\nMADDE 26 – (1) Birinci fıkra.\n"
                          "(7) (Değişik:RG-25/9/2020-31255) Yedinci fıkranın güncel hâli.\n")
    rec = {"operation": "BIRIM_DEGISTIR", "location": {"madde": "26", "fikra": 7}}
    kanit = note_evidence(rec, "RG-25/9/2020-31255", doc)
    assert kanit is not None and "fıkra 7" in kanit.unit
    # başka bir değişikliğin etiketi kanıt sayılmaz
    assert note_evidence(rec, "RG-1/1/2015-29200", doc) is None
    # notun bulunduğu birim dışındaki hedef için de kanıt yok
    assert note_evidence({"operation": "BIRIM_DEGISTIR", "location": {"madde": "26", "fikra": 1}},
                         "RG-25/9/2020-31255", doc) is None
