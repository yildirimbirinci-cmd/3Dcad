from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cad.loader import CadLoadError, CadLoader
from cad.plan_selection import crop_document
from cad.window_detector import detect_window_family
from cad.door_detector import detect_interior_doors
from cad.wall_detector import detect_walls
from ui.cad_view import CadGraphicsView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("3Dcad")
        self.resize(1500, 900)
        self.setMinimumSize(1000, 650)

        self._loader = CadLoader(flattening_distance=0.5)
        self._current_path: Path | None = None
        self._full_document = None
        self._selected_document = None

        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(285)

        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 18, 18, 18)
        side.setSpacing(10)

        title = QLabel("3Dcad")
        title.setObjectName("title")

        subtitle = QLabel("Mimari CAD → 3B")
        subtitle.setStyleSheet("color:#858585;")

        side.addWidget(title)
        side.addWidget(subtitle)
        side.addSpacing(14)

        self.view = CadGraphicsView()
        self.view.plan_area_selected.connect(self._apply_plan_selection)

        load_btn = QPushButton("Mimari CAD Ekle")
        load_btn.setObjectName("primary")
        load_btn.clicked.connect(self.open_cad)

        self.plan_btn = QPushButton("Plan Seç")
        self.plan_btn.setEnabled(False)
        self.plan_btn.clicked.connect(self._begin_plan_selection)

        self.interior_door_btn = QPushButton("İç Kapı")

        self.interior_door_btn.setEnabled(True)
        self.interior_door_btn.clicked.connect(self._detect_interior_doors)

        self.wall_btn = QPushButton("Duvar")
        self.wall_btn.setEnabled(True)
        self.wall_btn.clicked.connect(self._detect_walls)
        self.window_btn = QPushButton("Pencere")
        self.window_btn.setEnabled(False)
        self.window_btn.clicked.connect(self._detect_window_family)

        sliding_door_btn = QPushButton("Sürgü Kapı")
        entrance_door_btn = QPushButton("Giriş Kapısı")

        fit_btn = QPushButton("Görünüme Sığdır")
        fit_btn.clicked.connect(self.view.fit_all)

        clear_btn = QPushButton("CAD'i Temizle")
        clear_btn.clicked.connect(self.clear_cad)

        side.addWidget(load_btn)
        side.addWidget(self.plan_btn)
        side.addWidget(self.interior_door_btn)
        side.addWidget(self.wall_btn)
        side.addWidget(self.window_btn)
        side.addWidget(sliding_door_btn)
        side.addWidget(entrance_door_btn)
        side.addWidget(fit_btn)
        side.addWidget(clear_btn)
        side.addSpacing(16)

        section = QLabel("DOSYA BİLGİSİ")
        section.setObjectName("sectionTitle")
        side.addWidget(section)

        self.file_label = QLabel("Henüz CAD yüklenmedi")
        self.file_label.setWordWrap(True)
        self.file_label.setStyleSheet("color:#9d9d9d;")
        side.addWidget(self.file_label)

        side.addSpacing(8)

        section2 = QLabel("CAD ÖĖZETİ")
        section2.setObjectName("sectionTitle")
        side.addWidget(section2)

        self.entity_list = QListWidget()
        side.addWidget(self.entity_list, 1)

        layout.addWidget(sidebar)
        layout.addWidget(self.view, 1)

        self.setCentralWidget(root)
        self.statusBar().showMessage("Hazır — DWG veya DXF dosyası ekleyin")

    def _begin_plan_selection(self) -> None:
        if self._full_document is None:
            return

        self.window_btn.setEnabled(False)
        self.view.set_plan_cleanup_active(False)
        self.view.set_document(self._full_document)
        self.view.begin_plan_selection()
        self.statusBar().showMessage(
            "Plan alanını fare ile dikdörtgen olarak seçin"
        )

    def _apply_plan_selection(
        self,
        xmin: float,
        ymin: float,
        xmax: float,
        ymax: float,
    ) -> None:
        if self._full_document is None:
            return

        selected = crop_document(
            self._full_document,
            xmin,
            ymin,
            xmax,
            ymax,
        )

        if not selected.primitives and not selected.texts:
            self._selected_document = None
            self.window_btn.setEnabled(False)
            self.view.set_plan_cleanup_active(False)
            self.view.set_document(self._full_document)
            self.statusBar().showMessage("Seçilen alanda CAD verisi bulunamadı")
            return

        self._selected_document = selected
        self._prepare_plan_objects()
        self.view.set_plan_cleanup_active(True)
        self.view.set_document(selected)
        self.window_btn.setEnabled(True)

        self.statusBar().showMessage(
            "Plan alanı seçildi — Pencere butonu aktif"
        )

    def _prepare_plan_objects(self) -> None:
        document = self._selected_document

        if document is None:
            self._selected_door_candidates = ()
            self._selected_window_candidates = ()
            self._selected_wall_candidates = ()
            self._door_overlay_visible = False
            self._window_overlay_visible = False
            self._wall_overlay_visible = False
            return

        # 1. Once kapilar secilir.
        door_candidates = tuple(detect_interior_doors(document))

        # 2. Sonra pencereler secilir.
        window_result = detect_window_family(document, door_candidates)
        window_candidates = tuple(getattr(window_result, "windows", ()) or ())

        # 3. Sonra duvarlar secilir.
        wall_candidates = tuple(
            detect_walls(
                document,
                door_candidates,
                window_candidates,
            )
        )

        self._selected_door_candidates = door_candidates
        self._selected_window_candidates = window_candidates
        self._selected_wall_candidates = wall_candidates

        self._door_overlay_visible = False
        self._window_overlay_visible = False
        self._wall_overlay_visible = False

    def _detect_interior_doors(self) -> None:
        document = self._selected_document

        if document is None:
            return

        candidates = tuple(getattr(self, "_selected_door_candidates", ()) or ())

        if getattr(self, "_door_overlay_visible", False):
            self.view.show_interior_door_primitives(document, ())
            self._door_overlay_visible = False
            return

        primitive_indices = []

        for candidate in candidates:
            primitive_indices.extend(getattr(candidate, "display_primitive_indices", ()) or ())

        self.view.show_interior_door_primitives(
            document,
            tuple(dict.fromkeys(primitive_indices)),
        )
        self._door_overlay_visible = True

    def _detect_walls(self) -> None:
        document = self._selected_document

        if document is None:
            return

        candidates = tuple(getattr(self, "_selected_wall_candidates", ()) or ())

        if getattr(self, "_wall_overlay_visible", False):
            self.view.show_wall_primitives(document, ())
            self._wall_overlay_visible = False
            return

        primitive_indices = []

        for candidate in candidates:
            primitive_index = getattr(candidate, "primitive_index", None)
            if primitive_index is not None:
                primitive_indices.append(primitive_index)

        self.view.show_wall_primitives(
            document,
            tuple(dict.fromkeys(primitive_indices)),
        )
        self._wall_overlay_visible = True

    def _detect_window_family(self) -> None:
        if self._selected_document is None:
            return

        candidates = tuple(getattr(self, "_selected_window_candidates", ()) or ())

        if getattr(self, "_window_overlay_visible", False):
            self.view.show_window_rectangles(())
            self._window_overlay_visible = False
            return

        self.view.show_window_rectangles(candidates)
        self._window_overlay_visible = True

    def open_cad(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Mimari CAD Dosyası Seç",
            str(self._current_path.parent if self._current_path else Path.home()),
            "CAD Dosyaları (*.dwg *.dxf);;DWG Dosyaları (*.dwg);;DXF Dosyaları (*.dxf)",
        )

        if not filename:
            return

        path = Path(filename)
        self.statusBar().showMessage(f"Yükleniyor: {path.name}")

        try:
            document = self._loader.load(path)
        except CadLoadError as exc:
            self.statusBar().showMessage("CAD yüklenemedi")
            QMessageBox.critical(self, "CAD Yükleme Hatası", str(exc))
            return
        except Exception as exc:
            self.statusBar().showMessage("Beklenmeyen bir hata oluştu")
            QMessageBox.critical(self, "Beklenmeyen Hata", str(exc))
            return

        self._current_path = path
        self._full_document = document
        self._selected_document = None

        self.view.set_plan_cleanup_active(False)
        self.view.set_document(document)

        self.plan_btn.setEnabled(True)
        self.window_btn.setEnabled(False)

        self.file_label.setText(
            f"{path.name}\n"
            f"Katman sayısı: {len(document.layers)}\n"
            f"Çizim öğesi sayısı: {len(document.primitives)}"
        )

        self.entity_list.clear()

        for name, count in document.entity_counts.items():
            skipped = document.skipped_counts.get(name, 0)
            text = f"{name}: {count}"

            if skipped:
                text += f"   (atlanmış: {skipped})"

            self.entity_list.addItem(text)

        self.statusBar().showMessage(
            "CAD yüklendi — önce Plan Seç ile çalışma alanını seçin"
        )

    def clear_cad(self) -> None:
        self._current_path = None
        self._full_document = None
        self._selected_document = None

        self.view.clear_document()

        self.plan_btn.setEnabled(False)
        self.window_btn.setEnabled(False)

        self.file_label.setText("Henüz CAD yüklenmedi")
        self.entity_list.clear()

        self.statusBar().showMessage("CAD temizlendi")
