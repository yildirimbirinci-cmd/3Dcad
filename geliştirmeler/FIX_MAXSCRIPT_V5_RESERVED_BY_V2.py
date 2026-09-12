from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "max" / "3DCAD_BRIDGE.ms"

if not TARGET.is_file():
    raise RuntimeError(f"Dosya bulunamadi: {TARGET}")

text = TARGET.read_text(encoding="utf-8-sig")

start_token = "fn CAD3D_PointSegmentDistanceXYV5"
end_token = "fn CAD3D_ImportWalls filePath ="

start = text.find(start_token)
end = text.find(end_token, start)

if start < 0:
    raise RuntimeError(
        "WINDOW_PAIR_TOPOLOGY_V5 blogu bulunamadi. Dosya degistirilmedi."
    )

if end < 0:
    raise RuntimeError(
        "CAD3D_ImportWalls anchor bulunamadi. Dosya degistirilmedi."
    )

block = text[start:end]

before_count = len(
    re.findall(
        r"(?<![A-Za-z0-9_])by(?![A-Za-z0-9_])",
        block,
    )
)

if before_count <= 0:
    print("V5 blogunda standalone 'by' yok. Degisiklik gerekmiyor.")
    raise SystemExit(0)

# MAXScript'te "by" rezerve kelimedir.
# Yalnizca V5 blogunda, yalnizca standalone identifier olarak degistir.
fixed_block = re.sub(
    r"(?<![A-Za-z0-9_])by(?![A-Za-z0-9_])",
    "bYValue",
    block,
)

after_count = len(
    re.findall(
        r"(?<![A-Za-z0-9_])by(?![A-Za-z0-9_])",
        fixed_block,
    )
)

if after_count != 0:
    raise RuntimeError(
        "Standalone 'by' tamamen temizlenemedi. Dosya degistirilmedi."
    )

new_text = text[:start] + fixed_block + text[end:]

# Basit yapisal dogrulamalar.
required = (
    "fn CAD3D_PointSegmentDistanceXYV5 px py ax ay bx bYValue =",
    "local bYValue = (record[5]-pivotYmm) * mmUnit",
    "CAD3D_FindBandEdgeAtPointV5 ep shapeNode bx bYValue lowerRefZ zTol",
    "CAD3D_FindBandEdgeAtPointV5 ep shapeNode bx bYValue upperRefZ zTol",
)

missing = [
    token
    for token in required
    if token not in new_text
]

if missing:
    raise RuntimeError(
        "V5 reserved-word fix sonrasi beklenen satirlar bulunamadi:\n"
        + "\n".join(missing)
        + "\nDosya degistirilmedi."
    )

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = (
    ROOT
    / "geliştirmeler"
    / "backups"
    / f"MAXSCRIPT_V5_RESERVED_BY_V2_{stamp}"
)
backup_dir.mkdir(parents=True, exist_ok=True)

backup = backup_dir / TARGET.name
shutil.copy2(TARGET, backup)

TARGET.write_text(
    new_text,
    encoding="utf-8",
)

print("")
print("MAXSCRIPT_V5_RESERVED_BY_V2 INSTALLED")
print("TARGET :", TARGET)
print("BACKUP :", backup)
print("STANDALONE 'by' REPLACED :", before_count)
print("")
print("ONLY CHANGED:")
print("  WINDOW_PAIR_TOPOLOGY_V5 block")
print("")
print("NEXT:")
print(r'  fileIn @"C:\Users\yildi\Desktop\3Dcad\max\3DCAD_BRIDGE.ms"')
print("")
