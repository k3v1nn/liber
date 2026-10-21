# SPDX-License-Identifier: AGPL-3.0-only
"""Visual identity: colours, bundled fonts, line icons, logo, paper texture and stylesheet."""

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFilter
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QComboBox
from PySide6.QtSvg import QSvgRenderer


APP_NAME = "Liber"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

INK, INK_2 = "#17130f", "#2a231c"
PAPER, PAPER_2, PAGE = "#f3ebdc", "#ece2cf", "#fbf7ee"
LINE, LINE_2 = "#dccfb6", "#e6dcc8"
TEXT, TEXT_2, TEXT_3 = "#2a221b", "#6b5d4d", "#9a8b76"
SEAL, SEAL_DARK, GILT = "#b8432b", "#9a3522", "#c9a45c"
SERIF, SANS = "Fraunces", "Inter"

# A standing book and a lying book form the L of Liber.
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect x="13" y="5" width="15" height="41" rx="2" fill="#b8432b"/>
<rect x="13" y="11" width="15" height="2.4" fill="#c9a45c"/><rect x="13" y="38.5" width="15" height="2.4" fill="#c9a45c"/>
<rect x="13" y="46" width="40" height="3.4" rx="1.5" fill="#17130f"/>
<rect x="15" y="49.4" width="37" height="6" fill="#f3ebdc" stroke="#17130f" stroke-width=".8"/>
<rect x="13" y="55.4" width="40" height="3.4" rx="1.5" fill="#17130f"/>
</svg>"""

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
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "star": '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
}


def _render_svg(svg: str, size: int) -> QPixmap:
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return pixmap


def _icon_svg(name: str, color: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</g></svg>'


def line_icon(name: str, color: str = TEXT_2, size: int = 18, checked_color: str | None = None) -> QIcon:
    icon = QIcon(_render_svg(_icon_svg(name, color), size))
    if checked_color:
        icon.addPixmap(_render_svg(_icon_svg(name, checked_color), size), QIcon.Mode.Normal, QIcon.State.On)
    return icon


def brand_mark(size: int) -> QPixmap:
    return _render_svg(LOGO_SVG, size)


def app_icon(size: int = 256) -> QPixmap:
    """The mark on a rounded paper tile, used for the window and the executable."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(size * .04, size * .04, size * .92, size * .92), size * .22, size * .22)
    painter.fillPath(path, QColor(PAPER))
    painter.setPen(QPen(QColor(LINE), max(1, size / 128)))
    painter.drawPath(path)
    inset = size * .17
    QSvgRenderer(QByteArray(LOGO_SVG.encode())).render(painter, QRectF(inset, inset, size - inset * 2, size - inset * 2))
    painter.end()
    return pixmap


_fonts_loaded = False


def load_fonts():
    global _fonts_loaded
    if _fonts_loaded:
        return
    for font in sorted((ASSETS / "fonts").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(font))
    _fonts_loaded = True


def _seamless(noise: Image.Image, blur: float) -> Image.Image:
    width, height = noise.size
    tiled = Image.new(noise.mode, (width * 3, height * 3))
    for x in range(3):
        for y in range(3):
            tiled.paste(noise, (x * width, y * height))
    return tiled.filter(ImageFilter.GaussianBlur(blur)).crop((width, height, width * 2, height * 2))


