"""Büyük dil modeli (LLM) için istem (prompt) kurulumu.

Model eğitilmez; görev talimatla ve eğitim setinden seçilmiş birkaç örnekle anlatılır (few-shot).
Çıktı biçimi mT5 modeliyle AYNIDIR (bkz. ml/linearize.py), böylece üç sistem de aynı doğrulama
hattından geçer ve karşılaştırma adil olur.
"""
from __future__ import annotations

import json
from pathlib import Path

from mevzuatradar.ml.linearize import parse

TALIMAT = """Türk mevzuatındaki değişiklik maddelerini yapılandırılmış kayıtlara çeviren bir sistemsin.

Sana bir değişiklik yönetmeliğinin TEK bir maddesi verilir. Bu maddenin hangi düzenlemenin hangi
yerini nasıl değiştirdiğini çıkarır ve aşağıdaki biçimde yazarsın. Başka hiçbir açıklama yazma.

BİÇİM
Her kayıt: İŞLEM | konum | alan=değer | alan=değer
Birden çok kayıt ' ;; ' ile ayrılır. Madde hiçbir değişiklik yapmıyorsa (yürürlük, yürütme
maddeleri gibi) sadece: YOK

İŞLEMLER
IBARE_DEGISTIR  bir ibare başka bir ibareyle değiştirilir
IBARE_EKLE      bir ibareden sonra/önce yeni ibare eklenir
IBARE_KALDIR    bir ibare yürürlükten kaldırılır
BIRIM_DEGISTIR  madde/fıkra/bent/alt bent/cümle baştan yazılır
BIRIM_EKLE      yeni madde/fıkra/bent/alt bent/cümle eklenir
BIRIM_KALDIR    madde/fıkra/bent yürürlükten kaldırılır
BASLIK_DEGISTIR madde başlığı değiştirilir
EK_DEGISTIR / EK_EKLE   yönetmeliğin ekleri (EK-1, Ek-2 ...)

KONUM (yalnızca geçerli olanları yaz, boşlukla ayır)
tur=gecici|ek        madde geçici veya ek maddeyse
madde=5 | 26/A       hedef madde numarası
fikra=2              fıkra numarası (rakamla)
bent=c | ss          bent harfi
altbent=3            alt bent numarası
cumle=1 | 3,4        cümle numarası/numaraları
Konum yoksa tek tire yaz: -

ALANLAR
birim=ibare|madde|fikra|bent|alt_bent|cumle|baslik|ek
eski=...   değişen/kaldırılan ibare (metinde tırnak içinde geçtiği gibi)
yeni=...   yeni ibare veya yeni başlık
capa=...   IBARE_EKLE'de kendisinden sonra/önce eklenen ibare
konum=sonra|önce
sonra=...  eklemenin ardına geldiği fıkra/bent/madde

KURALLAR
- Uzun alıntı metinleri girdide [ALINTI1], [ALINTI2] ile gösterilir; bunları ASLA yazma.
  BIRIM_DEGISTIR ve BIRIM_EKLE kayıtlarında 'yeni' alanı YAZILMAZ.
- eski/yeni/capa alanlarını girdideki tırnak içi ifadelerden birebir kopyala, kendin üretme.
- Bir maddede birden çok değişiklik olabilir; her birini ayrı kayıt yaz, tekrar etme.
- "birinci, üçüncü ve beşinci fıkralarında" gibi çoklu hedefler ayrı kayıtlara açılır."""

# Örneklerin kapsaması istenen durumlar (sırayla aranır)
KAPSAM = [
    ("YOK", lambda recs: not recs),
    ("IBARE_DEGISTIR", lambda recs: any(r["operation"] == "IBARE_DEGISTIR" for r in recs)),
    ("IBARE_EKLE", lambda recs: any(r["operation"] == "IBARE_EKLE" for r in recs)),
    ("IBARE_KALDIR", lambda recs: any(r["operation"] == "IBARE_KALDIR" for r in recs)),
    ("BIRIM_DEGISTIR", lambda recs: any(r["operation"] == "BIRIM_DEGISTIR" for r in recs)),
    ("BIRIM_EKLE", lambda recs: any(r["operation"] == "BIRIM_EKLE" for r in recs)),
    ("BIRIM_KALDIR", lambda recs: any(r["operation"] == "BIRIM_KALDIR" for r in recs)),
    ("BASLIK_DEGISTIR", lambda recs: any(r["operation"] == "BASLIK_DEGISTIR" for r in recs)),
    ("cumle", lambda recs: any(r.get("unit") == "cumle" for r in recs)),
    ("coklu", lambda recs: len(recs) >= 3),
]


def ornek_sec(train_rows: list[dict], sayi: int = 10) -> list[dict]:
    """Her işlem türünden birer örnek seçer (kapsayıcı ve tekrarlanabilir: aynı girdi -> aynı seçim).
    Eşit kapsamda daha KISA örnek tercih edilir; istem uzamasın."""
    sirali = sorted(train_rows, key=lambda r: (len(r["input"]), r["id"]))
    secilen, kullanilan = [], set()
    for _, kosul in KAPSAM:
        if len(secilen) >= sayi:
            break
        for row in sirali:
            if row["id"] in kullanilan:
                continue
            if kosul(parse(row["target"])):
                secilen.append(row)
                kullanilan.add(row["id"])
                break
    return secilen[:sayi]


def build_messages(girdi: str, ornekler: list[dict]) -> list[dict]:
    """Sohbet biçiminde istem: talimat + örnek soru/cevap çiftleri + asıl madde."""
    mesajlar = [{"role": "system", "content": TALIMAT}]
    for ornek in ornekler:
        mesajlar.append({"role": "user", "content": ornek["input"]})
        mesajlar.append({"role": "assistant", "content": ornek["target"]})
    mesajlar.append({"role": "user", "content": girdi})
    return mesajlar


def export_prompts(split: str, shots: int = 10, data_dir: str = "data/ml") -> tuple[str, int]:
    """Bölmedeki her madde için istem üretir; (dosya yolu, örnek sayısı) döner."""
    d = Path(data_dir)
    train = [json.loads(l) for l in open(d / "seq2seq_train.jsonl", encoding="utf-8")]
    rows = [json.loads(l) for l in open(d / f"seq2seq_{split}.jsonl", encoding="utf-8")]
    ornekler = ornek_sec(train, shots)
    out = d / f"llm_{split}.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({"id": row["id"], "messages": build_messages(row["input"], ornekler)},
                               ensure_ascii=False) + "\n")
    return str(out), len(rows)
