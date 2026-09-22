import json

from mevzuatradar.ml.dataset import build_examples, canonical_record, quality, write_dataset

KONSOLIDE = """ÖRNEK YÖNETMELİK
Tanımlar
MADDE 3 – (1) Bu Yönetmelikte geçen;
a) Kurul: Bankacılık Düzenleme ve Denetleme Kurulunu,
Yürürlük
MADDE 46 – (1) Bu Yönetmelik 1/1/2021 tarihinde yürürlüğe girer.
"""

DEGISIKLIK = """ÖRNEK YÖNETMELİKTE DEĞİŞİKLİK YAPILMASINA DAİR YÖNETMELİK
MADDE 1 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin 46 ncı maddesi aşağıdaki şekilde değiştirilmiştir.
“MADDE 46 – (1) Bu Yönetmelik 1/1/2021 tarihinde yürürlüğe girer.”
MADDE 2 – Aynı Yönetmeliğin 3 üncü maddesinin birinci fıkrasının (a) bendinde yer alan “Kurum” ibaresi “Kurul” şeklinde değiştirilmiştir.
MADDE 3 – Aynı Yönetmeliğin 7 nci maddesinin birinci fıkrasında yer alan “x” ibaresi “y” şeklinde değiştirilmiştir.
MADDE 4 – Bu Yönetmelik yayımı tarihinde yürürlüğe girer.
"""


def _raw(tmp_path):
    d = tmp_path / "raw" / "ornek"
    d.mkdir(parents=True)
    (d / "konsolide_aaa.txt").write_text(KONSOLIDE, encoding="utf-8")
    (d / "degisiklik00_bbb.txt").write_text(DEGISIKLIK, encoding="utf-8")
    return str(tmp_path / "raw")


def test_kalite_etiketleri():
    assert quality([], "MADDE 4 – Bu Yönetmelik yayımı tarihinde yürürlüğe girer.") == "kayitsiz"
    assert quality([], "MADDE 5 – Bu Yönetmelik hükümlerini Başkan yürütür.") == "kayitsiz"
    assert quality([], "MADDE 14 – ... ibaresi “yıllık” biçiminde değiştirilmiştir.") == "supheli"
    assert quality(["uyumlu", "kontrol_edilemedi"]) == "kismen"
    assert quality(["uyumlu", "uyumlu"]) == "dogrulanmis"
    assert quality(["uyumlu", "sonradan_degisti"]) == "kismen"
    assert quality(["uyumlu", "uyumsuz"]) == "sorunlu"
    assert quality(["kaynak_tutarsizligi"]) == "sorunlu"


def test_ornekler_madde_bazinda_ve_etiketli(tmp_path):
    ex = {e["article"]: e for e in build_examples("ornek", _raw(tmp_path))}
    assert [ex[k]["quality"] for k in ("1", "2", "3", "4")] == ["dogrulanmis", "dogrulanmis", "sorunlu", "kayitsiz"]
    assert ex["2"]["records"] == [{"operation": "IBARE_DEGISTIR", "unit": "ibare", "old_text": "Kurum",
                                   "new_text": "Kurul", "location": {"madde_type": "normal", "madde": "3",
                                   "fikra": 1, "bent": "a", "alt_bent": None, "cumle": None}}]
    assert ex["1"]["text"].startswith("MADDE 1 –") and "MADDE 46 – (1)" in ex["1"]["text"]
    assert ex["4"]["records"] == []


def test_bolmeler_yonetmelik_bazinda(tmp_path):
    raw = _raw(tmp_path)
    stats = write_dataset(["ornek"], {"ornek": "dev"}, raw, str(tmp_path / "ml"))
    lines = (tmp_path / "ml" / "dev.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4 and all(json.loads(l)["split"] == "dev" for l in lines)
    assert not (tmp_path / "ml" / "train.jsonl").exists()
    assert stats[("dev", "ornek", "dogrulanmis")] == 2


def test_kanonik_kayit_kaynaga_ozgu_alanlari_atar():
    rec = {"amending_article": "1", "target_regulation": "X", "operation": "BIRIM_KALDIR", "unit": "fikra",
           "location": {"madde": "5", "fikra": 2}, "old_text": None}
    assert canonical_record(rec) == {"operation": "BIRIM_KALDIR", "unit": "fikra", "location": {
        "madde_type": None, "madde": "5", "fikra": 2, "bent": None, "alt_bent": None, "cumle": None}}
