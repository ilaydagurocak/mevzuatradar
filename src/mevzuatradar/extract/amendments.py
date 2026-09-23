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

from mevzuatradar.parse.structure import MADDE_RE, parse_structure

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
    rf"(?:(?P<mtype>[Gg]eçici|[Ee]k)\s+)?(?P<mnum>{_MNUM})\s+maddes(?!inden)",
)
# Çoklu hedef: "9 uncu ve 10 uncu maddelerinde", "birinci, dördüncü ve beşinci fıkralarında"
MADDE_LIST = re.compile(rf"(?P<list>{_MNUM}(?:\s*,\s*{_MNUM})*\s+ve\s+{_MNUM})\s+maddeleri")
FIKRA_LIST = re.compile(rf"(?P<list>(?:{_ORD_ALT})(?:\s*,\s*(?:{_ORD_ALT}))*\s+ve\s+(?:{_ORD_ALT}))\s+fıkra(?:ları|sı)")
FIKRA_REF = re.compile(rf"(?P<ford>{_ORD_ALT})\s+fıkras(?!ından)")
BENT_REF = re.compile(r"\((?P<bent>(?P<bl>[a-zçğıöşü])(?P=bl){0,2})\)\s+bend(?!inden)")
ALTBENT_REF = re.compile(r"\((?P<ab>\d+)\)\s+numaralı\s+alt\s+bend(?!inden)")
CUMLE_REF = re.compile(rf"(?P<cord>{_ORD_ALT})\s+cümles")
CUMLE_LIST = re.compile(rf"(?P<list>(?:{_ORD_ALT})(?:\s*,\s*(?:{_ORD_ALT}))*\s+ve\s+(?:{_ORD_ALT}))\s+cümleleri")
_LET = "[a-zçğıöşü]{1,3}"
BENT_LIST = re.compile(rf"(?P<list>\({_LET}\)(?:\s*,\s*\({_LET}\))*\s+ve\s+\({_LET}\))\s+(?:bentleri|bendi)")
ALTBENT_LIST = re.compile(r"(?P<list>\(\d+\)(?:\s*,\s*\(\d+\))*\s+ve\s+\(\d+\))\s+numaralı\s+alt\s+bentleri")
# Hedef bölgesinin başlangıcı: "... Yönetmeliğin" / "Aynı Yönetmeliğe" (yönetmelik adındaki "ile"yi bölmemek için)
REG_ANCHOR = re.compile(r"(?:Yönetmeli|Tebli)ğ(?:in|e)\b")
INSERT_AFTER = re.compile(
    rf"(?:(?P<ford>{_ORD_ALT})\s+fıkrasından|\((?P<bent>[a-zçğıöşü]{{1,3}})\)\s+bendinden|"
    rf"(?P<mnum>{_MNUM})\s+maddesinden)\s+sonra\s+gelmek\s+üzere"
)
TARGET_REG = re.compile(
    r"yayımlanan\s+(?P<name>.+?)\s*(?P<kind>Yönetmeli|Tebli)ğ(?:in|e)\b"
)
SAME_REG = re.compile(r"\bAynı\s+(?:Yönetmeli|Tebli)ğ(?:in|e)\b")

# --- Ekler (yönetmeliğe bağlı form/tablolar): "Ek-5", "EK-1/A", "EK-11-A", "EK-19’u" ---------
_EK = r"(?:EK|Ek)-\d+(?:[-/][A-ZÇĞİÖŞÜ])?(?:[’']\w+)?"
_EK_ID = re.compile(r"(?:EK|Ek)-(\d+(?:[-/][A-ZÇĞİÖŞÜ])?)")
# Ekin İÇİNDEKİ bir yere yapılan değişiklik: "Ek-1’in 40 ıncı fıkrası", "EK-1’inin Birinci Bölümünün ..."
EK_INTERNAL = re.compile(r"(?:EK|Ek)-(?P<ek>\d+(?:[-/][A-ZÇĞİÖŞÜ])?)[’'](?:in|inin|ın|ının|un|unun|ün|ünün)\b")

