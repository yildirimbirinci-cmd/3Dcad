from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "max" / "3DCAD_BRIDGE.ms"
MARKER = "CAD3D_MAX_CONNECT_BATCH_V3"

if not TARGET.is_file():
    raise RuntimeError(f"Dosya bulunamadi: {TARGET}")

text = TARGET.read_text(encoding="utf-8-sig")

if MARKER in text:
    print("ALREADY INSTALLED:", MARKER)
    raise SystemExit(0)

anchor = "fn CAD3D_ImportWalls filePath ="

if anchor not in text:
    raise RuntimeError(
        "CAD3D_ImportWalls bulunamadi. Dosya degistirilmedi."
    )

batch_fn = r'''

-- ============================================================
-- CAD3D_MAX_CONNECT_BATCH_V3
--
-- One Connect operation creates ALL requested horizontal bands.
-- Then every generated band is moved to its exact target local Z.
--
-- This avoids sequential Connect operations on already split vertical
-- edges, which caused the second level to fail verification.
-- ============================================================

fn CAD3D_ApplyConnectLevelsBatchV3 node levels wallHeightCm =
(
    if levels.count <= 0 then return true

    local cmUnit = units.decodeValue "1cm"
    local axisTol = units.decodeValue "0.01mm"
    local zTol = units.decodeValue "0.5mm"
    local minVertical = units.decodeValue "1mm"
    local minHorizontal = units.decodeValue "1mm"

    local ep = Edit_Poly()
    addModifier node ep

    max modify mode
    select node

    ep.SetPrimaryNode node
    modPanel.setCurrentObject ep

    ep.selectMode = 1
    ep.SetEPolySelLevel #Edge
    subObjectLevel = 2

    ep.RefreshScreen()
    completeRedraw()

    local edgeCountBefore = ep.GetNumEdges node:node
    local verticalEdges = #{}

    for edgeIndex = 1 to edgeCountBefore do
    (
        local va = ep.GetEdgeVertex edgeIndex 1 node:node
        local vb = ep.GetEdgeVertex edgeIndex 2 node:node

        if ((va > 0) and (vb > 0)) do
        (
            local pa = ep.GetVertex va node:node
            local pb = ep.GetVertex vb node:node

            local dx = abs (pb.x - pa.x)
            local dy = abs (pb.y - pa.y)
            local dz = abs (pb.z - pa.z)

            if ((dx <= axisTol) and (dy <= axisTol) and (dz > minVertical)) do
            (
                verticalEdges[edgeIndex] = true
            )
        )
    )

    if verticalEdges.numberSet <= 0 then
    (
        format "3Dcad Connect ERROR | no vertical edges found\n"
        return false
    )

    local clearEdges = #{}
    ep.SetSelection #Edge &clearEdges node:node

    local selectOK = ep.Select #Edge &verticalEdges select:true node:node
    local readback = ep.GetSelection #Edge node:node

    if ((selectOK != true) or (readback.numberSet != verticalEdges.numberSet)) then
    (
        format "3Dcad Connect ERROR | vertical selection failed | wanted=% selected=%\n" verticalEdges.numberSet readback.numberSet
        return false
    )

    ep.connectEdgeSegments = levels.count
    ep.connectEdgePinch = 0
    ep.connectEdgeSlide = 0

    format "\n========================================\n"
    format "3DCAD MAX CONNECT BATCH V3\n"
    format "Levels: %\n" levels
    format "Vertical edges selected: %\n" readback.numberSet
    format "Connect segments: %\n" levels.count

    ep.ButtonOp #ConnectEdges
    ep.RefreshScreen()
    completeRedraw()

    local edgeCountAfter = ep.GetNumEdges node:node

    if edgeCountAfter <= edgeCountBefore then
    (
        format "3Dcad Connect ERROR | batch Connect created no new topology\n"
        return false
    )

    local groups = #()

    for edgeIndex = (edgeCountBefore + 1) to edgeCountAfter do
    (
        local va = ep.GetEdgeVertex edgeIndex 1 node:node
        local vb = ep.GetEdgeVertex edgeIndex 2 node:node

        if ((va > 0) and (vb > 0)) do
        (
            local pa = ep.GetVertex va node:node
            local pb = ep.GetVertex vb node:node

            local dx = pb.x - pa.x
            local dy = pb.y - pa.y
            local dz = abs (pb.z - pa.z)
            local horizontalLength = sqrt ((dx * dx) + (dy * dy))

            if ((dz <= zTol) and (horizontalLength > minHorizontal)) do
            (
                local edgeZ = (pa.z + pb.z) * 0.5
                local foundGroup = 0

                for groupIndex = 1 to groups.count while foundGroup == 0 do
                (
                    if abs (groups[groupIndex][1] - edgeZ) <= zTol do
                    (
                        foundGroup = groupIndex
                    )
                )

                if foundGroup == 0 then
                (
                    local bits = #{}
                    bits[edgeIndex] = true
                    append groups #(edgeZ, bits)
                )
                else
                (
                    groups[foundGroup][2][edgeIndex] = true
                )
            )
        )
    )

    if groups.count != levels.count then
    (
        format "3Dcad Connect ERROR | generated band count mismatch | expected=% actual=%\n" levels.count groups.count
        return false
    )

    -- Sort generated groups by Z ascending.
    for i = 1 to (groups.count - 1) do
    (
        for j = (i + 1) to groups.count do
        (
            if groups[j][1] < groups[i][1] do
            (
                local temp = groups[i]
                groups[i] = groups[j]
                groups[j] = temp
            )
        )
    )

    -- Levels were already sorted by the Python request reader.
    -- Move every generated band to the matching exact target Z.
    for levelIndex = 1 to levels.count do
    (
        local targetCm = levels[levelIndex]
        local targetZ = targetCm * cmUnit

        local generatedZ = groups[levelIndex][1]
        local bandEdges = groups[levelIndex][2]
        local deltaZ = targetZ - generatedZ

        local clearBand = #{}
        ep.SetSelection #Edge &clearBand node:node

        local bandSelection = bandEdges
        local bandSelectOK = ep.Select #Edge &bandSelection select:true node:node
        local bandReadback = ep.GetSelection #Edge node:node

        if ((bandSelectOK != true) or (bandReadback.numberSet != bandEdges.numberSet)) then
        (
            format "3Dcad Connect ERROR | target=% cm | band selection failed | wanted=% selected=%\n" targetCm bandEdges.numberSet bandReadback.numberSet
            return false
        )

        local deltaVector = [0,0,deltaZ]

        ep.useSoftSel = false
        ep.SetOperation #Transform
        ep.MoveSelection deltaVector
        ep.Commit()

        ep.RefreshScreen()
        completeRedraw()

        local firstEdge = 0

        for edgeIndex = 1 to edgeCountAfter while firstEdge == 0 do
        (
            if bandEdges[edgeIndex] do firstEdge = edgeIndex
        )

        if firstEdge <= 0 then
        (
            format "3Dcad Connect ERROR | target=% cm | band edge missing after move\n" targetCm
            return false
        )

        local checkVA = ep.GetEdgeVertex firstEdge 1 node:node
        local checkVB = ep.GetEdgeVertex firstEdge 2 node:node
        local checkPA = ep.GetVertex checkVA node:node
        local checkPB = ep.GetVertex checkVB node:node

        if (
            (abs (checkPA.z - targetZ) > zTol) or
            (abs (checkPB.z - targetZ) > zTol)
        ) then
        (
            format "3Dcad Connect ERROR | target=% cm | final Z verification failed | A=% B=% expected=%\n" targetCm checkPA.z checkPB.z targetZ
            return false
        )

        format "3Dcad Connect moved | target=% cm | generated=% | delta=% | edges=%\n" targetCm generatedZ deltaZ bandEdges.numberSet
    )

    format "Connect levels completed: %\n" levels.count
    format "========================================\n\n"

    true
)


'''

