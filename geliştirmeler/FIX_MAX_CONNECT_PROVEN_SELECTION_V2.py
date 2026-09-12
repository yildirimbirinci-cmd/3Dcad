from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "max" / "3DCAD_BRIDGE.ms"
MARKER = "CAD3D_MAX_CONNECT_PROVEN_SELECTION_V2"

if not TARGET.is_file():
    raise RuntimeError(f"Dosya bulunamadi: {TARGET}")

text = TARGET.read_text(encoding="utf-8-sig")

if MARKER in text:
    print("ALREADY INSTALLED:", MARKER)
    raise SystemExit(0)

old_setup = '''    max modify mode
    select node
    modPanel.setCurrentObject ep
    ep.selectMode = 1
    subObjectLevel = 2
'''

new_setup = '''    -- CAD3D_MAX_CONNECT_PROVEN_SELECTION_V2
    -- Mirror the previously proven CAD_to_3D_Max Edit Poly setup.
    max modify mode
    select node

    ep.SetPrimaryNode node
    modPanel.setCurrentObject ep

    ep.selectMode = 1
    ep.SetEPolySelLevel #Edge
    subObjectLevel = 2

    ep.RefreshScreen()
    completeRedraw()
'''

old_vertical_select = '''    local edgeSelection = selectedVertical
    ep.SetSelection #Edge &edgeSelection node:node

    ep.connectEdgeSegments = 1
    ep.connectEdgePinch = 0
    ep.connectEdgeSlide = 0
'''

new_vertical_select = '''    -- CAD3D_MAX_CONNECT_PROVEN_SELECTION_V2
    -- Proven selection contract:
    -- clear -> Select -> authoritative GetSelection readback.
    local emptyEdgeSelection = #{}
    ep.SetSelection #Edge &emptyEdgeSelection node:node

    local edgeSelection = selectedVertical
    local edgeSelectOK = ep.Select #Edge &edgeSelection select:true node:node
    local selectedReadback = ep.GetSelection #Edge node:node

    if ((edgeSelectOK != true) or (selectedReadback.numberSet != selectedVertical.numberSet)) then
    (
        format "3Dcad Connect ERROR | target=% cm | vertical selection failed | wanted=% selected=%\\n" targetCm selectedVertical.numberSet selectedReadback.numberSet
        return false
    )

    format "3Dcad Connect vertical selection | target=% cm | selected=%\\n" targetCm selectedReadback.numberSet

    ep.connectEdgeSegments = 1
    ep.connectEdgePinch = 0
    ep.connectEdgeSlide = 0
'''

old_move = '''    local newSelection = newHorizontal
    ep.SetSelection #Edge &newSelection node:node

    local deltaVector = [0,0,deltaZ]
    ep.MoveSelection &deltaVector
    ep.RefreshScreen()
    completeRedraw()
'''

new_move = '''    -- CAD3D_MAX_CONNECT_PROVEN_SELECTION_V2
    -- Select actual newly-created horizontal Connect edges with
    -- clear -> Select -> readback, then use the proven transform contract.
    local clearNewEdges = #{}
    ep.SetSelection #Edge &clearNewEdges node:node

    local newSelection = newHorizontal
    local newSelectOK = ep.Select #Edge &newSelection select:true node:node
    local newReadback = ep.GetSelection #Edge node:node

    if ((newSelectOK != true) or (newReadback.numberSet != newHorizontal.numberSet)) then
    (
        format "3Dcad Connect ERROR | target=% cm | new horizontal selection failed | wanted=% selected=%\\n" targetCm newHorizontal.numberSet newReadback.numberSet
        return false
    )

    local deltaVector = [0,0,deltaZ]

    ep.useSoftSel = false
    ep.SetOperation #Transform
    ep.MoveSelection deltaVector
    ep.Commit()

    ep.RefreshScreen()
    completeRedraw()
'''

for label, old, new in (
    ("Edit Poly setup", old_setup, new_setup),
    ("vertical edge selection", old_vertical_select, new_vertical_select),
    ("horizontal move selection", old_move, new_move),
):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: beklenen 1 eslesme, bulunan {count}. Dosya degistirilmedi."
        )
    text = text.replace(old, new, 1)

if text.count(MARKER) < 3:
    raise RuntimeError("Patch marker dogrulamasi basarisiz. Dosya degistirilmedi.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = (
    ROOT
    / "geliştirmeler"
    / "backups"
    / f"MAX_CONNECT_PROVEN_SELECTION_V2_{stamp}"
)
backup_dir.mkdir(parents=True, exist_ok=True)
backup = backup_dir / TARGET.name

shutil.copy2(TARGET, backup)
TARGET.write_text(text, encoding="utf-8")

print("")
print("MAX_CONNECT_PROVEN_SELECTION_V2 INSTALLED")
print("TARGET :", TARGET)
print("BACKUP :", backup)
print("")
print("FIX:")
print("  SetPrimaryNode")
print("  SetEPolySelLevel #Edge")
print("  clear -> Select -> GetSelection verification")
print("  ButtonOp #ConnectEdges")
print("  clear -> Select new horizontal edges")
print("  SetOperation #Transform")
print("  MoveSelection")
print("  Commit")
print("")
print("NO Python/UI/facade/detector files changed.")
print("NO Bridge/opening deletion added.")
print("")
print("RELOAD IN 3DS MAX:")
print(r'  fileIn @"C:\Users\yildi\Desktop\3Dcad\max\3DCAD_BRIDGE.ms"')
print("")
