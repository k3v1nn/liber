# SPDX-License-Identifier: AGPL-3.0-only
"""Custom-painted widgets for the paper interface and the opening shelf."""

from __future__ import annotations

import time
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import (
    QEvent, QObject, QPointF, QRect, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QImage, QImageReader, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QTransform,
)
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QLabel, QListView, QListWidget, QSizePolicy, QStyle, QStyledItemDelegate,
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


def device_size(size: QSize, ratio: float) -> QSize:
    """Pixel size a cached pixmap needs so it stays sharp on high-DPI screens."""
    return QSize(max(1, round(size.width() * ratio)), max(1, round(size.height() * ratio)))


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
        self.scaled = QPixmap()
        self.scaled_for = QSize()
        self.setMinimumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def set_image(self, image: QPixmap):
        self.original = image
        self.scaled = QPixmap()
        self.update()

    def _page_pixmap(self, target: QSize) -> QPixmap:
        """Scale once per target size; consecutive paints reuse the cached pixmap."""
        if self.scaled.isNull() or self.scaled_for != target:
            self.scaled_for = target
            self.scaled = self.original.scaled(target, Qt.AspectRatioMode.IgnoreAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation)
        return self.scaled

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
        image = self._page_pixmap(device_size(size, self.devicePixelRatioF()))
        _shadow(painter, page, 2)
        painter.drawPixmap(page, image, QRectF(image.rect()))
        painter.setPen(QPen(QColor(LINE), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(page)


class CoverThumb(QWidget):
    """Book-shaped cover thumbnail that tilts slightly on hover."""

    def __init__(self, size: QSize):
        super().__init__()
        self.pixmap = QPixmap()
        self.scaled = QPixmap()
        self.scaled_for = QSize()
        self.hovered = False
        self.setFixedSize(size)

    def set_image(self, pixmap: QPixmap):
        self.pixmap = pixmap
        self.scaled = QPixmap()
        self.update()

    def enterEvent(self, event):
        self.hovered = True
        self.update()

    def leaveEvent(self, event):
        self.hovered = False
        self.update()

    def _cover(self, target: QSize) -> QPixmap:
        """Crop-scaling runs once per size; painting only blits the cached pixmap."""
        if self.scaled.isNull() or self.scaled_for != target:
            self.scaled_for = target
            self.scaled = self.pixmap.scaled(target, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                             Qt.TransformationMode.SmoothTransformation)
        return self.scaled

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
            target = device_size(book.size().toSize(), self.devicePixelRatioF())
            cover = self._cover(target)
            source = QRectF((cover.width() - target.width()) / 2, (cover.height() - target.height()) / 2,
                            target.width(), target.height())
            painter.drawPixmap(book, cover, source)
        painter.fillRect(QRectF(book.left(), book.top(), 4, book.height()), QColor(0, 0, 0, 55))


class ProgressRibbon(QWidget):
    """A thin red ribbon under the toolbar that runs while a task is busy."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(2)
        self.phase = 0.0
        self.fraction: float | None = None
        self.animation = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1500, loopCount=-1)
        self.animation.valueChanged.connect(self._tick)

    def _tick(self, value):
        self.phase = value
        self.update()

    def start(self):
        self.fraction = None
        self.animation.start()

    def set_progress(self, done: int, total: int):
        """A worker-reported fraction replaces the indeterminate sweep."""
        if total <= 0:
            return
        self.fraction = max(0.0, min(1.0, done / total))
        self.update()

    def stop(self):
        self.animation.stop()
        self.fraction = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.fraction is not None:
            painter.fillRect(QRectF(0, 0, self.width() * self.fraction, 2), QColor(SEAL))
            return
        if self.animation.state() != QVariantAnimation.State.Running:
            return
        segment = self.width() * .3
        painter.fillRect(QRectF(-segment + (self.width() + segment) * self.phase, 0, segment, 2), QColor(SEAL))


class ElidedLabel(QLabel):
    """One-line label that shows what fits, with the whole text as tooltip; `text()` keeps returning all of it."""

    def __init__(self, text: str = "", mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight):
        super().__init__()
        self._full = ""
        self._mode = mode
        self.setWordWrap(False)
        self.setText(text)

    def text(self) -> str:
        return self._full

    def setText(self, text: str):
        self._full = text
        self.setToolTip(text)
        self._elide()
        self.updateGeometry()

    def clear(self):
        self.setText("")

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self._full) + 2, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(10, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._elide()

    def _elide(self):
        width = self.contentsRect().width()
        shown = self.fontMetrics().elidedText(self._full, self._mode, width) if width > 0 else self._full
        if shown != QLabel.text(self):
            QLabel.setText(self, shown)


class DropOverlay(QWidget):
    """Dashed frame and caption laid over the window while files are dragged onto it."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.caption = ""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(184, 67, 43, 22))
        pen = QPen(QColor(SEAL), 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(14, 14, -14, -14), 14, 14)
        font = _font(SANS, 14, QFont.Weight.Medium)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        pill = QRectF(0, 0, metrics.horizontalAdvance(self.caption) + 40, 38)
        pill.moveCenter(QPointF(self.rect().center()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(INK))
        painter.drawRoundedRect(pill, 19, 19)
        painter.setPen(QColor(PAPER))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, self.caption)


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


THUMBNAIL_SIZE = QSize(168, 240)
THUMBNAIL_CACHE_LIMIT = 256


def _decode_thumbnail(path: str, size: QSize) -> QImage:
    """Decode a small, EXIF-oriented copy of an image; safe to call off the GUI thread."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    source = reader.size()
    if source.isValid() and not source.isEmpty():
        reader.setScaledSize(source.scaled(size, Qt.AspectRatioMode.KeepAspectRatio))
    return reader.read()


class _ThumbnailRequest(QRunnable):
    def __init__(self, path: str, mtime: float):
        super().__init__()
        self.path = path
        self.mtime = mtime

    def run(self):
        THUMBNAILS.finished.emit(self.path, self.mtime, _decode_thumbnail(self.path, THUMBNAIL_SIZE))


class ThumbnailLoader(QObject):
    """Decodes page thumbnails off the GUI thread; LRU cache keyed by path and modification time."""

    finished = Signal(str, float, QImage)
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.cache: OrderedDict[tuple[str, float], QPixmap] = OrderedDict()
        self.pending: set[tuple[str, float]] = set()
        # Holding the runnables keeps Python from collecting a worker the pool is still running.
        self.requests: dict[tuple[str, float], _ThumbnailRequest] = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        # The signal arrives from a worker thread; storing the QPixmap must happen on the GUI one.
        self.finished.connect(self._store, Qt.ConnectionType.QueuedConnection)

    def thumb(self, path: str) -> QPixmap:
        """The cached thumbnail, or an empty pixmap while the request is in flight."""
        if not path:
            return QPixmap()
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            return QPixmap()
        key = (path, mtime)
        cached = self.cache.get(key)
        if cached is not None:
            self.cache.move_to_end(key)
            return cached
        if key not in self.pending:
            self.pending.add(key)
            request = _ThumbnailRequest(*key)
            self.requests[key] = request
            self.pool.start(request)
        return QPixmap()

    def _store(self, path: str, mtime: float, image: QImage):
        key = (path, mtime)
        self.pending.discard(key)
        self.requests.pop(key, None)
        # A failed decode is cached as an empty pixmap: repainting must not retry it every frame.
        pixmap = QPixmap()
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(2)
        self.cache[key] = pixmap
        self.cache.move_to_end(key)
        while len(self.cache) > THUMBNAIL_CACHE_LIMIT:
            self.cache.popitem(last=False)
        self.changed.emit()

    def busy(self) -> bool:
        return bool(self.pending)


# One loader for the whole app: thumbnails survive list rebuilds and language switches.
THUMBNAILS = ThumbnailLoader()


class PageList(QListWidget):
    """Wrapping grid of comic pages that can be reordered by dragging."""

    reordered = Signal()

    def __init__(self):
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
        self.setItemDelegate(PageThumbDelegate(self))

    def dropEvent(self, event):
        super().dropEvent(event)
        self.reordered.emit()


class PageThumbDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.number = _font(SANS, 10.5)
        self.chapter = _font(SERIF, 11.5)
        THUMBNAILS.changed.connect(self._thumb_ready)

    def _thumb_ready(self):
        view = self.parent()
        if view is not None:
            view.viewport().update()

    def sizeHint(self, option, index):
        return QSize(98, 176)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        cell = QRectF(option.rect)
        area = QRectF(cell.left() + 8, cell.top() + 10, cell.width() - 16, 124)
        # Never decodes here: the first paint shows a placeholder and the loader repaints later.
        image = THUMBNAILS.thumb(index.data(PAGE_PATH) or "")
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
        self.title_fonts: dict[tuple[str, str, int], QFont] = {}
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
        self.last = self.started
        if self.isVisible() and not self.timer.isActive():
            self.timer.start()
        self.update()

    def showEvent(self, event):
        self.last = time.monotonic()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()

    def leaveEvent(self, event):
        self.paused = False
        self.hover = -1
        self.last = time.monotonic()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if self.isVisible() and not self.timer.isActive():
            self.timer.start()

    def mouseMoveEvent(self, event):
        self.paused = True
        self.hover = self._book_at(event.position())
        clickable = self.hover >= 0 and bool(self.books[self.hover].get("path"))
        self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        index = self._book_at(event.position())
        if index >= 0 and self.books[index].get("path"):
            self.opened.emit(self.books[index]["path"])

    def _placed_books(self) -> list[tuple[int, QTransform, float, float, float]]:
        """Geometry of the books on screen right now: index, transform, opacity, width, height."""
        width, height = self.width(), self.height()
        count = len(self.books)
        if not count or width <= 0 or height <= 0:
            return []
        book_w = min(height / 1.75, width / 8.5, 118)
        book_h = book_w * 1.5
        total = max(count * book_w * 1.25, width * 1.25)
        step = total / count
        elapsed = time.monotonic() - self.started
        placed = [((index * step - self.offset) % total - total / 2, index) for index in range(count)]
        placed.sort(key=lambda item: (abs(item[0]), item[1]), reverse=True)
        geometry = []
        for x, index in placed:
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
            geometry.append((index, transform, fade * min(1.0, t * 3), book_w, book_h))
        return geometry

    def _book_at(self, point) -> int:
        """Hit-test at click time; the painted geometry may belong to an older frame."""
        point = point.toPoint()
        for index, transform, opacity, book_w, book_h in reversed(self._placed_books()):
            if opacity >= .4 and transform.mapToPolygon(QRect(0, 0, int(book_w), int(book_h))).containsPoint(
                    point, Qt.FillRule.OddEvenFill):
                return index
        return -1

    def _settled(self) -> bool:
        """True once every book has finished falling into place."""
        return time.monotonic() - self.started > .25 + len(self.books) * .03 + 1.1

    def _tick(self):
        now = time.monotonic()
        if self.paused and self._settled():
            # A settled shelf under the pointer needs no 60 fps repaints.
            self.timer.stop()
            self.update()
            return
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
        for index, transform, opacity, book_w, book_h in self._placed_books():
            painter.setTransform(transform)
            painter.setOpacity(opacity)
            self._paint_book(painter, self.books[index], QRectF(0, 0, book_w, book_h))

    def _title_font(self, title: str, manga: bool, width: float) -> QFont:
        """Fit the title once per cover width; painting itself never measures fonts."""
        key = (title, "manga" if manga else "book", round(width))
        font = self.title_fonts.get(key)
        if font is None:
            available = width * .74
            pixels = width / (5.6 if manga else 8)
            font = _font(SANS if manga else SERIF, pixels, QFont.Weight.DemiBold if manga else QFont.Weight.Normal)
            longest = max(title.split() or [title], key=len)
            while pixels > 7 and QFontMetrics(font).horizontalAdvance(longest) > available:
                pixels -= .5
                font.setPixelSize(round(pixels))
            if len(self.title_fonts) > 256:
                self.title_fonts.clear()
            self.title_fonts[key] = font
        return font

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
            painter.setFont(self._title_font(title, manga, rect.width()))
            painter.drawText(inner.adjusted(0, inner.height() * .34, 0, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, title)
            line = QColor(ink)
            line.setAlpha(110)
            painter.fillRect(QRectF(inner.left(), inner.bottom() - 1, inner.width(), 1), line)
        painter.fillRect(QRectF(rect.left(), rect.top(), 5, rect.height()), QColor(0, 0, 0, 64))
        painter.fillRect(QRectF(rect.left() + 5, rect.top(), 1.5, rect.height()), QColor(255, 255, 255, 14))
        painter.restore()
