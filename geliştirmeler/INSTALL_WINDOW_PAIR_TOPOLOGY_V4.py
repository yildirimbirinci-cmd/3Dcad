from pathlib import Path
from datetime import datetime
import shutil
import re

ROOT = Path(r"C:\Users\yildi\Desktop\3Dcad")
SRC_RUNTIME = ROOT / "src" / "export" / "connect_levels_runtime.py"
SRC_MULTI = ROOT / "src" / "export" / "multi_floor_max_send.py"
SRC_BRIDGE = ROOT / "src" / "export" / "max_bridge.py"
MAXSCRIPT = ROOT / "max" / "3DCAD_BRIDGE.ms"

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "geliştirmeler" / "backups" / f"WINDOW_PAIR_TOPOLOGY_V4_{stamp}"
BACKUP.mkdir(parents=True, exist_ok=True)

for p in (SRC_RUNTIME, SRC_MULTI, SRC_BRIDGE, MAXSCRIPT):
    if not p.exists():
        raise RuntimeError(f"Eksik dosya: {p}")
    shutil.copy2(p, BACKUP / p.name)

def read(p):
    return p.read_text(encoding="utf-8-sig")

def write(p, text):
    p.write_text(text, encoding="utf-8")

runtime = read(SRC_RUNTIME)
multi = read(SRC_MULTI)
bridge = read(SRC_BRIDGE)
ms = read(MAXSCRIPT)

# ============================================================
# 1) PER-WINDOW RECORDS
# ============================================================

if "WINDOW_PAIR_TOPOLOGY_V4" not in runtime:
    runtime += r'''

# WINDOW_PAIR_TOPOLOGY_V4
def collect_window_topology_records(window, package):
    # Existing facade/local-Z solver remains authoritative.
    # Its unique global level list is intentionally ignored.
    collect_connect_levels(window, package)

    analysis = _current_analysis(window)
    if not isinstance(analysis, dict):
        raise RuntimeError(
            str(package.get("floor_name", ""))
            + ": cephe eslestirme sonucu bulunamadi."
        )

    floor_name = str(
        package.get("floor_name", "")
        or ""
    ).strip()

    wall_height = float(
        package.get("floor_height_cm", 0.0)
        or 0.0
    )

    document = getattr(
        window,
        "_full_document",
        None,
    )

    if document is None:
        document = package.get("document")

    from export.max_bridge import _source_to_mm
    source_to_mm = float(_source_to_mm(document))

    windows = list(
        package.get("windows", ())
        or ()
    )

    rows = [
        row
        for row in (
            analysis.get(
                "plan_guided_facade_windows",
                [],
            )
            or []
        )
        if (
            isinstance(row, dict)
            and str(
                row.get("floor_name", "")
                or ""
            ).strip() == floor_name
        )
    ]

    chosen = {}

    for row in rows:
        try:
            source_index = int(
                row.get("source_window_index")
            )
        except (TypeError, ValueError):
            continue

        if not (
            0 <= source_index < len(windows)
        ):
            continue

        try:
            bottom_cm = float(
                row["window_bottom_local_z_cm"]
            )
            top_cm = float(
                row["window_top_local_z_cm"]
            )
        except (KeyError, TypeError, ValueError):
            continue

        if not (
            0.0 < bottom_cm < top_cm < wall_height
        ):
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
            ax_mm = float(jamb_a[0]) * source_to_mm
            ay_mm = float(jamb_a[1]) * source_to_mm
            bx_mm = float(jamb_b[0]) * source_to_mm
            by_mm = float(jamb_b[1]) * source_to_mm
            selection_cost = float(
                row.get("selection_cost", 1.0e30)
            )
        except (TypeError, ValueError):
            continue

        record = {
            "window_id": (
                str(
                    row.get("source_window_id", "")
                    or ""
                ).strip()
                or ("W" + str(source_index + 1).zfill(3))
            ),
            "source_window_index": source_index,
            "jamb_a_mm": [ax_mm, ay_mm],
            "jamb_b_mm": [bx_mm, by_mm],
            "window_bottom_local_z_cm": bottom_cm,
            "window_top_local_z_cm": top_cm,
            "facade_number": row.get("facade_number"),
            "_selection_cost": selection_cost,
        }

        previous = chosen.get(source_index)

        if (
            previous is None
            or selection_cost
            < float(
                previous.get(
                    "_selection_cost",
                    1.0e30,
                )
            )
        ):
            chosen[source_index] = record

    records = []

    for source_index in sorted(chosen):
        record = dict(chosen[source_index])
        record.pop("_selection_cost", None)
        records.append(record)

    if not records:
        raise RuntimeError(
            floor_name
            + ": pencere topology kaydi olusturulamadi."
        )

    print("")
    print("=== WINDOW PAIR TOPOLOGY RECORDS V4 ===")
    print("FLOOR:", floor_name)
    print("SOURCE_TO_MM:", source_to_mm)
    print("WINDOW RECORDS:", len(records))
    for row in records:
        print(
            row["window_id"],
            "| BOTTOM:",
            row["window_bottom_local_z_cm"],
            "| TOP:",
            row["window_top_local_z_cm"],
        )
    print("GLOBAL CONNECT LEVELS: DISABLED")
    print("=== END WINDOW PAIR TOPOLOGY RECORDS V4 ===")
    print("")

    return tuple(records)
'''

