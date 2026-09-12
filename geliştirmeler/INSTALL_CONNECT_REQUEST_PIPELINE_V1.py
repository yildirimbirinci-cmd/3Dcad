from __future__ import annotations

from datetime import datetime
from pathlib import Path
import ast
import shutil

ROOT = Path.cwd()

RUNTIME = ROOT / "src" / "export" / "connect_levels_runtime.py"
MULTI = ROOT / "src" / "export" / "multi_floor_max_send.py"
BRIDGE = ROOT / "src" / "export" / "max_bridge.py"

for path in (MULTI, BRIDGE):
    if not path.is_file():
        raise RuntimeError(f"Gerekli dosya bulunamadı: {path}")

MARKER = "CAD3D_CONNECT_REQUEST_PIPELINE_V1"

runtime_code = r'''from __future__ import annotations

from collections import defaultdict
import math


ENGINE = "CAD3D_CONNECT_REQUEST_PIPELINE_V1"


def _num(value):
    try:
        value = float(value)
    except Exception:
        return None
    return value if math.isfinite(value) else None


def _int(value):
    try:
        return int(value)
    except Exception:
        return None


def _facade_number(row):
    if not isinstance(row, dict):
        return None
    return _int(row.get("facade_number"))


def _bottom_y(row):
    if not isinstance(row, dict):
        return None

    for key in (
        "elevation_bottom_y",
        "bottom_y",
        "y0",
    ):
        value = _num(row.get(key))
        if value is not None:
            return value

    box = row.get("bbox")

    if (
        isinstance(box, (tuple, list))
        and len(box) >= 4
    ):
        return _num(box[1])

    return None


def _top_y(row):
    if not isinstance(row, dict):
        return None

    for key in (
        "elevation_top_y",
        "top_y",
        "y1",
    ):
        value = _num(row.get(key))
        if value is not None:
            return value

    box = row.get("bbox")

    if (
        isinstance(box, (tuple, list))
        and len(box) >= 4
    ):
        return _num(box[3])

    bottom = _bottom_y(row)
    height = _num(
        row.get(
            "elevation_height"
        )
    )

    if (
        bottom is not None
        and height is not None
    ):
        return bottom + height

    return None


def _merge_intervals(intervals):
    merged = []

    for start, end in sorted(intervals):
        if end <= start:
            continue

        if (
            not merged
            or start > merged[-1][1]
        ):
            merged.append(
                [start, end]
            )
        else:
            merged[-1][1] = max(
                merged[-1][1],
                end,
            )

    return merged


def _horizontal_levels(
    region_geometry,
    bbox,
    source_to_mm,
):
    from cad._cad_to_3d_max_facade.elevation_opening_detector import (
        _extract_axis_segments,
        _merge_horizontal,
    )

    if not (
        isinstance(
            bbox,
            (tuple, list),
        )
        and len(bbox) == 4
    ):
        return []

    x0, y0, x1, y1 = (
        float(value)
        for value in bbox
    )

    width = max(
        x1 - x0,
        1.0e-12,
    )

    horizontal, _vertical = (
        _extract_axis_segments(
            region_geometry
        )
    )

    one_mm_source = (
        1.0
        / max(
            float(source_to_mm),
            1.0e-12,
        )
    )

    horizontal = [
        row
        for row in horizontal
        if (
            float(
                row.get(
                    "x1",
                    -1.0e30,
                )
            )
            >= x0
            and float(
                row.get(
                    "x0",
                    1.0e30,
                )
            )
            <= x1
            and y0
            <= float(
                row.get(
                    "y",
                    -1.0e30,
                )
            )
            <= y1
        )
    ]

    if not horizontal:
        return []

    horizontal = _merge_horizontal(
        horizontal,
        y_tolerance=max(
            one_mm_source,
            1.0e-9,
        ),
        gap_tolerance=max(
            one_mm_source * 2.0,
            1.0e-9,
        ),
    )

    groups = []

    for row in sorted(
        horizontal,
        key=lambda item: float(
            item["y"]
        ),
    ):
        y = float(
            row["y"]
        )

        sx0 = max(
            x0,
            float(
                row["x0"]
            ),
        )

        sx1 = min(
            x1,
            float(
                row["x1"]
            ),
        )

        if sx1 <= sx0:
            continue

        group = None

        for candidate in groups:
            if (
                abs(
                    float(
                        candidate["y"]
                    )
                    - y
                )
                <= one_mm_source
            ):
                group = candidate
                break

        if group is None:
            group = {
                "y": y,
                "ys": [],
                "intervals": [],
            }
            groups.append(
                group
            )

        group[
            "ys"
        ].append(
            y
        )

        group[
            "intervals"
        ].append(
            (
                sx0,
                sx1,
            )
        )

        group[
            "y"
        ] = (
            sum(
                group["ys"]
            )
            / len(
                group["ys"]
            )
        )

    levels = []

    for group in groups:
        intervals = (
            _merge_intervals(
                group[
                    "intervals"
                ]
            )
        )

        union_length = sum(
            end - start
            for start, end
            in intervals
        )

        longest = max(
            (
                end - start
                for start, end
                in intervals
            ),
            default=0.0,
        )

        levels.append(
            {
                "y":
                    float(
                        group["y"]
                    ),

                "coverage":
                    float(
                        union_length
                        / width
                    ),

                "longest_ratio":
                    float(
                        longest
                        / width
                    ),
            }
        )

    return levels


def _best_level(
    levels,
    lower_bound,
    upper_bound,
):
    candidates = [
        row
        for row in levels
        if (
            float(
                lower_bound
            )
            < float(
                row["y"]
            )
            < float(
                upper_bound
            )
        )
    ]

    if not candidates:
        return None

    # No architectural dimension threshold:
    # strongest/longest CAD horizontal wins.
    # Equal structural strength -> upper line wins.
    return max(
        candidates,
        key=lambda row: (
            float(
                row.get(
                    "coverage",
                    0.0,
                )
            ),
            float(
                row.get(
                    "longest_ratio",
                    0.0,
                )
            ),
            float(
                row["y"]
            ),
        ),
    )


def _current_analysis(window):
    result = getattr(
        window,
        "current_facade_match_result",
        None,
    )

    if isinstance(
        result,
        dict,
    ):
        return result

    return {}


def _preanalysis(window):
    result = getattr(
        window,
        "_cad3d_facade_preanalysis",
        None,
    )

    if isinstance(
        result,
        dict,
    ):
        return result

    return {}


def _facades_by_number(preanalysis):
    result = {}

    for facade in (
        preanalysis.get(
            "elevation_facades",
            [],
        )
        or []
    ):
        if not isinstance(
            facade,
            dict,
        ):
            continue

        number = (
            _facade_number(
                facade
            )
        )

        if number is not None:
            result[
                number
            ] = facade

    return result


def _regions_by_id(preanalysis):
    result = {}

    for region in (
        preanalysis.get(
            "regions",
            [],
        )
        or []
    ):
        if not isinstance(
            region,
            dict,
        ):
            continue

        region_id = (
            region.get(
                "region_id"
            )
        )

        if region_id is not None:
            result[
                str(
                    region_id
                )
            ] = region

    return result


def _rows_by_facade(
    analysis,
):
    result = defaultdict(
        list
    )

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

        number = (
            _facade_number(
                row
            )
        )

        if number is None:
            continue

        result[
            number
        ].append(
            row
        )

    return result


def _previous_top_for_same_facade(
    rows,
    target_floor_name,
    target_bottom,
):
    previous_tops = []

    for row in rows:
        row_floor = str(
            row.get(
                "floor_name",
                "",
            )
            or ""
        ).strip()

        if (
            row_floor
            == target_floor_name
        ):
            continue

        bottom = (
            _bottom_y(
                row
            )
        )

        top = (
            _top_y(
                row
            )
        )

        if (
            bottom is None
            or top is None
        ):
            continue

        if top < target_bottom:
            previous_tops.append(
                top
            )

    if not previous_tops:
        return None

    return max(
        previous_tops
    )


def collect_connect_levels(
    window,
    package,
):
    analysis = (
        _current_analysis(
            window
        )
    )

    preanalysis = (
        _preanalysis(
            window
        )
    )

    floor_name = str(
        package.get(
            "floor_name",
            "",
        )
        or ""
    ).strip()

    wall_height_cm = (
        _num(
            package.get(
                "wall_height_cm"
            )
        )
    )

    if not floor_name:
        raise RuntimeError(
            "Connect icin kat adi eksik."
        )

    if (
        wall_height_cm is None
        or wall_height_cm <= 0.0
    ):
        raise RuntimeError(
            floor_name
            + ": duvar yuksekligi gecersiz."
        )

    if not analysis:
        raise RuntimeError(
            floor_name
            + ": mevcut cephe eslestirme sonucu bulunamadi."
        )

    if not preanalysis:
        raise RuntimeError(
            floor_name
            + ": cephe preanalysis geometrisi bulunamadi."
        )

    from export.max_bridge import (
        _source_to_mm,
    )

    full_document = getattr(
        window,
        "_full_document",
        None,
    )

    if full_document is None:
        full_document = (
            package.get(
                "document"
            )
        )

    source_to_mm = float(
        _source_to_mm(
            full_document
        )
    )

    facades = (
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
        _rows_by_facade(
            analysis
        )
    )

    target_rows = [
        row
        for rows
        in all_rows_by_facade.values()
        for row in rows
        if str(
            row.get(
                "floor_name",
                "",
            )
            or ""
        ).strip()
        == floor_name
    ]

    if not target_rows:
        raise RuntimeError(
            floor_name
            + ": cephede eslesmis pencere satiri bulunamadi."
        )

    target_rows_by_facade = (
        defaultdict(
            list
        )
    )

    for row in target_rows:
        number = (
            _facade_number(
                row
            )
        )

        if number is not None:
            target_rows_by_facade[
                number
            ].append(
                row
            )

    facade_datums = {}
    levels_cm = []
    window_rows_used = 0

    for (
        facade_number,
        rows,
    ) in sorted(
        target_rows_by_facade.items()
    ):
        facade = (
            facades.get(
                facade_number
            )
        )

        if not isinstance(
            facade,
            dict,
        ):
            continue

        region_id = str(
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
            value
            for value in (
                _bottom_y(
                    row
                )
                for row in rows
            )
            if value is not None
        ]

        tops = [
            value
            for value in (
                _top_y(
                    row
                )
                for row in rows
            )
            if value is not None
        ]

        if (
            not bottoms
            or not tops
        ):
            continue

        target_bottom = min(
            bottoms
        )

        previous_top = (
            _previous_top_for_same_facade(
                all_rows_by_facade[
                    facade_number
                ],
                floor_name,
                target_bottom,
            )
        )

        bbox = facade.get(
            "bbox"
        )

        if not (
            isinstance(
                bbox,
                (tuple, list),
            )
            and len(
                bbox
            ) == 4
        ):
            continue

        lower_bound = (
            float(
                bbox[1]
            )
            if previous_top is None
            else float(
                previous_top
            )
        )

        structural_levels = (
            _horizontal_levels(
                region_geometry,
                bbox,
                source_to_mm,
            )
        )

        datum = (
            _best_level(
                structural_levels,
                lower_bound,
                target_bottom,
            )
        )

        if datum is None:
            continue

        datum_y = float(
            datum["y"]
        )

        facade_datums[
            facade_number
        ] = datum_y

        for row in rows:
            bottom = (
                _bottom_y(
                    row
                )
            )

            top = (
                _top_y(
                    row
                )
            )

            if (
                bottom is None
                or top is None
                or top <= bottom
            ):
                continue

            bottom_cm = (
                (
                    bottom
                    - datum_y
                )
                * source_to_mm
                / 10.0
            )

            top_cm = (
                (
                    top
                    - datum_y
                )
                * source_to_mm
                / 10.0
            )

            row[
                "floor_datum_y"
            ] = datum_y

            row[
                "window_bottom_local_z_cm"
            ] = float(
                bottom_cm
            )

            row[
                "window_top_local_z_cm"
            ] = float(
                top_cm
            )

            row[
                "window_height_cm"
            ] = float(
                (
                    top
                    - bottom
                )
                * source_to_mm
                / 10.0
            )

            levels_cm.extend(
                (
                    bottom_cm,
                    top_cm,
                )
            )

            window_rows_used += 1

    door_tops_used = 0

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

        facade_number = (
            _facade_number(
                match
            )
        )

        datum_y = (
            facade_datums.get(
                facade_number
            )
        )

        if datum_y is None:
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

            bottom = (
                _bottom_y(
                    pair
                )
            )

            top = (
                _top_y(
                    pair
                )
            )

            if (
                bottom is None
                or top is None
                or top <= bottom
            ):
                continue

            local_bottom_cm = (
                (
                    bottom
                    - datum_y
                )
                * source_to_mm
                / 10.0
            )

            local_top_cm = (
                (
                    top
                    - datum_y
                )
                * source_to_mm
                / 10.0
            )

            if not (
                -0.001
                <= local_bottom_cm
                < wall_height_cm
            ):
                continue

            if not (
                0.0
                < local_top_cm
                < wall_height_cm
            ):
                continue

            pair[
                "floor_name"
            ] = floor_name

            pair[
                "floor_datum_y"
            ] = datum_y

            pair[
                "door_bottom_local_z_cm"
            ] = float(
                local_bottom_cm
            )

            pair[
                "door_top_local_z_cm"
            ] = float(
                local_top_cm
            )

            pair[
                "door_height_cm"
            ] = float(
                (
                    top
                    - bottom
                )
                * source_to_mm
                / 10.0
            )

            levels_cm.append(
                local_top_cm
            )

            door_tops_used += 1

    unique = []
    seen = set()

    for raw_value in levels_cm:
        value = (
            _num(
                raw_value
            )
        )

        if value is None:
            continue

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

        unique.append(
            float(
                key
            )
        )

    unique.sort()

    if not unique:
        raise RuntimeError(
            floor_name
            + ": Connect icin kullanilabilir local Z seviyesi bulunamadi."
        )

    print("")
    print(
        "=== 3DCAD CONNECT REQUEST LEVELS V1 ==="
    )
    print(
        "FLOOR:",
        floor_name,
    )
    print(
        "SOURCE_TO_MM:",
        source_to_mm,
    )
    print(
        "WINDOW ROWS USED:",
        window_rows_used,
    )
    print(
        "DOOR TOPS USED:",
        door_tops_used,
    )
    print(
        "CONNECT LEVELS CM:",
        unique,
    )
    print(
        "========================================"
    )
    print("")

    return tuple(
        unique
    )
'''


