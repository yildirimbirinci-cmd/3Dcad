from __future__ import annotations

from pathlib import Path
from datetime import datetime
import ast
import shutil

ROOT = Path.cwd()
DEV = ROOT / "gelistirmeler"
if not DEV.exists():
    # Turkish folder name in the real project.
    DEV = ROOT / "geli\u015ftirmeler"

MAX_BRIDGE = ROOT / "src" / "export" / "max_bridge.py"
MULTI = ROOT / "src" / "export" / "multi_floor_max_send.py"
MAXSCRIPT = ROOT / "max" / "3DCAD_BRIDGE.ms"
VERTICAL = ROOT / "src" / "cad" / "vertical_opening_levels.py"
FACADE = ROOT / "src" / "cad" / "facade_runtime.py"

MARKER = "CAD3D_VERTICAL_CONNECT_PREP_V1"

for path in (MAX_BRIDGE, MULTI, MAXSCRIPT, VERTICAL, FACADE):
    if not path.exists():
        raise RuntimeError(f"Required file not found: {path}")

vertical_text = VERTICAL.read_text(encoding="utf-8-sig")
facade_text = FACADE.read_text(encoding="utf-8-sig")

if "VERTICAL_OPENING_LEVELS_V1" not in vertical_text:
    raise RuntimeError(
        "VERTICAL_OPENING_LEVELS_V1 is not installed in vertical_opening_levels.py. "
        "No files changed."
    )

if "VERTICAL_OPENING_LEVELS_V1" not in facade_text:
    raise RuntimeError(
        "Facade runtime is not bound to VERTICAL_OPENING_LEVELS_V1. "
        "No files changed."
    )

texts = {
    MAX_BRIDGE: MAX_BRIDGE.read_text(encoding="utf-8-sig"),
    MULTI: MULTI.read_text(encoding="utf-8-sig"),
    MAXSCRIPT: MAXSCRIPT.read_text(encoding="utf-8-sig"),
}

if all(MARKER in text for text in texts.values()):
    print("")
    print("VERTICAL CONNECT PREP V1 ALREADY INSTALLED")
    print("")
    raise SystemExit(0)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly one match, found {count}. No files changed."
        )
    return text.replace(old, new, 1)


def insert_before_once(text: str, needle: str, block: str, label: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly one insertion point, found {count}. No files changed."
        )
    return text.replace(needle, block + needle, 1)


# -----------------------------------------------------------------------------
# 1) src/export/max_bridge.py
# -----------------------------------------------------------------------------
max_text = texts[MAX_BRIDGE]

if MARKER not in max_text:
    normalizer = r'''

# CAD3D_VERTICAL_CONNECT_PREP_V1
def _cad3d_normalize_connect_levels(
    values,
    wall_height_cm,
):
    import math

    try:
        wall_height = float(
            wall_height_cm
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise RuntimeError(
            "Wall height is invalid for Connect preparation."
        ) from exc

    if (
        not math.isfinite(
            wall_height
        )
        or wall_height <= 0.0
    ):
        raise RuntimeError(
            "Wall height is invalid for Connect preparation."
        )

    output = []
    seen = set()

    for raw_value in (
        values
        or ()
    ):
        try:
            value = float(
                raw_value
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

        if not math.isfinite(
            value
        ):
            continue

        # Connect topology is needed only strictly inside the wall.
        if not (
            0.0
            < value
            < wall_height
        ):
            continue

        # Vertical-opening output is numeric CAD-derived data.
        # Rounding here is serialization/dedup only, not an architectural rule.
        key = round(
            value,
            6,
        )

        if key in seen:
            continue

        seen.add(
            key
        )
        output.append(
            float(key)
        )

    output.sort()

    return tuple(
        output
    )
'''

    max_text = insert_before_once(
        max_text,
        "def send_wall_lines_to_max(\n",
        normalizer,
        "max_bridge helper insertion",
    )

    signature_old = """    interfloor_cm=0.0,\n    pivot_source=None,\n):\n"""
    signature_new = """    interfloor_cm=0.0,\n    pivot_source=None,\n    connect_levels_cm=None,\n):\n"""

    max_text = replace_once(
        max_text,
        signature_old,
        signature_new,
        "max_bridge send signature",
    )

    connect_request_block = r'''    # CAD3D_VERTICAL_CONNECT_PREP_V1
    normalized_connect_levels = ()

    if is_floor_request:
        normalized_connect_levels = (
            _cad3d_normalize_connect_levels(
                connect_levels_cm,
                wall_height_cm,
            )
        )

        lines.append(
            "CONNECT_LEVEL_COUNT="
            + str(
                len(
                    normalized_connect_levels
                )
            )
        )

        for connect_level_cm in normalized_connect_levels:
            lines.append(
                "CONNECT_LEVEL_CM="
                + repr(
                    float(
                        connect_level_cm
                    )
                )
            )

'''

    max_text = insert_before_once(
        max_text,
        "    sent_count = 0\n",
        connect_request_block,
        "max_bridge request level insertion",
    )

