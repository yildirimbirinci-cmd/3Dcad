from __future__ import annotations

import ast
import shutil
from datetime import datetime
from pathlib import Path

ENGINE = "VERTICAL_OPENING_LEVELS_V1"
ROOT = Path.cwd()
FACADE_RUNTIME = ROOT / "src" / "cad" / "facade_runtime.py"
TARGET = ROOT / "src" / "cad" / "vertical_opening_levels.py"

MODULE_TEXT = r'''from __future__ import annotations

import math
from collections import defaultdict
from statistics import median

ENGINE = "VERTICAL_OPENING_LEVELS_V1"


def _number(value, default=None):
    try:
        result = float(value)
    except Exception:
        return default

    if not math.isfinite(result):
        return default

    return result


def _integer(value, default=None):
    try:
        return int(value)
    except Exception:
        return default


def _floor_key(row):
    name = str(row.get("floor_name", "") or "").strip()
    if name:
        return ("name", name)

    order = row.get("floor_order")
    if order is not None:
        return ("order", str(order))

    return ("unknown", "")


def _facade_number(row):
    return _integer(row.get("facade_number"))


def _pair_bottom(row):
    for key in (
        "elevation_bottom_y",
        "bottom_y",
        "y0",
    ):
        value = _number(row.get(key))
        if value is not None:
            return value

    box = row.get("bbox")
    if isinstance(box, (tuple, list)) and len(box) >= 4:
        return _number(box[1])

    return None


def _pair_top(row):
    for key in (
        "elevation_top_y",
        "top_y",
        "y1",
    ):
        value = _number(row.get(key))
        if value is not None:
            return value

    box = row.get("bbox")
    if isinstance(box, (tuple, list)) and len(box) >= 4:
        return _number(box[3])

    bottom = _pair_bottom(row)
    height = _number(row.get("elevation_height"))
    if bottom is not None and height is not None:
        return bottom + height

    return None


def _main_door_flag(row):
    for key in (
        "is_main_entrance",
        "main_entrance",
        "is_main_door",
    ):
        value = row.get(key)
        if value is True:
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


def _door_width(row):
    for key in (
        "plan_width",
        "width",
        "elevation_width",
    ):
        value = _number(row.get(key))
        if value is not None and value > 0.0:
            return value

    return 0.0


def _door_pairs_for_facade(analysis, facade_number):
    rows = []

    for match in analysis.get("matches", []) or []:
        if not isinstance(match, dict):
            continue

        if _facade_number(match) != facade_number:
            continue

        for pair in match.get("opening_pairs", []) or []:
            if not isinstance(pair, dict):
                continue

            if str(pair.get("kind", "") or "").strip().casefold() != "door":
                continue

            bottom = _pair_bottom(pair)
            top = _pair_top(pair)

            if bottom is None or top is None or top <= bottom:
                continue

            rows.append(pair)

    return rows


def _choose_ground_door(doors):
    if not doors:
        return None

    explicit = [row for row in doors if _main_door_flag(row)]
    pool = explicit if explicit else doors

    return max(
        pool,
        key=lambda row: (
            _door_width(row),
            -float(_pair_bottom(row) or 0.0),
        ),
    )


def _facade_map(analysis):
    result = {}

    for facade in analysis.get("elevation_facades", []) or []:
        if not isinstance(facade, dict):
            continue

        number = _facade_number(facade)
        if number is not None:
            result[number] = facade

    return result


def _group_horizontal_levels(horizontal, y_tolerance, x0, x1):
    facade_width = max(float(x1) - float(x0), 1.0e-9)
    groups = []

    for row in sorted(horizontal, key=lambda item: float(item["y"])):
        y = float(row["y"])
        lx0 = max(float(x0), float(row["x0"]))
        lx1 = min(float(x1), float(row["x1"]))

        if lx1 <= lx0:
            continue

        target = None
        for group in groups:
            if abs(float(group["y"]) - y) <= y_tolerance:
                target = group
                break

        if target is None:
            target = {"y": y, "intervals": []}
            groups.append(target)

        target["intervals"].append((lx0, lx1))
        target["y"] = sum(
            float(item["y"])
            for item in target.get("_rows", []) + [row]
        ) / float(len(target.get("_rows", [])) + 1)
        target.setdefault("_rows", []).append(row)

    levels = []

    for group in groups:
        intervals = sorted(group["intervals"])
        merged = []

        for start, end in intervals:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)

        union_length = sum(end - start for start, end in merged)
        longest = max((end - start for start, end in merged), default=0.0)

        levels.append(
            {
                "y": float(group["y"]),
                "coverage": float(union_length / facade_width),
                "longest_ratio": float(longest / facade_width),
                "segment_count": int(len(merged)),
            }
        )

    return levels


def _horizontal_levels_for_facade(geometry, bbox, source_to_mm):
    from cad._cad_to_3d_max_facade.elevation_opening_detector import (
        _extract_axis_segments,
        _merge_horizontal,
    )

    if not (
        isinstance(bbox, (tuple, list))
        and len(bbox) == 4
    ):
        return []

    x0, y0, x1, y1 = [float(value) for value in bbox]

    raw_horizontal, _ = _extract_axis_segments(geometry)
    raw_horizontal = [
        row
        for row in raw_horizontal
        if (
            float(row.get("x1", -1.0e30)) >= x0
            and float(row.get("x0", 1.0e30)) <= x1
            and y0 <= float(row.get("y", -1.0e30)) <= y1
        )
    ]

    if not raw_horizontal:
        return []

    # Pure numerical cleanup tolerance: 1 mm in source drawing units.
    source_to_mm = max(float(source_to_mm), 1.0e-12)
    one_mm_source = 1.0 / source_to_mm

    merged = _merge_horizontal(
        raw_horizontal,
        y_tolerance=max(one_mm_source, 1.0e-9),
        gap_tolerance=max(one_mm_source * 2.0, 1.0e-9),
    )

    return _group_horizontal_levels(
        merged,
        max(one_mm_source, 1.0e-9),
        x0,
        x1,
    )


def _best_level(levels):
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


def _floor_groups_for_facade(rows):
    grouped = defaultdict(list)

    for row in rows:
        grouped[_floor_key(row)].append(row)

    result = []

    for key, items in grouped.items():
        bottoms = [
            _number(item.get("elevation_bottom_y"))
            for item in items
        ]
        tops = [
            _number(item.get("elevation_top_y"))
            for item in items
        ]

        bottoms = [value for value in bottoms if value is not None]
        tops = [value for value in tops if value is not None]

        if not bottoms or not tops:
            continue

        result.append(
            {
                "key": key,
                "floor_name": str(items[0].get("floor_name", "") or ""),
                "floor_order": items[0].get("floor_order"),
                "rows": items,
                "bottom_min": min(bottoms),
                "bottom_median": float(median(bottoms)),
                "top_max": max(tops),
            }
        )

    result.sort(key=lambda item: float(item["bottom_median"]))
    return result


def _ground_datum(levels, floor_group, doors):
    chosen_door = _choose_ground_door(doors)

    if chosen_door is not None:
        bottom = _pair_bottom(chosen_door)
        if bottom is not None:
            return {
                "y": float(bottom),
                "source": (
                    "MAIN_ENTRANCE_DOOR_BOTTOM"
                    if _main_door_flag(chosen_door)
                    else "WIDEST_MATCHED_EXTERIOR_DOOR_BOTTOM"
                ),
                "door_pair": chosen_door,
            }

    window_bottom = float(floor_group["bottom_min"])
    candidates = [
        row
        for row in levels
        if float(row["y"]) < window_bottom
    ]

    best = _best_level(candidates)
    if best is None:
        return None

    return {
        "y": float(best["y"]),
        "source": "STRONGEST_HORIZONTAL_LEVEL_BELOW_LOWEST_STOREY_WINDOWS",
        "level": best,
    }


def _upper_datum(levels, previous_floor, current_floor):
    lower_bound = float(previous_floor["top_max"])
    upper_bound = float(current_floor["bottom_min"])

    candidates = [
        row
        for row in levels
        if lower_bound < float(row["y"]) < upper_bound
    ]

    best = _best_level(candidates)
    if best is None:
        return None

    return {
        "y": float(best["y"]),
        "source": "STRONGEST_STRUCTURAL_HORIZONTAL_LEVEL_BETWEEN_STOREYS",
        "level": best,
    }


def _attach_window_values(floor_group, datum_y, source_to_mm, source):
    count = 0

    for row in floor_group["rows"]:
        bottom = _number(row.get("elevation_bottom_y"))
        top = _number(row.get("elevation_top_y"))

        if bottom is None or top is None or top <= bottom:
            continue

        bottom_local_cm = (bottom - datum_y) * source_to_mm / 10.0
        top_local_cm = (top - datum_y) * source_to_mm / 10.0
        height_cm = (top - bottom) * source_to_mm / 10.0

        row["floor_datum_y"] = float(datum_y)
        row["window_bottom_local_z_cm"] = round(float(bottom_local_cm), 4)
        row["window_top_local_z_cm"] = round(float(top_local_cm), 4)
        row["window_height_cm"] = round(float(height_cm), 4)
        row["vertical_level_source"] = source
        count += 1

    return count


def _attach_door_values(analysis, floor_datums, source_to_mm):
    door_count = 0

    for match in analysis.get("matches", []) or []:
        if not isinstance(match, dict):
            continue

        facade_number = _facade_number(match)
        if facade_number is None:
            continue

        datums = floor_datums.get(facade_number, [])
        if not datums:
            continue

        datums_sorted = sorted(datums, key=lambda row: float(row["datum_y"]))

        for pair in match.get("opening_pairs", []) or []:
            if not isinstance(pair, dict):
                continue

            if str(pair.get("kind", "") or "").strip().casefold() != "door":
                continue

            bottom = _pair_bottom(pair)
            top = _pair_top(pair)

            if bottom is None or top is None or top <= bottom:
                continue

            eligible = [
                row
                for row in datums_sorted
                if float(row["datum_y"]) <= float(bottom)
            ]

            if eligible:
                floor_row = eligible[-1]
            else:
                floor_row = min(
                    datums_sorted,
                    key=lambda row: abs(float(row["datum_y"]) - float(bottom)),
                )

            datum_y = float(floor_row["datum_y"])
            bottom_local_cm = (bottom - datum_y) * source_to_mm / 10.0
            top_local_cm = (top - datum_y) * source_to_mm / 10.0
            height_cm = (top - bottom) * source_to_mm / 10.0

            pair["floor_name"] = floor_row.get("floor_name", "")
            pair["floor_datum_y"] = datum_y
            pair["door_bottom_local_z_cm"] = round(float(bottom_local_cm), 4)
            pair["door_top_local_z_cm"] = round(float(top_local_cm), 4)
            pair["door_height_cm"] = round(float(height_cm), 4)
            pair["vertical_level_source"] = floor_row.get("source", "")
            door_count += 1

    return door_count


def attach_vertical_opening_levels(window, analysis):
    if not isinstance(analysis, dict):
        return analysis

    rows = [
        row
        for row in (analysis.get("plan_guided_facade_windows", []) or [])
        if isinstance(row, dict)
    ]

    if not rows:
        analysis["vertical_opening_levels"] = {
            "engine": ENGINE,
            "window_count": 0,
            "door_count": 0,
            "floors": [],
            "unresolved": [],
        }
        return analysis

    full_document = getattr(window, "_full_document", None)
    if full_document is None:
        raise RuntimeError("VERTICAL_LEVELS_FULL_DOCUMENT_MISSING")

    from cad.facade_runtime import _document_geometry
    from export.max_bridge import _source_to_mm

    geometry = _document_geometry(full_document)
    if not geometry:
        raise RuntimeError("VERTICAL_LEVELS_CAD_GEOMETRY_MISSING")

    source_to_mm = float(_source_to_mm(full_document))
    if not math.isfinite(source_to_mm) or source_to_mm <= 0.0:
        raise RuntimeError("VERTICAL_LEVELS_SOURCE_SCALE_INVALID")

    facade_by_number = _facade_map(analysis)
    rows_by_facade = defaultdict(list)

    for row in rows:
        number = _facade_number(row)
        if number is not None:
            rows_by_facade[number].append(row)

    summary_floors = []
    unresolved = []
    floor_datums = defaultdict(list)
    window_count = 0

    for facade_number, facade_rows in sorted(rows_by_facade.items()):
        facade = facade_by_number.get(facade_number)
        if not isinstance(facade, dict):
            unresolved.append(
                {
                    "facade_number": facade_number,
                    "reason": "ELEVATION_FACADE_NOT_FOUND",
                }
            )
            continue

        levels = _horizontal_levels_for_facade(
            geometry,
            facade.get("bbox"),
            source_to_mm,
        )

        if not levels:
            unresolved.append(
                {
                    "facade_number": facade_number,
                    "reason": "NO_HORIZONTAL_LEVELS_IN_FACADE",
                }
            )
            continue

        floor_groups = _floor_groups_for_facade(facade_rows)
        if not floor_groups:
            unresolved.append(
                {
                    "facade_number": facade_number,
                    "reason": "NO_FLOOR_WINDOW_GROUPS",
                }
            )
            continue

        doors = _door_pairs_for_facade(analysis, facade_number)
        previous = None

        for index, floor_group in enumerate(floor_groups):
            if index == 0:
                datum = _ground_datum(levels, floor_group, doors)
            else:
                datum = _upper_datum(levels, previous, floor_group)

            if datum is None:
                unresolved.append(
                    {
                        "facade_number": facade_number,
                        "floor_name": floor_group.get("floor_name", ""),
                        "floor_order": floor_group.get("floor_order"),
                        "reason": (
                            "GROUND_FLOOR_DATUM_NOT_FOUND"
                            if index == 0
                            else "UPPER_FLOOR_DATUM_NOT_FOUND"
                        ),
                    }
                )
                previous = floor_group
                continue

            datum_y = float(datum["y"])
            source = str(datum["source"])

            attached = _attach_window_values(
                floor_group,
                datum_y,
                source_to_mm,
                source,
            )
            window_count += attached

            floor_record = {
                "facade_number": facade_number,
                "floor_name": floor_group.get("floor_name", ""),
                "floor_order": floor_group.get("floor_order"),
                "datum_y": datum_y,
                "source": source,
                "window_count": attached,
            }

            summary_floors.append(floor_record)
            floor_datums[facade_number].append(floor_record)
            previous = floor_group

    door_count = _attach_door_values(
        analysis,
        floor_datums,
        source_to_mm,
    )

    analysis["vertical_opening_levels"] = {
        "engine": ENGINE,
        "source_to_mm": source_to_mm,
        "window_count": int(window_count),
        "door_count": int(door_count),
        "floors": summary_floors,
        "unresolved": unresolved,
    }

    print("")
    print("=== 3DCAD VERTICAL OPENING LEVELS V1 ===")
    print("SOURCE TO MM:", source_to_mm)
    print("WINDOW LEVELS:", window_count)
    print("DOOR LEVELS  :", door_count)
    print("FLOOR DATUMS :", len(summary_floors))
    print("UNRESOLVED   :", len(unresolved))
    print("=== END VERTICAL OPENING LEVELS ===")
    print("")

    return analysis
'''


