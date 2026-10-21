# SPDX-License-Identifier: AGPL-3.0-only
"""Custom-painted widgets for the paper interface and the opening shelf."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QTransform
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QListView, QListWidget, QSizePolicy, QStyle, QStyledItemDelegate,
    QVBoxLayout, QWidget,
)

from .appearance import (
    GILT, INK, LINE, PAGE, PAPER, SANS, SEAL, SERIF, TEXT_2, TEXT_3, paper_texture,
)

BLOCK_INDEX = Qt.ItemDataRole.UserRole
BLOCK_ROLE = Qt.ItemDataRole.UserRole + 1
BLOCK_PAGE = Qt.ItemDataRole.UserRole + 2
BLOCK_LABEL = Qt.ItemDataRole.UserRole + 3
PAGE_PATH = Qt.ItemDataRole.UserRole
PAGE_COVER = Qt.ItemDataRole.UserRole + 1
PAGE_CHAPTER = Qt.ItemDataRole.UserRole + 2


def _font(family: str, pixels: float, weight=QFont.Weight.Normal, italic=False) -> QFont:
    font = QFont(family)
    font.setPixelSize(round(pixels))
    font.setWeight(weight)
    font.setItalic(italic)
    return font


def _shadow(painter: QPainter, rect: QRectF, radius: float, strength: int = 10):
    painter.setPen(Qt.PenStyle.NoPen)
    for step in range(10):
        painter.setBrush(QColor(60, 40, 20, max(0, strength - step)))
        painter.drawRoundedRect(rect.adjusted(-step * .4, step * .9, step * .4, step * 1.5), radius + step, radius + step)


class PaperSurface(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(PAPER))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        painter.drawTiledPixmap(self.rect(), paper_texture())


class StartBackdrop(QWidget):
    """Dark opening backdrop with a warm glow and a faint grain."""

    resized = Signal(int)

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        gradient = QRadialGradient(QPointF(rect.width() / 2, rect.height() * .35), max(rect.width(), rect.height()) * .75)
        gradient.setColorAt(0, QColor("#2a2219"))
        gradient.setColorAt(.62, QColor(INK))
        gradient.setColorAt(1, QColor(INK))
        painter.fillRect(rect, gradient)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.drawTiledPixmap(rect, paper_texture(dark=True))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit(self.width())


class PageFrame(QWidget):
    """A sheet of page paper with a soft shadow; content goes in its layout."""

    def __init__(self, color: str = PAGE, margin: int = 30):
        super().__init__()
        self.color = color
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8 + margin, 4 + margin, 8 + margin, 16 + margin)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        page = QRectF(self.rect()).adjusted(8, 4, -8, -16)
        _shadow(painter, page, 3)
        painter.setBrush(QColor(self.color))
        painter.setPen(QPen(QColor(LINE), 1))
        painter.drawRoundedRect(page, 3, 3)


class PagePreview(QWidget):
    """Shows a page image scaled to fit, as a sheet with a shadow, or a quiet placeholder."""

    def __init__(self, placeholder: str):
        super().__init__()
        self.placeholder = placeholder
        self.original = QPixmap()
        self.setMinimumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def set_image(self, image: QPixmap):
        self.original = image
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        area = QRectF(self.rect()).adjusted(10, 6, -10, -20)
        if self.original.isNull():
            painter.setPen(QColor(TEXT_3))
            painter.setFont(_font(SANS, 12, italic=True))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.placeholder)
            return
        size = self.original.size().scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
        page = QRectF(area.center().x() - size.width() / 2, area.top() + (area.height() - size.height()) / 2, size.width(), size.height())
        _shadow(painter, page, 2)
        painter.drawPixmap(page, self.original, QRectF(self.original.rect()))
        painter.setPen(QPen(QColor(LINE), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(page)


class CoverThumb(QWidget):
    """Book-shaped cover thumbnail that tilts slightly on hover."""

    def __init__(self, size: QSize):
        super().__init__()
        self.pixmap = QPixmap()
        self.hovered = False
        self.setFixedSize(size)

    def set_image(self, pixmap: QPixmap):
        self.pixmap = pixmap
        self.update()

    def enterEvent(self, event):
        self.hovered = True
        self.update()

    def leaveEvent(self, event):
        self.hovered = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        book = QRectF(self.rect()).adjusted(4, 4, -4, -12)
        if self.hovered:
            painter.translate(book.center())
            painter.rotate(-3)
            painter.translate(-book.center() + QPointF(0, -2))
        _shadow(painter, book, 3, 8)
        path = QPainterPath()
        path.addRoundedRect(book, 3, 3)
        painter.setClipPath(path)
        if self.pixmap.isNull():
            painter.fillRect(book, QColor("#e4d8c0"))
            painter.setPen(QPen(QColor(TEXT_3), 1, Qt.PenStyle.DashLine))
            painter.drawRect(book.adjusted(6, 6, -6, -6))
        else:
            source = QRectF(self.pixmap.rect())
            scale = max(book.width() / source.width(), book.height() / source.height())
            painter.drawPixmap(QRectF(book.center().x() - source.width() * scale / 2, book.center().y() - source.height() * scale / 2,
                                      source.width() * scale, source.height() * scale), self.pixmap, source)
        painter.fillRect(QRectF(book.left(), book.top(), 4, book.height()), QColor(0, 0, 0, 55))


class ProgressRibbon(QWidget):
    """A thin red ribbon under the toolbar that runs while a task is busy."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(2)
        self.phase = 0.0
        self.animation = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1500, loopCount=-1)
        self.animation.valueChanged.connect(self._tick)

    def _tick(self, value):
        self.phase = value
        self.update()

    def start(self):
        self.animation.start()

    def stop(self):
        self.animation.stop()
        self.update()

    def paintEvent(self, event):
        if self.animation.state() != QVariantAnimation.State.Running:
            return
        painter = QPainter(self)
        segment = self.width() * .3
        painter.fillRect(QRectF(-segment + (self.width() + segment) * self.phase, 0, segment, 2), QColor(SEAL))


