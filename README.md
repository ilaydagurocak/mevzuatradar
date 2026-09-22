# MevzuatRadar

Bankacılık mevzuatındaki değişiklikleri otomatik olarak takip eden, hangi düzenlemenin
hangi maddesinin nasıl değiştiğini çıkaran ve uyum ekiplerine kaynaklı cevaplar veren
bir document intelligence sistemi.

## Problem

BDDK, TCMB, SPK ve MASAK düzenlemeleri sık değişir ve değişiklik metinleri
("... 5 inci maddesinin ikinci fıkrasında yer alan “X” ibaresi “Y” şeklinde
değiştirilmiştir") tek başına okunduğunda anlamsızdır. Uyum ekipleri her değişikliği
elle ilgili maddeye işleyerek güncel metni takip eder. MevzuatRadar bu süreci otomatikleştirir.

## Yol haritası

| Aşama | Durum |
|---|---|
| 1. Veri toplama hattı (indirme, manifest, tekrar-güvenli) | ✅ iskelet hazır |
| 2. Yapı ayrıştırma (madde / fıkra / bent / alt bent, değişiklik notları) | ✅ v0 |
| 3. Değişiklik çıkarımı: kural tabanlı baseline + değerlendirme | ✅ v0 |
| 3b. NER/RE modeli (BERTurk fine-tune) ve LLM yaklaşımıyla karşılaştırma | ⏳ |
| 4. Değişiklikleri uygulama ve madde versiyonlama (konsolide metinle otomatik doğrulama) | ⏳ |
| 5. Taranmış Resmî Gazete sayıları için layout analizi + VLM | ⏳ |
| 6. Zamana duyarlı RAG uyum asistanı | ⏳ |
| 7. FastAPI + Triton servis, MLflow, CI eval, izleme | ⏳ |

## Kurulum

```bash
pip install -e ".[dev]"
pytest
```

## Kullanım

```bash
# Örnek bir yönetmeliği madde ağacına dönüştür
mevzuatradar parse data/samples/ornek_yonetmelik.txt

# Değişiklik yönetmeliğinden yapılandırılmış kayıtlar çıkar
mevzuatradar extract data/samples/ornek_degisiklik.txt --out preds.jsonl

# Gold etiketlerle karşılaştır
mevzuatradar evaluate --pred preds.jsonl --gold data/samples/ornek_degisiklik.gold.jsonl

# Gerçek veriyi indir (önce configs/sources.yaml içindeki url alanlarını doldurun)
mevzuatradar download
```

## Değişiklik kaydı şeması

```json
{
  "amending_article": "2",
  "target_regulation": "Örnek Bankacılık Hizmetleri Hakkında Yönetmelik",
  "operation": "IBARE_EKLE",
  "location": {"madde_type": "normal", "madde": "5", "fikra": 2, "bent": null, "alt_bent": null},
  "unit": "ibare",
  "anchor_text": "yazılı olarak", "anchor_position": "sonra",
  "new_text": "veya kalıcı veri saklayıcısı aracılığıyla"
}
```

Operasyonlar: `IBARE_DEGISTIR`, `IBARE_EKLE`, `IBARE_KALDIR`, `BIRIM_DEGISTIR`,
`BIRIM_EKLE`, `BIRIM_KALDIR`.

## Baseline sonuçları (örnek set)

| Yöntem | Precision | Recall | F1 |
|---|---|---|---|
| Kural tabanlı baseline | 0.875 | 0.778 | 0.824 |

Bilinen hatalar: birden fazla hedefli değişiklikler ("9 uncu ve 10 uncu maddelerinde"),
göreli referanslar ("bu fıkranın"), cümle düzeyinde değişiklikler. Bunlar model aşamasının
çözmesi gereken problemlerdir.

## Veri notu

`data/samples/` altındaki metinler **kurgusaldır**; gerçek bir düzenlemeyi yansıtmaz,
yalnızca Resmî Gazete'deki değişiklik dilini örneklemek için yazılmıştır.
Gerçek veri toplarken ilgili sitelerin kullanım koşullarına uyun ve istekleri seyrek tutun.