# ============================================================
# 2) MULTI FLOOR SENDER
# ============================================================

if "collect_window_topology_records" not in multi:
    pattern = re.compile(
        r'from export\.connect_levels_runtime import\s*(?:\(\s*)?collect_connect_levels(?:\s*\))?\s*\n'
        r'(?P<indent>\s*)connect_levels_cm\s*=\s*collect_connect_levels\(\s*window\s*,\s*package\s*\)',
        re.M,
    )
    m = pattern.search(multi)
    if not m:
        raise RuntimeError(
            "multi_floor_max_send.py: collect_connect_levels cagrisi bulunamadi."
        )
    indent = m.group("indent")
    replacement = (
        "from export.connect_levels_runtime import collect_window_topology_records\n"
        + indent
        + "window_topology_records = collect_window_topology_records(window, package)\n"
        + indent
        + "connect_levels_cm = ()"
    )
    multi = multi[:m.start()] + replacement + multi[m.end():]

if "window_topology_records=window_topology_records" not in multi:
    target = "connect_levels_cm=connect_levels_cm,"
    if target not in multi:
        raise RuntimeError(
            "multi_floor_max_send.py: connect_levels_cm kwarg bulunamadi."
        )
    multi = multi.replace(
        target,
        target
        + "\n            window_topology_records=window_topology_records,",
        1,
    )

# ============================================================
# 3) PYTHON MAX BRIDGE SERIALIZATION
# ============================================================

if "window_topology_records=None" not in bridge:
    target = "connect_levels_cm=None,"
    if target not in bridge:
        raise RuntimeError(
            "max_bridge.py: connect_levels_cm imzasi bulunamadi."
        )
    bridge = bridge.replace(
        target,
        target + "\n    window_topology_records=None,",
        1,
    )

if "WINDOW_LEVEL_COUNT=" not in bridge:
    serialization = r'''
    window_rows = []

    for row in (
        window_topology_records
        or ()
    ):
        if not isinstance(row, dict):
            continue

        jamb_a = row.get("jamb_a_mm")
        jamb_b = row.get("jamb_b_mm")

        if not (
            isinstance(jamb_a, (list, tuple))
            and len(jamb_a) >= 2
            and isinstance(jamb_b, (list, tuple))
            and len(jamb_b) >= 2
        ):
            continue

        window_rows.append(
            "W|"
            + _safe_line_text(
                row.get("window_id", "")
            )
            + "|"
            + repr(float(jamb_a[0]))
            + "|"
            + repr(float(jamb_a[1]))
            + "|"
            + repr(float(jamb_b[0]))
            + "|"
            + repr(float(jamb_b[1]))
            + "|"
            + repr(
                float(
                    row[
                        "window_bottom_local_z_cm"
                    ]
                )
            )
            + "|"
            + repr(
                float(
                    row[
                        "window_top_local_z_cm"
                    ]
                )
            )
        )

    request_lines.append(
        "WINDOW_LEVEL_COUNT="
        + str(len(window_rows))
    )
    request_lines.extend(window_rows)
'''

    m = re.search(
        r'\n(?P<indent>\s*)request_file\.write_text\(',
        bridge,
    )
    if not m:
        m = re.search(
            r'\n(?P<indent>\s*)request_path\.write_text\(',
            bridge,
        )
    if not m:
        raise RuntimeError(
            "max_bridge.py: request write anchor bulunamadi."
        )

    indent = m.group("indent")
    block = "\n".join(
        (indent + line if line else "")
        for line in serialization.strip("\n").splitlines()
    )
    bridge = bridge[:m.start()] + "\n" + block + bridge[m.start():]