# -----------------------------------------------------------------------------
# 2) src/export/multi_floor_max_send.py
# -----------------------------------------------------------------------------
multi_text = texts[MULTI]

if MARKER not in multi_text:
    collector = r'''

# CAD3D_VERTICAL_CONNECT_PREP_V1
def _cad3d_collect_connect_levels(
    window,
    package,
):
    import math

    try:
        from cad.facade_runtime import (
            refresh_facade_matches,
        )
    except ImportError:
        from src.cad.facade_runtime import (
            refresh_facade_matches,
        )

    result = refresh_facade_matches(
        window
    )

    if not isinstance(
        result,
        dict,
    ):
        raise RuntimeError(
            "Facade vertical result is not available."
        )

    floor_name = str(
        package.get(
            "floor_name",
            "",
        )
        or ""
    ).strip()

    if not floor_name:
        raise RuntimeError(
            "Floor name is missing for Connect preparation."
        )

    try:
        wall_height_cm = float(
            package[
                "wall_height_cm"
            ]
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise RuntimeError(
            floor_name
            + ": wall height is invalid for Connect preparation."
        ) from exc

    if (
        not math.isfinite(
            wall_height_cm
        )
        or wall_height_cm <= 0.0
    ):
        raise RuntimeError(
            floor_name
            + ": wall height is invalid for Connect preparation."
        )

    levels = []
    matched_window_count = 0
    missing_window_count = 0
    door_top_count = 0

    for row in (
        result.get(
            "plan_guided_facade_windows",
            [],
        )
        or []
    ):
        if not isinstance(
            row,
            dict,
        ):
            continue

        row_floor = str(
            row.get(
                "floor_name",
                "",
            )
            or ""
        ).strip()

        if row_floor != floor_name:
            continue

        kind = str(
            row.get(
                "kind",
                "window",
            )
            or "window"
        ).strip().lower()

        if kind != "window":
            continue

        matched_window_count += 1

        bottom = row.get(
            "window_bottom_local_z_cm"
        )
        top = row.get(
            "window_top_local_z_cm"
        )

        try:
            bottom_value = float(
                bottom
            )
            top_value = float(
                top
            )
        except (
            TypeError,
            ValueError,
        ):
            missing_window_count += 1
            continue

        if (
            not math.isfinite(
                bottom_value
            )
            or not math.isfinite(
                top_value
            )
            or top_value <= bottom_value
        ):
            missing_window_count += 1
            continue

        levels.extend(
            (
                bottom_value,
                top_value,
            )
        )

    if missing_window_count > 0:
        raise RuntimeError(
            floor_name
            + ": facade window vertical levels are incomplete: "
            + str(
                missing_window_count
            )
        )

    # Only CAD-derived door top levels are accepted here.
    # No fixed 210 cm fallback is introduced.
    for match in (
        result.get(
            "matches",
            [],
        )
        or []
    ):
        if not isinstance(
            match,
            dict,
        ):
            continue

        for pair in (
            match.get(
                "opening_pairs",
                [],
            )
            or []
        ):
            if not isinstance(
                pair,
                dict,
            ):
                continue

            pair_floor = str(
                pair.get(
                    "floor_name",
                    "",
                )
                or ""
            ).strip()

            if pair_floor != floor_name:
                continue

            kind = str(
                pair.get(
                    "kind",
                    "",
                )
                or ""
            ).strip().lower()

            if "door" not in kind:
                continue

            raw_top = pair.get(
                "door_top_local_z_cm"
            )

            try:
                top_value = float(
                    raw_top
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if not math.isfinite(
                top_value
            ):
                continue

            levels.append(
                top_value
            )
            door_top_count += 1

    normalized = []
    seen = set()

    for raw_value in levels:
        value = float(
            raw_value
        )

        if not (
            0.0
            < value
            < wall_height_cm
        ):
            continue

        key = round(
            value,
            6,
        )

        if key in seen:
            continue

        seen.add(
            key
        )
        normalized.append(
            float(key)
        )

    normalized.sort()

    if (
        matched_window_count > 0
        and not normalized
    ):
        raise RuntimeError(
            floor_name
            + ": no valid CAD-derived Connect level was produced."
        )

    print("")
    print(
        "=== 3DCAD VERTICAL CONNECT PREP V1 ==="
    )
    print(
        "FLOOR:",
        floor_name,
    )
    print(
        "FACADE WINDOWS:",
        matched_window_count,
    )
    print(
        "CAD DOOR TOPS:",
        door_top_count,
    )
    print(
        "CONNECT LEVELS CM:",
        normalized,
    )
    print(
        "======================================"
    )
    print("")

    return tuple(
        normalized
    )
'''

    multi_text = insert_before_once(
        multi_text,
        "def _send_next_floor(\n",
        collector,
        "multi-floor collector insertion",
    )

    # Locate the one current send_wall_lines_to_max call and inject both
    # calculation and keyword argument without rewriting the working function.
    tree = ast.parse(
        multi_text
    )

    send_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(
            node,
            ast.Call,
        )
        and (
            (
                isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "send_wall_lines_to_max"
            )
            or (
                isinstance(
                    node.func,
                    ast.Attribute,
                )
                and node.func.attr
                == "send_wall_lines_to_max"
            )
        )
    ]

    if len(send_calls) != 1:
        raise RuntimeError(
            "multi_floor_max_send.py: expected one send_wall_lines_to_max call, "
            f"found {len(send_calls)}. No files changed."
        )

    call = send_calls[0]
    lines = multi_text.splitlines(keepends=True)

    call_start_index = call.lineno - 1
    call_end_index = call.end_lineno - 1

    statement_index = call_start_index
    while (
        statement_index > 0
        and "send_wall_lines_to_max"
        not in lines[statement_index]
    ):
        statement_index -= 1

    statement_indent = (
        lines[statement_index]
        [: len(lines[statement_index]) - len(lines[statement_index].lstrip())]
    )

    prep_lines = (
        statement_indent
        + "connect_levels_cm = _cad3d_collect_connect_levels(window, package)\n"
    )

    lines.insert(
        statement_index,
        prep_lines,
    )

    # AST line indexes are now shifted by one below insertion point.
    call_end_index += 1

    keyword_indent = None
    for idx in range(
        call_start_index,
        min(
            call_end_index + 1,
            len(lines),
        ),
    ):
        if "pivot_source=" in lines[idx]:
            keyword_indent = (
                lines[idx]
                [: len(lines[idx]) - len(lines[idx].lstrip())]
            )
            break

    if keyword_indent is None:
        # Fallback to one indentation level deeper than assignment.
        keyword_indent = statement_indent + "    "

    closing_index = call_end_index

    lines.insert(
        closing_index,
        keyword_indent
        + "connect_levels_cm=connect_levels_cm,\n",
    )

    multi_text = "".join(
        lines
    )

