from __future__ import annotations

from datetime import datetime
from pathlib import Path
import ast
import math
import re
import shutil

ROOT = Path.cwd()

FACADE = ROOT / "src" / "cad" / "facade_runtime.py"
VERTICAL = ROOT / "src" / "cad" / "vertical_opening_levels.py"
MULTI = ROOT / "src" / "export" / "multi_floor_max_send.py"
MAX_BRIDGE = ROOT / "src" / "export" / "max_bridge.py"
MAXSCRIPT = ROOT / "max" / "3DCAD_BRIDGE.ms"

FILES = (FACADE, MULTI, MAX_BRIDGE, MAXSCRIPT)
for path in FILES:
    if not path.is_file():
        raise RuntimeError(f"Gerekli dosya bulunamadı: {path}")

MARKER_VERTICAL = "VERTICAL_OPENING_LEVELS_V2"
MARKER_CONNECT = "CAD3D_VERTICAL_CONNECT_PIPELINE_V2"

vertical_module = r'''from __future__ import annotations

import math
from collections import defaultdict
from statistics import median

ENGINE = "VERTICAL_OPENING_LEVELS_V2"


def _num(value, default=None):
    try:
        result = float(value)
    except Exception:
        return default
    return result if math.isfinite(result) else default


def _int(value, default=None):
    try:
        return int(value)
    except Exception:
        return default


def _facade_number(row):
    return _int(row.get("facade_number"))


def _bottom(row):
    for key in ("elevation_bottom_y", "bottom_y", "y0"):
        value = _num(row.get(key))
        if value is not None:
            return value
    box = row.get("bbox")
    if isinstance(box, (tuple, list)) and len(box) >= 4:
        return _num(box[1])
    return None


def _top(row):
    for key in ("elevation_top_y", "top_y", "y1"):
        value = _num(row.get(key))
        if value is not None:
            return value
    box = row.get("bbox")
    if isinstance(box, (tuple, list)) and len(box) >= 4:
        return _num(box[3])
    bottom = _bottom(row)
    height = _num(row.get("elevation_height"))
    if bottom is not None and height is not None:
        return bottom + height
    return None


def _is_main_entrance(row):
    for key in ("is_main_entrance", "main_entrance", "is_main_door"):
        if row.get(key) is True:
            return True

    role = str(
        row.get("role", row.get("door_role", ""))
        or ""
    ).strip().casefold()

    return role in {
        "main_entrance",
        "main entrance",
        "entrance",
        "main_door",
        "main door",
    }


def _floor_key(row):
    name = str(row.get("floor_name", "") or "").strip()
    if name:
        return ("name", name)

    order = row.get("floor_order")
    if order is not None:
        return ("order", str(order))

    return ("unknown", "")


def _region_map(analysis):
    result = {}
    for region in analysis.get("regions", []) or []:
        if not isinstance(region, dict):
            continue
        region_id = region.get("region_id")
        if region_id is not None:
            result[str(region_id)] = region
    return result


def _facade_map(analysis):
    result = {}
    for facade in analysis.get("elevation_facades", []) or []:
        if not isinstance(facade, dict):
            continue
        number = _facade_number(facade)
        if number is not None:
            result[number] = facade
    return result


def _merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def _horizontal_levels(region_geometry, bbox, source_to_mm):
    from cad._cad_to_3d_max_facade.elevation_opening_detector import (
        _extract_axis_segments,
        _merge_horizontal,
    )

    if not (
        isinstance(bbox, (tuple, list))
        and len(bbox) == 4
    ):
        return []

    x0, y0, x1, y1 = (float(v) for v in bbox)
    width = max(x1 - x0, 1.0e-12)

    horizontal, _ = _extract_axis_segments(region_geometry)

    source_to_mm = max(float(source_to_mm), 1.0e-12)
    one_mm_source = 1.0 / source_to_mm

    horizontal = [
        row
        for row in horizontal
        if (
            float(row.get("x1", -1.0e30)) >= x0
            and float(row.get("x0", 1.0e30)) <= x1
            and y0 <= float(row.get("y", -1.0e30)) <= y1
        )
    ]

    if not horizontal:
        return []

    merged_rows = _merge_horizontal(
        horizontal,
        y_tolerance=max(one_mm_source, 1.0e-9),
        gap_tolerance=max(one_mm_source * 2.0, 1.0e-9),
    )

    groups = []

    for row in sorted(merged_rows, key=lambda item: float(item["y"])):
        y = float(row["y"])
        sx0 = max(x0, float(row["x0"]))
        sx1 = min(x1, float(row["x1"]))
        if sx1 <= sx0:
            continue

        group = None
        for candidate in groups:
            if abs(float(candidate["y"]) - y) <= one_mm_source:
                group = candidate
                break

        if group is None:
            group = {"y": y, "ys": [], "intervals": []}
            groups.append(group)

        group["ys"].append(y)
        group["intervals"].append((sx0, sx1))
        group["y"] = sum(group["ys"]) / len(group["ys"])

    levels = []

    for group in groups:
        intervals = _merge_intervals(group["intervals"])
        union_length = sum(end - start for start, end in intervals)
        longest = max((end - start for start, end in intervals), default=0.0)

        levels.append(
            {
                "y": float(group["y"]),
                "coverage": float(union_length / width),
                "longest_ratio": float(longest / width),
                "segment_count": int(len(intervals)),
            }
        )

    return levels


def _best_structural_level(levels):
    if not levels:
        return None

    return max(
        levels,
        key=lambda row: (
            float(row.get("coverage", 0.0)),
            float(row.get("longest_ratio", 0.0)),
            float(row.get("y", -1.0e30)),
        ),
    )


def _floor_groups(rows):
    grouped = defaultdict(list)

    for row in rows:
        grouped[_floor_key(row)].append(row)

    result = []

    for _, items in grouped.items():
        bottoms = [_bottom(row) for row in items]
        tops = [_top(row) for row in items]
        bottoms = [v for v in bottoms if v is not None]
        tops = [v for v in tops if v is not None]

        if not bottoms or not tops:
            continue

        result.append(
            {
                "floor_name": str(items[0].get("floor_name", "") or "").strip(),
                "floor_order": items[0].get("floor_order"),
                "rows": items,
                "bottom_min": min(bottoms),
                "bottom_median": float(median(bottoms)),
                "top_max": max(tops),
            }
        )

    result.sort(key=lambda row: float(row["bottom_median"]))
    return result


def _door_pairs(analysis, facade_number):
    rows = []

    for match in analysis.get("matches", []) or []:
        if not isinstance(match, dict):
            continue

        if _facade_number(match) != facade_number:
            continue

        for pair in match.get("opening_pairs", []) or []:
            if not isinstance(pair, dict):
                continue

            kind = str(pair.get("kind", "") or "").strip().casefold()
            if "door" not in kind:
                continue

            bottom = _bottom(pair)
            top = _top(pair)

            if bottom is None or top is None or top <= bottom:
                continue

            rows.append(pair)

    return rows


def _ground_datum(levels, floor_group, doors):
    main_doors = [row for row in doors if _is_main_entrance(row)]

    if main_doors:
        bottom = _bottom(main_doors[0])
        if bottom is not None:
            return {
                "y": float(bottom),
                "source": "MAIN_ENTRANCE_DOOR_BOTTOM",
            }

    lowest_window_y = float(floor_group["bottom_min"])

    candidates = [
        row
        for row in levels
        if float(row["y"]) < lowest_window_y
    ]

    best = _best_structural_level(candidates)

    if best is None:
        return None

    return {
        "y": float(best["y"]),
        "source": "STRONGEST_HORIZONTAL_LEVEL_BELOW_GROUND_WINDOWS",
    }


def _upper_datum(levels, previous_floor, current_floor):
    previous_top = float(previous_floor["top_max"])
    current_bottom = float(current_floor["bottom_min"])

    candidates = [
        row
        for row in levels
        if previous_top < float(row["y"]) < current_bottom
    ]

    best = _best_structural_level(candidates)

    if best is None:
        return None

    return {
        "y": float(best["y"]),
        "source": "STRONGEST_HORIZONTAL_LEVEL_BETWEEN_STOREYS",
    }


def _attach_windows(floor_group, datum_y, source_to_mm, source):
    count = 0

    for row in floor_group["rows"]:
        bottom = _bottom(row)
        top = _top(row)

        if bottom is None or top is None or top <= bottom:
            continue

        bottom_cm = (bottom - datum_y) * source_to_mm / 10.0
        top_cm = (top - datum_y) * source_to_mm / 10.0
        height_cm = (top - bottom) * source_to_mm / 10.0

        row["floor_datum_y"] = float(datum_y)
        row["window_bottom_local_z_cm"] = float(bottom_cm)
        row["window_top_local_z_cm"] = float(top_cm)
        row["window_height_cm"] = float(height_cm)
        row["vertical_level_source"] = source

        count += 1

    return count


def _attach_doors(analysis, floor_datums, source_to_mm):
    count = 0

    for match in analysis.get("matches", []) or []:
        if not isinstance(match, dict):
            continue

        facade_number = _facade_number(match)
        datums = floor_datums.get(facade_number, [])

        if not datums:
            continue

        datums = sorted(datums, key=lambda row: float(row["datum_y"]))

        for pair in match.get("opening_pairs", []) or []:
            if not isinstance(pair, dict):
                continue

            kind = str(pair.get("kind", "") or "").strip().casefold()
            if "door" not in kind:
                continue

            bottom = _bottom(pair)
            top = _top(pair)

            if bottom is None or top is None or top <= bottom:
                continue

            below = [
                row
                for row in datums
                if float(row["datum_y"]) <= float(bottom)
            ]

            if below:
                floor_row = below[-1]
            else:
                floor_row = min(
                    datums,
                    key=lambda row: abs(float(row["datum_y"]) - float(bottom)),
                )

            datum_y = float(floor_row["datum_y"])

            pair["floor_name"] = str(floor_row.get("floor_name", "") or "")
            pair["floor_datum_y"] = datum_y
            pair["door_bottom_local_z_cm"] = (
                (bottom - datum_y) * source_to_mm / 10.0
            )
            pair["door_top_local_z_cm"] = (
                (top - datum_y) * source_to_mm / 10.0
            )
            pair["door_height_cm"] = (
                (top - bottom) * source_to_mm / 10.0
            )
            pair["vertical_level_source"] = str(
                floor_row.get("source", "") or ""
            )

            count += 1

    return count


def attach_vertical_opening_levels(window, analysis):
    if not isinstance(analysis, dict):
        return analysis

    rows = [
        row
        for row in (
            analysis.get("plan_guided_facade_windows", [])
            or []
        )
        if isinstance(row, dict)
    ]

    full_document = getattr(window, "_full_document", None)

    if full_document is None:
        raise RuntimeError("VERTICAL_LEVELS_FULL_DOCUMENT_MISSING")

    from export.max_bridge import _source_to_mm

    source_to_mm = float(_source_to_mm(full_document))

    if not math.isfinite(source_to_mm) or source_to_mm <= 0.0:
        raise RuntimeError("VERTICAL_LEVELS_SOURCE_SCALE_INVALID")

    if not rows:
        analysis["vertical_opening_levels"] = {
            "engine": ENGINE,
            "source_to_mm": source_to_mm,
            "window_count": 0,
            "door_count": 0,
            "floor_datums": [],
            "unresolved": [],
        }
        return analysis

    facades = _facade_map(analysis)
    regions = _region_map(analysis)

    rows_by_facade = defaultdict(list)

    for row in rows:
        number = _facade_number(row)
        if number is not None:
            rows_by_facade[number].append(row)

    floor_datums = defaultdict(list)
    summary_datums = []
    unresolved = []
    window_count = 0

    for facade_number, facade_rows in sorted(rows_by_facade.items()):
        facade = facades.get(facade_number)

        if not isinstance(facade, dict):
            unresolved.append(
                {
                    "facade_number": facade_number,
                    "reason": "FACADE_NOT_FOUND",
                }
            )
            continue

        region_id = str(facade.get("region_id", "") or "")
        region = regions.get(region_id)

        if not isinstance(region, dict):
            unresolved.append(
                {
                    "facade_number": facade_number,
                    "reason": "FACADE_REGION_NOT_FOUND",
                }
            )
            continue

        region_geometry = list(region.get("geometry", []) or [])

        if not region_geometry:
            unresolved.append(
                {
                    "facade_number": facade_number,
                    "reason": "FACADE_REGION_GEOMETRY_EMPTY",
                }
            )
            continue

        levels = _horizontal_levels(
            region_geometry,
            facade.get("bbox"),
            source_to_mm,
        )

        if not levels:
            unresolved.append(
                {
                    "facade_number": facade_number,
                    "reason": "HORIZONTAL_LEVEL_NOT_FOUND",
                }
            )
            continue

        groups = _floor_groups(facade_rows)

        if not groups:
            unresolved.append(
                {
                    "facade_number": facade_number,
                    "reason": "FLOOR_WINDOW_GROUP_NOT_FOUND",
                }
            )
            continue

        doors = _door_pairs(analysis, facade_number)
        previous = None

        for index, floor_group in enumerate(groups):
            if index == 0:
                datum = _ground_datum(
                    levels,
                    floor_group,
                    doors,
                )
            else:
                datum = _upper_datum(
                    levels,
                    previous,
                    floor_group,
                )

            if datum is None:
                unresolved.append(
                    {
                        "facade_number": facade_number,
                        "floor_name": floor_group.get("floor_name", ""),
                        "reason": (
                            "GROUND_DATUM_NOT_FOUND"
                            if index == 0
                            else "UPPER_DATUM_NOT_FOUND"
                        ),
                    }
                )
                previous = floor_group
                continue

            datum_y = float(datum["y"])
            source = str(datum["source"])

            attached = _attach_windows(
                floor_group,
                datum_y,
                source_to_mm,
                source,
            )

            window_count += attached

            record = {
                "facade_number": facade_number,
                "floor_name": floor_group.get("floor_name", ""),
                "floor_order": floor_group.get("floor_order"),
                "datum_y": datum_y,
                "source": source,
                "window_count": attached,
            }

            floor_datums[facade_number].append(record)
            summary_datums.append(record)
            previous = floor_group

    door_count = _attach_doors(
        analysis,
        floor_datums,
        source_to_mm,
    )

    analysis["vertical_opening_levels"] = {
        "engine": ENGINE,
        "source_to_mm": source_to_mm,
        "window_count": int(window_count),
        "door_count": int(door_count),
        "floor_datums": summary_datums,
        "unresolved": unresolved,
    }

    print("")
    print("=== 3DCAD VERTICAL OPENING LEVELS V2 ===")
    print("SOURCE_TO_MM:", source_to_mm)
    print("WINDOW LEVELS:", window_count)
    print("DOOR LEVELS:", door_count)
    print("FLOOR DATUMS:", len(summary_datums))
    print("UNRESOLVED:", len(unresolved))
    print("========================================")
    print("")

    return analysis
'''


