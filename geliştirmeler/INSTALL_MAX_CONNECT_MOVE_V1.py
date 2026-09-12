from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil

ROOT = Path.cwd()
TARGET = ROOT / "max" / "3DCAD_BRIDGE.ms"
MARKER = "CAD3D_MAX_CONNECT_MOVE_V1"

if not TARGET.is_file():
    raise RuntimeError(f"Dosya bulunamadi: {TARGET}")

text = TARGET.read_text(encoding="utf-8-sig")

if MARKER in text:
    print("ALREADY INSTALLED:", MARKER)
    raise SystemExit(0)

helpers = r'''

-- ============================================================
-- CAD3D_MAX_CONNECT_MOVE_V1
-- Reads CONNECT_LEVEL_CM from the current Python request.
-- Targets are FLOOR-LOCAL Z values. BASE_Z is never added here.
-- ============================================================

fn CAD3D_ReadConnectLevelsV1 filePath =
(
    local result = #()
    local stream = openFile filePath mode:"rt"

    if stream == undefined then return result

    while not eof stream do
    (
        local line = readLine stream

        if line != undefined do
        (
            if matchPattern line pattern:"CONNECT_LEVEL_CM=*" do
            (
                if line.count > 17 do
                (
                    local rawValue = substring line 18 (line.count - 17)
                    local value = undefined

                    try
                    (
                        value = rawValue as float
                    )
                    catch
                    (
                        value = undefined
                    )

                    if value != undefined do append result value
                )
            )
        )
    )

    close stream

    sort result

    local uniqueValues = #()

    for value in result do
    (
        if uniqueValues.count == 0 then
        (
            append uniqueValues value
        )
        else
        (
            if abs (value - uniqueValues[uniqueValues.count]) > 0.000001 do
            (
                append uniqueValues value
            )
        )
    )

    uniqueValues
)


fn CAD3D_ConnectAtLocalZV1 ep node targetCm wallHeightCm =
(
    local cmUnit = units.decodeValue "1cm"
    local targetZ = targetCm * cmUnit
    local wallTopZ = wallHeightCm * cmUnit

    local axisTol = units.decodeValue "0.01mm"
    local zTol = units.decodeValue "0.5mm"
    local minVertical = units.decodeValue "1mm"
    local minHorizontal = units.decodeValue "1mm"

    if targetZ <= zTol then return true
    if targetZ >= (wallTopZ - zTol) then return true

    local edgeCountBefore = ep.GetNumEdges node:node
    local selectedVertical = #{}

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
                local zMin = amin pa.z pb.z
                local zMax = amax pa.z pb.z

                if ((targetZ > (zMin + zTol)) and (targetZ < (zMax - zTol))) do
                (
                    selectedVertical[edgeIndex] = true
                )
            )
        )
    )

    if selectedVertical.numberSet <= 0 then
    (
        format "3Dcad Connect ERROR | target=% cm | vertical edge not found\n" targetCm
        return false
    )

    local edgeSelection = selectedVertical
    ep.SetSelection #Edge &edgeSelection node:node

    ep.connectEdgeSegments = 1
    ep.connectEdgePinch = 0
    ep.connectEdgeSlide = 0

    ep.ButtonOp #ConnectEdges
    ep.RefreshScreen()
    completeRedraw()

    local edgeCountAfter = ep.GetNumEdges node:node

    if edgeCountAfter <= edgeCountBefore then
    (
        format "3Dcad Connect ERROR | target=% cm | no new topology\n" targetCm
        return false
    )

    local newHorizontal = #{}
    local generatedZSum = 0.0
    local generatedZCount = 0

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
                newHorizontal[edgeIndex] = true
                generatedZSum += ((pa.z + pb.z) * 0.5)
                generatedZCount += 1
            )
        )
    )

    if ((newHorizontal.numberSet <= 0) or (generatedZCount <= 0)) then
    (
        format "3Dcad Connect ERROR | target=% cm | new horizontal edge not found\n" targetCm
        return false
    )

    local generatedZ = generatedZSum / generatedZCount
    local deltaZ = targetZ - generatedZ

    local newSelection = newHorizontal
    ep.SetSelection #Edge &newSelection node:node

    local deltaVector = [0,0,deltaZ]
    ep.MoveSelection &deltaVector
    ep.RefreshScreen()
    completeRedraw()

    local finalOK = true

    for edgeIndex = 1 to edgeCountAfter while finalOK do
    (
        if newHorizontal[edgeIndex] do
        (
            local va = ep.GetEdgeVertex edgeIndex 1 node:node
            local vb = ep.GetEdgeVertex edgeIndex 2 node:node

            local pa = ep.GetVertex va node:node
            local pb = ep.GetVertex vb node:node

            if abs (pa.z - targetZ) > zTol do finalOK = false
            if abs (pb.z - targetZ) > zTol do finalOK = false
        )
    )

    if finalOK != true then
    (
        format "3Dcad Connect ERROR | target=% cm | final Z verification failed\n" targetCm
        return false
    )

    format "3Dcad Connect moved | target=% cm | generated=% | delta=% | edges=%\n" targetCm generatedZ deltaZ newHorizontal.numberSet

    true
)


fn CAD3D_ApplyConnectLevelsV1 node levels wallHeightCm =
(
    if levels.count <= 0 then return true

    local ep = Edit_Poly()
    addModifier node ep

    max modify mode
    select node
    modPanel.setCurrentObject ep
    ep.selectMode = 1
    subObjectLevel = 2

    format "\n========================================\n"
    format "3DCAD MAX CONNECT MOVE V1\n"
    format "Levels: %\n" levels

    for targetCm in levels do
    (
        local ok = CAD3D_ConnectAtLocalZV1 ep node targetCm wallHeightCm

        if ok != true then
        (
            format "FAILED LEVEL: % cm\n" targetCm
            format "========================================\n\n"
            return false
        )
    )

    format "Connect levels completed: %\n" levels.count
    format "========================================\n\n"

    true
)


'''

