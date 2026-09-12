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
    raise RuntimeError("V5 fonksiyon blogu bulunamadi. Dosya degistirilmedi.")

if end < 0:
    raise RuntimeError("CAD3D_ImportWalls anchor bulunamadi. Dosya degistirilmedi.")

block = text[start:end]

replacements = (
    (
        "fn CAD3D_PointSegmentDistanceXYV5 px py ax ay bx by =",
        "fn CAD3D_PointSegmentDistanceXYV5 px py ax ay bx bYValue =",
    ),
    (
        "local dy = by-ay",
        "local dy = bYValue-ay",
    ),
    (
        "local by = (record[5]-pivotYmm) * mmUnit",
        "local bYValue = (record[5]-pivotYmm) * mmUnit",
    ),
    (
        "CAD3D_FindBandEdgeAtPointV5 ep shapeNode bx by lowerRefZ zTol",
        "CAD3D_FindBandEdgeAtPointV5 ep shapeNode bx bYValue lowerRefZ zTol",
    ),
    (
        "CAD3D_FindBandEdgeAtPointV5 ep shapeNode bx by upperRefZ zTol",
        "CAD3D_FindBandEdgeAtPointV5 ep shapeNode bx bYValue upperRefZ zTol",
    ),
)

changed = 0

for old, new in replacements:
    count = block.count(old)

    if count == 1:
        block = block.replace(old, new, 1)
        changed += 1
    elif count == 0 and new in block:
        pass
    else:
        raise RuntimeError(
            f"Beklenmeyen eslesme sayisi ({count}): {old!r}. Dosya degistirilmedi."
        )

# "by" is a MAXScript keyword. There must be no standalone identifier "by"
# left inside the newly-added V5 block.
remaining = re.findall(r"(?<![A-Za-z0-9_])by(?![A-Za-z0-9_])", block)
if remaining:
    raise RuntimeError(
        "V5 blogunda standalone 'by' hala bulundu. Dosya degistirilmedi."
    )

new_text = text[:start] + block + text[end:]

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = (
    ROOT
    / "geliştirmeler"
    / "backups"
    / f"MAXSCRIPT_V5_RESERVED_BY_FIX_{stamp}"
)
backup_dir.mkdir(parents=True, exist_ok=True)

backup = backup_dir / TARGET.name
shutil.copy2(TARGET, backup)

TARGET.write_text(new_text, encoding="utf-8")

print("")
print("MAXSCRIPT_V5_RESERVED_BY_FIX INSTALLED")
print("TARGET :", TARGET)
print("BACKUP :", backup)
print("REPLACEMENTS :", changed)
print("")
print("FIX:")
print("  MAXScript reserved identifier 'by' -> 'bYValue'")
print("  Only WINDOW_PAIR_TOPOLOGY_V5 block changed.")
print("")
print("IMPORTANT:")
print("  The V3 output you saw came from the already-loaded old bridge.")
print("  The failed fileIn did NOT load V5.")
print("")