def read(path):
    return path.read_text(encoding="utf-8-sig")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: beklenen 1 eşleşme, bulunan {count}. Dosyalar değiştirilmedi."
        )
    return text.replace(old, new, 1)


facade_text = read(FACADE)
multi_text = read(MULTI)
bridge_text = read(MAX_BRIDGE)
ms_text = read(MAXSCRIPT)

if MARKER_VERTICAL not in facade_text:
    anchor = '''    result = (
        _rewrite_source_metadata(
            result
        )
    )
'''

    insertion = anchor + '''
    # VERTICAL_OPENING_LEVELS_V2
    from cad.vertical_opening_levels import (
        attach_vertical_opening_levels,
    )

    result = attach_vertical_opening_levels(
        window,
        result,
    )
'''

    facade_text = replace_once(
        facade_text,
        anchor,
        insertion,
        "facade_runtime vertical binding",
    )

if MARKER_CONNECT not in multi_text:
    old_package = '''        "walls":
            walls,

        "bounds":
            bounds,
'''

    new_package = '''        "walls":
            walls,

        # CAD3D_VERTICAL_CONNECT_PIPELINE_V2
        "doors":
            doors,

        "windows":
            windows,

        "bounds":
            bounds,
'''

    multi_text = replace_once(
        multi_text,
        old_package,
        new_package,
        "multi-floor package doors/windows",
    )

    collector = r'''

# CAD3D_VERTICAL_CONNECT_PIPELINE_V2
def _cad3d_collect_connect_levels(
    window,
    package,
):
    import math

    from cad.facade_runtime import (
        refresh_facade_matches,
    )

    analysis = refresh_facade_matches(
        window
    )

    if not isinstance(
        analysis,
        dict,
    ):
        raise RuntimeError(
            "Cephe dikey kot sonucu alınamadı."
        )

    floor_name = str(
        package.get(
            "floor_name",
            "",
        )
        or ""
    ).strip()

    wall_height_cm = float(
        package.get(
            "wall_height_cm",
            0.0,
        )
        or 0.0
    )

    if not floor_name:
        raise RuntimeError(
            "Connect için kat adı eksik."
        )

    if (
        not math.isfinite(
            wall_height_cm
        )
        or wall_height_cm <= 0.0
    ):
        raise RuntimeError(
            floor_name
            + ": duvar yüksekliği geçersiz."
        )

    levels = []
    matched_windows = 0
    missing_windows = 0
    door_tops = 0

    for row in (
        analysis.get(
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

        if str(
            row.get(
                "floor_name",
                "",
            )
            or ""
        ).strip() != floor_name:
            continue

        matched_windows += 1

        bottom = row.get(
            "window_bottom_local_z_cm"
        )
        top = row.get(
            "window_top_local_z_cm"
        )

        try:
            bottom = float(
                bottom
            )
            top = float(
                top
            )
        except (
            TypeError,
            ValueError,
        ):
            missing_windows += 1
            continue

        if (
            not math.isfinite(
                bottom
            )
            or not math.isfinite(
                top
            )
            or top <= bottom
        ):
            missing_windows += 1
            continue

        levels.extend(
            (
                bottom,
                top,
            )
        )

    if missing_windows > 0:
        raise RuntimeError(
            floor_name
            + ": "
            + str(
                missing_windows
            )
            + " pencerenin cephe-local Z değeri üretilemedi."
        )

    for match in (
        analysis.get(
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

            kind = str(
                pair.get(
                    "kind",
                    "",
                )
                or ""
            ).strip().casefold()

            if "door" not in kind:
                continue

            if str(
                pair.get(
                    "floor_name",
                    "",
                )
                or ""
            ).strip() != floor_name:
                continue

            try:
                top = float(
                    pair.get(
                        "door_top_local_z_cm"
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if not math.isfinite(
                top
            ):
                continue

            levels.append(
                top
            )
            door_tops += 1

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
            float(
                key
            )
        )

    normalized.sort()

    expected_windows = len(
        package.get(
            "windows",
            (),
        )
        or ()
    )

    if (
        expected_windows > 0
        and matched_windows <= 0
    ):
        raise RuntimeError(
            floor_name
            + ": plan pencereleri ile cephe pencereleri arasında Connect kotu bulunamadı."
        )

    print("")
    print("=== 3DCAD CONNECT LEVELS V2 ===")
    print("FLOOR:", floor_name)
    print("PLAN WINDOWS:", expected_windows)
    print("FACADE WINDOWS:", matched_windows)
    print("DOOR TOPS:", door_tops)
    print("CONNECT LEVELS CM:", normalized)
    print("================================")
    print("")

    return tuple(
        normalized
    )
'''

    if "def _send_next_floor(\n" not in multi_text:
        raise RuntimeError(
            "multi_floor_max_send.py içinde _send_next_floor bulunamadı."
        )

    multi_text = multi_text.replace(
        "def _send_next_floor(\n",
        collector + "\ndef _send_next_floor(\n",
        1,
    )

    send_anchor = '''    try:
        result = send_wall_lines_to_max(
'''

    send_insert = '''    connect_levels_cm = (
        _cad3d_collect_connect_levels(
            window,
            package,
        )
    )

    try:
        result = send_wall_lines_to_max(
'''

    multi_text = replace_once(
        multi_text,
        send_anchor,
        send_insert,
        "multi-floor connect collector call",
    )

    pivot_anchor = '''            pivot_source=(
                package[
                    "pivot_source"
                ]
            ),
        )
'''

    pivot_new = '''            pivot_source=(
                package[
                    "pivot_source"
                ]
            ),
            connect_levels_cm=(
                connect_levels_cm
            ),
        )
'''

    multi_text = replace_once(
        multi_text,
        pivot_anchor,
        pivot_new,
        "multi-floor connect argument",
    )

