"""configs/sources.yaml içindeki adresleri indirir, ham dosyaları ve bir manifest tutar.

- Aynı içerik (sha256) ikinci kez kaydedilmez; böylece betik güvenle tekrar çalıştırılabilir.
- İstekler arasında bekleme süresi uygulanır. Sitelerin kullanım koşullarına uyun.
- Ham veri klasörünü (data/raw) DVC ile versiyonlamanız önerilir.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import truststore
import yaml

EXT_BY_TYPE = {"application/pdf": ".pdf", "text/html": ".html", "text/plain": ".txt"}


def _ext(content_type: str, url: str) -> str:
    base = content_type.split(";")[0].strip().lower()
    if base in EXT_BY_TYPE:
        return EXT_BY_TYPE[base]
    return ".pdf" if url.lower().endswith(".pdf") else ".bin"


def download_one(session: requests.Session, url: str, source_id: str, role: str,
                 raw_dir: Path, manifest: Path, timeout: int) -> dict | None:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
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


def run(config_path: str, raw_dir: str = "data/raw") -> list[dict]:
    # Bazı kamu siteleri (ör. mevzuat.gov.tr) TLS el sıkışmasında ara sertifikayı
    # göndermiyor; tarayıcılar bunu tamamlarken certifi'nin sabit kök listesi
    # tamamlayamıyor ("unable to get local issuer certificate"). truststore,
    # doğrulamayı işletim sisteminin güven deposuna (macOS Keychain vb.) devreder.
    # Import anında global yan etki olmasın diye burada, indirme başlarken çağrılır.
    truststore.inject_into_ssl()

    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    crawl = cfg.get("crawl", {})
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    manifest = raw / "manifest.jsonl"
    session = requests.Session()
    session.headers["User-Agent"] = crawl.get("user_agent", "MevzuatRadar/0.1")

    jobs = []
    for src in cfg["sources"]:
        if src.get("url"):
            jobs.append((src["id"], "konsolide", src["url"]))
        for i, amd in enumerate(src.get("amendments") or []):
            url = amd if isinstance(amd, str) else amd.get("url")
            if url:
                jobs.append((src["id"], f"degisiklik{i:02d}", url))

    saved = []
    for n, (sid, role, url) in enumerate(jobs):
        if n:
            time.sleep(crawl.get("delay_seconds", 3))
        try:
            meta = download_one(session, url, sid, role, raw, manifest, crawl.get("timeout_seconds", 30))
            print(f"[{'yeni' if meta else 'aynı'}] {sid} {role} {url}")
            if meta:
                saved.append(meta)
        except requests.RequestException as exc:
            print(f"[hata] {sid} {role} {url}: {exc}")
    if not jobs:
        print("İndirilecek adres yok: configs/sources.yaml içindeki url alanlarını doldurun.")
    return saved