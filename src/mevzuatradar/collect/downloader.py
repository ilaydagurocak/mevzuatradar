"""configs/sources.yaml içindeki adresleri indirir, ham dosyaları ve bir manifest tutar.

- Her siteye ilk istekten önce robots.txt okunur ve kurallara uyulur (bkz. polite.py).
- İstekler arasında bekleme süresi uygulanır; zaman aşımında artan sürelerle yeniden denenir.
- Daha önce indirilmiş bir adres (manifest'te kayıtlı) yeniden istenmez. Değişiklik yönetmelikleri
  yayımlandıktan sonra değişmez; konsolide metinler ise yalnızca refresh=True ile yeniden indirilir.
- Aynı içerik (sha256) ikinci kez kaydedilmez; betik güvenle tekrar çalıştırılabilir.
- Ham veri klasörünü (data/raw) DVC ile versiyonlamanız önerilir.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from mevzuatradar.collect.polite import RobotsChecker, use_system_certs, get_with_retry

EXT_BY_TYPE = {"application/pdf": ".pdf", "text/html": ".html", "text/plain": ".txt"}


def _ext(content_type: str, url: str) -> str:
    base = content_type.split(";")[0].strip().lower()
    if base in EXT_BY_TYPE:
        return EXT_BY_TYPE[base]
    return ".pdf" if url.lower().endswith(".pdf") else ".bin"


def download_one(session: requests.Session, url: str, source_id: str, role: str,
                 raw_dir: Path, manifest: Path, timeout: int) -> dict | None:
    resp = get_with_retry(session, url, timeout=timeout)
    digest = hashlib.sha256(resp.content).hexdigest()
    out_dir = raw_dir / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{role}_{digest[:16]}{_ext(resp.headers.get('Content-Type', ''), url)}"
    if path.exists():
        return None  # içerik değişmemiş
    path.write_bytes(resp.content)
    meta = {
        "source_id": source_id, "role": role, "url": url, "path": str(path),
        "sha256": digest, "content_type": resp.headers.get("Content-Type"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
    return meta


def _already_downloaded(manifest: Path) -> set[str]:
    if not manifest.exists():
        return set()
    urls = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            urls.add(json.loads(line)["url"])
        except (json.JSONDecodeError, KeyError):
            continue
    return urls


def run(config_path: str, raw_dir: str = "data/raw", refresh: bool = False) -> list[dict]:
    # Bazı kamu siteleri (ör. mevzuat.gov.tr) TLS el sıkışmasında ara sertifikayı
    # göndermiyor; tarayıcılar bunu tamamlarken certifi'nin sabit kök listesi
    # tamamlayamıyor ("unable to get local issuer certificate"). truststore,
    # doğrulamayı işletim sisteminin güven deposuna (macOS Keychain vb.) devreder.
    # Import anında global yan etki olmasın diye burada, indirme başlarken çağrılır.
    use_system_certs()

    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    crawl = cfg.get("crawl", {})
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    manifest = raw / "manifest.jsonl"
    session = requests.Session()
    user_agent = crawl.get("user_agent", "MevzuatRadar/0.1")
    session.headers["User-Agent"] = user_agent
    timeout = crawl.get("timeout_seconds", 30)
    robots = RobotsChecker(session, user_agent, timeout)

    jobs = []
    for src in cfg["sources"]:
        if src.get("url"):
            jobs.append((src["id"], "konsolide", src["url"]))
        if src.get("original_url"):
            jobs.append((src["id"], "orijinal", src["original_url"]))
        for i, amd in enumerate(src.get("amendments") or []):
            url = amd if isinstance(amd, str) else amd.get("url")
            if url:
                jobs.append((src["id"], f"degisiklik{i:02d}", url))

    known = _already_downloaded(manifest)
    saved, requested, skipped = [], 0, 0
    for sid, role, url in jobs:
        if url in known and not (refresh and role == "konsolide"):
            skipped += 1
            continue
        if not robots.allowed(url):
            print(f"[robots] {sid} {role} atlandı: sitenin kuralları bu adrese izin vermiyor ({url})")
            continue
        if requested:
            time.sleep(crawl.get("delay_seconds", 3))
        requested += 1
        try:
            meta = download_one(session, url, sid, role, raw, manifest, timeout)
            print(f"[{'yeni' if meta else 'aynı'}] {sid} {role} {url}")
            if meta:
                saved.append(meta)
        except requests.RequestException as exc:
            print(f"[hata] {sid} {role} {url}: {exc}")
    for site, note in robots.notes.items():
        print(f"[robots] {site}: {note}")
    if skipped:
        print(f"{skipped} adres daha önce indirildiği için istenmedi"
              + ("" if refresh else " (konsolide metinleri güncellemek için: mevzuatradar download --refresh)") + ".")
    print(f"Bu çalıştırmada siteye giden istek: {requested} sayfa + robots.txt kontrolleri.")
    if not jobs:
        print("İndirilecek adres yok: configs/sources.yaml içindeki url alanlarını doldurun.")
    return saved
