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
        if not self.isEnabled():
            color = "#b4c0d1"
        elif self.hasFocus() or self.view().isVisible():
            color = "#335fd1"
        elif self.underMouse():
            color = "#4a5d7a"
        else:
            color = "#66778f"
        painter.setPen(QPen(QColor(color), 1.6))
        x, y = self.width() - 15, self.height() // 2
        painter.drawLine(x - 4, y - 2, x, y + 2)
        painter.drawLine(x, y + 2, x + 4, y - 2)
        painter.end()


THEME = """
QMainWindow, QWidget#shell { background: #f1f4f8; }
QWidget { color: #1f2d44; font-family: 'Inter', 'Segoe UI', 'Noto Sans', sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QLabel#brand { font-size: 22px; font-weight: 700; color: #14213a; }
QLabel#subtitle, QLabel#muted { color: #5d6b81; font-size: 12px; }
QLabel#sectionLabel { color: #1b2b46; font-size: 14px; font-weight: 600; }
QLabel#eyebrow { color: #55647c; font-size: 11px; font-weight: 600; }
QLabel#activity { background: #eaf0fb; color: #29476f; border: 1px solid #d3e0f5; padding: 9px 14px; border-radius: 8px; font-size: 12px; }
QFrame#card { background: #ffffff; border: 1px solid #e0e6ef; border-radius: 12px; }
QFrame#toolbar { background: #ffffff; border: 1px solid #e0e6ef; border-radius: 12px; }
QWidget#details { background: #f1f4f8; }
QLabel#canvas { background: #e4e9f1; border: 1px solid #d5dde9; border-radius: 8px; color: #55647c; padding: 4px; }
QLabel#coverWell { background: #eef2f7; border: 1px solid #dde4ee; border-radius: 7px; color: #8393a9; }
QLabel#emptyIcon { background: #eaf0fb; border-radius: 30px; }
QPushButton { background: #ffffff; border: 1px solid #d5dde9; border-radius: 7px; padding: 6px 12px; font-weight: 500; }
QPushButton:hover { background: #f3f6fb; border-color: #9fb3d3; }
QPushButton:pressed { background: #e6edf8; }
QPushButton:focus { border-color: #335fd1; }
QPushButton:disabled { color: #96a3b6; background: #f4f6f9; border-color: #e6ebf2; }
QPushButton[primary="true"] { background: #335fd1; border-color: #335fd1; color: white; font-weight: 600; }
QPushButton[primary="true"]:hover { background: #284faf; border-color: #284faf; }
QPushButton[primary="true"]:pressed { background: #20409a; border-color: #20409a; }
QPushButton[primary="true"]:focus { border-color: #14337f; }
QPushButton[primary="true"]:disabled { background: #dbe4f6; border-color: #dbe4f6; color: #70829f; }
QPushButton[quiet="true"] { background: transparent; border-color: transparent; color: #55657f; }
QPushButton[quiet="true"]:hover { background: #ebf0f8; border-color: #d5dde9; }
QPushButton[quiet="true"]:pressed { background: #dfe7f4; }
QPushButton[quiet="true"]:focus { border-color: #335fd1; }
QPushButton[quiet="true"]:disabled { background: transparent; border-color: transparent; color: #a9b4c4; }
QLineEdit, QComboBox, QPlainTextEdit { background: #fafbfd; border: 1px solid #d9e1ec; border-radius: 7px; padding: 6px 9px; selection-background-color: #d6e3fb; selection-color: #17376f; }
QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover { border-color: #aebfd8; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { background: #ffffff; border-color: #335fd1; }
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled { color: #96a3b6; background: #f4f6f9; border-color: #e6ebf2; }
QComboBox { padding-right: 24px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView { background: white; color: #1f2d44; border: 1px solid #d5dde9; outline: 0; selection-background-color: #e4ecfc; selection-color: #1f3f7c; padding: 4px; }
QCheckBox { spacing: 8px; font-size: 12px; }
QCheckBox:disabled { color: #96a3b6; }
QTextBrowser { background: white; border: 1px solid #e0e6ef; border-radius: 8px; padding: 10px; }
QTableWidget, QListWidget { background: white; border: none; outline: 0; selection-background-color: #e9effc; selection-color: #1f3f7c; }
QListWidget::item { padding: 10px 8px; border-bottom: 1px solid #eef1f6; }
QListWidget::item:hover { background: #f5f8fc; }
QListWidget::item:selected { background: #e9effc; color: #1f3f7c; border-left: 3px solid #335fd1; }
QTableWidget::item:selected { background: #e9effc; color: #1f3f7c; }
QHeaderView::section { background: #f6f8fb; color: #55647c; border: none; border-bottom: 1px solid #e3e9f1; padding: 9px 7px; font-size: 11px; font-weight: 600; }
QTabWidget::pane { border: none; }
QTabWidget::tab-bar { alignment: left; }
QTabBar::tab { background: transparent; color: #55647c; padding: 10px 18px; margin-right: 4px; border-bottom: 2px solid transparent; font-weight: 500; }
QTabBar::tab:selected { color: #274fb8; border-bottom-color: #335fd1; font-weight: 600; }
QTabBar::tab:hover:!selected { color: #1f3f7c; background: #e9eff8; border-top-left-radius: 7px; border-top-right-radius: 7px; }
QScrollArea { border: none; background: transparent; }
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { margin: 0 5px; }
QSplitter::handle:hover { background: #c6d4ea; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 3px; }
QScrollBar::handle:vertical { background: #c4cfdf; border-radius: 2px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #9fb0c8; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 3px; }
QScrollBar::handle:horizontal { background: #c4cfdf; border-radius: 2px; min-width: 28px; }
QScrollBar::handle:horizontal:hover { background: #9fb0c8; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QProgressBar { background: #dde5f1; border: none; max-height: 4px; border-radius: 2px; }
QProgressBar::chunk { background: #335fd1; border-radius: 2px; }
QToolTip { background: #1f2d44; color: white; padding: 6px 8px; border: none; }
"""
