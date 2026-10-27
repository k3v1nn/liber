# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import copy
import hashlib
import html
import json
import re
import tempfile
import time
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageOps
from PIL.ImageQt import ImageQt

from PySide6.QtCore import QByteArray, QEasingCurve, QObject, QPropertyAnimation, QSettings, QSize, QStandardPaths, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QGraphicsOpacityEffect, QInputDialog, QLabel,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QStackedWidget, QVBoxLayout,
)

from .epub_export import export_manga, export_pdf
from .comic_pdf import import_comic_pdf
from .models import MangaProject, PdfProject
from .pdf_analysis import analyze_pdf, render_page
from .web_images import import_images_from_urls
from .i18n import EN, translate_engine_message
from .appearance import APP_NAME, PAPER, SEAL_DARK, SERIF, SUCCESS, THEME, WARN_INK, app_icon, line_icon, load_fonts
from .ui_layout import WorkspaceLayout
from .widgets import BLOCK_INDEX, BLOCK_LABEL, BLOCK_PAGE, BLOCK_ROLE, PAGE_CHAPTER, PAGE_COVER, PAGE_PATH, DropOverlay


IMAGE_FILTER = "Imagens (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
# Imported URL pages land in a temporary folder; its name must never become the book title.
TEMP_FOLDER_PREFIXES = ("conversor-epub-hq-", "conversor-epub-pdf-hq-")
TYPE_LABELS = {"Imagem": "Imagem", "Nota": "Nota", "Legenda": "Legenda", "Ignorar": "Ignorado"}
# Icon and colour that back up the tone of the footer message, so a failure never relies on colour alone.
TONE_ICONS = {"success": ("check", SUCCESS), "warning": ("alert", WARN_INK), "failure": ("alert", SEAL_DARK)}
COVER_COLORS = (("#2f4a3f", PAPER), ("#a8772e", "#17130f"), ("#5a2330", PAPER), ("#24334a", PAPER),
                ("#b8432b", PAPER), ("#3a3128", PAPER), ("#6d7b5b", PAPER), ("#22201d", "#c9a45c"))
# Public-domain classics shown on the shelf until the first EPUB is created.
SAMPLE_SHELF = (
    ("Dom Casmurro", "Machado de Assis", "pdf"), ("Iracema", "José de Alencar", "pdf"), ("O Cortiço", "Aluísio Azevedo", "pdf"),
    ("Kaze", "vol. 01", "manga"), ("Frankenstein", "Mary Shelley", "pdf"), ("Os Sertões", "Euclides da Cunha", "pdf"),
    ("Alice", "Lewis Carroll", "pdf"), ("Ronin", "vol. 07", "manga"), ("Senhora", "José de Alencar", "pdf"),
    ("Drácula", "Bram Stoker", "pdf"), ("Quincas Borba", "Machado de Assis", "pdf"), ("Mira", "vol. 03", "manga"),
)


def _natural_key(path: Path) -> list[int | str]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(path))]


def _images_in(folder: Path) -> list[Path]:
    return sorted((p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS), key=_natural_key)


def _scan_folders(paths: list[Path]) -> list[Path]:
    """Collect the images of dropped folders and files; runs on a worker thread."""
    images: list[Path] = []
    for path in paths:
        images.extend(_images_in(path) if path.is_dir() else [path] if path.suffix.lower() in IMAGE_EXTENSIONS else [])
    return images


def _sort_dropped(paths: list[Path]) -> tuple[list[Path], list[Path], list[Path], int]:
    """Folders, images and PDFs among dropped paths, plus how many paths are none of those."""
    folders = [path for path in paths if path.is_dir()]
    images = [path for path in paths if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
    pdfs = [path for path in paths if path.is_file() and path.suffix.lower() == ".pdf"]
    return folders, images, pdfs, len(paths) - len(folders) - len(images) - len(pdfs)


def parse_url_lines(text: str) -> tuple[list[str], int]:
    """Ordered, de-duplicated http(s) links from pasted text, plus the count of rejected lines."""
    urls: list[str] = []
    seen: set[str] = set()
    rejected = 0
    for line in text.splitlines():
        value = line.strip()
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            rejected += 1
            continue
        if value not in seen:
            seen.add(value)
            urls.append(value)
    return urls, rejected


def _read_oriented_pixmap(path: Path) -> QPixmap:
    try:
        with Image.open(path) as image:
            image.load()
            ImageOps.exif_transpose(image, in_place=True)
            if image.mode not in {"1", "L", "P", "RGB", "RGBA"}:
                image = image.convert("RGB")
            return QPixmap.fromImage(ImageQt(image))
    except (OSError, ValueError):
        return QPixmap()


# Workers that outlived their window: keeping them reachable stops Python from destroying a
# running QThread, which would abort the process.
RUNNING_TASKS = []


class TaskThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, function, *args):
        super().__init__()
        self.function = function
        self.args = args
        self._cancelled = False

    def cancel(self):
        """Ask the worker to stop; long-running callables poll `is_cancelled()`."""
        self._cancelled = True
        self.requestInterruption()

    def is_cancelled(self) -> bool:
        return self._cancelled or self.isInterruptionRequested()

    def run(self):
        try:
            result = self.function(*self.args)
        except Exception as exc:
            if not self.is_cancelled():
                self.failed.emit(str(exc))
            return
        if not self.is_cancelled():
            self.succeeded.emit(result)


def current_task() -> TaskThread | None:
    """The task running on this thread, so a worker can poll `is_cancelled()` without new arguments."""
    thread = QThread.currentThread()
    return thread if isinstance(thread, TaskThread) else None


def task_cancelled() -> bool:
    """Cancellation flag of the worker calling this, for callables started through `_start`."""
    task = current_task()
    return task is not None and task.is_cancelled()


class ImportProgress(QObject):
    """Carries worker-thread progress into the GUI thread; connected as a queued signal."""

    advanced = Signal(int, int, str)


