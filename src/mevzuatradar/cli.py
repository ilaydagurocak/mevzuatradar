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
  mevzuatradar export-llm --split test --shots 10
  mevzuatradar watch                      (bugünün Resmî Gazete'sini tarar)
  mevzuatradar watch --days 7 --all
  mevzuatradar find-original --source bddk_kart --write
  mevzuatradar build-versions --source bddk_kart --verbose
  mevzuatradar serve                      (http://127.0.0.1:8000 demo + /docs)
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

    from mevzuatradar.collect.polite import RobotsChecker, use_system_certs

    use_system_certs()
    crawl = cfg.get("crawl", {})
    session = requests.Session()
    session.headers["User-Agent"] = crawl.get("user_agent", "MevzuatRadar/0.1")
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

    raw = evaluate(args.pred, args.split, args.data_dir, args.raw_dir, snap=False, pred2_path=args.pred2)
    snapped = evaluate(args.pred, args.split, args.data_dir, args.raw_dir, snap=True, pred2_path=args.pred2)
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
        if "hibrit3" in snapped["verification"][src]:
            rows.append(("hibrit (2 model)", snapped["verification"][src]["hibrit3"]))
        for name, c in rows:
            oran = f"{c['oran']:.1%}" if c["oran"] is not None else "-"
            print(f"{src:<24}{name:<18}{c['kayit']:>6}{c.get('uyumlu', 0):>8}{c.get('uyumsuz', 0):>9}"
                  f"{c.get('hedef_bulunamadi', 0):>10}{c.get('kontrol_edilemedi', 0):>10}{oran:>8}")


def _export_llm(args):
    from mevzuatradar.ml.prompt import export_prompts

    yol, n = export_prompts(args.split, args.shots, args.data_dir)
    import json as _json
    ilk = _json.loads(open(yol, encoding="utf-8").readline())
    karakter = sum(len(m["content"]) for m in ilk["messages"])
    print(f"{n} istem yazıldı: {yol}")
    print(f"İstem başına yaklaşık {karakter} karakter (~{karakter // 3} token), {args.shots} örnek içeriyor.")


def _serve(args):
    try:
        import uvicorn
    except ImportError:
        print("Servis için: pip install -e \".[api]\"")
        return
    print(f"Demo sayfası: http://{args.host}:{args.port}/   API dokümantasyonu: /docs")
    uvicorn.run("mevzuatradar.api.main:app", host=args.host, port=args.port, reload=args.reload)


def _find_original(args):
    """Düzenlemenin İLK yayımını bulur: ilk değişiklik yönetmeliğindeki atıftan tarihi alır,
    o günün Resmî Gazete içindekiler sayfasında adı geçen (ama 'değişiklik' geçmeyen) bağlantıyı arar."""
    import glob
    from pathlib import Path as _Path

    import requests
    import yaml

    from mevzuatradar.collect.polite import RobotsChecker, use_system_certs
    from mevzuatradar.collect.rg_finder import (find_original_link, keyword_from_name, original_ref, _decode)
    from mevzuatradar.parse.text_extract import extract_text

    cfg_path = _Path(args.config)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    src = next((s for s in cfg["sources"] if s["id"] == args.source), None)
    if src is None:
        print(f"'{args.source}' kimlikli kaynak {args.config} içinde yok.")
        return
    degisiklikler = sorted(glob.glob(f"{args.raw_dir}/{args.source}/degisiklik*"))
    if not degisiklikler:
        print("Değişiklik yönetmeliği yok; önce 'find-amendments' ve 'download' çalıştırın.")
        return
    ref = original_ref(extract_text(degisiklikler[0]).text, src["name"])
    if ref is None:
        print("İlk yayım tarihi, ilk değişiklik yönetmeliğinin metninde bulunamadı.")
        return
    print(f"İlk yayım: {ref.label}")

    use_system_certs()
    crawl = cfg.get("crawl", {})
    session = requests.Session()
    session.headers["User-Agent"] = crawl.get("user_agent", "MevzuatRadar/0.1")
    robots = RobotsChecker(session, session.headers["User-Agent"], crawl.get("timeout_seconds", 30))
    if not robots.allowed(ref.index_url):
        print(f"[robots] izin verilmiyor: {ref.index_url}")
        return
    resp = session.get(ref.index_url, timeout=crawl.get("timeout_seconds", 30))
    resp.raise_for_status()
    keyword = [keyword_from_name(n) for n in [src["name"], *(src.get("former_names") or [])]]
    links = find_original_link(_decode(resp), ref.index_url, keyword)
    if not links:
        print(f"Bağlantı bulunamadı. İçindekiler: {ref.index_url}")
        return
    for baslik, url in links[:5]:
        print(f"[bulundu] {url}\n    {' '.join(baslik.split())[:160]}")
    if args.write:
        src["original_url"] = links[0][1]
        src["original_ref"] = ref.label
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
        print(f"{args.config} güncellendi (original_url). Şimdi: mevzuatradar download")


def _build_versions(args):
    from mevzuatradar.version.build import build_chain

    zincir = build_chain(args.source, args.raw_dir)
    toplam_u = sum(v.applied for v in zincir.versions)
    toplam_h = sum(len(v.failed) for v in zincir.versions)
    print(f"{zincir.source}: {len(zincir.versions) - 1} değişiklik uygulandı "
          f"({toplam_u} kayıt başarılı, {toplam_h} başarısız)")
    for v in zincir.versions[1:]:
        durum = f"{v.applied} uygulandı" + (f", {len(v.failed)} başarısız" if v.failed else "")
        print(f"  {v.label:<14} {durum}")
        if args.verbose:
            for islem, sebep in v.failed:
                print(f"      [atlandı] {islem}: {sebep}")
    if zincir.similarity is not None:
        print(f"\nSon sürüm ile resmi konsolide metnin benzerliği: {zincir.similarity:.1%}")
    from mevzuatradar.version.build import compare_by_article
    farklar = compare_by_article(args.source, zincir.versions[-1].text, args.raw_dir)
    if farklar:
        sayim = {}
        for d in farklar:
            sayim[d.durum] = sayim.get(d.durum, 0) + 1
        esit = sayim.get("ayni", 0)
        print(f"Madde bazında: {esit}/{len(farklar)} madde birebir aynı | "
              + ", ".join(f"{k}: {v}" for k, v in sorted(sayim.items()) if k != "ayni"))
        if args.verbose:
            for d in farklar:
                if d.durum != "ayni":
                    oran = f"{d.ratio:.0%}" if d.ratio is not None else "-"
                    print(f"    {d.madde:<16} {d.durum:<12} benzerlik {oran}")
    if args.out_dir:
        from pathlib import Path as _P
        d = _P(args.out_dir) / args.source
        d.mkdir(parents=True, exist_ok=True)
        for k, v in enumerate(zincir.versions):
            (d / f"{k:02d}_{v.label}.txt").write_text(v.text, encoding="utf-8")
        print(f"Sürümler yazıldı: {d}")


def _explain_superseded(args):
    from mevzuatradar.extract.pipeline import process_source
    from mevzuatradar.extract.supersede import explain

    run = process_source(args.source, args.raw_dir)
    if run is None:
        print(f"{args.source}: veri yok")
        return
    import glob
    import os

    from mevzuatradar.collect.rg_finder import collect_refs, consolidated_annotation_sources
    from mevzuatradar.extract.supersede import explain_with_notes
    from mevzuatradar.parse.text_extract import extract_text

    sonradan = [k for k, (_, _, res) in enumerate(run.results) if res.status == "sonradan_degisti"]
    kanitlar = explain(run.results)
    kons = glob.glob(f"{args.raw_dir}/{args.source}/konsolide_*")
    not_kanitlari = {}
    if kons:
        yol = max(kons, key=os.path.getmtime)
        refs = collect_refs(consolidated_annotation_sources(yol))
        etiketler = {i: r.label for i, r in enumerate(refs) if i < len(run.amendment_files)}
        not_kanitlari = explain_with_notes(run.results, etiketler, extract_text(yol).text)
    toplam = set(kanitlar) | set(not_kanitlari)
    print(f"{args.source}: {len(sonradan)} 'sonradan değişti' kaydının {len(toplam)} tanesi doğrulandı "
          f"({len(kanitlar)} sonraki değişikliğin alıntısıyla, {len(not_kanitlari)} resmi metnin "
          f"değişiklik notuyla)")
    if args.verbose:
        for k in sonradan:
            i, rec, _ = run.results[k]
            kanit, notu = kanitlar.get(k), not_kanitlari.get(k)
            loc = {a: b for a, b in rec["location"].items() if b not in (None, "normal")}
            yeni = (rec.get("new_text") or "")[:60]
            if kanit:
                print(f"  [kanıt] {rec['operation']} {loc} '{yeni}'")
                print(f"          -> değişiklik {kanit.amendment_index}, madde {kanit.amending_article} "
                      f"bu ibareyi alıntılıyor: '{(kanit.quoted or '')[:60]}'")
            elif notu:
                print(f"  [not]   {rec['operation']} {loc} '{yeni}'")
                print(f"          -> resmi metin {notu.unit} için {notu.label} notunu taşıyor")
            else:
                print(f"  [kanıtsız] {rec['operation']} {loc} '{yeni}'")


def _watch(args):
    import time
    from datetime import date, datetime, timedelta
    from pathlib import Path

    import requests
    import yaml

    from mevzuatradar.collect.polite import RobotsChecker, use_system_certs
    from mevzuatradar.collect.rg_finder import RGRef
    from mevzuatradar.collect.watch import load_state, save_state, scan_day, write_report

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    kaynaklar = [s for s in cfg["sources"] if s.get("name")]
    gun = datetime.strptime(args.date, "%d/%m/%Y").date() if args.date else date.today()

    use_system_certs()
    crawl = cfg.get("crawl", {})
    session = requests.Session()
    session.headers["User-Agent"] = crawl.get("user_agent", "MevzuatRadar/0.1")
    timeout = crawl.get("timeout_seconds", 30)
    robots = RobotsChecker(session, session.headers["User-Agent"], timeout)
    gecikme = crawl.get("delay_seconds", 3)

    gorulen = load_state(args.state)
    yeni_bulgular, taranan, hatali = [], 0, 0
    for k in range(args.days):
        d = gun - timedelta(days=k)
        for mukerrer in range(0, args.mukerrer + 1):
            ref = RGRef(d.year, d.month, d.day, sayi="?", mukerrer=mukerrer)
            if taranan:
                time.sleep(gecikme)
            taranan += 1
            try:
                hits, hata = scan_day(session, ref, kaynaklar, args.raw_dir, timeout, robots)
            except Exception as exc:
                hatali += 1
                print(f"[hata] {ref.label}: {type(exc).__name__}: {exc}")
                continue
            if hata:
                hatali += 1
                print(f"[atlandı] {ref.label}: {hata}")
                continue
            for h in hits:
                if h.url in gorulen and not args.all:
                    continue
                gorulen.add(h.url)
                yeni_bulgular.append(h)

    tarih = f"{gun:%d/%m/%Y}" + (f" ve önceki {args.days - 1} gün" if args.days > 1 else "")
    if not yeni_bulgular:
        print(f"{tarih}: takip edilen {len(kaynaklar)} düzenlemede yeni değişiklik yok "
              f"({taranan} sayfa denendi).")
    for h in yeni_bulgular:
        print(f"\n>>> {h.source_name}")
        print(f"    {h.rg_label} | {h.title[:120]}")
        print(f"    {h.url}")
        if h.error:
            print(f"    [hata] {h.error}")
            continue
        ozet = ", ".join(f"{k}: {v}" for k, v in sorted(h.statuses.items())) or "doğrulama yapılamadı"
        print(f"    {h.record_count} değişiklik kaydı | güncel metne göre: {ozet}")
        for rec in h.records[:args.show]:
            loc = {k: v for k, v in (rec.get("location") or {}).items() if v not in (None, "normal")}
            eski, yeni = (rec.get("old_text") or "")[:40], (rec.get("new_text") or "")[:60]
            print(f"      - {rec['operation']:<15} {loc} "
                  + (f"'{eski}' -> '{yeni}'" if eski else (f"'{yeni}'" if yeni else "")))
        if len(h.records) > args.show:
            print(f"      ... ve {len(h.records) - args.show} kayıt daha")
    if yeni_bulgular and args.report:
        write_report(args.report, yeni_bulgular)
        print(f"\nRapor: {args.report}")
    if not args.all:
        save_state(args.state, gorulen)
    if taranan and hatali == taranan:
        # Hiçbir sayfa okunamadıysa "değişiklik yok" sonucu yanıltıcıdır: sessiz başarısızlığı önle.
        print("\n[uyarı] Hiçbir sayfa okunamadı; sonuç güvenilir değil.")
        return 1
    return 0


def _madde_at(args):
    from datetime import datetime

    from mevzuatradar.version.build import madde_at

    gun = datetime.strptime(args.date, "%d/%m/%Y").date()
    metin, surum = madde_at(args.source, args.madde, gun, args.raw_dir)
    print(f"{args.source} | madde {args.madde} | {gun:%d/%m/%Y} itibarıyla yürürlükteki sürüm: {surum.label}")
    print()
    print(metin or "(bu tarihte böyle bir madde yok)")


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
    em.add_argument("--pred2", help="ikinci model tahminleri; üçlü hibrit için (kural -> 1. model -> 2. model)")
    em.add_argument("--split", default="dev"); em.add_argument("--data-dir", default="data/ml")
    em.add_argument("--raw-dir", default="data/raw")
    el = sub.add_parser("export-llm"); el.add_argument("--split", default="dev")
    el.add_argument("--shots", type=int, default=10); el.add_argument("--data-dir", default="data/ml")
    w = sub.add_parser("watch")
    w.add_argument("--date", help="gg/aa/yyyy (varsayılan: bugün)")
    w.add_argument("--days", type=int, default=1, help="kaç gün geriye taransın")
    w.add_argument("--mukerrer", type=int, default=1, help="kaç mükerrer sayı denensin")
    w.add_argument("--all", action="store_true", help="daha önce bildirilenleri de göster")
    w.add_argument("--show", type=int, default=5, help="bulgu başına gösterilecek kayıt sayısı")
    w.add_argument("--state", default="data/watch_state.json")
    w.add_argument("--report", default="reports/watch.jsonl")
    w.add_argument("--config", default="configs/sources.yaml"); w.add_argument("--raw-dir", default="data/raw")
    es2 = sub.add_parser("explain-superseded"); es2.add_argument("--source", required=True)
    es2.add_argument("--raw-dir", default="data/raw"); es2.add_argument("--verbose", action="store_true")
    ma = sub.add_parser("madde-at"); ma.add_argument("--source", required=True)
    ma.add_argument("--madde", required=True); ma.add_argument("--date", required=True, help="gg/aa/yyyy")
    ma.add_argument("--raw-dir", default="data/raw")
    bv = sub.add_parser("build-versions"); bv.add_argument("--source", required=True)
    bv.add_argument("--raw-dir", default="data/raw"); bv.add_argument("--out-dir")
    bv.add_argument("--verbose", action="store_true")
    fo = sub.add_parser("find-original"); fo.add_argument("--source", required=True)
    fo.add_argument("--write", action="store_true"); fo.add_argument("--config", default="configs/sources.yaml")
    fo.add_argument("--raw-dir", default="data/raw")
    sv = sub.add_parser("serve"); sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000); sv.add_argument("--reload", action="store_true")
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
    elif args.cmd == "export-llm":
        _export_llm(args)
    elif args.cmd == "serve":
        _serve(args)
    elif args.cmd == "find-original":
        _find_original(args)
    elif args.cmd == "build-versions":
        _build_versions(args)
    elif args.cmd == "madde-at":
        _madde_at(args)
    elif args.cmd == "explain-superseded":
        _explain_superseded(args)
    elif args.cmd == "watch":
        return _watch(args)
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
    raise SystemExit(main())
