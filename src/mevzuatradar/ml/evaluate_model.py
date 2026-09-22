"""Model tahminlerini kural sistemiyle AYNI ölçütlerle değerlendirir.

1) Gümüş etiket uyumu: güvenilir örneklerde modelin kayıtları kural+doğrulama çıktısıyla ne kadar örtüşüyor
   (madde bazında tam eşleşme ve kayıt bazında precision/recall/F1).
2) Doğrulama: modelin kayıtları, alıntılar yerlerine konduktan sonra konsolide metinle doğrulanır;
   kural sisteminin doğrulama tablosuyla yan yana raporlanır.
"""
from __future__ import annotations

import glob
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from mevzuatradar.extract.known_issues import apply_known_issues, file_urls, load_issues
from mevzuatradar.extract.pipeline import process_source
from mevzuatradar.extract.verify import verify_chronological
from mevzuatradar.ml.dataset import TRUSTED
from mevzuatradar.ml.linearize import BLOCK_OPS, parse
from mevzuatradar.parse.text_extract import extract_text

KEY_LOC = ["madde_type", "madde", "fikra", "bent", "alt_bent", "cumle"]


def record_key(rec: dict) -> tuple:
    loc = rec.get("location") or {}
    txt = lambda v: re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else None  # noqa: E731
    new = None if rec.get("operation") in BLOCK_OPS else txt(rec.get("new_text"))
    return (rec.get("operation"), rec.get("unit"), *(str(loc.get(k)) if loc.get(k) is not None else None
                                                      for k in KEY_LOC),
            txt(rec.get("old_text")), new, txt(rec.get("anchor_text")))


def _marker_chunk(rec: dict, joined: str) -> str | None:
    loc = rec.get("location") or {}
    if loc.get("alt_bent") is not None and rec.get("unit") == "alt_bent":
        pat, key = r"(?m)^\s*(\d+)\)\s", str(loc["alt_bent"])
    elif loc.get("bent") and rec.get("unit") == "bent":
        pat, key = r"(?m)^\s*([a-zçğıöşü]{1,3})\)\s", loc["bent"]
    elif loc.get("fikra") is not None and rec.get("unit") == "fikra":
        pat, key = r"(?m)^\s*\((\d+)\)\s", str(loc["fikra"])
    else:
        return None
    hits = list(re.finditer(pat, joined))
    if len(hits) < 2:
        return None
    return next((joined[h.start():(hits[k + 1].start() if k + 1 < len(hits) else len(joined))].strip()
                 for k, h in enumerate(hits) if h.group(1) == key), None)


def fill_block_text(records: list[dict], quotes: list[str]) -> list[dict]:
    """Modelin üretmediği uzun yeni metinleri alıntılardan doldurur. Sıra:
    1) her hedef kendi işaretini ((n), x), n)) birleşik alıntıda bulabiliyorsa işarete göre,
    2) hedef ve alıntı sayısı eşitse sırayla, 3) aksi halde birleşik metin."""
    blocks = [r for r in records if r["operation"] in BLOCK_OPS]
    if not blocks or not quotes:
        return records
    joined = "\n".join(quotes)
    chunks = [_marker_chunk(r, joined) for r in blocks] if len(blocks) > 1 else [None]
    if all(chunks):
        for r, c in zip(blocks, chunks):
            r["new_text"] = c
    elif len(blocks) == len(quotes):
        for r, q in zip(blocks, quotes):
            r["new_text"] = q
    else:
        for r in blocks:
            r["new_text"] = joined
    return records


TEXT_FIELDS = ("old_text", "new_text", "anchor_text")


