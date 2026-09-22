"""Kural sistemi + doğrulama çıktılarından makine öğrenmesi veri seti üretir (gümüş etiketler).

Her örnek bir değişiklik maddesidir:
  girdi : maddenin tam metni (operatif cümle + alıntılar)
  çıktı : o maddeden çıkarılan değişiklik kayıtları
  kalite: dogrulanmis | kismen | sorunlu | kayitsiz | supheli

Bölme yönetmelik bazında yapılır (aynı yönetmelik iki bölmede birden bulunmaz).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from mevzuatradar.extract.pipeline import process_source
from mevzuatradar.parse.structure import parse_structure
from mevzuatradar.parse.text_extract import extract_text

# Hedef çıktıda tutulan alanlar (kaynağa özgü "target_regulation" gibi alanlar modele öğretilmez)
TARGET_FIELDS = ["operation", "unit", "location", "old_text", "new_text", "anchor_text",
                 "anchor_position", "insert_after"]
LOC_FIELDS = ["madde_type", "madde", "fikra", "bent", "alt_bent", "cumle"]


def canonical_record(rec: dict) -> dict:
    out = {k: rec.get(k) for k in TARGET_FIELDS if k != "location"}
    loc = rec.get("location") or {}
    out["location"] = {k: loc.get(k) for k in LOC_FIELDS}
    return {k: v for k, v in out.items() if v not in (None, {}) or k == "location"}


BOILERPLATE = re.compile(r"yürürlüğe\s+gir|yürütür")


def quality(statuses: list[str], text: str = "") -> str:
    """kayitsiz: kural sistemi kayıt çıkarmadı VE madde bir yürürlük/yürütme maddesi (güvenli negatif).
    supheli : kayıt çıkmadı ama madde standart bir madde değil; kaçırılmış değişiklik olabilir,
              eğitime 'değişiklik yok' diye girmemeli."""
    if not statuses:
        return "kayitsiz" if BOILERPLATE.search(text) else "supheli"
    if all(s == "uyumlu" for s in statuses):
        return "dogrulanmis"
    if all(s in ("uyumlu", "sonradan_degisti", "kontrol_edilemedi") for s in statuses):
        return "kismen"
    return "sorunlu"


def build_examples(source: str, raw_dir: str = "data/raw") -> list[dict]:
    run = process_source(source, raw_dir)
    if run is None:
        return []
    examples = []
    for i, path in enumerate(run.amendment_files):
        doc = parse_structure(extract_text(path).text)
        for madde in doc.maddeler:
            hits = [(rec, res) for idx, rec, res in run.results
                    if idx == i and str(rec.get("amending_article")) == madde.key]
            statuses = [res.status for _, res in hits]
            examples.append({
                "id": f"{source}/{Path(path).stem.split('_')[0]}/madde{madde.key}",
                "source": source,
                "amendment_file": Path(path).name,
                "amendment_url": run.urls.get(Path(path).name),
                "article": madde.key,
                "text": madde.raw_text,
                "records": [canonical_record(rec) for rec, _ in hits],
                "statuses": statuses,
                "quality": quality(statuses, madde.raw_text),
            })
    return examples


def write_dataset(sources: list[str], split_of: dict[str, str], raw_dir: str = "data/raw",
                  out_dir: str = "data/ml") -> dict:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    handles, stats = {}, Counter()
    try:
        for src in sources:
            split = split_of.get(src, "train")
            if split not in handles:
                handles[split] = open(out / f"{split}.jsonl", "w", encoding="utf-8")
            for ex in build_examples(src, raw_dir):
                ex["split"] = split
                handles[split].write(json.dumps(ex, ensure_ascii=False) + "\n")
                stats[(split, src, ex["quality"])] += 1
    finally:
        for h in handles.values():
            h.close()
    return stats


TRUSTED = ("dogrulanmis", "kayitsiz")


def export_seq2seq(in_dir: str = "data/ml", out_dir: str = "data/ml") -> Counter:
    """Veri setini seq2seq biçimine çevirir: {id, source, input, target, quotes, quality}.
    - train: yalnızca güvenilir örnekler (doğrulanmış + gerçek yürürlük/yürütme maddeleri).
    - dev/test: TÜM maddeler; model de kural sistemi gibi her maddede tahmin yapar.
      'target' yalnızca güvenilir örneklerde gümüş etiket olarak anlamlıdır."""
    from mevzuatradar.ml.linearize import linearize, model_input

    stats = Counter()
    for split in ("train", "dev", "test"):
        src = Path(in_dir) / f"{split}.jsonl"
        if not src.exists():
            continue
        with open(src, encoding="utf-8") as fin, \
                open(Path(out_dir) / f"seq2seq_{split}.jsonl", "w", encoding="utf-8") as fout:
            for line in fin:
                ex = json.loads(line)
                if split == "train" and ex["quality"] not in TRUSTED:
                    continue
                inp, quotes = model_input(ex["text"])
                row = {"id": ex["id"], "source": ex["source"], "input": inp,
                       "target": linearize(ex["records"]), "quotes": quotes, "quality": ex["quality"]}
                fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                stats[(split, ex["quality"])] += 1
                stats[(split, "max_input_chars")] = max(stats[(split, "max_input_chars")], len(inp))
                stats[(split, "max_target_chars")] = max(stats[(split, "max_target_chars")], len(row["target"]))
    return stats
