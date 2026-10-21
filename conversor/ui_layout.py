# SPDX-License-Identifier: AGPL-3.0-only
"""Builds the opening screen and the paper workspace shared by both conversion modes."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
    QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from .appearance import APP_NAME, GILT, INK, PAPER, TEXT_2, app_icon, brand_mark, line_icon, CleanComboBox as QComboBox
from .models import BLOCK_ROLES, PAGE_ROLES
from .widgets import (
    BookShelf, CoverThumb, PageFrame, PageList, PagePreview, PaperSurface, ProgressRibbon,
    ResponsiveBody, SidePanel, StartBackdrop, TocDelegate, ToggleSwitch,
)


class WorkspaceLayout:
    def _label(self, text, role="muted"):
        label = QLabel(self._t(text))
        label.setObjectName(role)
        label.setWordWrap(True)
        return label

    def _centered_text(self, text, role, width):
        # Centred wrapped labels get no height-for-width from the layout, so size them up front.
        label = self._label(text, role)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFixedWidth(width)
        label.ensurePolished()
        label.setFixedHeight(label.heightForWidth(width))
        return label

    def _eyebrow(self, text, role="eyebrow"):
        label = QLabel(self._t(text).upper())
        label.setObjectName(role)
        font = label.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
        label.setFont(font)
        return label

    def _line(self, name="hline"):
        line = QFrame()
        line.setObjectName(name)
        return line

    def _button(self, label, callback, kind=None, icon=None, icon_color=TEXT_2, compact=False, height=32, checked_color=None):
        button = QPushButton("" if compact else self._t(label))
        button.setProperty("label", label)
        button.setAccessibleName(self._t(label))
        if compact or icon:
            button.setToolTip(self._t(label))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(height)
        if kind:
            button.setProperty("kind", kind)
        if icon:
            button.setIcon(line_icon(icon, icon_color, 16, checked_color))
            button.setIconSize(QSize(16, 16))
        if compact:
            button.setFixedWidth(height)
            button.setProperty("kind", kind or "icon")
        if callback:
            button.clicked.connect(lambda _checked=False: callback())
        return button

    def _field(self, label, value="", serif=True):
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(1)
        caption = self._label(label, "fieldCaption")
        caption.setWordWrap(False)
        edit = QLineEdit(value)
        edit.setProperty("serif", serif)
        edit.setAccessibleName(self._t(label))
        caption.setBuddy(edit)
        column.addWidget(caption)
        column.addWidget(edit)
        return box, edit

    def _language_toggle(self, dark=False):
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        group = QButtonGroup(box)
        for code, name in (("pt", "Português"), ("en", "English")):
            button = QPushButton(code.upper())
            button.setProperty("kind", "lang")
            button.setProperty("dark", dark)
            button.setCheckable(True)
            button.setChecked(self.ui_language == code)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(26)
            button.setAccessibleName(name)
            button.setToolTip(f"{self._t('Idioma da interface')}: {name}")
            button.clicked.connect(lambda _checked=False, value=code: self._change_language(value))
            group.addButton(button)
            row.addWidget(button)
            if code == "pt":
                row.addWidget(self._label("·", "heroHint" if dark else "hint"))
        self.language_toggles.append(box)
        return box

    def _start_screen(self):
        screen = StartBackdrop()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(28, 20, 28, 16)
        layout.setSpacing(0)
        nav = QHBoxLayout()
        tile = QLabel()
        icon = app_icon(72)
        icon.setDevicePixelRatio(2)
        tile.setPixmap(icon)
        name = QLabel(APP_NAME)
        name.setObjectName("brandNameDark")
        nav.addWidget(tile)
        nav.addSpacing(8)
        nav.addWidget(name)
        nav.addStretch()
        nav.addWidget(self._language_toggle(dark=True))
        layout.addLayout(nav)
        layout.addStretch(3)
        self.hero = QWidget()
        hero = QVBoxLayout(self.hero)
        hero.setContentsMargins(0, 0, 0, 0)
        hero.setSpacing(0)
        self.hero_title = QLabel(f"{self._t('Converta PDF, mangá')}<br>{self._t('e HQ em')} <span style=\"color:{GILT}; font-style:italic\">EPUB.</span>")
        self.hero_title.setObjectName("heroTitle")
        self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = self._centered_text("Revise capítulos, capa e ordem das páginas antes de gerar o arquivo. Tudo no seu computador.", "heroText", 500)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()
        buttons.addWidget(self._button("Livro em PDF", lambda: self._show_workspace("pdf"), "cream", "file", INK, height=46))
        buttons.addWidget(self._button("Mangá / HQ", lambda: self._show_workspace("manga"), "ghostDark", "image", PAPER, height=46))
        buttons.addStretch()
        hint = self._label("ou arraste um PDF, imagens ou uma pasta para a janela", "heroHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(self.hero_title)
        hero.addSpacing(16)
        hero.addWidget(text, 0, Qt.AlignmentFlag.AlignHCenter)
        hero.addSpacing(26)
        hero.addLayout(buttons)
        hero.addSpacing(16)
        hero.addWidget(hint)
        layout.addWidget(self.hero)
        layout.addStretch(2)
        self.shelf_caption = self._eyebrow("", "shelfCaption")
        self.shelf_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.shelf = BookShelf()
        self.shelf.setFixedHeight(214)
        self.shelf.opened.connect(self._open_recent)
        layout.addWidget(self.shelf_caption)
        layout.addSpacing(4)
        layout.addWidget(self.shelf)
        screen.resized.connect(self._fit_hero)
        return screen

    def _workspace(self):
        surface = PaperSurface()
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._top_bar())
        layout.addWidget(self._line())
        self.ribbon = ProgressRibbon()
        layout.addWidget(self.ribbon)
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self._pdf_body())
        self.mode_stack.addWidget(self._manga_body())
        layout.addWidget(self.mode_stack, 1)
        layout.addWidget(self._line())
        footer = QWidget()
        footer.setFixedHeight(32)
        row = QHBoxLayout(footer)
        row.setContentsMargins(22, 0, 22, 0)
        self.activity = self._label("Importe um PDF ou páginas de HQ para começar.", "status")
        self.activity.setWordWrap(False)
        self.activity.setMinimumWidth(10)
        self.summary = self._label("", "count")
        self.summary.setWordWrap(False)
        row.addWidget(self.activity, 1)
        row.addWidget(self.summary)
        layout.addWidget(footer)
        return surface

    def _top_bar(self):
        bar = QWidget()
        bar.setFixedHeight(60)
        row = QHBoxLayout(bar)
        row.setContentsMargins(22, 0, 22, 0)
        row.setSpacing(10)
        brand = QPushButton(APP_NAME)
        brand.setProperty("kind", "brand")
        brand.setIcon(QIcon(brand_mark(28)))
        brand.setIconSize(QSize(28, 28))
        brand.setCursor(Qt.CursorShape.PointingHandCursor)
        brand.setToolTip(self._t("Voltar ao início"))
        brand.setAccessibleName(self._t("Voltar ao início"))
        brand.clicked.connect(self._show_start)
        row.addWidget(brand)
        row.addSpacing(8)
        group = QButtonGroup(bar)
        self.tab_buttons = {}
        for mode, label, icon in (("pdf", "Livro em PDF", "file"), ("manga", "Mangá / HQ", "image")):
            button = self._button(label, lambda value=mode: self._set_mode(value), "tab", icon, checked_color=PAPER)
            button.setCheckable(True)
            group.addButton(button)
            self.tab_buttons[mode] = button
            self.text_buttons.append(button)
            row.addWidget(button)
        row.addStretch()
        self.pdf_import_button = self._button("Importar PDF", self._open_pdf, icon="file")
        self.text_buttons.append(self.pdf_import_button)
        row.addWidget(self.pdf_import_button)
        self.manga_add_group = QFrame()
        self.manga_add_group.setObjectName("addGroup")
        self.manga_add_group.setFixedHeight(32)
        group_row = QHBoxLayout(self.manga_add_group)
        group_row.setContentsMargins(0, 0, 0, 0)
        group_row.setSpacing(0)
        sources = self._manga_sources()
        for index, (icon, label, full, callback, short) in enumerate(sources):
            if index:
                group_row.addWidget(self._line("vline"))
            button = self._button(label, callback, "part", icon, height=30)
            button.setProperty("short", short)
            button.setProperty("edge", "left" if index == 0 else "right" if index == len(sources) - 1 else "")
            button.setAccessibleName(self._t(full))
            button.setToolTip(self._t(full))
            self.add_buttons.append(button)
            group_row.addWidget(button)
        row.addWidget(self.manga_add_group)
        row.addSpacing(6)
        row.addWidget(self._language_toggle())
        row.addSpacing(6)
        self.export_button = self._button("Gerar EPUB", self._export_current, "seal", "download", "#fff6ea", height=34)
        row.addWidget(self.export_button)
        return bar

    def _manga_sources(self):
        return (
            ("image", "Imagens", "Adicionar imagens", self._add_images, "Imagens"),
            ("folder", "Pasta", "Adicionar pasta", self._add_folder, "Pasta"),
            ("file", "PDF de HQ", "Adicionar PDF", self._add_comic_pdf, "PDF"),
            ("link", "URL pública", "Importar URL", self._add_url, "URL"),
        )

    def _empty_state(self, title, description, actions, hint=""):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)
        layout.addStretch(2)
        heading = self._label(title, "emptyTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = self._centered_text(description, "muted", 420)
        layout.addWidget(heading)
        layout.addSpacing(10)
        layout.addWidget(text, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(22)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch()
        for index, (icon, label, callback) in enumerate(actions):
            row.addWidget(self._button(label, callback, "ink" if index == 0 else "outline", icon, PAPER if index == 0 else INK, height=40))
        row.addStretch()
        layout.addLayout(row)
        if hint:
            note = self._label(hint, "hint")
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addSpacing(14)
            layout.addWidget(note)
        layout.addStretch(3)
        return widget

    def _side_panel(self, mode):
        fields = []
        for name, label, value, serif in (("title", "Título", "", True), ("author", "Autor", "", True), ("language", "Idioma", "pt-BR", False)):
            box, edit = self._field(label, value, serif)
            setattr(self, f"{mode}_{name}", edit)
            fields.append(box)
        extras = []
        if mode == "manga":
            self.manga_rtl = ToggleSwitch(self._t("Leitura da direita para a esquerda"))
            self.manga_rtl.setChecked(True)
            self.manga_rtl.setAccessibleName(self._t("Leitura da direita para a esquerda"))
            self.manga_rtl.toggled.connect(self._update_reading_direction)
            extras.append(self.manga_rtl)
        thumb = CoverThumb(QSize(92, 138))
        thumb.setAccessibleName(self._t("Capa"))
        setattr(self, f"{mode}_cover_image", thumb)
        cover = QWidget()
        stack = QVBoxLayout(cover)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(thumb, 0, Qt.AlignmentFlag.AlignBottom)
        actions = QVBoxLayout()
        actions.setSpacing(7)
        actions.addStretch()
        combo = QComboBox()
        combo.setFixedHeight(26)
        combo.setMinimumContentsLength(18)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.addItem(self._t("Importe um PDF para escolher a capa" if mode == "pdf" else "Adicione páginas para escolher a capa"))
        combo.setAccessibleName(self._t("Escolher página do PDF" if mode == "pdf" else "Capa"))
        combo.setEnabled(False)
        combo.currentIndexChanged.connect(getattr(self, f"_{mode}_cover_changed"))
        setattr(self, f"{mode}_cover_combo", combo)
        actions.addWidget(self._button("Escolher imagem", getattr(self, f"_add_{mode}_cover"), "link", height=20))
        clear = self._button("Limpar capa", getattr(self, f"_remove_{mode}_cover"), "link", height=20)
        clear.setEnabled(False)
        setattr(self, f"{mode}_clear_cover", clear)
        actions.addWidget(clear)
        info = self._label("", "count")
        info.hide()
        setattr(self, f"{mode}_cover_info", info)
        actions.addWidget(info)
        row.addLayout(actions, 1)
        stack.addLayout(row)
        stack.addWidget(combo)
        hint = None
        if mode == "pdf":
            self.pdf_warning = self._label("A análise sugere a estrutura; revise os títulos e a ordem dos blocos.", "hint")
            hint = self.pdf_warning
        return SidePanel(self._eyebrow("Livro" if mode == "pdf" else "HQ"), fields, extras, self._eyebrow("Capa"), cover, thumb, hint)

    def _column(self, eyebrow, extra=None):
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(24, 22, 24, 14)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(self._eyebrow(eyebrow))
        header.addStretch()
        if extra:
            header.addWidget(extra)
        layout.addLayout(header)
        return column, layout

    def _scrolling(self, body):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(body)
        body.setAutoFillBackground(False)
        return scroll

    def _segmented(self, options, callback):
        frame = QFrame()
        frame.setObjectName("segmented")
        row = QHBoxLayout(frame)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)
        group = QButtonGroup(frame)
        for index, label in enumerate(options):
            button = self._button(label, lambda value=index: callback(value), "seg", height=22)
            button.setCheckable(True)
            button.setChecked(index == 0)
            group.addButton(button)
            row.addWidget(button)
        return frame

    def _pdf_body(self):
        self.pdf_stack = QStackedWidget()
        self.pdf_stack.addWidget(self._empty_state(
            "Nenhum PDF aberto", "Importe um PDF para revisar capítulos, capa e texto antes de gerar o EPUB.",
            (("file", "Importar PDF", self._open_pdf),), "ou arraste o arquivo para a janela"))
        side = self._side_panel("pdf")
        self.pdf_count = self._label("", "count")
        middle, listing = self._column("Estrutura", self.pdf_count)
        filters = QHBoxLayout()
        filters.setSpacing(16)
        group = QButtonGroup(middle)
        self.block_filter = "all"
        for key, label in (("all", "Tudo"), ("Capítulo", "Capítulos"), ("Nota", "Notas"), ("Imagem", "Imagens"), ("Ignorar", "Ignorados")):
            button = self._button(label, lambda value=key: self._filter_blocks(value), "filter", height=22)
            button.setCheckable(True)
            button.setChecked(key == "all")
            group.addButton(button)
            filters.addWidget(button)
        filters.addStretch()
        listing.addLayout(filters)
        self.block_list = QListWidget()
        self.block_list.setItemDelegate(TocDelegate(self.block_list))
        self.block_list.setMouseTracking(True)
        self.block_list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.block_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.block_list.setSpacing(1)
        self.block_list.setAccessibleName(self._t("Estrutura do livro"))
        self.block_list.currentItemChanged.connect(self._select_pdf_item)
        listing.addWidget(self.block_list, 1)
        self.preview_stack = QStackedWidget()
        right, preview = self._column("Prévia", self._segmented(("EPUB", "PDF original"), self.preview_stack.setCurrentIndex))
        page = PageFrame()
        page.setMaximumWidth(480)
        self.pdf_preview = QTextBrowser()
        self.pdf_preview.setAccessibleName(self._t("Prévia do texto"))
        self.pdf_preview.viewport().setAutoFillBackground(False)
        page.layout().addWidget(self.pdf_preview)
        holder = QWidget()
        centered = QHBoxLayout(holder)
        centered.setContentsMargins(0, 0, 0, 0)
        centered.addWidget(page)
        self.preview_stack.addWidget(holder)
        self.pdf_page_image = PagePreview(self._t("Selecione um bloco para ver a página original."))
        self.pdf_page_image.setAccessibleName(self._t("PDF original"))
        self.preview_stack.addWidget(self.pdf_page_image)
        preview.addWidget(self.preview_stack, 1)
        self.pdf_stack.addWidget(self._scrolling(ResponsiveBody(side, middle, right)))
        return self.pdf_stack

    def _manga_body(self):
        self.manga_stack = QStackedWidget()
        self.manga_stack.addWidget(self._empty_state(
            "Nenhuma página ainda", "Adicione imagens, uma pasta, um PDF de HQ ou uma URL pública para montar a HQ.",
            [(icon, full if icon == "image" else label, callback) for icon, label, full, callback, _short in self._manga_sources()],
            "ou arraste imagens, uma pasta ou um PDF para a janela"))
        side = self._side_panel("manga")
        self.manga_count = self._label("", "count")
        middle, listing = self._column("Páginas", self.manga_count)
        self.manga_list = PageList(self._load_page_pixmap)
        self.manga_list.setAccessibleName(self._t("Páginas da HQ"))
        self.manga_list.currentRowChanged.connect(self._show_manga_page)
        self.manga_list.reordered.connect(self._manga_reordered)
        listing.addWidget(self.manga_list, 1)
        listing.addWidget(self._line())
        actions = QHBoxLayout()
        actions.setSpacing(2)
        for label, callback, icon in (
            ("Mover para trás", lambda: self._move_page(-1), "up"), ("Mover para frente", lambda: self._move_page(1), "down"),
            ("Início de capítulo", self._set_manga_chapter, "bookmark"), ("Usar como capa", self._use_page_as_cover, "star"),
            ("Remover", self._remove_page, "trash"),
        ):
            actions.addWidget(self._button(label, callback, icon=icon, compact=True, height=30))
        actions.addSpacing(6)
        actions.addWidget(self._label("ou arraste para reordenar", "hint"))
        actions.addStretch()
        listing.addLayout(actions)
        right, preview = self._column("Prévia")
        self.manga_image = PagePreview(self._t("Selecione uma página para conferir."))
        self.manga_image.setAccessibleName(self._t("Prévia da página"))
        preview.addWidget(self.manga_image, 1)
        caption = QHBoxLayout()
        self.manga_caption = self._label("", "count")
        self.manga_direction = self._label("", "count")
        caption.addWidget(self.manga_caption, 1)
        caption.addWidget(self.manga_direction)
        preview.addLayout(caption)
        self.manga_stack.addWidget(self._scrolling(ResponsiveBody(side, middle, right)))
        return self.manga_stack

    def _block_editor(self, block):
        holder = QWidget()
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(22, 2, 4, 10)
        frame = QFrame()
        frame.setObjectName("editor")
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(8)
        meta = QHBoxLayout()
        meta.setSpacing(8)
        self.block_role = QComboBox()
        self.page_role = QComboBox()
        for combo, roles in ((self.block_role, BLOCK_ROLES), (self.page_role, PAGE_ROLES)):
            combo.setFixedHeight(24)
            for role in roles:
                combo.addItem(self._t(role), role)
        self.block_role.setCurrentIndex(self.block_role.findData(block.role))
        self.page_role.setCurrentIndex(self.page_role.findData(self.pdf.page_roles[block.page]))
        self.page_role.currentTextChanged.connect(self._page_role_changed)
        self.block_role.setAccessibleName(self._t("Bloco"))
        self.page_role.setAccessibleName(self._t("Página"))
        meta.addWidget(self._label("Tipo"))
        meta.addWidget(self.block_role)
        meta.addSpacing(14)
        meta.addWidget(self._label(f"{self._t('Página')} {block.page + 1}"))
        meta.addWidget(self.page_role)
        meta.addStretch()
        layout.addLayout(meta)
        self.block_text = QPlainTextEdit(block.text)
        self.block_text.setPlaceholderText(self._t("Texto do bloco selecionado"))
        self.block_text.setAccessibleName(self._t("Texto do bloco selecionado"))
        self.block_text.setFixedHeight(78)
        layout.addWidget(self.block_text)
        actions = QHBoxLayout()
        actions.addWidget(self._button("Aplicar correção", self._save_pdf_edit, "ink", "check", PAPER, height=28))
        actions.addStretch()
        actions.addWidget(self._button("Subir bloco", lambda: self._move_block(-1), icon="up", compact=True, height=28))
        actions.addWidget(self._button("Descer bloco", lambda: self._move_block(1), icon="down", compact=True, height=28))
        layout.addLayout(actions)
        return holder
