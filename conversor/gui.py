# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import html
import re
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, QThread, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QMainWindow, QMessageBox, QTabWidget, QTableWidgetItem, QVBoxLayout,
    QSizePolicy, QWidget, QProgressBar,
)

from .epub_export import export_manga, export_pdf
from .comic_pdf import import_comic_pdf
from .models import MangaProject, PdfProject
from .pdf_analysis import analyze_pdf, render_page
from .web_images import import_images_from_url
from .i18n import EN, translate_engine_message
from .appearance import THEME, line_icon, CleanComboBox as QComboBox
from .ui_layout import WorkspaceLayout


IMAGE_FILTER = "Imagens (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"

def _natural_key(path: Path) -> list[int | str]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(path))]


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


class FitImage(QLabel):
    def __init__(self, placeholder: str):
        super().__init__(placeholder)
        self.placeholder = placeholder
        self.original = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(160, 140)

    def set_image(self, image: QPixmap):
        self.original = image
        if image.isNull():
            self.setText(self.placeholder)
            return
        self.setText("")
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        if not self.original.isNull():
            size = QSize(max(1, self.width() - 16), max(1, self.height() - 16))
            self.setPixmap(self.original.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))


class MainWindow(WorkspaceLayout, QMainWindow):
    def __init__(self):
        super().__init__()
        saved_language = QSettings("ConversorEPUB", "ConversorEPUB").value("ui_language", "pt")
        self.ui_language = saved_language if saved_language in ("pt", "en") else "pt"
        self.setWindowTitle("Conversor EPUB")
        self.resize(1280, 820)
        self.pdf: PdfProject | None = None
        self.manga = MangaProject()
        self.selected_block = -1
        self.tasks: list[TaskThread] = []
        self.temp_downloads: list[tempfile.TemporaryDirectory] = []
        self._build_ui()

    def _t(self, value: str) -> str:
        return EN.get(value, value) if self.ui_language == "en" else value

    def _message(self, value: str):
        self.activity.setText(value)
        self.statusBar().showMessage(value)

    def _build_ui(self):
        shell = QWidget()
        shell.setObjectName("shell")
        outer = QVBoxLayout(shell)
        outer.setContentsMargins(22, 16, 22, 16)
        outer.setSpacing(12)
        top = QHBoxLayout()
        title = QLabel(self._t("Conversor EPUB"))
        title.setObjectName("brand")
        symbol = QLabel()
        symbol.setPixmap(line_icon("book", "#335fd1", 32).pixmap(32, 32))
        top.addWidget(symbol)
        brand = QVBoxLayout()
        brand.setSpacing(2)
        brand.addWidget(title)
        brand.addWidget(self._label("Sua biblioteca, do seu jeito.", "subtitle"))
        top.addLayout(brand)
        top.addStretch()
        top.addWidget(QLabel(self._t("Idioma da interface")))
        self.ui_combo = QComboBox()
        self.ui_combo.setFixedSize(120, 36)
        self.ui_combo.addItem("Português", "pt")
        self.ui_combo.addItem("English", "en")
        self.ui_combo.setCurrentIndex(0 if self.ui_language == "pt" else 1)
        self.ui_combo.currentIndexChanged.connect(self._change_language)
        top.addWidget(self.ui_combo)
        outer.addLayout(top)
        self.activity = QLabel(self._t("Importe um PDF ou páginas de HQ para começar."))
        self.activity.setObjectName("activity")
        self.activity.setWordWrap(True)
        outer.addWidget(self.activity)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._pdf_tab(), self._t("Livro em PDF"))
        self.tabs.addTab(self._manga_tab(), self._t("Mangá / HQ"))
        outer.addWidget(self.tabs, 1)
        self.setCentralWidget(shell)
        self.setStyleSheet(THEME)
        self.setWindowTitle(self._t("Conversor EPUB"))
        self.statusBar().hide()

    def _change_language(self):
        language = self.ui_combo.currentData()
        if language == self.ui_language:
            return
        pdf_meta = (self.pdf_title.text(), self.pdf_author.text(), self.pdf_language.text())
        manga_meta = (self.manga_title.text(), self.manga_author.text(), self.manga_language.text(), self.manga_rtl.isChecked())
        self._save_pdf_edit(quiet=True)
        tab = self.tabs.currentIndex()
        block = self.selected_block
        manga_row = self.manga_list.currentRow()
        self.ui_language = language
        QSettings("ConversorEPUB", "ConversorEPUB").setValue("ui_language", language)
        self._build_ui()
        self.pdf_title.setText(pdf_meta[0]); self.pdf_author.setText(pdf_meta[1]); self.pdf_language.setText(pdf_meta[2])
        self.manga_title.setText(manga_meta[0]); self.manga_author.setText(manga_meta[1]); self.manga_language.setText(manga_meta[2]); self.manga_rtl.setChecked(manga_meta[3])
        if self.pdf:
            self.pdf_warning.setText(" ".join(translate_engine_message(w, self.ui_language) for w in self.pdf.warnings) or ("Analysis complete. Review the structure before exporting." if self.ui_language == "en" else "Análise concluída. Revise a estrutura antes de exportar."))
            self._populate_pdf(block)
        self._refresh_manga_list()
        if manga_row >= 0:
            self.manga_list.setCurrentRow(manga_row)
        self.tabs.setCurrentIndex(tab)
        self._message(self._t("Pronto para começar"))

    def _new_preview(self, text):
        preview = FitImage(self._t(text))
        preview.setObjectName("canvas")
        preview.setWordWrap(True)
        preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        return preview

    def _start(self, label: str, function, done, *args):
        self._message(self._t(label))
        self.progress.show()
        self.ui_combo.setEnabled(False)
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
            self.progress.hide()
            self.ui_combo.setEnabled(True)

    def _error(self, message: str):
        message = translate_engine_message(message, self.ui_language)
        self._message(("Error: " if self.ui_language == "en" else "Falha: ") + message)
        QMessageBox.critical(self, self._t("Conversor EPUB"), message)

    def _open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, self._t("Escolher PDF"), "", "PDF (*.pdf)")
        if path:
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
        self.block_table.blockSignals(True)
        self.block_table.setRowCount(len(project.blocks))
        self.block_stack.setCurrentIndex(1 if project.blocks else 0)
        self.pdf_editor.setEnabled(bool(project.blocks))
        self.pdf_export_button.setEnabled(bool(project.blocks))
        for row in range(len(project.blocks)):
            self._update_block_row(row)
        self.block_table.blockSignals(False)
        self.pdf_cover_combo.blockSignals(True)
        self.pdf_cover_combo.clear()
        for page in range(len(project.page_roles)):
            self.pdf_cover_combo.addItem(f"{self._t('Página')} {page + 1} · {self._t(project.page_roles[page])}", page)
        self.pdf_cover_combo.setCurrentIndex(project.cover_page)
        self.pdf_cover_combo.blockSignals(False)
        self.pdf_cover_combo.setEnabled(True)
        self._refresh_pdf_cover()
        self._refresh_pdf_preview()
        if project.blocks:
            self.block_table.setCurrentCell(min(max(selected, 0), len(project.blocks) - 1), 0)

    def _update_block_row(self, row: int):
        if not self.pdf:
            return
        block = self.pdf.blocks[row]
        summary = block.text[:130] if block.text else ("[image]" if self.ui_language == "en" else "[imagem]")
        for col, value in enumerate((str(block.page + 1), self._t(block.role), summary)):
            self.block_table.setItem(row, col, QTableWidgetItem(value))

    def _select_pdf_block(self, row: int, _col: int, _old_row: int, _old_col: int):
        if not self.pdf or row < 0 or row >= len(self.pdf.blocks):
            return
        self._save_pdf_edit(quiet=True)
        block = self.pdf.blocks[row]
        self.selected_block = row
        self.page_role.blockSignals(True)
        self.block_role.blockSignals(True)
        self.page_role.setCurrentIndex(self.page_role.findData(self.pdf.page_roles[block.page]))
        self.block_role.setCurrentIndex(self.block_role.findData(block.role))
        self.page_role.blockSignals(False)
        self.block_role.blockSignals(False)
        self.block_text.setPlainText(block.text)
        image = QPixmap()
        image.loadFromData(render_page(self.pdf.source, block.page, width=1200))
        self.pdf_page_image.set_image(image)

    def _page_role_changed(self, value: str):
        if self.pdf and self.selected_block >= 0:
            page = self.pdf.blocks[self.selected_block].page
            self.pdf.page_roles[page] = self.page_role.currentData()
            self.pdf_cover_combo.setItemText(page, f"{self._t('Página')} {page + 1} · {self._t(self.pdf.page_roles[page])}")

    def _save_pdf_edit(self, quiet: bool = False):
        if not self.pdf or self.selected_block < 0:
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
        self._update_block_row(row)
        self._update_block_row(target)
        self.selected_block = -1
        self.block_table.setCurrentCell(target, 0)
        self._refresh_pdf_preview()

    def _refresh_pdf_preview(self):
        if not self.pdf:
            return
        parts = ["<html><body style='font-family:serif;line-height:1.5;margin:2em'>"]
        for block in self.pdf.blocks:
            if block.role == "Ignorar":
                continue
            if block.role == "Imagem":
                caption = f"Image on page {block.page + 1}" if self.ui_language == "en" else f"Imagem da página {block.page + 1}"
                parts.append(f"<p><i>[{caption}]</i></p>")
                continue
            tag = {"Capítulo": "h1", "Seção": "h2", "Nota": "small"}.get(block.role, "p")
            text = block.rich_html if block.rich_html and block.text == block.source_text else html.escape(block.text)
            parts.append(f"<{tag}>{text}</{tag}>")
        parts.append("</body></html>")
        self.pdf_preview.setHtml("".join(parts))

    def _pdf_cover_changed(self):
        if self.pdf and self.pdf_cover_combo.currentIndex() >= 0:
            self.pdf.cover_page = self.pdf_cover_combo.currentData()
            self.pdf.custom_cover = None
            self._refresh_pdf_cover()

    def _refresh_pdf_cover(self):
        if not self.pdf:
            self.pdf_cover_image.clear()
            return
        if self.pdf.custom_cover:
            pixmap = QPixmap(str(self.pdf.custom_cover))
            self.pdf_cover_info.setText(f"{self._t('Capa customizada')}: {self.pdf.custom_cover.name}")
        else:
            pixmap = QPixmap()
            pixmap.loadFromData(render_page(self.pdf.source, self.pdf.cover_page, width=240))
            self.pdf_cover_info.setText(f"{self._t('Página')} {self.pdf.cover_page + 1} · {self._t(self.pdf.page_roles[self.pdf.cover_page])}")
        self.pdf_cover_image.setPixmap(pixmap.scaled(74, 104, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
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
            self._start("Gerando EPUB...", export_pdf, lambda _: self._message((f"EPUB saved to {path}" if self.ui_language == "en" else f"EPUB salvo em {path}")), self.pdf, path)

    def _append_manga_pages(self, paths: list[Path]):
        existing = set(self.manga.pages)
        self.manga.pages.extend(p for p in paths if p not in existing and p.is_file())
        self._refresh_manga_list()
        self._message((f"{len(self.manga.pages)} comic pages." if self.ui_language == "en" else f"{len(self.manga.pages)} páginas na HQ."))

    def _refresh_manga_list(self):
        current = self.manga_list.currentRow()
        self.manga_stack.setCurrentIndex(1 if self.manga.pages else 0)
        self.manga_export_button.setEnabled(bool(self.manga.pages))
        self.manga_list.clear()
        for index, path in enumerate(self.manga.pages):
            marker = "★ " if index == self.manga.cover_index and not self.manga.custom_cover else ""
            chapter = self.manga.chapter_titles.get(str(path))
            chapter_marker = f"  •  {chapter}" if chapter else ""
            self.manga_list.addItem(f"{marker}{index + 1:03d} — {path.name}{chapter_marker}")
        self.manga_cover_combo.blockSignals(True)
        self.manga_cover_combo.clear()
        for index, path in enumerate(self.manga.pages):
            self.manga_cover_combo.addItem(f"{self._t('Página')} {index + 1} · {path.name}", index)
        if not self.manga.pages:
            self.manga_cover_combo.addItem(self._t("Adicione páginas para escolher a capa"))
        self.manga_cover_combo.setCurrentIndex(self.manga.cover_index if self.manga.pages else 0)
        self.manga_cover_combo.blockSignals(False)
        self.manga_cover_combo.setEnabled(bool(self.manga.pages))
        if self.manga.pages:
            self.manga_list.setCurrentRow(min(max(current, 0), len(self.manga.pages) - 1))
        self._refresh_manga_cover()

    def _add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self._t("Escolher imagens"), "", self._t(IMAGE_FILTER))
        if paths:
            self._append_manga_pages(sorted((Path(p) for p in paths), key=_natural_key))

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, self._t("Escolher pasta de imagens"))
        if path:
            extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
            pages = sorted((p for p in Path(path).rglob("*") if p.suffix.lower() in extensions), key=_natural_key)
            self._append_manga_pages(pages)

    def _add_comic_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, self._t("Escolher PDF de HQ"), "", "PDF (*.pdf)")
        if not path:
            return
        source = Path(path)
        temp = tempfile.TemporaryDirectory(prefix="conversor-epub-pdf-hq-")
        self.temp_downloads.append(temp)
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
        if 0 <= row < len(self.manga.pages):
            image = QPixmap(str(self.manga.pages[row]))
            self.manga_image.set_image(image)
        else:
            self.manga_image.set_image(QPixmap())

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

    def _manga_cover_changed(self):
        if self.manga_cover_combo.currentIndex() >= 0 and self.manga.pages:
            self.manga.cover_index = self.manga_cover_combo.currentData()
            self.manga.custom_cover = None
            self._refresh_manga_list()

    def _refresh_manga_cover(self):
        source = self.manga.custom_cover
        if source:
            self.manga_cover_info.setText(f"{self._t('Capa customizada')}: {source.name}")
        elif self.manga.pages:
            source = self.manga.pages[self.manga.cover_index]
            self.manga_cover_info.setText(f"{self._t('Página')} {self.manga.cover_index + 1} · {source.name}")
        else:
            self.manga_cover_info.setText(self._t("Escolha uma página ou adicione uma imagem."))
        if source:
            pixmap = QPixmap(str(source))
            self.manga_cover_image.setPixmap(pixmap.scaled(74, 104, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.manga_cover_image.clear()
        self.manga_clear_cover.setEnabled(self.manga.custom_cover is not None)

    def _add_manga_cover(self):
        path, _ = QFileDialog.getOpenFileName(self, self._t("Escolher imagem de capa"), "", self._t(IMAGE_FILTER))
        if path:
            self.manga.custom_cover = Path(path)
            self._refresh_manga_cover()

    def _remove_manga_cover(self):
        self.manga.custom_cover = None
        self._refresh_manga_cover()

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
            self._start("Gerando EPUB de HQ...", export_manga, lambda _: self._message((f"EPUB saved to {path}" if self.ui_language == "en" else f"EPUB salvo em {path}")), self.manga, path)


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    icon = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    app.exec()
