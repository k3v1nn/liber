# SPDX-License-Identifier: AGPL-3.0-only

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog

from conversor.gui import MainWindow, UrlImportDialog, parse_url_lines
from conversor.web_images import ImportCancelled, ImportReport
from conversor.widgets import THUMBNAILS


class ImportWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
                cls.app = QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.window = MainWindow(self.settings)
        THUMBNAILS.cache.clear()
        THUMBNAILS.pending.clear()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        THUMBNAILS.cache.clear()
        THUMBNAILS.pending.clear()
        self.tmp.cleanup()

    def _wait(self, condition, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        return condition()

    def _wait_idle(self):
        return self._wait(lambda: not self.window.tasks)

    def _page(self, index, size=(40, 60)):
        path = self.root / "local" / f"{index + 1:03d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, (index % 250, 10, 20)).save(path)
        return path

    def test_parse_url_lines_dedupes_and_counts_invalid_lines(self):
        urls, rejected = parse_url_lines(
            " https://example.org/a \n\nhttps://example.org/a\nftp://example.org/b\nnot a link\nhttps://example.org/c\n")
        self.assertEqual(urls, ["https://example.org/a", "https://example.org/c"])
        self.assertEqual(rejected, 2)

    def test_dialog_prefill_comes_from_clipboard_links_only(self):
        QApplication.clipboard().setText("https://example.org/a\nlixo\nhttps://example.org/a\nhttps://example.org/b\n")
        self.assertEqual(self.window._clipboard_links(), "https://example.org/a\nhttps://example.org/b")

        dialog = UrlImportDialog(self.window, "Importar imagens", "Um link por linha:",
                                 self.window._link_counts, "Importar", "Cancelar")
        dialog.set_links(self.window._clipboard_links())
        self.assertEqual(dialog.urls(), ["https://example.org/a", "https://example.org/b"])

        dialog.editor.setPlainText("https://example.org/typed")
        dialog.set_links("https://example.org/other")
        self.assertEqual(dialog.urls(), ["https://example.org/typed"])
        dialog.deleteLater()

    def test_url_dialog_reports_the_pasted_links(self):
        dialog = UrlImportDialog(self.window, "Importar imagens", "Um link por linha:",
                                 self.window._link_counts, "Importar", "Cancelar")
        dialog.set_links("https://example.org/a\nlixo\nhttps://example.org/a\nhttps://example.org/b")
        self.assertEqual(dialog.urls(), ["https://example.org/a", "https://example.org/b"])
        self.assertTrue(dialog.accept_button.isEnabled())
        self.assertIn("2 links prontos", dialog.count.text())
        self.assertIn("1 linha inválida", dialog.count.text())

        dialog.editor.setPlainText("lixo")
        self.assertEqual(dialog.urls(), [])
        self.assertFalse(dialog.accept_button.isEnabled())
        dialog.deleteLater()

    def test_appending_a_batch_keeps_existing_rows_and_selection(self):
        first = [self._page(index) for index in range(3)]
        self.window._show_workspace("manga")
        self.window._append_manga_pages(first)
        rows = [self.window.manga_list.item(row) for row in range(3)]
        self.window.manga_list.setCurrentRow(1)
        preview = self.window.manga_image.original

        second = [self._page(index) for index in range(3, 6)]
        self.window._append_manga_pages(second)

        self.assertEqual(self.window.manga_list.count(), 6)
        for row, item in enumerate(rows):
            self.assertIs(self.window.manga_list.item(row), item)
        self.assertEqual(self.window.manga_list.currentRow(), 1)
        self.assertIs(self.window.manga_image.original, preview)
        self.assertEqual(self.window.activity.text(), "6 páginas nesta HQ (1 fonte).")

    def test_multi_url_import_appends_reports_in_order_and_summarises(self):
        urls = ["https://example.org/um", "https://example.org/dois"]

        def fake_import(targets, directory, *, progress=None, is_cancelled=None):
            reports = []
            for position, url in enumerate(targets, 1):
                folder = Path(directory) / f"source-{position:02d}"
                folder.mkdir(parents=True, exist_ok=True)
                paths = []
                for page in range(2):
                    target = folder / f"page-{page + 1:04d}.png"
                    Image.new("RGB", (40, 60), (position * 20, page * 10, 0)).save(target)
                    paths.append(target)
                if progress:
                    progress(2, 2, f"Imagem {position} de {len(targets)}")
                reports.append(ImportReport(url=url, title=f"Título {position}", paths=paths,
                                            skipped=position - 1, truncated=position == len(targets)))
            return reports

        with patch("conversor.gui.UrlImportDialog", _AcceptedDialog(urls)), \
                patch("conversor.gui.import_images_from_urls", side_effect=fake_import):
            self.window._add_url()
            self.assertTrue(self._wait_idle())

        pages = self.window.manga.pages
        self.assertEqual([path.name for path in pages],
                         ["page-0001.png", "page-0002.png", "page-0001.png", "page-0002.png"])
        self.assertEqual([path.parent.name for path in pages], ["source-01", "source-01", "source-02", "source-02"])
        self.assertEqual(self.window.manga_list.count(), 4)
        self.assertEqual(self.window.manga_title.text(), "Título 1")
        summary = self.window.activity.text()
        self.assertTrue(summary.startswith("4 páginas nesta HQ (2 fontes)."))
        self.assertIn("4 páginas de 2 links", summary)
        self.assertIn("1 ignoradas", summary)
        self.assertTrue(summary.endswith("limitado a 300."))
        self.assertIsNone(self.window.import_progress)
        # The pages are still in use, so the temporary source folder must survive the task.
        self.assertEqual(len(self.window.temp_downloads), 1)
        self.assertTrue(pages[0].parent.exists())
        self.assertEqual(self.window.manga_list.item(0).toolTip(), f"Título 1 · page-0001.png")

    def test_import_progress_updates_the_activity_and_the_ribbon(self):
        self.window._import_progress(3, 10, "Imagem 3 de 10")
        self.assertEqual(self.window.activity.text(), "Baixando 3/10 — Imagem 3 de 10")
        self.assertAlmostEqual(self.window.ribbon.fraction, 0.3)

    def test_cancelled_import_keeps_the_project_and_removes_its_temp_folder(self):
        existing = self._page(0)
        self.window._show_workspace("manga")
        self.window._append_manga_pages([existing])
        started = threading.Event()
        seen = {}

        def fake_import(targets, directory, *, progress=None, is_cancelled=None):
            seen["folder"] = Path(directory)
            started.set()
            while not is_cancelled():
                time.sleep(0.01)
            raise ImportCancelled()

        with patch("conversor.gui.UrlImportDialog", _AcceptedDialog(["https://example.org/um"])), \
                patch("conversor.gui.import_images_from_urls", side_effect=fake_import):
            self.window._add_url()
            self.assertTrue(self._wait(started.is_set))
            self.assertFalse(self.window.cancel_button.isHidden())
            self.window._cancel_task()
            self.assertTrue(self._wait_idle())

        self.assertEqual(self.window.manga.pages, [existing])
        self.assertEqual(self.window.manga_list.count(), 1)
        self.assertEqual(self.window.activity.text(), "Tarefa cancelada.")
        self.assertEqual(self.window.temp_downloads, [])
        self.assertFalse(seen["folder"].exists())
        self.assertTrue(self.window.cancel_button.isHidden())

    def test_removing_the_last_page_of_a_source_cleans_its_temp_folder(self):
        download = self.window._new_temp("conversor-epub-hq-")
        folder = Path(download.name)
        pages = [folder / "page-0001.png", folder / "page-0002.png"]
        for index, path in enumerate(pages):
            Image.new("RGB", (40, 60), (index * 30, 0, 0)).save(path)

        self.window._show_workspace("manga")
        self.window._append_manga_pages(pages)
        self.window.manga_list.setCurrentRow(0)
        self.window._remove_page()
        self.assertTrue(folder.exists())
        self.assertEqual(len(self.window.temp_downloads), 1)

        self.window.manga_list.setCurrentRow(0)
        self.window._remove_page()
        self.assertFalse(folder.exists())
        self.assertEqual(self.window.temp_downloads, [])

    def test_three_hundred_pages_append_without_decoding_on_the_gui_thread(self):
        paths = [self._page(index, size=(120, 180)) for index in range(300)]
        self.window._show_workspace("manga")
        threads = []

        def fake_decode(path, size):
            threads.append(threading.get_ident())
            return _small_image(size)

        with patch("conversor.widgets._decode_thumbnail", side_effect=fake_decode):
            started = time.monotonic()
            self.window._append_manga_pages(paths)
            elapsed = time.monotonic() - started
            self.assertEqual(self.window.manga_list.count(), 300)
            self.assertLess(elapsed, 5.0, f"appending 300 pages took {elapsed:.2f}s")
            self.assertEqual(threads, [])

            self.window.manga_list.grab()
            self.assertTrue(self._wait(lambda: threads and not THUMBNAILS.busy(), timeout=15))
        self.assertNotIn(threading.main_thread().ident, threads)


def _small_image(size):
    image = QImage(size.width(), size.height(), QImage.Format.Format_RGB32)
    image.fill(QColor("#804020"))
    return image


class _AcceptedDialog:
    """Stands in for UrlImportDialog: accepted, with a fixed list of links."""

    def __init__(self, urls):
        self.links = urls

    def __call__(self, *_args, **_kwargs):
        return self

    def set_links(self, _text):
        return None

    def exec(self):
        return QDialog.DialogCode.Accepted

    def urls(self):
        return list(self.links)


if __name__ == "__main__":
    unittest.main()
