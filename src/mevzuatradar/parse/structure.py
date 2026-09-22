"""Türkçe mevzuat metnini madde / fıkra / bent / alt bent ağacına dönüştürür.

Girdi: düz metin (HTML veya PDF'ten çıkarılmış). Çıktı: Document nesnesi.

Değişiklik işaretleri iki biçimde gelir ve ikisi de metinden ayrılıp annotation olarak tutulur:
- Satır içi notlar:  "(Değişik:RG-25/9/2020-31255)"
- Dipnotlar (mevzuat.gov.tr'nin eski konsolide metinleri): "MADDE 26/A –(1) (1) ...",
  "(7) (5) Metin...", "…bilgilendirirler.(3)". Dipnot tanımları belgenin sonunda
  "(1) 1/8/2009 tarihli ve 27306 sayılı Resmî Gazete’de ..." biçimindedir.

Bilinen sınırlamalar:
- Bentlerden sonra gelen kapanış cümlesi ("... ifade eder.") son bende eklenir.
- Madde başlığı, MADDE satırından hemen önceki kısa satır olarak tahmin edilir.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

MADDE_RE = re.compile(
    r"^(?:(?P<kind>GEÇİCİ|Geçici|EK|Ek)\s+)?(?:MADDE|Madde)\s+"
    r"(?P<num>\d+(?:/[A-ZÇĞİÖŞÜ])?)\s*[–—-]\s*(?P<rest>.*)$"
)
BOLUM_RE = re.compile(r"^(?P<ord>[A-ZÇĞİÖŞÜ ]+?)\s+(?P<level>BÖLÜM|KISIM)$")
FIKRA_RE = re.compile(r"^\((?P<num>\d+)\)\s*(?P<rest>.*)$")
BENT_RE = re.compile(r"^(?P<letter>[a-zçğıöşü])\)\s*(?P<rest>.*)$")
ALTBENT_RE = re.compile(r"^(?P<num>\d+)\)\s*(?P<rest>.*)$")
ANNOTATION_RE = re.compile(
    r"\((?P<type>Değişik|Ek|Mülga|İptal)(?:\s+[a-zçğıöşü]+)?\s*:\s*(?P<src>[^)]*)\)"
)
# Dipnot tanımı: "(3) 21/12/2008 tarihli ve 27087 sayılı Resmî Gazete’de yayımlanan Yönetmeliğin
# 2 nci maddesiyle ...". "maddesiyle" şartı, tarihle başlayan gerçek fıkralarla karışmayı önler.
FOOTNOTE_DEF_RE = re.compile(
    r"^\((?P<num>\d+)\)\s*(?P<text>\d{1,2}/\d{1,2}/\d{4}\s+tarihli\b.*Resm[iî]\s+Gazete.*"
    r"madde(?:si|leri)[y]?le.*)$"
)
# Noktalama işaretine bitişik dipnot referansı: "bilgilendirirler.(3)"
INLINE_FOOTNOTE_RE = re.compile(r"(?<=[.;:,])\((?P<num>\d+)\)")
LEADING_NUM_RE = re.compile(r"^\((?P<num>\d+)\)\s*(?P<rest>.*)$")

KIND_MAP = {"GEÇİCİ": "gecici", "Geçici": "gecici", "EK": "ek", "Ek": "ek"}


@dataclass
class Annotation:
    type: str   # Değişik | Ek | Mülga | İptal | Dipnot
    source: str  # ör. "RG-15/3/2023-32134" veya dipnot için "dipnot:3"


@dataclass
class AltBent:
    num: int
    text: str = ""
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class Bent:
    letter: str
    text: str = ""
    alt_bentler: list[AltBent] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class Fikra:
    num: int
    text: str = ""
    bentler: list[Bent] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class Madde:
    kind: str  # normal | gecici | ek
    num: str
    title: str | None = None
    section: str | None = None
    text: str = ""  # fıkrasız maddeler için gövde metni
    fikralar: list[Fikra] = field(default_factory=list)
    raw_text: str = ""  # alıntı blokları dahil ham metin (değişiklik çıkarımı için)
    annotations: list[Annotation] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.num if self.kind == "normal" else f"{self.kind}:{self.num}"


@dataclass
class Document:
    title: str | None = None
    maddeler: list[Madde] = field(default_factory=list)
    footnotes: dict[int, str] = field(default_factory=dict)  # dipnot no -> tanım metni

    def to_dict(self) -> dict:
        return asdict(self)

    def get(self, key: str) -> Madde | None:
        return next((m for m in self.maddeler if m.key == key), None)


def _split_annotations(text: str) -> tuple[str, list[Annotation]]:
    anns = [Annotation(m["type"], m["src"].strip()) for m in ANNOTATION_RE.finditer(text)]
    text = ANNOTATION_RE.sub("", text)
    anns += [Annotation("Dipnot", f"dipnot:{m['num']}") for m in INLINE_FOOTNOTE_RE.finditer(text)]
    text = INLINE_FOOTNOTE_RE.sub("", text)
    clean = re.sub(r"\s{2,}", " ", text).strip()
    return clean, anns


def _append(target, text: str) -> None:
    clean, anns = _split_annotations(text)
    target.annotations.extend(anns)
    if clean:
        target.text = f"{target.text} {clean}".strip()


def _strip_leading_footnote(text: str, target_anns: list[Annotation]) -> str:
    """Satır başındaki '(k)' dipnot referansını ayırır (fıkra numarasından SONRA gelir)."""
    m = LEADING_NUM_RE.match(text)
    if m:
        target_anns.append(Annotation("Dipnot", f"dipnot:{m['num']}"))
        return m["rest"]
    return text


def _start_unit(unit, rest: str) -> None:
    """Yeni fıkra/bent metnini yerleştirir: önce notlar, sonra baştaki dipnot numarası ayrılır.
    '(7) (Değişik:RG-...)(5) Metin' ve '(7) (5) Metin' biçimlerinin ikisi de 'Metin' verir."""
    clean, anns = _split_annotations(rest)
    unit.annotations.extend(anns)
    clean = _strip_leading_footnote(clean, unit.annotations)
    if clean:
        unit.text = f"{unit.text} {clean}".strip()


def _next_nonblank(lines: list[str], i: int) -> str | None:
    for j in range(i + 1, len(lines)):
        if lines[j].strip():
            return lines[j].strip()
    return None


def parse_structure(text: str) -> Document:
    lines = text.replace("\r\n", "\n").split("\n")
    doc = Document()
    section: str | None = None
    expect_section_title = False
    pending_title: tuple[str, list[Annotation]] | None = None
    madde = fikra = bent = altbent = None
    quote_depth = 0

    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue

        # 1) Alıntı blokları ("“...”"): yapı olarak yorumlanmaz, maddenin ham metnine eklenir.
        is_quoted = quote_depth > 0 or line.startswith("“")
        quote_depth = max(0, quote_depth + line.count("“") - line.count("”"))
        if is_quoted:
            if madde is not None:
                madde.raw_text += "\n" + line
            continue

        if doc.title is None:
            doc.title = line
            continue
        if (not doc.maddeler and section is None and line.isupper()
                and not BOLUM_RE.match(line) and not MADDE_RE.match(line)):
            doc.title += " " + line  # birden fazla satıra bölünmüş başlık
            continue

        # 2) Dipnot tanımları (genellikle belgenin sonunda): yapıya dahil edilmez.
        fd = FOOTNOTE_DEF_RE.match(line)
        if fd:
            doc.footnotes[int(fd["num"])] = fd["text"]
            continue

        # 3) Madde başlangıcı
        m = MADDE_RE.match(line)
        if m:
            title, title_anns = pending_title if pending_title else (None, [])
            madde = Madde(
                kind=KIND_MAP.get(m["kind"], "normal"),
                num=m["num"],
                title=title,
                section=section,
                raw_text=line,
                annotations=list(title_anns),
            )
            doc.maddeler.append(madde)
            pending_title = None
            fikra = bent = altbent = None
            rest = m["rest"].strip()
            # "MADDE 5 – (Ek:RG-...) (1) Metin": fıkradan önce gelen notlar maddeye aittir.
            lead = re.match(rf"^(?:{ANNOTATION_RE.pattern}\s*)+(?=\(\d+\))", rest)
            if lead:
                madde.annotations.extend(_split_annotations(lead.group())[1])
                rest = rest[lead.end():]
            # "MADDE 26/A –(1) (1) Metin": ilk numara maddeye ait dipnot, ikincisi fıkra numarası.
            two = re.match(r"^\((?P<fn>\d+)\)\s*(?=\(\d+\))", rest)
            if two:
                madde.annotations.append(Annotation("Dipnot", f"dipnot:{two['fn']}"))
                rest = rest[two.end():]
            # "MADDE 28/A –(4)" ve metin bir sonraki satırda: tek başına duran numara dipnottur.
            elif (alone := re.fullmatch(r"\((?P<fn>\d+)\)", rest)):
                madde.annotations.append(Annotation("Dipnot", f"dipnot:{alone['fn']}"))
                rest = ""
            fm = FIKRA_RE.match(rest)
            if fm:
                fikra = Fikra(num=int(fm["num"]))
                _start_unit(fikra, fm["rest"])
                madde.fikralar.append(fikra)
            elif rest:
                _append(madde, rest)
            continue

        # 4) Bölüm / kısım başlıkları
        bm = BOLUM_RE.match(line)
        if bm:
            section = line
            expect_section_title = True
            madde = fikra = bent = altbent = None
            continue
        if expect_section_title:
            section = f"{section} – {line}"
            expect_section_title = False
            continue

        if madde is not None:
            madde.raw_text += "\n" + line

        # 5) Fıkra / bent / alt bent
        fm = FIKRA_RE.match(line)
        if fm and madde is not None:
            fikra = Fikra(num=int(fm["num"]))
            # "(7) (5) Metin": fıkra numarasından sonra gelen numara dipnottur.
            _start_unit(fikra, fm["rest"])
            madde.fikralar.append(fikra)
            bent = altbent = None
            continue
        bm2 = BENT_RE.match(line)
        if bm2 and madde is not None:
            if fikra is None:  # fıkrasız maddede bent: örtük fıkra oluştur
                fikra = Fikra(num=1)
                madde.fikralar.append(fikra)
            bent = Bent(letter=bm2["letter"])
            _start_unit(bent, bm2["rest"])
            fikra.bentler.append(bent)
            altbent = None
            continue
        am = ALTBENT_RE.match(line)
        if am and bent is not None:
            altbent = AltBent(num=int(am["num"]))
            _append(altbent, am["rest"])
            bent.alt_bentler.append(altbent)
            continue

        # 6) Madde başlığı: sonraki dolu satır bir MADDE satırıysa bu kısa satır başlıktır.
        #    Uzunluk, değişiklik notları çıkarıldıktan SONRA ölçülür.
        clean_title, title_anns = _split_annotations(line)
        nxt = _next_nonblank(lines, i)
        if (len(clean_title) <= 80 and not clean_title.endswith((".", ",", ";", ":"))
                and nxt and MADDE_RE.match(nxt)):
            pending_title = (clean_title, title_anns)
            if madde is not None:  # başlık satırını önceki maddenin ham metninden çıkar
                madde.raw_text = madde.raw_text.rsplit("\n", 1)[0]
            continue

        # 7) Devam satırı: en derindeki açık birime eklenir.
        target = altbent or bent or fikra or madde
        if target is not None:
            _append(target, line)

    return doc