# ============================================================
# 4) MAXSCRIPT V4
# ============================================================

if "fn CAD3D_WindowPairTopologyV4" not in ms:
    helper = r'''

-- ============================================================
-- WINDOW_PAIR_TOPOLOGY_V4
-- Two reference Connects + per-window jamb edge movement.
-- No Bridge/opening in this stage.
-- ============================================================

fn CAD3D_ReadWindowLevelRecordsV4 rows =
(
    local records = #()

    for line in rows do
    (
        if matchPattern line pattern:"W|*" then
        (
            local p = filterString line "|"

            if p.count >= 8 then
            (
                append records #(
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

    records
)


fn CAD3D_PointSegmentDistanceXYV4 px py ax ay bx by =
(
    local dx = bx - ax
    local dy = by - ay
    local d2 = (dx * dx) + (dy * dy)

    if d2 <= 1.0e-12 then
    (
        sqrt (((px-ax)*(px-ax)) + ((py-ay)*(py-ay)))
    )
    else
    (
        local t = (((px-ax)*dx) + ((py-ay)*dy)) / d2

        if t < 0.0 do t = 0.0
        if t > 1.0 do t = 1.0

        local qx = ax + (t * dx)
        local qy = ay + (t * dy)

        sqrt (((px-qx)*(px-qx)) + ((py-qy)*(py-qy)))
    )
)


fn CAD3D_ResolveHorizontalEdgeAtZV4 ep node px py targetZ zTol =
(
    local bestEdge = 0
    local bestDist = 1.0e30
    local edgeCount = ep.GetNumEdges node:node

    for i = 1 to edgeCount do
    (
        local va = ep.GetEdgeVertex i 1 node:node
        local vb = ep.GetEdgeVertex i 2 node:node

        if va > 0 and vb > 0 then
        (
            local a = ep.GetVertex va node:node
            local b = ep.GetVertex vb node:node

            local dz = abs (b.z - a.z)
            local za = abs (a.z - targetZ)
            local zb = abs (b.z - targetZ)

            local ddx = b.x - a.x
            local ddy = b.y - a.y
            local xyLen = sqrt ((ddx*ddx) + (ddy*ddy))

            if dz <= zTol and za <= zTol and zb <= zTol and xyLen > 1.0e-9 then
            (
                local d = CAD3D_PointSegmentDistanceXYV4 px py a.x a.y b.x b.y

                if d < bestDist then
                (
                    bestDist = d
                    bestEdge = i
                )
            )
        )
    )

    #(bestEdge, bestDist)
)


fn CAD3D_ConnectOneBandV4 ep node verticalSelection =
(
    local before = ep.GetNumEdges node:node

    local clearEdges = #{}
    ep.SetSelection #Edge &clearEdges node:node

    local selectedOK = ep.Select #Edge &verticalSelection select:true node:node
    local readback = ep.GetSelection #Edge node:node

    if selectedOK != true or readback.numberSet <= 0 then
    (
        return #(false, 0.0)
    )

    ep.SetOperation #ConnectEdges
    ep.connectEdgeSegments = 1
    ep.ButtonOp #ConnectEdges
    ep.Commit()

    ep.RefreshScreen()
    completeRedraw()

    local after = ep.GetNumEdges node:node

    if after <= before then
    (
        return #(false, 0.0)
    )

    local firstEdge = before + 1
    local v = ep.GetEdgeVertex firstEdge 1 node:node

    if v <= 0 then
    (
        return #(false, 0.0)
    )

    local p = ep.GetVertex v node:node

    #(true, p.z)
)


fn CAD3D_WindowPairTopologyV4 shapeNode rows pivotXmm pivotYmm heightCm =
(
    local records = CAD3D_ReadWindowLevelRecordsV4 rows

    format "\n"
    format "========================================\n"
    format "WINDOW PAIR TOPOLOGY V4\n"
    format "Window records : %\n" records.count

    if records.count <= 0 then
    (
        format "No window topology records. Stage skipped.\n"
        format "========================================\n"
        return true
    )

    local cmUnit = units.decodeValue "1cm"
    local mmUnit = units.decodeValue "1mm"
    local modelBottomZ = 0.0
    local modelTopZ = heightCm * cmUnit
    local zTol = units.decodeValue "0.05mm"

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

    -- A) one upper reference Connect
    local fullVertical = #{}
    local edgeCountA = ep.GetNumEdges node:shapeNode

    for i = 1 to edgeCountA do
    (
        local va = ep.GetEdgeVertex i 1 node:shapeNode
        local vb = ep.GetEdgeVertex i 2 node:shapeNode

        if va > 0 and vb > 0 then
        (
            local a = ep.GetVertex va node:shapeNode
            local b = ep.GetVertex vb node:shapeNode

            local dx = abs (b.x-a.x)
            local dy = abs (b.y-a.y)
            local z0 = amin a.z b.z
            local z1 = amax a.z b.z

            if dx <= zTol and dy <= zTol and abs(z0-modelBottomZ) <= zTol and abs(z1-modelTopZ) <= zTol then
            (
                fullVertical[i] = true
            )
        )
    )

    local upperResult = CAD3D_ConnectOneBandV4 ep shapeNode fullVertical

    if upperResult[1] != true then
    (
        format "WINDOW PAIR TOPOLOGY ERROR: upper reference Connect failed.\n"
        return false
    )

    local upperRefZ = upperResult[2]

    -- B) one lower reference Connect
    local lowerVertical = #{}
    local edgeCountB = ep.GetNumEdges node:shapeNode

    for i = 1 to edgeCountB do
    (
        local va = ep.GetEdgeVertex i 1 node:shapeNode
        local vb = ep.GetEdgeVertex i 2 node:shapeNode

        if va > 0 and vb > 0 then
        (
            local a = ep.GetVertex va node:shapeNode
            local b = ep.GetVertex vb node:shapeNode

            local dx = abs (b.x-a.x)
            local dy = abs (b.y-a.y)
            local z0 = amin a.z b.z
            local z1 = amax a.z b.z

            if dx <= zTol and dy <= zTol and abs(z0-modelBottomZ) <= zTol and abs(z1-upperRefZ) <= zTol then
            (
                lowerVertical[i] = true
            )
        )
    )

    local lowerResult = CAD3D_ConnectOneBandV4 ep shapeNode lowerVertical

    if lowerResult[1] != true then
    (
        format "WINDOW PAIR TOPOLOGY ERROR: lower reference Connect failed.\n"
        return false
    )

    local lowerRefZ = lowerResult[2]

    format "Upper reference Z: %\n" upperRefZ
    format "Lower reference Z: %\n" lowerRefZ
    format "Global Connect bands: 2\n"

    -- C) preflight all windows before moving anything
    local resolved = #()

    for r in records do
    (
        local id = r[1]
        local ax = (r[2] - pivotXmm) * mmUnit
        local ay = (r[3] - pivotYmm) * mmUnit
        local bx = (r[4] - pivotXmm) * mmUnit
        local by = (r[5] - pivotYmm) * mmUnit
        local bottomZ = r[6] * cmUnit
        local topZ = r[7] * cmUnit

        local la = CAD3D_ResolveHorizontalEdgeAtZV4 ep shapeNode ax ay lowerRefZ zTol
        local lb = CAD3D_ResolveHorizontalEdgeAtZV4 ep shapeNode bx by lowerRefZ zTol
        local ua = CAD3D_ResolveHorizontalEdgeAtZV4 ep shapeNode ax ay upperRefZ zTol
        local ub = CAD3D_ResolveHorizontalEdgeAtZV4 ep shapeNode bx by upperRefZ zTol

        if la[1] <= 0 or lb[1] <= 0 or ua[1] <= 0 or ub[1] <= 0 then
        (
            format "% PREFLIGHT FAILED: unresolved edge pair.\n" id
            return false
        )

        if la[1] == lb[1] or ua[1] == ub[1] then
        (
            format "% PREFLIGHT FAILED: jambs resolved to same edge.\n" id
            return false
        )

        append resolved #(id, la[1], lb[1], ua[1], ub[1], bottomZ, topZ)
        format "% PREFLIGHT OK | LOWER=%/% UPPER=%/% | BOTTOM=% TOP=%\n" id la[1] lb[1] ua[1] ub[1] r[6] r[7]
    )

    format "PREFLIGHT COMPLETE: % / %\n" resolved.count records.count

    -- D) move only each window's pair
    for r in resolved do
    (
        local id = r[1]
        local clearE = #{}

        local lowerEdges = #{}
        lowerEdges[r[2]] = true
        lowerEdges[r[3]] = true

        ep.SetSelection #Edge &clearE node:shapeNode
        ep.Select #Edge &lowerEdges select:true node:shapeNode
        ep.SetOperation #Transform
        ep.useSoftSel = false
        ep.MoveSelection [0,0,(r[6]-lowerRefZ)]
        ep.Commit()

        local upperEdges = #{}
        upperEdges[r[4]] = true
        upperEdges[r[5]] = true

        ep.SetSelection #Edge &clearE node:shapeNode
        ep.Select #Edge &upperEdges select:true node:shapeNode
        ep.SetOperation #Transform
        ep.useSoftSel = false
        ep.MoveSelection [0,0,(r[7]-upperRefZ)]
        ep.Commit()

        format "% MOVED | LOWER -> % cm | UPPER -> % cm\n" id (r[6]/cmUnit) (r[7]/cmUnit)
    )

    ep.RefreshScreen()
    completeRedraw()

    format "Windows moved: %\n" resolved.count
    format "Rule: TWO REFERENCE CONNECTS + PER-WINDOW JAMBS\n"
    format "Bridge: DISABLED\n"
    format "========================================\n"

    true
)
'''

    anchor = "\nfn CAD3D_OnTick"
    if anchor not in ms:
        raise RuntimeError(
            "3DCAD_BRIDGE.ms: CAD3D_OnTick anchor bulunamadi."
        )

    ms = ms.replace(
        anchor,
        helper + anchor,
        1,
    )

