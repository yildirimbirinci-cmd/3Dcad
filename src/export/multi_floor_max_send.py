from __future__ import annotations

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

    raw_pivot = floor.get(
        "pivot_source"
    )

    if (
        not isinstance(
            raw_pivot,
            (tuple, list),
        )
        or len(raw_pivot) < 2
    ):
        raise RuntimeError(
            name
            + ": pivot belirlenmedi."
        )

    try:
        pivot_source = (
            float(raw_pivot[0]),
            float(raw_pivot[1]),
        )
    except (
        TypeError,
        ValueError,
        IndexError,
    ) as exc:
        raise RuntimeError(
            name
            + ": pivot bilgisi gecersiz."
        ) from exc

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

        # CAD3D_CONNECT_REQUEST_PIPELINE_V1
        "doors":
            doors,

        "windows":
            windows,

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
        "USER PIVOT SOURCE:",
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

    # CAD3D_CONNECT_REQUEST_PIPELINE_V1
    from export.connect_levels_runtime import (
        collect_connect_levels,
    )

    connect_levels_cm = collect_connect_levels(
        window,
        package,
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
            connect_levels_cm=(
                connect_levels_cm
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
