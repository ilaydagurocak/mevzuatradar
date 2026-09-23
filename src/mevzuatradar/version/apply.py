"""Değişiklikleri düzenlemenin metnine uygular ve sürümler üretir.

Neden: elimizde yalnızca güncel (konsolide) metin var. İlk metinden başlayıp değişiklikleri tarih
sırasıyla uygulayarak her tarihteki metni üretebiliriz. Bu üç şeyi sağlar:
  1) "sonradan değişti" kayıtları kendi zamanlarındaki metinle doğrulanabilir,
  2) "bu madde 2019'da nasıldı?" sorusu cevaplanabilir,
  3) sonuç resmi konsolide metinle karşılaştırılarak sistemin kendisi denetlenebilir.

Yaklaşım: yapı ağacını yeniden kurup metne çevirmek yerine METİN ÜZERİNDE satır bazlı çalışılır;
böylece resmi metnin biçimi (başlıklar, boşluklar) korunur ve karşılaştırma anlamlı olur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from mevzuatradar.parse.structure import BENT_RE, BOLUM_RE, FIKRA_RE, MADDE_RE

KIND = {"gecici": ("GEÇİCİ", "Geçici"), "ek": ("EK", "Ek")}


@dataclass
class ApplyResult:
    status: str           # uygulandi | hedef_bulunamadi | metin_bulunamadi | desteklenmiyor
    detail: str = ""


def _madde_span(lines: list[str], madde: str, madde_type: str = "normal") -> tuple[int, int] | None:
    """Maddenin satır aralığı [başlangıç, bitiş). Başlangıç MADDE satırıdır."""
    bekleyen = KIND.get(madde_type)
    baslangic = None
    for i, line in enumerate(lines):
        m = MADDE_RE.match(line.strip())
        if not m:
            continue
        if baslangic is not None:               # bir sonraki madde: bitiş
            return baslangic, i
        tur_uyumlu = (m["kind"] in bekleyen) if bekleyen else (m["kind"] is None)
        if tur_uyumlu and m["num"] == madde:
            baslangic = i
    return (baslangic, len(lines)) if baslangic is not None else None


def _fikra_span(lines: list[str], span: tuple[int, int], fikra: int) -> tuple[int, int] | None:
    """Fıkranın satır aralığı. Birinci fıkra MADDE satırının devamında olabilir."""
    bas, son = span
    sinirlar = []
    ilk = MADDE_RE.match(lines[bas].strip())
    if ilk and FIKRA_RE.match(ilk["rest"].strip()):
        sinirlar.append((int(FIKRA_RE.match(ilk["rest"].strip())["num"]), bas))
    for i in range(bas + 1, son):
        m = FIKRA_RE.match(lines[i].strip())
        if m:
            sinirlar.append((int(m["num"]), i))
    for k, (num, i) in enumerate(sinirlar):
        if num == fikra:
            return i, (sinirlar[k + 1][1] if k + 1 < len(sinirlar) else son)
    return None


def _bent_span(lines: list[str], span: tuple[int, int], bent: str) -> tuple[int, int] | None:
    bas, son = span
    sinirlar = [(m["letter"], i) for i in range(bas, son) if (m := BENT_RE.match(lines[i].strip()))]
    for k, (letter, i) in enumerate(sinirlar):
        if letter == bent:
            return i, (sinirlar[k + 1][1] if k + 1 < len(sinirlar) else son)
    return None


def _icerik_sonu(lines: list[str], bas: int, son: int) -> int:
    """Maddenin içeriğinin gerçekten bittiği satır.

    Madde bloğunun sonunda bir sonraki maddeye ait başlıklar olabilir: boş satırlar,
    "DÖRDÜNCÜ BÖLÜM" gibi bölüm başlıkları ve madde başlığı. Maddeye fıkra/bent eklerken
    bunların ÖNÜNE eklenmelidir, yoksa yeni metin sonraki bölümün içinde kalır.
    """
    while son - 1 > bas:
        t = lines[son - 1].strip()
        if not t or BOLUM_RE.match(t) or (len(t) < 120 and not t.endswith((".", ":", ",", ";"))):
            son -= 1
            continue
        break
    return son


def _scope(lines: list[str], loc: dict, strict: bool = False) -> tuple[tuple[int, int] | None, str]:
    """Kaydın hedeflediği en dar satır aralığı ve bulunamadıysa sebebi.

    strict=True (metni değiştiren/silen işlemler): istenen fıkra/bent yoksa üst kapsama DÜŞÜLMEZ.
    Aksi halde 'sekizinci fıkrayı kaldır' isteği maddenin tamamını siler.
    strict=False (ibare işlemleri): metin arandığı için üst kapsamda aramak zararsızdır.
    """
    if not loc.get("madde"):
        return None, "hedef madde yok"
    span = _madde_span(lines, str(loc["madde"]), loc.get("madde_type") or "normal")
    if span is None:
        return None, f"madde {loc['madde']} bulunamadı"
    if loc.get("fikra") is not None:
        alt = _fikra_span(lines, span, int(loc["fikra"]))
        if alt is None and strict:
            return None, f"madde {loc['madde']} içinde {loc['fikra']}. fıkra yok"
        span = alt or span
    if loc.get("bent"):
        alt = _bent_span(lines, span, str(loc["bent"]))
        if alt is None and strict:
            return None, f"({loc['bent']}) bendi yok"
        span = alt or span
    return span, ""


def _baslik_satiri(lines: list[str], madde_bas: int) -> int | None:
    """Madde başlığı, MADDE satırından hemen önceki kısa metin satırıdır."""
    for i in range(madde_bas - 1, max(-1, madde_bas - 4), -1):
        t = lines[i].strip()
        if not t:
            continue
        if MADDE_RE.match(t) or FIKRA_RE.match(t) or BENT_RE.match(t) or len(t) > 120:
            return None
        return i
    return None


def _madde_onek(satir: str) -> str:
    """'MADDE 5 – ' kısmı: fıkra/madde metni değişirken numara ve tire korunmalı."""
    m = MADDE_RE.match(satir.strip())
    if not m:
        return ""
    return satir[:satir.index(m["rest"])] if m["rest"] else satir.rstrip() + " "


def _fikra_bloklari(yeni: str) -> list[tuple[int, str]]:
    """Yeni metni '(n)' işaretlerine göre fıkra bloklarına ayırır."""
    satirlar = yeni.split("\n")
    bloklar, mevcut = [], None
    for satir in satirlar:
        m = FIKRA_RE.match(satir.strip())
        if m:
            mevcut = [int(m["num"]), satir]
            bloklar.append(mevcut)
        elif mevcut is not None:
            mevcut[1] += "\n" + satir
    return [(n, t) for n, t in bloklar]


def _cumleler(blok: str) -> list[str]:
    """Fıkra metnini cümlelere böler (nokta veya iki nokta üst üste + boşluk)."""
    return [c for c in re.split(r"(?<=[.:])\s+", blok.strip()) if c]


def _strip_marker(text: str) -> str:
    """Yeni metnin başındaki fıkra/bent işaretini korur ama karşılaştırmada gerekmez."""
    return text.strip()


def apply_record(text: str, rec: dict) -> tuple[str, ApplyResult]:
    """Tek bir değişiklik kaydını metne uygular. Metin değişmediyse sebebi ApplyResult'ta döner."""
    op, unit = rec.get("operation"), rec.get("unit")
    loc = rec.get("location") or {}
    lines = text.split("\n")
    yikici = op in ("BIRIM_DEGISTIR", "BIRIM_KALDIR")
    span, sebep = _scope(lines, loc, strict=yikici)

    if op in ("IBARE_DEGISTIR", "IBARE_EKLE", "IBARE_KALDIR"):
        if span is None:
            return text, ApplyResult("hedef_bulunamadi", sebep)
        bas, son = span
        blok = "\n".join(lines[bas:son])
        if op == "IBARE_DEGISTIR":
            eski, yeni = rec.get("old_text") or "", rec.get("new_text") or ""
            if eski not in blok:
                return text, ApplyResult("metin_bulunamadi", f"'{eski[:40]}' hedefte yok")
            blok = blok.replace(eski, yeni)
        elif op == "IBARE_KALDIR":
            eski = rec.get("old_text") or ""
            if eski not in blok:
                return text, ApplyResult("metin_bulunamadi", f"'{eski[:40]}' hedefte yok")
            blok = re.sub(r"\s{2,}", " ", blok.replace(eski, ""))
        else:  # IBARE_EKLE
            capa, yeni = rec.get("anchor_text") or "", rec.get("new_text") or ""
            if capa and capa not in blok:
                return text, ApplyResult("metin_bulunamadi", f"çapa '{capa[:40]}' hedefte yok")
            if not capa:
                return text, ApplyResult("desteklenmiyor", "çapasız ibare ekleme")
            yerine = f"{capa} {yeni}" if rec.get("anchor_position") != "once" else f"{yeni} {capa}"
            blok = blok.replace(capa, yerine, 1)
        return "\n".join(lines[:bas] + blok.split("\n") + lines[son:]), ApplyResult("uygulandi")

    if op == "BIRIM_DEGISTIR":
        if span is None:
            return text, ApplyResult("hedef_bulunamadi", sebep)
        yeni = _strip_marker(rec.get("new_text") or "")
        if not yeni:
            return text, ApplyResult("desteklenmiyor", "yeni metin yok")
        if unit == "cumle":
            if not str(loc.get("cumle") or "").isdigit():
                return text, ApplyResult("desteklenmiyor", f"cümle konumu: {loc.get('cumle')}")
            bas, son = span
            blok = "\n".join(lines[bas:son])
            cumleler = _cumleler(blok)
            k = int(loc["cumle"]) - 1
            if k >= len(cumleler):
                return text, ApplyResult("hedef_bulunamadi", f"{loc['cumle']}. cümle yok ({len(cumleler)} cümle)")
            onek = _madde_onek(lines[bas]) if MADDE_RE.match(lines[bas].strip()) else ""
            if onek:
                cumleler[0] = cumleler[0][len(onek.strip()):].strip() if cumleler[0].startswith(onek.strip()) \
                    else cumleler[0]
            cumleler[k] = yeni
            return "\n".join(lines[:bas] + (onek + " ".join(cumleler)).split("\n") + lines[son:]), \
                ApplyResult("uygulandi")
        bas, son = span
        if unit == "baslik":
            b = _baslik_satiri(lines, bas)
            if MADDE_RE.match(yeni.split("\n")[0].strip()) or any(
                    MADDE_RE.match(l.strip()) for l in yeni.split("\n")):
                # Yeni metin kendi MADDE satırını içeriyor: başlıktan itibaren tümü değişir
                return "\n".join(lines[:b if b is not None else bas] + yeni.split("\n") + lines[son:]), \
                    ApplyResult("uygulandi")
            # Yeni metin: ilk satır başlık, varsa "(n)" blokları ilgili fıkraların yerine geçer
            satirlar, bloklar = yeni.split("\n"), _fikra_bloklari(yeni)
            yeni_baslik = satirlar[0].strip()
            metin = "\n".join(lines[:b] + [yeni_baslik] + lines[b + 1:]) if b is not None else text
            for numara, blok in bloklar:
                metin, alt = apply_record(metin, {**rec, "unit": "fikra", "new_text": blok,
                                                  "location": {**loc, "fikra": numara}})
                if alt.status == "hedef_bulunamadi":
                    # O numarada fıkra henüz yoksa blok bir EKLEMEdir ("... aynı maddeye
                    # aşağıdaki fıkra eklenmiştir" ifadesi başlık değişikliğiyle aynı cümlede geçebilir)
                    metin, alt = apply_record(metin, {**rec, "operation": "BIRIM_EKLE", "unit": "fikra",
                                                      "new_text": blok,
                                                      "location": {k: v for k, v in loc.items() if k != "fikra"}})
                if alt.status != "uygulandi":
                    return metin, ApplyResult(alt.status, f"fıkra {numara}: {alt.detail}")
            return metin, ApplyResult("uygulandi")
        if unit == "bent" and son - bas > 1 and not yeni.rstrip().endswith((".", ":")):
            # Bentlerden sonra gelen kapanış cümlesi ("... zorunludur.") fıkraya aittir, bende değil;
            # bent değiştirilirken silinmemeli.
            while son - 1 > bas and lines[son - 1].strip().endswith((".", ":")) \
                    and not BENT_RE.match(lines[son - 1].strip()):
                son -= 1
        if MADDE_RE.match(yeni.split("\n")[0].strip()):
            yeni_satirlar = yeni.split("\n")          # yeni metin kendi MADDE satırını getiriyor
        elif unit == "madde" or MADDE_RE.match(lines[bas].strip()):
            # Madde değişiyorsa ya da birinci fıkra MADDE satırının devamındaysa numara korunur
            yeni_satirlar = (_madde_onek(lines[bas]) + yeni).split("\n")
        else:
            yeni_satirlar = yeni.split("\n")
        return "\n".join(lines[:bas] + yeni_satirlar + lines[son:]), ApplyResult("uygulandi")

    if op == "BIRIM_EKLE":
        yeni = _strip_marker(rec.get("new_text") or "")
        if not yeni:
            return text, ApplyResult("desteklenmiyor", "yeni metin yok")
        if unit in ("madde", "gecici_madde", "ek_madde") and not loc.get("madde"):
            return text + "\n" + yeni, ApplyResult("uygulandi")     # yönetmeliğin sonuna
        if span is None:
            # "28/A maddesi eklenmiştir": henüz yok, 28. maddeden sonraya gelir
            kok = str(loc.get("madde") or "").split("/")[0]
            onceki = _madde_span(lines, kok, loc.get("madde_type") or "normal") if kok else None
            if onceki is None:
                return text, ApplyResult("hedef_bulunamadi", sebep)
            return "\n".join(lines[:onceki[1]] + yeni.split("\n") + lines[onceki[1]:]), ApplyResult("uygulandi")
        bas, son = span
        # Aynı numarada fıkra zaten varsa bu bir EKLEME değil, o fıkranın DEĞİŞTİRİLMESİdir:
        # bir maddede aynı numaralı iki fıkra olamaz.
        if unit == "fikra" and (bloklar := _fikra_bloklari(yeni)):
            kalan, metin = [], text
            for numara, blok in bloklar:
                if _fikra_span(metin.split("\n"), _madde_span(metin.split("\n"), str(loc["madde"]),
                                                               loc.get("madde_type") or "normal"), numara):
                    metin, alt = apply_record(metin, {**rec, "operation": "BIRIM_DEGISTIR", "new_text": blok,
                                                      "location": {**loc, "fikra": numara}})
                    if alt.status != "uygulandi":
                        return metin, ApplyResult(alt.status, f"fıkra {numara}: {alt.detail}")
                else:
                    kalan.append(blok)
            if not kalan:
                return metin, ApplyResult("uygulandi")
            if metin != text:                      # bir kısmı değiştirildi, kalanlar eklenecek
                return apply_record(metin, {**rec, "new_text": "\n".join(kalan)})
        son = _icerik_sonu(lines, bas, son)
        if (sonra := rec.get("insert_after")):                       # "(d) bendinden sonra gelmek üzere"
            alt = _bent_span(lines, (bas, son), str(sonra)) or _fikra_span(lines, (bas, son), int(sonra)) \
                if str(sonra).isdigit() else _bent_span(lines, (bas, son), str(sonra))
            if alt:
                son = alt[1]
        return "\n".join(lines[:son] + yeni.split("\n") + lines[son:]), ApplyResult("uygulandi")

    if op == "BASLIK_DEGISTIR":
        if span is None:
            return text, ApplyResult("hedef_bulunamadi", sebep)
        yeni = _strip_marker(rec.get("new_text") or "")
        b = _baslik_satiri(lines, span[0])
        if b is None:      # başlık satırı yoksa MADDE satırının önüne eklenir
            return "\n".join(lines[:span[0]] + [yeni] + lines[span[0]:]), ApplyResult("uygulandi")
        return "\n".join(lines[:b] + [yeni] + lines[b + 1:]), ApplyResult("uygulandi")

    if op in ("EK_EKLE", "EK_DEGISTIR"):
        return text, ApplyResult("desteklenmiyor", "ekler (form/tablo) düzenleme metninde yer almıyor")

    if op == "BIRIM_KALDIR":
        if span is None:
            return text, ApplyResult("hedef_bulunamadi", sebep)
        bas, son = span
        return "\n".join(lines[:bas] + lines[son:]), ApplyResult("uygulandi")

    return text, ApplyResult("desteklenmiyor", f"{op} için uygulama yok")


def apply_records(text: str, records: list[dict]) -> tuple[str, list[ApplyResult]]:
    """Bir değişiklik yönetmeliğinin kayıtlarını sırayla uygular."""
    sonuclar = []
    for rec in records:
        text, res = apply_record(text, rec)
        sonuclar.append(res)
    return text, sonuclar
