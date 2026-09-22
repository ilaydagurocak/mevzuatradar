"""Komut satırı arayüzü.

  mevzuatradar download --config configs/sources.yaml
  mevzuatradar parse    data/samples/ornek_yonetmelik.txt
  mevzuatradar extract  data/samples/ornek_degisiklik.txt --out preds.jsonl
  mevzuatradar evaluate --pred preds.jsonl --gold data/samples/ornek_degisiklik.gold.jsonl
  mevzuatradar verify   --consolidated KONSOLIDE.html --amendment DEGISIKLIK.html
  mevzuatradar find-amendments --source bddk_kart --write
  mevzuatradar verify-source --source bddk_kart
  mevzuatradar verify-all [--min-rate 0.95]
  mevzuatradar build-dataset
  mevzuatradar add-source --id bddk_x --name "..." --issuer BDDK --url "<mevzuat.gov.tr sayfa adresi>" --split train
  mevzuatradar find-amendments --all --write
  mevzuatradar export-seq2seq
  mevzuatradar evaluate-model --pred data/ml/preds_dev.jsonl --split dev
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
    keyword = [keyword_from_name(n) for n in [src["name"], *(src.get("former_names") or [])]]
    print(f"{len(refs)} değişiklik tarihi bulundu. Aranan başlık(lar): "
          + " | ".join(f"'{k} ... Değişiklik'" for k in keyword))

    truststore.inject_into_ssl()
    crawl = cfg.get("crawl", {})
    session = requests.Session()
    session.headers["User-Agent"] = crawl.get("user_agent", "MevzuatRadar/0.1")
    from mevzuatradar.collect.polite import RobotsChecker
    robots = RobotsChecker(session, session.headers["User-Agent"], crawl.get("timeout_seconds", 30))
    results = find_amendment_urls(session, refs, keyword, crawl.get("delay_seconds", 3),
                                  crawl.get("timeout_seconds", 30), robots=robots)
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
    for site, note in robots.notes.items():
        print(f"[robots] {site}: {note}")
    ok = sum(1 for _, links, _ in results if links)
    print(f"Özet: {len(refs)} tarihin {ok} tanesi için bağlantı bulundu.")

    if args.write and found:
        existing = [a if isinstance(a, str) else a.get("url") for a in (src.get("amendments") or [])]
        src["amendments"] = existing + [u for u in found if u not in existing]
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
        print(f"{args.config} güncellendi ({len(src['amendments'])} değişiklik bağlantısı).")
    elif found:
        print("Bağlantıları sources.yaml'a eklemek için komutu --write ile tekrar çalıştırın.")


def _run_verify(source: str, raw_dir: str):
    """Bir kaynağın tüm değişikliklerini çıkarıp konsolide metinle doğrular. (dosyalar, sonuçlar) döner."""
    from mevzuatradar.extract.pipeline import process_source

    run = process_source(source, raw_dir)
    if run is None:
        return [], None
    for iid in run.resolved_issues:
        print(f"[bilgi] Bilinen kaynak tutarsızlığı '{iid}' artık görünmüyor (doğrulama geçiyor); "
              f"configs/known_source_issues.yaml içinden kaldırılabilir.")
    return run.amendment_files, run.results


def _summarize(results) -> dict:
    counts = {k: 0 for k in ("uyumlu", "sonradan_degisti", "uyumsuz", "hedef_bulunamadi",
                             "kontrol_edilemedi", "kaynak_tutarsizligi")}
    for _, _, res in results:
        counts[res.status] = counts.get(res.status, 0) + 1
    checkable = counts["uyumlu"] + counts["uyumsuz"] + counts["hedef_bulunamadi"]
    counts["oran"] = counts["uyumlu"] / checkable if checkable else None
    return counts


def _write_report(source: str, amds, results) -> str:
    from pathlib import Path

    out = Path("reports"); out.mkdir(exist_ok=True)
    path = out / f"verify_{source}.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for i, rec, res in results:
            fh.write(json.dumps({"amendment_file": Path(amds[i]).name, **rec,
                                 "status": res.status, "detail": res.detail}, ensure_ascii=False) + "\n")
    return str(path)


def _verify_source(args):
    from pathlib import Path

    amds, results = _run_verify(args.source, args.raw_dir)
    if results is None:
        print("Konsolide metin veya değişiklik metni bulunamadı; önce 'download' çalıştırın.")
        return
    for i, rec, res in results:
        if args.verbose or res.status in ("uyumsuz", "hedef_bulunamadi", "kontrol_edilemedi", "kaynak_tutarsizligi"):
            loc = rec["location"]
            print(f"[{res.status}] {Path(amds[i]).name[:12]} madde {rec['amending_article']}: {rec['operation']} "
                  f"→ madde {loc.get('madde_type', 'normal')}:{loc['madde']}, fıkra {loc['fikra']}, "
                  f"bent {loc['bent']}, alt bent {loc.get('alt_bent')}, cümle {loc.get('cumle')} | {res.detail}")
            if args.show_diff and res.status == "uyumsuz":
                print(f"    beklenen: {res.expected}\n    bulunan : {res.actual}")
    c = _summarize(results)
    print(f"\n{len(amds)} değişiklik yönetmeliği, {len(results)} değişiklik kaydı")
    for k in ("uyumlu", "sonradan_degisti", "uyumsuz", "hedef_bulunamadi", "kontrol_edilemedi", "kaynak_tutarsizligi"):
        print(f"  {k:<20} {c[k]}")
    if c["oran"] is not None:
        print(f"Doğrulama oranı (sonradan değişenler ve kaynak tutarsızlıkları hariç): {c['oran']:.1%}")
    print(f"Ayrıntılı rapor: {_write_report(args.source, amds, results)}")


def _verify_all(args):
    import yaml
    from pathlib import Path

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    rows, tot = [], {"kayit": 0, "uyumlu": 0, "kontrol": 0}
    for src in cfg["sources"]:
        amds, results = _run_verify(src["id"], args.raw_dir)
        if results is None:
            continue
        _write_report(src["id"], amds, results)
        c = _summarize(results)
        rows.append((src["id"], len(amds), len(results), c))
        tot["kayit"] += len(results)
        tot["uyumlu"] += c["uyumlu"]
        tot["kontrol"] += c["uyumlu"] + c["uyumsuz"] + c["hedef_bulunamadi"]
    print(f"{'kaynak':<28}{'değ.':>5}{'kayıt':>7}{'uyumlu':>8}{'sonra':>7}{'uyumsuz':>9}{'bulunam.':>10}"
          f"{'kontrol-':>10}{'kaynak-hata':>12}{'oran':>8}")
    for sid, n_amd, n_rec, c in rows:
        oran = f"{c['oran']:.1%}" if c["oran"] is not None else "-"
        print(f"{sid:<28}{n_amd:>5}{n_rec:>7}{c['uyumlu']:>8}{c['sonradan_degisti']:>7}{c['uyumsuz']:>9}"
              f"{c['hedef_bulunamadi']:>10}{c['kontrol_edilemedi']:>10}{c['kaynak_tutarsizligi']:>12}{oran:>8}")
    if tot["kontrol"]:
        genel = tot["uyumlu"] / tot["kontrol"]
        print(f"\nToplam: {tot['kayit']} kayıt, genel doğrulama oranı {genel:.1%}")
        if args.min_rate is not None and genel < args.min_rate:
            print(f"HATA: oran {args.min_rate:.1%} eşiğinin altında.")
            sys.exit(1)


def _build_dataset(args):
    import yaml
    from collections import defaultdict
    from pathlib import Path

    from mevzuatradar.ml.dataset import write_dataset

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    splits = yaml.safe_load(Path(args.splits).read_text(encoding="utf-8")) if Path(args.splits).exists() else {}
    split_of = {src: name for name, srcs in (splits or {}).items() for src in (srcs or [])}
    sources = [s["id"] for s in cfg["sources"]]
    stats = write_dataset(sources, split_of, args.raw_dir, args.out_dir)

    table = defaultdict(lambda: defaultdict(int))
    for (split, src, q), n in stats.items():
        table[(split, src)][q] += n
    cols = ["dogrulanmis", "kismen", "sorunlu", "kayitsiz", "supheli"]
    print(f"{'bölme':<7}{'kaynak':<28}" + "".join(f"{c:>13}" for c in cols))
    for (split, src), row in sorted(table.items()):
        print(f"{split:<7}{src:<28}" + "".join(f"{row[c]:>13}" for c in cols))
    for split in sorted({k[0] for k in table}):
        tot = {c: sum(r[c] for (sp, _), r in table.items() if sp == split) for c in cols}
        print(f"{split:<7}{'TOPLAM':<28}" + "".join(f"{tot[c]:>13}" for c in cols))
    print(f"Veri seti yazıldı: {args.out_dir}/<bölme>.jsonl")


def _add_source(args):
    from mevzuatradar.collect.sources import add_source

    iframe = add_source(args.id, args.name, args.issuer, args.url, args.split, args.config, args.splits,
                        former_names=args.former_name)
    print(f"'{args.id}' eklendi ({args.split} bölmesi).\nMetin adresi: {iframe}")


def _export_seq2seq(args):
    from mevzuatradar.ml.dataset import export_seq2seq

    st = export_seq2seq(args.in_dir, args.out_dir)
    for split in ("train", "dev", "test"):
        qs = {q: n for (sp, q), n in st.items() if sp == split and not q.startswith("max_")}
        if qs:
            detay = ", ".join(f"{q} {n}" for q, n in sorted(qs.items()))
            print(f"{split:<6} {sum(qs.values()):>4} örnek ({detay}) | en uzun girdi "
                  f"{st[(split, 'max_input_chars')]} karakter, en uzun hedef {st[(split, 'max_target_chars')]}")
    print(f"Yazıldı: {args.out_dir}/seq2seq_<bölme>.jsonl")


def _evaluate_model(args):
    from mevzuatradar.ml.evaluate_model import evaluate

    raw = evaluate(args.pred, args.split, args.data_dir, args.raw_dir, snap=False)
    snapped = evaluate(args.pred, args.split, args.data_dir, args.raw_dir, snap=True)
    for label, res in (("model (ham)", raw), ("model + kopyalama kısıtı", snapped)):
        s = res["silver"]
        print(f"{label:<26} gümüş etiket ({s['ornek']} örnek): tam eşleşme {s['tam_eslesme']:.1%} | "
              f"kayıt P {s['precision']:.1%} R {s['recall']:.1%} F1 {s['f1']:.1%}")
    print(f"Güvenilir örneklerde tekrarlanan (tekilleştirilen) model kaydı: {raw['silver']['tekrar_atilan']}")
    if raw["missing_predictions"]:
        print(f"UYARI: {raw['missing_predictions']} örnek için tahmin yok (boş sayıldı).")
    print(f"\n{'kaynak':<24}{'sistem':<18}{'kayıt':>6}{'uyumlu':>8}{'uyumsuz':>9}{'bulunam.':>10}{'kontrol-':>10}{'oran':>8}")
    for src in raw["verification"]:
        rows = [("kural", raw["verification"][src]["kural"]), ("model (ham)", raw["verification"][src]["model"]),
                ("model + kısıt", snapped["verification"][src]["model"]),
                ("hibrit", snapped["verification"][src]["hibrit"])]
        for name, c in rows:
            oran = f"{c['oran']:.1%}" if c["oran"] is not None else "-"
            print(f"{src:<24}{name:<18}{c['kayit']:>6}{c.get('uyumlu', 0):>8}{c.get('uyumsuz', 0):>9}"
                  f"{c.get('hedef_bulunamadi', 0):>10}{c.get('kontrol_edilemedi', 0):>10}{oran:>8}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mevzuatradar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download"); d.add_argument("--config", default="configs/sources.yaml")
    d.add_argument("--raw-dir", default="data/raw")
    d.add_argument("--refresh", action="store_true", help="konsolide metinleri yeniden indir")
    p = sub.add_parser("parse"); p.add_argument("path"); p.add_argument("--out")
    e = sub.add_parser("extract"); e.add_argument("path"); e.add_argument("--out")
    v = sub.add_parser("evaluate"); v.add_argument("--pred", required=True); v.add_argument("--gold", required=True)
    vf = sub.add_parser("verify"); vf.add_argument("--consolidated", required=True)
    vf.add_argument("--amendment", required=True); vf.add_argument("--show-diff", action="store_true")
    fa = sub.add_parser("find-amendments"); fa.add_argument("--source")
    fa.add_argument("--all", action="store_true", help="değişiklik listesi boş olan tüm kaynaklar")
    fa.add_argument("--config", default="configs/sources.yaml"); fa.add_argument("--raw-dir", default="data/raw")
    fa.add_argument("--write", action="store_true")
    vs = sub.add_parser("verify-source"); vs.add_argument("--source", required=True)
    vs.add_argument("--raw-dir", default="data/raw"); vs.add_argument("--show-diff", action="store_true")
    vs.add_argument("--verbose", action="store_true")
    va = sub.add_parser("verify-all"); va.add_argument("--config", default="configs/sources.yaml")
    va.add_argument("--raw-dir", default="data/raw"); va.add_argument("--min-rate", type=float)
    ad = sub.add_parser("add-source"); ad.add_argument("--id", required=True); ad.add_argument("--name", required=True)
    ad.add_argument("--issuer", required=True); ad.add_argument("--url", required=True)
    ad.add_argument("--split", choices=["train", "dev", "test"], required=True)
    ad.add_argument("--former-name", action="append", default=[],
                    help="düzenlemenin eski adı (adı değişmişse; birden çok kez verilebilir)")
    ad.add_argument("--config", default="configs/sources.yaml"); ad.add_argument("--splits", default="configs/splits.yaml")
    es = sub.add_parser("export-seq2seq"); es.add_argument("--in-dir", default="data/ml")
    es.add_argument("--out-dir", default="data/ml")
    em = sub.add_parser("evaluate-model"); em.add_argument("--pred", required=True)
    em.add_argument("--split", default="dev"); em.add_argument("--data-dir", default="data/ml")
    em.add_argument("--raw-dir", default="data/raw")
    bd = sub.add_parser("build-dataset"); bd.add_argument("--config", default="configs/sources.yaml")
    bd.add_argument("--splits", default="configs/splits.yaml"); bd.add_argument("--raw-dir", default="data/raw")
    bd.add_argument("--out-dir", default="data/ml")
    args = ap.parse_args(argv)

    if args.cmd == "download":
        from mevzuatradar.collect.downloader import run
        run(args.config, args.raw_dir, refresh=args.refresh)
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
    elif args.cmd == "verify-all":
        _verify_all(args)
    elif args.cmd == "build-dataset":
        _build_dataset(args)
    elif args.cmd == "add-source":
        _add_source(args)
    elif args.cmd == "export-seq2seq":
        _export_seq2seq(args)
    elif args.cmd == "evaluate-model":
        _evaluate_model(args)
    elif args.cmd == "find-amendments":
        if args.all:
            import yaml
            from pathlib import Path
            cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
            todo = [x["id"] for x in cfg["sources"] if x.get("url") and not x.get("amendments")]
            print(f"Değişiklik listesi boş kaynaklar: {', '.join(todo) or '(yok)'}")
            for sid in todo:
                print(f"\n===== {sid} =====")
                args.source = sid
                _find_amendments(args)
        elif args.source:
            _find_amendments(args)
        else:
            print("--source veya --all belirtin.")
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
