from pathlib import Path

ROOT = Path.cwd()

MAIN = ROOT / "src" / "ui" / "main_window.py"
MULTI = ROOT / "src" / "export" / "multi_floor_max_send.py"
CONTROLLER = ROOT / "src" / "ui" / "floor_pivot_controller.py"

main = MAIN.read_text(encoding="utf-8-sig")
multi = MULTI.read_text(encoding="utf-8-sig")

if "MANUAL_FLOOR_PIVOT_V1" in main:
    raise RuntimeError(
        "MANUAL_FLOOR_PIVOT_V1 zaten kurulu. DOSYALARA DOKUNULMADI."
    )


def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(
            f"{label} bulunamadi. DOSYALARA DOKUNULMADI."
        )

    return text.replace(old, new, 1)


# ============================================================
# 1. FLOOR PIVOT CONTROLLER
#    CadGraphicsView DEĞİŞTİRİLMİYOR.
# ============================================================

controller = r'''from __future__ import annotations

from PySide6.QtCore import (
    QEvent,
    QObject,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsView,
)


class FloorPivotController(QObject):
    """
    MANUAL_FLOOR_PIVOT_V1

    CAD_to_3D_Max davranisi:
    - kullanici pivotu CAD gorunumunden secer
    - 14 ekran pikseli snap yaricapi
    - vertex + segment snap
    - bas-surukle-birak
    - birakildiginda CAD X/Y commit edilir

    CadGraphicsView koordinat sistemi:
        CAD X -> scene X
        CAD Y -> -scene Y
    """

    pivot_committed = Signal(
        float,
        float,
        str,
    )

    SNAP_RADIUS_PX = 14.0

    def __init__(
        self,
        view,
    ) -> None:
        super().__init__(view)

        self.view = view

        self.active = False
        self.dragging = False

        self.document = None
        self.point = None
        self.snap_kind = ""

        self._vertices = ()
        self._segments = ()

        self._marker = None

        self._previous_drag_mode = (
            QGraphicsView.DragMode.ScrollHandDrag
        )

        self._previous_mouse_tracking = False

        self.view.viewport().installEventFilter(
            self
        )

    # --------------------------------------------------------
    # SNAP GEOMETRY
    # --------------------------------------------------------

    def _build_snap_geometry(
        self,
        document,
    ) -> None:
        vertices = []
        segments = []

        for primitive in (
            getattr(
                document,
                "primitives",
                (),
            )
            or ()
        ):
            points = []

            for point in (
                getattr(
                    primitive,
                    "points",
                    (),
                )
                or ()
            ):
                try:
                    points.append(
                        (
                            float(point[0]),
                            float(point[1]),
                        )
                    )
                except Exception:
                    continue

            if not points:
                continue

            vertices.extend(points)

            for index in range(
                len(points) - 1
            ):
                segments.append(
                    (
                        points[index],
                        points[index + 1],
                    )
                )

            if (
                bool(
                    getattr(
                        primitive,
                        "closed",
                        False,
                    )
                )
                and len(points) > 2
            ):
                segments.append(
                    (
                        points[-1],
                        points[0],
                    )
                )

        self._vertices = tuple(vertices)
        self._segments = tuple(segments)

    @staticmethod
    def _distance_sq(
        a,
        b,
    ) -> float:
        dx = (
            float(a[0])
            - float(b[0])
        )

        dy = (
            float(a[1])
            - float(b[1])
        )

        return (
            dx * dx
            + dy * dy
        )

    @staticmethod
    def _project_to_segment(
        point,
        a,
        b,
    ):
        px, py = point
        ax, ay = a
        bx, by = b

        dx = bx - ax
        dy = by - ay

        length_sq = (
            dx * dx
            + dy * dy
        )

        if length_sq <= 1.0e-20:
            return (
                float(ax),
                float(ay),
            )

        t = (
            (
                (px - ax) * dx
                + (py - ay) * dy
            )
            / length_sq
        )

        t = max(
            0.0,
            min(
                1.0,
                t,
            ),
        )

        return (
            ax + dx * t,
            ay + dy * t,
        )

    def _scene_units_per_pixel(
        self,
    ) -> float:
        transform = self.view.transform()

        scale = max(
            abs(
                float(
                    transform.m11()
                )
            ),
            abs(
                float(
                    transform.m22()
                )
            ),
            1.0e-12,
        )

        return 1.0 / scale

    def _snap(
        self,
        raw_point,
    ):
        radius = (
            self.SNAP_RADIUS_PX
            * self._scene_units_per_pixel()
        )

        radius_sq = (
            radius * radius
        )

        best_point = raw_point
        best_kind = "free"
        best_distance = float("inf")

        # Vertex once kontrol edilir.
        for point in self._vertices:
            distance = self._distance_sq(
                raw_point,
                point,
            )

            if distance < best_distance:
                best_distance = distance
                best_point = point
                best_kind = "vertex"

        # Sonra segment govdesi.
        for a, b in self._segments:
            projected = (
                self._project_to_segment(
                    raw_point,
                    a,
                    b,
                )
            )

            distance = self._distance_sq(
                raw_point,
                projected,
            )

            if distance < best_distance:
                best_distance = distance
                best_point = projected
                best_kind = "segment"

        if best_distance <= radius_sq:
            return (
                (
                    float(best_point[0]),
                    float(best_point[1]),
                ),
                best_kind,
            )

        return (
            (
                float(raw_point[0]),
                float(raw_point[1]),
            ),
            "free",
        )

    # --------------------------------------------------------
    # COORDINATE
    # --------------------------------------------------------

    def _cad_point_from_event(
        self,
        event,
    ):
        scene_point = self.view.mapToScene(
            event.position().toPoint()
        )

        return (
            float(
                scene_point.x()
            ),
            float(
                -scene_point.y()
            ),
        )

    # --------------------------------------------------------
    # MARKER
    # --------------------------------------------------------

    def _remove_marker(
        self,
    ) -> None:
        marker = self._marker
        self._marker = None

        if marker is None:
            return

        try:
            scene = marker.scene()

            if scene is not None:
                scene.removeItem(
                    marker
                )

        except RuntimeError:
            pass

    def _draw_marker(
        self,
        point,
    ) -> None:
        if point is None:
            self._remove_marker()
            return

        scene = self.view.scene()

        if scene is None:
            return

        if self._marker is not None:
            try:
                if (
                    self._marker.scene()
                    is not scene
                ):
                    self._marker = None
            except RuntimeError:
                self._marker = None

        scene_per_pixel = (
            self._scene_units_per_pixel()
        )

        radius = (
            5.0
            * scene_per_pixel
        )

        arm = (
            10.0
            * scene_per_pixel
        )

        path = QPainterPath()

        path.addEllipse(
            QRectF(
                -radius,
                -radius,
                radius * 2.0,
                radius * 2.0,
            )
        )

        path.moveTo(
            -arm,
            0.0,
        )

        path.lineTo(
            arm,
            0.0,
        )

        path.moveTo(
            0.0,
            -arm,
        )

        path.lineTo(
            0.0,
            arm,
        )

        if self._marker is None:
            marker = QGraphicsPathItem()

            pen = QPen(
                QColor("#ffffff")
            )

            pen.setCosmetic(True)
            pen.setWidthF(2.0)

            marker.setPen(pen)
            marker.setBrush(
                Qt.BrushStyle.NoBrush
            )

            marker.setZValue(
                4000000
            )

            scene.addItem(marker)

            self._marker = marker

        self._marker.setPath(path)

        self._marker.setPos(
            float(point[0]),
            float(-point[1]),
        )

        self._marker.setVisible(True)

    def show_point(
        self,
        point,
    ) -> None:
        if point is None:
            self.point = None
            self._remove_marker()
            return

        self.point = (
            float(point[0]),
            float(point[1]),
        )

        self._draw_marker(
            self.point
        )

    # --------------------------------------------------------
    # MODE
    # --------------------------------------------------------

    def begin(
        self,
        document,
        current_point=None,
    ) -> None:
        if document is None:
            raise RuntimeError(
                "Kat CAD verisi bulunamadi."
            )

        self.finish(
            clear_marker=True
        )

        self.document = document

        self._build_snap_geometry(
            document
        )

        self.active = True
        self.dragging = False

        self._previous_drag_mode = (
            self.view.dragMode()
        )

        viewport = self.view.viewport()

        self._previous_mouse_tracking = (
            viewport.hasMouseTracking()
        )

        viewport.setMouseTracking(
            True
        )

        self.view.setDragMode(
            QGraphicsView.DragMode.NoDrag
        )

        self.view.setCursor(
            Qt.CursorShape.CrossCursor
        )

        if current_point is not None:
            self.show_point(
                current_point
            )

    def finish(
        self,
        *,
        clear_marker=False,
    ) -> None:
        was_active = self.active

        self.active = False
        self.dragging = False

        if was_active:
            try:
                self.view.setDragMode(
                    self._previous_drag_mode
                )
            except Exception:
                self.view.setDragMode(
                    QGraphicsView.DragMode.ScrollHandDrag
                )

            try:
                self.view.viewport().setMouseTracking(
                    self._previous_mouse_tracking
                )
            except Exception:
                pass

            self.view.unsetCursor()

        if clear_marker:
            self._remove_marker()

    # --------------------------------------------------------
    # EVENTS
    # --------------------------------------------------------

    def eventFilter(
        self,
        obj,
        event,
    ):
        if (
            not self.active
            or obj
            is not self.view.viewport()
        ):
            return False

        event_type = event.type()

        if (
            event_type
            == QEvent.Type.MouseButtonPress
            and event.button()
            == Qt.MouseButton.LeftButton
        ):
            raw_point = (
                self._cad_point_from_event(
                    event
                )
            )

            point, snap_kind = (
                self._snap(
                    raw_point
                )
            )

            self.point = point
            self.snap_kind = snap_kind
            self.dragging = True

            self._draw_marker(
                point
            )

            self.view.setCursor(
                Qt.CursorShape.SizeAllCursor
            )

            event.accept()
            return True

        if (
            event_type
            == QEvent.Type.MouseMove
        ):
            raw_point = (
                self._cad_point_from_event(
                    event
                )
            )

            point, snap_kind = (
                self._snap(
                    raw_point
                )
            )

            self.snap_kind = snap_kind

            if self.dragging:
                self.point = point

            self._draw_marker(
                point
            )

            event.accept()
            return True

        if (
            event_type
            == QEvent.Type.MouseButtonRelease
            and event.button()
            == Qt.MouseButton.LeftButton
            and self.dragging
        ):
            raw_point = (
                self._cad_point_from_event(
                    event
                )
            )

            point, snap_kind = (
                self._snap(
                    raw_point
                )
            )

            self.point = point
            self.snap_kind = snap_kind
            self.dragging = False

            self._draw_marker(
                point
            )

            self.finish(
                clear_marker=False
            )

            self.pivot_committed.emit(
                float(point[0]),
                float(point[1]),
                str(snap_kind),
            )

            event.accept()
            return True

        return False
'''


