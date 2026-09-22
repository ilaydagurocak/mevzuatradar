"""Değişiklik yönetmeliklerinden yapılandırılmış değişiklik kayıtları çıkaran
kural tabanlı BASELINE.

Amaç en iyi sonucu almak değil, ileride eğitilecek NER/RE modelinin ve LLM
yaklaşımının geçmesi gereken ölçülebilir bir alt sınır koymaktır.

Bilinen sınırlamalar (değerlendirmede görünür olmaları için bilinçli bırakıldı):
- Birden fazla hedef ("9 uncu ve 10 uncu maddelerinde") tek kayda indirgenir.
- "bu fıkranın", "anılan bendin" gibi göreli referanslar çözülmez.
- Cümle ekleme/değiştirme ("ikinci cümlesi") desteklenmez.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from mevzuatradar.parse.structure import parse_structure

# --- Türkçe sıra sayıları ----------------------------------------------------
_UNITS = ["bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_UNIT_ORD = ["birinci", "ikinci", "üçüncü", "dördüncü", "beşinci",
             "altıncı", "yedinci", "sekizinci", "dokuzuncu"]
_TENS = {"on": 10, "yirmi": 20, "otuz": 30}
_TENS_ORD = {"onuncu": 10, "yirminci": 20, "otuzuncu": 30}

ORDINALS: dict[str, int] = {w: i + 1 for i, w in enumerate(_UNIT_ORD)}
ORDINALS.update(_TENS_ORD)
for tw, tv in _TENS.items():
    for i, uw in enumerate(_UNIT_ORD):
        ORDINALS[f"{tw} {uw}"] = tv + i + 1

_ORD_ALT = "|".join(sorted(map(re.escape, ORDINALS), key=len, reverse=True))
_NUM_SUFFIX = r"(?:inci|ıncı|nci|ncı|üncü|uncu)"

# --- Konum referansları --------------------------------------------------------
_MNUM = rf"(?:\d+/[A-ZÇĞİÖŞÜ]|\d+(?=\s*{_NUM_SUFFIX}))(?:\s*{_NUM_SUFFIX})?"
MADDE_REF = re.compile(
    rf"(?:(?P<mtype>geçici|ek)\s+)?(?P<mnum>{_MNUM})\s+maddes(?!inden)",
)
# Çoklu hedef: "9 uncu ve 10 uncu maddelerinde", "birinci, dördüncü ve beşinci fıkralarında"
MADDE_LIST = re.compile(rf"(?P<list>{_MNUM}(?:\s*,\s*{_MNUM})*\s+ve\s+{_MNUM})\s+maddeleri")
FIKRA_LIST = re.compile(rf"(?P<list>(?:{_ORD_ALT})(?:\s*,\s*(?:{_ORD_ALT}))*\s+ve\s+(?:{_ORD_ALT}))\s+fıkraları")
FIKRA_REF = re.compile(rf"(?P<ford>{_ORD_ALT})\s+fıkras(?!ından)")
BENT_REF = re.compile(r"\((?P<bent>[a-zçğıöşü])\)\s+bend(?!inden)")
ALTBENT_REF = re.compile(r"\((?P<ab>\d+)\)\s+numaralı\s+alt\s+bend(?!inden)")
INSERT_AFTER = re.compile(
    rf"(?:(?P<ford>{_ORD_ALT})\s+fıkrasından|\((?P<bent>[a-zçğıöşü])\)\s+bendinden|"
    rf"(?P<mnum>{_MNUM})\s+maddesinden)\s+sonra\s+gelmek\s+üzere"
)
TARGET_REG = re.compile(
    r"yayımlanan\s+(?P<name>.+?)\s*(?P<kind>Yönetmeli|Tebli)ğ(?:in|e)\b"
)
SAME_REG = re.compile(r"\bAynı\s+(?:Yönetmeli|Tebli)ğ(?:in|e)\b")

# --- Operasyonlar -------------------------------------------------------------
Q = "“([^”]*)”"
OPS: list[tuple[str, re.Pattern, str]] = [
    # (operasyon adı, desen, konum segmenti: "before" = eşleşmeden önce, "through" = eşleşme dahil)
    ("IBARE_EKLE", re.compile(
        rf"{Q}\s+ibare(?:sinden|lerinden)\s+(sonra|önce)\s+gelmek\s+üzere\s+{Q}\s+ibare(?:si|leri)\s+eklenmiş"
    ), "before"),
    ("IBARE_DEGISTIR", re.compile(rf"{Q}\s+ibare(?:si|leri)\s+{Q}\s+şeklinde"), "before"),
    ("BASLIK_DEGISTIR", re.compile(rf"başlığı\s+{Q}\s+şeklinde"), "through"),
    ("IBARE_KALDIR", re.compile(
        rf"{Q}\s+ibare(?:si|leri)\s+(?:yürürlükten\s+kaldırılmış|metinden\s+çıkarılmış)"
    ), "before"),
    ("BIRIM_DEGISTIR", re.compile(
        r"(?P<unit>alt\s+bendi|bendi|fıkrası|maddesi|başlığı)\s+aşağıdaki\s+şekilde\s+değiştirilmiş"
    ), "through"),
    ("BIRIM_KALDIR", re.compile(
        r"(?P<unit>alt\s+bendi|alt\s+bentleri|bendi|bentleri|fıkrası|fıkraları|maddesi|maddeleri)"
        r"\s+yürürlükten\s+kaldırılmış"
    ), "through"),
    ("BIRIM_EKLE", re.compile(
        rf"(?:aşağıdaki|aşağıda\s+yer\s+alan)\s+(?:(?P<newnum>\d+/[A-ZÇĞİÖŞÜ])\s+|(?:{_ORD_ALT})\s+|\([a-zçğıöşü\d]\)\s+)?"
        r"(?P<unit>geçici\s+madde|ek\s+madde|alt\s+bentler|alt\s+bent|fıkralar|fıkra|bentler|bent|"
        r"maddesi|maddeler|madde|cümleler|cümle)\s+eklenmiş"
    ), "through"),
]

_UNIT_NORM = [
    ("alt bent", "alt_bent"), ("geçici madde", "gecici_madde"), ("ek madde", "ek_madde"),
    ("başlı", "baslik"), ("bent", "bent"), ("bend", "bent"), ("fıkra", "fikra"),
    ("madde", "madde"), ("cümle", "cumle"),
]


def _norm_unit(u: str | None) -> str | None:
    if not u:
        return None
    u = re.sub(r"\s+", " ", u)
    return next((v for k, v in _UNIT_NORM if u.startswith(k)), u)


@dataclass
class Location:
    madde_type: str = "normal"
    madde: str | None = None
    fikra: int | None = None
    bent: str | None = None
    alt_bent: int | None = None


@dataclass
class Amendment:
    amending_article: str
    target_regulation: str | None
    operation: str
    location: Location = field(default_factory=Location)
    unit: str | None = None
    old_text: str | None = None
    new_text: str | None = None
    anchor_text: str | None = None
    anchor_position: str | None = None  # "sonra" | "önce"
    insert_after: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _mnum(text: str) -> str:
    """'4 üncü' -> '4', '28/A' -> '28/A'."""
    return re.match(r"\d+(?:/[A-ZÇĞİÖŞÜ])?", text).group()


def _expand_locations(loc: Location, segment: str) -> list[Location]:
    """Çoklu hedefli ifadeleri ('9 uncu ve 10 uncu maddelerinde') ayrı konumlara açar."""
    locs = [loc]
    if (ml := list(MADDE_LIST.finditer(segment))):
        nums = re.findall(r"\d+(?:/[A-ZÇĞİÖŞÜ])?", ml[-1]["list"])
        locs = [Location(madde_type=loc.madde_type, madde=n) for n in nums]
    if (fl := list(FIKRA_LIST.finditer(segment))):
        ords = re.findall(_ORD_ALT, fl[-1]["list"])
        locs = [Location(madde_type=l.madde_type, madde=l.madde, fikra=ORDINALS[o]) for l in locs for o in ords]
    return locs


def _update_location(loc: Location, segment: str) -> Location:
    """Segmentteki en son referansa göre konumu günceller; üst seviye değişince alt seviyeler sıfırlanır."""
    madde_m = list(MADDE_REF.finditer(segment))
    fikra_m = list(FIKRA_REF.finditer(segment))
    bent_m = list(BENT_REF.finditer(segment))
    alt_m = list(ALTBENT_REF.finditer(segment))
    new = Location(**asdict(loc))
    if madde_m:
        mm = madde_m[-1]
        new = Location(madde_type={"geçici": "gecici", "ek": "ek"}.get(mm["mtype"] or "", "normal"),
                       madde=_mnum(mm["mnum"]))
    if fikra_m:
        new.fikra, new.bent, new.alt_bent = ORDINALS[fikra_m[-1]["ford"]], None, None
    if bent_m:
        new.bent, new.alt_bent = bent_m[-1]["bent"], None
    if alt_m:
        new.alt_bent = int(alt_m[-1]["ab"])
    return new


def _clean_block(text: str) -> str:
    text = text.strip()
    if text.startswith("“"):
        text = text[1:]
    if text.endswith("”"):
        text = text[:-1]
    return re.sub(r"[ \t]+", " ", text).strip()


def extract_from_article(article_num: str, text: str, current_reg: str | None) -> tuple[list[Amendment], str | None]:
    """Tek bir değişiklik maddesinden (ör. 'MADDE 2 – Aynı Yönetmeliğin ...') kayıtları çıkarır."""
    if (tm := TARGET_REG.search(text)):
        suffix = "Yönetmelik" if tm["kind"] == "Yönetmeli" else "Tebliğ"
        current_reg = f"{tm['name'].strip()} {suffix}"
    elif not SAME_REG.search(text) and not re.search(r"(?:Yönetmeli|Tebli)ğ(?:in|e)\b", text):
        return [], current_reg

    # Operatif kısım: alıntı bloğundan önceki ilk satır(lar). Alıntılı yeni metin ayrıca tutulur.
    lines = text.split("\n")
    operative = lines[0]
    block = "\n".join(lines[1:])

    matches = []
    for name, pat, seg_mode in OPS:
        for m in pat.finditer(operative):
            matches.append((m.start(), m.end(), name, m, seg_mode))
    # Çakışan eşleşmeleri ele: daha önce başlayan (ve daha uzun) kazanır.
    matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    kept, last_end = [], -1
    for mt in matches:
        if mt[0] >= last_end:
            kept.append(mt)
            last_end = mt[1]

    # Bir maddede birden fazla "aşağıdaki şekilde/aşağıdaki ... eklenmiştir" varsa, her biri
    # sırasıyla kendi alıntı bloğunu alır (ör. fıkra değiştirilip yeni fıkra eklendiğinde).
    quoted = [q.strip() for q in re.findall(r"“(.*?)”", block, flags=re.S)]
    block_ops = [mt for mt in kept if mt[2] in ("BIRIM_DEGISTIR", "BIRIM_EKLE")]
    split_blocks = len(block_ops) > 1 and len(quoted) == len(block_ops)
    block_iter = iter(quoted)

    results: list[Amendment] = []
    loc, prev_end = Location(), 0
    for start, end, name, m, seg_mode in kept:
        segment = operative[prev_end: start if seg_mode == "before" else end]
        # "(e) bendi ile beşinci fıkrasının (h) bendi aşağıdaki şekilde değiştirilmiştir" + iki alıntı:
        # her hedef sırasıyla kendi alıntısını alır.
        parts = re.split(r"\s+ile\s+", segment)
        if (name in ("BIRIM_DEGISTIR", "BIRIM_EKLE") and len(block_ops) == 1
                and len(quoted) > 1 and len(parts) == len(quoted)):
            unit = _norm_unit(m["unit"])
            for part, q in zip(parts, quoted):
                loc = _update_location(loc, part)
                results.append(Amendment(article_num, current_reg, name, location=loc, unit=unit, new_text=q))
            prev_end = end
            continue
        loc = _update_location(loc, segment)
        rec = Amendment(article_num, current_reg, name, location=loc)
        if name == "IBARE_DEGISTIR":
            rec.unit, rec.old_text, rec.new_text = "ibare", m.group(1), m.group(2)
        elif name == "IBARE_EKLE":
            rec.unit, rec.anchor_text, rec.anchor_position, rec.new_text = "ibare", m.group(1), m.group(2), m.group(3)
        elif name == "IBARE_KALDIR":
            rec.unit, rec.old_text = "ibare", m.group(1)
        elif name == "BASLIK_DEGISTIR":
            rec.unit, rec.new_text = "baslik", m.group(1)
            rec.location = Location(madde_type=loc.madde_type, madde=loc.madde)
        else:
            rec.unit = _norm_unit(m["unit"])
            if name in ("BIRIM_DEGISTIR", "BIRIM_EKLE"):
                if split_blocks:
                    rec.new_text = next(block_iter) or None
                elif len(quoted) > 1:
                    rec.new_text = "\n".join(quoted)
                else:
                    rec.new_text = _clean_block(block) or None
            if rec.unit == "baslik":
                rec.location = Location(madde_type=loc.madde_type, madde=loc.madde)
            if name == "BIRIM_EKLE":
                if (ia := INSERT_AFTER.search(segment)):
                    rec.insert_after = ((ia["mnum"] and _mnum(ia["mnum"])) or (ia["ford"] and str(ORDINALS[ia["ford"]])) or ia["bent"])
                if rec.unit in ("madde", "gecici_madde", "ek_madde") and not MADDE_REF.search(segment):
                    rec.location = Location()  # yönetmeliğe yeni madde: hedef madde yok
                elif rec.unit in ("fikra", "fikralar"):
                    rec.location = Location(madde_type=loc.madde_type, madde=loc.madde)  # maddeye fıkra eklenir
        for target in _expand_locations(rec.location, segment):
            results.append(Amendment(**{**asdict(rec), "location": target}))
        prev_end = end
    return results, current_reg


def extract_amendments(text: str) -> list[Amendment]:
    doc = parse_structure(text)
    out: list[Amendment] = []
    current_reg = None
    for madde in doc.maddeler:
        recs, current_reg = extract_from_article(madde.key, madde.raw_text, current_reg)
        out.extend(recs)
    return out
