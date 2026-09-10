DARK_STYLESHEET = r"""
QMainWindow, QWidget {
    background: #191A1B;
    color: #D4D4D4;
    font-family: "Segoe UI";
    font-size: 10pt;
}

QFrame#sidebar {
    background: #18191A;
    border-right: 1px solid #2B2B2B;
}

QLabel {
    background: transparent;
    color: #D4D4D4;
}

QLabel#title {
    font-size: 17pt;
    font-weight: 600;
    color: #F0F0F0;
}

QLabel#sectionTitle {
    font-size: 9pt;
    font-weight: 600;
    color: #C8C8C8;
}

QPushButton {
    min-height: 34px;
    padding: 0 12px;
    border: 1px solid #343434;
    border-radius: 3px;
    background: #1C1D1E;
    color: #DCDCDC;
}

QPushButton:hover {
    background: #232425;
}

QPushButton:pressed {
    background: #161718;
}

QPushButton#primary {
    background: #1C1D1E;
    border-color: #3A3A3A;
    color: #FFFFFF;
    font-weight: 600;
}

QPushButton#primary:hover {
    background: #252627;
}

QListWidget, QTextEdit {
    background: #191A1B;
    border: 1px solid #2D2D2D;
    border-radius: 2px;
    color: #D4D4D4;
    selection-background-color: #303030;
    selection-color: #FFFFFF;
    outline: 0;
}

QListWidget::item {
    padding: 3px 5px;
}

QListWidget::item:hover {
    background: #222324;
}

QStatusBar {
    background: #18191A;
    color: #B8B8B8;
    border-top: 1px solid #2B2B2B;
}

QScrollBar:vertical {
    background: #191A1B;
    width: 12px;
}

QScrollBar:horizontal {
    background: #191A1B;
    height: 12px;
}

QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {
    background: #373737;
    min-height: 24px;
    min-width: 24px;
    border-radius: 2px;
}

QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {
    background: #4A4A4A;
}

QScrollBar::add-line,
QScrollBar::sub-line {
    width: 0;
    height: 0;
}

QScrollBar::add-page,
QScrollBar::sub-page {
    background: transparent;
}
"""
