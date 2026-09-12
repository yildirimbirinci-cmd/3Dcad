from __future__ import annotations

from datetime import datetime
from pathlib import Path
import ast
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "src" / "export" / "connect_levels_runtime.py"
MARKER = "CAD3D_CONNECT_FULL_DOCUMENT_GEOMETRY_V1"

if not TARGET.is_file():
    raise RuntimeError(f"Dosya bulunamadı: {TARGET}")

text = TARGET.read_text(encoding="utf-8-sig")

if MARKER in text:
    print("ALREADY INSTALLED:", MARKER)
    raise SystemExit(0)

old_a = '''    facades = (
        _facades_by_number(
            preanalysis
        )
    )

    regions = (
        _regions_by_id(
            preanalysis
        )
    )

    all_rows_by_facade = (
'''

new_a = '''    facades = (
        _facades_by_number(
            preanalysis
        )
    )

    # CAD3D_CONNECT_FULL_DOCUMENT_GEOMETRY_V1
    # Region rows in the serialized/preanalysis result do not carry
    # geometry. Use the already-loaded full CAD geometry and let
    # _horizontal_levels() restrict it to each facade bbox.
    from cad.facade_runtime import (
        _document_geometry,
    )

    full_geometry = list(
        _document_geometry(
            full_document
        )
        or []
    )

    if not full_geometry:
        raise RuntimeError(
            floor_name
            + ": tam CAD geometrisi Connect icin alinamadi."
        )

    all_rows_by_facade = (
'''

old_b = '''        region_id = str(
            facade.get(
                "region_id",
                "",
            )
            or ""
        )

        region = (
            regions.get(
                region_id
            )
        )

        if not isinstance(
            region,
            dict,
        ):
            continue

        region_geometry = list(
            region.get(
                "geometry",
                [],
            )
            or []
        )

        if not region_geometry:
            continue

        bottoms = [
'''

new_b = '''        bottoms = [
'''

old_c = '''        structural_levels = (
            _horizontal_levels(
                region_geometry,
                bbox,
                source_to_mm,
            )
        )
'''

new_c = '''        structural_levels = (
            _horizontal_levels(
                full_geometry,
                bbox,
                source_to_mm,
            )
        )
'''

for label, old, new in (
    ("full geometry setup", old_a, new_a),
    ("region geometry block", old_b, new_b),
    ("horizontal level source", old_c, new_c),
):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: beklenen 1 eslesme, bulunan {count}. Dosya degistirilmedi."
        )
    text = text.replace(old, new, 1)

ast.parse(text)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = (
    ROOT
    / "geliştirmeler"
    / "backups"
    / f"CONNECT_FULL_DOCUMENT_GEOMETRY_V1_{stamp}"
)
backup_dir.mkdir(parents=True, exist_ok=True)
backup = backup_dir / TARGET.name
shutil.copy2(TARGET, backup)

TARGET.write_text(text, encoding="utf-8")
ast.parse(TARGET.read_text(encoding="utf-8-sig"))

print("")
print("CONNECT_FULL_DOCUMENT_GEOMETRY_V1 INSTALLED")
print("TARGET :", TARGET)
print("BACKUP :", backup)
print("")
print("CHANGE:")
print("  Connect datum geometry source:")
print("  region['geometry'] -> full_document CAD geometry")
print("  facade bbox still limits each search region")
print("")
print("NOT CHANGED:")
print("  facade_runtime.py")
print("  main_window.py")
print("  cad_view.py")
print("  detectors")
print("  max/3DCAD_BRIDGE.ms")
print("")