def read(path):
    return path.read_text(
        encoding="utf-8-sig"
    )


def replace_once(
    text,
    old,
    new,
    label,
):
    count = text.count(
        old
    )

    if count != 1:
        raise RuntimeError(
            label
            + ": beklenen 1 eslesme, bulunan "
            + str(
                count
            )
            + ". Dosyalar degistirilmedi."
        )

    return text.replace(
        old,
        new,
        1,
    )


multi_text = read(
    MULTI
)

bridge_text = read(
    BRIDGE
)

if MARKER in multi_text:
    raise RuntimeError(
        "CONNECT_REQUEST_PIPELINE_V1 zaten multi_floor_max_send.py icinde."
    )

if MARKER in bridge_text:
    raise RuntimeError(
        "CONNECT_REQUEST_PIPELINE_V1 zaten max_bridge.py icinde."
    )

package_old = '''        "walls":
            walls,

        "bounds":
            bounds,
'''

package_new = '''        "walls":
            walls,

        # CAD3D_CONNECT_REQUEST_PIPELINE_V1
        "doors":
            doors,

        "windows":
            windows,

        "bounds":
            bounds,
'''

multi_text = replace_once(
    multi_text,
    package_old,
    package_new,
    "floor package",
)

collector_call_old = '''    try:
        result = send_wall_lines_to_max(
'''

