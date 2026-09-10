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

        section2 = QLabel("CAD ÖĞE ÖZETİ")
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
            self.view.set_document(self._full_document)
            self.statusBar().showMessage("Seçilen alanda CAD verisi bulunamadı")
            return

        self._selected_document = selected
        self.view.set_document(selected)
        self.window_btn.setEnabled(True)

        self.statusBar().showMessage(
            "Plan alanı seçildi — Pencere butonu aktif"
        )

    def _detect_interior_doors(self) -> None:
        if self._selected_document is None:
            return

        doors = detect_interior_doors(
            self._selected_document
        )

        indices = []

        for candidate in doors:
            indices.extend(
                candidate.display_primitive_indices
            )

        self.view.show_interior_door_primitives(
            self._selected_document,
            sorted(set(indices)),
        )

        self.statusBar().showMessage(
            f"{len(doors)} interior door candidate(s) selected"
        )
    def _detect_window_family(self) -> None:
        if self._selected_document is None or self._current_path is None:
            return

        result = detect_window_family(self._selected_document)

        if result is None:
            self.statusBar().showMessage(
                "Seçilen plan alanında pencere bulunamadı"
            )
            return

        windows = list(result.windows)

        records = []

        for index, candidate in enumerate(windows, start=1):
            corners = [[float(x), float(y)] for x, y in candidate.corners]
            lines = [
                {
                    "start": [float(a[0]), float(a[1])],
                    "end": [float(b[0]), float(b[1])],
                }
                for a, b in candidate.lines
            ]

            records.append(
                {
                    "id": index,
                    "type": "window",
                    "is_seed": candidate is result.seed,
                    "source_file": str(self._current_path),
                    "coordinate_system": "cad_world_xy",
                    "closed": True,
                    "corners": corners,
                    "lines": lines,
                }
            )

        output_dir = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "output"
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        target = output_dir / "window_selections.json"
        target.write_text(
            json.dumps(
                {
                    "type": "window_family",
                    "count": len(records),
                    "windows": records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self.view.show_window_rectangles(windows)

        self.statusBar().showMessage(
            f"1 pencere referans seçildi — aynı nesne türünde {len(windows)} pencere seçildi"
        )

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