# -----------------------------------------------------------------------------
# 3) max/3DCAD_BRIDGE.ms
# -----------------------------------------------------------------------------
ms_text = texts[MAXSCRIPT]

if MARKER not in ms_text:
    ms_helpers = r'''

-- ============================================================
-- CAD3D_VERTICAL_CONNECT_PREP_V1
--
-- Uses ONLY CONNECT_LEVEL_CM values supplied by Python.
-- No fixed door/window architectural height is introduced here.
-- BASE_Z is node/world placement and is NOT added to local Connect Z.
-- ============================================================

fn CAD3D_ReadConnectLevelsV1 filePath =
(
    local rawLevels = #()
    local stream = undefined

    try
    (
        stream = openFile filePath mode:"rt"
    )
    catch
    (
        stream = undefined
    )

    if stream == undefined then return rawLevels

    while not eof stream do
    (
        local line = readLine stream

        if line != undefined then
        (
            if matchPattern line pattern:"CONNECT_LEVEL_CM=*" then
            (
                if line.count > 17 then
                (
                    local valueText = substring line 18 (line.count - 17)
                    local value = undefined

                    try
                    (
                        value = valueText as float
                    )
                    catch
                    (
                        value = undefined
                    )

                    if value != undefined do
                    (
                        append rawLevels value
                    )
                )
            )
        )
    )

    close stream

    sort rawLevels

    local uniqueLevels = #()

    for value in rawLevels do
    (
        if uniqueLevels.count == 0 then
        (
            append uniqueLevels value
        )
        else
        (
            if (abs (value - uniqueLevels[uniqueLevels.count])) > 0.000001 do
            (
                append uniqueLevels value
            )
        )
    )

    uniqueLevels
)


fn CAD3D_ConnectOneLevelV1 editPolyMod shapeNode targetCm wallHeightCm =
(
    local cmUnit = units.decodeValue "1cm"
    local targetZ = targetCm * cmUnit
    local wallTopZ = wallHeightCm * cmUnit

    local minVerticalLength = units.decodeValue "1mm"
    local absoluteXYTolerance = units.decodeValue "0.01mm"
    local relativeXYTolerance = 0.000001
    local levelZTolerance = units.decodeValue "0.5mm"
    local horizontalMinLength = units.decodeValue "1mm"

    if targetZ <= levelZTolerance then return true
    if targetZ >= (wallTopZ - levelZTolerance) then return true

    local edgeCountBefore = editPolyMod.GetNumEdges node:shapeNode
    local verticalEdges = #{}
    local verticalEdgeCount = 0

    for edgeIndex = 1 to edgeCountBefore do
    (
        local vertexA = editPolyMod.GetEdgeVertex edgeIndex 1 node:shapeNode
        local vertexB = editPolyMod.GetEdgeVertex edgeIndex 2 node:shapeNode

        if ((vertexA > 0) and (vertexB > 0)) then
        (
            local pointA = editPolyMod.GetVertex vertexA node:shapeNode
            local pointB = editPolyMod.GetVertex vertexB node:shapeNode

            local dx = abs (pointB.x - pointA.x)
            local dy = abs (pointB.y - pointA.y)
            local dz = abs (pointB.z - pointA.z)

            local xyTolerance = absoluteXYTolerance

            if ((dz * relativeXYTolerance) > xyTolerance) do
            (
                xyTolerance = dz * relativeXYTolerance
            )

            if ((dz > minVerticalLength) and (dx <= xyTolerance) and (dy <= xyTolerance)) then
            (
                local zMin = amin pointA.z pointB.z
                local zMax = amax pointA.z pointB.z

                if ((targetZ > (zMin + levelZTolerance)) and (targetZ < (zMax - levelZTolerance))) then
                (
                    verticalEdges[edgeIndex] = true
                    verticalEdgeCount += 1
                )
            )
        )
    )

    if verticalEdgeCount <= 0 then
    (
        format "3Dcad Connect ERROR: no vertical edge span for target % cm\n" targetCm
        return false
    )

    local clearEdges = #{}
    editPolyMod.SetSelection #Edge &clearEdges node:shapeNode

    local selectOK = editPolyMod.Select #Edge &verticalEdges select:true node:shapeNode
    local selectedReadback = editPolyMod.GetSelection #Edge node:shapeNode

    if ((selectOK != true) or (selectedReadback.numberSet != verticalEdgeCount)) then
    (
        format "3Dcad Connect ERROR: vertical edge selection failed at % cm\n" targetCm
        return false
    )

    editPolyMod.connectEdgeSegments = 1
    editPolyMod.connectEdgePinch = 0
    editPolyMod.connectEdgeSlide = 0

    editPolyMod.ButtonOp #ConnectEdges
    editPolyMod.RefreshScreen()
    completeRedraw()

    local edgeCountAfter = editPolyMod.GetNumEdges node:shapeNode

    if edgeCountAfter <= edgeCountBefore then
    (
        format "3Dcad Connect ERROR: Connect created no topology at % cm\n" targetCm
        return false
    )

    local horizontalEdges = #{}
    local horizontalCount = 0
    local minConnectZ = 1.0e30
    local maxConnectZ = -1.0e30

    for edgeIndex = (edgeCountBefore + 1) to edgeCountAfter do
    (
        local vertexA = editPolyMod.GetEdgeVertex edgeIndex 1 node:shapeNode
        local vertexB = editPolyMod.GetEdgeVertex edgeIndex 2 node:shapeNode

        if ((vertexA > 0) and (vertexB > 0)) then
        (
            local pointA = editPolyMod.GetVertex vertexA node:shapeNode
            local pointB = editPolyMod.GetVertex vertexB node:shapeNode

            local dx = pointB.x - pointA.x
            local dy = pointB.y - pointA.y
            local dz = abs (pointB.z - pointA.z)
            local horizontalLength = sqrt ((dx * dx) + (dy * dy))

            if ((dz <= levelZTolerance) and (horizontalLength > horizontalMinLength)) then
            (
                horizontalEdges[edgeIndex] = true
                horizontalCount += 1

                if pointA.z < minConnectZ do minConnectZ = pointA.z
                if pointA.z > maxConnectZ do maxConnectZ = pointA.z
                if pointB.z < minConnectZ do minConnectZ = pointB.z
                if pointB.z > maxConnectZ do maxConnectZ = pointB.z
            )
        )
    )

    if horizontalCount <= 0 then
    (
        format "3Dcad Connect ERROR: no new horizontal edges at % cm\n" targetCm
        return false
    )

    if ((maxConnectZ - minConnectZ) > levelZTolerance) then
    (
        format "3Dcad Connect ERROR: new horizontal edges do not share one Z at % cm\n" targetCm
        return false
    )

    local currentConnectZ = (minConnectZ + maxConnectZ) * 0.5
    local moveDeltaZ = targetZ - currentConnectZ

    local clearHorizontal = #{}
    editPolyMod.SetSelection #Edge &clearHorizontal node:shapeNode

    local horizontalSelectOK = editPolyMod.Select #Edge &horizontalEdges select:true node:shapeNode
    local horizontalReadback = editPolyMod.GetSelection #Edge node:shapeNode

    if ((horizontalSelectOK != true) or (horizontalReadback.numberSet != horizontalCount)) then
    (
        format "3Dcad Connect ERROR: new horizontal edge selection failed at % cm\n" targetCm
        return false
    )

    editPolyMod.useSoftSel = false
    editPolyMod.SetOperation #Transform
    editPolyMod.MoveSelection [0,0,moveDeltaZ]
    editPolyMod.Commit()

    editPolyMod.RefreshScreen()
    completeRedraw()

    for edgeIndex = 1 to edgeCountAfter do
    (
        if horizontalEdges[edgeIndex] then
        (
            local vertexA = editPolyMod.GetEdgeVertex edgeIndex 1 node:shapeNode
            local vertexB = editPolyMod.GetEdgeVertex edgeIndex 2 node:shapeNode
            local pointA = editPolyMod.GetVertex vertexA node:shapeNode
            local pointB = editPolyMod.GetVertex vertexB node:shapeNode

            if ((abs (pointA.z - targetZ)) > levelZTolerance) then
            (
                format "3Dcad Connect ERROR: final Z verification failed at % cm\n" targetCm
                return false
            )

            if ((abs (pointB.z - targetZ)) > levelZTolerance) then
            (
                format "3Dcad Connect ERROR: final Z verification failed at % cm\n" targetCm
                return false
            )
        )
    )

    format "3Dcad Connect moved | target=% cm | generatedZ=% | delta=% | horizontalEdges=%\n" targetCm currentConnectZ moveDeltaZ horizontalCount

    true
)


fn CAD3D_ConnectLevelsV1 shapeNode editPolyMod connectLevels wallHeightCm =
(
    if connectLevels.count <= 0 then return true

    max modify mode
    select shapeNode

    editPolyMod.SetPrimaryNode shapeNode
    modPanel.setCurrentObject editPolyMod
    editPolyMod.selectMode = 1
    editPolyMod.SetEPolySelLevel #Edge
    subObjectLevel = 2

    editPolyMod.RefreshScreen()
    completeRedraw()

    format "\n"
    format "========================================\n"
    format "3DCAD VERTICAL CONNECT PREP V1\n"
    format "Connect levels: %\n" connectLevels

    for targetCm in connectLevels do
    (
        local levelOK = CAD3D_ConnectOneLevelV1 editPolyMod shapeNode targetCm wallHeightCm

        if levelOK != true then
        (
            format "3Dcad Connect ERROR: target failed: % cm\n" targetCm
            format "========================================\n"
            return false
        )
    )

    format "Connect levels completed: %\n" connectLevels.count
    format "========================================\n"
    format "\n"

    true
)


'''

    ms_text = insert_before_once(
        ms_text,
        "fn CAD3D_ImportWalls filePath =\n",
        ms_helpers,
        "MaxScript helper insertion",
    )

    extrude_old = '''        addModifier shapeNode extrudeMod\n\n        format "3Dcad Extrude added | height=% cm | segments=1 | caps=ON\\n" heightCm\n'''

    extrude_new = '''        addModifier shapeNode extrudeMod\n\n        format "3Dcad Extrude added | height=% cm | segments=1 | caps=ON\\n" heightCm\n\n        -- CAD3D_VERTICAL_CONNECT_PREP_V1\n        local connectLevelsCm = CAD3D_ReadConnectLevelsV1 filePath\n\n        if connectLevelsCm.count > 0 then\n        (\n            local editPolyMod = Edit_Poly()\n            addModifier shapeNode editPolyMod\n\n            local connectOK = CAD3D_ConnectLevelsV1 shapeNode editPolyMod connectLevelsCm heightCm\n\n            if connectOK != true then\n            (\n                delete shapeNode\n                format "3Dcad bridge: vertical Connect preparation failed.\\n"\n                return false\n            )\n        )\n'''

    ms_text = replace_once(
        ms_text,
        extrude_old,
        extrude_new,
        "MaxScript Extrude binding",
    )

