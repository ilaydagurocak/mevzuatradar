import json

from mevzuatradar.ml.linearize import parse
from mevzuatradar.ml.prompt import TALIMAT, build_messages, export_prompts, ornek_sec

TRAIN = [
    {"id": "a", "input": "MADDE 9 – Bu Yönetmelik yayımı tarihinde yürürlüğe girer.", "target": "YOK"},
    {"id": "b", "input": "MADDE 1 – ... “Kurum” ibaresi “Kurul” şeklinde değiştirilmiştir.",
     "target": "IBARE_DEGISTIR | madde=3 fikra=1 | birim=ibare | eski=Kurum | yeni=Kurul"},
    {"id": "c", "input": "MADDE 2 – ... aşağıdaki fıkra eklenmiştir. [ALINTI1]",
     "target": "BIRIM_EKLE | madde=8 | birim=fikra"},
    {"id": "d", "input": "MADDE 3 – ... üçüncü fıkrası yürürlükten kaldırılmıştır.",
     "target": "BIRIM_KALDIR | madde=6 fikra=3 | birim=fikra"},
    {"id": "e", "input": "MADDE 4 – ... çok değişiklikli uzun bir madde [ALINTI1]",
     "target": ("IBARE_DEGISTIR | madde=5 | birim=ibare | eski=a | yeni=b ;; "
                "BIRIM_DEGISTIR | madde=5 fikra=1 | birim=fikra ;; BASLIK_DEGISTIR | madde=5 | birim=baslik | yeni=Yeni")},
]


def test_ornekler_farkli_islem_turlerini_kapsar():
    secilen = ornek_sec(TRAIN, 5)
    islemler = {r["operation"] for row in secilen for r in parse(row["target"])}
    assert "YOK" in {row["target"] for row in secilen}          # "değişiklik yok" örneği
    assert {"IBARE_DEGISTIR", "BIRIM_EKLE", "BIRIM_KALDIR"} <= islemler
    assert secilen == ornek_sec(TRAIN, 5)                        # tekrarlanabilir


def test_istem_talimat_ve_ornek_ciftleri_icerir():
    m = build_messages("MADDE 7 – Test girdisi.", ornek_sec(TRAIN, 3))
    assert m[0]["role"] == "system" and "İŞLEMLER" in m[0]["content"]
    assert [x["role"] for x in m[1:-1]] == ["user", "assistant"] * 3
    assert m[-1] == {"role": "user", "content": "MADDE 7 – Test girdisi."}
    assert "ALINTI" in TALIMAT  # uzun alıntıların yazılmaması gerektiği anlatılıyor


def test_istem_dosyasi_yazilir(tmp_path):
    (tmp_path / "seq2seq_train.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in TRAIN), encoding="utf-8")
    (tmp_path / "seq2seq_dev.jsonl").write_text(
        json.dumps({"id": "x/y/madde1", "input": "MADDE 1 – Deneme.", "target": "YOK"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    yol, n = export_prompts("dev", 3, str(tmp_path))
    satir = json.loads(open(yol, encoding="utf-8").readline())
    assert n == 1 and satir["id"] == "x/y/madde1"
    assert satir["messages"][-1]["content"] == "MADDE 1 – Deneme." and len(satir["messages"]) == 8
