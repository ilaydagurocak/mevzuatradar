import json

from mevzuatradar.ml.dataset import export_seq2seq, write_dataset
from mevzuatradar.ml.evaluate_model import evaluate, fill_block_text
from mevzuatradar.ml.linearize import parse
from tests.test_dataset import _raw


def test_alinti_doldurma_isaretlere_gore():
    recs = parse("BIRIM_DEGISTIR | madde=14 fikra=1 | birim=fikra ;; BIRIM_DEGISTIR | madde=14 fikra=6 | birim=fikra")
    fill_block_text(recs, ["(1) Bir.", "(5) Beş.\n(6) Altı."])
    assert [r["new_text"] for r in recs] == ["(1) Bir.", "(6) Altı."]


def test_kusursuz_model_kural_sistemiyle_ayni_sonucu_alir(tmp_path):
    raw, ml = _raw(tmp_path), tmp_path / "ml"
    write_dataset(["ornek"], {"ornek": "dev"}, raw, str(ml))
    export_seq2seq(str(ml), str(ml))
    rows = [json.loads(l) for l in open(ml / "seq2seq_dev.jsonl", encoding="utf-8")]
    assert {r["quality"] for r in rows} == {"dogrulanmis", "sorunlu", "kayitsiz"}  # dev: tüm maddeler
    preds = ml / "preds.jsonl"
    preds.write_text("".join(json.dumps({"id": r["id"], "prediction": r["target"]}) + "\n" for r in rows), encoding="utf-8")
    res = evaluate(str(preds), "dev", str(ml), raw)
    assert res["silver"]["tam_eslesme"] == 1.0 and res["silver"]["f1"] == 1.0
    v = res["verification"]["ornek"]
    assert v["model"]["oran"] == v["kural"]["oran"] and v["model"]["kayit"] == v["kural"]["kayit"]


def test_bos_tahmin_eden_model_cezalandirilir(tmp_path):
    raw, ml = _raw(tmp_path), tmp_path / "ml"
    write_dataset(["ornek"], {"ornek": "dev"}, raw, str(ml))
    export_seq2seq(str(ml), str(ml))
    rows = [json.loads(l) for l in open(ml / "seq2seq_dev.jsonl", encoding="utf-8")]
    preds = ml / "preds.jsonl"
    preds.write_text("".join(json.dumps({"id": r["id"], "prediction": "YOK"}) + "\n" for r in rows), encoding="utf-8")
    res = evaluate(str(preds), "dev", str(ml), raw)
    assert res["silver"]["recall"] == 0.0 and res["verification"]["ornek"]["model"]["kayit"] == 0


def test_kopyalama_kisiti_uydurulan_ibareyi_duzeltir():
    from mevzuatradar.ml.evaluate_model import snap_to_quotes
    girdi = ("MADDE 1- Aynı Yönetmeliğin geçici 1 inci maddesinde yer alan “30/6/2023 tarihine kadar” ibaresi "
             "“30/9/2023 tarihine kadar” şeklinde değiştirilmiştir.")
    uydurma = "30/6/2023 tarihli ve 6362 sayılı Sermaye Piyasası Kanunu ile " * 20
    recs = parse(f"IBARE_DEGISTIR | tur=gecici madde=1 | eski={uydurma} | yeni=30/9/2023 tarihine kadar")
    snap_to_quotes(recs, girdi)
    assert recs[0]["old_text"] == "30/6/2023 tarihine kadar" and recs[0]["new_text"] == "30/9/2023 tarihine kadar"


def test_kopyalama_kisiti_alakasiz_metne_dokunmaz():
    from mevzuatradar.ml.evaluate_model import snap_to_quotes
    recs = parse("IBARE_DEGISTIR | madde=5 | eski=tamamen başka bir şey | yeni=Kurul")
    snap_to_quotes(recs, "MADDE 1 – ... “Kurum” ibaresi “Kurul” şeklinde değiştirilmiştir.")
    assert recs[0]["old_text"] == "tamamen başka bir şey"  # benzerlik eşiğin altında: dokunulmaz