if MARKER_CONNECT not in bridge_text:
    signature_old = '''    interfloor_cm=0.0,
    pivot_source=None,
):
'''

    signature_new = '''    interfloor_cm=0.0,
    pivot_source=None,
    connect_levels_cm=None,
):
'''

    bridge_text = replace_once(
        bridge_text,
        signature_old,
        signature_new,
        "max_bridge signature",
    )

    serializer = r'''
    # CAD3D_VERTICAL_CONNECT_PIPELINE_V2
    normalized_connect_levels = []

    if is_floor_request:
        seen_connect_levels = set()

        for raw_level in (
            connect_levels_cm
            or ()
        ):
            try:
                level = float(
                    raw_level
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if not math.isfinite(
                level
            ):
                continue

            if not (
                0.0
                < level
                < float(
                    wall_height_cm
                )
            ):
                continue

            key = round(
                level,
                6,
            )

            if key in seen_connect_levels:
                continue

            seen_connect_levels.add(
                key
            )
            normalized_connect_levels.append(
                float(
                    key
                )
            )

        normalized_connect_levels.sort()

        lines.append(
            "CONNECT_LEVEL_COUNT="
            + str(
                len(
                    normalized_connect_levels
                )
            )
        )

        for level in normalized_connect_levels:
            lines.append(
                "CONNECT_LEVEL_CM="
                + repr(
                    float(
                        level
                    )
                )
            )

'''

    if "    sent_count = 0\n" not in bridge_text:
        raise RuntimeError(
            "max_bridge.py içinde request yazım noktası bulunamadı."
        )

    bridge_text = bridge_text.replace(
        "    sent_count = 0\n",
        serializer + "    sent_count = 0\n",
        1,
    )

