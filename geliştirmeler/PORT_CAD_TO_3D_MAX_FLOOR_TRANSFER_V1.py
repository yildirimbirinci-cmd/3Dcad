from pathlib import Path
import ast

ROOT = Path.cwd()

MAIN = ROOT / "src" / "ui" / "main_window.py"
BRIDGE = ROOT / "src" / "export" / "max_bridge.py"
MULTI = ROOT / "src" / "export" / "multi_floor_max_send.py"
MAXSCRIPT = ROOT / "max" / "3DCAD_BRIDGE.ms"


# ============================================================
# MAX BRIDGE PYTHON V2
# ============================================================

bridge_text = r'''from __future__ import annotations

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
'''


# ============================================================
# MULTI FLOOR CONTROLLER
# ============================================================

multi_text = r'''from __future__ import annotations

import json
import re
import time
from pathlib import Path

from cad.door_detector import detect_interior_doors
from cad.wall_detector import detect_walls
from cad.window_detector import detect_window_family
from export.max_bridge import send_wall_lines_to_max


ENGINE = "3DCAD_MULTI_FLOOR_MAX_SEND_V1"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _result_path() -> Path:
    return (
        _project_root()
        / "data"
        / "cache"
        / "max_bridge"
        / "visible_cad_result.txt"
    )


def floor_index_from_name(
    floor_name: str,
) -> int:
    name = str(
        floor_name or ""
    ).strip()

    if name == "Giriş Kat":
        return 0

    if name == "Bodrum Kat":
        return -1

    match = re.fullmatch(
        r"([+-]?\d+)\.\s*Kat",
        name,
        flags=re.IGNORECASE,
    )

    if match:
        return int(
            match.group(1)
        )

    raise RuntimeError(
        "Kat sırası çözülemedi: "
        + name
    )


def ordered_confirmed_floors(
    floors,
):
    records = []
    names = set()
    indexes = {}

    for source in floors or ():
        if not isinstance(source, dict):
            continue

        row = dict(source)

        name = str(
            row.get("name", "")
            or ""
        ).strip()

        if not name:
            raise RuntimeError(
                "Onaylı kat adı eksik."
            )

        if name in names:
            raise RuntimeError(
                "Aynı kat adı birden fazla kullanılmış: "
                + name
            )

        names.add(name)

        index = floor_index_from_name(
            name
        )

        if index in indexes:
            raise RuntimeError(
                "İki kat aynı kat sırasını kullanıyor: "
                + indexes[index]
                + " / "
                + name
            )

        indexes[index] = name
        row["_floor_index"] = index

        document = row.get(
            "document"
        )

        if document is None:
            raise RuntimeError(
                name
                + ": kat CAD verisi eksik."
            )

        bounds = row.get(
            "bounds"
        )

        if (
            not isinstance(
                bounds,
                (tuple, list),
            )
            or len(bounds) != 4
        ):
            raise RuntimeError(
                name
                + ": kat sınırları geçersiz."
            )

        height = float(
            row.get(
                "wall_height_cm",
                0.0,
            )
            or 0.0
        )

        gap = float(
            row.get(
                "interfloor_cm",
                0.0,
            )
            or 0.0
        )

        if height <= 0.0:
            raise RuntimeError(
                name
                + ": duvar yüksekliği geçersiz."
            )

        if gap < 0.0:
            raise RuntimeError(
                name
                + ": kat arası negatif olamaz."
            )

        records.append(row)

    return sorted(
        records,
        key=lambda row:
            int(row["_floor_index"]),
    )


def _floor_by_index(
    records,
):
    return {
        int(row["_floor_index"]):
            row
        for row in records
    }


def _height(
    row,
) -> float:
    return float(
        row["wall_height_cm"]
    )


def _gap(
    row,
) -> float:
    return float(
        row["interfloor_cm"]
    )


def _base_z_for_index(
    target_index: int,
    by_index,
) -> float:
    target_index = int(
        target_index
    )

    if target_index == 0:
        return 0.0

    if 0 not in by_index:
        raise RuntimeError(
            "Kat kotu için Giriş Kat onaylanmış olmalıdır."
        )

    if target_index > 0:
        required = list(
            range(
                0,
                target_index,
            )
        )

        missing = [
            index
            for index in required
            if index not in by_index
        ]

        if missing:
            raise RuntimeError(
                "Üst kat BASE_Z için alt kat eksik: "
                + ", ".join(
                    str(value)
                    for value in missing
                )
            )

        if target_index not in by_index:
            raise RuntimeError(
                "Hedef kat kaydı eksik."
            )

        base_z = 0.0

        for lower_index in range(
            0,
            target_index,
        ):
            base_z += _height(
                by_index[
                    lower_index
                ]
            )

            upper_index = (
                lower_index + 1
            )

            base_z += _gap(
                by_index[
                    upper_index
                ]
            )

        return float(base_z)

    required_upper_basements = list(
        range(
            -1,
            target_index,
            -1,
        )
    )

    missing = [
        index
        for index in required_upper_basements
        if index not in by_index
    ]

    if missing:
        raise RuntimeError(
            "Bodrum BASE_Z için üst bodrum kat eksik: "
            + ", ".join(
                str(value)
                for value in missing
            )
        )

    if target_index not in by_index:
        raise RuntimeError(
            "Hedef bodrum kat kaydı eksik."
        )

    depth = (
        _height(
            by_index[
                target_index
            ]
        )
        + _gap(
            by_index[
                target_index
            ]
        )
    )

    for index in required_upper_basements:
        depth += (
            _height(
                by_index[index]
            )
            + _gap(
                by_index[index]
            )
        )

    return -float(depth)


def _prepare_floor_package(
    floor,
    by_index,
):
    name = str(
        floor["name"]
    )

    index = int(
        floor["_floor_index"]
    )

    document = floor[
        "document"
    ]

    bounds = tuple(
        float(value)
        for value in floor[
            "bounds"
        ]
    )

    x0, y0, x1, y1 = bounds

    pivot_source = (
        (x0 + x1) * 0.5,
        (y0 + y1) * 0.5,
    )

    # EXACT SAME CURRENT 3Dcad DETECTOR ORDER:
    # door -> window -> wall
    doors = tuple(
        detect_interior_doors(
            document
        )
    )

    window_result = (
        detect_window_family(
            document,
            doors,
        )
    )

    windows = tuple(
        getattr(
            window_result,
            "windows",
            (),
        )
        or ()
    )

    walls = tuple(
        detect_walls(
            document,
            doors,
            windows,
        )
    )

    if not walls:
        raise RuntimeError(
            name
            + ": gönderilecek duvar bulunamadı."
        )

    gap = float(
        floor[
            "interfloor_cm"
        ]
    )

    if index == 0:
        gap = 0.0

    return {
        "floor_name":
            name,

        "floor_index":
            index,

        "document":
            document,

        "walls":
            walls,

        "bounds":
            bounds,

        "pivot_source":
            pivot_source,

        "wall_height_cm":
            float(
                floor[
                    "wall_height_cm"
                ]
            ),

        "interfloor_cm":
            gap,

        "base_z_cm":
            _base_z_for_index(
                index,
                by_index,
            ),
    }


def _read_result(
    request_id,
):
    path = _result_path()

    if not path.exists():
        return None

    try:
        lines = path.read_text(
            encoding="utf-8-sig",
        ).splitlines()
    except Exception:
        return None

    if (
        not lines
        or lines[0].strip()
        != "3DCAD_WALL_RESULT_V2"
    ):
        return None

    data = {}

    for line in lines[1:]:
        if "=" not in line:
            continue

        key, value = line.split(
            "=",
            1,
        )

        data[
            key.strip()
        ] = value.strip()

    if (
        data.get(
            "REQUEST_ID",
            ""
        )
        != str(request_id)
    ):
        return None

    return data


def _write_log(
    window,
):
    state = getattr(
        window,
        "_max_floor_send_batch",
        None,
    )

    if not isinstance(
        state,
        dict,
    ):
        return

    target = (
        _project_root()
        / "logs"
        / "multi_floor_max_send.json"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "engine":
            ENGINE,

        "active":
            bool(
                state.get(
                    "active",
                    False,
                )
            ),

        "cursor":
            int(
                state.get(
                    "cursor",
                    0,
                )
            ),

        "floor_count":
            len(
                state.get(
                    "packages",
                    (),
                )
            ),

        "results":
            list(
                state.get(
                    "results",
                    (),
                )
            ),
    }

    target.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _finish(
    window,
    *,
    success,
    message,
):
    state = getattr(
        window,
        "_max_floor_send_batch",
        None,
    )

    if isinstance(
        state,
        dict,
    ):
        state["active"] = False

    _write_log(window)

    button = getattr(
        window,
        "generate_3d_btn",
        None,
    )

    if button is not None:
        button.setText(
            "3D Oluştur"
        )

        button.setEnabled(
            True
        )

    window.statusBar().showMessage(
        message
    )

    print("")
    print(
        "=== 3DCAD MULTI FLOOR MAX SEND END ==="
    )
    print(
        "SUCCESS:",
        bool(success),
    )
    print(
        "MESSAGE:",
        message,
    )
    print(
        "=== END ==="
    )
    print("")


def _watch_result(
    window,
    request_id,
    started_at,
):
    from PySide6.QtCore import QTimer

    state = getattr(
        window,
        "_max_floor_send_batch",
        None,
    )

    if (
        not isinstance(
            state,
            dict,
        )
        or not state.get(
            "active",
            False,
        )
    ):
        return

    result = _read_result(
        request_id
    )

    if result is not None:
        package = state[
            "packages"
        ][
            state["cursor"]
        ]

        status = str(
            result.get(
                "STATUS",
                "",
            )
        ).upper()

        if status == "OK":
            state[
                "results"
            ].append(
                {
                    "floor_name":
                        package[
                            "floor_name"
                        ],

                    "floor_index":
                        package[
                            "floor_index"
                        ],

                    "base_z_cm":
                        package[
                            "base_z_cm"
                        ],

                    "request_id":
                        request_id,

                    "status":
                        "success",
                }
            )

            print(
                "MAX RESULT OK:",
                package[
                    "floor_name"
                ],
                "| REQUEST:",
                request_id,
            )

            state["cursor"] += 1

            _write_log(
                window
            )

            QTimer.singleShot(
                250,
                lambda:
                    _send_next_floor(
                        window
                    ),
            )

            return

        _finish(
            window,
            success=False,
            message=(
                package[
                    "floor_name"
                ]
                + " Max aktarımı başarısız | "
                + str(
                    result.get(
                        "MESSAGE",
                        "unknown",
                    )
                )
            ),
        )

        return

    if (
        time.monotonic()
        - float(started_at)
        > 300.0
    ):
        _finish(
            window,
            success=False,
            message=(
                "3ds Max sonucu için "
                "300 saniye zaman aşımı."
            ),
        )

        return

    QTimer.singleShot(
        100,
        lambda:
            _watch_result(
                window,
                request_id,
                started_at,
            ),
    )


def _send_next_floor(
    window,
):
    state = getattr(
        window,
        "_max_floor_send_batch",
        None,
    )

    if (
        not isinstance(
            state,
            dict,
        )
        or not state.get(
            "active",
            False,
        )
    ):
        return

    packages = state[
        "packages"
    ]

    cursor = int(
        state[
            "cursor"
        ]
    )

    if cursor >= len(packages):
        names = [
            row[
                "floor_name"
            ]
            for row in packages
        ]

        _finish(
            window,
            success=True,
            message=(
                "3ds Max aktarımı tamamlandı | "
                + " -> ".join(names)
            ),
        )

        return

    package = packages[
        cursor
    ]

    floor_name = package[
        "floor_name"
    ]

    window.statusBar().showMessage(
        (
            f"{cursor + 1}/{len(packages)} "
            + floor_name
            + " 3ds Max'e gönderiliyor..."
        )
    )

    print("")
    print(
        "=== 3DCAD MULTI FLOOR MAX SEND ==="
    )
    print(
        "FLOOR:",
        floor_name,
    )
    print(
        "INDEX:",
        package[
            "floor_index"
        ],
    )
    print(
        "HEIGHT:",
        package[
            "wall_height_cm"
        ],
    )
    print(
        "GAP:",
        package[
            "interfloor_cm"
        ],
    )
    print(
        "BASE_Z:",
        package[
            "base_z_cm"
        ],
    )
    print(
        "AUTO PIVOT SOURCE:",
        package[
            "pivot_source"
        ],
    )
    print(
        "WALLS:",
        len(
            package[
                "walls"
            ]
        ),
    )

    try:
        result = send_wall_lines_to_max(
            package[
                "document"
            ],
            package[
                "walls"
            ],
            floor_name=(
                package[
                    "floor_name"
                ]
            ),
            floor_index=(
                package[
                    "floor_index"
                ]
            ),
            base_z_cm=(
                package[
                    "base_z_cm"
                ]
            ),
            wall_height_cm=(
                package[
                    "wall_height_cm"
                ]
            ),
            interfloor_cm=(
                package[
                    "interfloor_cm"
                ]
            ),
            pivot_source=(
                package[
                    "pivot_source"
                ]
            ),
        )

    except Exception as exc:
        _finish(
            window,
            success=False,
            message=(
                floor_name
                + " gönderimi durduruldu | "
                + str(exc)
            ),
        )
        return

    request_id = str(
        result[
            "request_id"
        ]
    )

    state[
        "current_request_id"
    ] = request_id

    state[
        "current_floor"
    ] = floor_name

    print(
        "REQUEST ID:",
        request_id,
    )
    print(
        "WAITING FOR MAX RESULT..."
    )

    _write_log(
        window
    )

    _watch_result(
        window,
        request_id,
        time.monotonic(),
    )


def start_floor_send(
    window,
    floor_names=None,
):
    current = getattr(
        window,
        "_max_floor_send_batch",
        None,
    )

    if (
        isinstance(current, dict)
        and current.get(
            "active",
            False,
        )
    ):
        raise RuntimeError(
            "Kat aktarımı zaten devam ediyor."
        )

    confirmed = (
        ordered_confirmed_floors(
            getattr(
                window,
                "_confirmed_floors",
                (),
            )
        )
    )

    if not confirmed:
        raise RuntimeError(
            "Onaylanmış kat planı yok."
        )

    by_index = _floor_by_index(
        confirmed
    )

    if floor_names is None:
        selected = confirmed
    else:
        wanted = {
            str(name)
            for name in floor_names
        }

        selected = [
            floor
            for floor in confirmed
            if floor["name"] in wanted
        ]

        missing = (
            wanted
            - {
                floor["name"]
                for floor in selected
            }
        )

        if missing:
            raise RuntimeError(
                "Onaylı kat bulunamadı: "
                + ", ".join(
                    sorted(missing)
                )
            )

    packages = [
        _prepare_floor_package(
            floor,
            by_index,
        )
        for floor in selected
    ]

    if not packages:
        raise RuntimeError(
            "Gönderilecek kat yok."
        )

    window._max_floor_send_batch = {
        "engine":
            ENGINE,

        "active":
            True,

        "cursor":
            0,

        "packages":
            packages,

        "results":
            [],

        "current_request_id":
            "",

        "current_floor":
            "",
    }

    button = getattr(
        window,
        "generate_3d_btn",
        None,
    )

    if button is not None:
        button.setEnabled(
            False
        )

        button.setText(
            "3D Oluşturuluyor..."
        )

    print("")
    print(
        "=== 3DCAD MULTI FLOOR MAX SEND START ==="
    )
    print(
        "ORDER:",
        " -> ".join(
            package[
                "floor_name"
            ]
            for package in packages
        ),
    )
    print(
        "FLOOR COUNT:",
        len(packages),
    )
    print(
        "NEXT FLOOR WAITS FOR PREVIOUS MAX SUCCESS"
    )
    print(
        "=== END START ==="
    )

    _write_log(
        window
    )

    _send_next_floor(
        window
    )

    return True
'''