def require(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"Gerekli dosya bulunamadi: {path}")


require(FACADE_RUNTIME)

runtime_text = FACADE_RUNTIME.read_text(encoding="utf-8-sig")

if ENGINE in runtime_text:
    print(f"{ENGINE} zaten kurulu.")
    raise SystemExit(0)

anchor = '''    result = (
        _rewrite_source_metadata(
            result
        )
    )
'''

if anchor not in runtime_text:
    raise RuntimeError(
        "facade_runtime.py icinde _rewrite_source_metadata baglama noktasi bulunamadi."
    )

insertion = anchor + '''
    # VERTICAL_OPENING_LEVELS_V1
    from cad.vertical_opening_levels import (
        attach_vertical_opening_levels,
    )

    result = attach_vertical_opening_levels(
        window,
        result,
    )
'''

patched_runtime = runtime_text.replace(anchor, insertion, 1)

# Syntax validation before touching project files.
compile(MODULE_TEXT, str(TARGET), "exec")
compile(patched_runtime, str(FACADE_RUNTIME), "exec")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_dir = (
    ROOT
    / "geliştirmeler"
    / "backups"
    / f"{ENGINE}_{stamp}"
)
backup_dir.mkdir(parents=True, exist_ok=True)

backup_runtime = backup_dir / "facade_runtime.py"
shutil.copy2(FACADE_RUNTIME, backup_runtime)

