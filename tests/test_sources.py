import yaml

from mevzuatradar.collect.sources import add_source, to_iframe_url


def test_sayfa_adresi_iframe_adresine_cevrilir():
    assert to_iframe_url("https://mevzuat.gov.tr/mevzuat?MevzuatNo=34360&MevzuatTur=7&MevzuatTertip=5") == \
        "https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?MevzuatTur=7&MevzuatNo=34360&MevzuatTertip=5"
    iframe = "https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?MevzuatTur=7&MevzuatNo=1&MevzuatTertip=5"
    assert to_iframe_url(iframe) == iframe


def test_kaynak_ve_bolme_eklenir_mevcutlar_korunur(tmp_path):
    cfg, spl = tmp_path / "s.yaml", tmp_path / "sp.yaml"
    cfg.write_text(yaml.safe_dump({"sources": [{"id": "eski", "url": "u", "amendments": ["a", "b"]}],
                                   "crawl": {"delay_seconds": 3}}), encoding="utf-8")
    spl.write_text(yaml.safe_dump({"train": ["eski"], "dev": [], "test": []}), encoding="utf-8")
    add_source("yeni", "Yeni Yönetmelik", "BDDK",
               "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=99&MevzuatTur=7&MevzuatTertip=5", "test", str(cfg), str(spl))
    c = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert c["sources"][0]["amendments"] == ["a", "b"] and c["crawl"]["delay_seconds"] == 3
    assert c["sources"][1]["url"].endswith("MevzuatNo=99&MevzuatTertip=5")
    sp = yaml.safe_load(spl.read_text(encoding="utf-8"))
    assert sp["train"] == ["eski"] and sp["test"] == ["yeni"]
    add_source("yeni", "Yeni Yönetmelik", "BDDK", c["sources"][1]["url"], "train", str(cfg), str(spl))
    sp = yaml.safe_load(spl.read_text(encoding="utf-8"))
    assert sp["test"] == [] and sp["train"] == ["eski", "yeni"]  # bir kaynak tek bölmede
