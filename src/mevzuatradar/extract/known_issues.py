"""Elle doğrulanmış kaynak tutarsızlıklarını doğrulama sonuçlarına uygular.

Bir girdi, (kaynak, değişiklik yönetmeliği adresi, değişiklik maddesi, işlem, konum) ile eşleşir.
Etiket yalnızca doğrulama başarısızsa ("uyumsuz" veya "hedef_bulunamadi") uygulanır.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from mevzuatradar.extract.verify import VerifyResult

FAILED = ("uyumsuz", "hedef_bulunamadi")


def load_issues(path: str | Path = "configs/known_source_issues.yaml") -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("issues") or []


def file_urls(raw_dir: str | Path) -> dict[str, str]:
    """manifest.jsonl'den dosya adı -> kaynak adres eşlemesi."""
    manifest = Path(raw_dir) / "manifest.jsonl"
    out = {}
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            try:
                meta = json.loads(line)
                out[Path(meta["path"]).name] = meta["url"]
            except (json.JSONDecodeError, KeyError):
                continue
    return out


def _matches(issue: dict, source: str, url: str | None, rec: dict) -> bool:
    if issue.get("source") != source or issue.get("amendment_url") != url:
        return False
    if str(issue.get("amending_article")) != str(rec.get("amending_article")):
        return False
    if issue.get("operation") != rec.get("operation"):
        return False
    loc = rec.get("location") or {}
    return all(str(loc.get(k)) == str(v) for k, v in (issue.get("location") or {}).items())


def apply_known_issues(source: str, amds: list[str], results: list, issues: list[dict],
                       urls: dict[str, str]) -> tuple[list, list[str]]:
    """Sonuçları günceller. Dönüş: (yeni sonuçlar, artık gerekmeyen girdilerin id'leri)."""
    relevant = [i for i in issues if i.get("source") == source]
    used, unused_ok = set(), set()
    out = []
    for idx, rec, res in results:
        url = urls.get(Path(amds[idx]).name)
        hit = next((i for i in relevant if _matches(i, source, url, rec)), None)
        if hit and res.status in FAILED:
            evid = "; ".join(e.get("url", "") for e in hit.get("evidence") or [])
            res = VerifyResult("kaynak_tutarsizligi",
                               f"[{hit['id']}] {' '.join(hit.get('description', '').split())} Kanıt: {evid}",
                               res.expected, res.actual)
            used.add(hit["id"])
        elif hit:
            unused_ok.add(hit["id"])
        out.append((idx, rec, res))
    return out, sorted(unused_ok - used)
