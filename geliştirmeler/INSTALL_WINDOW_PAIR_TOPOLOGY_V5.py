from __future__ import annotations

from datetime import datetime
from pathlib import Path
import ast
import shutil

ROOT = Path.cwd()
RUNTIME = ROOT / "src" / "export" / "connect_levels_runtime.py"
MULTI = ROOT / "src" / "export" / "multi_floor_max_send.py"
MAXSCRIPT = ROOT / "max" / "3DCAD_BRIDGE.ms"

for path in (RUNTIME, MULTI, MAXSCRIPT):
    if not path.is_file():
        raise RuntimeError(f"Dosya bulunamadi: {path}")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = ROOT / "geliştirmeler" / "backups" / f"WINDOW_PAIR_TOPOLOGY_V5_{stamp}"
backup_dir.mkdir(parents=True, exist_ok=True)

for path in (RUNTIME, MULTI, MAXSCRIPT):
    shutil.copy2(path, backup_dir / path.name)

runtime = RUNTIME.read_text(encoding="utf-8-sig")
multi = MULTI.read_text(encoding="utf-8-sig")
ms = MAXSCRIPT.read_text(encoding="utf-8-sig")

if "def write_window_pair_topology_records(" not in runtime:
    runtime += r'''

# WINDOW_PAIR_TOPOLOGY_V5
def write_window_pair_topology_records(window, package):
    # Reuse the working facade datum/local-Z solver.
    # Its unique-Z list is deliberately ignored.
    import contextlib
    import io
    from pathlib import Path

    with contextlib.redirect_stdout(io.StringIO()):
        collect_connect_levels(window, package)

    analysis = _current_analysis(window)
    if not isinstance(analysis, dict):
        raise RuntimeError("Window topology: cephe sonucu bulunamadi.")

    floor_name = str(package.get("floor_name", "") or "").strip()

    wall_height_cm = _num(
        package.get(
            "wall_height_cm",
            package.get("floor_height_cm"),
        )
    )

    if wall_height_cm is None or wall_height_cm <= 0.0:
        raise RuntimeError(
            floor_name
            + ": Window topology duvar yuksekligi gecersiz."
        )

    full_document = getattr(window, "_full_document", None)
    if full_document is None:
        full_document = package.get("document")

    from export.max_bridge import _source_to_mm
    source_to_mm = float(_source_to_mm(full_document))

    windows = list(package.get("windows", ()) or ())

    rows = [
        row
        for row in (
            analysis.get("plan_guided_facade_windows", [])
            or []
        )
        if (
            isinstance(row, dict)
            and str(row.get("floor_name", "") or "").strip()
            == floor_name
        )
    ]

    chosen = {}

    for row in rows:
        try:
            source_index = int(row.get("source_window_index"))
        except (TypeError, ValueError):
            continue

        if not (0 <= source_index < len(windows)):
            continue

        item = windows[source_index]
        if not isinstance(item, dict):
            continue

        jamb_a = item.get("jamb_a")
        jamb_b = item.get("jamb_b")

        if not (
            isinstance(jamb_a, (list, tuple))
            and len(jamb_a) >= 2
            and isinstance(jamb_b, (list, tuple))
            and len(jamb_b) >= 2
        ):
            continue

        try:
            bottom_cm = float(row["window_bottom_local_z_cm"])
            top_cm = float(row["window_top_local_z_cm"])
            ax_mm = float(jamb_a[0]) * source_to_mm
            ay_mm = float(jamb_a[1]) * source_to_mm
            bx_mm = float(jamb_b[0]) * source_to_mm
            by_mm = float(jamb_b[1]) * source_to_mm
            selection_cost = float(
                row.get("selection_cost", 1.0e30)
            )
        except (KeyError, TypeError, ValueError):
            continue

        if not (0.0 < bottom_cm < top_cm < float(wall_height_cm)):
            continue

        record = {
            "id": (
                str(row.get("source_window_id", "") or "").strip()
                or ("W" + str(source_index + 1).zfill(3))
            ),
            "source_index": source_index,
            "ax_mm": ax_mm,
            "ay_mm": ay_mm,
            "bx_mm": bx_mm,
            "by_mm": by_mm,
            "bottom_cm": bottom_cm,
            "top_cm": top_cm,
            "selection_cost": selection_cost,
        }

        previous = chosen.get(source_index)

        if (
            previous is None
            or selection_cost
            < float(previous.get("selection_cost", 1.0e30))
        ):
            chosen[source_index] = record

    records = [
        chosen[index]
        for index in sorted(chosen)
    ]

    if not records:
        raise RuntimeError(
            floor_name
            + ": Window topology icin eslesmis pencere/jamb kaydi yok."
        )

    target = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "cache"
        / "max_bridge"
        / "window_pair_topology_records.txt"
    )

    target.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# WINDOW_PAIR_TOPOLOGY_V5",
        "# W|id|ax_mm|ay_mm|bx_mm|by_mm|bottom_cm|top_cm",
    ]

    for row in records:
        lines.append(
            "|".join(
                (
                    "W",
                    str(row["id"]),
                    repr(float(row["ax_mm"])),
                    repr(float(row["ay_mm"])),
                    repr(float(row["bx_mm"])),
                    repr(float(row["by_mm"])),
                    repr(float(row["bottom_cm"])),
                    repr(float(row["top_cm"])),
                )
            )
        )

    target.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print("")
    print("=== WINDOW PAIR TOPOLOGY RECORDS V5 ===")
    print("FLOOR:", floor_name)
    print("WINDOW RECORDS:", len(records))
    print("GLOBAL CONNECT LEVELS: DISABLED")
    print("MAX REFERENCE BANDS: 2")
    print("TXT:", str(target))
    print("=== END WINDOW PAIR TOPOLOGY V5 ===")
    print("")

    return target
'''