collector_call_new = '''    # CAD3D_CONNECT_REQUEST_PIPELINE_V1
    from export.connect_levels_runtime import (
        collect_connect_levels,
    )

    connect_levels_cm = collect_connect_levels(
        window,
        package,
    )

    try:
        result = send_wall_lines_to_max(
'''

multi_text = replace_once(
    multi_text,
    collector_call_old,
    collector_call_new,
    "send collector",
)

send_arg_old = '''            pivot_source=(
                package[
                    "pivot_source"
                ]
            ),
        )
'''

send_arg_new = '''            pivot_source=(
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
    send_arg_old,
    send_arg_new,
    "send connect argument",
)

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

serialize_marker = '''    sent_count = 0
'''

serialize_block = '''    # CAD3D_CONNECT_REQUEST_PIPELINE_V1
    normalized_connect_levels = []
    seen_connect_levels = set()

    if is_floor_request:
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

            if (
                level != level
                or abs(
                    level
                )
                == float(
                    "inf"
                )
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

    sent_count = 0
'''

bridge_text = replace_once(
    bridge_text,
    serialize_marker,
    serialize_block,
    "request serializer",
)

# Validate Python before touching project.
compile(
    runtime_code,
    str(
        RUNTIME
    ),
    "exec",
)

ast.parse(
    multi_text
)

ast.parse(
    bridge_text
)

stamp = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)

backup_dir = (
    ROOT
    / "geliştirmeler"
    / "backups"
    / (
        "CONNECT_REQUEST_PIPELINE_V1_"
        + stamp
    )
)

backup_dir.mkdir(
    parents=True,
    exist_ok=True,
)

for path in (
    MULTI,
    BRIDGE,
):
    shutil.copy2(
        path,
        backup_dir
        / path.name,
    )

if RUNTIME.exists():
    shutil.copy2(
        RUNTIME,
        backup_dir
        / RUNTIME.name,
    )

RUNTIME.write_text(
    runtime_code,
    encoding="utf-8",
)

MULTI.write_text(
    multi_text,
    encoding="utf-8",
)

BRIDGE.write_text(
    bridge_text,
    encoding="utf-8",
)

# Final validation.
compile(
    RUNTIME.read_text(
        encoding="utf-8-sig"
    ),
    str(
        RUNTIME
    ),
    "exec",
)

compile(
    MULTI.read_text(
        encoding="utf-8-sig"
    ),
    str(
        MULTI
    ),
    "exec",
)

compile(
    BRIDGE.read_text(
        encoding="utf-8-sig"
    ),
    str(
        BRIDGE
    ),
    "exec",
)

print("")
print(
    "CONNECT_REQUEST_PIPELINE_V1 INSTALLED"
)
print("")
print(
    "CHANGED:"
)
print(
    "  src/export/connect_levels_runtime.py"
)
print(
    "  src/export/multi_floor_max_send.py"
)
print(
    "  src/export/max_bridge.py"
)
print("")
print(
    "NOT CHANGED:"
)
print(
    "  src/cad/facade_runtime.py"
)
print(
    "  src/ui/main_window.py"
)
print(
    "  src/ui/cad_view.py"
)
print(
    "  max/3DCAD_BRIDGE.ms"
)
print("")
print(
    "THIS STAGE ONLY SENDS CONNECT_LEVEL_CM."
)
print(
    "MAX CONNECT IS NOT ENABLED YET."
)
print("")
print(
    "BACKUP:"
)
print(
    " ",
    backup_dir,
)
print("")
