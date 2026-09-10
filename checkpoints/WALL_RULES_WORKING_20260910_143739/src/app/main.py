from __future__ import annotations

import sys

from PySide6.QtCore import QLocale
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from core.encoding_guard import assert_project_text_is_clean_utf8
from core.paths import ensure_runtime_dirs, project_root


def main() -> int:
    ensure_runtime_dirs()
    assert_project_text_is_clean_utf8(project_root())

    from ui.main_window import MainWindow
    from ui.theme import DARK_STYLESHEET

    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey))

    app = QApplication(sys.argv)
    app.setApplicationName("3Dcad")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(DARK_STYLESHEET)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
