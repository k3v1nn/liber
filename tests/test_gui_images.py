# SPDX-License-Identifier: AGPL-3.0-only

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtWidgets import QApplication

from conversor.gui import _read_oriented_pixmap


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


if __name__ == "__main__":
    unittest.main()
