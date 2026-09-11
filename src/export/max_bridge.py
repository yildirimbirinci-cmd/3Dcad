from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_to_mm(document) -> float:
    try:
        import ezdxf

        doc = ezdxf.readfile(document.parsed_path)
        insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    except Exception:
        insunits = 0

    table = {
        1: 25.4,
        2: 304.8,
        4: 1.0,
        5: 10.0,
        6: 1000.0,
    }

    return float(table.get(insunits, 1.0))


def _safe_line_text(value) -> str:
    return (
        str(value or "")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def _safe_node_name(floor_name: str) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(floor_name or ""),
    )

    text = (
        text.encode("ascii", "ignore")
        .decode("ascii")
    )

    text = re.sub(
        r"[^A-Za-z0-9]+",
        "_",
        text,
    ).strip("_")

    if not text:
        text = "Floor"

    return "3Dcad_" + text + "_Walls"


def send_wall_lines_to_max(
    document,
    wall_candidates,
    *,
    floor_name=None,
    floor_index=None,
    base_z_cm=0.0,
    wall_height_cm=0.0,
    interfloor_cm=0.0,
    pivot_source=None,
):
    if document is None:
        raise RuntimeError(
            "Önce plan alanı seçilmelidir."
        )

    candidates = tuple(
        wall_candidates or ()
    )

    if not candidates:
        raise RuntimeError(
            "Max'e gönderilecek seçilmiş duvar yok."
        )

    indices = []

    for candidate in candidates:
        index = getattr(
            candidate,
            "primitive_index",
            None,
        )

        if index is None:
            continue

        index = int(index)

        if (
            index < 0
            or index >= len(document.primitives)
            or index in indices
        ):
            continue

        indices.append(index)

    if not indices:
        raise RuntimeError(
            "Geçerli duvar primitive'i bulunamadı."
        )

    selected_primitives = [
        document.primitives[index]
        for index in indices
    ]

    xs = []
    ys = []

    for primitive in selected_primitives:
        for x, y in primitive.points:
            xs.append(float(x))
            ys.append(float(y))

    if not xs:
        raise RuntimeError(
            "Duvar geometrisi boş."
        )

    source_to_mm = _source_to_mm(
        document
    )

    if pivot_source is None:
        pivot_x_source = (
            min(xs) + max(xs)
        ) * 0.5

        pivot_y_source = (
            min(ys) + max(ys)
        ) * 0.5
    else:
        if (
            not isinstance(
                pivot_source,
                (tuple, list),
            )
            or len(pivot_source) != 2
        ):
            raise RuntimeError(
                "Kat pivotu geçersiz."
            )

        pivot_x_source = float(
            pivot_source[0]
        )

        pivot_y_source = float(
            pivot_source[1]
        )

    pivot_x_mm = (
        pivot_x_source
        * source_to_mm
    )

    pivot_y_mm = (
        pivot_y_source
        * source_to_mm
    )

    request_id = str(
        time.time_ns()
    )

    is_floor_request = (
        floor_name is not None
    )

    if is_floor_request:
        if floor_index is None:
            raise RuntimeError(
                "Kat index bilgisi eksik."
            )

        floor_name = _safe_line_text(
            floor_name
        )

        node_name = _safe_node_name(
            floor_name
        )

        lines = [
            "3DCAD_WALL_REQUEST_V2",
            "REQUEST_ID=" + request_id,
            "FLOOR_NAME=" + floor_name,
            "FLOOR_INDEX=" + str(
                int(floor_index)
            ),
            "BASE_Z_CM=" + repr(
                float(base_z_cm)
            ),
            "HEIGHT_CM=" + repr(
                float(wall_height_cm)
            ),
            "INTERFLOOR_CM=" + repr(
                float(interfloor_cm)
            ),
            "NODE_NAME=" + node_name,
            "PIVOT_X_MM=" + repr(
                float(pivot_x_mm)
            ),
            "PIVOT_Y_MM=" + repr(
                float(pivot_y_mm)
            ),
            "SOURCE_TO_MM=" + repr(
                float(source_to_mm)
            ),
        ]
    else:
        node_name = "3Dcad_Walls"

        lines = [
            "3DCAD_WALL_REQUEST_V1",
            "REQUEST_ID=" + request_id,
            "PIVOT_X_MM=" + repr(
                float(pivot_x_mm)
            ),
            "PIVOT_Y_MM=" + repr(
                float(pivot_y_mm)
            ),
            "SOURCE_TO_MM=" + repr(
                float(source_to_mm)
            ),
        ]

    sent_count = 0

    for primitive in selected_primitives:
        points = tuple(
            primitive.points or ()
        )

        if len(points) < 2:
            continue

        point_text = ";".join(
            (
                f"{float(x) * source_to_mm:.9f},"
                f"{float(y) * source_to_mm:.9f}"
            )
            for x, y in points
        )

        closed = (
            1
            if bool(primitive.closed)
            else 0
        )

        lines.append(
            f"S|{closed}|{point_text}"
        )

        sent_count += 1

    if sent_count <= 0:
        raise RuntimeError(
            "Aktarılabilir duvar çizgisi bulunamadı."
        )

    target = (
        _project_root()
        / "data"
        / "cache"
        / "max_bridge"
        / "visible_cad_request.txt"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = target.with_suffix(
        ".tmp"
    )

    temporary.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    temporary.replace(target)

    return {
        "request_id":
            request_id,

        "wall_count":
            sent_count,

        "pivot_x_mm":
            pivot_x_mm,

        "pivot_y_mm":
            pivot_y_mm,

        "source_to_mm":
            source_to_mm,

        "floor_name":
            floor_name
            if is_floor_request
            else None,

        "floor_index":
            int(floor_index)
            if is_floor_request
            else None,

        "base_z_cm":
            float(base_z_cm)
            if is_floor_request
            else 0.0,

        "wall_height_cm":
            float(wall_height_cm)
            if is_floor_request
            else 0.0,

        "interfloor_cm":
            float(interfloor_cm)
            if is_floor_request
            else 0.0,

        "node_name":
            node_name,

        "request_file":
            target,
    }
