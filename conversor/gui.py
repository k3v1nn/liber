# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import hashlib
import html
import json
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageOps
from PIL.ImageQt import ImageQt

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSettings, QSize, QStandardPaths, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QGraphicsOpacityEffect, QInputDialog, QListWidgetItem,
    QMainWindow, QMessageBox, QStackedWidget,
)

from .epub_export import export_manga, export_pdf
from .comic_pdf import import_comic_pdf
from .models import MangaProject, PdfProject
from .pdf_analysis import analyze_pdf, render_page
from .web_images import import_images_from_url
from .i18n import EN, translate_engine_message
from .appearance import APP_NAME, PAPER, SERIF, THEME, app_icon, load_fonts
from .ui_layout import WorkspaceLayout
from .widgets import BLOCK_INDEX, BLOCK_LABEL, BLOCK_PAGE, BLOCK_ROLE, PAGE_CHAPTER, PAGE_COVER, PAGE_PATH


IMAGE_FILTER = "Imagens (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
TYPE_LABELS = {"Imagem": "Imagem", "Nota": "Nota", "Legenda": "Legenda", "Ignorar": "Ignorado"}
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


class TaskThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, function, *args):
        super().__init__()
        self.function = function
        self.args = args

    def run(self):
        try:
            self.succeeded.emit(self.function(*self.args))
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(WorkspaceLayout, QMainWindow):
    def __init__(self):
        super().__init__()
        load_fonts()
        self.settings = QSettings("ConversorEPUB", "ConversorEPUB")
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
        self.screen_name = "start"
        self.mode = "pdf"
        self._build_ui()

    def _t(self, value: str) -> str:
        return EN.get(value, value) if self.ui_language == "en" else value

    def _message(self, value: str):
        self.activity.setText(value)

    def _build_ui(self):
        self.language_toggles = []
        self.text_buttons = []
        self.add_buttons = []
        self.editor_item = None
        self.block_items: list[QListWidgetItem] = []
        QApplication.instance().setStyleSheet(THEME)
        self.screens = QStackedWidget()
        self.screens.addWidget(self._start_screen())
        self.screens.addWidget(self._workspace())
        self.setCentralWidget(self.screens)
        self._set_mode(self.mode)
        self._fit_bar(self.width())
        if self.screen_name == "start":
            self._show_start()
        else:
            self.screens.setCurrentIndex(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_bar(self.width())

    def _fit_bar(self, width: int):
        for button in self.text_buttons:
            button.setText("" if width < 920 else self._t(button.property("label")))
        # The four comic sources shorten their labels before falling back to icons only.
        for button in self.add_buttons:
            label = button.property("label") if width >= 1080 else button.property("short") if width >= 920 else ""
            button.setText(self._t(label) if label else "")

    def _fit_hero(self, width: int):
        self.hero_title.setStyleSheet(f"font-size: {60 if width >= 1100 else 50 if width >= 860 else 40}px;")

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
        self.mode = mode
        self.mode_stack.setCurrentIndex(0 if mode == "pdf" else 1)
        self.tab_buttons[mode].setChecked(True)
        self.pdf_import_button.setVisible(mode == "pdf")
        self.manga_add_group.setVisible(mode == "manga")
        self._refresh_status()

    def _refresh_status(self):
        en = self.ui_language == "en"
        if self.mode == "pdf":
            ready = bool(self.pdf and self.pdf.blocks)
            summary = (f"{self.pdf.source.name} · {len(self.pdf.page_roles)} {'pages' if en else 'páginas'}") if self.pdf else ""
        else:
            ready = bool(self.manga.pages)
            chapters = len([p for p in self.manga.pages if str(p) in self.manga.chapter_titles])
            summary = (f"{len(self.manga.pages)} {'pages' if en else 'páginas'} · {chapters} {'chapters' if en else 'capítulos'}") if ready else ""
        self.export_button.setEnabled(ready)
        self.summary.setText(summary)

    def _export_current(self):
        self._export_pdf() if self.mode == "pdf" else self._export_manga()

    def _change_language(self, language: str):
        if language == self.ui_language:
            return
        pdf_meta = (self.pdf_title.text(), self.pdf_author.text(), self.pdf_language.text())
        manga_meta = (self.manga_title.text(), self.manga_author.text(), self.manga_language.text(), self.manga_rtl.isChecked())
        self._save_pdf_edit(quiet=True)
        block = self.selected_block
        manga_row = self.manga_list.currentRow()
        self.ui_language = language
        self.settings.setValue("ui_language", language)
        self._build_ui()
        self.pdf_title.setText(pdf_meta[0]); self.pdf_author.setText(pdf_meta[1]); self.pdf_language.setText(pdf_meta[2])
        self.manga_title.setText(manga_meta[0]); self.manga_author.setText(manga_meta[1]); self.manga_language.setText(manga_meta[2]); self.manga_rtl.setChecked(manga_meta[3])
        if self.pdf:
            self.pdf_warning.setText(" ".join(translate_engine_message(w, self.ui_language) for w in self.pdf.warnings) or ("Analysis complete. Review the structure before exporting." if self.ui_language == "en" else "Análise concluída. Revise a estrutura antes de exportar."))
            self._populate_pdf(block)
        self._refresh_manga_list()
        if manga_row >= 0:
            self.manga_list.setCurrentRow(manga_row)
        self._update_reading_direction()
        self._message(self._t("Pronto para começar"))

    def _start(self, label: str, function, done, *args):
        self._message(self._t(label))
        self.ribbon.start()
        for toggle in self.language_toggles:
            toggle.setEnabled(False)
        task = TaskThread(function, *args)
        self.tasks.append(task)
        task.succeeded.connect(done)
        task.failed.connect(self._error)
        task.finished.connect(lambda: self._task_finished(task))
        task.start()

    def _task_finished(self, task):
        if task in self.tasks:
            self.tasks.remove(task)
        if not self.tasks:
            self.ribbon.stop()
            for toggle in self.language_toggles:
                toggle.setEnabled(True)

    def _error(self, message: str):
        message = translate_engine_message(message, self.ui_language)
        self._message(("Error: " if self.ui_language == "en" else "Falha: ") + message)
        QMessageBox.critical(self, APP_NAME, message)

    def dragEnterEvent(self, event):
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        images = []
        for path in paths:
            images.extend(_images_in(path) if path.is_dir() else [path] if path.suffix.lower() in IMAGE_EXTENSIONS else [])
        pdfs = [path for path in paths if path.suffix.lower() == ".pdf"]
        if images:
            self._show_workspace("manga")
            self._append_manga_pages(images)
        elif pdfs and self.screen_name == "workspace" and self.mode == "manga":
            self._add_comic_pdf(pdfs[0])
        elif pdfs:
            self._analyze_pdf(str(pdfs[0]))
        else:
            return
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
            while len(books) < 8:
                books = books + books[:8 - len(books)]
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
        self._message((f"EPUB saved to {path}" if self.ui_language == "en" else f"EPUB salvo em {path}"))
        self._record_recent(kind, path)

    def _open_recent(self, path: str):
        folder = Path(path).parent
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            self._error("The folder for this EPUB no longer exists." if self.ui_language == "en" else "A pasta deste EPUB não existe mais.")

    def _open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, self._t("Escolher PDF"), "", "PDF (*.pdf)")
        if path:
            self._analyze_pdf(path)

    def _analyze_pdf(self, path: str):
        self._show_workspace("pdf")
        self._start("Analisando PDF...", analyze_pdf, self._pdf_loaded, path)

    def _pdf_loaded(self, project: PdfProject):
        self.pdf = project
        self.selected_block = -1
        self.pdf_title.setText(project.title)
        self.pdf_author.setText(project.author)
        self.pdf_language.setText(project.language)
        self.pdf_warning.setText(" ".join(translate_engine_message(w, self.ui_language) for w in project.warnings) or ("Analysis complete. Review the structure before exporting." if self.ui_language == "en" else "Análise concluída. Revise a estrutura antes de exportar."))
        self._populate_pdf()
        self._message((f"PDF analyzed: {len(project.page_roles)} pages, {len(project.blocks)} blocks." if self.ui_language == "en" else f"PDF analisado: {len(project.page_roles)} páginas, {len(project.blocks)} blocos."))

    def _populate_pdf(self, selected: int = 0):
        project = self.pdf
        if not project:
            return
        self.selected_block = -1
        self.pdf_stack.setCurrentIndex(1 if project.blocks else 0)
        self.block_list.blockSignals(True)
        self.block_list.clear()
        self.editor_item = None
        self.block_items = []
        for row in range(len(project.blocks)):
            item = QListWidgetItem()
            self.block_list.addItem(item)
            self.block_items.append(item)
            self._update_block_row(row)
        self.block_list.blockSignals(False)
        self._apply_block_filter()
        chapters = sum(block.role == "Capítulo" for block in project.blocks)
        self.pdf_count.setText(f"{chapters} chapters · {len(project.blocks)} blocks" if self.ui_language == "en" else f"{chapters} capítulos · {len(project.blocks)} blocos")
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
        item.setText(block.text[:200] if block.text else ("[image]" if self.ui_language == "en" else "[imagem]"))
        item.setData(BLOCK_INDEX, row)
        item.setData(BLOCK_ROLE, block.role)
        item.setData(BLOCK_PAGE, block.page + 1)
        item.setData(BLOCK_LABEL, self._t(TYPE_LABELS[block.role]) if block.role in TYPE_LABELS else "")

    def _filter_blocks(self, key: str):
        self.block_filter = key
        self._apply_block_filter()

    def _apply_block_filter(self):
        if not self.pdf:
            return
        for row, item in enumerate(self.block_items):
            item.setHidden(self.block_filter != "all" and self.pdf.blocks[row].role != self.block_filter)
        if self.editor_item is not None and 0 <= self.selected_block < len(self.block_items):
            self.editor_item.setHidden(self.block_items[self.selected_block].isHidden())

    def _select_pdf_item(self, current, _previous):
        if not self.pdf or current is None or current.data(BLOCK_INDEX) is None:
            return
        self._save_pdf_edit(quiet=True)
        index = current.data(BLOCK_INDEX)
        block = self.pdf.blocks[index]
        self.selected_block = index
        self._place_editor(current, block)
        image = QPixmap()
        image.loadFromData(render_page(self.pdf.source, block.page, width=1200))
        self.pdf_page_image.set_image(image)
        self.pdf_preview.scrollToAnchor(f"b{index}")

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

    def _save_pdf_edit(self, quiet: bool = False):
        if not self.pdf or self.selected_block < 0 or self.editor_item is None:
            return
        block = self.pdf.blocks[self.selected_block]
        block.role = self.block_role.currentData()
        block.text = self.block_text.toPlainText().strip()
        self._update_block_row(self.selected_block)
        self._refresh_pdf_preview()
        if not quiet:
            self._message("Edit saved in the current project." if self.ui_language == "en" else "Correção salva no projeto atual.")

    def _move_block(self, step: int):
        if not self.pdf or self.selected_block < 0:
            return
        self._save_pdf_edit(quiet=True)
        row = self.selected_block
        target = row + step
        if not 0 <= target < len(self.pdf.blocks):
            return
        if self.pdf.blocks[row].page != self.pdf.blocks[target].page:
            self._message("Move blocks within the same page." if self.ui_language == "en" else "Reordene blocos dentro da mesma página.")
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
                caption = f"Image on page {block.page + 1}" if self.ui_language == "en" else f"Imagem da página {block.page + 1}"
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
            self._error("Import a PDF first." if self.ui_language == "en" else "Importe um PDF primeiro.")
            return
        path, _ = QFileDialog.getOpenFileName(self, self._t("Escolher imagem de capa"), "", self._t(IMAGE_FILTER))
        if path:
            self.pdf.custom_cover = Path(path)
            self._refresh_pdf_cover()

    def _remove_pdf_cover(self):
        if self.pdf:
            self.pdf.custom_cover = None
            self._refresh_pdf_cover()

    def _export_pdf(self):
        if not self.pdf:
            self._error("Import a PDF first." if self.ui_language == "en" else "Importe um PDF primeiro.")
            return
        self._save_pdf_edit()
        self.pdf.title = self.pdf_title.text().strip()
        self.pdf.author = self.pdf_author.text().strip()
        self.pdf.language = self.pdf_language.text().strip()
        if len(self.pdf.scanned_pages) - len(self.pdf.ocr_pages) > len(self.pdf.page_roles) / 2:
            self._error("This PDF appears scanned and OCR did not recover enough text. Review the pages before exporting." if self.ui_language == "en" else "Este PDF parece escaneado e o OCR não recuperou texto suficiente. Confira as páginas antes de exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(self, self._t("Salvar EPUB"), self.pdf.source.with_suffix(".epub").name, "EPUB (*.epub)")
        if path:
            self._start("Gerando EPUB...", export_pdf, lambda _: self._export_done("pdf", path), self.pdf, path)

    def _load_page_pixmap(self, path: str) -> QPixmap:
        return _read_oriented_pixmap(Path(path))

    def _append_manga_pages(self, paths: list[Path]):
        existing = set(self.manga.pages)
        self.manga.pages.extend(p for p in paths if p not in existing and p.is_file())
        self._refresh_manga_list()
        self._message((f"{len(self.manga.pages)} comic pages." if self.ui_language == "en" else f"{len(self.manga.pages)} páginas na HQ."))

    def _refresh_manga_list(self):
        current = self.manga_list.currentRow()
        pages = self.manga.pages
        self.manga_stack.setCurrentIndex(1 if pages else 0)
        self.manga_list.blockSignals(True)
        self.manga_list.clear()
        for index, path in enumerate(pages):
            item = QListWidgetItem(f"{index + 1:03d}")
            item.setData(PAGE_PATH, str(path))
            item.setData(PAGE_COVER, index == self.manga.cover_index and not self.manga.custom_cover)
            item.setData(PAGE_CHAPTER, self.manga.chapter_titles.get(str(path), ""))
            item.setToolTip(path.name)
            self.manga_list.addItem(item)
        self.manga_list.blockSignals(False)
        self.manga_cover_combo.blockSignals(True)
        self.manga_cover_combo.clear()
        for index, path in enumerate(pages):
            self.manga_cover_combo.addItem(f"{self._t('Página')} {index + 1} · {path.name}", index)
        if not pages:
            self.manga_cover_combo.addItem(self._t("Adicione páginas para escolher a capa"))
        self.manga_cover_combo.setCurrentIndex(self.manga.cover_index if pages else 0)
        self.manga_cover_combo.blockSignals(False)
        self.manga_cover_combo.setEnabled(bool(pages))
        chapters = len([p for p in pages if str(p) in self.manga.chapter_titles])
        self.manga_count.setText(f"{len(pages)} pages · {chapters} chapters" if self.ui_language == "en" else f"{len(pages)} páginas · {chapters} capítulos")
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
            self._append_manga_pages(_images_in(Path(path)))

    def _add_comic_pdf(self, source: Path | None = None):
        if source is None:
            path, _ = QFileDialog.getOpenFileName(self, self._t("Escolher PDF de HQ"), "", "PDF (*.pdf)")
            if not path:
                return
            source = Path(path)
        temp = tempfile.TemporaryDirectory(prefix="conversor-epub-pdf-hq-")
        self.temp_downloads.append(temp)
        self._show_workspace("manga")
        self._start("Convertendo páginas do PDF...", import_comic_pdf,
                    lambda pages: self._comic_pdf_loaded(pages, source), source, temp.name)

    def _comic_pdf_loaded(self, paths: list[Path], source: Path):
        if not self.manga_title.text().strip():
            self.manga_title.setText(source.stem)
        self._append_manga_pages(paths)

    def _add_url(self):
        url, ok = QInputDialog.getText(self, self._t("Importar imagens"), self._t("URL de uma imagem ou galeria pública:"))
        if not ok or not url.strip():
            return
        temp = tempfile.TemporaryDirectory(prefix="conversor-epub-hq-")
        self.temp_downloads.append(temp)
        self._start("Baixando imagens da página...", import_images_from_url, self._url_imported, url.strip(), temp.name)

    def _url_imported(self, paths: list[Path]):
        if not paths:
            self._error("No page images found. Save the images and use 'Add folder'." if self.ui_language == "en" else "Nenhuma imagem de página foi encontrada. Tente salvar as imagens e usar 'Adicionar pasta'.")
            return
        self._append_manga_pages(paths)

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

    def _remove_page(self):
        row = self.manga_list.currentRow()
        if 0 <= row < len(self.manga.pages):
            removed = self.manga.pages.pop(row)
            self.manga.chapter_titles.pop(str(removed), None)
            if self.manga.cover_index > row:
                self.manga.cover_index -= 1
            self.manga.cover_index = min(self.manga.cover_index, max(0, len(self.manga.pages) - 1))
            self._refresh_manga_list()

    def _use_page_as_cover(self):
        row = self.manga_list.currentRow()
        if 0 <= row < len(self.manga.pages):
            self.manga.cover_index = row
            self.manga.custom_cover = None
            self._refresh_manga_list()
            self.manga_list.setCurrentRow(row)

    def _manga_cover_changed(self):
        if self.manga_cover_combo.currentIndex() >= 0 and self.manga.pages:
            self.manga.cover_index = self.manga_cover_combo.currentData()
            self.manga.custom_cover = None
            self._refresh_manga_list()

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

    def _remove_manga_cover(self):
        self.manga.custom_cover = None
        self._refresh_manga_list()

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

    def _export_manga(self):
        if not self.manga.pages:
            self._error("Add images first." if self.ui_language == "en" else "Adicione imagens primeiro.")
            return
        self.manga.title = self.manga_title.text().strip() or self.manga.pages[0].parent.name
        self.manga.author = self.manga_author.text().strip()
        self.manga.language = self.manga_language.text().strip()
        self.manga.right_to_left = self.manga_rtl.isChecked()
        path, _ = QFileDialog.getSaveFileName(self, self._t("Salvar EPUB"), f"{self.manga.title}.epub", "EPUB (*.epub)")
        if path:
            self._start("Gerando EPUB de HQ...", export_manga, lambda _: self._export_done("manga", path), self.manga, path)


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    load_fonts()
    app.setWindowIcon(QIcon(app_icon(256)))
    window = MainWindow()
    window.show()
    app.exec()