def _norm_txt(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()


def snap_to_quotes(records: list[dict], model_input_text: str, threshold: float = 0.5) -> list[dict]:
    """Kopyalama kısıtı: değişiklik cümlelerinde ibareler her zaman girdide tırnak içinde yazılıdır.
    Modelin ürettiği ibare, girdideki en benzer tırnaklı ifadeyle değiştirilir; böylece model konumu ve
    işlemi kendisi çözer ama metni uyduramaz (ezberden kopyalama, tekrar döngüleri).
    Benzerlik, üretilen metnin tırnak uzunluğu kadar başıyla ölçülür; eşiğin altındaysa dokunulmaz."""
    from difflib import SequenceMatcher

    quotes = [q.strip() for q in re.findall(r"“([^”]*)”", model_input_text) if q.strip()]
    if not quotes:
        return records
    for rec in records:
        for field in TEXT_FIELDS:
            val = rec.get(field)
            if not val or (field == "new_text" and rec.get("operation") in BLOCK_OPS):
                continue
            if val in quotes:
                continue
            nv = _norm_txt(val)
            best, score = None, 0.0
            for q in quotes:
                nq = _norm_txt(q)
                s_ = SequenceMatcher(None, nv[: len(nq) + 10], nq).ratio()
                if s_ > score:
                    best, score = q, s_
            if best is not None and score >= threshold:
                rec[field] = best
    return records


def dedupe(records: list[dict]) -> tuple[list[dict], int]:
    """Aynı maddede birebir aynı kayıtları bir kez tutar. Üretici modeller kayıt düzeyinde tekrar döngüsüne
    girebilir; her kopyanın ayrı 'uyumlu' sayılması sonucu şişirir. Dönüş: (tekilleştirilmiş, atılan sayısı)."""
    seen, out = set(), []
    for r in records:
        k = record_key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out, len(records) - len(out)


def _summ(results) -> dict:
    c = Counter(res.status for _, _, res in results)
    checkable = c["uyumlu"] + c["uyumsuz"] + c["hedef_bulunamadi"]
    return {"kayit": len(results), **c, "oran": c["uyumlu"] / checkable if checkable else None}


def evaluate(pred_path: str, split: str = "dev", data_dir: str = "data/ml", raw_dir: str = "data/raw",
             snap: bool = False) -> dict:
    rows = {json.loads(l)["id"]: json.loads(l) for l in open(Path(data_dir) / f"seq2seq_{split}.jsonl", encoding="utf-8")}
    preds = {}
    for line in open(pred_path, encoding="utf-8"):
        p = json.loads(line)
        preds[p["id"]] = p.get("prediction", "")

    # 1) Gümüş etiket uyumu
    tp = n_pred = n_gold = exact = n_trusted = n_dup = 0
    for rid, row in rows.items():
        if row["quality"] not in TRUSTED:
            continue
        n_trusted += 1
        gold = Counter(record_key(r) for r in parse(row["target"]))
        pr, dup = dedupe(parse(preds.get(rid, "")))
        n_dup += dup
        if snap:
            snap_to_quotes(pr, row["input"])
        pred = Counter(record_key(r) for r in pr)
        tp += sum((gold & pred).values()); n_pred += sum(pred.values()); n_gold += sum(gold.values())
        exact += gold == pred
    prec = tp / n_pred if n_pred else 0.0
    rec = tp / n_gold if n_gold else 0.0
    silver = {"ornek": n_trusted, "tam_eslesme": exact / n_trusted if n_trusted else None,
              "precision": prec, "recall": rec, "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0}

    # 2) Doğrulama: kaynak bazında model kayıtları vs kural sistemi
    by_source = defaultdict(list)
    for rid, row in rows.items():
        by_source[row["source"]].append(rid)
    issues, urls = load_issues(), file_urls(raw_dir)
    verification = {}
    for source, ids in sorted(by_source.items()):
        amds = sorted(glob.glob(f"{raw_dir}/{source}/degisiklik*"))
        kons = glob.glob(f"{raw_dir}/{source}/konsolide_*")
        if not amds or not kons:
            continue
        index = {Path(a).name.split("_")[0]: i for i, a in enumerate(amds)}
        per_amd = [[] for _ in amds]
        for rid in ids:
            _, prefix, madde = rid.split("/")
            recs, _ = dedupe(parse(preds.get(rid, "")))
            if snap:
                snap_to_quotes(recs, rows[rid]["input"])
            recs = fill_block_text(recs, rows[rid]["quotes"])
            for r in recs:
                r["amending_article"] = madde.replace("madde", "", 1)
            per_amd[index[prefix]].extend(recs)
        kons_text = extract_text(max(kons, key=os.path.getmtime)).text
        model_results = verify_chronological(per_amd, kons_text)
        model_results, _ = apply_known_issues(source, amds, model_results, issues, urls)
        rules = process_source(source, raw_dir)

        # Hibrit (önceden tanımlı, doğrulama sinyali KULLANMAZ): her madde için kural sisteminin kayıtları;
        # kural sistemi o maddede hiçbir kayıt çıkarmadıysa modelin kayıtları.
        rule_by_article = defaultdict(list)
        for i, rec, _ in rules.results:
            rule_by_article[(i, str(rec.get("amending_article")))].append(
                {k: v for k, v in rec.items() if k != "target_regulation"})
        hybrid = [[] for _ in amds]
        for i, recs in enumerate(per_amd):
            by_art = defaultdict(list)
            for r in recs:
                by_art[str(r["amending_article"])].append(r)
            articles = {a for (j, a) in rule_by_article if j == i} | set(by_art)
            for art in sorted(articles):
                hybrid[i].extend(rule_by_article.get((i, art)) or by_art.get(art, []))
        hybrid_results = verify_chronological(hybrid, kons_text)
        hybrid_results, _ = apply_known_issues(source, amds, hybrid_results, issues, urls)
        verification[source] = {"kural": _summ(rules.results), "model": _summ(model_results),
                                "hibrit": _summ(hybrid_results)}
    silver["tekrar_atilan"] = n_dup
    return {"silver": silver, "verification": verification, "missing_predictions": len(set(rows) - set(preds))}