if MARKER_CONNECT not in ms_text:
    helpers = r'''

-- ============================================================
-- CAD3D_VERTICAL_CONNECT_PIPELINE_V2
-- CONNECT_LEVEL_CM comes from Python/CAD facade analysis.
-- BASE_Z is NOT added here. Targets are floor-local Z.
-- ============================================================

fn CAD3D_ReadConnectLevelsV2 filePath =
(
    local values = #()
    local stream = openFile filePath mode:"rt"

    if stream == undefined then return values

    while not eof stream do
    (
        local line = readLine stream

        if line != undefined do
        (
            if matchPattern line pattern:"CONNECT_LEVEL_CM=*" do
            (
                if line.count > 17 do
                (
                    local textValue = substring line 18 (line.count - 17)
                    local numberValue = undefined

                    try
                    (
                        numberValue = textValue as float
                    )
                    catch
                    (
                        numberValue = undefined
                    )

                    if numberValue != undefined do append values numberValue
                )
            )
        )
    )

    close stream
    sort values

    local uniqueValues = #()

    for value in values do
    (
        if uniqueValues.count == 0 then
        (
            append uniqueValues value
        )
        else
        (
            if (abs (value - uniqueValues[uniqueValues.count])) > 0.000001 do
            (
                append uniqueValues value
            )
        )
    )

    uniqueValues
)


fn CAD3D_ConnectOneLevelV2 editPolyMod shapeNode targetCm wallHeightCm =
(
    local cmUnit = units.decodeValue "1cm"
    local targetZ = targetCm * cmUnit
    local wallTopZ = wallHeightCm * cmUnit

    local xyTolerance = units.decodeValue "0.01mm"
    local zTolerance = units.decodeValue "0.5mm"
    local minVerticalLength = units.decodeValue "1mm"
    local minHorizontalLength = units.decodeValue "1mm"

    if targetZ <= zTolerance then return true
    if targetZ >= (wallTopZ - zTolerance) then return true

    local edgeCountBefore = editPolyMod.GetNumEdges node:shapeNode
    local verticalEdges = #{}

    for edgeIndex = 1 to edgeCountBefore do
    (
        local vertexA = editPolyMod.GetEdgeVertex edgeIndex 1 node:shapeNode
        local vertexB = editPolyMod.GetEdgeVertex edgeIndex 2 node:shapeNode

        if ((vertexA > 0) and (vertexB > 0)) do
        (
            local pointA = editPolyMod.GetVertex vertexA node:shapeNode
            local pointB = editPolyMod.GetVertex vertexB node:shapeNode

            local dx = abs (pointB.x - pointA.x)
            local dy = abs (pointB.y - pointA.y)
            local dz = abs (pointB.z - pointA.z)

            if ((dz > minVerticalLength) and (dx <= xyTolerance) and (dy <= xyTolerance)) do
            (
                local zMin = amin pointA.z pointB.z
                local zMax = amax pointA.z pointB.z

                if ((targetZ > (zMin + zTolerance)) and (targetZ < (zMax - zTolerance))) do
                (
                    verticalEdges[edgeIndex] = true
                )
            )
        )
    )

    if verticalEdges.numberSet <= 0 then
    (
        format "3Dcad Connect ERROR | target=% cm | no vertical span\n" targetCm
        return false
    )

    local setVertical = verticalEdges
    editPolyMod.SetSelection #Edge &setVertical node:shapeNode
    editPolyMod.connectEdgeSegments = 1
    editPolyMod.connectEdgePinch = 0
    editPolyMod.connectEdgeSlide = 0
    editPolyMod.ButtonOp #ConnectEdges
    editPolyMod.RefreshScreen()
    completeRedraw()

    local edgeCountAfter = editPolyMod.GetNumEdges node:shapeNode

    if edgeCountAfter <= edgeCountBefore then
    (
        format "3Dcad Connect ERROR | target=% cm | topology not created\n" targetCm
        return false
    )

    local newHorizontalEdges = #{}
    local minZ = 1.0e30
    local maxZ = -1.0e30

    for edgeIndex = (edgeCountBefore + 1) to edgeCountAfter do
    (
        local vertexA = editPolyMod.GetEdgeVertex edgeIndex 1 node:shapeNode
        local vertexB = editPolyMod.GetEdgeVertex edgeIndex 2 node:shapeNode

        if ((vertexA > 0) and (vertexB > 0)) do
        (
            local pointA = editPolyMod.GetVertex vertexA node:shapeNode
            local pointB = editPolyMod.GetVertex vertexB node:shapeNode

            local dx = pointB.x - pointA.x
            local dy = pointB.y - pointA.y
            local dz = abs (pointB.z - pointA.z)
            local horizontalLength = sqrt ((dx * dx) + (dy * dy))

            if ((dz <= zTolerance) and (horizontalLength > minHorizontalLength)) do
            (
                newHorizontalEdges[edgeIndex] = true

                if pointA.z < minZ do minZ = pointA.z
                if pointA.z > maxZ do maxZ = pointA.z
                if pointB.z < minZ do minZ = pointB.z
                if pointB.z > maxZ do maxZ = pointB.z
            )
        )
    )

    if newHorizontalEdges.numberSet <= 0 then
    (
        format "3Dcad Connect ERROR | target=% cm | new horizontal edges not found\n" targetCm
        return false
    )

    if (maxZ - minZ) > zTolerance then
    (
        format "3Dcad Connect ERROR | target=% cm | generated edges have mixed Z\n" targetCm
        return false
    )

    local generatedZ = (minZ + maxZ) * 0.5
    local deltaZ = targetZ - generatedZ

    local setHorizontal = newHorizontalEdges
    editPolyMod.SetSelection #Edge &setHorizontal node:shapeNode
    editPolyMod.useSoftSel = false

    local deltaVector = [0,0,deltaZ]
    editPolyMod.MoveSelection &deltaVector

    editPolyMod.RefreshScreen()
    completeRedraw()

    local finalOK = true

    for edgeIndex = 1 to edgeCountAfter while finalOK do
    (
        if newHorizontalEdges[edgeIndex] do
        (
            local vertexA = editPolyMod.GetEdgeVertex edgeIndex 1 node:shapeNode
            local vertexB = editPolyMod.GetEdgeVertex edgeIndex 2 node:shapeNode
            local pointA = editPolyMod.GetVertex vertexA node:shapeNode
            local pointB = editPolyMod.GetVertex vertexB node:shapeNode

            if (abs (pointA.z - targetZ)) > zTolerance do finalOK = false
            if (abs (pointB.z - targetZ)) > zTolerance do finalOK = false
        )
    )

    if finalOK != true then
    (
        format "3Dcad Connect ERROR | target=% cm | final Z verification failed\n" targetCm
        return false
    )

    format "3Dcad Connect moved | target=% cm | generated=% | delta=% | edges=%\n" targetCm generatedZ deltaZ newHorizontalEdges.numberSet

    true
)


fn CAD3D_ConnectLevelsV2 shapeNode connectLevels wallHeightCm =
(
    if connectLevels.count <= 0 then return true

    local editPolyMod = Edit_Poly()
    addModifier shapeNode editPolyMod

    max modify mode
    select shapeNode
    modPanel.setCurrentObject editPolyMod
    editPolyMod.selectMode = 1
    editPolyMod.SetEPolySelLevel #Edge
    subObjectLevel = 2

    editPolyMod.RefreshScreen()
    completeRedraw()

    format "\n========================================\n"
    format "3DCAD VERTICAL CONNECT PIPELINE V2\n"
    format "Connect levels: %\n" connectLevels

    for targetCm in connectLevels do
    (
        local levelOK = CAD3D_ConnectOneLevelV2 editPolyMod shapeNode targetCm wallHeightCm

        if levelOK != true then
        (
            format "Connect failed at % cm\n" targetCm
            format "========================================\n"
            return false
        )
    )

    format "Connect levels completed: %\n" connectLevels.count
    format "========================================\n\n"

    true
)


'''

    if "fn CAD3D_ImportWalls filePath =" not in ms_text:
        raise RuntimeError(
            "3DCAD_BRIDGE.ms içinde CAD3D_ImportWalls bulunamadı."
        )

    ms_text = ms_text.replace(
        "fn CAD3D_ImportWalls filePath =",
        helpers + "fn CAD3D_ImportWalls filePath =",
        1,
    )

    extrude_pattern = re.compile(
        r'(?P<block>'
        r'(?P<indent>[ \t]*)addModifier shapeNode extrudeMod[ \t]*\r?\n'
        r'(?:[ \t]*\r?\n)?'
        r'(?P=indent)format "3Dcad Extrude added \| height=% cm \| segments=1 \| caps=ON\\n" heightCm[ \t]*\r?\n'
        r')'
    )

    match = extrude_pattern.search(ms_text)

    if match is None:
        raise RuntimeError(
            "3DCAD_BRIDGE.ms içinde Extrude bağlama noktası bulunamadı."
        )

    indent = match.group("indent")

    connect_block = (
        match.group("block")
        + "\n"
        + indent + "-- CAD3D_VERTICAL_CONNECT_PIPELINE_V2\n"
        + indent + "local connectLevelsCm = CAD3D_ReadConnectLevelsV2 filePath\n"
        + "\n"
        + indent + "if connectLevelsCm.count > 0 then\n"
        + indent + "(\n"
        + indent + "    local connectOK = CAD3D_ConnectLevelsV2 shapeNode connectLevelsCm heightCm\n"
        + "\n"
        + indent + "    if connectOK != true then\n"
        + indent + "    (\n"
        + indent + "        delete shapeNode\n"
        + indent + "        format \"3Dcad bridge: vertical Connect failed.\\n\"\n"
        + indent + "        return false\n"
        + indent + "    )\n"
        + indent + ")\n"
    )

    ms_text = (
        ms_text[:match.start()]
        + connect_block
        + ms_text[match.end():]
    )