def contains_named_call(node, name):
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == name
        ):
            return True
    return False

tree = ast.parse(multi)

send_func = None
for node in tree.body:
    if (
        isinstance(node, ast.FunctionDef)
        and node.name == "_send_next_floor"
    ):
        send_func = node
        break

if send_func is None:
    raise RuntimeError(
        "multi_floor_max_send.py: _send_next_floor bulunamadi."
    )

if "write_window_pair_topology_records(" not in multi:
    target_stmt = None

    for node in ast.walk(send_func):
        if (
            isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr))
            and contains_named_call(node, "collect_connect_levels")
        ):
            target_stmt = node
            break

    lines = multi.splitlines(keepends=True)

    if target_stmt is not None:
        indent = " " * int(target_stmt.col_offset)

        replacement = (
            indent
            + "from export.connect_levels_runtime import write_window_pair_topology_records\n"
            + indent
            + "write_window_pair_topology_records(window, package)\n"
            + indent
            + "connect_levels_cm = ()\n"
        )

        lines[
            target_stmt.lineno - 1:
            target_stmt.end_lineno
        ] = [replacement]

        multi = "".join(lines)

    else:
        send_stmt = None

        for node in ast.walk(send_func):
            if (
                isinstance(node, (ast.Assign, ast.Expr))
                and contains_named_call(node, "send_wall_lines_to_max")
            ):
                send_stmt = node
                break

        if send_stmt is None:
            raise RuntimeError(
                "multi_floor_max_send.py: Max send cagrisi bulunamadi."
            )

        indent = " " * int(send_stmt.col_offset)

        insertion = (
            indent
            + "from export.connect_levels_runtime import write_window_pair_topology_records\n"
            + indent
            + "write_window_pair_topology_records(window, package)\n"
            + indent
            + "connect_levels_cm = ()\n"
        )

        lines[
            send_stmt.lineno - 1:
            send_stmt.lineno - 1
        ] = [insertion]

        multi = "".join(lines)

ast.parse(multi)