# --- Operasyonlar -------------------------------------------------------------
Q = "“([^”]*)”"
OPS: list[tuple[str, re.Pattern, str]] = [
    # (operasyon adı, desen, konum segmenti: "before" = eşleşmeden önce, "through" = eşleşme dahil)
    ("IBARE_EKLE", re.compile(
        # "... ibaresi eklenmiştir" veya ortak fiil: "... ibaresi, “X” ibaresinden sonra ... ibaresi eklenmiştir"
        rf"{Q}\s+ibare(?:sinden|lerinden)\s+(sonra|önce)\s+gelmek\s+üzere\s+{Q}\s+ibare(?:si|leri)"
        rf"(?=\s+eklenmiş|\s*,[^.]*?eklenmiş)"
    ), "before"),
    # "şeklinde" / "olarak" eşanlamlı; "şeklide" resmi metinde görülen bir yazım hatası
    ("IBARE_DEGISTIR", re.compile(rf"{Q}\s+ibare(?:si|leri)\s+{Q}\s+(?:şeklinde|şeklide|olarak)"), "before"),
    ("BASLIK_DEGISTIR", re.compile(rf"başlığı\s+{Q}\s+şeklinde"), "through"),
    ("EK_EKLE", re.compile(rf"(?P<ekler>{_EK}(?:\s*,\s*{_EK})*(?:\s+ve\s+{_EK})?)\s+eklenmiş"), "through"),
    ("EK_DEGISTIR", re.compile(rf"(?P<ekler>{_EK}(?:\s*,\s*{_EK})*(?:\s+ve\s+{_EK})?)\s+ekteki\s+şekilde\s+değiştirilmiş"),
     "through"),
    ("IBARE_KALDIR", re.compile(
        rf"{Q}\s+ibare(?:si|leri)\s+(?:yürürlükten\s+kaldırılmış|metinden\s+çıkarılmış)"
    ), "before"),
    ("BIRIM_DEGISTIR", re.compile(
        r"(?P<unit>alt\s+bentleri|alt\s+bendi|bentleri|bendi|fıkraları|fıkrası|maddeleri|maddesi|başlığı|cümleleri|cümlesi)"
        r"(?:\s+(?:başlığıyla|başlığı\s+ile)\s+birlikte)?\s+aşağıdaki\s+şekilde\s+değiştirilmiş"
    ), "through"),
    ("BIRIM_KALDIR", re.compile(
        r"(?P<unit>alt\s+bendi|alt\s+bentleri|bendi|bentleri|fıkrası|fıkraları|maddesi|maddeleri|cümlesi|cümleleri)"
        r"\s+yürürlükten\s+kaldırılmış"
    ), "through"),
    ("BIRIM_EKLE", re.compile(
        rf"(?:aşağıdaki|aşağıda\s+yer\s+alan)\s+(?:(?P<newnum>\d+/[A-ZÇĞİÖŞÜ])\s+|"
        rf"(?:{_ORD_ALT})(?:\s*,\s*(?:{_ORD_ALT}))*(?:\s+ve\s+(?:{_ORD_ALT}))?\s+|\([a-zçğıöşü\d]{1,3}\)\s+)?"
        r"(?P<unit>geçici\s+madde|ek\s+madde|alt\s+bentler|alt\s+bent|fıkralar|fıkra|bentler|bent|"
        r"maddesi|maddeler|madde|cümleler|cümle)\s+eklenmiş"
    ), "through"),
]