# ============================================================
# 2. main_window.py
# ============================================================

main = replace_once(
    main,
    '''        self._active_floor_document = None

        self._plan_view_active = False
''',
    '''        self._active_floor_document = None
        self._active_floor_bounds = None

        # MANUAL_FLOOR_PIVOT_V1
        self._active_floor_pivot = None
        self._active_floor_pivot_snap = ""
        self._floor_pivot_controller = None

        self._plan_view_active = False
''',
    "MainWindow pivot state anchor",
)


# Gercek Kat Ayarlari layout'una,
# Planı Onayla'nın hemen önüne eklenir.
confirm_anchor = (
    '        self.confirm_floor_btn = QPushButton('
)

confirm_pos = main.find(
    confirm_anchor
)

if confirm_pos < 0:
    raise RuntimeError(
        "confirm_floor_btn anchor bulunamadi. DOSYALARA DOKUNULMADI."
    )

pivot_button_code = '''        # MANUAL_FLOOR_PIVOT_V1
        self.pivot_floor_btn = QPushButton("Pivot Belirle")
        self.pivot_floor_btn.clicked.connect(
            self._start_floor_pivot_selection
        )
        floor_layout.addWidget(
            self.pivot_floor_btn
        )

'''

main = (
    main[:confirm_pos]
    + pivot_button_code
    + main[confirm_pos:]
)


