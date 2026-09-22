"""Değişiklik çıkarımını elle etiketlenmiş (gold) kayıtlarla karşılaştırır.

Bir tahmin, aşağıdaki alanların TAMAMI eşleşirse doğru sayılır (katı eşleşme).
Alan bazlı doğruluk ayrıca raporlanır; böylece hataların nerede yoğunlaştığı görülür.
"""
from __future__ import annotations

import json
import re
from collections import Counter

KEY_FIELDS = ["amending_article", "operation", "unit", "old_text", "new_text",
              "anchor_text", "anchor_position", "insert_after"]
LOC_FIELDS = ["madde_type", "madde", "fikra", "bent", "alt_bent"]


def _norm(v):
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v.replace("“", "").replace("”", "")).strip()
    return v


def record_key(rec: dict) -> tuple:
    loc = rec.get("location") or {}
    return tuple(_norm(rec.get(f)) for f in KEY_FIELDS) + tuple(_norm(loc.get(f)) for f in LOC_FIELDS)


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def evaluate(pred: list[dict], gold: list[dict]) -> dict:
    pc, gc = Counter(map(record_key, pred)), Counter(map(record_key, gold))
    tp = sum((pc & gc).values())
    p = tp / max(sum(pc.values()), 1)
    r = tp / max(sum(gc.values()), 1)
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {
        "precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3),
        "tp": tp, "n_pred": sum(pc.values()), "n_gold": sum(gc.values()),
        "missed": [dict(zip(KEY_FIELDS + LOC_FIELDS, k)) for k in (gc - pc).elements()],
        "spurious": [dict(zip(KEY_FIELDS + LOC_FIELDS, k)) for k in (pc - gc).elements()],
    }
