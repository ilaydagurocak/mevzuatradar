#!/usr/bin/env python3
"""Ürettiğimiz sürüm ile resmi konsolide metni madde madde, cümle cümle karşılaştırır.

build-versions "madde 12 farkli benzerlik 80%" der ama farkın ne olduğunu göstermez.
Bu araç o farkı cümle düzeyinde yazar: '-' bizim ürettiğimizde olan, '+' resmi metinde olan.

Kullanım:
    python tools/madde_fark.py <kaynak> [madde ...]
    python tools/madde_fark.py tcmb_ft_ucret_teblig 4 12 17
    python tools/madde_fark.py tcmb_ft_ucret_teblig            # farklı olan tüm maddeler
    python tools/madde_fark.py bddk_kart gecici:1 --tam        # kesilmemiş cümleler
"""
from __future__ import annotations

import dataclasses
import difflib
import glob
import os
import re
import sys

KES = 300  # uzun cümleler bu uzunlukta kesilir (--tam ile kapatılır)


def cumlelere_bol(metin: str) -> list[str]:
    """Maddeyi okunabilir birimlere böler: fıkra işaretleri ve cümle sonları."""
    metin = re.sub(r"\s+", " ", metin).strip()
    metin = re.sub(r"(?<!^)\s*(\(\d+\))\s*", r"\n\1 ", metin)  # fıkralar yeni satıra
    parcalar = []
    for satir in metin.split("\n"):
        satir = satir.strip()
        if not satir:
            continue
        parcalar += [c.strip() for c in re.split(r"(?<=[.:;])\s+(?=[\"“(A-ZÇĞİÖŞÜ])", satir) if c.strip()]
    return parcalar


def surum_metni(kaynak: str, raw_dir: str) -> str:
    from mevzuatradar.version.build import build_chain

    zincir = build_chain(kaynak, raw_dir)
    alanlar = ({f.name: getattr(zincir, f.name) for f in dataclasses.fields(zincir)}
               if dataclasses.is_dataclass(zincir) else vars(zincir))
    for deger in alanlar.values():
        if isinstance(deger, list) and deger and hasattr(deger[0], "text"):
            son = deger[-1]
            print(f"son sürüm: {getattr(son, 'label', '?')} "
                  f"({len(deger)} sürüm, {getattr(son, 'date', '') or 'tarihsiz'})")
            return son.text
    raise SystemExit("HATA: zincir sonucunda sürüm listesi bulunamadı.")


def maddeleri_oku(metin: str) -> dict[str, object]:
    from mevzuatradar.parse.structure import parse_structure

    return {m.key: m for m in parse_structure(metin).maddeler}


def main(argv: list[str]) -> int:
    tam = "--tam" in argv
    argv = [a for a in argv if a != "--tam"]
    if len(argv) < 2:
        print(__doc__)
        return 1
    kaynak, istenen = argv[1], argv[2:]
    raw_dir = "data/raw"

    from mevzuatradar.parse.text_extract import extract_text

    kons = glob.glob(f"{raw_dir}/{kaynak}/konsolide_*")
    if not kons:
        print(f"HATA: {kaynak} için konsolide metin yok (mevzuatradar download).")
        return 1

    bizim = maddeleri_oku(surum_metni(kaynak, raw_dir))
    resmi = maddeleri_oku(extract_text(max(kons, key=os.path.getmtime)).text)

    if istenen:
        anahtarlar = []
        for istek in istenen:
            esler = [k for k in set(bizim) | set(resmi) if k == istek or k.endswith(f":{istek}")]
            if not esler:
                print(f"[yok] '{istek}' adlı madde ne bizde ne resmi metinde bulundu")
            anahtarlar += esler
    else:
        anahtarlar = [k for k in set(bizim) | set(resmi)
                      if k not in bizim or k not in resmi
                      or difflib.SequenceMatcher(
                          None, re.sub(r"\s+", " ", bizim[k].raw_text),
                          re.sub(r"\s+", " ", resmi[k].raw_text)).ratio() < 0.98]

    anahtarlar = sorted(set(anahtarlar), key=lambda k: (":" in k, len(k), k))
    if not anahtarlar:
        print("Fark yok: bütün maddeler birebir aynı.")
        return 0

    for key in anahtarlar:
        b, r = bizim.get(key), resmi.get(key)
        print("\n" + "=" * 78)
        if b is None:
            print(f"MADDE {key}: yalnızca resmi metinde var (bizim sürümde yok)")
            print("  " + re.sub(r"\s+", " ", r.raw_text)[:600])
            continue
        if r is None:
            print(f"MADDE {key}: yalnızca bizim sürümde var (resmi metinde yok)")
            print("  " + re.sub(r"\s+", " ", b.raw_text)[:600])
            continue

        oran = difflib.SequenceMatcher(None, re.sub(r"\s+", " ", b.raw_text),
                                       re.sub(r"\s+", " ", r.raw_text)).ratio()
        print(f"MADDE {key}  —  benzerlik {oran:.0%}   ('-' bizim, '+' resmi)")
        print("=" * 78)
        bc, rc = cumlelere_bol(b.raw_text), cumlelere_bol(r.raw_text)
        for satir in difflib.unified_diff(bc, rc, lineterm="", n=1):
            if satir.startswith(("---", "+++")):
                continue
            if satir.startswith("@@"):
                print(f"\n  {satir}")
            else:
                govde = satir[1:].strip()
                if not tam and len(govde) > KES:
                    govde = govde[:KES] + " …"
                print(f"  {satir[0]} {govde}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
