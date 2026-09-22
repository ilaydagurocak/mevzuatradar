from mevzuatradar.collect.rg_finder import collect_refs, find_links, keyword_from_name, parse_ref, tr_upper


def test_referans_ayrisma_ve_url():
    r = parse_ref("RG-25/9/2020-31255")
    assert (r.year, r.month, r.day, r.sayi, r.mukerrer) == (2020, 9, 25, "31255", 0)
    assert r.index_url == "https://www.resmigazete.gov.tr/eskiler/2020/09/20200925.htm"
    m = parse_ref("RG-8/10/2013-28789 Mükerrer")
    assert m.mukerrer == 1 and m.index_url.endswith("/2013/10/20131008M1.htm")
    assert parse_ref("RG-24/2/2021-31405 2. Mükerrer").mukerrer == 2


def test_oneksiz_ve_tekrarlanan_referanslar_birlesir():
    refs = collect_refs(["RG-17/12/2010-27788", "17/12/2010-27788", "RG-1/8/2009-27306"])
    assert [r.label for r in refs] == ["RG-1/8/2009-27306", "RG-17/12/2010-27788"]


def test_turkce_buyuk_harf():
    assert tr_upper("Kredi Kartları Hakkında") == "KREDİ KARTLARI HAKKINDA"


def test_icindekiler_sayfasinda_baglanti_bulma():
    html = """<html><body>
    <a href="20200925-3.htm">––  Hayvan Hastalıklarında Tazminat Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik</a>
    <a href="20200925-5.htm">––  Banka Kartları ve Kredi Kartları Hakkında Yönetmelikte
        Değişiklik Yapılmasına Dair Yönetmelik</a>
    <a href="20200925-6.htm">––  Banka Kartları ve Kredi Kartları Hakkında Yönetmelik Uygulama Rehberi</a>
    </body></html>"""
    kw = keyword_from_name("Banka Kartları ve Kredi Kartları Hakkında Yönetmelik")
    assert kw == "Banka Kartları ve Kredi Kartları Hakkında"
    links = find_links(html, "https://www.resmigazete.gov.tr/eskiler/2020/09/20200925.htm", kw)
    assert [u for _, u in links] == ["https://www.resmigazete.gov.tr/eskiler/2020/09/20200925-5.htm"]
