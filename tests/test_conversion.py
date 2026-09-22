import tempfile
import io
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from conversor.epub_export import export_manga, export_pdf
from conversor.models import MangaProject
from conversor.pdf_analysis import analyze_pdf
from conversor.web_images import import_images_from_url


class ConversionTests(unittest.TestCase):
    def test_pdf_analysis_and_reflowable_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "book.pdf"
            doc = pymupdf.open()
            for heading, body in [
                ("Capítulo 1", "Primeiro parágrafo de um livro de exemplo."),
                ("Capítulo 2", "Segundo parágrafo de um livro de exemplo."),
            ]:
                page = doc.new_page()
                page.insert_text((72, 80), heading, fontsize=22)
                page.insert_text((72, 130), body, fontsize=11)
            doc.set_metadata({"title": "Livro teste", "author": "Autora teste"})
            doc.save(source)
            doc.close()
            project = analyze_pdf(source)
            self.assertEqual(project.title, "Livro teste")
            self.assertTrue(any(block.role == "Capítulo" for block in project.blocks))
            target = root / "book.epub"
            export_pdf(project, target)
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
                self.assertIn("mimetype", names)
                self.assertTrue(any(name.endswith("nav.xhtml") for name in names))
                text = b" ".join(archive.read(name) for name in names if name.endswith(".xhtml"))
                self.assertIn("Primeiro parágrafo", text.decode("utf-8"))

    def test_manga_fixed_layout_and_reading_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = []
            for index in (1, 2):
                path = root / f"{index:03d}.png"
                Image.new("RGB", (900, 1300), (index * 40, 100, 100)).save(path)
                paths.append(path)
            project = MangaProject(title="HQ teste", pages=paths)
            project.chapter_titles[str(paths[0])] = "Capítulo 1"
            target = root / "comic.epub"
            export_manga(project, target)
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
                self.assertTrue(any(name.endswith("page-0001.xhtml") for name in names))
                package = archive.read("EPUB/content.opf").decode("utf-8")
                self.assertIn("pre-paginated", package)
                self.assertIn('page-progression-direction="rtl"', package)
                self.assertIn("Capítulo 1", archive.read("EPUB/nav.xhtml").decode("utf-8"))

    def test_scanned_page_uses_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = Image.new("RGB", (900, 1300), "white")
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default(size=36)
            draw.text((70, 100), "Capitulo 1", fill="black", font=font)
            draw.text((70, 170), "Este e um paragrafo escaneado para testar o OCR.", fill="black", font=font)
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            doc = pymupdf.open()
            page = doc.new_page(width=450, height=650)
            page.insert_image(page.rect, stream=stream.getvalue())
            source = root / "scan.pdf"
            doc.save(source)
            doc.close()
            project = analyze_pdf(source)
            self.assertEqual(project.scanned_pages, [1])
            self.assertEqual(project.ocr_pages, [1])
            self.assertTrue(any("paragrafo escaneado" in block.text for block in project.blocks))

    def test_public_gallery_import_uses_visible_image_order(self):
        class Response:
            def __init__(self, content_type, content):
                self.headers = {"Content-Type": content_type}
                self.content = content

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def raise_for_status(self):
                pass

            def iter_content(self, _size):
                yield self.content

        class Session:
            def __init__(self, image_data):
                self.headers = {}
                self.image_data = image_data

            def get(self, url, **_kwargs):
                if url.endswith("/chapter"):
                    return Response("text/html", b'<img data-src="/pages/1.png"><img src="/pages/2.png">')
                return Response("image/png", self.image_data)

        with tempfile.TemporaryDirectory() as tmp:
            data = io.BytesIO()
            Image.new("RGB", (400, 600), "white").save(data, format="PNG")
            with patch("conversor.web_images.requests.Session", return_value=Session(data.getvalue())):
                pages = import_images_from_url("https://example.org/chapter", tmp)
            self.assertEqual(len(pages), 2)
            self.assertTrue(all(page.is_file() for page in pages))


if __name__ == "__main__":
    unittest.main()