compile(vertical_module, str(VERTICAL), "exec")
ast.parse(facade_text)
ast.parse(multi_text)
ast.parse(bridge_text)

required_checks = (
    (facade_text, MARKER_VERTICAL, "facade_runtime vertical marker"),
    (multi_text, MARKER_CONNECT, "multi-floor marker"),
    (bridge_text, MARKER_CONNECT, "max_bridge marker"),
    (ms_text, MARKER_CONNECT, "MaxScript marker"),
    (bridge_text, "CONNECT_LEVEL_CM=", "request serializer"),
    (multi_text, "connect_levels_cm=(", "multi-floor sender"),
    (ms_text, "CAD3D_ConnectLevelsV2", "Max Connect function"),
)

for text, needle, label in required_checks:
    if needle not in text:
        raise RuntimeError(
            f"{label} doğrulaması başarısız. Dosyalar değiştirilmedi."
        )

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = (
    ROOT
    / "geliştirmeler"
    / "backups"
    / f"CONNECT_PIPELINE_V2_{stamp}"
)
backup_dir.mkdir(parents=True, exist_ok=True)

for path in FILES:
    shutil.copy2(
        path,
        backup_dir / path.name,
    )

if VERTICAL.exists():
    shutil.copy2(
        VERTICAL,
        backup_dir / "vertical_opening_levels.py",
    )

