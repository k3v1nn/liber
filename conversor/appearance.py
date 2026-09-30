# SPDX-License-Identifier: AGPL-3.0-only
"""Shared visual styles and original line icons for the desktop UI."""

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QComboBox
from PySide6.QtSvg import QSvgRenderer


PATHS = {
    "book": '<path d="M12 5v15M3 4h5a4 4 0 0 1 4 2 4 4 0 0 1 4-2h5v15h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3z"/>',
    "file": '<path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8M8 16h6"/>',
    "folder": '<path d="M3 6h7l2 3h9l-2 11H3zM3 9V4h6l2 2h8v3"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-7 5 7"/>',
    "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    "link": '<path d="m10 14 4-4M8 16l-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m0 12a4 4 0 0 0 6 0l5-5a4 4 0 0 0-6-6l-1 1" transform="translate(1 0) scale(.9)"/>',
    "up": '<path d="M12 20V4m-6 6 6-6 6 6"/>',
    "down": '<path d="M12 4v16m-6-6 6 6 6-6"/>',
    "trash": '<path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',
    "bookmark": '<path d="M6 3h12v18l-6-4-6 4z"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
}


def line_icon(name: str, color: str = "#64748b", size: int = 20) -> QIcon:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</g></svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


class CleanComboBox(QComboBox):
    """Draw the same small chevron on every desktop platform."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#71829b" if self.isEnabled() else "#b4c0d1"), 1.5))
        x, y = self.width() - 15, self.height() // 2
        painter.drawLine(x - 4, y - 2, x, y + 2)
        painter.drawLine(x, y + 2, x + 4, y - 2)
        painter.end()


THEME = """
QMainWindow, QWidget#shell { background: #f3f5f8; }
QWidget { color: #263247; font-family: 'Inter', 'Segoe UI', 'Noto Sans', sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QLabel#brand { font-size: 22px; font-weight: 700; color: #17243b; }
QLabel#subtitle, QLabel#muted { color: #78869a; font-size: 12px; }
QLabel#sectionLabel { color: #24334c; font-size: 14px; font-weight: 600; }
QLabel#eyebrow { color: #728098; font-size: 11px; font-weight: 600; }
QLabel#activity { background: #eaf0f9; color: #45658f; padding: 9px 14px; border-radius: 8px; font-size: 12px; }
QFrame#card { background: #ffffff; border: 1px solid #e4e9f0; border-radius: 12px; }
QWidget#details { background: #f3f5f8; }
QWidget#canvas { background: #e9edf3; }
QLabel#coverWell { background: #eff2f7; border: 1px solid #e1e7f0; border-radius: 7px; color: #98a6b8; }
QPushButton { background: #ffffff; border: 1px solid #dce3ed; border-radius: 7px; padding: 6px 12px; font-weight: 500; }
QPushButton:hover { background: #f5f8fc; border-color: #aebed6; }
QPushButton:pressed { background: #e8eef7; }
QPushButton:focus { border-color: #4b76c2; }
QPushButton:disabled { color: #a1adbc; background: #f6f8fa; border-color: #e9edf3; }
QPushButton[primary="true"] { background: #335fd1; border-color: #335fd1; color: white; font-weight: 600; }
QPushButton[primary="true"]:hover { background: #284faf; }
QPushButton[primary="true"]:disabled { background: #dce5f7; border-color: #dce5f7; color: #8496b5; }
QPushButton[quiet="true"] { background: transparent; border-color: transparent; color: #657792; }
QPushButton[quiet="true"]:hover { background: #edf2f9; }
QLineEdit, QComboBox, QPlainTextEdit { background: #fafbfd; border: 1px solid #e1e7ef; border-radius: 7px; padding: 6px 9px; selection-background-color: #dde7fa; selection-color: #1c3d78; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { background: #ffffff; border-color: #7d9fdf; }
QLineEdit:disabled, QComboBox:disabled { color: #9aa7b9; background: #f6f8fb; }
QComboBox { padding-right: 24px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView { background: white; color: #263247; selection-background-color: #e7eefc; selection-color: #24437a; padding: 4px; }
QTextBrowser { background: white; border: none; padding: 12px; }
QTableWidget, QListWidget { background: white; border: none; outline: 0; selection-background-color: #edf2fc; selection-color: #254982; }
QListWidget::item { padding: 10px 8px; border-bottom: 1px solid #f0f3f7; }
QListWidget::item:selected { background: #edf2fc; border-left: 3px solid #335fd1; }
QHeaderView::section { background: #f8fafc; color: #7b889c; border: none; border-bottom: 1px solid #e8edf4; padding: 9px 7px; font-size: 11px; font-weight: 600; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #758399; padding: 10px 18px; border-bottom: 2px solid transparent; font-weight: 500; }
QTabBar::tab:selected { color: #335fd1; border-bottom-color: #335fd1; font-weight: 600; }
QTabBar::tab:hover { color: #244cae; }
QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: transparent; }
QSplitter::handle:hover { background: #d6e0ef; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 3px; }
QScrollBar::handle:vertical { background: #cbd5e3; border-radius: 3px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QProgressBar { background: #e0e7f2; border: none; max-height: 4px; border-radius: 2px; }
QProgressBar::chunk { background: #335fd1; }
QToolTip { background: #23334e; color: white; padding: 6px; border: none; }
"""