if "fn CAD3D_WindowPairTopologyV5" not in ms:
    helper = r'''

-- ============================================================
-- WINDOW_PAIR_TOPOLOGY_V5
-- Global unique facade Z values are NOT Connect bands.
-- Exactly TWO reference bands are created.
-- Only each window's own jamb edge pairs are moved.
-- Bridge/opening is NOT performed in this stage.
-- ============================================================

fn CAD3D_ReadWindowPairRecordsV5 requestFile =
(
    local result = #()
    local sideFile = (getFilenamePath requestFile) + "window_pair_topology_records.txt"

    if doesFileExist sideFile == false then
    (
        format "WINDOW PAIR V5 ERROR: records file missing: %\n" sideFile
        return result
    )

    local f = openFile sideFile mode:"rt"

    if f == undefined then return result

    while not eof f do
    (
        local line = readLine f

        if line != undefined do
        (
            if matchPattern line pattern:"W|*" do
            (
                local p = filterString line "|"

                if p.count >= 8 do
                (
                    append result #(
                        p[2],
                        (p[3] as float),
                        (p[4] as float),
                        (p[5] as float),
                        (p[6] as float),
                        (p[7] as float),
                        (p[8] as float)
                    )
                )
            )
        )
    )

    close f
    result
)


fn CAD3D_PointSegmentDistanceXYV5 px py ax ay bx by =
(
    local dx = bx - ax
    local dy = by - ay
    local d2 = (dx*dx) + (dy*dy)

    if d2 <= 1.0e-12 then
    (
        sqrt (((px-ax)*(px-ax)) + ((py-ay)*(py-ay)))
    )
    else
    (
        local t = (((px-ax)*dx) + ((py-ay)*dy)) / d2
        if t < 0.0 do t = 0.0
        if t > 1.0 do t = 1.0

        local qx = ax + (t*dx)
        local qy = ay + (t*dy)

        sqrt (((px-qx)*(px-qx)) + ((py-qy)*(py-qy)))
    )
)


fn CAD3D_FindBandEdgeAtPointV5 ep node px py targetZ zTol =
(
    local bestEdge = 0
    local bestDistance = 1.0e30
    local edgeCount = ep.GetNumEdges node:node

    for edgeIndex = 1 to edgeCount do
    (
        local va = ep.GetEdgeVertex edgeIndex 1 node:node
        local vb = ep.GetEdgeVertex edgeIndex 2 node:node

        if ((va > 0) and (vb > 0)) do
        (
            local pa = ep.GetVertex va node:node
            local pb = ep.GetVertex vb node:node

            local dz = abs (pb.z-pa.z)
            local za = abs (pa.z-targetZ)
            local zb = abs (pb.z-targetZ)

            local dx = pb.x-pa.x
            local dy = pb.y-pa.y
            local xyLen = sqrt ((dx*dx) + (dy*dy))

            if (
                (dz <= zTol)
                and (za <= zTol)
                and (zb <= zTol)
                and (xyLen > 1.0e-9)
            ) do
            (
                local distance = CAD3D_PointSegmentDistanceXYV5 px py pa.x pa.y pb.x pb.y

                if distance < bestDistance do
                (
                    bestDistance = distance
                    bestEdge = edgeIndex
                )
            )
        )
    )

    #(bestEdge, bestDistance)
)


fn CAD3D_WindowPairTopologyV5 shapeNode requestFile pivotXmm pivotYmm heightCm =
(
    local records = CAD3D_ReadWindowPairRecordsV5 requestFile

    format "\n"
    format "========================================\n"
    format "WINDOW PAIR TOPOLOGY V5\n"
    format "Window records       : %\n" records.count
    format "Global unique Z bands: DISABLED\n"
    format "Reference bands      : 2\n"

    if records.count <= 0 then
    (
        format "WINDOW PAIR V5 ERROR: no records.\n"
        format "========================================\n"
        return false
    )

    local cmUnit = units.decodeValue "1cm"
    local mmUnit = units.decodeValue "1mm"
    local zTol = units.decodeValue "0.05mm"
    local wallTopZ = heightCm * cmUnit

    local ep = Edit_Poly()
    addModifier shapeNode ep

    max modify mode
    select shapeNode
    ep.SetPrimaryNode shapeNode
    modPanel.setCurrentObject ep
    ep.selectMode = 1
    ep.SetEPolySelLevel #Edge
    subObjectLevel = 2

    ep.RefreshScreen()
    completeRedraw()

    local edgeCountBefore = ep.GetNumEdges node:shapeNode
    local verticalEdges = #{}

    for edgeIndex = 1 to edgeCountBefore do
    (
        local va = ep.GetEdgeVertex edgeIndex 1 node:shapeNode
        local vb = ep.GetEdgeVertex edgeIndex 2 node:shapeNode

        if ((va > 0) and (vb > 0)) do
        (
            local pa = ep.GetVertex va node:shapeNode
            local pb = ep.GetVertex vb node:shapeNode

            local dx = abs (pb.x-pa.x)
            local dy = abs (pb.y-pa.y)
            local z0 = amin pa.z pb.z
            local z1 = amax pa.z pb.z

            if (
                (dx <= zTol)
                and (dy <= zTol)
                and (abs z0 <= zTol)
                and (abs (z1-wallTopZ) <= zTol)
            ) do
            (
                verticalEdges[edgeIndex] = true
            )
        )
    )

    if verticalEdges.numberSet <= 0 then
    (
        format "WINDOW PAIR V5 ERROR: full-height vertical edges not found.\n"
        return false
    )

    local clearEdges = #{}
    ep.SetSelection #Edge &clearEdges node:shapeNode

    local selectOK = ep.Select #Edge &verticalEdges select:true node:shapeNode
    local selected = ep.GetSelection #Edge node:shapeNode

    if ((selectOK != true) or (selected.numberSet != verticalEdges.numberSet)) then
    (
        format "WINDOW PAIR V5 ERROR: vertical selection failed.\n"
        return false
    )

    ep.SetOperation #ConnectEdges
    ep.connectEdgeSegments = 2
    ep.connectEdgePinch = 0
    ep.connectEdgeSlide = 0
    ep.ButtonOp #ConnectEdges
    ep.Commit()

    ep.RefreshScreen()
    completeRedraw()

    local edgeCountAfter = ep.GetNumEdges node:shapeNode

    if edgeCountAfter <= edgeCountBefore then
    (
        format "WINDOW PAIR V5 ERROR: reference Connect produced no topology.\n"
        return false
    )

    local generatedZ = #()

    for edgeIndex = (edgeCountBefore + 1) to edgeCountAfter do
    (
        local va = ep.GetEdgeVertex edgeIndex 1 node:shapeNode
        local vb = ep.GetEdgeVertex edgeIndex 2 node:shapeNode

        if ((va > 0) and (vb > 0)) do
        (
            local pa = ep.GetVertex va node:shapeNode
            local pb = ep.GetVertex vb node:shapeNode

            local dz = abs (pb.z-pa.z)
            local dx = pb.x-pa.x
            local dy = pb.y-pa.y
            local xyLen = sqrt ((dx*dx) + (dy*dy))

            if ((dz <= zTol) and (xyLen > 1.0e-9)) do
            (
                local z = (pa.z + pb.z) * 0.5
                local exists = false

                for oldZ in generatedZ while exists == false do
                (
                    if abs(oldZ-z) <= zTol do exists = true
                )

                if exists == false do append generatedZ z
            )
        )
    )

    sort generatedZ

    if generatedZ.count != 2 then
    (
        format "WINDOW PAIR V5 ERROR: expected 2 generated bands, got %.\n" generatedZ.count
        return false
    )

    local lowerRefZ = generatedZ[1]
    local upperRefZ = generatedZ[2]

    format "Lower reference Z    : %\n" lowerRefZ
    format "Upper reference Z    : %\n" upperRefZ

    local resolved = #()

    for record in records do
    (
        local id = record[1]

        local ax = (record[2]-pivotXmm) * mmUnit
        local ay = (record[3]-pivotYmm) * mmUnit
        local bx = (record[4]-pivotXmm) * mmUnit
        local by = (record[5]-pivotYmm) * mmUnit

        local bottomZ = record[6] * cmUnit
        local topZ = record[7] * cmUnit

        local lowerA = CAD3D_FindBandEdgeAtPointV5 ep shapeNode ax ay lowerRefZ zTol
        local lowerB = CAD3D_FindBandEdgeAtPointV5 ep shapeNode bx by lowerRefZ zTol
        local upperA = CAD3D_FindBandEdgeAtPointV5 ep shapeNode ax ay upperRefZ zTol
        local upperB = CAD3D_FindBandEdgeAtPointV5 ep shapeNode bx by upperRefZ zTol

        if (
            (lowerA[1] <= 0)
            or (lowerB[1] <= 0)
            or (upperA[1] <= 0)
            or (upperB[1] <= 0)
        ) then
        (
            format "% PREFLIGHT FAILED | unresolved jamb edge.\n" id
            return false
        )

        if (
            (lowerA[1] == lowerB[1])
            or (upperA[1] == upperB[1])
        ) then
        (
            format "% PREFLIGHT FAILED | A/B resolved to same edge.\n" id
            return false
        )

        append resolved #(
            id,
            lowerA[1],
            lowerB[1],
            upperA[1],
            upperB[1],
            bottomZ,
            topZ
        )

        format "% PREFLIGHT OK | LOWER=%/% | UPPER=%/% | BOTTOM=% cm | TOP=% cm\n" id lowerA[1] lowerB[1] upperA[1] upperB[1] record[6] record[7]
    )

    format "PREFLIGHT COMPLETE: % / %\n" resolved.count records.count

    for item in resolved do
    (
        local id = item[1]

        local lowerBits = #{}
        lowerBits[item[2]] = true
        lowerBits[item[3]] = true

        ep.SetSelection #Edge &clearEdges node:shapeNode
        ep.Select #Edge &lowerBits select:true node:shapeNode
        ep.useSoftSel = false
        ep.SetOperation #Transform
        ep.MoveSelection [0,0,(item[6]-lowerRefZ)]
        ep.Commit()

        local upperBits = #{}
        upperBits[item[4]] = true
        upperBits[item[5]] = true

        ep.SetSelection #Edge &clearEdges node:shapeNode
        ep.Select #Edge &upperBits select:true node:shapeNode
        ep.useSoftSel = false
        ep.SetOperation #Transform
        ep.MoveSelection [0,0,(item[7]-upperRefZ)]
        ep.Commit()

        format "% MOVED | bottom=% cm | top=% cm\n" id (item[6]/cmUnit) (item[7]/cmUnit)
    )

    ep.RefreshScreen()
    completeRedraw()

    format "Windows moved        : %\n" resolved.count
    format "Global Connect bands : 2 ONLY\n"
    format "Bridge               : DISABLED\n"
    format "========================================\n"
    format "\n"

    true
)


'''

    anchor = "fn CAD3D_ImportWalls filePath ="

    if anchor not in ms:
        raise RuntimeError(
            "3DCAD_BRIDGE.ms: CAD3D_ImportWalls bulunamadi."
        )

    ms = ms.replace(anchor, helper + anchor, 1)

