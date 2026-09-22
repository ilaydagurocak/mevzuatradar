"""Bir kaynağın uçtan uca işlenmesi: değişiklik çıkarımı + zaman farkındalıklı doğrulama +
bilinen kaynak tutarsızlıkları. CLI ve veri seti üretici aynı fonksiyonu kullanır."""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field

from mevzuatradar.extract.amendments import extract_amendments
from mevzuatradar.extract.known_issues import apply_known_issues, file_urls, load_issues
from mevzuatradar.extract.verify import verify_chronological
from mevzuatradar.parse.text_extract import extract_text


@dataclass
class SourceRun:
    source: str
    amendment_files: list[str]
    results: list  # [(değişiklik_sırası, kayıt, VerifyResult)]
    resolved_issues: list[str] = field(default_factory=list)
    urls: dict[str, str] = field(default_factory=dict)


def process_source(source: str, raw_dir: str = "data/raw",
                   issues_path: str = "configs/known_source_issues.yaml") -> SourceRun | None:
    base = f"{raw_dir}/{source}"
    kons = glob.glob(f"{base}/konsolide_*")
    amds = sorted(glob.glob(f"{base}/degisiklik*"))  # degisiklik00, 01, ... = tarih sırası
    if not kons or not amds:
        return None
    per_amd = [[a.to_dict() for a in extract_amendments(extract_text(f).text)] for f in amds]
    results = verify_chronological(per_amd, extract_text(max(kons, key=os.path.getmtime)).text)
    urls = file_urls(raw_dir)
    results, resolved = apply_known_issues(source, amds, results, load_issues(issues_path), urls)
    return SourceRun(source, amds, results, resolved, urls)
