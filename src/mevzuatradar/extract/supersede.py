"""Sonradan üzerine yazılmış değişiklikleri, SONRAKİ değişikliklerin alıntılarıyla doğrular.

Sorun: bir değişikliğin etkisi daha sonra başka bir değişiklikle üzerine yazılmışsa, bugünkü
konsolide metne bakarak doğrulanamaz ("sonradan_degisti").

Fikir: sonraki değişiklik, değiştirdiği ESKİ ibareyi kendi metninde alıntılar. O eski ibare,
önceki değişikliğin getirdiği yeni ibare ise, önceki değişikliğin gerçekten uygulandığı
bağımsız olarak kanıtlanmış olur. Kanıt bizim ürettiğimiz metinden değil, başka bir resmi
belgeden gelir; bu yüzden döngüsel değildir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class NoteEvidence:
    """Resmi konsolide metnin kendi değişiklik notu: '(Değişik:RG-25/9/2020-31255)'.
    Kaynak resmi metnin kendisi olduğu için bağımsız kanıttır."""
    label: str                   # değişikliğin Resmî Gazete etiketi
    unit: str                    # notun bulunduğu birim (madde/fıkra/bent)


@dataclass
class Evidence:
    amendment_index: int         # kanıtı sağlayan değişikliğin sırası
    amending_article: str        # o değişikliğin kaçıncı maddesi
    quoted: str                  # alıntılanan eski ibare


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _same_place(a: dict, b: dict) -> bool:
    la, lb = a.get("location") or {}, b.get("location") or {}
    return (str(la.get("madde")) == str(lb.get("madde"))
            and (la.get("madde_type") or "normal") == (lb.get("madde_type") or "normal"))


def find_evidence(records: list[tuple[int, dict]], index: int) -> Evidence | None:
    """records: [(değişiklik_sırası, kayıt), ...] tarih sırasıyla. index: incelenen kaydın yeri.

    Aranan: aynı maddede, DAHA SONRAKİ bir değişikliğin eski/çapa ibaresi, bu kaydın yeni
    ibaresini içeriyor mu?
    """
    i, rec = records[index]
    yeni = _norm(rec.get("new_text"))
    if not yeni or len(yeni) < 8:                    # çok kısa ibareler rastlantısal eşleşir
        return None
    for j, sonraki in records[index + 1:]:
        if j <= i or not _same_place(rec, sonraki):
            continue
        for alan in ("old_text", "anchor_text"):
            alinti = _norm(sonraki.get(alan))
            if alinti and (yeni in alinti or alinti in yeni) and len(alinti) >= 8:
                return Evidence(j, str(sonraki.get("amending_article")), sonraki.get(alan))
    return None


def explain(results: list[tuple[int, dict, object]]) -> dict[int, Evidence]:
    """verify_chronological çıktısındaki 'sonradan_degisti' kayıtları için kanıt arar.
    Dönüş: {kaydın sırası: Evidence}"""
    kayitlar = [(i, rec) for i, rec, _ in results]
    out = {}
    for k, (_, _, res) in enumerate(results):
        if getattr(res, "status", None) != "sonradan_degisti":
            continue
        kanit = find_evidence(kayitlar, k)
        if kanit is not None:
            out[k] = kanit
    return out


def _rg_digits(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch.isdigit() or ch == "/")


def note_evidence(rec: dict, label: str, doc) -> NoteEvidence | None:
    """Kaydın hedeflediği birimde, bu değişikliğin etiketini taşıyan resmi not var mı?"""
    loc = rec.get("location") or {}
    madde = doc.get(str(loc.get("madde"))) if loc.get("madde") else None
    if madde is None:
        return None
    hedef = _rg_digits(label)
    if not hedef:
        return None

    def esles(anns, birim):
        for a in anns or []:
            if hedef and hedef in _rg_digits(getattr(a, "source", "")):
                return NoteEvidence(label, birim)
        return None

    if (e := esles(madde.annotations, f"madde {madde.num}")):
        return e
    for f in madde.fikralar:
        if loc.get("fikra") not in (None, f.num):
            continue
        if (e := esles(f.annotations, f"madde {madde.num} fıkra {f.num}")):
            return e
        for b in f.bentler:
            if loc.get("bent") not in (None, b.letter):
                continue
            if (e := esles(b.annotations, f"madde {madde.num} fıkra {f.num} bent {b.letter}")):
                return e
    return None


def explain_with_notes(results: list[tuple[int, dict, object]], labels: dict[int, str],
                       consolidated_text: str) -> dict[int, NoteEvidence]:
    """'sonradan_degisti' kayıtları için resmi konsolide metnin notlarında kanıt arar.
    labels: {değişiklik sırası: 'RG-...'}"""
    from mevzuatradar.parse.structure import parse_structure

    doc = parse_structure(consolidated_text)
    out = {}
    for k, (i, rec, res) in enumerate(results):
        if getattr(res, "status", None) != "sonradan_degisti" or i not in labels:
            continue
        kanit = note_evidence(rec, labels[i], doc)
        if kanit is not None:
            out[k] = kanit
    return out
