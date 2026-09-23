import json

from mevzuatradar.collect.rg_finder import RGRef
from mevzuatradar.collect.watch import Hit, load_state, save_state, scan_day, write_report

ICINDEKILER = """<html><body>
 <div>T.C. Resmî Gazete 23 Eylül 2026 Tarihli ve 33000 Sayılı Resmî Gazete</div>
 <a href="20260923-1.htm">Banka Kartları ve Kredi Kartları Hakkında Yönetmelikte Değişiklik Yapılmasına Dair Yönetmelik</a>
 <a href="20260923-2.htm">Başka Bir Yönetmelikte Değişiklik Yapılmasına Dair Yönetmelik</a>
 <a href="20260923-3.htm">Banka Kartları ve Kredi Kartları Hakkında Yönetmelik</a>
</body></html>"""

DEGISIKLIK = """<html><body><p>BANKA KARTLARI VE KREDİ KARTLARI HAKKINDA YÖNETMELİKTE DEĞİŞİKLİK</p>
<p>MADDE 1 – 10/3/2007 tarihli ve 26458 sayılı Resmî Gazete’de yayımlanan Banka Kartları ve Kredi
Kartları Hakkında Yönetmeliğin 3 üncü maddesinin birinci fıkrasında yer alan “Kurum” ibaresi
“Kurul” şeklinde değiştirilmiştir.</p>
<p>MADDE 2 – Bu Yönetmelik yayımı tarihinde yürürlüğe girer.</p></body></html>"""

KONSOLIDE = "BANKA KARTLARI\nTanımlar\nMADDE 3 – (1) Bu Yönetmelikte geçen Kurul: Bankacılık Kurulunu,\n"

KAYNAKLAR = [{"id": "bddk_kart", "name": "Banka Kartları ve Kredi Kartları Hakkında Yönetmelik"},
             {"id": "bddk_diger", "name": "Hiç Geçmeyen Bir Yönetmelik"}]


class SahteYanit:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.content = text, status, text.encode("utf-8")
        self.encoding, self.apparent_encoding = "utf-8", "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class SahteSession:
    def __init__(self, sayfalar):
        self.sayfalar, self.istekler = sayfalar, []

    def get(self, url, timeout=None):
        self.istekler.append(url)
        return SahteYanit(*self.sayfalar.get(url, ("", 404)))


def _raw(tmp_path):
    d = tmp_path / "bddk_kart"
    d.mkdir(parents=True)
    (d / "konsolide_x.txt").write_text(KONSOLIDE, encoding="utf-8")
    return str(tmp_path)


def test_takip_edilen_yonetmelikteki_degisiklik_bulunur_ve_dogrulanir(tmp_path):
    ref = RGRef(2026, 9, 23, sayi="?")
    session = SahteSession({ref.index_url: (ICINDEKILER, 200),
                            "https://www.resmigazete.gov.tr/eskiler/2026/09/20260923-1.htm": (DEGISIKLIK, 200)})
    hits, hata = scan_day(session, ref, KAYNAKLAR, _raw(tmp_path))
    assert hata is None and len(hits) == 1                  # yalnızca takip edilen ve "değişiklik" olan
    h = hits[0]
    assert h.source_id == "bddk_kart" and h.record_count == 1
    assert h.rg_label == "RG-23/9/2026-33000"          # sayı numarası sayfadan okundu
    assert h.statuses == {"uyumlu": 1}                      # güncel metne göre doğrulandı
    assert h.records[0]["new_text"] == "Kurul"


def test_sayi_yayimlanmayan_gun_sessizce_gecilir(tmp_path):
    ref = RGRef(2026, 9, 21, sayi="?")                      # pazar
    hits, hata = scan_day(SahteSession({}), ref, KAYNAKLAR, _raw(tmp_path))
    assert hits == [] and hata is None


def test_durum_dosyasi_tekrar_bildirimi_onler(tmp_path):
    yol = str(tmp_path / "state.json")
    assert load_state(yol) == set()
    save_state(yol, {"https://a", "https://b"})
    assert load_state(yol) == {"https://a", "https://b"}


def test_rapor_jsonl_olarak_eklenir(tmp_path):
    yol = str(tmp_path / "rapor.jsonl")
    write_report(yol, [Hit("x", "X Yönetmeliği", "RG-23/9/2026-33000", "https://u", "başlık", 2, {"uyumlu": 2})])
    satir = json.loads(open(yol, encoding="utf-8").readline())
    assert satir["source_id"] == "x" and satir["statuses"] == {"uyumlu": 2}


def test_sayi_numarasi_sayfadan_okunur():
    from mevzuatradar.collect.watch import sayi_from_page
    # Gerçek sayfa biçimi
    gercek = ("<html><body><p>T.C. Resmî Gazete</p><p>27 Ağustos 2025 Tarihli ve 32999 Sayılı Resmî Gazete</p>"
              "<a>Kredi Garanti Kurumlarına Sağlanan Hazine Desteğine İlişkin Kararda Değişiklik Yapılmasına "
              "Dair Karar (Karar Sayısı: 10258)</a></body></html>")
    assert sayi_from_page(gercek) == "32999"        # "Karar Sayısı: 10258" tuzağına düşmemeli
    assert sayi_from_page("<div>başlıksız sayfa</div>") is None
