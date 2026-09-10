from __future__ import annotations

import time
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_to_mm(document) -> float:
    """
    Read CAD drawing units from the parsed DXF.

    Returned value converts one CAD drawing unit to millimeters.
    """
    try:
        import ezdxf

        doc = ezdxf.readfile(document.parsed_path)
        insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    except Exception:
        insunits = 0

    # AutoCAD INSUNITS -> millimeters per drawing unit.
    table = {
        1: 25.4,       # inch
        2: 304.8,      # foot
        4: 1.0,        # millimeter
        5: 10.0,       # centimeter
        6: 1000.0,     # meter
    }

    return float(table.get(insunits, 1.0))


def send_wall_lines_to_max(
    document,
    wall_candidates,
):
    """
    Send ONLY the currently detected wall primitives.

    Pivot rule:
        selected plan bounds center -> CAD pivot
        Max local XY = CAD XY - pivot XY
        Max node world position = 0,0,0
    """

    if document is None:
        raise RuntimeError("Önce plan alanı seçilmelidir.")

    candidates = tuple(wall_candidates or ())

    if not candidates:
        raise RuntimeError("Max'e gönderilecek seçilmiş duvar yok.")

    indices = []

    for candidate in candidates:
        index = getattr(candidate, "primitive_index", None)

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
        raise RuntimeError("Geçerli duvar primitive'i bulunamadı.")

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
        raise RuntimeError("Duvar geometrisi boş.")

    source_to_mm = _source_to_mm(document)

    pivot_x_source = (min(xs) + max(xs)) * 0.5
    pivot_y_source = (min(ys) + max(ys)) * 0.5

    pivot_x_mm = pivot_x_source * source_to_mm
    pivot_y_mm = pivot_y_source * source_to_mm

    request_id = str(time.time_ns())

    lines = [
        "3DCAD_WALL_REQUEST_V1",
        "REQUEST_ID=" + request_id,
        "PIVOT_X_MM=" + repr(float(pivot_x_mm)),
        "PIVOT_Y_MM=" + repr(float(pivot_y_mm)),
        "SOURCE_TO_MM=" + repr(float(source_to_mm)),
    ]

    sent_count = 0

    for primitive in selected_primitives:
        points = tuple(primitive.points or ())

        if len(points) < 2:
            continue

        point_text = ";".join(
            (
                f"{float(x) * source_to_mm:.9f},"
                f"{float(y) * source_to_mm:.9f}"
            )
            for x, y in points
        )

        closed = 1 if bool(primitive.closed) else 0

        lines.append(
            f"S|{closed}|{point_text}"
        )

        sent_count += 1

    if sent_count <= 0:
        raise RuntimeError("Aktarılabilir duvar çizgisi bulunamadı.")

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

    temporary = target.with_suffix(".tmp")

    temporary.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    temporary.replace(target)

    return {
        "request_id": request_id,
        "wall_count": sent_count,
        "pivot_x_mm": pivot_x_mm,
        "pivot_y_mm": pivot_y_mm,
        "source_to_mm": source_to_mm,
        "request_file": target,
    }