VERTICAL.write_text(
    vertical_module,
    encoding="utf-8",
)
FACADE.write_text(
    facade_text,
    encoding="utf-8",
)
MULTI.write_text(
    multi_text,
    encoding="utf-8",
)
MAX_BRIDGE.write_text(
    bridge_text,
    encoding="utf-8",
)
MAXSCRIPT.write_text(
    ms_text,
    encoding="utf-8",
)

try:
    compile(
        VERTICAL.read_text(encoding="utf-8-sig"),
        str(VERTICAL),
        "exec",
    )
    compile(
        FACADE.read_text(encoding="utf-8-sig"),
        str(FACADE),
        "exec",
    )
    compile(
        MULTI.read_text(encoding="utf-8-sig"),
        str(MULTI),
        "exec",
    )
    compile(
        MAX_BRIDGE.read_text(encoding="utf-8-sig"),
        str(MAX_BRIDGE),
        "exec",
    )
except Exception:
    for path in FILES:
        shutil.copy2(
            backup_dir / path.name,
            path,
        )

    old_vertical = backup_dir / "vertical_opening_levels.py"

    if old_vertical.exists():
        shutil.copy2(
            old_vertical,
            VERTICAL,
        )
    elif VERTICAL.exists():
        VERTICAL.unlink()

    raise

print("")
print("CONNECT_PIPELINE_V2 INSTALLED")
print("")
print("PIPELINE:")
print("  facade CAD geometry")
print("  -> floor-local opening Z")
print("  -> CONNECT_LEVEL_CM")
print("  -> Extrude")
print("  -> Edit Poly")
print("  -> Connect")
print("  -> exact local Z move")
print("")
print("NO FIXED 90/210/300/315/335 CM OPENING VALUES ADDED")
print("BASE_Z remains world placement only")
print("NO Bridge / hole opening operation added")
print("")
print("BACKUP:")
print(" ", backup_dir)
print("")
print("RELOAD MAXSCRIPT:")
print(r'  fileIn @"C:\Users\yildi\Desktop\3Dcad\max\3DCAD_BRIDGE.ms"')
print("")
