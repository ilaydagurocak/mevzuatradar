"""Değişiklik kayıtlarını seq2seq modeli için kısa metne çevirir ve geri okur.

Tasarım:
- Girdi: değişiklik maddesinin metni; operatif cümleden sonraki uzun alıntı blokları
  [ALINTI1], [ALINTI2] ... etiketleriyle değiştirilir. Model uzun metin kopyalamaz.
- Çıktı: kayıtlar ' ;; ' ile ayrılır, her kayıt 'İŞLEM | konum | alanlar' biçimindedir.
  Kayıt yoksa 'YOK'. Birim işlemlerinin (fıkra/bent/madde ekleme-değiştirme) yeni metni
  çıktıda YOKTUR; sonradan alıntılardan, kural sistemiyle aynı dağıtım mantığıyla doldurulur.

Örnek:
  IBARE_DEGISTIR | madde=3 fikra=1 bent=ss | eski=tüzel kişiyi | yeni=organını ;; BIRIM_EKLE | madde=3 fikra=1 | birim=bent
"""
from __future__ import annotations

import re

from mevzuatradar.extract.amendments import _quote_spans

REC_SEP, PART_SEP = " ;; ", " | "
EMPTY = "YOK"
LOC_KEYS = [("madde_type", "tur"), ("madde", "madde"), ("fikra", "fikra"), ("bent", "bent"),
            ("alt_bent", "altbent"), ("cumle", "cumle")]
FIELD_KEYS = [("unit", "birim"), ("old_text", "eski"), ("new_text", "yeni"), ("anchor_text", "capa"),
              ("anchor_position", "konum"), ("insert_after", "sonra")]
# Yeni metni alıntı bloklarından gelen işlemler (modelin üretmediği alan)
BLOCK_OPS = {"BIRIM_DEGISTIR", "BIRIM_EKLE"}


def model_input(text: str) -> tuple[str, list[str]]:
    """(modele verilecek girdi, alıntı blokları). Operatif cümledeki kısa ibareler yerinde kalır."""
    lines = text.split("\n")
    operative, block = lines[0], "\n".join(lines[1:])
    quotes, parts, last = [], [], 0
    for a, b in _quote_spans(block):
        quotes.append(block[a + 1:b - 1].strip())
        parts.append(block[last:a])
        parts.append(f"[ALINTI{len(quotes)}]")
        last = b
    parts.append(block[last:])
    rest = re.sub(r"\s+", " ", "".join(parts)).strip()
    return (operative + (" " + rest if rest else "")).strip(), quotes


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v)).replace("|", "/").replace(";;", ";").strip()


def linearize(records: list[dict]) -> str:
    if not records:
        return EMPTY
    out = []
    for rec in records:
        loc = rec.get("location") or {}
        loc_str = " ".join(f"{short}={_clean(loc[k])}" for k, short in LOC_KEYS
                           if loc.get(k) not in (None, "") and not (k == "madde_type" and loc[k] == "normal"))
        fields = []
        for k, short in FIELD_KEYS:
            v = rec.get(k)
            if v in (None, ""):
                continue
            if k == "new_text" and rec.get("operation") in BLOCK_OPS:
                continue  # uzun alıntı metni modelin işi değil
            fields.append(f"{short}={_clean(v)}")
        out.append(PART_SEP.join([rec["operation"], loc_str or "-"] + fields))
    return REC_SEP.join(out)


def parse(text: str) -> list[dict]:
    """linearize()'ın tersi. Bozuk parçalar sessizce atlanır (model çıktısı hatalı olabilir)."""
    text = (text or "").strip()
    if not text or text == EMPTY:
        return []
    records = []
    for chunk in text.split(";;"):
        parts = [p.strip() for p in chunk.split("|")]
        if len(parts) < 2 or not re.fullmatch(r"[A-Z_]+", parts[0]):
            continue
        loc = {k: None for k, _ in LOC_KEYS}
        loc["madde_type"] = "normal"
        for item in parts[1].split():
            if "=" in item:
                key, val = item.split("=", 1)
                full = next((k for k, s in LOC_KEYS if s == key), None)
                if full:
                    loc[full] = int(val) if full in ("fikra", "alt_bent") and val.isdigit() else val
        rec = {"operation": parts[0], "location": loc}
        for p in parts[2:]:
            if "=" in p:
                key, val = p.split("=", 1)
                full = next((k for k, s in FIELD_KEYS if s == key.strip()), None)
                if full:
                    rec[full] = val.strip()
        records.append(rec)
    return records
