"""Komut satırı arayüzü.

  mevzuatradar download --config configs/sources.yaml
  mevzuatradar parse    data/samples/ornek_yonetmelik.txt
  mevzuatradar extract  data/samples/ornek_degisiklik.txt --out preds.jsonl
  mevzuatradar evaluate --pred preds.jsonl --gold data/samples/ornek_degisiklik.gold.jsonl
  mevzuatradar verify   --consolidated KONSOLIDE.html --amendment DEGISIKLIK.html
  mevzuatradar find-amendments --source bddk_kart --write
  mevzuatradar verify-source --source bddk_kart
"""
from __future__ import annotations

import argparse
import json
import sys


def _write(records, out):
    fh = open(out, "w", encoding="utf-8") if out else sys.stdout
    for r in records:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    if out:
        fh.close()
        print(f"{len(records)} kayıt yazıldı: {out}")


def _find_amendments(args):
    import glob
    import os
    from pathlib import Path

    import requests
    import truststore
    import yaml

    from mevzuatradar.collect.rg_finder import (collect_refs, consolidated_annotation_sources,
                                                find_amendment_urls, keyword_from_name)

    cfg_path = Path(args.config)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    src = next((s for s in cfg["sources"] if s["id"] == args.source), None)
    if src is None:
        print(f"'{args.source}' kimlikli kaynak {args.config} içinde yok.")
        return
    files = glob.glob(f"{args.raw_dir}/{args.source}/konsolide_*")
    if not files:
        print("Konsolide metin bulunamadı; önce 'mevzuatradar download' çalıştırın.")
        return
    refs = collect_refs(consolidated_annotation_sources(max(files, key=os.path.getmtime)))
    keyword = keyword_from_name(src["name"])
    print(f"{len(refs)} değişiklik tarihi bulundu. Aranan başlık: '{keyword} ... Değişiklik'")

    truststore.inject_into_ssl()
    crawl = cfg.get("crawl", {})
    session = requests.Session()
    session.headers["User-Agent"] = crawl.get("user_agent", "MevzuatRadar/0.1")
    results = find_amendment_urls(session, refs, keyword,
                                  crawl.get("delay_seconds", 3), crawl.get("timeout_seconds", 30))
    found = []
    for ref, links, err in results:
        if err:
            print(f"[hata] {ref.label}: {err}")
        elif not links:
            print(f"[bulunamadı] {ref.label}  (içindekiler: {ref.index_url})")
        else:
            for title, url in links:
                print(f"[bulundu] {ref.label}: {url}\n    {title}")
                if url not in found:
                    found.append(url)
    ok = sum(1 for _, links, _ in results if links)
    print(f"Özet: {len(refs)} tarihin {ok} tanesi için bağlantı bulundu.")

    if args.write and found:
        existing = [a if isinstance(a, str) else a.get("url") for a in (src.get("amendments") or [])]
        src["amendments"] = existing + [u for u in found if u not in existing]
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
        print(f"{args.config} güncellendi ({len(src['amendments'])} değişiklik bağlantısı).")
    elif found:
        print("Bağlantıları sources.yaml'a eklemek için komutu --write ile tekrar çalıştırın.")