# -----------------------------------------------------------------------------
# Validate all Python text BEFORE touching project files.
# -----------------------------------------------------------------------------
ast.parse(max_text)
ast.parse(multi_text)

if MARKER not in max_text:
    raise RuntimeError("max_bridge marker verification failed. No files changed.")
if MARKER not in multi_text:
    raise RuntimeError("multi_floor marker verification failed. No files changed.")
if MARKER not in ms_text:
    raise RuntimeError("MaxScript marker verification failed. No files changed.")

if "CONNECT_LEVEL_CM=" not in max_text:
    raise RuntimeError("Request serialization verification failed. No files changed.")
if "CAD3D_ConnectLevelsV1" not in ms_text:
    raise RuntimeError("Max Connect function verification failed. No files changed.")
if "connect_levels_cm=connect_levels_cm" not in multi_text:
    raise RuntimeError("Multi-floor binding verification failed. No files changed.")

# -----------------------------------------------------------------------------
# Backup + atomic-ish write.
# -----------------------------------------------------------------------------
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = DEV / "backups" / f"VERTICAL_CONNECT_PREP_V1_{stamp}"
backup_dir.mkdir(parents=True, exist_ok=True)

for path in (MAX_BRIDGE, MULTI, MAXSCRIPT):
    shutil.copy2(
        path,
        backup_dir / path.name,
    )

