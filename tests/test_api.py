import pytest

pytest.importorskip("fastapi")

# Starlette sürümüne göre test istemcisi httpx ya da httpx2 ister; yoksa API testleri atlanır
# (servis kodu bundan etkilenmez, yalnızca test istemcisi gerektirir).
try:
    from fastapi.testclient import TestClient
except RuntimeError as exc:  # pragma: no cover
    pytest.skip(f"test istemcisi kullanılamıyor: {exc}", allow_module_level=True)

from mevzuatradar.api.main import app  # noqa: E402

client = TestClient(app)

DEGISIKLIK = ("MADDE 1 – 1/1/2020 tarihli ve 1 sayılı Resmî Gazete’de yayımlanan Örnek Yönetmeliğin 3 üncü "
              "maddesinin birinci fıkrasının (a) bendinde yer alan “Kurum” ibaresi “Kurul” şeklinde değiştirilmiştir.")
KONSOLIDE = ("ÖRNEK YÖNETMELİK\nTanımlar\nMADDE 3 – (1) Bu Yönetmelikte geçen;\n"
             "a) Kurul: Bankacılık Düzenleme ve Denetleme Kurulunu,\n")


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_extract():
    r = client.post("/extract", json={"text": DEGISIKLIK})
    assert r.status_code == 200
    d = r.json()
    assert d["count"] == 1
    kayit = d["records"][0]
    assert kayit["operation"] == "IBARE_DEGISTIR"
    assert (kayit["old_text"], kayit["new_text"]) == ("Kurum", "Kurul")
    assert kayit["location"]["madde"] == "3" and kayit["location"]["bent"] == "a"


def test_extract_bos_metin():
    r = client.post("/extract", json={"text": "MADDE 5 – Bu Yönetmelik yayımı tarihinde yürürlüğe girer."})
    assert r.status_code == 200 and r.json() == {"count": 0, "records": []}


def test_verify_konsolide_metinle():
    r = client.post("/verify", json={"text": DEGISIKLIK, "consolidated_text": KONSOLIDE})
    assert r.status_code == 200
    d = r.json()
    assert d["summary"] == {"uyumlu": 1} and d["records"][0]["status"] == "uyumlu"


def test_verify_yanlis_hedef_uyumsuz_isaretlenir():
    bozuk = DEGISIKLIK.replace("3 üncü", "9 uncu")
    d = client.post("/verify", json={"text": bozuk, "consolidated_text": KONSOLIDE}).json()
    assert d["records"][0]["status"] == "hedef_bulunamadi"


def test_eksik_alan_422():
    assert client.post("/extract", json={}).status_code == 422


def test_demo_sayfasi():
    r = client.get("/")
    assert r.status_code == 200 and "MevzuatRadar" in r.text and "/extract" in r.text


def test_version_ucu_gecersiz_tarih():
    r = client.get("/version", params={"source": "x", "date": "2019-01-01"})
    assert r.status_code == 422 and "gg/aa/yyyy" in r.json()["detail"]


def test_version_ucu_bilinmeyen_kaynak():
    r = client.get("/version", params={"source": "olmayan_kaynak", "date": "01/01/2019", "raw_dir": "/tmp/yok"})
    assert r.status_code == 404