class UrlImportDialog(QDialog):
    """Paste one or more public links, one per line."""

    def __init__(self, parent, title: str, hint: str, summary, accept_label: str, cancel_label: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self.summary = summary
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        label = QLabel(hint)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("https://exemplo.org/capitulo-1")
        self.editor.setFixedHeight(160)
        layout.addWidget(self.editor)
        self.count = QLabel("")
        layout.addWidget(self.count)
        self.buttons = QDialogButtonBox()
        self.accept_button = self.buttons.addButton(accept_label, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(cancel_label, QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.editor.textChanged.connect(self._sync)
        self._sync()

    def set_links(self, text: str):
        """Pre-fill from the clipboard without overwriting what the user already typed."""
        if not self.editor.toPlainText().strip():
            self.editor.setPlainText(text)

    def urls(self) -> list[str]:
        return parse_url_lines(self.editor.toPlainText())[0]

    def _sync(self):
        urls, rejected = parse_url_lines(self.editor.toPlainText())
        self.count.setText(self.summary(len(urls), rejected))
        self.accept_button.setEnabled(bool(urls))


class MainWindow(WorkspaceLayout, QMainWindow):
    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        load_fonts()
        self.settings = settings or QSettings("ConversorEPUB", "ConversorEPUB")
        saved_language = self.settings.value("ui_language", "pt")
        self.ui_language = saved_language if saved_language in ("pt", "en") else "pt"
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)
        self.setMinimumSize(780, 560)
        self.setAcceptDrops(True)
        self.pdf: PdfProject | None = None
        self.manga = MangaProject()
        self.selected_block = -1
        self.tasks: list[TaskThread] = []
        self.temp_downloads: list[tempfile.TemporaryDirectory] = []
        self.page_images: dict[int, QPixmap] = {}
        self.source_titles: dict[Path, str] = {}
        self.import_progress: ImportProgress | None = None
        self.busy = False
        self.failure: str | None = None
        self._analysis_origin: tuple[str, str] | None = None
        self._pending_language: str | None = None
        self._bar_bucket: int | None = None
        self._hero_bucket: int | None = None
        self.screen_name = "start"
        self.mode = "pdf"
        self._restore_session()
        self._install_shortcuts()
        self._build_ui()

    def _t(self, value: str, **values) -> str:
        text = EN.get(value, value) if self.ui_language == "en" else value
        return text.format(**values) if values else text

    def _plural(self, count: int, one: str, many: str) -> str:
        """Singular or plural phrase; both keys hold an `{n}` placeholder."""
        return self._t(one if count == 1 else many, n=count)

    def _with_shortcut(self, text: str, key) -> str:
        return f"{text} ({QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)})"

    def _restore_session(self):
        """Window size and last place come back from the previous run; unreadable values are ignored."""
        geometry = self.settings.value("window_geometry")
        if isinstance(geometry, (QByteArray, bytes)) and geometry:
            self.restoreGeometry(QByteArray(geometry))
        if self.settings.value("last_mode") in ("pdf", "manga"):
            self.mode = self.settings.value("last_mode")
        if self.settings.value("last_screen") == "workspace":
            self.screen_name = "workspace"

    def _save_session(self):
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("last_mode", self.mode)
        self.settings.setValue("last_screen", self.screen_name)

    def _install_shortcuts(self):
        self.shortcut_open = QShortcut(QKeySequence(QKeySequence.StandardKey.Open), self)
        self.shortcut_open.activated.connect(self._open_current)
        self.shortcut_save = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        self.shortcut_save.activated.connect(self._save_current)
        # Esc only claims the key while a task runs, so it keeps closing dialogs and menus otherwise.
        self.shortcut_cancel = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.shortcut_cancel.activated.connect(self._cancel_task)
        self.shortcut_cancel.setEnabled(False)

    def _open_current(self):
        """Ctrl+O: add images in comic mode, pick a PDF everywhere else."""
        if self.busy:
            self._message(self._t("Aguarde a tarefa atual terminar."), "warning")
        elif self.screen_name == "workspace" and self.mode == "manga":
            self._add_images()
        else:
            self._open_pdf()

    def _save_current(self):
        """Ctrl+S: export, but only where the Export button itself would be enabled."""
        if self.screen_name == "workspace" and self.export_button.isEnabled():
            self._export_current()

    def _message(self, value: str, tone: str = "info"):
        self.failure = None
        self._show_activity(value, tone)

    def _show_activity(self, value: str, tone: str):
        self.activity.setText(value)
        self._set_tone(tone)

    def _set_tone(self, tone: str):
        """Colour the footer line and show its icon; `info` is the quiet default."""
        if self.activity.property("tone") != tone:
            self.activity.setProperty("tone", tone)
            style = self.activity.style()
            style.unpolish(self.activity)
            style.polish(self.activity)
        icon = TONE_ICONS.get(tone)
        if icon:
            self.activity_icon.setPixmap(line_icon(icon[0], icon[1], 16).pixmap(QSize(16, 16)))
        self.activity_icon.setVisible(icon is not None)

    def _clear_failure(self):
        """A successful action wipes a leftover failure note from the activity line."""
        if self.failure is not None:
            self.failure = None
            self.activity.clear()
            self._set_tone("info")

    def _build_ui(self):
        self.language_toggles = []
        self.text_buttons = []
        self.add_buttons = []
        self.empty_action_buttons = []
        self.page_action_buttons = []
        self.editor_buttons = []
        self.editor_item = None
        self.block_items: list[QListWidgetItem] = []
        self.page_images.clear()
        # The language and the widget tree changed; both fits must run again.
        self._bar_bucket = None
        self._hero_bucket = None
        QApplication.instance().setStyleSheet(THEME)
        self.screens = QStackedWidget()
        self.screens.addWidget(self._start_screen())
        self.screens.addWidget(self._workspace())
        self.preview_stack.currentChanged.connect(self._preview_tab_changed)
        self.setCentralWidget(self.screens)
        self.drop_overlay = DropOverlay(self.screens)
        self._set_mode(self.mode)
        self._fit_bar(self.width(), force=True)
        self._set_busy(self.busy)
        if self.screen_name == "start":
            self._show_start()
        else:
            self.screens.setCurrentIndex(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_bar(self.width())

    def _fit_bar(self, width: int, force: bool = False):
        # Labels only change at these widths, so a resize inside a bucket must not rerun the styling.
        bucket = 0 if width < 920 else 1 if width < 1080 else 2
        if not force and bucket == self._bar_bucket:
            return
        self._bar_bucket = bucket
        for button in self.text_buttons:
            button.setText("" if bucket == 0 else self._t(button.property("label")))
        # The four comic sources shorten their labels before falling back to icons only.
        for button in self.add_buttons:
            label = button.property("label") if bucket == 2 else button.property("short") if bucket == 1 else ""
            button.setText(self._t(label) if label else "")

    def _fit_hero(self, width: int):
        bucket = 0 if width < 860 else 1 if width < 1100 else 2
        if bucket == self._hero_bucket:
            return
        self._hero_bucket = bucket
        self.hero_title.setStyleSheet(f"font-size: {(40, 50, 60)[bucket]}px;")

    def _fade_in(self, widget, duration: int):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: widget.setGraphicsEffect(None))
        animation.start()
        self._animation = animation

    def _show_start(self):
        self.screen_name = "start"
        self._refresh_shelf()
        self.screens.setCurrentIndex(0)
        self.shelf.restart()
        self._fade_in(self.hero, 900)

    def _show_workspace(self, mode: str):
        self._set_mode(mode)
        if self.screen_name != "workspace":
            self.screen_name = "workspace"
            self.screens.setCurrentIndex(1)
            self._fade_in(self.screens.widget(1), 350)

    def _set_mode(self, mode: str):
        switched = mode != self.mode
        self.mode = mode
        self.mode_stack.setCurrentIndex(0 if mode == "pdf" else 1)
        self.tab_buttons[mode].setChecked(True)
        self.pdf_import_button.setVisible(mode == "pdf")
        self.manga_add_group.setVisible(mode == "manga")
        self._refresh_status()
        if switched:
            self._retire_mode_note()

    def _retire_mode_note(self):
        """The other mode's note is stale; a running task or a warning keeps its line."""
        if self.busy or self.activity.property("tone") in ("failure", "warning"):
            return
        self.failure = None
        self.activity.clear()
        self._set_tone("info")

    def _refresh_status(self):
        if self.mode == "pdf":
            ready = bool(self.pdf and self.pdf.blocks)
            summary = self._t("{name} · {pages} páginas", name=self.pdf.source.name, pages=len(self.pdf.page_roles)) if self.pdf else ""
            missing = "Este PDF não tem blocos para exportar." if self.pdf else "Importe um PDF para poder exportar."
        else:
            ready = bool(self.manga.pages)
            chapters = len([p for p in self.manga.pages if str(p) in self.manga.chapter_titles])
            summary = self._t("{pages} páginas · {chapters} capítulos", pages=len(self.manga.pages), chapters=chapters) if ready else ""
            missing = "Adicione páginas para poder exportar."
        self.export_button.setEnabled(ready and not self.busy)
        # A disabled button says why, so the missing step is never a guess.
        if self.busy:
            tip = self._t("Aguarde a tarefa atual terminar.")
        elif ready:
            tip = self._with_shortcut(self._t("Gerar EPUB"), QKeySequence.StandardKey.Save)
        else:
            tip = self._t(missing)
        self.export_button.setToolTip(tip)
        self.summary.setText(summary)

    def _export_current(self):
        self._export_pdf() if self.mode == "pdf" else self._export_manga()

    def _change_language(self, language: str):
        """Defer the rebuild: it replaces the language button that emitted the click."""
        if language == self.ui_language or self._pending_language:
            return
        self._pending_language = language
        self._save_pdf_edit(quiet=True)
        state = {
            "pdf_meta": (self.pdf_title.text(), self.pdf_author.text(), self.pdf_language.text()),
            "manga_meta": (self.manga_title.text(), self.manga_author.text(), self.manga_language.text(), self.manga_rtl.isChecked()),
            "block": self.selected_block,
            "manga_row": self.manga_list.currentRow(),
            "filter": self.block_filter,
            "preview_tab": self.preview_stack.currentIndex(),
        }
        QTimer.singleShot(0, self, lambda: self._apply_language(state))

    def _apply_language(self, state: dict):
        language = self._pending_language
        self._pending_language = None
        if language is None:
            return
        self.ui_language = language
        self.settings.setValue("ui_language", language)
        self._build_ui()
        pdf_meta = state["pdf_meta"]
        manga_meta = state["manga_meta"]
        self.pdf_title.setText(pdf_meta[0]); self.pdf_author.setText(pdf_meta[1]); self.pdf_language.setText(pdf_meta[2])
        self.manga_title.setText(manga_meta[0]); self.manga_author.setText(manga_meta[1]); self.manga_language.setText(manga_meta[2]); self.manga_rtl.setChecked(manga_meta[3])
        self._check_block_filter(state["filter"])
        if self.pdf:
            self._show_pdf_warnings()
            self._populate_pdf(state["block"])
        self._refresh_manga_list()
        if state["manga_row"] >= 0:
            self.manga_list.setCurrentRow(state["manga_row"])
        self.preview_stack.setCurrentIndex(state["preview_tab"])
        self._update_reading_direction()
        self._message(self._t("Pronto para começar"))

    def _busy_controls(self) -> list:
        return [*self.add_buttons, *self.empty_action_buttons, self.pdf_import_button,
                *self.page_action_buttons, *self.editor_buttons]

    def _set_busy(self, busy: bool):
        """Every control that can start or reshape a task is gated by this single switch."""
        self.busy = busy
        for control in self._busy_controls():
            control.setEnabled(not busy)
        for toggle in self.language_toggles:
            toggle.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.shortcut_cancel.setEnabled(busy)
        self._refresh_status()

    def _start(self, label: str, function, done, *args, on_error=None, on_end=None) -> TaskThread:
        self._message(self._t(label))
        self.ribbon.start()
        task = TaskThread(function, *args)
        self.tasks.append(task)
        # Queued callbacks always land on the GUI thread, whatever thread emits the signal.
        task.succeeded.connect(done, Qt.ConnectionType.QueuedConnection)
        task.failed.connect(on_error or self._error, Qt.ConnectionType.QueuedConnection)
        if on_end is not None:
            task.finished.connect(on_end, Qt.ConnectionType.QueuedConnection)
        task.finished.connect(lambda: self._task_finished(task), Qt.ConnectionType.QueuedConnection)
        self._set_busy(True)
        task.start()
        return task

    def _cancel_task(self):
        if not self.tasks:
            return
        for task in self.tasks:
            task.cancel()
        self.cancel_button.setEnabled(False)
        self._message(self._t("Cancelando..."))

    def _task_finished(self, task: TaskThread):
        if task in self.tasks:
            self.tasks.remove(task)
        task.deleteLater()
        if not self.tasks:
            self.ribbon.stop()
            self._set_busy(False)
            if task.is_cancelled() and self.failure is None:
                self._message(self._t("Tarefa cancelada."))

    def _error(self, message: str):
        message = translate_engine_message(message, self.ui_language)
        self.failure = message
        self._show_activity(self._t("Falha: {message}", message=message), "failure")
        QMessageBox.critical(self, APP_NAME, message)

    def _retire_tasks(self, timeout_ms: int = 3000):
        """Stop workers before the window goes away; one that ignores cancellation is never destroyed."""
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        deadline = time.monotonic() + timeout_ms / 1000
        for task in tasks:
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if not task.wait(remaining):
                RUNNING_TASKS.append(task)
                task.finished.connect(task.deleteLater)
            if task in self.tasks:
                self.tasks.remove(task)

    def closeEvent(self, event):
        self._save_session()
        self._retire_tasks()
        for download in self.temp_downloads:
            try:
                download.cleanup()
            except OSError:
                pass
        self.temp_downloads.clear()
        super().closeEvent(event)

    def _dragged_paths(self, event) -> list[Path]:
        return [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]

    def _show_drop_overlay(self):
        self.drop_overlay.caption = self._t("Solte para importar")
        self.drop_overlay.setGeometry(self.screens.rect())
        self.drop_overlay.raise_()
        self.drop_overlay.show()

    def dragEnterEvent(self, event):
        if self.busy:
            self._message(self._t("Aguarde a tarefa atual terminar."), "warning")
            event.ignore()
            return
        paths = self._dragged_paths(event)
        folders, images, pdfs, _ = _sort_dropped(paths)
        if not (folders or images or pdfs):
            # Nothing the app can read: the drag is refused, and a drop would never arrive to explain why.
            if paths:
                self._message(self._t("Formato não suportado. Solte um PDF, imagens ou uma pasta."), "warning")
            event.ignore()
            return
        self._show_drop_overlay()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.drop_overlay.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.drop_overlay.hide()
        if self.busy:
            self._message(self._t("Aguarde a tarefa atual terminar."), "warning")
            event.ignore()
            return
        folders, images, pdfs, other = _sort_dropped(self._dragged_paths(event))
        note = ""
        if folders or images:
            if pdfs or other:
                note = self._t("Alguns itens foram ignorados.")
            self._show_workspace("manga")
            if folders:
                # Walking a dropped tree runs on a worker so the drop itself stays instant.
                self._start("Lendo pasta...", _scan_folders, self._folder_loaded, folders + images)
            else:
                self._append_manga_pages(sorted(images, key=_natural_key))
        elif pdfs:
            if len(pdfs) > 1:
                note = self._t("Só o primeiro PDF foi usado.")
            elif other:
                note = self._t("Alguns itens foram ignorados.")
            if self.screen_name == "workspace" and self.mode == "manga":
                self._add_comic_pdf(pdfs[0])
            else:
                self._analyze_pdf(str(pdfs[0]))
        else:
            self._message(self._t("Formato não suportado. Solte um PDF, imagens ou uma pasta."), "warning")
            event.ignore()
            return
        if note:
            self._message(f"{self.activity.text()} {note}", "warning")
        event.acceptProposedAction()

    def _recents(self) -> list[dict]:
        try:
            recents = json.loads(self.settings.value("recent_epubs", "[]"))
        except (TypeError, ValueError):
            return []
        return [entry for entry in recents if isinstance(entry, dict) and entry.get("path")] if isinstance(recents, list) else []

    def _refresh_shelf(self):
        recents = self._recents()
        if recents:
            books = []
            for index, entry in enumerate(recents):
                color, ink = COVER_COLORS[index % len(COVER_COLORS)]
                cover = entry.get("cover")
                books.append({"title": entry.get("title") or Path(entry["path"]).stem, "author": entry.get("author", ""),
                              "kind": entry.get("kind"), "color": color, "ink": ink, "path": entry["path"],
                              "cover": QPixmap(cover) if cover and Path(cover).is_file() else None})
            caption = "Últimos EPUBs · clique para abrir a pasta"
        else:
            books = [{"title": title, "author": author, "kind": kind, "color": COVER_COLORS[i % len(COVER_COLORS)][0],
                      "ink": COVER_COLORS[i % len(COVER_COLORS)][1]} for i, (title, author, kind) in enumerate(SAMPLE_SHELF)]
            caption = "Sua estante começa aqui"
        self.shelf.set_books(books)
        self.shelf_caption.setText(self._t(caption).upper())

    def _record_recent(self, kind: str, path: str):
        project = self.pdf if kind == "pdf" else self.manga
        entry = {"path": str(path), "title": project.title or Path(path).stem, "author": project.author, "kind": kind}
        cover = QPixmap()
        if project.custom_cover:
            cover = _read_oriented_pixmap(project.custom_cover)
        elif kind == "pdf":
            cover.loadFromData(render_page(project.source, project.cover_page, width=360))
        elif project.pages:
            cover = _read_oriented_pixmap(project.pages[project.cover_index])
        if not cover.isNull():
            folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "covers"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{hashlib.sha1(str(path).encode()).hexdigest()[:16]}.png"
            if cover.scaledToHeight(360, Qt.TransformationMode.SmoothTransformation).save(str(target)):
                entry["cover"] = str(target)
        recents = [item for item in self._recents() if item.get("path") != entry["path"]]
        self.settings.setValue("recent_epubs", json.dumps([entry, *recents][:14], ensure_ascii=False))

    def _export_done(self, kind: str, path: str):
        self._message(self._t("EPUB salvo em {path}", path=path), "success")
        self._record_recent(kind, path)

    def _open_recent(self, path: str):
        folder = Path(path).parent
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            self._error(self._t("A pasta deste EPUB não existe mais."))

    def _open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, self._t("Escolher PDF"), "", "PDF (*.pdf)")
        if path:
            self._analyze_pdf(path)

    def _analyze_pdf(self, path: str):
        # Keep the origin so a failed analysis can put the user back where they were.
        self._analysis_origin = (self.screen_name, self.mode)
        self._show_workspace("pdf")
        self._start("Analisando PDF...", analyze_pdf, self._pdf_loaded, path, on_error=self._analysis_failed)

    def _analysis_failed(self, message: str):
        origin = self._analysis_origin or (self.screen_name, self.mode)
        self._analysis_origin = None
        if self.pdf is None:
            self.pdf_stack.setCurrentIndex(0)
        if origin[0] == "start":
            self._show_start()
        else:
            self._show_workspace(origin[1])
        self._error(message)

    def _pdf_loaded(self, project: PdfProject):
        self._analysis_origin = None
        self.pdf = project
        self.selected_block = -1
        self.page_images.clear()
        self._check_block_filter("all")
        self.pdf_title.setText(project.title)
        self.pdf_title.setCursorPosition(0)
        self.pdf_author.setText(project.author)
        self.pdf_language.setText(project.language)
        self._show_pdf_warnings()
        self._populate_pdf()
        self._message(self._t("PDF analisado: {pages} páginas, {blocks} blocos.", pages=len(project.page_roles), blocks=len(project.blocks)), "success")

    def _show_pdf_warnings(self):
        """Warnings get their own strip above the structure list; only the general tip stays in the side panel."""
        warnings = [translate_engine_message(warning, self.ui_language) for warning in self.pdf.warnings]
        self.pdf_notice_text.setText("\n".join(warnings))
        self.pdf_notice.setVisible(bool(warnings))
        self.pdf_warning.setText(self._t("Análise concluída. Revise a estrutura antes de exportar."))

    def _populate_pdf(self, selected: int = 0):
        project = self.pdf
        if not project:
            return
        self.selected_block = -1
        self.pdf_stack.setCurrentIndex(1 if project.blocks else 0)
        self.block_list.blockSignals(True)
        self.block_list.clear()
        self.editor_item = None
        # Clearing the list deletes the editor widget, so its buttons must not stay in the busy gate.
        self.editor_buttons = []
        self.block_items = []
        for row in range(len(project.blocks)):
            item = QListWidgetItem()
            self.block_list.addItem(item)
            self.block_items.append(item)
            self._update_block_row(row)
        self.block_list.blockSignals(False)
        self._apply_block_filter()
        chapters = sum(block.role == "Capítulo" for block in project.blocks)
        self.pdf_count.setText(self._t("{chapters} capítulos · {blocks} blocos", chapters=chapters, blocks=len(project.blocks)))
        self.pdf_cover_combo.blockSignals(True)
        self.pdf_cover_combo.clear()
        for page in range(len(project.page_roles)):
            self.pdf_cover_combo.addItem(f"{self._t('Página')} {page + 1} · {self._t(project.page_roles[page])}", page)
        self.pdf_cover_combo.setCurrentIndex(project.cover_page)
        self.pdf_cover_combo.blockSignals(False)
        self.pdf_cover_combo.setEnabled(True)
        self._refresh_pdf_cover()
        self._refresh_pdf_preview()
        self._refresh_status()
        if project.blocks:
            self.block_list.setCurrentItem(self.block_items[min(max(selected, 0), len(project.blocks) - 1)])

    def _update_block_row(self, row: int):
        if not self.pdf:
            return
        block = self.pdf.blocks[row]
        item = self.block_items[row]
        item.setText(block.text[:200] if block.text else self._t("[imagem]"))
        item.setData(BLOCK_INDEX, row)
        item.setData(BLOCK_ROLE, block.role)
        item.setData(BLOCK_PAGE, block.page + 1)
        item.setData(BLOCK_LABEL, self._t(TYPE_LABELS[block.role]) if block.role in TYPE_LABELS else "")

    def _check_block_filter(self, key: str):
        """Sync the filter state and its buttons without touching the rows of a project in transit."""
        self.block_filter = key
        for name, button in self.filters.items():
            button.blockSignals(True)
            button.setChecked(name == key)
            button.blockSignals(False)

    def _filter_blocks(self, key: str):
        self._check_block_filter(key)
        self._apply_block_filter()

    def _apply_block_filter(self):
        if not self.pdf:
            return
        for row, item in enumerate(self.block_items):
            item.setHidden(self.block_filter != "all" and self.pdf.blocks[row].role != self.block_filter)
        if self.editor_item is not None and 0 <= self.selected_block < len(self.block_items):
            self.editor_item.setHidden(self.block_items[self.selected_block].isHidden())
        # A filter that hides every row gives way to an explanation instead of a blank panel.
        empty = bool(self.block_items) and all(item.isHidden() for item in self.block_items)
        self.block_stack.setCurrentIndex(1 if empty else 0)

    def _select_pdf_item(self, current, _previous):
        if not self.pdf or current is None or current.data(BLOCK_INDEX) is None:
            return
        self._save_pdf_edit(quiet=True)
        index = current.data(BLOCK_INDEX)
        block = self.pdf.blocks[index]
        self.selected_block = index
        self._place_editor(current, block)
        if self.preview_stack.currentIndex() == 1:
            self._show_pdf_page(block.page)
        self.pdf_preview.scrollToAnchor(f"b{index}")

    def _show_pdf_page(self, page: int):
        if not self.pdf:
            return
        image = self.page_images.get(page)
        if image is None:
            image = QPixmap()
            image.loadFromData(render_page(self.pdf.source, page, width=1200))
            self.page_images[page] = image
        self.pdf_page_image.set_image(image)

    def _preview_tab_changed(self, index: int):
        if index == 1 and self.pdf and 0 <= self.selected_block < len(self.pdf.blocks):
            self._show_pdf_page(self.pdf.blocks[self.selected_block].page)

    def _place_editor(self, item: QListWidgetItem, block):
        """Open the editor as a row right below the selected block."""
        self.block_list.blockSignals(True)
        if self.editor_item is not None:
            self.block_list.takeItem(self.block_list.row(self.editor_item))
        editor = self._block_editor(block)
        self.editor_item = QListWidgetItem()
        self.editor_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.editor_item.setSizeHint(QSize(10, editor.sizeHint().height()))
        self.block_list.insertItem(self.block_list.row(item) + 1, self.editor_item)
        self.block_list.setItemWidget(self.editor_item, editor)
        self.editor_item.setHidden(item.isHidden())
        self.block_list.blockSignals(False)
        self.block_list.scrollToItem(self.editor_item)
        self.block_list.scrollToItem(item)

    def _page_role_changed(self, value: str):
        if self.pdf and self.selected_block >= 0:
            page = self.pdf.blocks[self.selected_block].page
            self.pdf.page_roles[page] = self.page_role.currentData()
            self.pdf_cover_combo.setItemText(page, f"{self._t('Página')} {page + 1} · {self._t(self.pdf.page_roles[page])}")
            self._clear_failure()

    def _editor_changed(self) -> bool:
        """True while the open editor holds text or a type the block does not have yet."""
        if not self.pdf or self.selected_block < 0 or self.editor_item is None:
            return False
        block = self.pdf.blocks[self.selected_block]
        return self.block_role.currentData() != block.role or self.block_text.toPlainText().strip() != block.text.strip()

    def _refresh_editor_dirty(self, *_args):
        if self.editor_item is not None:
            self.editor_dirty.setVisible(self._editor_changed())

    def _save_pdf_edit(self, quiet: bool = False):
        if not self.pdf or self.selected_block < 0 or self.editor_item is None:
            return
        changed = self._editor_changed()
        block = self.pdf.blocks[self.selected_block]
        block.role = self.block_role.currentData()
        block.text = self.block_text.toPlainText().strip()
        self._update_block_row(self.selected_block)
        self._refresh_pdf_preview()
        self._refresh_editor_dirty()
        if not quiet:
            self._message(self._t("Correção salva no projeto atual."), "success")
        elif changed:
            # Moving on applies a pending edit; say so instead of changing the block silently.
            self._message(self._t("Correção aplicada ao bloco {number}.", number=self.selected_block + 1), "success")
        self._clear_failure()

    def _move_block(self, step: int):
        if not self.pdf or self.selected_block < 0:
            return
        self._save_pdf_edit(quiet=True)
        row = self.selected_block
        target = row + step
        if not 0 <= target < len(self.pdf.blocks):
            return
        if self.pdf.blocks[row].page != self.pdf.blocks[target].page:
            self._message(self._t("Reordene blocos dentro da mesma página."), "warning")
            return
        self.pdf.blocks[row], self.pdf.blocks[target] = self.pdf.blocks[target], self.pdf.blocks[row]
        self._populate_pdf(target)

    def _refresh_pdf_preview(self):
        if not self.pdf:
            return
        parts = [f"<html><body style=\"font-family:'{SERIF}', serif; font-size:15px; color:#2a221b\">"]
        for index, block in enumerate(self.pdf.blocks):
            if block.role == "Ignorar":
                continue
            anchor = f'<a name="b{index}"></a>'
            if block.role == "Imagem":
                caption = self._t("Imagem da página {page}", page=block.page + 1)
                parts.append(f"<p align='center' style='color:#9a8b76; font-size:13px'>{anchor}<i>[{caption}]</i></p>")
                continue
            text = block.rich_html if block.rich_html and block.text == block.source_text else html.escape(block.text)
            if block.role == "Capítulo":
                parts.append(f"<h1 align='center' style='font-weight:400; font-size:24px; margin-top:26px; margin-bottom:14px'>{anchor}{text}</h1>")
            elif block.role == "Seção":
                parts.append(f"<h2 style='font-weight:400; font-size:19px; margin-top:18px'>{anchor}{text}</h2>")
            elif block.role in ("Nota", "Legenda"):
                parts.append(f"<p align='{'center' if block.role == 'Legenda' else 'left'}' style='font-size:12px; color:#6b5d4d'>{anchor}{text}</p>")
            else:
                parts.append(f"<p style='text-indent:20px; margin-top:0; margin-bottom:6px; line-height:150%'>{anchor}{text}</p>")
        parts.append("</body></html>")
        self.pdf_preview.setHtml("".join(parts))
        if self.selected_block >= 0:
            self.pdf_preview.scrollToAnchor(f"b{self.selected_block}")

    def _pdf_cover_changed(self):
        if self.pdf and self.pdf_cover_combo.currentIndex() >= 0:
            self.pdf.cover_page = self.pdf_cover_combo.currentData()
            self.pdf.custom_cover = None
            self._refresh_pdf_cover()
            self._clear_failure()

    def _refresh_pdf_cover(self):
        if not self.pdf:
            self.pdf_cover_image.set_image(QPixmap())
            return
        info = ""
        if self.pdf.custom_cover:
            pixmap = _read_oriented_pixmap(self.pdf.custom_cover)
            info = f"{self._t('Capa customizada')}: {self.pdf.custom_cover.name}"
        else:
            pixmap = QPixmap()
            pixmap.loadFromData(render_page(self.pdf.source, self.pdf.cover_page, width=360))
        self.pdf_cover_image.set_image(pixmap)
        self.pdf_cover_info.setText(info)
        self.pdf_cover_info.setVisible(bool(info))
        self.pdf_clear_cover.setEnabled(self.pdf.custom_cover is not None)

    def _add_pdf_cover(self):
        if not self.pdf:
            self._message(self._t("Importe um PDF primeiro."), "warning")
            return
        path, _ = QFileDialog.getOpenFileName(self, self._t("Escolher imagem de capa"), "", self._t(IMAGE_FILTER))
        if path:
            self.pdf.custom_cover = Path(path)
            self._refresh_pdf_cover()
            self._clear_failure()

    def _remove_pdf_cover(self):
        if self.pdf:
            self.pdf.custom_cover = None
            self._refresh_pdf_cover()
            self._clear_failure()

    def _export_pdf(self):
        if not self.pdf:
            self._message(self._t("Importe um PDF primeiro."), "warning")
            return
        self._save_pdf_edit()
        self.pdf.title = self.pdf_title.text().strip()
        self.pdf.author = self.pdf_author.text().strip()
        self.pdf.language = self.pdf_language.text().strip()
        if len(self.pdf.scanned_pages) - len(self.pdf.ocr_pages) > len(self.pdf.page_roles) / 2:
            self._error(self._t("Este PDF parece escaneado e o OCR não recuperou texto suficiente. Confira as páginas antes de exportar."))
            return
        path, _ = QFileDialog.getSaveFileName(self, self._t("Salvar EPUB"), self.pdf.source.with_suffix(".epub").name, "EPUB (*.epub)")
        if path:
            # Workers get their own copy so live edits never race the export.
            snapshot = copy.deepcopy(self.pdf)
            self._start("Gerando EPUB...", export_pdf, lambda _: self._export_done("pdf", path), snapshot, path)

    def _new_temp(self, prefix: str) -> tempfile.TemporaryDirectory:
        download = tempfile.TemporaryDirectory(prefix=prefix)
        self.temp_downloads.append(download)
        return download

    def _release_source(self, folder: Path):
        """Delete a temporary folder once no page from it is left in the project."""
        folder = Path(folder)
        for download in list(self.temp_downloads):
            root = Path(download.name)
            # A URL batch owns the folder plus one source-NN subfolder per link.
            if folder != root and root not in folder.parents:
                continue
            if any(path.parent == root or root in path.parents for path in self.manga.pages):
                return
            self.temp_downloads.remove(download)
            self.source_titles.pop(root, None)
            try:
                download.cleanup()
            except OSError:
                pass
            return

    def _pages_and_sources_text(self) -> str:
        pages = self._plural(len(self.manga.pages), "{n} página", "{n} páginas")
        sources = self._plural(len({path.parent for path in self.manga.pages}), "{n} fonte", "{n} fontes")
        return self._t("{pages} nesta HQ ({sources}).", pages=pages, sources=sources)

    def _page_tooltip(self, path: Path) -> str:
        title = self.source_titles.get(path.parent)
        return f"{title} · {path.name}" if title else path.name

    def _manga_item(self, index: int, path: Path) -> QListWidgetItem:
        item = QListWidgetItem(f"{index + 1:03d}")
        item.setData(PAGE_PATH, str(path))
        item.setData(PAGE_COVER, index == self.manga.cover_index and not self.manga.custom_cover)
        item.setData(PAGE_CHAPTER, self.manga.chapter_titles.get(str(path), ""))
        item.setToolTip(self._page_tooltip(path))
        return item

    def _rebuild_manga_cover_combo(self):
        pages = self.manga.pages
        self.manga_cover_combo.blockSignals(True)
        self.manga_cover_combo.clear()
        for index, path in enumerate(pages):
            self.manga_cover_combo.addItem(f"{self._t('Página')} {index + 1} · {path.name}", index)
        if not pages:
            self.manga_cover_combo.addItem(self._t("Adicione páginas para escolher a capa"))
        self.manga_cover_combo.setCurrentIndex(self.manga.cover_index if pages else 0)
        self.manga_cover_combo.blockSignals(False)
        self.manga_cover_combo.setEnabled(bool(pages))

    def _update_manga_counts(self):
        pages = self.manga.pages
        chapters = len([p for p in pages if str(p) in self.manga.chapter_titles])
        self.manga_count.setText(self._t("{pages} páginas · {chapters} capítulos", pages=len(pages), chapters=chapters))

    def _append_manga_pages(self, paths: list[Path], announce: bool = True):
        """Append only the new pages: existing rows, their thumbnails and the selection survive."""
        existing = set(self.manga.pages)
        added: list[Path] = []
        for path in paths:
            path = Path(path)
            if path in existing or not path.is_file():
                continue
            existing.add(path)
            added.append(path)
        if not added:
            self._refresh_status()
            return
        first = len(self.manga.pages)
        self.manga.pages.extend(added)
        was_empty = first == 0
        self.manga_stack.setCurrentIndex(1)
        self.manga_list.blockSignals(True)
        for position, path in enumerate(added):
            self.manga_list.addItem(self._manga_item(first + position, path))
        self.manga_list.blockSignals(False)
        # One combo rebuild per batch keeps the cover picker in sync without a per-page signal storm.
        self._rebuild_manga_cover_combo()
        self._update_manga_counts()
        if was_empty:
            # The first page is the cover now; select it once instead of decoding on every import.
            self.manga_list.setCurrentRow(0)
            self._refresh_manga_cover()
        self._refresh_status()
        if announce:
            self._message(self._pages_and_sources_text())

    def _refresh_manga_list(self):
        current = self.manga_list.currentRow()
        pages = self.manga.pages
        self.manga_stack.setCurrentIndex(1 if pages else 0)
        self.manga_list.blockSignals(True)
        self.manga_list.clear()
        for index, path in enumerate(pages):
            self.manga_list.addItem(self._manga_item(index, path))
        self.manga_list.blockSignals(False)
        self._rebuild_manga_cover_combo()
        self._update_manga_counts()
        if pages:
            self.manga_list.setCurrentRow(min(max(current, 0), len(pages) - 1))
        else:
            self._show_manga_page(-1)
        self._refresh_manga_cover()
        self._refresh_status()

    def _add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self._t("Escolher imagens"), "", self._t(IMAGE_FILTER))
        if paths:
            self._append_manga_pages(sorted((Path(p) for p in paths), key=_natural_key))

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, self._t("Escolher pasta de imagens"))
        if path:
            # The recursive walk can be slow on a big tree, so it runs on a worker.
            self._start("Lendo pasta...", _scan_folders, self._folder_loaded, [Path(path)])

    def _folder_loaded(self, paths: list[Path]):
        if not paths:
            self._message(self._t("Nenhuma imagem foi encontrada nessa pasta."), "warning")
            return
        self._append_manga_pages(paths)

    def _add_comic_pdf(self, source: Path | None = None):
        if source is None:
            path, _ = QFileDialog.getOpenFileName(self, self._t("Escolher PDF de HQ"), "", "PDF (*.pdf)")
            if not path:
                return
            source = Path(path)
        temp = self._new_temp("conversor-epub-pdf-hq-")
        self._show_workspace("manga")
        self._start("Convertendo páginas do PDF...", import_comic_pdf,
                    lambda pages: self._comic_pdf_loaded(pages, source), source, temp.name,
                    on_end=lambda: self._release_source(Path(temp.name)))

    def _comic_pdf_loaded(self, paths: list[Path], source: Path):
        if not self.manga_title.text().strip():
            self.manga_title.setText(source.stem)
        self._append_manga_pages(paths)

    def _clipboard_links(self) -> str:
        urls, _ = parse_url_lines(QApplication.clipboard().text() or "")
        return "\n".join(urls)

    def _link_counts(self, valid: int, rejected: int) -> str:
        parts = [self._plural(valid, "{n} link pronto", "{n} links prontos")]
        if rejected:
            parts.append(self._plural(rejected, "{n} linha inválida ignorada", "{n} linhas inválidas ignoradas"))
        return " · ".join(parts)

    def _add_url(self):
        dialog = UrlImportDialog(self, self._t("Importar imagens"),
                                 self._t("Cole um ou vários links (um por linha) de imagens ou páginas públicas:"),
                                 self._link_counts, self._t("Importar"), self._t("Cancelar"))
        links = self._clipboard_links()
        if links:
            dialog.set_links(links)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        urls = dialog.urls()
        if not urls:
            self._message(self._t("Nenhum link válido para importar."), "warning")
            return
        temp = self._new_temp("conversor-epub-hq-")
        progress = ImportProgress()
        progress.advanced.connect(self._import_progress, Qt.ConnectionType.QueuedConnection)
        # The hub must outlive the worker emitting into it.
        self.import_progress = progress
        self._show_workspace("manga")
        # One task for the whole paste; the worker keeps the URL order and cancels between images.
        self._start("Baixando imagens da página...",
                    partial(import_images_from_urls, progress=progress.advanced.emit, is_cancelled=task_cancelled),
                    lambda reports: self._imported(reports, urls), urls, Path(temp.name),
                    on_end=lambda: self._import_finished(temp))

    def _import_progress(self, done: int, total: int, message: str):
        self.ribbon.set_progress(done, total)
        detail = translate_engine_message(message, self.ui_language)
        self.activity.setText(self._t("Baixando {done}/{total} — {detail}", done=done, total=total, detail=detail))

    def _import_finished(self, download: tempfile.TemporaryDirectory):
        """A cancelled or empty import leaves no pages behind, so its folder can go."""
        self.import_progress = None
        self._release_source(Path(download.name))

    def _imported(self, reports, urls: list[str]):
        self.import_progress = None
        pages: list[Path] = []
        skipped = 0
        truncated = False
        failures: list[tuple[int, str]] = []
        for rank, report in enumerate(reports, 1):
            if report.paths and report.title:
                self.source_titles[Path(report.paths[0]).parent] = report.title
            pages.extend(Path(path) for path in report.paths)
            skipped += report.skipped
            truncated = truncated or report.truncated
            if report.error:
                position = urls.index(report.url) + 1 if report.url in urls else rank
                failures.append((position, translate_engine_message(report.error, self.ui_language)))
        if not pages:
            message = self._t("Nenhuma imagem de página foi encontrada. Tente salvar as imagens e usar 'Adicionar pasta'.")
            self._message(f"{message} {failures[0][1]}" if failures else message, "warning")
            return
        before = len(self.manga.pages)
        self._append_manga_pages(pages, announce=False)
        added = len(self.manga.pages) - before
        if added and not self.manga_title.text().strip():
            # The page title is a better default than the temporary folder of the import.
            title = next((report.title for report in reports if report.paths and report.title), "")
            if title:
                self.manga_title.setText(title)
        self._message(self._import_message(added, len(urls), skipped, truncated, failures), "success")

    def _import_message(self, added: int, links: int, skipped: int, truncated: bool,
                        failures: list[tuple[int, str]]) -> str:
        detail = [self._t("{pages} de {links}", pages=self._plural(added, "{n} página", "{n} páginas"),
                          links=self._plural(links, "{n} link", "{n} links"))]
        if skipped:
            detail.append(self._t("{n} ignoradas", n=skipped))
        detail.extend(self._t("link {position} falhou: {reason}", position=position, reason=reason) for position, reason in failures)
        if truncated:
            detail.append(self._t("limitado a 300"))
        return f"{self._pages_and_sources_text()} {'; '.join(detail)}."

    def _show_manga_page(self, row: int):
        if not 0 <= row < len(self.manga.pages):
            self.manga_image.set_image(QPixmap())
            self.manga_caption.setText("")
            return
        path = self.manga.pages[row]
        self.manga_image.set_image(_read_oriented_pixmap(path))
        chapter = next((self.manga.chapter_titles[str(p)] for p in reversed(self.manga.pages[:row + 1]) if str(p) in self.manga.chapter_titles), "")
        cover = row == self.manga.cover_index and not self.manga.custom_cover
        self.manga_caption.setText(" · ".join(part for part in (path.name, chapter, self._t("Capa").lower() if cover else "") if part))
        self._update_reading_direction()

    def _update_reading_direction(self):
        self.manga_direction.setText(self._t("← direita para a esquerda") if self.manga_rtl.isChecked() else self._t("esquerda para a direita →"))

    def _manga_reordered(self):
        paths = [Path(self.manga_list.item(i).data(PAGE_PATH)) for i in range(self.manga_list.count())]
        if sorted(map(str, paths)) != sorted(map(str, self.manga.pages)):
            self._refresh_manga_list()
            return
        cover = self.manga.pages[self.manga.cover_index] if self.manga.pages else None
        row = self.manga_list.currentRow()
        self.manga.pages = paths
        if cover in paths:
            self.manga.cover_index = paths.index(cover)
        self._refresh_manga_list()
        self.manga_list.setCurrentRow(row)
        self._clear_failure()

    def _move_page(self, step: int):
        row = self.manga_list.currentRow()
        target = row + step
        if 0 <= row < len(self.manga.pages) and 0 <= target < len(self.manga.pages):
            self.manga.pages[row], self.manga.pages[target] = self.manga.pages[target], self.manga.pages[row]
            if self.manga.cover_index == row:
                self.manga.cover_index = target
            elif self.manga.cover_index == target:
                self.manga.cover_index = row
            self._refresh_manga_list()
            self.manga_list.setCurrentRow(target)
            self._clear_failure()

    def _remove_page(self):
        row = self.manga_list.currentRow()
        if 0 <= row < len(self.manga.pages):
            removed = self.manga.pages.pop(row)
            self.manga.chapter_titles.pop(str(removed), None)
            if self.manga.cover_index > row:
                self.manga.cover_index -= 1
            self.manga.cover_index = min(self.manga.cover_index, max(0, len(self.manga.pages) - 1))
            self._refresh_manga_list()
            # The folder of that source has no page left in the project once its last one is gone.
            self._release_source(removed.parent)
            self._clear_failure()

    def _use_page_as_cover(self):
        row = self.manga_list.currentRow()
        if 0 <= row < len(self.manga.pages):
            self.manga.cover_index = row
            self.manga.custom_cover = None
            self._refresh_manga_list()
            self.manga_list.setCurrentRow(row)
            self._clear_failure()

    def _manga_cover_changed(self):
        if self.manga_cover_combo.currentIndex() >= 0 and self.manga.pages:
            self.manga.cover_index = self.manga_cover_combo.currentData()
            self.manga.custom_cover = None
            self._refresh_manga_list()
            self._clear_failure()

    def _refresh_manga_cover(self):
        source = self.manga.custom_cover
        info = f"{self._t('Capa customizada')}: {source.name}" if source else ""
        if not source and self.manga.pages:
            source = self.manga.pages[self.manga.cover_index]
        self.manga_cover_image.set_image(_read_oriented_pixmap(source) if source else QPixmap())
        self.manga_cover_info.setText(info)
        self.manga_cover_info.setVisible(bool(info))
        self.manga_clear_cover.setEnabled(self.manga.custom_cover is not None)

    def _add_manga_cover(self):
        path, _ = QFileDialog.getOpenFileName(self, self._t("Escolher imagem de capa"), "", self._t(IMAGE_FILTER))
        if path:
            self.manga.custom_cover = Path(path)
            self._refresh_manga_list()
            self._clear_failure()

    def _remove_manga_cover(self):
        self.manga.custom_cover = None
        self._refresh_manga_list()
        self._clear_failure()

    def _set_manga_chapter(self):
        row = self.manga_list.currentRow()
        if not 0 <= row < len(self.manga.pages):
            return
        page = self.manga.pages[row]
        current = self.manga.chapter_titles.get(str(page), "")
        title, ok = QInputDialog.getText(self, self._t("Capítulo"), self._t("Título do capítulo que começa nesta página:"), text=current)
        if ok:
            if title.strip():
                self.manga.chapter_titles[str(page)] = title.strip()
            else:
                self.manga.chapter_titles.pop(str(page), None)
            self._refresh_manga_list()
            self.manga_list.setCurrentRow(row)
            self._clear_failure()

    def _default_manga_title(self) -> str:
        if not self.manga.pages:
            return "HQ"
        folder = self.manga.pages[0].parent
        # Imported URL pages live in a temporary folder; its name must never become the book title.
        if folder.name.startswith(TEMP_FOLDER_PREFIXES):
            return self.source_titles.get(folder) or "HQ"
        return folder.name

    def _export_manga(self):
        if not self.manga.pages:
            self._message(self._t("Adicione imagens primeiro."), "warning")
            return
        self.manga.title = self.manga_title.text().strip() or self._default_manga_title()
        self.manga.author = self.manga_author.text().strip()
        self.manga.language = self.manga_language.text().strip()
        self.manga.right_to_left = self.manga_rtl.isChecked()
        path, _ = QFileDialog.getSaveFileName(self, self._t("Salvar EPUB"), f"{self.manga.title}.epub", "EPUB (*.epub)")
        if path:
            # Workers get their own copy so live edits never race the export.
            snapshot = copy.deepcopy(self.manga)
            self._start("Gerando EPUB de HQ...", export_manga, lambda _: self._export_done("manga", path), snapshot, path)


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    load_fonts()
    app.setWindowIcon(QIcon(app_icon(256)))
    window = MainWindow()
    window.show()
    app.exec()