# Replace active old V3/V2/V1 call with V4.
if "CAD3D_WindowPairTopologyV4 shapeNode rows pivotX pivotY heightCm" not in ms:
    found = False

    for fn in (
        "CAD3D_ApplyConnectLevelsBatchV3",
        "CAD3D_ApplyConnectLevelsV2",
        "CAD3D_ApplyConnectLevelsV1",
    ):
        pattern = re.compile(
            rf'local\s+([A-Za-z0-9_]+)\s*=\s*{fn}\s+shapeNode\s+connectLevelsCm\s+heightCm'
        )
        m = pattern.search(ms)

        if m:
            var = m.group(1)
            replacement = (
                f"local {var} = "
                "CAD3D_WindowPairTopologyV4 "
                "shapeNode rows pivotX pivotY heightCm"
            )
            ms = (
                ms[:m.start()]
                + replacement
                + ms[m.end():]
            )
            found = True
            break

    if not found:
        anchor = "addModifier shapeNode extrudeMod"

        if anchor not in ms:
            raise RuntimeError(
                "3DCAD_BRIDGE.ms: Connect call veya Extrude anchor bulunamadi."
            )

        ms = ms.replace(
            anchor,
            anchor
            + '''
        local windowPairTopologyOK = CAD3D_WindowPairTopologyV4 shapeNode rows pivotX pivotY heightCm

        if windowPairTopologyOK != true then
        (
            format "3Dcad bridge: WINDOW PAIR TOPOLOGY V4 failed.\\n"
            delete shapeNode
            return false
        )''',
            1,
        )

