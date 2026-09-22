from __future__ import annotations

import html
import re
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QSizePolicy,
    QWidget,
)

from .epub_export import export_manga, export_pdf
from .models import BLOCK_ROLES, PAGE_ROLES, MangaProject, PdfProject
from .pdf_analysis import analyze_pdf, render_page
from .web_images import import_images_from_url


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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Conversor EPUB")
        self.resize(1280, 820)
        self.pdf: PdfProject | None = None
        self.manga = MangaProject()
        self.selected_block = -1
        self.tasks: list[TaskThread] = []
        self.temp_downloads: list[tempfile.TemporaryDirectory] = []
        tabs = QTabWidget()
        tabs.addTab(self._pdf_tab(), "Livro em PDF")
        tabs.addTab(self._manga_tab(), "Mangá / HQ")
        self.setCentralWidget(tabs)
        self.statusBar().showMessage("Importe um PDF ou páginas de HQ para começar.")

    def _button(self, label: str, callback) -> QPushButton:
        button = QPushButton(label)
        button.clicked.connect(callback)
        return button

    def _pdf_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        actions = QHBoxLayout()
        actions.addWidget(self._button("Importar PDF", self._open_pdf))
        actions.addWidget(self._button("Definir página como capa", self._set_pdf_cover))
        actions.addWidget(self._button("Exportar EPUB", self._export_pdf))
        actions.addStretch()
        layout.addLayout(actions)

        metadata = QGroupBox("Dados do livro")
        metadata.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        form = QFormLayout(metadata)
        self.pdf_title = QLineEdit()
        self.pdf_author = QLineEdit()
        self.pdf_language = QLineEdit("pt-BR")
        form.addRow("Título", self.pdf_title)
        form.addRow("Autor", self.pdf_author)
        form.addRow("Idioma", self.pdf_language)
        layout.addWidget(metadata)

        self.pdf_warning = QLabel("A análise sugere a estrutura; revise os títulos e a ordem dos blocos.")
        self.pdf_warning.setWordWrap(True)
        self.pdf_warning.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(self.pdf_warning)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Blocos encontrados (selecione para corrigir)"))
        self.block_table = QTableWidget(0, 3)
        self.block_table.setHorizontalHeaderLabels(["Página", "Tipo", "Conteúdo"])
        self.block_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.block_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.block_table.verticalHeader().setVisible(False)
        self.block_table.setColumnWidth(0, 75)
        self.block_table.setColumnWidth(1, 105)
        self.block_table.horizontalHeader().setStretchLastSection(True)
        self.block_table.currentCellChanged.connect(self._select_pdf_block)
        left_layout.addWidget(self.block_table)
        block_actions = QHBoxLayout()
        block_actions.addWidget(self._button("↑ Bloco", lambda: self._move_block(-1)))
        block_actions.addWidget(self._button("↓ Bloco", lambda: self._move_block(1)))
        left_layout.addLayout(block_actions)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        edit_row = QHBoxLayout()
        self.page_role = QComboBox()
        self.page_role.addItems(PAGE_ROLES)
        self.page_role.currentTextChanged.connect(self._page_role_changed)
        self.block_role = QComboBox()
        self.block_role.addItems(BLOCK_ROLES)
        edit_row.addWidget(QLabel("Página:"))
        edit_row.addWidget(self.page_role)
        edit_row.addWidget(QLabel("Bloco:"))
        edit_row.addWidget(self.block_role)
        right_layout.addLayout(edit_row)
        self.block_text = QPlainTextEdit()
        self.block_text.setPlaceholderText("Texto do bloco selecionado")
        self.block_text.setMaximumHeight(100)
        right_layout.addWidget(self.block_text)
        right_layout.addWidget(self._button("Salvar correção e atualizar prévia", self._save_pdf_edit))

        preview_tabs = QTabWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.pdf_page_image = QLabel("Selecione um bloco para ver a página original.")
        self.pdf_page_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self.pdf_page_image)
        preview_tabs.addTab(scroll, "PDF original")
        self.pdf_preview = QTextBrowser()
        preview_tabs.addTab(self.pdf_preview, "Prévia do texto")
        right_layout.addWidget(preview_tabs)
        splitter.addWidget(right)
        splitter.setSizes([550, 730])
        layout.addWidget(splitter)
        return root

    def _manga_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        actions = QHBoxLayout()
        actions.addWidget(self._button("Adicionar imagens", self._add_images))
        actions.addWidget(self._button("Adicionar pasta", self._add_folder))
        actions.addWidget(self._button("Importar URL", self._add_url))
        actions.addStretch()
        layout.addLayout(actions)
        metadata = QGroupBox("Dados da HQ")
        metadata.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        form = QFormLayout(metadata)
        self.manga_title = QLineEdit()
        self.manga_author = QLineEdit()
        self.manga_language = QLineEdit("pt-BR")
        self.manga_rtl = QCheckBox("Leitura da direita para a esquerda")
        self.manga_rtl.setChecked(True)
        form.addRow("Título", self.manga_title)
        form.addRow("Autor", self.manga_author)
        form.addRow("Idioma", self.manga_language)
        form.addRow("Direção", self.manga_rtl)
        layout.addWidget(metadata)
        layout.addWidget(QLabel("Revise a ordem das páginas. URLs importam imagens visíveis de uma página pública; sites dinâmicos podem exigir arquivos locais."))
        manga_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.manga_list = QListWidget()
        self.manga_list.currentRowChanged.connect(self._show_manga_page)
        manga_splitter.addWidget(self.manga_list)
        self.manga_image = QLabel("Selecione uma página para conferir.")
        self.manga_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.manga_image)
        manga_splitter.addWidget(scroll)
        manga_splitter.setSizes([350, 850])
        layout.addWidget(manga_splitter)
        page_actions = QHBoxLayout()
        page_actions.addWidget(self._button("↑ Subir", lambda: self._move_page(-1)))
        page_actions.addWidget(self._button("↓ Descer", lambda: self._move_page(1)))
        page_actions.addWidget(self._button("Remover", self._remove_page))
        page_actions.addWidget(self._button("Usar como capa", self._set_manga_cover))
        page_actions.addWidget(self._button("Início de capítulo", self._set_manga_chapter))
        page_actions.addStretch()
        page_actions.addWidget(self._button("Exportar EPUB", self._export_manga))
        layout.addLayout(page_actions)
        return root

    def _start(self, label: str, function, done, *args):
        self.statusBar().showMessage(label)
        task = TaskThread(function, *args)
        self.tasks.append(task)
        task.succeeded.connect(done)
        task.failed.connect(self._error)
        task.finished.connect(lambda: self.tasks.remove(task) if task in self.tasks else None)
        task.start()

    def _error(self, message: str):
        self.statusBar().showMessage("Falha: " + message)
        QMessageBox.critical(self, "Conversor EPUB", message)

    def _open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Escolher PDF", "", "PDF (*.pdf)")
        if path:
            self._start("Analisando PDF...", analyze_pdf, self._pdf_loaded, path)

    def _pdf_loaded(self, project: PdfProject):
        self.pdf = project
        self.selected_block = -1
        self.pdf_title.setText(project.title)
        self.pdf_author.setText(project.author)
        self.pdf_language.setText(project.language)
        self.pdf_warning.setText(" ".join(project.warnings) or "Análise concluída. Revise a estrutura antes de exportar.")
        self.block_table.blockSignals(True)
        self.block_table.setRowCount(len(project.blocks))
        for row in range(len(project.blocks)):
            self._update_block_row(row)
        self.block_table.blockSignals(False)
        self._refresh_pdf_preview()
        if project.blocks:
            self.block_table.setCurrentCell(0, 0)
        self.statusBar().showMessage(f"PDF analisado: {len(project.page_roles)} páginas, {len(project.blocks)} blocos.")

    def _update_block_row(self, row: int):
        if not self.pdf:
            return
        block = self.pdf.blocks[row]
        summary = block.text[:130] if block.text else "[imagem]"
        for col, value in enumerate((str(block.page + 1), block.role, summary)):
            self.block_table.setItem(row, col, QTableWidgetItem(value))

    def _select_pdf_block(self, row: int, _col: int, _old_row: int, _old_col: int):
        if not self.pdf or row < 0 or row >= len(self.pdf.blocks):
            return
        self._save_pdf_edit(quiet=True)
        block = self.pdf.blocks[row]
        self.selected_block = row
        self.page_role.blockSignals(True)
        self.block_role.blockSignals(True)
        self.page_role.setCurrentText(self.pdf.page_roles[block.page])
        self.block_role.setCurrentText(block.role)
        self.page_role.blockSignals(False)
        self.block_role.blockSignals(False)
        self.block_text.setPlainText(block.text)
        image = QPixmap()
        image.loadFromData(render_page(self.pdf.source, block.page))
        self.pdf_page_image.setPixmap(image)

    def _page_role_changed(self, value: str):
        if self.pdf and self.selected_block >= 0:
            page = self.pdf.blocks[self.selected_block].page
            self.pdf.page_roles[page] = value

    def _save_pdf_edit(self, quiet: bool = False):
        if not self.pdf or self.selected_block < 0:
            return
        block = self.pdf.blocks[self.selected_block]
        block.role = self.block_role.currentText()
        block.text = self.block_text.toPlainText().strip()
        self._update_block_row(self.selected_block)
        self._refresh_pdf_preview()
        if not quiet:
            self.statusBar().showMessage("Correção salva no projeto atual.")

    def _move_block(self, step: int):
        if not self.pdf or self.selected_block < 0:
            return
        self._save_pdf_edit(quiet=True)
        row = self.selected_block
        target = row + step
        if not 0 <= target < len(self.pdf.blocks):
            return
        if self.pdf.blocks[row].page != self.pdf.blocks[target].page:
            self.statusBar().showMessage("Reordene blocos dentro da mesma página.")
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
                parts.append(f"<p><i>[Imagem da página {block.page + 1}]</i></p>")
                continue
            tag = {"Capítulo": "h1", "Seção": "h2", "Nota": "small"}.get(block.role, "p")
            text = block.rich_html if block.rich_html and block.text == block.source_text else html.escape(block.text)
            parts.append(f"<{tag}>{text}</{tag}>")
        parts.append("</body></html>")
        self.pdf_preview.setHtml("".join(parts))

    def _set_pdf_cover(self):
        if self.pdf and self.selected_block >= 0:
            self.pdf.cover_page = self.pdf.blocks[self.selected_block].page
            self.statusBar().showMessage(f"Página {self.pdf.cover_page + 1} definida como capa.")

    def _export_pdf(self):
        if not self.pdf:
            self._error("Importe um PDF primeiro.")
            return
        self._save_pdf_edit()
        self.pdf.title = self.pdf_title.text().strip()
        self.pdf.author = self.pdf_author.text().strip()
        self.pdf.language = self.pdf_language.text().strip()
        if len(self.pdf.scanned_pages) - len(self.pdf.ocr_pages) > len(self.pdf.page_roles) / 2:
            self._error("Este PDF parece escaneado e o OCR não recuperou texto suficiente. Confira as páginas antes de exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar EPUB", self.pdf.source.with_suffix(".epub").name, "EPUB (*.epub)")
        if path:
            self._start("Gerando EPUB...", export_pdf, lambda _: self.statusBar().showMessage(f"EPUB salvo em {path}"), self.pdf, path)

    def _append_manga_pages(self, paths: list[Path]):
        existing = set(self.manga.pages)
        self.manga.pages.extend(p for p in paths if p not in existing and p.is_file())
        self._refresh_manga_list()
        self.statusBar().showMessage(f"{len(self.manga.pages)} páginas na HQ.")

    def _refresh_manga_list(self):
        current = self.manga_list.currentRow()
        self.manga_list.clear()
        for index, path in enumerate(self.manga.pages):
            marker = "★ " if index == self.manga.cover_index else ""
            chapter = self.manga.chapter_titles.get(str(path))
            chapter_marker = f"  •  {chapter}" if chapter else ""
            self.manga_list.addItem(f"{marker}{index + 1:03d} — {path.name}{chapter_marker}")
        if self.manga.pages:
            self.manga_list.setCurrentRow(min(max(current, 0), len(self.manga.pages) - 1))

    def _add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Escolher imagens", "", IMAGE_FILTER)
        if paths:
            self._append_manga_pages(sorted((Path(p) for p in paths), key=_natural_key))

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Escolher pasta de imagens")
        if path:
            extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
            pages = sorted((p for p in Path(path).rglob("*") if p.suffix.lower() in extensions), key=_natural_key)
            self._append_manga_pages(pages)

    def _add_url(self):
        url, ok = QInputDialog.getText(self, "Importar imagens", "URL de uma imagem ou galeria pública:")
        if not ok or not url.strip():
            return
        temp = tempfile.TemporaryDirectory(prefix="conversor-epub-hq-")
        self.temp_downloads.append(temp)
        self._start("Baixando imagens da página...", import_images_from_url, self._url_imported, url.strip(), temp.name)

    def _url_imported(self, paths: list[Path]):
        if not paths:
            self._error("Nenhuma imagem de página foi encontrada. Tente salvar as imagens e usar 'Adicionar pasta'.")
            return
        self._append_manga_pages(paths)

    def _show_manga_page(self, row: int):
        if 0 <= row < len(self.manga.pages):
            image = QPixmap(str(self.manga.pages[row]))
            self.manga_image.setPixmap(image.scaledToWidth(700, Qt.TransformationMode.SmoothTransformation))

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

    def _set_manga_cover(self):
        row = self.manga_list.currentRow()
        if 0 <= row < len(self.manga.pages):
            self.manga.cover_index = row
            self._refresh_manga_list()

    def _set_manga_chapter(self):
        row = self.manga_list.currentRow()
        if not 0 <= row < len(self.manga.pages):
            return
        page = self.manga.pages[row]
        current = self.manga.chapter_titles.get(str(page), "")
        title, ok = QInputDialog.getText(self, "Capítulo", "Título do capítulo que começa nesta página:", text=current)
        if ok:
            if title.strip():
                self.manga.chapter_titles[str(page)] = title.strip()
            else:
                self.manga.chapter_titles.pop(str(page), None)
            self._refresh_manga_list()

    def _export_manga(self):
        if not self.manga.pages:
            self._error("Adicione imagens primeiro.")
            return
        self.manga.title = self.manga_title.text().strip() or self.manga.pages[0].parent.name
        self.manga.author = self.manga_author.text().strip()
        self.manga.language = self.manga_language.text().strip()
        self.manga.right_to_left = self.manga_rtl.isChecked()
        path, _ = QFileDialog.getSaveFileName(self, "Salvar EPUB", f"{self.manga.title}.epub", "EPUB (*.epub)")
        if path:
            self._start("Gerando EPUB de HQ...", export_manga, lambda _: self.statusBar().showMessage(f"EPUB salvo em {path}"), self.manga, path)


def main():
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