active_old_calls = (
    "CAD3D_ApplyConnectLevelsBatchV3 shapeNode connectLevelsCm heightCm",
    "CAD3D_ApplyConnectLevelsV1 shapeNode connectLevelsCm heightCm",
)

if (
    "CAD3D_WindowPairTopologyV5 shapeNode filePath pivotX pivotY heightCm"
    not in ms
):
    replaced = False

    for old_call in active_old_calls:
        if old_call in ms:
            ms = ms.replace(
                old_call,
                "CAD3D_WindowPairTopologyV5 shapeNode filePath pivotX pivotY heightCm",
                1,
            )
            replaced = True
            break

    if not replaced:
        raise RuntimeError(
            "3DCAD_BRIDGE.ms: aktif eski Connect cagrisi bulunamadi."
        )

compile(runtime, str(RUNTIME), "exec")
compile(multi, str(MULTI), "exec")

for token in (
    "fn CAD3D_WindowPairTopologyV5",
    "CAD3D_WindowPairTopologyV5 shapeNode filePath pivotX pivotY heightCm",
    "ep.connectEdgeSegments = 2",
):
    if token not in ms:
        raise RuntimeError(
            "MaxScript dogrulama hatasi: " + token
        )

RUNTIME.write_text(runtime, encoding="utf-8")
MULTI.write_text(multi, encoding="utf-8")
MAXSCRIPT.write_text(ms, encoding="utf-8")

print("")
print("WINDOW_PAIR_TOPOLOGY_V5 INSTALLED")
print("")
print("FIXED PREVIOUS INSTALLER:")
print("  multi_floor_max_send.py is patched by Python AST")
print("  exact source formatting is no longer required")
print("")
print("ACTIVE TOPOLOGY:")
print("  old unique CONNECT_LEVEL_CM list -> DISABLED")
print("  Max global reference bands      -> EXACTLY 2")
print("  window lower edge pair          -> own facade bottom Z")
print("  window upper edge pair          -> own facade top Z")
print("  BASE_Z                          -> unchanged")
print("  Bridge/opening                  -> disabled")
print("")
print("CHANGED:")
print("  src/export/connect_levels_runtime.py")
print("  src/export/multi_floor_max_send.py")
print("  max/3DCAD_BRIDGE.ms")
print("")
print("NOT CHANGED:")
print("  max_bridge.py")
print("  facade matching")
print("  door/window/wall detectors")
print("  UI / facade labels")
print("  pivots / BASE_Z")
print("")
print("BACKUP:")
print(" ", backup_dir)
print("")
