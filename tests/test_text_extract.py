from mevzuatradar.extract.amendments import extract_amendments
from mevzuatradar.parse.structure import parse_structure
from mevzuatradar.parse.text_extract import from_html

# mevzuat.gov.tr / Resmî Gazete tarzı: paragraf <span>'lere bölünmüş, kaynakta satır kaydırmalı.
WORD_HTML = """<html><body><div class=WordSection1>
<p class=MsoNormal align=center><b><span>ÖRNEK YÖNETMELİKTE DEĞİŞİKLİK
YAPILMASINA DAİR YÖNETMELİK</span></b></p>
<p class=MsoNormal><b><span>MADDE 1 –</span></b><span> 1/1/2020 tarihli ve 1 sayılı
Resmî Gazete’de yayımlanan Örnek Yönetmeliğin </span><span>4 üncü maddesinin</span>
birinci fıkrasında yer alan “otuz” ibaresi “on beş” şeklinde değiştirilmiştir.</p>
<p class=MsoNormal><span>MADDE 2 –</span><span> Bu Yönetmelik yayımı tarihinde yürürlüğe girer.</span></p>
</div></body></html>"""


def test_span_bolunmus_paragraf_tek_satir_olur():
    text = from_html(WORD_HTML)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    assert lines[0] == "ÖRNEK YÖNETMELİKTE DEĞİŞİKLİK YAPILMASINA DAİR YÖNETMELİK"
    assert lines[1].startswith("MADDE 1 – 1/1/2020 tarihli") and lines[1].endswith("değiştirilmiştir.")


def test_html_uctan_uca_kayit_uretir():
    # Regresyon koruması: HTML çıkarımı bozulursa bu test 0 kayıtla başarısız olur.
    text = from_html(WORD_HTML)
    assert [m.key for m in parse_structure(text).maddeler] == ["1", "2"]
    recs = extract_amendments(text)
    assert [(r.operation, r.location.madde, r.location.fikra) for r in recs] == [("IBARE_DEGISTIR", "4", 1)]


def test_yorumlar_ve_ust_simge_dipnotlari_metne_karismaz():
    html = """<html><body>
    <p>MADDE 3 – Aynı Yönetmeliğin ikinci cümlesi değiştirilmiştir.</p>
    <!--[if gte vml 1]><v:shapetype id="_x0000_t75" coordsize="21600,21600"></v:shapetype><![endif]-->
    <p>MADDE 17 –<sup>1</sup> (1) Teminatlı borçlar şunlardır.</p>
    <p>x<sup>2</sup> formülü korunur.</p>
    </body></html>"""
    text = from_html(html)
    assert "vml" not in text and "shapetype" not in text
    assert "MADDE 17 – (1) Teminatlı borçlar şunlardır." in text
    # Bilinen ödünleşim: mevzuat metinlerinde üst simge rakamlar neredeyse her zaman dipnottur;
    # bu yüzden silinirler. Nadir görülen formül üsleri (x²) de bu sırada kaybolur.
    assert "x formülü korunur." in text
