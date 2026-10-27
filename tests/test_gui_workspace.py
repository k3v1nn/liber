# SPDX-License-Identifier: AGPL-3.0-only

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
from PIL import Image
from PySide6.QtCore import QPointF, QSettings
from PySide6.QtWidgets import QApplication

from conversor.gui import MainWindow
from conversor.pdf_analysis import analyze_pdf
from conversor.widgets import BLOCK_INDEX, PAGE_PATH


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
                cls.app = QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # A throwaway INI file keeps the user's real language choice and shelf untouched on every platform.
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.window = MainWindow(self.settings)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def _load_pdf(self):
        source = self.root / "book.pdf"
        doc = pymupdf.open()
        for heading, body in (("Capítulo 1", "Primeiro parágrafo."), ("Capítulo 2", "Segundo parágrafo.")):
            page = doc.new_page()
            page.insert_text((72, 80), heading, fontsize=22)
            page.insert_text((72, 130), body, fontsize=11)
        doc.save(source)
        doc.close()
        self.window._show_workspace("pdf")
        self.window._pdf_loaded(analyze_pdf(source))
        return self.window.pdf

    def _pages(self, count):
        paths = []
        for index in range(count):
            path = self.root / f"{index + 1:03d}.png"
            Image.new("RGB", (40, 60), (index * 40, 0, 0)).save(path)
            paths.append(path)
        return paths

    def test_inline_editor_follows_selection_and_saves_the_previous_block(self):
        project = self._load_pdf()
        rows = [index for index, block in enumerate(project.blocks) if block.role == "Parágrafo"]
        self.window.block_list.setCurrentItem(self.window.block_items[rows[0]])
        self.window.block_text.setPlainText("Texto corrigido.")
        self.window.block_list.setCurrentItem(self.window.block_items[rows[1]])
        self.assertEqual(project.blocks[rows[0]].text, "Texto corrigido.")
        self.assertEqual(self.window.block_list.count(), len(project.blocks) + 1)
        editor_row = self.window.block_list.row(self.window.editor_item)
        self.assertEqual(self.window.block_list.item(editor_row - 1).data(BLOCK_INDEX), rows[1])

    def test_filter_shows_only_the_chosen_block_type(self):
        project = self._load_pdf()
        self.window._filter_blocks("Capítulo")
        visible = [row for row, item in enumerate(self.window.block_items) if not item.isHidden()]
        self.assertTrue(visible)
        self.assertTrue(all(project.blocks[row].role == "Capítulo" for row in visible))

    def test_dragging_pages_keeps_the_cover_page(self):
        pages = self._pages(3)
        self.window._append_manga_pages(pages)
        self.window.manga_list.setCurrentRow(1)
        self.window._use_page_as_cover()
        moved = self.window.manga_list.takeItem(1)
        self.window.manga_list.insertItem(0, moved)
        self.window._manga_reordered()
        self.assertEqual(self.window.manga.pages, [pages[1], pages[0], pages[2]])
        self.assertEqual(self.window.manga.cover_index, 0)
        self.assertEqual(self.window.manga_list.item(0).data(PAGE_PATH), str(pages[1]))

    def test_language_switch_keeps_the_open_projects(self):
        project = self._load_pdf()
        self.window.pdf_title.setText("Meu livro")
        self.window._append_manga_pages(self._pages(2))
        self.window._change_language("en")
        self.app.processEvents()
        self.assertIs(self.window.pdf, project)
        self.assertEqual(self.window.pdf_title.text(), "Meu livro")
        self.assertEqual(self.window.export_button.text(), "Create EPUB")
        self.assertEqual(self.window.manga_list.count(), 2)

    def test_exported_epub_goes_on_the_opening_shelf(self):
        self._load_pdf()
        target = self.root / "book.epub"
        target.touch()
        with patch("conversor.gui.QStandardPaths.writableLocation", return_value=str(self.root / "data")):
            self.window._export_done("pdf", str(target))
        recents = json.loads(self.settings.value("recent_epubs"))
        self.assertEqual(recents[0]["path"], str(target))
        self.assertTrue(Path(recents[0]["cover"]).is_file())
        self.window._show_start()
        self.assertEqual(self.window.shelf.books[0]["path"], str(target))

    def test_shelf_finds_the_book_under_the_mouse(self):
        shelf = self.window.shelf
        shelf.resize(1000, 214)
        shelf.started -= 5
        shelf.grab()
        self.assertGreaterEqual(shelf._book_at(QPointF(500.5, 107.5)), 0)
        self.assertEqual(shelf._book_at(QPointF(500.5, -300.5)), -1)

    def test_shelf_hit_testing_survives_a_stale_paint(self):
        shelf = self.window.shelf
        shelf.resize(1000, 214)
        shelf.started -= 5
        # No grab(): the geometry must be computed from the current frame, not from an old paint.
        self.assertGreaterEqual(shelf._book_at(QPointF(500.5, 107.5)), 0)

    def test_shelf_shows_the_real_recents_without_padding(self):
        recents = [{"path": str(self.root / f"book{index}.epub"), "title": f"Livro {index}", "kind": "pdf"}
                   for index in range(3)]
        self.settings.setValue("recent_epubs", json.dumps(recents))
        self.window._refresh_shelf()
        self.assertEqual([book["path"] for book in self.window.shelf.books], [entry["path"] for entry in recents])

    def test_shelf_paints_without_a_usable_width(self):
        shelf = self.window.shelf
        shelf.resize(0, 214)
        shelf.grab()

    def test_shelf_title_fit_is_cached_per_width(self):
        shelf = self.window.shelf
        first = shelf._title_font("Dom Casmurro", False, 100.0)
        self.assertIs(shelf._title_font("Dom Casmurro", False, 100.0), first)
        self.assertIsNot(shelf._title_font("Dom Casmurro", False, 120.0), first)


if __name__ == "__main__":
    unittest.main()