# ============================================================
# VALIDATE BEFORE WRITE
# ============================================================

compile(runtime, str(SRC_RUNTIME), "exec")
compile(multi, str(SRC_MULTI), "exec")
compile(bridge, str(SRC_BRIDGE), "exec")

for token in (
    "fn CAD3D_WindowPairTopologyV4",
    "fn CAD3D_ReadWindowLevelRecordsV4",
    "CAD3D_WindowPairTopologyV4 shapeNode rows pivotX pivotY heightCm",
):
    if token not in ms:
        raise RuntimeError(
            "MaxScript validation failed: " + token
        )

# ============================================================
# WRITE
# ============================================================

write(SRC_RUNTIME, runtime)
write(SRC_MULTI, multi)
write(SRC_BRIDGE, bridge)
write(MAXSCRIPT, ms)

print("")
print("WINDOW_PAIR_TOPOLOGY_V4 INSTALLED")
print("")
print("CHANGED:")
print("  src/export/connect_levels_runtime.py")
print("  src/export/multi_floor_max_send.py")
print("  src/export/max_bridge.py")
print("  max/3DCAD_BRIDGE.ms")
print("")
print("BEHAVIOR:")
print("  Global unique facade Z Connect list DISABLED")
print("  Exactly 2 reference Connect bands")
print("  Per-window lower/upper jamb edge pair move ENABLED")
print("  Exact facade local Z preserved")
print("  Bridge/opening DISABLED")
print("")
print("UNCHANGED:")
print("  facade matching")
print("  door/window/wall detection")
print("  pivots / BASE_Z")
print("  UI / facade labels")
print("")
print("BACKUP:")
print(" ", BACKUP)
print("")
