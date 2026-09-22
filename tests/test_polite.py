import requests

from mevzuatradar.collect.polite import RobotsChecker, get_with_retry

UA = "MevzuatRadar/0.1 (egitim amacli portfoy projesi)"


class FakeResp:
    def __init__(self, status=200, text=""):
        self.status_code, self.text = status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    """Adres -> yanıt (veya fırlatılacak istisna) listesi; her çağrıda sıradakini döndürür."""
    def __init__(self, routes):
        self.routes, self.calls = {k: list(v) for k, v in routes.items()}, []

    def get(self, url, timeout=None):
        self.calls.append(url)
        item = self.routes[url].pop(0) if len(self.routes[url]) > 1 else self.routes[url][0]
        if isinstance(item, Exception):
            raise item
        return item


# Sitelerin 20/9/2026'da yayınladığı robots.txt'lerin kısaltılmış halleri
MEVZUAT_ROBOTS = "User-agent: Googlebot\nNoindex:/MevzuatMetin/3.5.20059986.pdf\nNoindex:/MevzuatMetin/1.5.7354.pdf\n"
RG_ROBOTS = ("User-agent: Googlebot\nNoindex:/arsiv/17961.pdf\n\nUser-agent: Bingbot\n"
             "Noindex: /eskiler/2023/11/20231103-11.pdf\n")


def test_gercek_robots_dosyalari_bizim_kullanimimizi_kisitlamaz():
    s = FakeSession({"https://www.mevzuat.gov.tr/robots.txt": [FakeResp(200, MEVZUAT_ROBOTS)],
                     "https://www.resmigazete.gov.tr/robots.txt": [FakeResp(200, RG_ROBOTS)]})
    rc = RobotsChecker(s, UA)
    assert rc.allowed("https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?MevzuatTur=7&MevzuatNo=11180&MevzuatTertip=5")
    assert rc.allowed("https://www.resmigazete.gov.tr/eskiler/2020/09/20200925-12.htm")
    rc.allowed("https://www.mevzuat.gov.tr/baska")  # aynı site: robots.txt yeniden istenmez
    assert s.calls.count("https://www.mevzuat.gov.tr/robots.txt") == 1


def test_disallow_kurali_uygulanir():
    s = FakeSession({"https://ornek.gov.tr/robots.txt": [FakeResp(200, "User-agent: *\nDisallow: /gizli/\n")]})
    rc = RobotsChecker(s, UA)
    assert not rc.allowed("https://ornek.gov.tr/gizli/belge.htm")
    assert rc.allowed("https://ornek.gov.tr/acik/belge.htm")


def test_rfc9309_durum_kodlari():
    rc = RobotsChecker(FakeSession({"https://a.tr/robots.txt": [FakeResp(404)]}), UA)
    assert rc.allowed("https://a.tr/x")                       # 404: kural yok, serbest
    rc = RobotsChecker(FakeSession({"https://b.tr/robots.txt": [FakeResp(503)]}), UA)
    assert not rc.allowed("https://b.tr/x")                   # 5xx: kısıtlı say
    rc = RobotsChecker(FakeSession({"https://c.tr/robots.txt": [requests.Timeout()]}), UA)
    assert not rc.allowed("https://c.tr/x")                   # ulaşılamıyor: kısıtlı say


def test_zaman_asiminda_yeniden_dener():
    s = FakeSession({"https://a.tr/x": [requests.Timeout(), FakeResp(429), FakeResp(200, "tamam")]})
    assert get_with_retry(s, "https://a.tr/x", retries=2, backoff=0).text == "tamam"
    assert len(s.calls) == 3


def test_manifestteki_adresler_yeniden_istenmez(tmp_path, monkeypatch):
    import json

    import yaml

    from mevzuatradar.collect import downloader

    raw = tmp_path / "raw"; raw.mkdir()
    (raw / "manifest.jsonl").write_text(json.dumps({"url": "https://a.tr/kons"}) + "\n" +
                                        json.dumps({"url": "https://a.tr/deg0"}) + "\n", encoding="utf-8")
    cfg = tmp_path / "s.yaml"
    cfg.write_text(yaml.safe_dump({"sources": [{"id": "x", "url": "https://a.tr/kons",
                                                "amendments": ["https://a.tr/deg0", "https://a.tr/deg1"]}],
                                   "crawl": {"delay_seconds": 0}}), encoding="utf-8")
    istenen = []
    monkeypatch.setattr(downloader.truststore, "inject_into_ssl", lambda: None)
    monkeypatch.setattr(downloader.RobotsChecker, "allowed", lambda self, url: True)
    monkeypatch.setattr(downloader, "download_one", lambda s, url, *a, **k: istenen.append(url))
    downloader.run(str(cfg), str(raw))
    assert istenen == ["https://a.tr/deg1"]                      # yalnızca yeni değişiklik
    istenen.clear()
    downloader.run(str(cfg), str(raw), refresh=True)
    assert istenen == ["https://a.tr/kons", "https://a.tr/deg1"]  # refresh: konsolide de