# Pivot metodlari, confirm metodunun hemen once.
method_anchor = (
    "    def _confirm_floor_plan(self) -> None:\n"
)

if method_anchor not in main:
    raise RuntimeError(
        "_confirm_floor_plan anchor bulunamadi. DOSYALARA DOKUNULMADI."
    )

pivot_methods = r'''    # ====================================================
    # MANUAL_FLOOR_PIVOT_V1
    # ====================================================

    @staticmethod
    def _floor_pivot_bounds_key(
        bounds,
    ):
        if not (
            isinstance(
                bounds,
                (tuple, list),
            )
            and len(bounds) == 4
        ):
            return None

        try:
            return tuple(
                round(
                    float(value),
                    6,
                )
                for value in bounds
            )
        except Exception:
            return None

    def _cancel_floor_pivot_selection(
        self,
        *,
        clear_marker=True,
    ) -> None:
        controller = getattr(
            self,
            "_floor_pivot_controller",
            None,
        )

        if controller is not None:
            controller.finish(
                clear_marker=bool(
                    clear_marker
                )
            )

    def _sync_active_floor_pivot(
        self,
    ) -> None:
        self._cancel_floor_pivot_selection(
            clear_marker=True
        )

        self._active_floor_pivot = None
        self._active_floor_pivot_snap = ""

        bounds = getattr(
            self,
            "_active_floor_bounds",
            None,
        )

        key = (
            self._floor_pivot_bounds_key(
                bounds
            )
        )

        if key is None:
            return

        for floor in (
            getattr(
                self,
                "_confirmed_floors",
                (),
            )
            or ()
        ):
            if not isinstance(
                floor,
                dict,
            ):
                continue

            existing_key = (
                self._floor_pivot_bounds_key(
                    floor.get(
                        "bounds"
                    )
                )
            )

            if existing_key != key:
                continue

            pivot = floor.get(
                "pivot_source"
            )

            if (
                isinstance(
                    pivot,
                    (tuple, list),
                )
                and len(pivot) == 2
            ):
                self._active_floor_pivot = (
                    float(pivot[0]),
                    float(pivot[1]),
                )

                self._active_floor_pivot_snap = str(
                    floor.get(
                        "pivot_snap_kind",
                        "",
                    )
                    or ""
                )

            break

        controller = getattr(
            self,
            "_floor_pivot_controller",
            None,
        )

        if (
            controller is not None
            and self._active_floor_pivot
            is not None
        ):
            controller.show_point(
                self._active_floor_pivot
            )

    def _start_floor_pivot_selection(
        self,
    ) -> None:
        floor_document = getattr(
            self,
            "_active_floor_document",
            None,
        )

        bounds = getattr(
            self,
            "_active_floor_bounds",
            None,
        )

        if (
            floor_document is None
            or self._floor_pivot_bounds_key(
                bounds
            )
            is None
        ):
            QMessageBox.warning(
                self,
                "Pivot",
                "Önce Plan Seç ile bir kat planı seçin.",
            )
            return

        controller = getattr(
            self,
            "_floor_pivot_controller",
            None,
        )

        if controller is None:
            from ui.floor_pivot_controller import (
                FloorPivotController,
            )

            controller = FloorPivotController(
                self.view
            )

            controller.pivot_committed.connect(
                self._commit_floor_pivot
            )

            self._floor_pivot_controller = (
                controller
            )

        controller.begin(
            floor_document,
            current_point=getattr(
                self,
                "_active_floor_pivot",
                None,
            ),
        )

        self.statusBar().showMessage(
            "Pivot Belirle — katlar arasında aynı mimari referans noktasını seçip bırakın"
        )

    def _commit_floor_pivot(
        self,
        x: float,
        y: float,
        snap_kind: str,
    ) -> None:
        self._active_floor_pivot = (
            float(x),
            float(y),
        )

        self._active_floor_pivot_snap = str(
            snap_kind
            or "free"
        )

        self.statusBar().showMessage(
            "Pivot kaydedildi | "
            f"X={float(x):.3f} "
            f"Y={float(y):.3f} | "
            f"Snap={self._active_floor_pivot_snap}"
        )

'''