text = text.replace(
    anchor,
    batch_fn + anchor,
    1,
)

old_call = "local connectOK = CAD3D_ApplyConnectLevelsV1 shapeNode connectLevelsCm heightCm"
new_call = "local connectOK = CAD3D_ApplyConnectLevelsBatchV3 shapeNode connectLevelsCm heightCm"

count = text.count(old_call)

if count != 1:
    raise RuntimeError(
        f"Connect call: beklenen 1 eslesme, bulunan {count}. Dosya degistirilmedi."
    )

text = text.replace(
    old_call,
    new_call,
    1,
)

if text.count(MARKER) < 1:
    raise RuntimeError(
        "Patch marker dogrulamasi basarisiz. Dosya degistirilmedi."
    )

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = (
    ROOT
    / "geliştirmeler"
    / "backups"
    / f"MAX_CONNECT_BATCH_V3_{stamp}"
)
backup_dir.mkdir(parents=True, exist_ok=True)

backup = backup_dir / TARGET.name
shutil.copy2(TARGET, backup)

TARGET.write_text(text, encoding="utf-8")

print("")
print("MAX_CONNECT_BATCH_V3 INSTALLED")
print("TARGET :", TARGET)
print("BACKUP :", backup)
print("")
print("FIX:")
print("  one Edit Poly")
print("  one Connect operation")
print("  segments = CONNECT_LEVEL_COUNT")
print("  generated horizontal bands grouped by Z")
print("  each band moved to exact sorted CONNECT_LEVEL_CM")
print("  each moved band numerically verified")
print("")
print("NO Python/UI/facade/detector files changed.")
print("NO Bridge/opening deletion added.")
print("")
print("RELOAD IN 3DS MAX:")
print(r'  fileIn @"C:\Users\yildi\Desktop\3Dcad\max\3DCAD_BRIDGE.ms"')
print("")