anchor_fn = "fn CAD3D_ImportWalls filePath ="

if anchor_fn not in text:
    raise RuntimeError(
        "CAD3D_ImportWalls bulunamadi. Dosya degistirilmedi."
    )

text = text.replace(
    anchor_fn,
    helpers + anchor_fn,
    1,
)

pattern = re.compile(
    r'(?P<indent>^[ \t]*)addModifier[ \t]+shapeNode[ \t]+extrudeMod[ \t]*$',
    re.MULTILINE,
)

match = pattern.search(text)

if match is None:
    raise RuntimeError(
        "addModifier shapeNode extrudeMod bulunamadi. Dosya degistirilmedi."
    )

indent = match.group("indent")

block = (
    match.group(0)
    + "\n\n"
    + indent + "-- CAD3D_MAX_CONNECT_MOVE_V1\n"
    + indent + "local connectLevelsCm = CAD3D_ReadConnectLevelsV1 filePath\n"
    + indent + "if connectLevelsCm.count > 0 then\n"
    + indent + "(\n"
    + indent + "    local connectOK = CAD3D_ApplyConnectLevelsV1 shapeNode connectLevelsCm heightCm\n"
    + indent + "    if connectOK != true do\n"
    + indent + "    (\n"
    + indent + "        throw \"CAD3D_VERTICAL_CONNECT_FAILED\"\n"
    + indent + "    )\n"
    + indent + ")\n"
)

text = text[:match.start()] + block + text[match.end():]

if text.count(MARKER) < 2:
    raise RuntimeError(
        "Patch marker dogrulamasi basarisiz. Dosya degistirilmedi."
    )

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = (
    ROOT
    / "geliştirmeler"
    / "backups"
    / f"MAX_CONNECT_MOVE_V1_{stamp}"
)
backup_dir.mkdir(parents=True, exist_ok=True)

backup = backup_dir / TARGET.name
shutil.copy2(TARGET, backup)

TARGET.write_text(text, encoding="utf-8")

print("")
print("MAX_CONNECT_MOVE_V1 INSTALLED")
print("TARGET :", TARGET)
print("BACKUP :", backup)
print("")
print("BEHAVIOR:")
print("  Extrude")
print("  -> Edit Poly")
print("  -> vertical edges spanning each CONNECT_LEVEL_CM")
print("  -> Connect")
print("  -> move newly created horizontal edges to exact local Z")
print("")
print("BASE_Z is NOT added to Connect levels.")
print("NO Bridge / opening deletion is added.")
print("")
print("RELOAD IN 3DS MAX:")
print(r'  fileIn @"C:\Users\yildi\Desktop\3Dcad\max\3DCAD_BRIDGE.ms"')
print("")
