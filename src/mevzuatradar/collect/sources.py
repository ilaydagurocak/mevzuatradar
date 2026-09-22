"""configs/sources.yaml ve configs/splits.yaml dosyalarını güvenle güncelleyen yardımcılar."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

IFRAME = "https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?MevzuatTur={tur}&MevzuatNo={no}&MevzuatTertip={tertip}"

SPLITS_HEADER = """# Model veri seti bölmeleri — YÖNETMELİK BAZINDA.
# Aynı yönetmelikten örnekler iki bölmede birden bulunmamalı; aksi halde model ezber yapar.
# "test" bölmesindeki yönetmeliklerin hatalarına karşılaştırma bitene kadar BAKILMAZ ve
# kurallar onlara göre düzeltilmez; aksi halde test, genelleme ölçüsü olmaktan çıkar.
"""


def to_iframe_url(url: str) -> str:
    """mevzuat.gov.tr sayfa adresini (mevzuat?MevzuatNo=..&MevzuatTur=..&MevzuatTertip=..) metnin
    yüklendiği iframe adresine çevirir. Zaten iframe adresiyse olduğu gibi döner."""
    parts = urlsplit(url.strip())
    if "MevzuatFihristDetayIframe" in parts.path:
        return url.strip()
    q = {k.lower(): v[0] for k, v in parse_qs(parts.query).items()}
    try:
        return IFRAME.format(tur=q["mevzuattur"], no=q["mevzuatno"], tertip=q.get("mevzuattertip", "5"))
    except KeyError as exc:
        raise ValueError(f"Adreste MevzuatNo/MevzuatTur bulunamadı: {url}") from exc


def add_source(sid: str, name: str, issuer: str, url: str, split: str,
               config: str = "configs/sources.yaml", splits: str = "configs/splits.yaml",
               former_names: list[str] | None = None) -> str:
    cfg_path, spl_path = Path(config), Path(splits)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    iframe = to_iframe_url(url)
    existing = next((s for s in cfg["sources"] if s["id"] == sid), None)
    extra = {"former_names": list(former_names)} if former_names else {}
    if existing:
        existing.update({"name": name, "issuer": issuer, "url": iframe, **extra})
    else:
        cfg["sources"].append({"id": sid, "name": name, "issuer": issuer, "url": iframe, **extra, "amendments": []})
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")

    spl = (yaml.safe_load(spl_path.read_text(encoding="utf-8")) if spl_path.exists() else None) or {}
    for key in ("train", "dev", "test"):
        spl[key] = [s for s in (spl.get(key) or []) if s != sid]
    spl.setdefault(split, []).append(sid)
    spl_path.write_text(SPLITS_HEADER + yaml.safe_dump(spl, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return iframe
