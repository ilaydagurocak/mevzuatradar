"""Çıkarılan değişiklik kayıtlarını, düzenlemenin güncel (konsolide) metniyle karşılaştırır.

Fikir: bir değişiklik doğru çıkarıldıysa, etkisi konsolide metinde görünür olmalıdır.
Böylece elle etiket gerekmeden çıkarım kalitesi ölçülebilir.

Durumlar:
  uyumlu            -> değişikliğin etkisi konsolide metinde görülüyor
  uyumsuz           -> hedef bulundu ama metin beklenenle örtüşmüyor
  hedef_bulunamadi  -> konsolide metinde hedef madde/fıkra/bent yok
  kontrol_edilemedi -> bu operasyon türü için henüz kontrol yazılmadı
  sonradan_degisti  -> uyumsuz/bulunamadı, ama aynı birime daha sonra başka bir
                       değişiklik dokunmuş; konsolide metin o SON hali gösterir

Not: Aynı birim sonradan tekrar değiştirildiyse konsolide metin yalnızca SON hali
gösterir; bu durumda eski bir değişiklik "uyumsuz" görünebilir. Değişiklikleri
tarih sırasıyla uygulayan versiyonlama (4. aşama) bu sınırlamayı kaldıracak.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from mevzuatradar.parse.structure import Document, Madde, parse_structure


def _norm(text: str | None) -> str:
    text = (text or "").replace("“", "").replace("”", "").replace("\xa0", " ")
    text = re.sub(r"[–—‐‑]", "-", text)  # uzun/kısa tire farkları anlam taşımaz
    return re.sub(r"\s+", " ", text).strip()


def _madde_text(m: Madde) -> str:
    parts = [m.text]
    for f in m.fikralar:
        parts.append(f"({f.num}) {f.text}")
        for b in f.bentler:
            parts.append(f"{b.letter}) {b.text}")
            parts.extend(f"{a.num}) {a.text}" for a in b.alt_bentler)
    return _norm(" ".join(p for p in parts if p))


@dataclass
class VerifyResult:
    status: str
    detail: str
    expected: str | None = None
    actual: str | None = None


def _find_target(doc: Document, loc: dict):
    key = loc["madde"] if loc.get("madde_type", "normal") == "normal" else f"{loc['madde_type']}:{loc['madde']}"
    madde = doc.get(key) if loc.get("madde") else None
    if madde is None:
        return None, f"madde {key} bulunamadı"
    unit = madde
    if loc.get("fikra") is not None:
        unit = next((f for f in madde.fikralar if f.num == loc["fikra"]), None)
        if unit is None:
            return None, f"madde {key} fıkra {loc['fikra']} bulunamadı"
    if loc.get("bent"):
        fikralar = [unit] if unit is not madde else madde.fikralar
        unit = next((b for f in fikralar for b in f.bentler if b.letter == loc["bent"]), None)
        if unit is None:
            return None, f"madde {key} bent {loc['bent']} bulunamadı"
    return unit, ""


def _unit_text(unit) -> str:
    """Birimin metni, alt birimleriyle birlikte (fıkra -> bentler -> alt bentler)."""
    if isinstance(unit, Madde):
        return _madde_text(unit)
    parts = [unit.text]
    for b in getattr(unit, "bentler", []):
        parts.append(f"{b.letter}) {b.text}")
        parts.extend(f"{a.num}) {a.text}" for a in b.alt_bentler)
    for a in getattr(unit, "alt_bentler", []):
        parts.append(f"{a.num}) {a.text}")
    return _norm(" ".join(p for p in parts if p))


def verify_record(rec: dict, doc: Document) -> VerifyResult:
    op = rec["operation"]
    loc = rec.get("location") or {}

    if op == "BASLIK_DEGISTIR" or (op == "BIRIM_DEGISTIR" and rec.get("unit") == "baslik"):
        target, err = _find_target(doc, {**loc, "fikra": None, "bent": None})
        if target is None:
            return VerifyResult("hedef_bulunamadi", err)
        expected, actual = _norm(rec.get("new_text")), _norm(target.title)
        ok = expected == actual
        return VerifyResult("uyumlu" if ok else "uyumsuz",
                            "başlık birebir aynı" if ok else "başlık farklı", expected, actual)

    if op == "BIRIM_EKLE":
        new = rec.get("new_text") or ""
        if rec.get("unit") in ("madde", "maddeler", "gecici_madde", "ek_madde"):
            added = parse_structure("BAŞLIK\n" + new).maddeler
            if not added:
                return VerifyResult("kontrol_edilemedi", "eklenen madde metni ayrıştırılamadı")
            for m in added:
                target = doc.get(m.key)
                if target is None:
                    return VerifyResult("hedef_bulunamadi", f"eklenen madde {m.key} konsolide metinde yok")
                if _madde_text(m) != _madde_text(target):
                    return VerifyResult("uyumsuz", f"eklenen madde {m.key} metni farklı",
                                        _madde_text(m), _madde_text(target))
            return VerifyResult("uyumlu", f"eklenen madde(ler) konsolide metinde birebir var")
        # Fıkra/bent eklemeleri: eklenen metnin başı hedef maddenin metninde geçmeli (yaklaşık kontrol).
        target, err = _find_target(doc, {**loc, "fikra": None, "bent": None})
        if target is None:
            return VerifyResult("hedef_bulunamadi", err)
        probe, actual = _norm(new)[:150], _madde_text(target)
        if probe and probe in actual:
            return VerifyResult("uyumlu", "eklenen metin hedef maddede geçiyor", probe, actual)
        return VerifyResult("uyumsuz", "eklenen metin hedef maddede bulunamadı", probe, actual)

    if op == "BIRIM_DEGISTIR" and rec.get("unit") == "madde":
        target, err = _find_target(doc, loc)
        if target is None:
            return VerifyResult("hedef_bulunamadi", err)
        # Yeni metni aynı ayrıştırıcıdan geçir ki iki taraf aynı biçimde karşılaştırılsın.
        new_doc = parse_structure("BAŞLIK\n" + (rec.get("new_text") or ""))
        if not new_doc.maddeler:
            return VerifyResult("kontrol_edilemedi", "yeni metin madde olarak ayrıştırılamadı")
        expected, actual = _madde_text(new_doc.maddeler[0]), _madde_text(target)
        ok = expected == actual
        return VerifyResult("uyumlu" if ok else "uyumsuz",
                            "madde metni birebir aynı" if ok else "madde metni farklı", expected, actual)

    if op == "BIRIM_DEGISTIR" and rec.get("unit") == "fikra":
        # Tek alıntı birden fazla fıkra içerebilir: "(2) ... \n(3) ..." -> 2. ve 3. fıkrayla karşılaştır.
        nums = [int(n) for n in re.findall(r"(?m)^\s*\((\d+)\)\s", rec.get("new_text") or "")]
        if len(nums) > 1:
            madde, err = _find_target(doc, {**loc, "fikra": None, "bent": None})
            if madde is None:
                return VerifyResult("hedef_bulunamadi", err)
            found = {f.num: f for f in madde.fikralar}
            if any(n not in found for n in nums):
                return VerifyResult("hedef_bulunamadi", f"fıkralar {nums} konsolide metinde eksik")
            expected = _norm(re.sub(r"(?m)^\s*\(\d+\)\s*", "", rec["new_text"]))
            actual = _norm(" ".join(_unit_text(found[n]) for n in nums))
            ok = expected == actual
            return VerifyResult("uyumlu" if ok else "uyumsuz",
                                f"fıkralar {nums} birebir aynı" if ok else f"fıkralar {nums} farklı", expected, actual)

    if op == "BIRIM_DEGISTIR" and rec.get("unit") in ("fikra", "bent"):
        target, err = _find_target(doc, loc)
        if target is None:
            return VerifyResult("hedef_bulunamadi", err)
        expected = _norm(re.sub(r"^(\(\d+\)|[a-zçğıöşü]\))\s*", "", rec.get("new_text") or ""))
        actual = _unit_text(target)
        ok = expected == actual
        return VerifyResult("uyumlu" if ok else "uyumsuz",
                            "birim metni birebir aynı" if ok else "birim metni farklı", expected, actual)

    if op in ("IBARE_DEGISTIR", "IBARE_EKLE"):
        target, err = _find_target(doc, loc)
        if target is None:
            return VerifyResult("hedef_bulunamadi", err)
        actual = _unit_text(target)
        new = _norm(rec.get("new_text"))
        if new and new in actual:
            return VerifyResult("uyumlu", "yeni ibare hedef metinde geçiyor", new, actual)
        return VerifyResult("uyumsuz", "yeni ibare hedef metinde bulunamadı", new, actual)

    if op == "BIRIM_KALDIR":
        target, err = _find_target(doc, loc)
        if target is None:
            # Kaldırılan birim konsolide metinden tamamen çıkmış olabilir: bu da tutarlı.
            return VerifyResult("uyumlu", f"hedef konsolide metinde yok ({err})")
        anns = getattr(target, "annotations", [])
        if any(a.type == "Mülga" for a in anns) or not _unit_text(target):
            return VerifyResult("uyumlu", "hedef mülga olarak işaretli")
        return VerifyResult("uyumsuz", "hedef hâlâ yürürlükte görünüyor")

    return VerifyResult("kontrol_edilemedi", f"{op} için kontrol henüz yok")


def verify(records: list[dict], consolidated_text: str) -> list[tuple[dict, VerifyResult]]:
    doc = parse_structure(consolidated_text)
    return [(r, verify_record(r, doc)) for r in records]


def _overlaps(a: dict, b: dict) -> bool:
    """İki konum aynı birime (veya biri diğerini kapsayan birime) mi dokunuyor?"""
    if not a.get("madde") or not b.get("madde"):
        return False
    if (a.get("madde_type"), a["madde"]) != (b.get("madde_type"), b["madde"]):
        return False
    for lvl in ("fikra", "bent", "alt_bent"):
        if a.get(lvl) is not None and b.get(lvl) is not None and a[lvl] != b[lvl]:
            return False
    return True


def _effective_location(rec: dict) -> dict:
    """Madde ekleme kayıtlarında hedef, eklenen maddenin kendisidir (sonraki değişikliklerle eşleşsin diye)."""
    loc = rec.get("location") or {}
    if rec["operation"] == "BIRIM_EKLE" and not loc.get("madde") and rec.get("new_text"):
        added = parse_structure("BAŞLIK\n" + rec["new_text"]).maddeler
        if added:
            return {"madde_type": added[0].kind, "madde": added[0].num,
                    "fikra": None, "bent": None, "alt_bent": None}
    return loc


def verify_chronological(amendment_records: list[list[dict]], consolidated_text: str):
    """Değişiklikleri tarih sırasıyla ele alır. Uyumsuz çıkan bir kayıttan sonra aynı birime
    dokunan başka bir değişiklik varsa, sonucu 'sonradan_degisti' olarak yeniden sınıflandırır.

    Döndürür: [(değişiklik_sırası, kayıt, VerifyResult), ...]
    """
    doc = parse_structure(consolidated_text)
    flat = [(i, r) for i, recs in enumerate(amendment_records) for r in recs]
    out = []
    for k, (i, rec) in enumerate(flat):
        res = verify_record(rec, doc)
        if res.status in ("uyumsuz", "hedef_bulunamadi"):
            here = _effective_location(rec)
            later = [r for j, r in flat[k + 1:] if j > i and _overlaps(here, _effective_location(r))]
            if later:
                res = VerifyResult("sonradan_degisti",
                                   f"{res.detail}; aynı birime sonradan {len(later)} değişiklik daha dokunmuş",
                                   res.expected, res.actual)
        out.append((i, rec, res))
    return out
