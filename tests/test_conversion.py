# SPDX-License-Identifier: AGPL-3.0-only

import tempfile
import io
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path
from xml.etree import ElementTree as ET

import pymupdf
import requests
from PIL import Image, ImageDraw, ImageFont

from conversor.epub_export import export_manga, export_pdf
from conversor.models import Block, MangaProject, PdfProject
from conversor.pdf_analysis import analyze_pdf
from conversor.web_images import import_images_from_url
from conversor.i18n import translate_engine_message
from conversor.comic_pdf import import_comic_pdf


def _save_oriented_image(path, fmt, orientation):
    image = Image.new("RGB", (400, 600))
    for color, box in (
        ((255, 0, 0), (0, 0, 200, 300)),
        ((0, 255, 0), (200, 0, 400, 300)),
        ((0, 0, 255), (0, 300, 200, 600)),
        ((255, 255, 0), (200, 300, 400, 600)),
    ):
        image.paste(color, box)
    exif = Image.Exif()
    exif[274] = orientation
    image.save(path, format=fmt, exif=exif)
    image.close()


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
            cover = root / "cover.png"
            Image.new("RGB", (120, 180), "blue").save(cover)
            project.custom_cover = cover
            target = root / "book.epub"
            export_pdf(project, target)
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
                self.assertIn("mimetype", names)
                self.assertTrue(any(name.endswith("nav.xhtml") for name in names))
                text = b" ".join(archive.read(name) for name in names if name.endswith(".xhtml"))
                self.assertIn("Primeiro parágrafo", text.decode("utf-8"))
                with Image.open(io.BytesIO(archive.read("EPUB/cover.png"))) as image:
                    self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))

    def test_pdf_chapter_titles_in_navigation(self):
        cases = (
            ("starts_with_chapter", [], ["Conteúdo"], 0, []),
            ("ignored_header", [Block(0, "Ignorar", "Cabeçalho")], ["Conteúdo"], 0, []),
            ("external_cover", [Block(0, "Parágrafo", "Capa")], ["Capa externa", "Conteúdo"], 1, []),
            ("introduction", [Block(0, "Parágrafo", "Introdução")], ["Conteúdo"], 0, ["Livro teste"]),
        )
        namespaces = {
            "xhtml": "http://www.w3.org/1999/xhtml",
            "epub": "http://www.idpf.org/2007/ops",
            "ncx": "http://www.daisy.org/z3986/2005/ncx/",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cover = root / "cover.png"
            Image.new("RGB", (120, 180), "blue").save(cover)
            for name, prefix, page_roles, page, initial_titles in cases:
                with self.subTest(name=name):
                    project = PdfProject(
                        source=root / "book.pdf",
                        title="Livro teste",
                        custom_cover=cover,
                        page_roles=page_roles,
                        blocks=prefix + [
                            Block(page, "Capítulo", "Capítulo 1 & início"),
                            Block(page, "Parágrafo", "Primeiro parágrafo."),
                            Block(page, "Capítulo", "Capítulo 2"),
                            Block(page, "Parágrafo", "Segundo parágrafo."),
                        ],
                    )
                    target = root / f"{name}.epub"
                    export_pdf(project, target)
                    with zipfile.ZipFile(target) as archive:
                        nav = ET.fromstring(archive.read("EPUB/nav.xhtml"))
                        links = nav.findall(
                            ".//xhtml:nav[@epub:type='toc']//xhtml:a", namespaces,
                        )
                        expected = initial_titles + ["Capítulo 1 & início", "Capítulo 2"]
                        self.assertEqual([link.text for link in links], expected)
                        ncx = ET.fromstring(archive.read("EPUB/toc.ncx"))
                        self.assertEqual(
                            [node.text for node in ncx.findall(".//ncx:navLabel/ncx:text", namespaces)],
                            expected,
                        )
                        for link in links[len(initial_titles):]:
                            chapter = ET.fromstring(archive.read(f"EPUB/{link.attrib['href']}"))
                            self.assertEqual(chapter.find(".//xhtml:h1", namespaces).text, link.text)

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

    def test_exif_orientation_is_normalized_for_web_import_and_manga_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oriented_jpeg = root / "oriented.jpg"
            mirrored_png = root / "mirrored.png"
            _save_oriented_image(oriented_jpeg, "JPEG", 6)
            _save_oriented_image(mirrored_png, "PNG", 2)
            jpeg_source = oriented_jpeg.read_bytes()
            png_source = mirrored_png.read_bytes()

            class Response:
                def __init__(self, content, url):
                    self.headers = {"Content-Type": "image/jpeg" if content is jpeg_data else "image/png"}
                    self.content = content
                    self.url = url

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def raise_for_status(self):
                    pass

                def iter_content(self, _size):
                    yield self.content

            jpeg_data = jpeg_source
            png_data = png_source

            class Session:
                def __init__(self):
                    self.headers = {}

                def get(self, url, **_kwargs):
                    return Response(jpeg_data if url.endswith("photo.jpg") else png_data, url)

            with patch("conversor.web_images.requests.Session", return_value=Session()):
                imported = import_images_from_url("https://example.org/photo.jpg", root / "imported")
                mirrored = import_images_from_url("https://example.org/mirror.png", root / "mirrored")

            self.assertEqual(len(imported), 1)
            self.assertEqual(len(mirrored), 1)
            with Image.open(imported[0]) as image:
                self.assertEqual(image.size, (600, 400))
                self.assertIsNone(image.getexif().get(274))
                self.assertGreater(image.getpixel((20, 20))[2], 200)
                self.assertGreater(image.getpixel((580, 20))[0], 200)
            with Image.open(mirrored[0]) as image:
                self.assertEqual(image.size, (400, 600))
                self.assertIsNone(image.getexif().get(274))
                self.assertEqual(image.getpixel((20, 20)), (0, 255, 0))
                self.assertEqual(image.getpixel((380, 20)), (255, 0, 0))
            self.assertEqual(oriented_jpeg.read_bytes(), jpeg_source)
            self.assertEqual(mirrored_png.read_bytes(), png_source)

            epub_path = root / "comic.epub"
            export_manga(MangaProject(title="EXIF", pages=[imported[0], mirrored[0]]), epub_path)
            with zipfile.ZipFile(epub_path) as archive:
                with Image.open(io.BytesIO(archive.read("EPUB/images/page-0001.png"))) as page:
                    self.assertEqual(page.size, (600, 400))
                    self.assertIsNone(page.getexif().get(274))
                    self.assertGreater(page.getpixel((20, 20))[2], 200)
                with Image.open(io.BytesIO(archive.read("EPUB/images/page-0002.png"))) as page:
                    self.assertEqual(page.size, (400, 600))
                    self.assertIsNone(page.getexif().get(274))
                    self.assertEqual(page.getpixel((20, 20)), (0, 255, 0))
                    self.assertEqual(page.getpixel((380, 20)), (255, 0, 0))
                page_xhtml = ET.fromstring(archive.read("EPUB/pages/page-0001.xhtml"))
                viewport = page_xhtml.find(".//{*}meta[@name='viewport']")
                self.assertEqual(viewport.attrib["content"], "width=600,height=400")
                second_page = ET.fromstring(archive.read("EPUB/pages/page-0002.xhtml"))
                second_viewport = second_page.find(".//{*}meta[@name='viewport']")
                self.assertEqual(second_viewport.attrib["content"], "width=400,height=600")
            self.assertEqual(oriented_jpeg.read_bytes(), jpeg_source)

    def test_oriented_manga_jpeg_and_custom_pdf_cover_keep_image_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "oriented.jpg"
            _save_oriented_image(source, "JPEG", 6)
            original = source.read_bytes()

            manga_path = root / "manga.epub"
            export_manga(MangaProject(title="JPEG EXIF", pages=[source]), manga_path)
            with zipfile.ZipFile(manga_path) as archive:
                self.assertIn("EPUB/cover.jpg", archive.namelist())
                with Image.open(io.BytesIO(archive.read("EPUB/cover.jpg"))) as cover:
                    self.assertEqual(cover.format, "JPEG")
                    self.assertEqual(cover.size, (600, 400))
                    self.assertIsNone(cover.getexif().get(274))
                    self.assertGreater(cover.getpixel((20, 20))[2], 200)
                page = ET.fromstring(archive.read("EPUB/pages/page-0001.xhtml"))
                self.assertEqual(page.find(".//{*}meta[@name='viewport']").attrib["content"], "width=600,height=400")

            pdf_path = root / "pdf.epub"
            project = PdfProject(
                source=root / "unused.pdf",
                title="Capa EXIF",
                blocks=[Block(0, "Parágrafo", "Conteúdo")],
                page_roles=["Conteúdo"],
                custom_cover=source,
            )
            export_pdf(project, pdf_path)
            with zipfile.ZipFile(pdf_path) as archive:
                with Image.open(io.BytesIO(archive.read("EPUB/cover.png"))) as cover:
                    self.assertEqual(cover.size, (600, 400))
                    self.assertIsNone(cover.getexif().get(274))
                    self.assertGreater(cover.getpixel((20, 20))[2], 200)
            self.assertEqual(source.read_bytes(), original)

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
            def __init__(self, content_type, content, url):
                self.headers = {"Content-Type": content_type}
                self.content = content
                self.url = url

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
                    return Response("text/html", b'<img data-src="/pages/1.png"><img src="/pages/2.png">', url)
                return Response("image/png", self.image_data, url)

        with tempfile.TemporaryDirectory() as tmp:
            data = io.BytesIO()
            Image.new("RGB", (400, 600), "white").save(data, format="PNG")
            with patch("conversor.web_images.requests.Session", return_value=Session(data.getvalue())):
                pages = import_images_from_url("https://example.org/chapter", tmp)
            self.assertEqual(len(pages), 2)
            self.assertTrue(all(page.is_file() for page in pages))

    def test_redirected_gallery_resolves_relative_images_from_final_url(self):
        def response(url, content_type, content, status=200):
            result = requests.Response()
            result.url = url
            result.status_code = status
            result.headers["Content-Type"] = content_type
            result._content = content
            result._content_consumed = True
            return result

        original_url = "https://example.org/start"
        final_url = "https://gallery.example.org/books/chapter/"
        responses = {
            original_url: response(
                final_url, "text/html",
                b'<img src="../images/red.png"><img src="/images/blue.png">',
            ),
        }
        for url, color in (
            ("https://gallery.example.org/books/images/red.png", "red"),
            ("https://gallery.example.org/images/blue.png", "blue"),
        ):
            data = io.BytesIO()
            Image.new("RGB", (400, 600), color).save(data, format="PNG")
            responses[url] = response(url, "image/png", data.getvalue())

        def get(url, **_kwargs):
            return responses.get(url) or response(url, "text/plain", b"Not found", 404)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("conversor.web_images.requests.Session.get", side_effect=get):
                pages = import_images_from_url(original_url, tmp)
            self.assertEqual([page.name for page in pages], ["page-0001.png", "page-0002.png"])
            with Image.open(pages[0]) as first, Image.open(pages[1]) as second:
                self.assertEqual(first.getpixel((0, 0)), (255, 0, 0))
                self.assertEqual(second.getpixel((0, 0)), (0, 0, 255))

    def test_custom_cover_is_exported_without_adding_a_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cover = root / "cover.png"
            Image.new("RGB", (120, 180), "blue").save(cover)
            page = root / "page.png"
            Image.new("RGB", (120, 180), "red").save(page)
            project = MangaProject(title="Cover test", pages=[page], custom_cover=cover)
            target = root / "comic.epub"
            export_manga(project, target)
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
                self.assertEqual(len([name for name in names if name.endswith(".xhtml") and "/pages/" in name]), 1)
                with Image.open(io.BytesIO(archive.read("EPUB/cover.png"))) as image:
                    self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))

    def test_comic_pdf_pages_keep_their_order_in_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "comic.pdf"
            document = pymupdf.open()
            for color in ((1, 0, 0), (0, 0, 1)):
                page = document.new_page(width=120, height=180)
                page.draw_rect(page.rect, fill=color, color=None)
            document.save(source)
            document.close()
            pages = import_comic_pdf(source, root / "pages", longest_edge=360)
            self.assertEqual([page.name for page in pages], ["page-00001.png", "page-00002.png"])
            with Image.open(pages[0]) as first, Image.open(pages[1]) as second:
                self.assertEqual(first.getpixel((100, 100)), (255, 0, 0))
                self.assertEqual(second.getpixel((100, 100)), (0, 0, 255))
            target = root / "comic.epub"
            export_manga(MangaProject(title="Comic", pages=pages), target)
            with zipfile.ZipFile(target) as archive:
                self.assertIn("EPUB/pages/page-0001.xhtml", archive.namelist())
                self.assertIn("EPUB/pages/page-0002.xhtml", archive.namelist())

    def test_engine_messages_have_english_translation(self):
        self.assertEqual(translate_engine_message("O PDF está protegido por senha.", "en"), "The PDF is password protected.")


if __name__ == "__main__":
    unittest.main()
