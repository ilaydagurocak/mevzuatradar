"""'bizde_yok' maddelerin masum sebepleri: mülga mezar taşı ve kaynak tutarsızlığı."""
import textwrap

from mevzuatradar.version.build import (
    bilinen_kaldirma_tutarsizligi_mi,
    bizde_yok_nedeni,
    mulga_mezari_mi,
)


def test_mezar_tasi_taninir():
    assert mulga_mezari_mi("MADDE 15 – (Mülga:RG-1/8/2019-30849)")


def test_gecici_ve_ek_madde_mezar_taslari_da_taninir():
    assert mulga_mezari_mi("GEÇİCİ MADDE 3 – (Mülga:RG-1/1/2020-31000)")
    assert mulga_mezari_mi("EK MADDE 1 – (Mülga:RG-1/1/2020-31000)")


def test_harfli_madde_ve_kisa_cizgi_bicimi():
    assert mulga_mezari_mi("MADDE 12/A- (Mülga:RG-1/1/2020-31000)")


def test_satir_sonlari_ve_fazla_bosluk_sorun_degil():
    assert mulga_mezari_mi("MADDE 15 –\n   (Mülga:RG-1/8/2019-30849)\n")


def test_icerigi_olan_madde_mezar_tasi_degildir():
    assert not mulga_mezari_mi(
        "MADDE 15 – (Mülga üçüncü fıkra:RG-1/8/2019-30849) (1) Kuruluşlar bildirim yapar.")
    assert not mulga_mezari_mi("MADDE 15 – (1) Kuruluşlar bildirim yapar.")


def test_bilinen_tutarsizlik_yapilandirmadan_okunur(tmp_path):
    yol = tmp_path / "known.yaml"
    yol.write_text(textwrap.dedent("""
        issues:
          - id: kredi-gecici2-mulga-islenmemis
            source: bddk_kredi_siniflandirma
            operation: BIRIM_KALDIR
            location: {madde_type: gecici, madde: "2"}
          - id: baska-bir-sey
            source: bddk_muhasebe
            operation: BIRIM_DEGISTIR
            location: {madde: "5"}
    """), encoding="utf-8")
    assert bilinen_kaldirma_tutarsizligi_mi("bddk_kredi_siniflandirma", "gecici:2", str(yol))
    # Farklı kaynak, farklı madde ve kaldırma olmayan işlem sayılmaz.
    assert not bilinen_kaldirma_tutarsizligi_mi("bddk_fk_muhasebe", "gecici:2", str(yol))
    assert not bilinen_kaldirma_tutarsizligi_mi("bddk_kredi_siniflandirma", "gecici:3", str(yol))
    assert not bilinen_kaldirma_tutarsizligi_mi("bddk_muhasebe", "5", str(yol))


def test_yapilandirma_yoksa_sessizce_false():
    assert not bilinen_kaldirma_tutarsizligi_mi("x", "1", "olmayan/dosya.yaml")


def test_neden_etiketi_sirasi():
    assert bizde_yok_nedeni("herhangi", "15", "MADDE 15 – (Mülga:RG-1/8/2019-30849)") == "mulga_mezari"
    assert bizde_yok_nedeni("herhangi", "9", "MADDE 9 – (1) Gerçek içerik.") == "bizde_yok"


def test_gercek_yapilandirmada_kredi_gecici2_kayitli():
    """configs/known_source_issues.yaml'daki girdi gerçekten eşleşiyor mu?"""
    import os

    if not os.path.exists("configs/known_source_issues.yaml"):
        return
    assert bilinen_kaldirma_tutarsizligi_mi("bddk_kredi_siniflandirma", "gecici:2")