@lru_cache(maxsize=2)
def paper_texture(dark: bool = False) -> QPixmap:
    """A subtle, seamless paper grain: multiply it over light surfaces, screen it over dark ones."""
    size = 256
    grain = _seamless(Image.effect_noise((size, size), 46), .55)
    fibre = _seamless(Image.effect_noise((size // 4, size // 2), 50).resize((size, size), Image.BICUBIC), 1.5)
    if dark:
        texture = Image.merge("RGB", [Image.eval(grain, lambda v: max(0, v - 128) // 7)] * 3)
    else:
        mixed = Image.blend(grain, fibre, .15)
        texture = Image.merge("RGB", [Image.eval(mixed, lambda v: 255 - max(0, 132 - v) // 8)] * 3)
    return QPixmap.fromImage(ImageQt(texture))


class CleanComboBox(QComboBox):
    """A text-like combo box with the same small chevron on every desktop platform."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = TEXT_3 if not self.isEnabled() else SEAL if self.hasFocus() or self.view().isVisible() else TEXT_2
        painter.setPen(QPen(QColor(color), 1.4))
        x, y = self.width() - 8, self.height() // 2
        painter.drawLine(x - 3, y - 1, x, y + 2)
        painter.drawLine(x, y + 2, x + 3, y - 1)
        painter.end()


THEME = f"""
QWidget {{ color: {TEXT}; font-family: '{SANS}', 'Segoe UI', 'Noto Sans', sans-serif; font-size: 13px; }}
QMainWindow, QDialog, QMessageBox, QInputDialog {{ background: {PAPER}; }}
QLabel {{ background: transparent; }}
QLabel#eyebrow {{ color: {TEXT_2}; font-size: 10px; font-weight: 500; }}
QLabel#fieldCaption {{ color: {TEXT_3}; font-size: 11px; }}
QLabel#count {{ color: {TEXT_3}; font-size: 11px; }}
QLabel#muted {{ color: {TEXT_2}; font-size: 12px; }}
QLabel#hint, QLabel#status {{ color: {TEXT_2}; font-size: 12px; font-style: italic; }}
QLabel#hint {{ color: {TEXT_3}; }}
QLabel#brandName {{ font-family: '{SERIF}'; font-size: 21px; font-weight: 600; color: {INK}; }}
QLabel#brandNameDark {{ font-family: '{SERIF}'; font-size: 21px; font-weight: 600; color: {PAPER}; }}
QLabel#emptyTitle {{ font-family: '{SERIF}'; font-size: 28px; color: {INK}; }}
QLabel#heroTitle {{ font-family: '{SERIF}'; color: {PAPER}; }}
QLabel#heroText {{ color: #c7baa3; font-size: 15px; }}
QLabel#heroHint {{ color: #8f826e; font-size: 12px; }}
QLabel#shelfCaption {{ color: #7c6f5c; font-size: 10px; font-weight: 500; }}
QLabel#cover {{ background: {PAGE}; border: 1px solid {LINE}; border-radius: 3px; }}
QFrame#hline {{ background: {LINE}; min-height: 1px; max-height: 1px; border: none; }}
QFrame#vline {{ background: {LINE}; min-width: 1px; max-width: 1px; border: none; }}
QFrame#editor {{ background: rgba(255, 252, 245, 0.7); border: none; border-left: 2px solid {SEAL};
    border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
QFrame#segmented {{ background: rgba(23, 19, 15, 0.06); border-radius: 12px; }}
QPushButton {{ background: transparent; border: 1px solid {LINE}; border-radius: 15px; padding: 0 14px; color: {INK}; font-weight: 500; }}
QPushButton:hover {{ background: {PAPER_2}; }}
QPushButton:focus {{ border-color: {SEAL}; }}
QPushButton:disabled {{ color: #b8aa94; }}
QPushButton[kind="seal"] {{ background: {SEAL}; border-color: {SEAL}; color: #fff6ea; padding: 0 18px; }}
QPushButton[kind="seal"]:hover {{ background: {SEAL_DARK}; border-color: {SEAL_DARK}; }}
QPushButton[kind="seal"]:focus {{ border-color: {INK}; }}
QPushButton[kind="seal"]:disabled {{ background: #e3cdc2; border-color: #e3cdc2; color: #fbf3ea; }}
QPushButton[kind="ink"] {{ background: {INK}; border-color: {INK}; color: {PAPER}; }}
QPushButton[kind="ink"]:hover {{ background: #3a3128; }}
QPushButton[kind="ink"]:focus {{ border-color: {SEAL}; }}
QPushButton[kind="outline"] {{ border: 1px solid #cdbb98; background: rgba(255, 252, 245, 0.55); color: {INK}; border-radius: 20px; padding: 0 16px; }}
QPushButton[kind="outline"]:hover {{ background: {PAGE}; border-color: {TEXT_3}; }}
QPushButton[kind="outline"]:focus {{ border-color: {SEAL}; }}
QFrame#addGroup {{ border: 1px solid #cdbb98; border-radius: 16px; background: rgba(255, 252, 245, 0.55); }}
QPushButton[kind="part"] {{ border: none; border-radius: 0; padding: 0 12px; color: {INK}; }}
QPushButton[kind="part"]:hover {{ background: {PAPER_2}; }}
QPushButton[kind="part"]:focus {{ color: {SEAL}; }}
QPushButton[kind="part"][edge="left"] {{ border-top-left-radius: 15px; border-bottom-left-radius: 15px; padding-left: 14px; }}
QPushButton[kind="part"][edge="right"] {{ border-top-right-radius: 15px; border-bottom-right-radius: 15px; padding-right: 14px; }}
QPushButton[kind="tab"] {{ border-color: transparent; color: {TEXT_2}; padding: 0 15px; }}
QPushButton[kind="tab"]:hover {{ background: transparent; color: {INK}; }}
QPushButton[kind="tab"]:checked {{ background: {INK}; border-color: {INK}; color: {PAPER}; }}
QPushButton[kind="tab"]:focus {{ border-color: {SEAL}; }}
QPushButton[kind="link"], QPushButton[kind="filter"], QPushButton[kind="lang"] {{ border: none; border-radius: 0; padding: 0; font-weight: 400; text-align: left; }}
QPushButton[kind="link"] {{ color: {TEXT_2}; }}
QPushButton[kind="link"]:hover, QPushButton[kind="link"]:focus {{ background: transparent; color: {SEAL}; }}
QPushButton[kind="link"]:disabled {{ color: #c9bca6; }}
QPushButton[kind="filter"] {{ color: {TEXT_3}; font-size: 12px; border-bottom: 1px solid transparent; }}
QPushButton[kind="filter"]:hover, QPushButton[kind="filter"]:focus {{ background: transparent; color: {INK}; }}
QPushButton[kind="filter"]:checked {{ color: {INK}; border-bottom: 1px solid {SEAL}; }}
QPushButton[kind="lang"] {{ color: {TEXT_3}; font-size: 12px; }}
QPushButton[kind="lang"]:hover, QPushButton[kind="lang"]:focus {{ background: transparent; color: {INK}; }}
QPushButton[kind="lang"]:checked {{ color: {INK}; font-weight: 600; }}
QPushButton[kind="lang"][dark="true"] {{ color: #8f826e; }}
QPushButton[kind="lang"][dark="true"]:hover, QPushButton[kind="lang"][dark="true"]:checked {{ color: {PAPER}; }}
QPushButton[kind="seg"] {{ border-color: transparent; border-radius: 10px; padding: 0 11px; color: {TEXT_2}; font-size: 11px; font-weight: 400; }}
QPushButton[kind="seg"]:hover {{ background: transparent; color: {INK}; }}
QPushButton[kind="seg"]:checked {{ background: {PAGE}; color: {INK}; }}
QPushButton[kind="icon"] {{ border-color: transparent; border-radius: 14px; padding: 0; }}
QPushButton[kind="icon"]:focus {{ border-color: {SEAL}; }}
QPushButton[kind="cream"] {{ background: {PAPER}; border-color: {PAPER}; color: {INK}; border-radius: 22px; padding: 0 22px; font-size: 14px; }}
QPushButton[kind="cream"]:hover {{ background: #ffffff; border-color: #ffffff; }}
QPushButton[kind="cream"]:focus {{ border-color: {GILT}; }}
QPushButton[kind="ghostDark"] {{ border-color: #574a3c; color: {PAPER}; border-radius: 22px; padding: 0 22px; font-size: 14px; }}
QPushButton[kind="ghostDark"]:hover {{ background: rgba(243, 235, 220, 0.06); border-color: #8a7965; }}
QPushButton[kind="ghostDark"]:focus {{ border-color: {GILT}; }}
QPushButton[kind="brand"] {{ border: none; padding: 0 4px 0 0; font-family: '{SERIF}'; font-size: 21px; font-weight: 600; color: {INK}; }}
QPushButton[kind="brand"]:hover {{ background: transparent; color: {SEAL}; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}
QLineEdit {{ background: transparent; border: none; border-bottom: 1px solid {LINE}; padding: 3px 0 7px 0;
    selection-background-color: #ecd3c8; selection-color: {INK}; }}
QLineEdit:focus {{ border-bottom-color: {SEAL}; }}
QLineEdit[serif="true"] {{ font-family: '{SERIF}'; font-size: 17px; color: {INK}; }}
QDialog QLineEdit {{ background: {PAGE}; border: 1px solid {LINE}; border-radius: 6px; padding: 6px 8px; }}
QComboBox {{ background: transparent; border: none; border-bottom: 1px dotted {TEXT_3}; padding: 2px 18px 3px 0; color: {INK}; }}
QComboBox:focus {{ border-bottom: 1px solid {SEAL}; }}
QComboBox:disabled {{ color: #b8aa94; }}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{ background: {PAGE}; color: {INK}; border: 1px solid {LINE}; outline: 0; padding: 4px;
    selection-background-color: {PAPER_2}; selection-color: {INK}; }}
QPlainTextEdit {{ background: transparent; border: none; font-family: '{SERIF}'; font-size: 15px; color: {INK};
    selection-background-color: #ecd3c8; selection-color: {INK}; }}
QTextBrowser, QListWidget, QScrollArea {{ background: transparent; border: none; outline: 0; }}
QListWidget::item {{ border: none; }}
QMenu {{ background: {PAGE}; border: 1px solid {LINE}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 8px 28px 8px 10px; border-radius: 7px; color: {INK}; }}
QMenu::item:selected {{ background: {PAPER_2}; }}
QMenu::icon {{ padding-left: 10px; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(23, 19, 15, 0.16); border-radius: 2px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(23, 19, 15, 0.3); }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(23, 19, 15, 0.16); border-radius: 2px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: {INK}; color: {PAPER}; padding: 6px 8px; border: none; }}
"""