main = main.replace(
    method_anchor,
    pivot_methods + method_anchor,
    1,
)


# Plan Onayla: pivot secilmemisse onay yok.
main = replace_once(
    main,
    '''        floor_data = {
''',
    '''        pivot = getattr(
            self,
            "_active_floor_pivot",
            None,
        )

        if not (
            isinstance(
                pivot,
                (tuple, list),
            )
            and len(pivot) == 2
        ):
            QMessageBox.warning(
                self,
                "Pivot",
                "Önce Pivot Belirle ile bu katın referans noktasını seçin.",
            )
            return

        floor_data = {
''',
    "floor_data pivot validation",
)


# Pivot bilgisi confirmed floor kaydina girer.
main = replace_once(
    main,
    '''            "document": floor_document,
        }
''',
    '''            "document": floor_document,
            "pivot_source": (
                float(pivot[0]),
                float(pivot[1]),
            ),
            "pivot_snap_kind": str(
                getattr(
                    self,
                    "_active_floor_pivot_snap",
                    "",
                )
                or ""
            ),
            "pivot_master": (
                floor_name == "Giriş Kat"
            ),
        }
''',
    "confirmed floor pivot fields",
)


# Kat plani secilince o katin daha once kaydedilmis
# pivotu varsa geri yüklenir.
main = replace_once(
    main,
    '''            self.floor_panel.setVisible(True)
            self.floor_panel.setEnabled(True)
''',
    '''            self._sync_active_floor_pivot()

            self.floor_panel.setVisible(True)
            self.floor_panel.setEnabled(True)
''',
    "active floor pivot restore",
)


