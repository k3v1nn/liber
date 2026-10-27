# SPDX-License-Identifier: AGPL-3.0-only

import os
import tempfile
import threading
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import pymupdf
from PIL import Image
from PySide6.QtCore import QMimeData, QPointF, QSettings, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QLabel

from conversor.gui import MainWindow
from conversor.pdf_analysis import analyze_pdf


class FeedbackTests(unittest.TestCase):
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

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def _pdf(self, name="book.pdf"):
        source = self.root / name
        doc = pymupdf.open()
        for heading, body in (("Capítulo 1", "Primeiro parágrafo."), ("Capítulo 2", "Segundo parágrafo.")):
            page = doc.new_page()
            page.insert_text((72, 80), heading, fontsize=22)
            page.insert_text((72, 130), body, fontsize=11)
        doc.save(source)
        doc.close()
        return source

    def _load_pdf(self, warnings=()):
        self.window._show_workspace("pdf")
        project = analyze_pdf(self._pdf())
        project.warnings = list(warnings)
        self.window._pdf_loaded(project)
        return project

    def _image(self, name="page.png"):
        path = self.root / name
        Image.new("RGB", (40, 60), (30, 0, 0)).save(path)
        return path

    def _drag(self, kind, *paths):
        # The event only borrows the mime data, so it has to outlive this call.
        self.mime = QMimeData()
        self.mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        args = (Qt.DropAction.CopyAction, self.mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        with warnings.catch_warnings():
            # Qt 6 deprecates this constructor but offers no other way to build a drag-enter event.
            warnings.simplefilter("ignore", DeprecationWarning)
            event = QDragEnterEvent(QPointF(4, 4).toPoint(), *args) if kind == "enter" else QDropEvent(QPointF(4, 4), *args)
        event.setAccepted(False)
        return event

    def test_analysis_warnings_have_their_own_strip_at_every_width(self):
        self.window.resize(900, 640)
        self.window.show()
        self._load_pdf(["Páginas com pouco texto detectadas: 2, 3."])
        self.app.processEvents()
        self.assertTrue(self.window.pdf_notice.isVisibleTo(self.window))
        self.assertIn("pouco texto", self.window.pdf_notice_text.text())
        # The side panel keeps only the general tip, which compact layouts may hide.
        self.assertNotIn("pouco texto", self.window.pdf_warning.text())

        self._load_pdf()
        self.assertFalse(self.window.pdf_notice.isVisibleTo(self.window))

    def test_a_filter_with_no_match_explains_itself(self):
        self._load_pdf()
        self.assertEqual(self.window.block_stack.currentIndex(), 0)
        self.window._filter_blocks("Imagem")
        self.assertEqual(self.window.block_stack.currentIndex(), 1)
        self.window._filter_blocks("all")
        self.assertEqual(self.window.block_stack.currentIndex(), 0)

    def test_long_activity_text_is_elided_with_the_full_text_as_tooltip(self):
        self.window.resize(900, 640)
        self.window.show()
        self.window._show_workspace("pdf")
        long_text = "Baixando 3/10 — " + "uma mensagem bem longa " * 20
        self.window._message(long_text)
        self.app.processEvents()
        shown = QLabel.text(self.window.activity)
        self.assertEqual(self.window.activity.text(), long_text)
        self.assertTrue(shown.endswith("…") and len(shown) < len(long_text))
        self.assertEqual(self.window.activity.toolTip(), long_text)
        self.assertLessEqual(self.window.activity.fontMetrics().horizontalAdvance(shown), self.window.activity.width())

    def test_failure_is_styled_apart_and_cleared_by_the_next_success(self):
        self.window._show_workspace("pdf")
        with patch("conversor.gui.QMessageBox.critical"):
            self.window._error("não foi possível converter")
        self.assertEqual(self.window.activity.property("tone"), "failure")
        self.assertTrue(self.window.activity_icon.isVisibleTo(self.window))

        self.window._message("EPUB salvo.", "success")
        self.assertEqual(self.window.activity.property("tone"), "success")
        self.assertIsNone(self.window.failure)
        self.window._message("Pronto.")
        self.assertEqual(self.window.activity.property("tone"), "info")
        self.assertFalse(self.window.activity_icon.isVisibleTo(self.window))

    def test_the_merge_hint_reads_in_full_and_elides_only_when_it_runs_out_of_room(self):
        self.window.resize(1280, 800)
        self.window.show()
        self.window._show_workspace("manga")
        self.window._append_manga_pages([self._image()])
        self.app.processEvents()
        hint = self.window.manga_merge_hint
        self.assertTrue(hint.isVisibleTo(self.window))
        self.assertEqual(hint.text(), "Novas importações somam páginas a esta HQ.")
        # The reported bug: at 1280 the hint shared the buttons row and showed "Novas importaç…".
        self.assertEqual(QLabel.text(hint), hint.text())
        self.assertGreaterEqual(hint.width(), hint.fontMetrics().horizontalAdvance(hint.text()))

        hint.setFixedWidth(90)
        self.app.processEvents()
        shown = QLabel.text(hint)
        self.assertTrue(shown.endswith("…"))
        self.assertLess(len(shown), len(hint.text()))
        self.assertEqual(hint.toolTip(), hint.text())

    def test_switching_modes_retires_the_other_note_but_keeps_tasks_and_warnings(self):
        self._load_pdf()
        self.assertIn("PDF analisado", self.window.activity.text())
        self.window._set_mode("manga")
        self.assertEqual(self.window.activity.text(), "")
        self.assertEqual(self.window.activity.property("tone"), "info")
        self.assertFalse(self.window.activity_icon.isVisibleTo(self.window))

        # A task in flight owns the line: switching modes must not hide its progress or its failure.
        self.window._set_busy(True)
        self.window._message("Analisando PDF...")
        self.window._set_mode("pdf")
        self.assertEqual(self.window.activity.text(), "Analisando PDF...")
        with patch("conversor.gui.QMessageBox.critical"):
            self.window._error("não foi possível converter")
        self.window._set_mode("manga")
        self.assertIn("não foi possível converter", self.window.activity.text())
        self.window._set_busy(False)

        self.window._message("Alguns itens foram ignorados.", "warning")
        self.window._set_mode("pdf")
        self.assertEqual(self.window.activity.text(), "Alguns itens foram ignorados.")

    def test_a_disabled_export_button_says_why(self):
        self.window._show_workspace("pdf")
        self.assertFalse(self.window.export_button.isEnabled())
        self.assertEqual(self.window.export_button.toolTip(), "Importe um PDF para poder exportar.")
        self.window._set_mode("manga")
        self.assertEqual(self.window.export_button.toolTip(), "Adicione páginas para poder exportar.")

        self.window._append_manga_pages([self._image()])
        self.assertIn("Ctrl+S", self.window.export_button.toolTip())
        self.window._set_busy(True)
        self.assertEqual(self.window.export_button.toolTip(), "Aguarde a tarefa atual terminar.")
        self.window._set_busy(False)

        self.window._change_language("en")
        self.app.processEvents()
        self.window._set_busy(True)
        self.assertEqual(self.window.export_button.toolTip(), "Wait for the current task to finish.")
        self.window._set_busy(False)

    def test_icon_only_source_buttons_keep_names_and_tooltips(self):
        self.window.resize(900, 640)
        self.window.show()
        self.window._show_workspace("manga")
        self.app.processEvents()
        buttons = [*self.window.add_buttons, self.window.pdf_import_button, *self.window.tab_buttons.values()]
        for button in buttons:
            self.assertEqual(button.text(), "")
            self.assertTrue(button.toolTip())
            self.assertTrue(button.accessibleName())
        self.assertTrue(self.window.manga_add_group.accessibleName())

    def test_window_geometry_and_place_come_back_and_bad_values_are_ignored(self):
        self.window._show_workspace("manga")
        # The offscreen test screen is small, and Qt keeps restored windows inside it.
        self.window.resize(790, 580)
        self.window.close()

        again = MainWindow(self.settings)
        self.assertEqual((again.width(), again.height()), (790, 580))
        self.assertEqual((again.screen_name, again.mode), ("workspace", "manga"))
        again.close()

        self.settings.setValue("window_geometry", "not geometry")
        self.settings.setValue("last_mode", "bogus")
        fallback = MainWindow(self.settings)
        self.assertEqual((fallback.width(), fallback.height()), (1280, 820))
        self.assertEqual(fallback.mode, "pdf")
        fallback.close()

    def test_shortcuts_follow_the_mode_and_the_busy_state(self):
        self.assertEqual(self.window.shortcut_open.key(), QKeySequence(QKeySequence.StandardKey.Open))
        self.assertEqual(self.window.shortcut_save.key(), QKeySequence(QKeySequence.StandardKey.Save))
        with patch.object(self.window, "_open_pdf") as open_pdf, patch.object(self.window, "_add_images") as add_images:
            self.window._show_workspace("pdf")
            self.window._open_current()
            open_pdf.assert_called_once()
            self.window._show_workspace("manga")
            self.window._open_current()
            add_images.assert_called_once()

        with patch.object(self.window, "_export_current") as export:
            self.window._save_current()
            export.assert_not_called()
            self.window._append_manga_pages([self._image()])
            self.window._save_current()
            export.assert_called_once()

        self.assertFalse(self.window.shortcut_cancel.isEnabled())
        gate = threading.Event()
        self.window._start("Gerando EPUB...", gate.wait, lambda _: None)
        self.assertTrue(self.window.shortcut_cancel.isEnabled())
        with patch.object(self.window, "_open_pdf") as open_pdf:
            self.window._open_current()
            open_pdf.assert_not_called()
        gate.set()
        self.window._retire_tasks()
        self.assertIn("Ctrl+O", self.window.pdf_import_button.toolTip())
        self.assertIn("Esc", self.window.cancel_button.toolTip())

    def test_dragging_unsupported_files_is_refused_with_a_message(self):
        note = self.root / "notes.txt"
        note.write_text("x")
        enter = self._drag("enter", note)
        self.window.dragEnterEvent(enter)
        self.assertFalse(enter.isAccepted())
        self.assertFalse(self.window.drop_overlay.isVisibleTo(self.window))
        self.assertEqual(self.window.activity.property("tone"), "warning")

        for path in (self._pdf(), self._image(), self.root):
            enter = self._drag("enter", path)
            self.window.dragEnterEvent(enter)
            self.assertTrue(enter.isAccepted(), path)
            self.assertTrue(self.window.drop_overlay.isVisibleTo(self.window))
            self.window.dragLeaveEvent(QDragLeaveEvent())
            self.assertFalse(self.window.drop_overlay.isVisibleTo(self.window))

    def test_dropping_several_pdfs_uses_the_first_and_says_so(self):
        first, second = self._pdf("a.pdf"), self._pdf("b.pdf")
        drop = self._drag("drop", first, second)
        with patch.object(self.window, "_analyze_pdf") as analyze:
            self.window.dropEvent(drop)
        analyze.assert_called_once_with(str(first))
        self.assertTrue(drop.isAccepted())
        self.assertIn("Só o primeiro PDF foi usado.", self.window.activity.text())

    def test_dropping_only_unsupported_files_reports_it(self):
        note = self.root / "notes.txt"
        note.write_text("x")
        drop = self._drag("drop", note)
        self.window.dropEvent(drop)
        self.assertFalse(drop.isAccepted())
        self.assertEqual(self.window.activity.text(), "Formato não suportado. Solte um PDF, imagens ou uma pasta.")

    def test_unapplied_edit_is_flagged_and_applied_with_feedback_on_selection_change(self):
        project = self._load_pdf()
        rows = [index for index, block in enumerate(project.blocks) if block.role == "Parágrafo"]
        self.window.block_list.setCurrentItem(self.window.block_items[rows[0]])
        self.assertFalse(self.window.editor_dirty.isVisibleTo(self.window))

        self.window.block_text.setPlainText("Texto corrigido.")
        self.assertTrue(self.window.editor_dirty.isVisibleTo(self.window))
        self.window.block_list.setCurrentItem(self.window.block_items[rows[1]])
        self.assertEqual(project.blocks[rows[0]].text, "Texto corrigido.")
        self.assertEqual(self.window.activity.text(), f"Correção aplicada ao bloco {rows[0] + 1}.")
        self.assertFalse(self.window.editor_dirty.isVisibleTo(self.window))

        self.window._message("Pronto.")
        self.window.block_list.setCurrentItem(self.window.block_items[rows[0]])
        self.assertEqual(self.window.activity.text(), "Pronto.")


if __name__ == "__main__":
    unittest.main()