# ============================================================
# MAXSCRIPT V2
# ============================================================

maxscript_text = r'''/*
3Dcad -> 3ds Max Wall Bridge V2

CAD_to_3D_Max proven floor transfer contract:
- each floor has its own CAD XY pivot
- CAD XY is made local by subtracting that pivot
- BASE_Z_CM controls world Z
- each floor has a separate Max node
- previous same-floor node is replaced only after new import succeeds
- result file confirms success before Python sends next floor
*/

global CAD3DcadBridgeTimer
global CAD3DcadBridgeLastRequestId = ""
global CAD3DcadScriptFile = getSourceFileName()
global CAD3DcadScriptDir = getFilenamePath CAD3DcadScriptFile
global CAD3DcadProjectRoot = pathConfig.appendPath CAD3DcadScriptDir ".."
global CAD3DcadRequestFile = pathConfig.appendPath CAD3DcadProjectRoot "data\cache\max_bridge\visible_cad_request.txt"
global CAD3DcadResultFile = pathConfig.appendPath CAD3DcadProjectRoot "data\cache\max_bridge\visible_cad_result.txt"


fn CAD3D_ReadRequestId filePath =
(
    if not (doesFileExist filePath) then return ""

    local stream = openFile filePath mode:"rt"
    if stream == undefined then return ""

    local header = readLine stream
    local result = ""

    while not (eof stream) do
    (
        local line = readLine stream

        if line != undefined then
        (
            if matchPattern line pattern:"REQUEST_ID=*" then
            (
                result = substring line 12 (line.count - 11)
                exit
            )
        )
    )

    close stream
    result
)


fn CAD3D_ReadOption lines prefix =
(
    for line in lines do
    (
        if matchPattern line pattern:(prefix + "*") then
        (
            return substring line (prefix.count + 1) (line.count - prefix.count)
        )
    )

    undefined
)


fn CAD3D_WriteResult requestId statusText messageText =
(
    local tempPath = CAD3DcadResultFile + ".tmp"
    local stream = createFile tempPath

    if stream == undefined then return false

    format "3DCAD_WALL_RESULT_V2\n" to:stream
    format "REQUEST_ID=%\n" requestId to:stream
    format "STATUS=%\n" statusText to:stream
    format "MESSAGE=%\n" messageText to:stream

    close stream

    if doesFileExist CAD3DcadResultFile do
    (
        deleteFile CAD3DcadResultFile
    )

    renameFile tempPath CAD3DcadResultFile
    true
)


fn CAD3D_CleanImportedSpline shapeNode =
(
    local weldTolerance = units.decodeValue "0.1mm"

    updateShape shapeNode

    for splineIndex = 1 to (numSplines shapeNode) do
    (
        local knotCount = numKnots shapeNode splineIndex

        if knotCount > 1 then
        (
            local knotSelection = #()

            for knotIndex = 1 to knotCount do
            (
                append knotSelection knotIndex
            )

            setKnotSelection shapeNode splineIndex knotSelection keep:false
        )
    )

    weldSpline shapeNode weldTolerance

    updateShape shapeNode

    for splineIndex = 1 to (numSplines shapeNode) do
    (
        setKnotSelection shapeNode splineIndex #() keep:false
    )

    updateShape shapeNode
)


fn CAD3D_ImportWalls filePath =
(
    if not (doesFileExist filePath) then return false

    local stream = openFile filePath mode:"rt"
    if stream == undefined then return false

    local header = readLine stream

    local isV1 = (header == "3DCAD_WALL_REQUEST_V1")
    local isV2 = (header == "3DCAD_WALL_REQUEST_V2")

    if not isV1 and not isV2 then
    (
        close stream
        format "3Dcad bridge: invalid request header.\n"
        return false
    )

    local rows = #()

    while not (eof stream) do
    (
        local line = readLine stream

        if line != undefined and line != "" do
        (
            append rows line
        )
    )

    close stream

    local requestId = CAD3D_ReadOption rows "REQUEST_ID="
    local pivotXText = CAD3D_ReadOption rows "PIVOT_X_MM="
    local pivotYText = CAD3D_ReadOption rows "PIVOT_Y_MM="

    if requestId == undefined then
    (
        format "3Dcad bridge: request id missing.\n"
        return false
    )

    if pivotXText == undefined or pivotYText == undefined then
    (
        format "3Dcad bridge: pivot metadata missing.\n"
        return false
    )

    local pivotX = pivotXText as float
    local pivotY = pivotYText as float

    local floorName = ""
    local floorIndexText = ""
    local baseZ = 0.0
    local heightCm = 0.0
    local interfloorCm = 0.0
    local nodeName = "3Dcad_Walls"

    if isV2 then
    (
        local floorNameText = CAD3D_ReadOption rows "FLOOR_NAME="
        local floorIndexValue = CAD3D_ReadOption rows "FLOOR_INDEX="
        local baseZText = CAD3D_ReadOption rows "BASE_Z_CM="
        local heightText = CAD3D_ReadOption rows "HEIGHT_CM="
        local interfloorText = CAD3D_ReadOption rows "INTERFLOOR_CM="
        local nodeNameText = CAD3D_ReadOption rows "NODE_NAME="

        if floorNameText != undefined do floorName = floorNameText
        if floorIndexValue != undefined do floorIndexText = floorIndexValue
        if baseZText != undefined do baseZ = baseZText as float
        if heightText != undefined do heightCm = heightText as float
        if interfloorText != undefined do interfloorCm = interfloorText as float
        if nodeNameText != undefined do nodeName = nodeNameText
    )

    local tempNodeName = "__3Dcad_TEMP_" + requestId
    local staleTemp = getNodeByName tempNodeName

    if staleTemp != undefined do
    (
        delete staleTemp
    )

    local shapeNode = splineShape name:tempNodeName
    shapeNode.wirecolor = color 0 140 255

    local splineCount = 0
    local mmUnit = units.decodeValue "1mm"
    local cmUnit = units.decodeValue "1cm"

    for line in rows do
    (
        if matchPattern line pattern:"S|*" then
        (
            local parts = filterString line "|"

            if parts.count >= 3 then
            (
                local closedFlag = parts[2] as integer
                local pointsText = parts[3]
                local pointRows = filterString pointsText ";"

                if pointRows.count >= 2 then
                (
                    addNewSpline shapeNode
                    splineCount += 1

                    for pointText in pointRows do
                    (
                        local xy = filterString pointText ","

                        if xy.count >= 2 then
                        (
                            local xMM = xy[1] as float
                            local yMM = xy[2] as float

                            local localX = (xMM - pivotX) * mmUnit
                            local localY = (yMM - pivotY) * mmUnit

                            addKnot shapeNode splineCount #corner #line [localX,localY,0]
                        )
                    )

                    if closedFlag == 1 do
                    (
                        close shapeNode splineCount
                    )
                )
            )
        )
    )

    if splineCount <= 0 then
    (
        delete shapeNode
        format "3Dcad bridge: no wall splines.\n"
        return false
    )

    updateShape shapeNode

    shapeNode.position = [
        0,
        0,
        baseZ * cmUnit
    ]

    try
    (
        setUserProp shapeNode "FloorName" floorName
        setUserProp shapeNode "FloorIndex" floorIndexText
        setUserProp shapeNode "BaseZCm" (baseZ as string)
        setUserProp shapeNode "WallHeightCm" (heightCm as string)
        setUserProp shapeNode "InterfloorCm" (interfloorCm as string)
        setUserProp shapeNode "PivotXMM" (pivotX as string)
        setUserProp shapeNode "PivotYMM" (pivotY as string)
    )
    catch()

    local oldNode = getNodeByName nodeName

    if oldNode != undefined and oldNode != shapeNode do
    (
        delete oldNode
    )

    shapeNode.name = nodeName

    select shapeNode
    completeRedraw()

    format "\n"
    format "========================================\n"
    format "3Dcad WALL BRIDGE V2\n"
    format "Floor        : %\n" floorName
    format "Floor index  : %\n" floorIndexText
    format "Node         : %\n" nodeName
    format "Wall splines : %\n" splineCount
    format "Pivot CAD mm : X=% Y=%\n" pivotX pivotY
    format "BASE Z cm    : %\n" baseZ
    format "Wall height  : % cm\n" heightCm
    format "Interfloor   : % cm\n" interfloorCm
    format "Node world   : 0,0,% cm\n" baseZ
    format "========================================\n"
    format "\n"

    true
)


fn CAD3D_OnTick sender args =
(
    local requestId = CAD3D_ReadRequestId CAD3DcadRequestFile

    if requestId != "" and requestId != CAD3DcadBridgeLastRequestId then
    (
        CAD3DcadBridgeLastRequestId = requestId

        try
        (
            local ok = CAD3D_ImportWalls CAD3DcadRequestFile

            if ok then
            (
                CAD3D_WriteResult requestId "OK" "OK"
            )
            else
            (
                CAD3D_WriteResult requestId "ERROR" "IMPORT_FAILED"
            )
        )
        catch
        (
            format "\n3Dcad bridge ERROR:\n%\n" (getCurrentException())
            CAD3D_WriteResult requestId "ERROR" "MAXSCRIPT_EXCEPTION"
        )
    )
)


try
(
    if CAD3DcadBridgeTimer != undefined do
    (
        CAD3DcadBridgeTimer.Stop()
    )
)
catch()


CAD3DcadBridgeLastRequestId = CAD3D_ReadRequestId CAD3DcadRequestFile

CAD3DcadBridgeTimer = dotNetObject "System.Windows.Forms.Timer"
CAD3DcadBridgeTimer.Interval = 500

dotNet.addEventHandler CAD3DcadBridgeTimer "Tick" CAD3D_OnTick
CAD3DcadBridgeTimer.Start()


format "\n"
format "========================================\n"
format "3Dcad MAX BRIDGE ACTIVE V2 - MULTI FLOOR\n"
format "Request: %\n" CAD3DcadRequestFile
format "Result : %\n" CAD3DcadResultFile
format "========================================\n"
format "\n"
'''


