# SPDX-License-Identifier: AGPL-3.0-only

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
from PIL import Image
from PySide6.QtCore import QEvent, QMimeData, QPointF, QSettings, QThread, QUrl, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QPushButton

from conversor.gui import MainWindow, current_task
from conversor.models import PdfProject
from conversor.pdf_analysis import analyze_pdf


class TaskLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
                cls.app = QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # A throwaway INI file keeps the user's real language choice and shelf untouched.
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.window = MainWindow(self.settings)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def _wait(self, condition, timeout=5.0):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        return condition()

    def _wait_idle(self):
        return self._wait(lambda: not self.window.tasks)

    def _pdf(self, name):
        source = self.root / name
        doc = pymupdf.open()
        for heading, body in (("Capítulo 1", "Primeiro parágrafo."), ("Capítulo 2", "Segundo parágrafo.")):
            page = doc.new_page()
            page.insert_text((72, 80), heading, fontsize=22)
            page.insert_text((72, 130), body, fontsize=11)
        doc.save(source)
        doc.close()
        return source

    def _load_pdf(self, name="book.pdf"):
        self.window._show_workspace("pdf")
        self.window._pdf_loaded(analyze_pdf(self._pdf(name)))
        return self.window.pdf

    def _page(self, index):
        path = self.root / f"{index + 1:03d}.png"
        Image.new("RGB", (40, 60), (index * 40, 0, 0)).save(path)
        return path

    def test_language_toggle_rebuilds_after_the_clicked_button_is_gone(self):
        project = self._load_pdf()
        self.window.pdf_title.setText("Meu livro")
        self.window._append_manga_pages([self._page(0), self._page(1)])
        self.window._filter_blocks("Capítulo")
        self.window.preview_stack.setCurrentIndex(1)
        self.window.manga_rtl.setChecked(False)
        self.window.manga_list.setCurrentRow(1)

        english = next(button for button in self.window.language_toggles[0].findChildren(QPushButton) if button.text() == "EN")
        english.click()
        self.app.processEvents()

        self.assertIs(self.window.pdf, project)
        self.assertEqual(self.window.pdf_title.text(), "Meu livro")
        self.assertEqual(self.window.export_button.text(), "Create EPUB")
        self.assertEqual(self.window.block_filter, "Capítulo")
        self.assertTrue(self.window.filters["Capítulo"].isChecked())
        self.assertEqual(self.window.preview_stack.currentIndex(), 1)
        self.assertFalse(self.window.manga_rtl.isChecked())
        self.assertEqual(self.window.manga_direction.text(), "left to right →")
        self.assertEqual(self.window.manga_list.currentRow(), 1)
        self.assertEqual(self.settings.value("ui_language"), "en")

    def test_closing_the_window_cancels_workers_and_cleans_downloads(self):
        started = []
        results = []

        def worker():
            started.append(True)
            task = current_task()
            for _ in range(2000):
                if task.is_cancelled():
                    return "cancelled"
                time.sleep(0.005)
            return "finished"

        download = tempfile.TemporaryDirectory(prefix="conversor-epub-hq-")
        Path(download.name, "001.png").write_bytes(b"page")
        self.window.temp_downloads.append(download)
        self.window._start("Baixando imagens da página...", worker, results.append)
        self.assertTrue(self._wait(lambda: started))

        self.window.close()
        self.app.processEvents()

        self.assertEqual(self.window.tasks, [])
        self.assertEqual(self.window.temp_downloads, [])
        self.assertFalse(Path(download.name).exists())
        self.assertEqual(results, [])

    def test_controls_stay_disabled_until_the_worker_succeeds(self):
        self._load_pdf()
        finished = []

        def done(result):
            finished.append((result, QThread.currentThread() is self.app.thread()))

        self.window._start("Gerando EPUB...", lambda: "ok", done)
        self.assertTrue(self.window.busy)
        for control in self.window._busy_controls():
            self.assertFalse(control.isEnabled())
        self.assertFalse(self.window.export_button.isEnabled())

        self.assertTrue(self._wait(lambda: finished))
        self.assertEqual(finished, [("ok", True)])
        self.assertFalse(self.window.busy)
        for control in self.window._busy_controls():
            self.assertTrue(control.isEnabled())
        self.assertTrue(self.window.export_button.isEnabled())

    def test_controls_come_back_after_a_worker_failure(self):
        self._load_pdf()

        def explode():
            raise RuntimeError("não foi possível converter")

        with patch("conversor.gui.QMessageBox.critical") as critical:
            self.window._start("Gerando EPUB...", explode, lambda _: None)
            self.assertFalse(self.window.export_button.isEnabled())
            self.assertTrue(self._wait_idle())

        critical.assert_called_once()
        self.assertFalse(self.window.busy)
        self.assertTrue(self.window.export_button.isEnabled())
        for control in self.window._busy_controls():
            self.assertTrue(control.isEnabled())
        self.assertTrue(self.window.activity.text().startswith("Falha: "))

        self.window._remove_manga_cover()
        self.assertEqual(self.window.activity.text(), "")
        self.assertIsNone(self.window.failure)

    def test_failed_analysis_leaves_no_exportable_project_behind(self):
        with patch("conversor.gui.QMessageBox.critical"):
            self.window._analyze_pdf(str(self.root / "missing.pdf"))
            self.assertTrue(self._wait_idle())

        self.assertIsNone(self.window.pdf)
        self.assertFalse(self.window.export_button.isEnabled())
        self.assertEqual(self.window.screen_name, "start")

    def test_failed_analysis_rolls_back_to_the_previous_project(self):
        project = self._load_pdf()
        with patch("conversor.gui.QMessageBox.critical"):
            self.window._analyze_pdf(str(self.root / "missing.pdf"))
            self.assertTrue(self._wait_idle())

        self.assertIs(self.window.pdf, project)
        self.assertTrue(self.window.export_button.isEnabled())
        self.assertEqual(self.window.screen_name, "workspace")
        self.assertEqual(self.window.mode, "pdf")

    def test_new_pdf_resets_the_block_filter(self):
        self._load_pdf()
        self.window._filter_blocks("Capítulo")
        self.assertEqual(self.window.block_filter, "Capítulo")

        self.window._pdf_loaded(analyze_pdf(self._pdf("second.pdf")))

        self.assertEqual(self.window.block_filter, "all")
        self.assertTrue(self.window.filters["all"].isChecked())
        self.assertFalse(self.window.filters["Capítulo"].isChecked())
        self.assertTrue(all(not item.isHidden() for item in self.window.block_items))

    def test_busy_gate_survives_a_pdf_without_blocks(self):
        self._load_pdf()
        self.assertTrue(self.window.editor_buttons)
        source = self.root / "empty.pdf"
        doc = pymupdf.open()
        doc.new_page()
        doc.save(source)
        doc.close()
        self.window._pdf_loaded(PdfProject(source=source, title="Vazio", page_roles=["Conteúdo"]))
        # The editor widget is only scheduled for deletion, so the stale buttons die on the next turn.
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(self.window.editor_buttons, [])

        self.window._start("Analisando PDF...", lambda: "ok", lambda _: None)
        self.assertTrue(self.window.busy)
        self.assertTrue(self._wait_idle())
        self.assertFalse(self.window.busy)

    def test_export_workers_receive_a_snapshot_of_the_project(self):
        project = self._load_pdf()
        # The generated fixture has little text per page; the OCR gate is not what this test covers.
        project.scanned_pages.clear()
        seen = []

        def fake_export(snapshot, _destination):
            seen.append(snapshot)

        target = str(self.root / "book.epub")
        with patch("conversor.gui.QFileDialog.getSaveFileName", return_value=(target, "")), \
                patch("conversor.gui.export_pdf", side_effect=fake_export), \
                patch.object(self.window, "_export_done"):
            self.window._export_pdf()
            self.assertTrue(self._wait_idle())

        self.assertEqual(len(seen), 1)
        self.assertIsNot(seen[0], project)
        self.assertIsNot(seen[0].blocks[0], project.blocks[0])
        self.assertEqual(len(seen[0].blocks), len(project.blocks))
        self.assertEqual(seen[0].title, project.title)

    def test_dropping_files_while_busy_is_ignored(self):
        self.window._start("Gerando EPUB...", lambda: time.sleep(0.2), lambda _: None)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self._page(9)))])
        event = QDropEvent(QPointF(4, 4), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.window.dropEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(self.window.activity.text(), "Aguarde a tarefa atual terminar.")
        self.assertEqual(self.window.manga.pages, [])
        self.assertTrue(self._wait_idle())

    def test_validation_notices_use_the_activity_line(self):
        with patch("conversor.gui.QMessageBox.critical") as critical:
            self.window._export_pdf()
            self.assertEqual(self.window.activity.text(), "Importe um PDF primeiro.")
            self.window._export_manga()
            self.assertEqual(self.window.activity.text(), "Adicione imagens primeiro.")
            self.window._add_pdf_cover()
            self.assertEqual(self.window.activity.text(), "Importe um PDF primeiro.")
            self.window._imported([], [])
        self.assertEqual(self.window.activity.text(), "Nenhuma imagem de página foi encontrada. Tente salvar as imagens e usar 'Adicionar pasta'.")
        critical.assert_not_called()
        self.assertIsNone(self.window.failure)

    def test_manga_title_falls_back_instead_of_using_the_temp_folder(self):
        download = tempfile.TemporaryDirectory(prefix="conversor-epub-hq-")
        self.window.temp_downloads.append(download)
        path = Path(download.name, "001.png")
        Image.new("RGB", (40, 60), (10, 0, 0)).save(path)
        self.window._append_manga_pages([path])
        self.window._show_workspace("manga")

        with patch("conversor.gui.QFileDialog.getSaveFileName", return_value=("", "")) as save:
            self.window._export_manga()

        self.assertEqual(self.window.manga.title, "HQ")
        self.assertEqual(save.call_args.args[2], "HQ.epub")

    def test_pdf_page_preview_only_renders_on_the_original_tab(self):
        self._load_pdf()
        self.assertEqual(self.window.preview_stack.currentIndex(), 0)
        self.assertEqual(self.window.page_images, {})
        self.assertEqual(len({block.page for block in self.window.pdf.blocks}), 2)

        self.window.preview_stack.setCurrentIndex(1)
        page = self.window.pdf.blocks[self.window.selected_block].page
        self.assertFalse(self.window.page_images[page].isNull())

        self.window.preview_stack.setCurrentIndex(0)
        for item in self.window.block_items:
            self.window.block_list.setCurrentItem(item)
        self.assertEqual(set(self.window.page_images), {page})


if __name__ == "__main__":
    unittest.main()