MAX_BRIDGE.write_text(max_text, encoding="utf-8")
MULTI.write_text(multi_text, encoding="utf-8")
MAXSCRIPT.write_text(ms_text, encoding="utf-8")

# Compile checks after write. If one fails, restore all changed files.
try:
    compile(
        MAX_BRIDGE.read_text(encoding="utf-8"),
        str(MAX_BRIDGE),
        "exec",
    )
    compile(
        MULTI.read_text(encoding="utf-8"),
        str(MULTI),
        "exec",
    )
except Exception:
    shutil.copy2(backup_dir / MAX_BRIDGE.name, MAX_BRIDGE)
    shutil.copy2(backup_dir / MULTI.name, MULTI)
    shutil.copy2(backup_dir / MAXSCRIPT.name, MAXSCRIPT)
    raise

print("")
print("VERTICAL_CONNECT_PREP_V1 INSTALLED")
print("")
print("PIPELINE:")
print("  CAD facade vertical levels")
print("  -> CONNECT_LEVEL_CM request rows")
print("  -> Extrude")
print("  -> Edit Poly")
print("  -> Connect")
print("  -> exact local Z move")
print("")
print("LEVEL SOURCES:")
print("  window_bottom_local_z_cm")
print("  window_top_local_z_cm")
print("  door_top_local_z_cm (only when CAD-derived)")
print("")
print("NO FIXED ARCHITECTURAL HEIGHT FALLBACK ADDED")
print("BASE_Z remains node/world placement only")
print("NO Bridge / opening hole operation added yet")
print("")
print("BACKUP:")
print(" ", backup_dir)
print("")
print("RELOAD IN 3DS MAX:")
print("  max\\3DCAD_BRIDGE.ms")
print("")
