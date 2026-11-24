"""Package the submission ZIP (excludes .env, .venv, the 1 GB papers ZIP and the extracted text).
Usage: python src/make_zip.py   -> ../assignment2.zip
"""
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
EXCL_DIRS = {".venv", "__pycache__", "papers_zip"}
EXCL_FILES = {".env", "papers_text.jsonl"}
out = ROOT.parent / "assignment2.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if p.is_file() and not (set(rel.parts) & EXCL_DIRS) and p.name not in EXCL_FILES:
            z.write(p, Path("assignment2") / rel)
print("wrote", out, round(out.stat().st_size / 1e6, 1), "MB")
