"""MevzuatRadar HTTP servisi.

Uç noktalar:
  GET  /health   servis durumu
  POST /extract  değişiklik maddesi metni -> yapılandırılmış kayıtlar
  POST /verify   metin + konsolide metin -> kayıtlar + doğrulama sonuçları
  GET  /         tarayıcıdan denemek için küçük demo sayfası
  GET  /docs     FastAPI'nin otomatik ürettiği etkileşimli dokümantasyon

Çıkarım kural tabanlı motorla yapılır: milisaniyeler sürer, GPU gerektirmez.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from mevzuatradar.extract.amendments import extract_amendments
from mevzuatradar.extract.verify import verify
from mevzuatradar.ml.dataset import canonical_record

SURUM = "0.1.0"

app = FastAPI(
    title="MevzuatRadar",
    version=SURUM,
    description="Türk mevzuatındaki değişiklik metinlerini yapılandırılmış kayıtlara çevirir ve "
                "düzenlemenin güncel (konsolide) metniyle doğrular.",
)


class ExtractRequest(BaseModel):
    text: str = Field(..., description="Değişiklik yönetmeliğinin metni (bir veya birden çok madde).",
                      examples=["MADDE 1 – 15/3/2020 tarihli ve 31069 sayılı Resmî Gazete'de yayımlanan Örnek "
                                "Yönetmeliğin 5 inci maddesinin ikinci fıkrasında yer alan “Kurum” ibaresi "
                                "“Kurul” şeklinde değiştirilmiştir."])


class VerifyRequest(ExtractRequest):
    consolidated_text: str = Field(..., description="Düzenlemenin güncel (konsolide) metni.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": SURUM}


@app.post("/extract")
def extract(req: ExtractRequest) -> dict:
    kayitlar = [canonical_record(a.to_dict()) for a in extract_amendments(req.text)]
    return {"count": len(kayitlar), "records": kayitlar}


@app.post("/verify")
def verify_endpoint(req: VerifyRequest) -> dict:
    kayitlar = [a.to_dict() for a in extract_amendments(req.text)]
    sonuclar = verify(kayitlar, req.consolidated_text)
    cikti = [{**canonical_record(rec), "status": res.status, "detail": res.detail} for rec, res in sonuclar]
    ozet: dict[str, int] = {}
    for r in cikti:
        ozet[r["status"]] = ozet.get(r["status"], 0) + 1
    return {"count": len(cikti), "summary": ozet, "records": cikti}


@app.get("/version")
def version_endpoint(source: str, date: str, madde: str | None = None, raw_dir: str = "data/raw") -> dict:
    """Bir düzenlemenin (ya da tek bir maddesinin) verilen tarihteki metni.

    Değişiklikler ilk metne tarih sırasıyla uygulanarak üretilir; bu yüzden ham veri (ilk metin ve
    değişiklikler) yerelde bulunmalıdır.
    """
    from datetime import datetime

    from fastapi import HTTPException

    from mevzuatradar.version.build import madde_at, version_at

    try:
        gun = datetime.strptime(date, "%d/%m/%Y").date()
    except ValueError:
        raise HTTPException(422, "Tarih biçimi gg/aa/yyyy olmalı") from None
    try:
        if madde:
            metin, surum = madde_at(source, madde, gun, raw_dir)
            if metin is None:
                raise HTTPException(404, f"{date} itibarıyla {madde}. madde yok")
        else:
            surum = version_at(source, gun, raw_dir)
            metin = surum.text
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from None
    return {"source": source, "date": date, "madde": madde, "version": surum.label,
            "version_date": surum.date.isoformat() if surum.date else None, "text": metin}


DEMO = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>MevzuatRadar</title><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{font-family:-apple-system,system-ui,sans-serif;max-width:56rem;margin:2rem auto;padding:0 1rem;line-height:1.5}
 textarea{width:100%;min-height:9rem;font:inherit;padding:.6rem;border:1px solid #ccc;border-radius:.4rem}
 button{font:inherit;padding:.5rem 1.2rem;border:0;border-radius:.4rem;background:#1a56db;color:#fff;cursor:pointer}
 table{border-collapse:collapse;width:100%;margin-top:1rem;font-size:.92rem}
 th,td{border:1px solid #ddd;padding:.45rem .6rem;text-align:left;vertical-align:top}
 th{background:#f4f5f7} code{background:#f4f5f7;padding:.1rem .3rem;border-radius:.2rem}
 .muted{color:#666;font-size:.9rem}
</style></head><body>
<h1>MevzuatRadar</h1>
<p class="muted">Bir değişiklik maddesi yapıştırın; sistem hangi düzenlemenin hangi yerinin nasıl değiştiğini
çıkarsın. API dokümantasyonu: <a href="/docs">/docs</a></p>
<textarea id="t">MADDE 10 – Aynı Yönetmeliğin 17 nci maddesinin birinci fıkrası, ikinci fıkrasının birinci cümlesi ve üçüncü fıkrasının birinci cümlesi aşağıdaki şekilde değiştirilmiştir.
“(1) Kart çıkaran kuruluşlar ile kart hamilleri arasındaki ilişkiler sözleşmelerle düzenlenir.”
“Kart teslimi sırasında banka kartı hamillerine bilgilendirme yapılması zorunludur:”
“Kart teslimi sırasında kredi kartı hamillerine bilgi verilmesi zorunludur:”</textarea>
<p><button onclick="cikar()">Çıkar</button></p>
<div id="out"></div>
<script>
async function cikar(){
  const out = document.getElementById('out');
  out.innerHTML = '<p class="muted">Çalışıyor…</p>';
  const r = await fetch('/extract', {method:'POST', headers:{'Content-Type':'application/json'},
                                     body: JSON.stringify({text: document.getElementById('t').value})});
  const d = await r.json();
  if(!d.count){ out.innerHTML = '<p>Değişiklik kaydı bulunamadı.</p>'; return; }
  const yer = l => Object.entries(l).filter(([k,v]) => v && v !== 'normal')
                    .map(([k,v]) => k+'='+v).join(' ') || '-';
  out.innerHTML = '<p><b>' + d.count + '</b> kayıt</p><table><tr><th>İşlem</th><th>Hedef</th><th>Birim</th>' +
    '<th>Eski</th><th>Yeni</th></tr>' + d.records.map(r =>
      '<tr><td><code>'+r.operation+'</code></td><td>'+yer(r.location)+'</td><td>'+(r.unit||'')+'</td><td>'+
      (r.old_text||'')+'</td><td>'+((r.new_text||'').slice(0,90))+'</td></tr>').join('') + '</table>';
}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def demo() -> str:
    return DEMO