def test_tekrarlanan_kayitlar_tek_sayilir(tmp_path):
    raw, ml = _raw(tmp_path), tmp_path / "ml"
    write_dataset(["ornek"], {"ornek": "dev"}, raw, str(ml))
    export_seq2seq(str(ml), str(ml))
    rows = [json.loads(l) for l in open(ml / "seq2seq_dev.jsonl", encoding="utf-8")]
    preds = ml / "preds.jsonl"
    # Doğru tahmin, ama her değişikliği 5 kez tekrarlayan bir model
    tekrarli = lambda t: t if t == "YOK" else " ;; ".join([t] * 5)  # noqa: E731
    preds.write_text("".join(json.dumps({"id": r["id"], "prediction": tekrarli(r["target"])}) + "\n" for r in rows),
                     encoding="utf-8")
    res = evaluate(str(preds), "dev", str(ml), raw)
    v = res["verification"]["ornek"]
    assert v["model"]["kayit"] == v["kural"]["kayit"] and v["model"]["oran"] == v["kural"]["oran"]
    assert res["silver"]["tekrar_atilan"] > 0 and res["silver"]["f1"] == 1.0


def test_hibrit_kural_bos_kaldiginda_modeli_kullanir(tmp_path):
    raw, ml = _raw(tmp_path), tmp_path / "ml"
    write_dataset(["ornek"], {"ornek": "dev"}, raw, str(ml))
    export_seq2seq(str(ml), str(ml))
    rows = [json.loads(l) for l in open(ml / "seq2seq_dev.jsonl", encoding="utf-8")]
    preds = ml / "preds.jsonl"
    # Hiçbir şey bilmeyen model: hibrit, kural sistemiyle aynı olmalı
    preds.write_text("".join(json.dumps({"id": r["id"], "prediction": "YOK"}) + "\n" for r in rows), encoding="utf-8")
    v = evaluate(str(preds), "dev", str(ml), raw, snap=True)["verification"]["ornek"]
    assert v["hibrit"]["kayit"] == v["kural"]["kayit"] and v["hibrit"]["oran"] == v["kural"]["oran"]
    # Kuralın boş kaldığı yürürlük maddesinde (madde 4) doğru bir değişiklik "bulan" model: hibrite eklenir
    ekstra = "IBARE_DEGISTIR | madde=3 fikra=1 bent=a | birim=ibare | eski=Kurum | yeni=Kurul"
    preds.write_text("".join(json.dumps({"id": r["id"], "prediction": ekstra if r["id"].endswith("madde4") else "YOK"})
                             + "\n" for r in rows), encoding="utf-8")
    v = evaluate(str(preds), "dev", str(ml), raw, snap=True)["verification"]["ornek"]
    assert v["hibrit"]["kayit"] == v["kural"]["kayit"] + 1


def test_uclu_hibrit_ikinci_modeli_son_care_olarak_kullanir(tmp_path):
    raw, ml = _raw(tmp_path), tmp_path / "ml"
    write_dataset(["ornek"], {"ornek": "dev"}, raw, str(ml))
    export_seq2seq(str(ml), str(ml))
    rows = [json.loads(l) for l in open(ml / "seq2seq_dev.jsonl", encoding="utf-8")]
    dogru = "IBARE_DEGISTIR | madde=3 fikra=1 bent=a | birim=ibare | eski=Kurum | yeni=Kurul"
    bos = ml / "p1.jsonl"; ikinci = ml / "p2.jsonl"
    # 1. model hiçbir şey bulmuyor; 2. model kuralın boş geçtiği maddede doğru kayıt buluyor
    bos.write_text("".join(json.dumps({"id": r["id"], "prediction": "YOK"}) + "\n" for r in rows), encoding="utf-8")
    ikinci.write_text("".join(json.dumps({"id": r["id"], "prediction": dogru if r["id"].endswith("madde4") else "YOK"})
                              + "\n" for r in rows), encoding="utf-8")
    v = evaluate(str(bos), "dev", str(ml), raw, snap=True, pred2_path=str(ikinci))["verification"]["ornek"]
    assert v["hibrit"]["kayit"] == v["kural"]["kayit"]          # tek model: katkı yok
    assert v["hibrit3"]["kayit"] == v["kural"]["kayit"] + 1     # ikinci model devreye girdi
