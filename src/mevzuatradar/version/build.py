"""İlk metinden başlayıp değişiklikleri sırayla uygulayarak sürüm zinciri kurar."""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from mevzuatradar.extract.pipeline import process_source
from mevzuatradar.parse.text_extract import extract_text
from mevzuatradar.version.apply import apply_record


@dataclass
class Version:
    label: str                      # değişikliğin Resmî Gazete etiketi ("ilk metin" ya da dosya adı)
    text: str
    applied: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)   # (işlem, sebep)


@dataclass
class MaddeDiff:
    madde: str
    ratio: float | None          # None: bizde ya da resmi metinde yok
    durum: str                   # ayni | farkli | bizde_yok | resmide_yok


@dataclass
class ChainResult:
    source: str
    versions: list[Version]
    similarity: float | None        # son sürüm ile resmi konsolide metnin benzerliği
    consolidated_found: bool


def _normalize(text: str) -> str:
    """Karşılaştırma için: dipnot/değişiklik notları, fazla boşluk ve büyük/küçük fark etmesin."""
    text = re.sub(r"\((?:Değişik|Ek|Mülga|İptal)[^)]*\)", " ", text)
    text = re.sub(r"\(\d{1,2}\)", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def build_chain(source: str, raw_dir: str = "data/raw") -> ChainResult:
    orijinal = glob.glob(f"{raw_dir}/{source}/orijinal_*")
    if not orijinal:
        raise FileNotFoundError(f"{source}: ilk metin yok (mevzuatradar find-original --source {source} --write)")
    run = process_source(source, raw_dir)
    if run is None:
        raise FileNotFoundError(f"{source}: değişiklik yönetmeliği yok")

    metin = extract_text(max(orijinal, key=os.path.getmtime)).text
    versions = [Version("ilk metin", metin)]

    kayitlar: dict[int, list[dict]] = {}
    for i, rec, _ in run.results:
        kayitlar.setdefault(i, []).append(rec)

    for i, dosya in enumerate(run.amendment_files):
        surum = Version(Path(dosya).name.split("_")[0], metin)
        for rec in kayitlar.get(i, []):
            metin, res = apply_record(metin, rec)
            if res.status == "uygulandi":
                surum.applied += 1
            else:
                surum.failed.append((f"{rec['operation']} {rec['location'].get('madde')}", res.detail))
        surum.text = metin
        versions.append(surum)

    kons = glob.glob(f"{raw_dir}/{source}/konsolide_*")
    benzerlik = None
    if kons:
        resmi = extract_text(max(kons, key=os.path.getmtime)).text
        benzerlik = SequenceMatcher(None, _normalize(metin), _normalize(resmi)).ratio()
    return ChainResult(source, versions, benzerlik, bool(kons))


def compare_by_article(source: str, text: str, raw_dir: str = "data/raw",
                       esik: float = 0.98) -> list[MaddeDiff]:
    """Ürettiğimiz metni resmi konsolide metinle MADDE MADDE karşılaştırır.

    Bütün metni tek parça karşılaştırmak sıralama farklarına ve eklere (form/tablo) duyarlıdır;
    madde bazında karşılaştırma hangi maddede sorun olduğunu doğrudan gösterir.
    """
    from mevzuatradar.parse.structure import parse_structure

    kons = glob.glob(f"{raw_dir}/{source}/konsolide_*")
    if not kons:
        return []
    resmi = parse_structure(extract_text(max(kons, key=os.path.getmtime)).text)
    bizim = parse_structure(text)
    bizim_map = {m.key: m for m in bizim.maddeler}
    resmi_map = {m.key: m for m in resmi.maddeler}

    out = []
    for key in sorted(set(bizim_map) | set(resmi_map), key=lambda k: (":" in k, len(k), k)):
        b, r = bizim_map.get(key), resmi_map.get(key)
        if b is None:
            out.append(MaddeDiff(key, None, "bizde_yok"))
        elif r is None:
            out.append(MaddeDiff(key, None, "resmide_yok"))
        else:
            oran = SequenceMatcher(None, _normalize(b.raw_text), _normalize(r.raw_text)).ratio()
            out.append(MaddeDiff(key, oran, "ayni" if oran >= esik else "farkli"))
    return out
