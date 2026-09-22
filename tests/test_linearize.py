from mevzuatradar.extract.amendments import extract_from_article
from mevzuatradar.ml.dataset import canonical_record
from mevzuatradar.ml.linearize import BLOCK_OPS, linearize, model_input, parse

TEXT = ("MADDE 1- 1/12/2021 tarihli ve 31676 sayılı Resmî Gazete’de yayımlanan Ödeme Hizmetleri ve Elektronik Para "
        "İhracı ile Ödeme Hizmeti Sağlayıcıları Hakkında Yönetmeliğin 3 üncü maddesinin birinci fıkrasının (ss) bendinde "
        "yer alan “tüzel kişiyi” ibaresi “organını” olarak değiştirilmiş ve aynı fıkraya aşağıdaki bentler eklenmiştir.\n"
        "“zz) Dijital cüzdan: Uzun bir tanım metni,\naaa) Kartlı sistem kuruluşu: Başka bir uzun tanım,”")


def test_girdi_alintilari_etiketlenir_ibareler_kalir():
    inp, quotes = model_input(TEXT)
    assert "[ALINTI1]" in inp and "Dijital cüzdan" not in inp
    assert "“tüzel kişiyi” ibaresi “organını”" in inp
    assert quotes == ["zz) Dijital cüzdan: Uzun bir tanım metni,\naaa) Kartlı sistem kuruluşu: Başka bir uzun tanım,"]


def test_dogrusallastirma_ve_geri_okuma():
    recs = [canonical_record(r.to_dict()) for r in extract_from_article("1", TEXT, None)[0]]
    lin = linearize(recs)
    assert lin == ("IBARE_DEGISTIR | madde=3 fikra=1 bent=ss | birim=ibare | eski=tüzel kişiyi | yeni=organını"
                   " ;; BIRIM_EKLE | madde=3 fikra=1 | birim=bent")
    back = parse(lin)
    for orig, got in zip(recs, back):
        expected = {k: v for k, v in orig.items() if not (k == "new_text" and orig["operation"] in BLOCK_OPS)}
        assert got == expected


def test_bos_ve_bozuk_cikti():
    assert linearize([]) == "YOK" and parse("YOK") == [] and parse("") == []
    # Modelin ürettiği bozuk parçalar atlanır, sağlam olanlar okunur.
    assert parse("anlamsız çıktı ;; IBARE_DEGISTIR | madde=5 | eski=a | yeni=b") == [{
        "operation": "IBARE_DEGISTIR", "old_text": "a", "new_text": "b",
        "location": {"madde_type": "normal", "madde": "5", "fikra": None, "bent": None, "alt_bent": None, "cumle": None}}]


def test_ornek_setin_tamami_gidis_donus():
    from pathlib import Path
    from mevzuatradar.extract.amendments import extract_amendments
    text = (Path(__file__).parent.parent / "data/samples/ornek_degisiklik.txt").read_text(encoding="utf-8")
    recs = [canonical_record(a.to_dict()) for a in extract_amendments(text)]
    back = parse(linearize(recs))
    assert len(back) == len(recs) == 9
    for orig, got in zip(recs, back):
        assert got == {k: v for k, v in orig.items() if not (k == "new_text" and orig["operation"] in BLOCK_OPS)}
