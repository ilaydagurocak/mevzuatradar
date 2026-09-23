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


def _read_preds(path: str) -> dict[str, str]:
    out = {}
    for line in open(path, encoding="utf-8"):
        p = json.loads(line)
        out[p["id"]] = p.get("prediction", "")
    return out


def _by_article(ids: list[str], preds: dict, rows: dict, index: dict, n_amd: int, snap: bool) -> list[dict]:
    """Tahminleri (değişiklik dosyası, madde) -> kayıtlar biçiminde toplar."""
    out = [defaultdict(list) for _ in range(n_amd)]
    for rid in ids:
        _, prefix, madde = rid.split("/")
        recs, _ = dedupe(parse(preds.get(rid, "")))
        if snap:
            snap_to_quotes(recs, rows[rid]["input"])
        recs = fill_block_text(recs, rows[rid]["quotes"])
        art = madde.replace("madde", "", 1)
        for r in recs:
            r["amending_article"] = art
        if recs:
            out[index[prefix]][art].extend(recs)
    return out


def evaluate(pred_path: str, split: str = "dev", data_dir: str = "data/ml", raw_dir: str = "data/raw",
             snap: bool = False, pred2_path: str | None = None) -> dict:
    """pred2_path verilirse üçlü hibrit de hesaplanır: kural -> (boşsa) 1. model -> (boşsa) 2. model."""
    rows = {json.loads(l)["id"]: json.loads(l) for l in open(Path(data_dir) / f"seq2seq_{split}.jsonl", encoding="utf-8")}
    preds = _read_preds(pred_path)
    preds2 = _read_preds(pred2_path) if pred2_path else None

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
        model_art = _by_article(ids, preds, rows, index, len(amds), snap)
        model2_art = _by_article(ids, preds2, rows, index, len(amds), snap) if preds2 else None
        per_amd = [[r for art in sorted(d) for r in d[art]] for d in model_art]
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
        def _hibrit(kaynaklar: list) -> list[list[dict]]:
            """Her madde için sırayla ilk boş olmayan kaynağın kayıtları."""
            out = [[] for _ in amds]
            for i in range(len(amds)):
                articles = {a for (j, a) in rule_by_article if j == i}
                for d in kaynaklar:
                    articles |= set(d[i])
                for art in sorted(articles):
                    secim = rule_by_article.get((i, art)) or next(
                        (d[i][art] for d in kaynaklar if d[i].get(art)), [])
                    out[i].extend(secim)
            return out

        hybrid_results = verify_chronological(_hibrit([model_art]), kons_text)
        hybrid_results, _ = apply_known_issues(source, amds, hybrid_results, issues, urls)
        verification[source] = {"kural": _summ(rules.results), "model": _summ(model_results),
                                "hibrit": _summ(hybrid_results)}
        if model2_art is not None:
            uclu = verify_chronological(_hibrit([model_art, model2_art]), kons_text)
            uclu, _ = apply_known_issues(source, amds, uclu, issues, urls)
            verification[source]["hibrit3"] = _summ(uclu)
    silver["tekrar_atilan"] = n_dup
    return {"silver": silver, "verification": verification, "missing_predictions": len(set(rows) - set(preds))}
