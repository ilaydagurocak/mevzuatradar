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


def test_eski_adla_yayimlanan_degisiklik_de_bulunur():
    html = """<a href="20190101-3.htm">Finansal Kiralama, Faktoring ve Finansman Şirketlerinin Muhasebe Uygulamaları
    İle Finansal Tabloları Hakkında Yönetmelikte Değişiklik Yapılmasına Dair Yönetmelik</a>"""
    guncel = keyword_from_name("Finansal Kiralama, Faktoring, Finansman ve Tasarruf Finansman Şirketlerinin Muhasebe "
                               "Uygulamaları ile Finansal Tabloları Hakkında Yönetmelik")
    eski = keyword_from_name("Finansal Kiralama, Faktoring ve Finansman Şirketlerinin Muhasebe Uygulamaları İle "
                             "Finansal Tabloları Hakkında Yönetmelik")
    base = "https://www.resmigazete.gov.tr/eskiler/2019/01/20190101.htm"
    assert find_links(html, base, guncel) == []                    # yalnızca güncel adla: kaçar
    assert [u for _, u in find_links(html, base, [guncel, eski])] == [
        "https://www.resmigazete.gov.tr/eskiler/2019/01/20190101-3.htm"]


def test_orijinal_yayim_referansi_dogru_atiftan_alinir():
    from mevzuatradar.collect.rg_finder import original_ref
    # Metinde iki atıf var: önce dayanak kanun, sonra değiştirilen yönetmelik
    metin = ("MADDE 1 – 5/11/2013 tarihli ve 28812 sayılı Resmî Gazete’de yayımlanan Bankacılık Kanununa dayanılarak, "
             "11/7/2014 tarihli ve 29057 sayılı Resmî Gazete’de yayımlanan Bankaların İç Sistemleri ve İçsel Sermaye "
             "Yeterliliği Değerlendirme Süreci Hakkında Yönetmeliğin 5 inci maddesi değiştirilmiştir.")
    ref = original_ref(metin, "Bankaların İç Sistemleri ve İçsel Sermaye Yeterliliği Değerlendirme Süreci Hakkında Yönetmelik")
    assert ref.label == "RG-11/7/2014-29057"
    assert ref.index_url == "https://www.resmigazete.gov.tr/eskiler/2014/07/20140711.htm"


def test_orijinal_baglanti_degisiklikleri_elemeli():
    from mevzuatradar.collect.rg_finder import find_original_link
    html = """<a href="20070310-3.htm">Banka Kartları ve Kredi Kartları Hakkında Yönetmelik</a>
              <a href="20070310-4.htm">Banka Kartları ve Kredi Kartları Hakkında Yönetmelikte Değişiklik Yapılmasına Dair Yönetmelik</a>
              <a href="20070310-5.htm">Başka Bir Yönetmelik</a>"""
    base = "https://www.resmigazete.gov.tr/eskiler/2007/03/20070310.htm"
    hits = find_original_link(html, base, keyword_from_name("Banka Kartları ve Kredi Kartları Hakkında Yönetmelik"))
    assert [u for _, u in hits] == ["https://www.resmigazete.gov.tr/eskiler/2007/03/20070310-3.htm"]