if TARGET.exists():
    shutil.copy2(TARGET, backup_dir / "vertical_opening_levels.py")

TARGET.write_text(MODULE_TEXT, encoding="utf-8")
FACADE_RUNTIME.write_text(patched_runtime, encoding="utf-8")

# Final compile verification from disk.
compile(TARGET.read_text(encoding="utf-8-sig"), str(TARGET), "exec")
compile(
    FACADE_RUNTIME.read_text(encoding="utf-8-sig"),
    str(FACADE_RUNTIME),
    "exec",
)

print("")
print("VERTICAL_OPENING_LEVELS_V1 INSTALLED")
print("")
print("BACKUP:")
print(" ", backup_dir)
print("")
print("ADDED:")
print("  src\\cad\\vertical_opening_levels.py")
print("")
print("PATCHED:")
print("  src\\cad\\facade_runtime.py")
print("")
print("OUTPUT FIELDS:")
print("  window_bottom_local_z_cm")
print("  window_top_local_z_cm")
print("  window_height_cm")
print("  door_bottom_local_z_cm")
print("  door_top_local_z_cm")
print("  door_height_cm")
print("  floor_datum_y")
print("")
print("UNCHANGED:")
print("  wall_detector.py")
print("  door_detector.py")
print("  window_detector.py")
print("  max_bridge.py")
print("  max\\3DCAD_BRIDGE.ms")
print("  pivot / BASE_Z")
print("")
print("NOTE:")
print("  Bu asamada Max Connect yapilmaz.")
print("  Yalniz gercek cephe-local kapı/pencere Z seviyeleri uretilir.")
print("")
