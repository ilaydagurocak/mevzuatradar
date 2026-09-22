from mevzuatradar.extract.known_issues import apply_known_issues
from mevzuatradar.extract.verify import VerifyResult

ISSUE = {"id": "ornek", "source": "kredi", "amendment_url": "https://rg/2016.htm", "amending_article": "1",
         "operation": "BIRIM_KALDIR", "location": {"madde_type": "gecici", "madde": "2"},
         "description": "Açıklama.", "evidence": [{"url": "https://kanit"}]}
REC = {"amending_article": "1", "operation": "BIRIM_KALDIR",
       "location": {"madde_type": "gecici", "madde": "2", "fikra": None, "bent": None}}
AMDS = ["data/raw/kredi/degisiklik00_abc.html"]
URLS = {"degisiklik00_abc.html": "https://rg/2016.htm"}


def test_basarisiz_dogrulama_kaynak_tutarsizligi_olur():
    res, resolved = apply_known_issues("kredi", AMDS, [(0, REC, VerifyResult("uyumsuz", "x"))], [ISSUE], URLS)
    assert res[0][2].status == "kaynak_tutarsizligi" and "https://kanit" in res[0][2].detail
    assert resolved == []


def test_kaynak_duzelirse_etiket_uygulanmaz_ve_bildirilir():
    res, resolved = apply_known_issues("kredi", AMDS, [(0, REC, VerifyResult("uyumlu", "x"))], [ISSUE], URLS)
    assert res[0][2].status == "uyumlu" and resolved == ["ornek"]


def test_baska_kayitlar_etkilenmez():
    diger = {**REC, "location": {"madde_type": "normal", "madde": "2"}}
    res, _ = apply_known_issues("kredi", AMDS, [(0, diger, VerifyResult("uyumsuz", "x"))], [ISSUE], URLS)
    assert res[0][2].status == "uyumsuz"