# ============================================================
# MAIN WINDOW: REPLACE ONLY _create_3d
# ============================================================

main_text = MAIN.read_text(
    encoding="utf-8-sig"
)

tree = ast.parse(main_text)

main_class = next(
    node
    for node in tree.body
    if isinstance(node, ast.ClassDef)
    and node.name == "MainWindow"
)

create_node = next(
    (
        node
        for node in main_class.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_create_3d"
    ),
    None,
)

if create_node is None:
    raise RuntimeError(
        "_create_3d bulunamadi. HICBIR DOSYA DEGISTIRILMEDI."
    )


new_create_3d = r'''    def _create_3d(self) -> None:
        confirmed = [
            row
            for row in (
                getattr(
                    self,
                    "_confirmed_floors",
                    (),
                )
                or ()
            )
            if isinstance(
                row,
                dict,
            )
        ]

        # Onaylanmis katlar varsa CAD_to_3D_Max
        # multi-floor transfer menu kullanilir.
        if confirmed:
            from PySide6.QtWidgets import (
                QMenu,
            )

            from export.multi_floor_max_send import (
                ordered_confirmed_floors,
                start_floor_send,
            )

            try:
                ordered = (
                    ordered_confirmed_floors(
                        confirmed
                    )
                )
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Kat Aktarım Hatası",
                    str(exc),
                )
                return

            menu = QMenu(self)

            menu.setStyleSheet(
                """
                QMenu {
                    background-color: #1d1f20;
                    color: #e6e6e6;
                    border: 1px solid #343434;
                    padding: 4px;
                }

                QMenu::item {
                    padding: 6px 24px 6px 10px;
                }

                QMenu::item:selected {
                    background-color: #2a2c2d;
                }

                QMenu::separator {
                    height: 1px;
                    background: #343434;
                    margin: 4px 6px;
                }
                """
            )

            def launch(
                names,
            ):
                try:
                    start_floor_send(
                        self,
                        names,
                    )
                except Exception as exc:
                    QMessageBox.critical(
                        self,
                        "3D Oluştur Hatası",
                        str(exc),
                    )

            for floor in ordered:
                floor_name = str(
                    floor[
                        "name"
                    ]
                )

                action = menu.addAction(
                    floor_name
                )

                action.triggered.connect(
                    lambda checked=False,
                    name=floor_name:
                        launch(
                            (name,)
                        )
                )

            if len(ordered) > 0:
                menu.addSeparator()

            all_action = menu.addAction(
                "Tüm Katları Gönder"
            )

            all_action.triggered.connect(
                lambda checked=False:
                    launch(None)
            )

            button = self.generate_3d_btn

            menu.exec(
                button.mapToGlobal(
                    button.rect().bottomLeft()
                )
            )

            return

        # Hic kat onaylanmadiysa mevcut tek-plan
        # transfer davranisi aynen korunur.
        document = self._selected_document

        if document is None:
            QMessageBox.warning(
                self,
                "3D Oluştur",
                "Önce Plan Seç ile çalışma alanını seçin.",
            )
            return

        walls = tuple(
            getattr(
                self,
                "_selected_wall_candidates",
                (),
            )
            or ()
        )

        if not walls:
            QMessageBox.warning(
                self,
                "3D Oluştur",
                "Gönderilecek seçilmiş duvar bulunamadı.",
            )
            return

        try:
            result = send_wall_lines_to_max(
                document,
                walls,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "3D Oluştur Hatası",
                str(exc),
            )
            return

        self.statusBar().showMessage(
            "3D Oluştur - "
            f"{result['wall_count']} duvar çizgisi Max'e gönderildi | "
            f"Pivot X={result['pivot_x_mm']:.3f} mm "
            f"Y={result['pivot_y_mm']:.3f} mm"
        )
'''


