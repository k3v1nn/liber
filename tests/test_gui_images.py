# SPDX-License-Identifier: AGPL-3.0-only

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QListWidgetItem

from conversor.gui import _read_oriented_pixmap
from conversor.widgets import THUMBNAIL_CACHE_LIMIT, PAGE_PATH, CoverThumb, PageList, PagePreview, THUMBNAILS


class PreviewImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
                cls.app = QApplication([])

    def test_preview_respects_all_exif_orientations_for_jpeg_and_png(self):
        colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))
        cases = (
            (1, (40, 60), (0, 1, 2, 3)),
            (2, (40, 60), (1, 0, 3, 2)),
            (3, (40, 60), (3, 2, 1, 0)),
            (4, (40, 60), (2, 3, 0, 1)),
            (5, (60, 40), (0, 2, 1, 3)),
            (6, (60, 40), (2, 0, 3, 1)),
            (7, (60, 40), (3, 1, 2, 0)),
            (8, (60, 40), (1, 3, 0, 2)),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for fmt in ("JPEG", "PNG"):
                for orientation, size, order in cases:
                    with self.subTest(format=fmt, orientation=orientation):
                        path = Path(tmp) / f"image.{fmt.lower()}"
                        with Image.new("RGB", (40, 60)) as source:
                            for color, box in zip(colors, (
                                (0, 0, 20, 30), (20, 0, 40, 30),
                                (0, 30, 20, 60), (20, 30, 40, 60),
                            )):
                                source.paste(color, box)
                            exif = Image.Exif()
                            exif[274] = orientation
                            source.save(path, format=fmt, exif=exif)
                        preview = _read_oriented_pixmap(path).toImage()
                        self.assertEqual((preview.width(), preview.height()), size)
                        points = ((5, 5), (size[0] - 6, 5),
                                  (5, size[1] - 6), (size[0] - 6, size[1] - 6))
                        for point, index in zip(points, order):
                            pixel = preview.pixelColor(*point)
                            for actual, expected in zip(
                                (pixel.red(), pixel.green(), pixel.blue()), colors[index],
                            ):
                                self.assertLessEqual(abs(actual - expected), 12)

    def test_rotated_png_preview_preserves_transparency(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transparent.png"
            with Image.new("RGBA", (40, 60), (255, 0, 0, 0)) as source:
                source.paste((0, 0, 255, 128), (0, 30, 20, 60))
                exif = Image.Exif()
                exif[274] = 6
                source.save(path, exif=exif)
            preview = _read_oriented_pixmap(path).toImage()
            self.assertEqual((preview.width(), preview.height()), (60, 40))
            self.assertEqual(preview.pixelColor(5, 5).alpha(), 128)
            self.assertEqual(preview.pixelColor(55, 5).alpha(), 0)

    def test_unreadable_image_returns_empty_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.png"
            path.write_bytes(b"not an image")
            self.assertTrue(_read_oriented_pixmap(path).isNull())
            self.assertTrue(_read_oriented_pixmap(Path(tmp) / "missing.png").isNull())


class ThumbnailPaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
                cls.app = QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "page.png"
        Image.new("RGB", (400, 600), (120, 40, 10)).save(self.path)
        THUMBNAILS.cache.clear()
        THUMBNAILS.pending.clear()

    def tearDown(self):
        deadline = time.monotonic() + 10
        while THUMBNAILS.busy() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
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

    def _view(self):
        view = PageList()
        item = QListWidgetItem("001")
        item.setData(PAGE_PATH, str(self.path))
        view.addItem(item)
        view.resize(320, 240)
        return view

    def test_paint_shows_a_placeholder_before_the_worker_returns(self):
        view = self._view()
        gate = threading.Event()
        started = threading.Event()
        calls = []

        def slow_decode(path, size):
            calls.append(path)
            started.set()
            gate.wait(10)
            image = QImage(size, QImage.Format.Format_RGB32)
            image.fill(QColor("#4a7a3a"))
            return image

        with patch("conversor.widgets._decode_thumbnail", side_effect=slow_decode):
            began = time.monotonic()
            view.grab()
            elapsed = time.monotonic() - began
            # A synchronous decode would have blocked this paint on the gate.
            self.assertLess(elapsed, 1.0, f"paint took {elapsed:.2f}s")
            self.assertTrue(THUMBNAILS.thumb(str(self.path)).isNull())
            self.assertTrue(self._wait(started.is_set))
            self.assertTrue(THUMBNAILS.thumb(str(self.path)).isNull())
            gate.set()
            self.assertTrue(self._wait(lambda: not THUMBNAILS.busy()))
            thumbnail = THUMBNAILS.thumb(str(self.path))
            self.assertFalse(thumbnail.isNull())
            self.assertEqual(thumbnail.width(), 168)
            view.grab()
            self.assertEqual(calls.count(str(self.path)), 1)

        view.deleteLater()
        self.app.processEvents()

    def test_cached_thumbnail_is_never_decoded_again(self):
        view = self._view()
        with patch("conversor.widgets._decode_thumbnail", side_effect=self._image) as first:
            view.grab()
            self.assertTrue(self._wait(lambda: not THUMBNAILS.busy()))
            self.assertEqual(first.call_count, 1)

        with patch("conversor.widgets._decode_thumbnail", side_effect=self._image) as second:
            view.grab()
            self.app.processEvents()
            self.assertEqual(second.call_count, 0)
        view.deleteLater()
        self.app.processEvents()

    def test_cache_is_bounded_and_drops_the_oldest_thumbnails(self):
        for index in range(THUMBNAIL_CACHE_LIMIT + 5):
            THUMBNAILS._store(f"/tmp/page-{index}.png", float(index), QImage())
        self.assertEqual(len(THUMBNAILS.cache), THUMBNAIL_CACHE_LIMIT)
        self.assertNotIn(("/tmp/page-0.png", 0.0), THUMBNAILS.cache)
        self.assertIn((f"/tmp/page-{THUMBNAIL_CACHE_LIMIT + 4}.png", float(THUMBNAIL_CACHE_LIMIT + 4)),
                      THUMBNAILS.cache)

    @staticmethod
    def _image(_path, size):
        image = QImage(size, QImage.Format.Format_RGB32)
        image.fill(QColor("#4a7a3a"))
        return image


class ScaledPreviewTests(unittest.TestCase):
    """Previews must scale once per size instead of on every paint."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
                cls.app = QApplication([])

    def test_page_preview_reuses_the_scaled_pixmap_until_it_is_resized(self):
        preview = PagePreview("vazio")
        preview.resize(300, 420)
        source = QPixmap(200, 300)
        source.fill(QColor("#804020"))
        preview.set_image(source)
        preview.grab()
        first = preview.scaled
        self.assertFalse(first.isNull())

        preview.grab()
        self.assertIs(preview.scaled, first)

        preview.resize(380, 480)
        preview.grab()
        self.assertIsNot(preview.scaled, first)
        preview.deleteLater()

    def test_cover_thumb_reuses_the_cropped_pixmap(self):
        thumb = CoverThumb(QSize(92, 138))
        source = QPixmap(400, 600)
        source.fill(QColor("#305040"))
        thumb.set_image(source)
        thumb.grab()
        first = thumb.scaled
        self.assertFalse(first.isNull())

        thumb.grab()
        self.assertIs(thumb.scaled, first)
        thumb.deleteLater()


if __name__ == "__main__":
    unittest.main()