def _verify_source(args):
    import glob
    import os
    from pathlib import Path

    from mevzuatradar.extract.amendments import extract_amendments
    from mevzuatradar.extract.verify import verify_chronological
    from mevzuatradar.parse.text_extract import extract_text

    base = f"{args.raw_dir}/{args.source}"
    kons = glob.glob(f"{base}/konsolide_*")
    amds = sorted(glob.glob(f"{base}/degisiklik*"))  # degisiklik00, 01, ... = tarih sırası
    if not kons or not amds:
        print("Konsolide metin veya değişiklik metni bulunamadı; önce 'download' çalıştırın.")
        return
    per_amd = [[a.to_dict() for a in extract_amendments(extract_text(f).text)] for f in amds]
    results = verify_chronological(per_amd, extract_text(max(kons, key=os.path.getmtime)).text)

    counts: dict[str, int] = {}
    for i, rec, res in results:
        counts[res.status] = counts.get(res.status, 0) + 1
        if args.verbose or res.status in ("uyumsuz", "hedef_bulunamadi", "kontrol_edilemedi"):
            loc = rec["location"]
            print(f"[{res.status}] {Path(amds[i]).name[:12]} madde {rec['amending_article']}: {rec['operation']} "
                  f"→ madde {loc['madde']}, fıkra {loc['fikra']}, bent {loc['bent']} | {res.detail}")
            if args.show_diff and res.status == "uyumsuz":
                print(f"    beklenen: {res.expected}\n    bulunan : {res.actual}")

    total = sum(counts.values())
    checkable = sum(counts.get(k, 0) for k in ("uyumlu", "uyumsuz", "hedef_bulunamadi"))
    print(f"\n{len(amds)} değişiklik yönetmeliği, {total} değişiklik kaydı")
    for k in ("uyumlu", "sonradan_degisti", "uyumsuz", "hedef_bulunamadi", "kontrol_edilemedi"):
        print(f"  {k:<18} {counts.get(k, 0)}")
    if checkable:
        print(f"Doğrulama oranı (sonradan değişenler hariç): {counts.get('uyumlu', 0) / checkable:.1%}")

    out = Path("reports"); out.mkdir(exist_ok=True)
    with open(out / f"verify_{args.source}.jsonl", "w", encoding="utf-8") as fh:
        for i, rec, res in results:
            fh.write(json.dumps({"amendment_file": Path(amds[i]).name, **rec,
                                 "status": res.status, "detail": res.detail}, ensure_ascii=False) + "\n")
    print(f"Ayrıntılı rapor: reports/verify_{args.source}.jsonl")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mevzuatradar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download"); d.add_argument("--config", default="configs/sources.yaml")
    d.add_argument("--raw-dir", default="data/raw")
    p = sub.add_parser("parse"); p.add_argument("path"); p.add_argument("--out")
    e = sub.add_parser("extract"); e.add_argument("path"); e.add_argument("--out")
    v = sub.add_parser("evaluate"); v.add_argument("--pred", required=True); v.add_argument("--gold", required=True)
    vf = sub.add_parser("verify"); vf.add_argument("--consolidated", required=True)
    vf.add_argument("--amendment", required=True); vf.add_argument("--show-diff", action="store_true")
    fa = sub.add_parser("find-amendments"); fa.add_argument("--source", required=True)
    fa.add_argument("--config", default="configs/sources.yaml"); fa.add_argument("--raw-dir", default="data/raw")
    fa.add_argument("--write", action="store_true")
    vs = sub.add_parser("verify-source"); vs.add_argument("--source", required=True)
    vs.add_argument("--raw-dir", default="data/raw"); vs.add_argument("--show-diff", action="store_true")
    vs.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "download":
        from mevzuatradar.collect.downloader import run
        run(args.config, args.raw_dir)
    elif args.cmd in ("parse", "extract"):
        from mevzuatradar.parse.text_extract import extract_text
        ext = extract_text(args.path)
        if ext.needs_ocr:
            print("Uyarı: dosya taranmış görünüyor (metin katmanı yok); OCR/VLM modülü gerekli.", file=sys.stderr)
        if args.cmd == "parse":
            from mevzuatradar.parse.structure import parse_structure
            doc = parse_structure(ext.text).to_dict()
            text = json.dumps(doc, ensure_ascii=False, indent=2)
            if args.out:
                open(args.out, "w", encoding="utf-8").write(text)
                print(f"{len(doc['maddeler'])} madde yazıldı: {args.out}")
            else:
                print(text)
        else:
            from mevzuatradar.extract.amendments import extract_amendments
            _write([a.to_dict() for a in extract_amendments(ext.text)], args.out)
    elif args.cmd == "verify":
        from mevzuatradar.extract.amendments import extract_amendments
        from mevzuatradar.extract.verify import verify
        from mevzuatradar.parse.text_extract import extract_text
        records = [a.to_dict() for a in extract_amendments(extract_text(args.amendment).text)]
        results = verify(records, extract_text(args.consolidated).text)
        for rec, res in results:
            loc = rec["location"]
            print(f"[{res.status}] madde {rec['amending_article']}: {rec['operation']} → "
                  f"hedef madde {loc['madde']}, fıkra {loc['fikra']}, bent {loc['bent']} | {res.detail}")
            if args.show_diff and res.status == "uyumsuz":
                print(f"    beklenen: {res.expected}\n    bulunan : {res.actual}")
        counts = {}
        for _, res in results:
            counts[res.status] = counts.get(res.status, 0) + 1
        print("Özet:", counts if counts else "değişiklik kaydı bulunamadı")
    elif args.cmd == "verify-source":
        _verify_source(args)
    elif args.cmd == "find-amendments":
        _find_amendments(args)
    elif args.cmd == "evaluate":
        from mevzuatradar.extract.evaluate import evaluate, load_jsonl
        res = evaluate(load_jsonl(args.pred), load_jsonl(args.gold))
        print(f"Precision {res['precision']}  Recall {res['recall']}  F1 {res['f1']}  "
              f"(doğru {res['tp']} / tahmin {res['n_pred']} / gold {res['n_gold']})")
        for label in ("missed", "spurious"):
            for r in res[label]:
                print(f"  [{'kaçırılan' if label == 'missed' else 'hatalı'}] madde {r['amending_article']}: "
                      f"{r['operation']} → hedef madde {r['madde']}, fıkra {r['fikra']}, bent {r['bent']}")


if __name__ == "__main__":
    main()