main_lines = main_text.splitlines(
    keepends=True
)

replacement = (
    new_create_3d.rstrip()
    + "\n"
)

main_lines[
    create_node.lineno - 1:
    create_node.end_lineno
] = [replacement]

patched_main = "".join(
    main_lines
)

# Her seyi yazmadan once Python syntax kontrolu.
compile(
    bridge_text,
    "max_bridge.py",
    "exec",
)

compile(
    multi_text,
    "multi_floor_max_send.py",
    "exec",
)

compile(
    patched_main,
    "main_window.py",
    "exec",
)

# Syntax basarili. Simdi yaz.
BRIDGE.write_text(
    bridge_text,
    encoding="utf-8",
)

MULTI.write_text(
    multi_text,
    encoding="utf-8",
)

MAXSCRIPT.write_text(
    maxscript_text,
    encoding="utf-8",
)

MAIN.write_text(
    patched_main,
    encoding="utf-8",
)

print("")
print("CAD_TO_3D_MAX FLOOR TRANSFER PORT V1 INSTALLED")
print("")
print("CORE RULES:")
print("  EACH FLOOR = OWN CAD BOUNDS CENTER PIVOT")
print("  GROUND BASE_Z = 0")
print("  UPPER BASE_Z = LOWER HEIGHTS + CURRENT/INTERMEDIATE GAPS")
print("  BASEMENT BASE_Z = NEGATIVE STACK")
print("  SINGLE FLOOR SEND = ENABLED")
print("  ALL FLOORS SEND = ENABLED")
print("  NEXT FLOOR WAITS FOR PREVIOUS MAX SUCCESS")
print("  SAME FLOOR MAX NODE REPLACED ONLY AFTER NEW IMPORT")
print("")
print("WALL DETECTOR = UNCHANGED")
print("DOOR DETECTOR = UNCHANGED")
print("WINDOW DETECTOR = UNCHANGED")
print("CAD VIEW = UNCHANGED")
print("")