_UNIT_NORM = [
    ("alt bent", "alt_bent"), ("alt bend", "alt_bent"), ("geçici madde", "gecici_madde"), ("ek madde", "ek_madde"),
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
    cumle: str | None = None  # "1" veya "3,4"


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
    if (bl := list(BENT_LIST.finditer(segment))):
        letters = re.findall(r"\(([a-zçğıöşü]{1,3})\)", bl[-1]["list"])
        locs = [Location(madde_type=l.madde_type, madde=l.madde, fikra=l.fikra, bent=b) for l in locs for b in letters]
    if (al := list(ALTBENT_LIST.finditer(segment))):
        nums = [int(n) for n in re.findall(r"\((\d+)\)", al[-1]["list"])]
        locs = [Location(madde_type=l.madde_type, madde=l.madde, fikra=l.fikra, bent=l.bent, alt_bent=n)
                for l in locs for n in nums]
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
        new = Location(madde_type={"geçici": "gecici", "ek": "ek"}.get((mm["mtype"] or "").lower(), "normal"),
                       madde=_mnum(mm["mnum"]))
    if fikra_m:
        new.fikra, new.bent, new.alt_bent = ORDINALS[fikra_m[-1]["ford"]], None, None
    if bent_m:
        new.bent, new.alt_bent = bent_m[-1]["bent"], None
    if alt_m:
        new.alt_bent = int(alt_m[-1]["ab"])
    if madde_m or fikra_m or bent_m or alt_m:
        new.cumle = None
    if (cl := list(CUMLE_LIST.finditer(segment))):
        new.cumle = ",".join(str(ORDINALS[o]) for o in re.findall(_ORD_ALT, cl[-1]["list"]))
    elif (cm := list(CUMLE_REF.finditer(segment))):
        new.cumle = str(ORDINALS[cm[-1]["cord"]])
    return new


def _clean_block(text: str) -> str:
    text = text.strip()
    if text.startswith(("“", '"')):
        text = text[1:]
    if text.endswith(("”", '"')):
        text = text[:-1]
    return re.sub(r"[ \t]+", " ", text).strip()


def _quote_spans(text: str) -> list[tuple[int, int]]:
    """En dıştaki alıntıların (başlangıç, bitiş) aralıkları. Türkçe tırnaklar iç içe olabilir:
    “(3) ... “Beşinci Grup-Zarar Niteliğindeki Krediler” altında ...” tek bir alıntıdır."""
    spans, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "“":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "”" and depth > 0:
            depth -= 1
            if depth == 0:
                spans.append((start, i + 1))
    if not spans:  # Türkçe tırnak yoksa düz tırnak çiftleri
        spans = [(m.start(), m.end()) for m in re.finditer(r'"[^"]*"', text)]
    return spans


def _extract_quotes(block: str) -> list[str]:
    return [block[a + 1:b - 1].strip() for a, b in _quote_spans(block)]


def _mask_quotes(text: str) -> str:
    """Alıntıların içini aynı uzunlukta dolgu ile değiştirir; konum çözümlemesi alıntı içeriğine bakmasın."""
    chars = list(text)
    for a, b in _quote_spans(text):
        for i in range(a + 1, b - 1):
            chars[i] = "_"
    return "".join(chars)


_HAS_REF = [MADDE_REF, FIKRA_REF, BENT_REF, ALTBENT_REF, CUMLE_REF, FIKRA_LIST, BENT_LIST, ALTBENT_LIST, CUMLE_LIST]
_PLURAL_UNITS = ("fıkralar", "bentler", "alt bentler", "maddeler", "cümleler")


def _part_unit(part: str) -> str | None:
    """Parçadaki son birim kelimesine göre birim ('... fıkrasının birinci cümlesi' -> cumle)."""
    words = re.findall(r"(alt\s+bent|alt\s+bend|cümle|fıkra|bent|bend|madde)", part)
    return _norm_unit(words[-1]) if words else None


_GENITIVE_END = re.compile(r"(?:maddesinin|maddelerinin|fıkrasının|fıkralarının|bendinin|bentlerinin)\s*$")
_UNIT_END = re.compile(r"(?:madde|fıkra|bent|bend|cümle)\w*\s*$")


def _split_targets(text: str, sep: str) -> list[str] | None:
    """Metni ayırıcıya göre hedef parçalarına böler. Kurallar:
    - '-nin' ekiyle biten parça ('17 nci maddesinin,') hedef değil bağlamdır; sonraki parçaya eklenir.
    - Son parça dışındaki her parça bir birim adıyla bitmelidir ('... fıkrası', '... bendi').
      '26 ncı maddesinin yedinci ve sekizinci fıkrası' bu yüzden bölünmez (liste olarak çözülür).
    Uygun bölme yoksa None döner."""
    raw = re.split(sep, text)
    if len(raw) < 2:
        return None
    parts, carry = [], ""
    for i, piece in enumerate(raw):
        piece = f"{carry} {piece}".strip() if carry else piece
        carry = ""
        if i < len(raw) - 1:
            if _GENITIVE_END.search(piece):
                carry = piece
                continue
            if not _UNIT_END.search(piece):
                return None
        parts.append(piece)
    if len(parts) < 2 or not all(any(p.search(x) for p in _HAS_REF) for x in parts):
        return None
    return parts


def _targets(loc: Location, segment: str) -> tuple[Location, list[tuple[Location, str | None]]]:
    """Bir işlemin segmentinden hedef konumları çıkarır. '... (e) bendi ile ... (h) bendi' gibi
    'ile' ile bağlanmış hedefleri ayırır; yönetmelik adındaki 'ile'yi bölmemek için yalnızca
    '... Yönetmeliğin' ifadesinden SONRAKİ bölgeye bakar. Dönüş: (son konum, [(hedef, birim_ipucu)])."""
    anchors = list(REG_ANCHOR.finditer(segment))
    cut = anchors[-1].end() if anchors else 0
    loc = _update_location(loc, segment[:cut])
    # "birinci fıkrası, ikinci fıkrasının birinci cümlesi ve üçüncü fıkrasının birinci cümlesi":
    # yalnızca HER parça kendi başına bir referans içeriyorsa bölünür; böylece
    # "birinci, dördüncü ve beşinci fıkralarında" gibi listeler bölünmez.
    # Önce en ince ayrım denenir; tutmazsa yalnızca "ile" ("üçüncü ve dördüncü cümleleri ile ...").
    for sep in (r"\s*,\s*|\s+ve\s+|\s+ile\s+", r"\s+ile\s+"):
        parts = _split_targets(segment[cut:], sep)
        if parts:
            out, sub = [], loc
            for part in parts:
                sub = _update_location(sub, part)
                out += [(t, _part_unit(part)) for t in _expand_locations(sub, part)]
            return sub, out
    rest = segment[cut:]
    loc = _update_location(loc, rest)
    return loc, [(t, None) for t in _expand_locations(loc, rest)]


# "Aynı Yönetmeliğin 17 nci maddesinde aşağıdaki düzenlemeler yapılmıştır:" + alt maddeler (a), (b), ...
DUZENLEMELER = re.compile(r"^(?P<ctx>.*?)\s+madde(?:si|sin)(?:de|e)\s+aşağıdaki\s+düzenlemeler\s+yapılmış")
SUB_ITEM = re.compile(r"^(?P<m>[a-zçğıöşü])\)\s+(?P<rest>.+)$")


def _tr_lower_first(text: str) -> str:
    if not text:
        return text
    first = {"I": "ı", "İ": "i"}.get(text[0], text[0].lower())
    return first + text[1:]


def _split_sub_items(block: str) -> list[str]:
    """Alt maddeleri (a), (b), ... ve her birine ait alıntı satırlarını gruplar."""
    items, current, depth = [], None, 0
    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        m = SUB_ITEM.match(stripped) if depth == 0 else None
        if m and not stripped.startswith(("“", '"')):
            current = [m["rest"]]
            items.append(current)
        elif current is not None:
            current.append(stripped)
        depth = max(0, depth + stripped.count("“") - stripped.count("”"))
    return ["\n".join(it) for it in items]


def _split_by_markers(text: str, targets: list) -> list[str] | None:
    """Birden çok hedefe tek/az sayıda alıntı düştüğünde metni işaretlerine göre böler.
    Hedefler fıkra ise '(n)', bent ise 'x)', alt bent ise 'n)' satır başı işaretleri kullanılır.
    Her hedef kendi işaretini bulamazsa None döner."""
    if len(targets) < 2:
        return None
    locs = [t for t, _ in targets]
    if all(l.alt_bent is not None for l in locs):
        pat, keys = r"(?m)^\s*(\d+)\)\s", [str(l.alt_bent) for l in locs]
    elif all(l.bent for l in locs):
        pat, keys = r"(?m)^\s*([a-zçğıöşü]{1,3})\)\s", [l.bent for l in locs]
    elif all(l.fikra is not None for l in locs):
        pat, keys = r"(?m)^\s*\((\d+)\)\s", [str(l.fikra) for l in locs]
    else:
        return None
    hits = list(re.finditer(pat, text))
    chunks = {}
    for k, h in enumerate(hits):
        end = hits[k + 1].start() if k + 1 < len(hits) else len(text)
        chunks.setdefault(h.group(1), text[h.start():end].strip())
    if not all(key in chunks for key in keys):
        return None
    return [chunks[key] for key in keys]


def extract_from_article(article_num: str, text: str, current_reg: str | None) -> tuple[list[Amendment], str | None]:
    """Tek bir değişiklik maddesinden (ör. 'MADDE 2 – Aynı Yönetmeliğin ...') kayıtları çıkarır."""
    if (tm := TARGET_REG.search(text)):
        suffix = "Yönetmelik" if tm["kind"] == "Yönetmeli" else "Tebliğ"
        current_reg = f"{tm['name'].strip()} {suffix}"
    elif not SAME_REG.search(text) and not re.search(r"(?:Yönetmeli|Tebli)ğ(?:in|e)\b", text):
        return [], current_reg

    lines = text.split("\n")
    # Alt maddeli yapı: her alt madde, ana cümledeki bağlamla ("... 17 nci maddesinin") birleştirilip
    # kendi başına bir değişiklik cümlesi gibi işlenir.
    if (dz := DUZENLEMELER.search(lines[0])):
        context = f"{dz['ctx']} maddesinin"
        results = []
        for item in _split_sub_items("\n".join(lines[1:])):
            first, *rest = item.split("\n")
            sub = f"{context} {_tr_lower_first(first)}" + ("\n" + "\n".join(rest) if rest else "")
            recs, _ = extract_from_article(article_num, sub, current_reg)
            results.extend(recs)
        return results, current_reg

    operative = lines[0]
    masked = _mask_quotes(operative)  # konum çözümlemesi için
    block = "\n".join(lines[1:])

    matches = []
    for name, pat, seg_mode in OPS:
        for m in pat.finditer(operative):
            matches.append((m.start(), m.end(), name, m, seg_mode))
    matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    kept, last_end = [], -1
    for mt in matches:
        if mt[0] >= last_end:
            kept.append(mt)
            last_end = mt[1]

    # 1. geçiş: her işlemin hedeflerini bul
    plan, loc, prev_end = [], Location(), 0
    for start, end, name, m, seg_mode in kept:
        segment = masked[prev_end: start if seg_mode == "before" else end]
        before = loc
        loc, targets = _targets(loc, segment)
        plan.append((name, m, segment, before, loc, targets))
        prev_end = end

    # 2. geçiş: alıntı bloklarını işlemlere dağıt
    quoted = _extract_quotes(block)
    block_idx = [i for i, p in enumerate(plan) if p[0] in ("BIRIM_DEGISTIR", "BIRIM_EKLE")]
    quota = {i: len(plan[i][5]) for i in block_idx}
    alloc: dict[int, list[str]] = {}
    if block_idx and quoted and len(block_idx) == 1 and sum(quota.values()) != len(quoted) \
            and (by_marker := _split_by_markers("\n".join(quoted), plan[block_idx[0]][5])):
        alloc = {block_idx[0]: by_marker}                           # işaretlere göre: (1), (5), a), 2) ...
    elif block_idx and quoted:
        if sum(quota.values()) == len(quoted):                      # her hedefe bir alıntı
            it = iter(quoted)
            alloc = {i: [next(it) for _ in range(quota[i])] for i in block_idx}
        elif len(block_idx) == len(quoted):                         # her işleme bir alıntı
            alloc = {i: [q] * quota[i] for i, q in zip(block_idx, quoted)}
        else:
            extra = len(quoted) - sum(quota.values())
            plural = [i for i in block_idx if re.sub(r"\s+", " ", plan[i][1]["unit"]) in _PLURAL_UNITS]
            if extra > 0 and plural:                                 # fazlalık çoğul birime ("fıkralar")
                j, it = plural[-1], iter(quoted)
                for i in block_idx:
                    n = quota[i] + (extra if i == j else 0)
                    chunk = [next(it) for _ in range(n)]
                    alloc[i] = chunk if len(chunk) == quota[i] else ["\n".join(chunk)] * quota[i]
            else:                                                    # son çare: hepsi birlikte
                alloc = {i: ["\n".join(quoted)] * quota[i] for i in block_idx}
    elif block_idx:
        alloc = {i: [_clean_block(block) or None] * quota[i] for i in block_idx}

    # 3. geçiş: kayıtları üret
    results: list[Amendment] = []
    for i, (name, m, segment, before, loc, targets) in enumerate(plan):
        base = Amendment(article_num, current_reg, name)
        if name == "IBARE_DEGISTIR":
            base.unit, base.old_text, base.new_text = "ibare", m.group(1), m.group(2)
        elif name == "IBARE_EKLE":
            base.unit, base.anchor_text, base.anchor_position, base.new_text = "ibare", m.group(1), m.group(2), m.group(3)
        elif name == "IBARE_KALDIR":
            base.unit, base.old_text = "ibare", m.group(1)
        elif name == "BASLIK_DEGISTIR":
            base.unit, base.new_text = "baslik", m.group(1)
        elif name in ("EK_EKLE", "EK_DEGISTIR"):
            base.unit = "ek"
            targets = [(Location(madde_type="ek_belge", madde=f"EK-{e.upper()}"), None)
                       for e in _EK_ID.findall(m["ekler"])]
        else:
            base.unit = _norm_unit(m["unit"])
        if name == "BIRIM_EKLE" and (ia := INSERT_AFTER.search(segment)):
            base.insert_after = ((ia["mnum"] and _mnum(ia["mnum"])) or (ia["ford"] and str(ORDINALS[ia["ford"]])) or ia["bent"])
        texts = alloc.get(i)
        ek_ic = EK_INTERNAL.search(segment)
        for k, (t, hint) in enumerate(targets):
            if ek_ic:  # ekin içindeki bir yer: madde yapısına ait değil
                t = Location(madde_type="ek_belge", madde=f"EK-{ek_ic['ek'].upper()}", fikra=t.fikra, bent=t.bent,
                             alt_bent=t.alt_bent, cumle=t.cumle)
            rec = Amendment(**{**asdict(base), "location": t})
            if hint:
                rec.unit = hint
            if texts is not None:
                rec.new_text = texts[k] if k < len(texts) else texts[-1]
            if rec.unit == "baslik":
                rec.location = Location(madde_type=t.madde_type, madde=t.madde)
            elif name == "BIRIM_EKLE":
                if rec.unit in ("madde", "gecici_madde", "ek_madde") and not MADDE_REF.search(segment):
                    rec.location = Location()  # yönetmeliğe yeni madde: hedef madde yok
                elif rec.unit == "fikra":
                    rec.location = Location(madde_type=t.madde_type, madde=t.madde)  # maddeye fıkra eklenir
                elif rec.unit == "bent":  # fıkraya bent eklenir: hedef fıkranın kendisi
                    rec.location = Location(madde_type=t.madde_type, madde=t.madde, fikra=t.fikra)
                elif rec.unit == "alt_bent":  # bende alt bent eklenir: hedef bendin kendisi
                    rec.location = Location(madde_type=t.madde_type, madde=t.madde, fikra=t.fikra, bent=t.bent)
            results.append(rec)
    return results, current_reg


def extract_amendments(text: str) -> list[Amendment]:
    # Ayrıştırıcı ilk satırı belge başlığı sayar. Metin doğrudan bir madde ile başlıyorsa
    # (ör. API'ye tek bir madde yapıştırıldığında) o madde kaybolmasın diye başlık eklenir.
    ilk = next((l.strip() for l in text.split("\n") if l.strip()), "")
    if MADDE_RE.match(ilk):
        text = "BAŞLIK\n" + text
    doc = parse_structure(text)
    out: list[Amendment] = []
    current_reg = None
    for madde in doc.maddeler:
        recs, current_reg = extract_from_article(madde.key, madde.raw_text, current_reg)
        out.extend(recs)
    return out
