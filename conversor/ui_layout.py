# SPDX-License-Identifier: AGPL-3.0-only
"""Workspace layout shared by both conversion modes."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QStackedWidget, QTabWidget, QTableWidget, QTextBrowser,
    QVBoxLayout, QWidget,
)

from .appearance import line_icon, CleanComboBox as QComboBox
from .models import BLOCK_ROLES, PAGE_ROLES


class WorkspaceLayout:
    def _label(self, text, role="muted"):
        label = QLabel(self._t(text))
        label.setObjectName(role)
        label.setWordWrap(True)
        return label

    def _card(self, title):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._label(title, "sectionLabel"))
        return card, layout

    def _button(self, label, callback, primary=False, icon=None, compact=False):
        button = QPushButton("" if compact else self._t(label))
        button.setAccessibleName(self._t(label))
        button.setToolTip(self._t(label))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(36)
        if icon:
            button.setIcon(line_icon(icon, "#ffffff" if primary else "#657792"))
            button.setIconSize(QSize(18, 18))
        if compact:
            button.setFixedWidth(36)
            button.setProperty("quiet", True)
        button.setProperty("primary", primary)
        button.clicked.connect(callback)
        return button

    def _field(self, layout, label, value=""):
        column = QVBoxLayout()
        column.setSpacing(5)
        column.addWidget(self._label(label, "eyebrow"))
        field = QLineEdit(value)
        field.setFixedHeight(36)
        column.addWidget(field)
        layout.addLayout(column)
        return field

    def _details_panel(self, mode):
        panel = QWidget()
        panel.setObjectName("details")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        metadata, form = self._card("Dados do livro" if mode == "pdf" else "Dados da HQ")
        form.setSpacing(8)
        for name, label, value in (("title", "Título", ""), ("author", "Autor", ""), ("language", "Idioma", "pt-BR")):
            setattr(self, f"{mode}_{name}", self._field(form, label, value))
        if mode == "manga":
            self.manga_rtl = QCheckBox(self._t("Leitura da direita para a esquerda"))
            self.manga_rtl.setChecked(True)
            self.manga_rtl.setStyleSheet("font-size: 11px;")
            form.addWidget(self.manga_rtl)
        layout.addWidget(metadata)
        cover, content = self._card("Capa")
        content.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(12)
        thumb = QLabel()
        thumb.setObjectName("coverWell")
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setFixedSize(78, 108)
        thumb.setPixmap(line_icon("image", "#a3b0c2", 28).pixmap(28, 28))
        setattr(self, f"{mode}_cover_image", thumb)
        row.addWidget(thumb)
        info = self._label("Escolha uma página ou adicione uma imagem.")
        info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        setattr(self, f"{mode}_cover_info", info)
        row.addWidget(info, 1)
        content.addLayout(row)
        combo = QComboBox()
        combo.setFixedHeight(36)
        combo.setMinimumContentsLength(8)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.addItem(self._t("Importe um PDF para escolher a capa" if mode == "pdf" else "Adicione páginas para escolher a capa"))
        combo.setEnabled(False)
        combo.currentIndexChanged.connect(getattr(self, f"_{mode}_cover_changed"))
        setattr(self, f"{mode}_cover_combo", combo)
        content.addWidget(combo)
        buttons = QHBoxLayout()
        buttons.addWidget(self._button("Escolher imagem", getattr(self, f"_add_{mode}_cover"), icon="image"), 1)
        clear = self._button("Limpar capa", getattr(self, f"_remove_{mode}_cover"), icon="trash", compact=True)
        clear.setEnabled(False)
        setattr(self, f"{mode}_clear_cover", clear)
        buttons.addWidget(clear)
        content.addLayout(buttons)
        layout.addWidget(cover)
        if mode == "pdf":
            self.pdf_warning = self._label("A análise sugere a estrutura; revise os títulos e a ordem dos blocos.")
            layout.addWidget(self.pdf_warning)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(292)
        scroll.setMaximumWidth(304)
        scroll.setWidget(panel)
        return scroll

    def _empty_state(self, title, description, action, callback, icon):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 24, 20, 24)
        layout.addStretch()
        symbol = QLabel()
        symbol.setPixmap(line_icon(icon, "#96a9c8", 40).pixmap(40, 40))
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(symbol)
        heading = self._label(title, "sectionLabel")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        text = self._label(description)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text)
        layout.addSpacing(10)
        button = self._button(action, callback, icon=icon)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        return widget

    def _workspace(self, mode, imports):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(16)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        for label, callback, icon in imports:
            toolbar.addWidget(self._button(label, callback, icon=icon))
        toolbar.addStretch()
        export = self._button("Exportar EPUB", getattr(self, f"_export_{mode}"), primary=True, icon="download")
        export.setEnabled(False)
        setattr(self, f"{mode}_export_button", export)
        toolbar.addWidget(export)
        layout.addLayout(toolbar)
        workspace = QHBoxLayout()
        workspace.setSpacing(16)
        workspace.addWidget(self._details_panel(mode))
        layout.addLayout(workspace, 1)
        return root, workspace

    def _pdf_tab(self):
        root, workspace = self._workspace("pdf", [("Importar PDF", self._open_pdf, "file")])
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(12)
        splitter.setChildrenCollapsible(False)
        left, listing = self._card("Estrutura do livro")
        left.setMinimumWidth(240)
        self.block_stack = QStackedWidget()
        self.block_stack.addWidget(self._empty_state("Seu livro começa aqui", "Importe um PDF para organizar capítulos e revisar o texto.", "Importar PDF", self._open_pdf, "book"))
        self.block_table = QTableWidget(0, 3)
        self.block_table.setHorizontalHeaderLabels([self._t("Página"), self._t("Tipo"), self._t("Conteúdo")])
        self.block_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.block_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.block_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.block_table.setShowGrid(False)
        self.block_table.verticalHeader().setVisible(False)
        self.block_table.verticalHeader().setDefaultSectionSize(40)
        self.block_table.setColumnWidth(0, 48)
        self.block_table.setColumnWidth(1, 90)
        self.block_table.horizontalHeader().setStretchLastSection(True)
        self.block_table.currentCellChanged.connect(self._select_pdf_block)
        self.block_stack.addWidget(self.block_table)
        listing.addWidget(self.block_stack, 1)
        footer = QHBoxLayout()
        footer.addWidget(self._button("↑ Bloco", lambda: self._move_block(-1), icon="up", compact=True))
        footer.addWidget(self._button("↓ Bloco", lambda: self._move_block(1), icon="down", compact=True))
        footer.addStretch()
        listing.addLayout(footer)
        splitter.addWidget(left)
        right, preview = self._card("Revisão e prévia")
        right.setMinimumWidth(360)
        self.pdf_editor = QWidget()
        editor = QVBoxLayout(self.pdf_editor)
        editor.setContentsMargins(0, 0, 0, 0)
        editor.setSpacing(8)
        edit_row = QHBoxLayout()
        self.page_role = QComboBox()
        self.block_role = QComboBox()
        for combo, roles in ((self.page_role, PAGE_ROLES), (self.block_role, BLOCK_ROLES)):
            combo.setFixedHeight(34)
            for role in roles:
                combo.addItem(self._t(role), role)
        self.page_role.currentTextChanged.connect(self._page_role_changed)
        edit_row.addWidget(self._label("Página:"))
        edit_row.addWidget(self.page_role, 1)
        edit_row.addWidget(self._label("Bloco:"))
        edit_row.addWidget(self.block_role, 1)
        editor.addLayout(edit_row)
        self.block_text = QPlainTextEdit()
        self.block_text.setPlaceholderText(self._t("Texto do bloco selecionado"))
        self.block_text.setFixedHeight(90)
        editor.addWidget(self.block_text)
        editor.addWidget(self._button("Aplicar correção", self._save_pdf_edit, icon="check"), 0, Qt.AlignmentFlag.AlignRight)
        self.pdf_editor.setEnabled(False)
        preview.addWidget(self.pdf_editor)
        preview_tabs = QTabWidget()
        self.pdf_page_image = self._new_preview("Selecione um bloco para ver a página original.")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.pdf_page_image)
        preview_tabs.addTab(scroll, self._t("PDF original"))
        self.pdf_preview = QTextBrowser()
        preview_tabs.addTab(self.pdf_preview, self._t("Prévia do texto"))
        preview.addWidget(preview_tabs, 1)
        splitter.addWidget(right)
        splitter.setSizes([300, 600])
        workspace.addWidget(splitter, 1)
        return root

    def _manga_tab(self):
        root, workspace = self._workspace("manga", [
            ("Adicionar imagens", self._add_images, "image"), ("Adicionar pasta", self._add_folder, "folder"),
            ("Adicionar PDF", self._add_comic_pdf, "file"), ("Importar URL", self._add_url, "link"),
        ])
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(12)
        splitter.setChildrenCollapsible(False)
        left, listing = self._card("Páginas da HQ")
        left.setMinimumWidth(228)
        self.manga_stack = QStackedWidget()
        self.manga_stack.addWidget(self._empty_state("Uma página de cada vez", "Adicione imagens ou um PDF para montar sua HQ.", "Adicionar PDF", self._add_comic_pdf, "image"))
        self.manga_list = QListWidget()
        self.manga_list.currentRowChanged.connect(self._show_manga_page)
        self.manga_stack.addWidget(self.manga_list)
        listing.addWidget(self.manga_stack, 1)
        footer = QHBoxLayout()
        for label, callback, icon in (("↑ Subir", lambda: self._move_page(-1), "up"), ("↓ Descer", lambda: self._move_page(1), "down"), ("Remover", self._remove_page, "trash"), ("Início de capítulo", self._set_manga_chapter, "bookmark")):
            footer.addWidget(self._button(label, callback, icon=icon, compact=True))
        footer.addStretch()
        listing.addLayout(footer)
        splitter.addWidget(left)
        right, preview = self._card("Prévia da página")
        self.manga_image = self._new_preview("Selecione uma página para conferir.")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.manga_image)
        preview.addWidget(scroll, 1)
        splitter.addWidget(right)
        splitter.setSizes([260, 640])
        workspace.addWidget(splitter, 1)
        return root