class ToggleSwitch(QCheckBox):
    def sizeHint(self):
        metrics = self.fontMetrics()
        return QSize(42 + metrics.horizontalAdvance(self.text()), max(26, metrics.height() + 6))

    def minimumSizeHint(self):
        return QSize(120, 34)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = (self.height() - 18) / 2
        painter.setPen(QPen(QColor(SEAL), 1.5) if self.hasFocus() else Qt.PenStyle.NoPen)
        painter.setBrush(QColor(INK if self.isChecked() else "#cdbfa5"))
        painter.drawRoundedRect(QRectF(1, top, 30, 18), 9, 9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PAPER))
        painter.drawEllipse(QRectF(16 if self.isChecked() else 4, top + 3, 12, 12))
        painter.setPen(QColor(INK))
        painter.drawText(QRectF(42, 0, self.width() - 42, self.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, self.text())


BODY_TEXT = "#3a3029"
# Background and text colour of the small type tag on non-paragraph blocks.
TAG_COLORS = {"Imagem": ("#e2e8d4", "#4a5e3b"), "Legenda": ("#e2e8d4", "#4a5e3b"),
              "Nota": ("#f1e5c4", "#74591c"), "Ignorar": ("#e6dfd2", "#7d705f")}


def _two_lines(metrics: QFontMetrics, text: str, width: float) -> list[str]:
    words, line = text.split(), ""
    for index, word in enumerate(words):
        trial = f"{line} {word}".strip()
        if line and metrics.horizontalAdvance(trial) > width:
            return [line, metrics.elidedText(" ".join(words[index:]), Qt.TextElideMode.ElideRight, int(width))]
        line = trial
    return [metrics.elidedText(line, Qt.TextElideMode.ElideRight, int(width))]


class TocDelegate(QStyledItemDelegate):
    """Paints PDF blocks as a table of contents: serif headings with dotted leaders, readable two-line body rows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chapter = _font(SERIF, 17)
        self.section = _font(SERIF, 15)
        self.body = _font(SANS, 13.5)
        self.tag = _font(SANS, 10.5, QFont.Weight.Medium)
        self.number = _font(SANS, 12)

    def _text_box(self, index, left: float, right: float):
        """Return the tag width and the text x/width for a body row spanning left..right."""
        page_width = QFontMetrics(self.number).horizontalAdvance(str(index.data(BLOCK_PAGE)))
        label = index.data(BLOCK_LABEL)
        tag_width = QFontMetrics(self.tag).horizontalAdvance(label) + 14 if label else 0
        x = left + 24 + (tag_width + 8 if label else 0)
        return tag_width, x, max(40, right - 12 - page_width - 14 - x)

    def sizeHint(self, option, index):
        if index.data(BLOCK_INDEX) is None:
            return super().sizeHint(option, index)
        role = index.data(BLOCK_ROLE)
        if role in ("Capítulo", "Seção"):
            return QSize(200, 50 if role == "Capítulo" else 42)
        width = self.parent().viewport().width() if self.parent() else 400
        _, _, available = self._text_box(index, 0, width - 2)
        text = " ".join(str(index.data(Qt.ItemDataRole.DisplayRole) or "").split())
        lines = len(_two_lines(QFontMetrics(self.body), text, available))
        return QSize(200, 18 + lines * QFontMetrics(self.body).lineSpacing())

    def paint(self, painter, option, index):
        if index.data(BLOCK_INDEX) is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(0, 1, -2, -1)
        role = index.data(BLOCK_ROLE)
        selected = option.state & QStyle.StateFlag.State_Selected
        if selected or option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(23, 19, 15, 16 if selected else 9))
            painter.drawRoundedRect(rect, 8, 8)
        if selected:
            painter.setBrush(QColor(SEAL))
            painter.drawRoundedRect(QRectF(rect.left(), rect.top() + 6, 3, rect.height() - 12), 1.5, 1.5)
        page = str(index.data(BLOCK_PAGE))
        number = QFontMetrics(self.number)
        page_x = rect.right() - 12 - number.horizontalAdvance(page)
        if role in ("Capítulo", "Seção"):
            font = self.chapter if role == "Capítulo" else self.section
            metrics = QFontMetrics(font)
            x = rect.left() + 12
            band = QRectF(rect.left(), rect.top() + (8 if role == "Capítulo" else 2), rect.width(), rect.height() - (8 if role == "Capítulo" else 2))
            text = metrics.elidedText(" ".join(str(index.data(Qt.ItemDataRole.DisplayRole) or "").split()), Qt.TextElideMode.ElideRight, int(max(20, page_x - 20 - x)))
            painter.setFont(font)
            painter.setPen(QColor(INK))
            painter.drawText(QRectF(x, band.top(), page_x - x, band.height()), Qt.AlignmentFlag.AlignVCenter, text)
            baseline = band.center().y() + metrics.ascent() / 2 - 1
            start = x + metrics.horizontalAdvance(text) + 8
            if page_x - 8 > start + 8:
                painter.setPen(QPen(QColor("#bba98a"), 1.4, Qt.PenStyle.DotLine))
                painter.drawLine(QPointF(start, baseline), QPointF(page_x - 8, baseline))
            painter.setFont(self.number)
            painter.setPen(QColor(TEXT_2))
            painter.drawText(QRectF(page_x, band.top(), rect.right() - page_x, band.height()), Qt.AlignmentFlag.AlignVCenter, page)
            painter.restore()
            return
        metrics = QFontMetrics(self.body)
        line_height = metrics.lineSpacing()
        top = rect.top() + 8
        tag_width, x, available = self._text_box(index, rect.left(), rect.right())
        label = index.data(BLOCK_LABEL)
        if label:
            background, foreground = TAG_COLORS.get(role, ("#e6dfd2", TEXT_2))
            tag = QRectF(rect.left() + 24, top + (line_height - 18) / 2, tag_width, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(tag, 9, 9)
            painter.setFont(self.tag)
            painter.setPen(QColor(foreground))
            painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, label)
        font = QFont(self.body)
        font.setStrikeOut(role == "Ignorar")
        painter.setFont(font)
        painter.setPen(QColor(TEXT_3 if role == "Ignorar" else BODY_TEXT))
        text = " ".join(str(index.data(Qt.ItemDataRole.DisplayRole) or "").split())
        for number_of_line, line in enumerate(_two_lines(metrics, text, available)):
            painter.drawText(QRectF(x, top + number_of_line * line_height, available, line_height), Qt.AlignmentFlag.AlignVCenter, line)
        painter.setFont(self.number)
        painter.setPen(QColor(TEXT_2))
        painter.drawText(QRectF(page_x, top, rect.right() - page_x, line_height), Qt.AlignmentFlag.AlignVCenter, page)
        painter.restore()


class PageList(QListWidget):
    """Wrapping grid of comic pages that can be reordered by dragging."""

    reordered = Signal()

    def __init__(self, loader):
        super().__init__()
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setGridSize(QSize(98, 176))
        self.setSpacing(0)
        self.setMouseTracking(True)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setItemDelegate(PageThumbDelegate(loader, self))

    def dropEvent(self, event):
        super().dropEvent(event)
        self.reordered.emit()


class PageThumbDelegate(QStyledItemDelegate):
    def __init__(self, loader, parent=None):
        super().__init__(parent)
        self.loader = loader
        self.cache: dict[str, QPixmap] = {}
        self.number = _font(SANS, 10.5)
        self.chapter = _font(SERIF, 11.5)

    def sizeHint(self, option, index):
        return QSize(98, 176)

    def _thumb(self, path: str) -> QPixmap:
        if path not in self.cache:
            image = self.loader(path)
            if not image.isNull():
                image = image.scaled(QSize(168, 240), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                image.setDevicePixelRatio(2)
            self.cache[path] = image
        return self.cache[path]

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        cell = QRectF(option.rect)
        area = QRectF(cell.left() + 8, cell.top() + 10, cell.width() - 16, 124)
        image = self._thumb(index.data(PAGE_PATH))
        size = QSize(60, 86) if image.isNull() else image.deviceIndependentSize().toSize().scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
        lift = 3 if option.state & QStyle.StateFlag.State_MouseOver else 0
        page = QRectF(area.center().x() - size.width() / 2, area.bottom() - size.height() - lift, size.width(), size.height())
        _shadow(painter, page, 1, 8)
        if image.isNull():
            painter.fillRect(page, QColor(PAGE))
        else:
            painter.drawPixmap(page, image, QRectF(image.rect()))
        selected = option.state & QStyle.StateFlag.State_Selected
        painter.setPen(QPen(QColor(INK), 2) if selected else QPen(QColor(LINE), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(page.adjusted(-2, -2, 2, 2) if selected else page, 2, 2)
        if index.data(PAGE_COVER):
            badge = QRectF(page.right() - 9, page.top() - 7, 16, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(INK))
            painter.drawEllipse(badge)
            painter.setPen(QColor(GILT))
            painter.setFont(_font(SANS, 9))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "★")
        chapter = index.data(PAGE_CHAPTER)
        if chapter:
            ribbon = QPainterPath()
            left, top = page.left() + 6, page.top() - 3
            ribbon.moveTo(left, top)
            ribbon.lineTo(left + 9, top)
            ribbon.lineTo(left + 9, top + 18)
            ribbon.lineTo(left + 4.5, top + 14)
            ribbon.lineTo(left, top + 18)
            ribbon.closeSubpath()
            painter.fillPath(ribbon, QColor(SEAL))
        painter.setPen(QColor(TEXT_3))
        painter.setFont(self.number)
        painter.drawText(QRectF(cell.left(), area.bottom() + 6, cell.width(), 14), Qt.AlignmentFlag.AlignHCenter, index.data(Qt.ItemDataRole.DisplayRole))
        if chapter:
            painter.setPen(QColor(SEAL))
            painter.setFont(self.chapter)
            text = QFontMetrics(self.chapter).elidedText(chapter, Qt.TextElideMode.ElideRight, int(cell.width() - 8))
            painter.drawText(QRectF(cell.left(), area.bottom() + 21, cell.width(), 16), Qt.AlignmentFlag.AlignHCenter, text)
        painter.restore()


class SidePanel(QWidget):
    """Book or comic details. Stacks vertically in a column, or spreads into a strip on narrow windows."""

    def __init__(self, eyebrow: QWidget, fields: list[QWidget], extras: list[QWidget], cover_eyebrow: QWidget, cover: QWidget,
                 cover_thumb: CoverThumb, hint: QWidget | None):
        super().__init__()
        self.eyebrow, self.fields, self.extras = eyebrow, fields, extras
        self.cover_eyebrow, self.cover, self.cover_thumb, self.hint = cover_eyebrow, cover, cover_thumb, hint
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(24, 22, 24, 18)
        self.compact = None
        self.set_compact(False)

    def set_compact(self, compact: bool):
        if compact == self.compact:
            return
        self.compact = compact
        while self.grid.count():
            self.grid.takeAt(0)
        for row in range(12):
            self.grid.setRowStretch(row, 0)
        for column in range(6):
            self.grid.setColumnStretch(column, 0)
        self.cover_thumb.setFixedSize(QSize(42, 62) if compact else QSize(92, 138))
        self.cover_eyebrow.setVisible(not compact)
        if self.hint:
            self.hint.setVisible(not compact)
        if compact:
            self.grid.setHorizontalSpacing(26)
            self.grid.setVerticalSpacing(6)
            self.grid.addWidget(self.eyebrow, 0, 0, 1, len(self.fields) + 1)
            for column, field in enumerate(self.fields):
                self.grid.addWidget(field, 1, column)
                self.grid.setColumnStretch(column, 1)
            self.grid.addWidget(self.cover, 1, len(self.fields), 2, 1)
            for row, extra in enumerate(self.extras, start=2):
                self.grid.addWidget(extra, row, 0, 1, len(self.fields))
        else:
            self.grid.setHorizontalSpacing(0)
            self.grid.setVerticalSpacing(12)
            row = 0
            for widget in [self.eyebrow, *self.fields, *self.extras]:
                self.grid.addWidget(widget, row, 0)
                row += 1
            self.grid.addWidget(self.cover_eyebrow, row, 0)
            self.grid.addWidget(self.cover, row + 1, 0)
            self.grid.setRowStretch(row + 2, 1)
            if self.hint:
                self.grid.addWidget(self.hint, row + 3, 0)
            self.grid.setColumnStretch(0, 1)


class ResponsiveBody(QWidget):
    """Three columns on wide windows, details on top on medium ones, a single scrolling column on narrow ones."""

    WIDE, MEDIUM = 1100, 860

    def __init__(self, side: SidePanel, middle: QWidget, right: QWidget):
        super().__init__()
        self.side, self.middle, self.right = side, middle, right
        self.lines = [self._line("vline"), self._line("vline"), self._line("hline"), self._line("hline")]
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(0)
        self.mode = None
        self.arrange(1280)

    @staticmethod
    def _line(name):
        line = QFrame()
        line.setObjectName(name)
        return line

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange(self.width())

    def arrange(self, width: int):
        mode = "wide" if width >= self.WIDE else "medium" if width >= self.MEDIUM else "narrow"
        if mode == self.mode:
            return
        self.mode = mode
        while self.grid.count():
            self.grid.takeAt(0)
        for index in range(6):
            self.grid.setColumnStretch(index, 0)
            self.grid.setRowStretch(index, 0)
        for line in self.lines:
            line.hide()
        vline, vline2, hline, hline2 = self.lines
        self.side.set_compact(mode != "wide")
        self.side.setFixedWidth(272) if mode == "wide" else self.side.setMaximumWidth(16777215)
        if mode != "wide":
            self.side.setMinimumWidth(0)
        narrow = mode == "narrow"
        self.middle.setMinimumHeight(380 if narrow else 0)
        self.right.setMinimumHeight(560 if narrow else 0)
        if mode == "wide":
            for column, widget in enumerate((self.side, vline, self.middle, vline2, self.right)):
                self.grid.addWidget(widget, 0, column)
            self.grid.setColumnStretch(2, 10)
            self.grid.setColumnStretch(4, 11)
            self.grid.setRowStretch(0, 1)
            vline.show(); vline2.show()
        elif mode == "medium":
            self.grid.addWidget(self.side, 0, 0, 1, 3)
            self.grid.addWidget(hline, 1, 0, 1, 3)
            self.grid.addWidget(self.middle, 2, 0)
            self.grid.addWidget(vline, 2, 1)
            self.grid.addWidget(self.right, 2, 2)
            self.grid.setColumnStretch(0, 10)
            self.grid.setColumnStretch(2, 11)
            self.grid.setRowStretch(2, 1)
            hline.show(); vline.show()
        else:
            for row, widget in enumerate((self.side, hline, self.middle, hline2, self.right)):
                self.grid.addWidget(widget, row, 0)
            self.grid.setColumnStretch(0, 1)
            hline.show(); hline2.show()
        self.side.grid.invalidate()
        self.grid.invalidate()


def _ease_out_back(t: float) -> float:
    c = 1.4
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


class BookShelf(QWidget):
    """Curved, slowly turning shelf of books. Books fall into place each time the shelf appears."""

    opened = Signal(str)

    def __init__(self):
        super().__init__()
        self.books: list[dict] = []
        self.offset = 0.0
        self.paused = False
        self.hover = -1
        self.started = time.monotonic()
        self.last = self.started
        self.hits: list[tuple[int, object]] = []
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.setMouseTracking(True)
        self.setMinimumHeight(170)

    def set_books(self, books: list[dict]):
        self.books = books
        self.update()

    def restart(self):
        self.started = time.monotonic()
        self.update()

    def showEvent(self, event):
        self.last = time.monotonic()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()

    def leaveEvent(self, event):
        self.paused = False
        self.hover = -1
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseMoveEvent(self, event):
        self.paused = True
        self.hover = self._book_at(event.position())
        clickable = self.hover >= 0 and bool(self.books[self.hover].get("path"))
        self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        index = self._book_at(event.position())
        if index >= 0 and self.books[index].get("path"):
            self.opened.emit(self.books[index]["path"])

    def _book_at(self, point) -> int:
        point = point.toPoint()
        for index, polygon in reversed(self.hits):
            if polygon.containsPoint(point, Qt.FillRule.OddEvenFill):
                return index
        return -1

    def _tick(self):
        now = time.monotonic()
        if not self.paused:
            self.offset += (now - self.last) * 16
        self.last = now
        self.update()

    def paintEvent(self, event):
        if not self.books:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        width, height = self.width(), self.height()
        book_w = min(height / 1.75, width / 8.5, 118)
        book_h = book_w * 1.5
        step = book_w * 1.25
        count = len(self.books)
        total = max(count * step, width * 1.25)
        step = total / count
        elapsed = time.monotonic() - self.started
        placed = []
        for index in range(count):
            x = (index * step - self.offset) % total - total / 2
            placed.append((abs(x), index, x))
        self.hits = []
        for _, index, x in sorted(placed, reverse=True):
            k = x / (width / 2)
            delay = .25 + abs(index - count / 2) * .06
            t = min(1.0, max(0.0, (elapsed - delay) / 1.1))
            if t <= 0:
                continue
            eased = _ease_out_back(t)
            fade = min(1.0, max(0.0, (1.02 - abs(k)) / .32))
            if fade <= 0:
                continue
            tilt = (1 if index % 2 else -1) * (6 + index % 5 * 3)
            transform = QTransform()
            transform.translate(width / 2 + x, height / 2 + 6 - (1 - eased) * height * 1.6 - (8 if index == self.hover else 0))
            transform.rotate(max(-60.0, min(60.0, -k * 50)), Qt.Axis.YAxis)
            scale = 1 + k * k * .3
            transform.scale(scale, scale)
            transform.rotate(tilt * (1 - eased))
            transform.translate(-book_w / 2, -book_h / 2)
            painter.setTransform(transform)
            painter.setOpacity(fade * min(1.0, t * 3))
            self._paint_book(painter, self.books[index], QRectF(0, 0, book_w, book_h))
            if fade >= .4:
                self.hits.append((index, transform.mapToPolygon(QRect(0, 0, int(book_w), int(book_h)))))

    def _paint_book(self, painter: QPainter, book: dict, rect: QRectF):
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(8):
            painter.setBrush(QColor(0, 0, 0, 22 - step * 2))
            painter.drawRoundedRect(rect.adjusted(2 - step, 10 + step * 2, -2 + step, 8 + step * 3), 6, 6)
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        painter.save()
        painter.setClipPath(path)
        cover = book.get("cover")
        if cover is not None and not cover.isNull():
            source = QRectF(cover.rect())
            scale = max(rect.width() / source.width(), rect.height() / source.height())
            painter.drawPixmap(QRectF(rect.center().x() - source.width() * scale / 2, rect.center().y() - source.height() * scale / 2,
                                      source.width() * scale, source.height() * scale), cover, source)
        else:
            painter.fillRect(rect, QColor(book["color"]))
            ink = QColor(book.get("ink", PAPER))
            inner = rect.adjusted(rect.width() * .16, rect.height() * .1, -rect.width() * .1, -rect.height() * .1)
            painter.setPen(ink)
            small = _font(SANS, rect.width() / 15)
            small.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
            painter.setFont(small)
            painter.drawText(inner, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, (book.get("author") or "").upper())
            manga = book.get("kind") == "manga"
            title = book["title"].upper() if manga else book["title"]
            pixels = rect.width() / (5.6 if manga else 8)
            title_font = _font(SANS if manga else SERIF, pixels, QFont.Weight.DemiBold if manga else QFont.Weight.Normal)
            longest = max(title.split() or [title], key=len)
            while pixels > 7 and QFontMetrics(title_font).horizontalAdvance(longest) > inner.width():
                pixels -= .5
                title_font.setPixelSize(round(pixels))
            painter.setFont(title_font)
            painter.drawText(inner.adjusted(0, inner.height() * .34, 0, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, title)
            line = QColor(ink)
            line.setAlpha(110)
            painter.fillRect(QRectF(inner.left(), inner.bottom() - 1, inner.width(), 1), line)
        painter.fillRect(QRectF(rect.left(), rect.top(), 5, rect.height()), QColor(0, 0, 0, 64))
        painter.fillRect(QRectF(rect.left() + 5, rect.top(), 1.5, rect.height()), QColor(255, 255, 255, 14))
        painter.restore()