# Plan onaylandiktan sonra gecici aktif state temizlenir.
main = replace_once(
    main,
    '''        self._active_floor_document = None
        self._active_floor_bounds = None
        self._floor_selection_mode = False

        self.floor_panel.setVisible(False)
''',
    '''        self._active_floor_document = None
        self._active_floor_bounds = None
        self._active_floor_pivot = None
        self._active_floor_pivot_snap = ""
        self._floor_selection_mode = False

        self.floor_panel.setVisible(False)
''',
    "confirmed floor active pivot clear",
)


# Yeni Plan Sec moduna girmeden aktif pivot drag iptal edilir.
main = replace_once(
    main,
    '''        if self._full_document is None:
            return

        # ----------------------------------------------------
        # KAT ATAMA SECIMI
''',
    '''        if self._full_document is None:
            return

        self._cancel_floor_pivot_selection(
            clear_marker=True
        )

        # ----------------------------------------------------
        # KAT ATAMA SECIMI
''',
    "plan selection pivot cancel",
)


# Ana menuye donerken event filter aktif kalmasin.
main = replace_once(
    main,
    '''        # Ana plan secim durumuna don.
        self._selected_document = None
''',
    '''        self._cancel_floor_pivot_selection(
            clear_marker=True
        )

        # Ana plan secim durumuna don.
        self._selected_document = None
''',
    "main menu pivot cancel",
)


# CAD temizlenirken pivot state de temizlenir.
main = replace_once(
    main,
    '''    def clear_cad(self) -> None:
        self._set_main_cad_action_buttons_enabled(False)
''',
    '''    def clear_cad(self) -> None:
        self._cancel_floor_pivot_selection(
            clear_marker=True
        )
        self._active_floor_pivot = None
        self._active_floor_pivot_snap = ""

        self._set_main_cad_action_buttons_enabled(False)
''',
    "clear cad pivot reset",
)


# ============================================================
# 3. multi_floor_max_send.py
#
# Otomatik bounds-center pivot KALDIRILIR.
# Kaydedilen kullanici pivotu kullanilir.
# ============================================================

multi = replace_once(
    multi,
    '''    x0, y0, x1, y1 = bounds

    pivot_source = (
        (x0 + x1) * 0.5,
        (y0 + y1) * 0.5,
    )
''',
    '''    # MANUAL_FLOOR_PIVOT_V1
    raw_pivot = floor.get(
        "pivot_source"
    )

    if not (
        isinstance(
            raw_pivot,
            (tuple, list),
        )
        and len(raw_pivot) == 2
    ):
        raise RuntimeError(
            name
            + ": pivot belirlenmemiş. "
            + "Kat Ayarları > Pivot Belirle kullanın."
        )

    try:
        pivot_source = (
            float(raw_pivot[0]),
            float(raw_pivot[1]),
        )
    except Exception as exc:
        raise RuntimeError(
            name
            + ": kayıtlı pivot değeri geçersiz."
        ) from exc
''',
    "automatic pivot source",
)

multi = multi.replace(
    '"AUTO PIVOT SOURCE:"',
    '"USER PIVOT SOURCE:"',
    1,
)


# ============================================================
# VALIDATION BEFORE WRITE
# ============================================================

compile(
    controller,
    str(CONTROLLER),
    "exec",
)

compile(
    main,
    str(MAIN),
    "exec",
)

compile(
    multi,
    str(MULTI),
    "exec",
)


# ============================================================
# WRITE
# ============================================================

CONTROLLER.write_text(
    controller,
    encoding="utf-8",
)

MAIN.write_text(
    main,
    encoding="utf-8",
)

MULTI.write_text(
    multi,
    encoding="utf-8",
)

print("")
print("MANUAL_FLOOR_PIVOT_V1 INSTALLED")
print("")
print("Kat Ayarlari:")
print("  Duvar Yuksekligi")
print("  Pivot Belirle")
print("  Plani Onayla")
print("")
print("Pivot:")
print("  User selected CAD X/Y")
print("  Vertex + segment snap")
print("  Snap radius = 14 screen px")
print("  Per-floor pivot storage")
print("")
print("Export:")
print("  Automatic bounds-center pivot REMOVED")
print("  Saved user pivot ENABLED")
print("")
print("UNCHANGED:")
print("  cad_view.py")
print("  wall_detector.py")
print("  door_detector.py")
print("  window_detector.py")
print("  max_bridge.py")
print("  3DCAD_BRIDGE.ms")
print("  BASE_Z logic")
print("")
