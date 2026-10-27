# SPDX-License-Identifier: AGPL-3.0-only

import gc
import io
import os
import shutil
import subprocess
import tempfile
import tracemalloc
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
from conversor.pdf_analysis import _guess_page_role, _reading_order, _tessdata_candidates, analyze_pdf
from conversor.web_images import import_images_from_urls
from conversor.i18n import translate_engine_message
from conversor.comic_pdf import import_comic_pdf


NAMESPACES = {
    "xhtml": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "opf": "http://www.idpf.org/2007/opf",
}


def _toc_links(archive):
    nav = ET.fromstring(archive.read("EPUB/nav.xhtml"))
    return nav.findall(".//xhtml:nav[@epub:type='toc']//xhtml:a", NAMESPACES)


def _cover_file(root):
    cover = root / "cover.png"
    Image.new("RGB", (120, 180), "blue").save(cover)
    return cover


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
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cover = _cover_file(root)
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
                        links = _toc_links(archive)
                        expected = initial_titles + ["Capítulo 1 & início", "Capítulo 2"]
                        self.assertEqual([link.text for link in links], expected)
                        ncx = ET.fromstring(archive.read("EPUB/toc.ncx"))
                        self.assertEqual(
                            [node.text for node in ncx.findall(".//ncx:navLabel/ncx:text", NAMESPACES)],
                            expected,
                        )
                        for link in links[len(initial_titles):]:
                            chapter = ET.fromstring(archive.read(f"EPUB/{link.attrib['href']}"))
                            self.assertEqual(chapter.find(".//xhtml:h1", NAMESPACES).text, link.text)

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
                self.assertTrue(any(name.endswith("page-0001.xhtml") for name in archive.namelist()))
                first = archive.infolist()[0]
                self.assertEqual((first.filename, first.compress_type), ("mimetype", zipfile.ZIP_STORED))
                package = ET.fromstring(archive.read("EPUB/content.opf"))
                metadata = {
                    item.get("property"): item.text
                    for item in package.findall(".//opf:metadata/opf:meta", NAMESPACES)
                    if item.get("property")
                }
                self.assertEqual(metadata["rendition:layout"], "pre-paginated")
                self.assertEqual(metadata["rendition:spread"], "auto")
                spine = package.find("opf:spine", NAMESPACES)
                self.assertEqual(spine.get("page-progression-direction"), "rtl")
                self.assertEqual(
                    [ref.get("idref") for ref in spine.findall("opf:itemref", NAMESPACES)],
                    ["nav", "page-0001", "page-0002"],
                )
                page_refs = [ref for ref in spine.findall("opf:itemref", NAMESPACES) if ref.get("idref", "").startswith("page-")]
                self.assertEqual([ref.get("properties") for ref in page_refs], ["rendition:layout-pre-paginated"] * 2)
                self.assertIsNotNone(package.find(".//opf:manifest/opf:item[@href='styles/page.css']", NAMESPACES))
                page_css = archive.read("EPUB/styles/page.css").decode("utf-8")
                self.assertIn("html, body { margin: 0; padding: 0;", page_css)
                page = ET.fromstring(archive.read("EPUB/pages/page-0001.xhtml"))
                self.assertEqual(page.find(".//xhtml:head/xhtml:link", NAMESPACES).get("href"), "../styles/page.css")
                self.assertIsNotNone(page.find(".//xhtml:body/xhtml:img", NAMESPACES))
                self.assertIn("Capítulo 1", archive.read("EPUB/nav.xhtml").decode("utf-8"))

    def test_exif_orientation_is_normalized_at_import_for_jpeg_and_at_export_for_png(self):
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

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def get(self, url, **_kwargs):
                    return Response(jpeg_data if url.endswith("photo.jpg") else png_data, url)

            with patch("conversor.web_images.requests.Session", return_value=Session()):
                imported = import_images_from_urls(["https://example.org/photo.jpg"], root / "imported")[0].paths
                mirrored = import_images_from_urls(["https://example.org/mirror.png"], root / "mirrored")[0].paths

            self.assertEqual(len(imported), 1)
            self.assertEqual(len(mirrored), 1)
            with Image.open(imported[0]) as image:
                self.assertEqual(image.size, (600, 400))
                self.assertIsNone(image.getexif().get(274))
                self.assertGreater(image.getpixel((20, 20))[2], 200)
                self.assertGreater(image.getpixel((580, 20))[0], 200)
            # PNG orientation is applied when the file is read, so the download keeps its bytes.
            self.assertEqual(mirrored[0].read_bytes(), png_source)
            with Image.open(mirrored[0]) as image:
                self.assertEqual(image.size, (400, 600))
                self.assertEqual(image.getexif().get(274), 2)
                self.assertEqual(image.getpixel((20, 20)), (255, 0, 0))
                self.assertEqual(image.getpixel((380, 20)), (0, 255, 0))
            self.assertEqual(oriented_jpeg.read_bytes(), jpeg_source)
            self.assertEqual(mirrored_png.read_bytes(), png_source)

            epub_path = root / "comic.epub"
            export_manga(MangaProject(title="EXIF", pages=[imported[0], mirrored[0]]), epub_path)
            with zipfile.ZipFile(epub_path) as archive:
                with Image.open(io.BytesIO(archive.read("EPUB/images/page-0001.jpg"))) as page:
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
                package = ET.fromstring(archive.read("EPUB/content.opf"))
                manifest = {item.get("href"): item for item in package.findall(".//opf:manifest/opf:item", NAMESPACES)}
                # The chosen cover page is the page itself, so no second copy is stored.
                self.assertNotIn("cover.jpg", manifest)
                cover_item = manifest["images/page-0001.jpg"]
                self.assertEqual(cover_item.get("properties"), "cover-image")
                meta = {
                    item.get("name"): item.get("content")
                    for item in package.findall(".//opf:metadata/opf:meta", NAMESPACES)
                    if item.get("name")
                }
                self.assertEqual(meta["cover"], cover_item.get("id"))
                with Image.open(io.BytesIO(archive.read("EPUB/images/page-0001.jpg"))) as cover:
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

    def test_text_light_vector_page_is_not_flagged_as_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = io.BytesIO()
            Image.new("RGB", (80, 80), "black").save(logo, format="PNG")
            doc = pymupdf.open()
            poem = doc.new_page(width=450, height=650)
            poem.insert_text((72, 120), "Eu canto", fontsize=12)
            divider = doc.new_page(width=450, height=650)
            divider.insert_text((72, 120), "Parte II", fontsize=12)
            divider.insert_image(pymupdf.Rect(72, 200, 132, 260), stream=logo.getvalue())
            source = root / "poem.pdf"
            doc.save(source)
            doc.close()
            project = analyze_pdf(source)
            self.assertEqual(project.scanned_pages, [])
            self.assertEqual(project.ocr_pages, [])

    def test_reading_order_keeps_wide_blocks_as_section_breaks(self):
        width = 600.0
        blocks = [
            Block(0, "Parágrafo", "Título largo", (40, 10, 560, 40), 18),
            Block(0, "Parágrafo", "Esquerda 1", (40, 60, 280, 200), 11),
            Block(0, "Parágrafo", "Direita 1", (330, 60, 560, 200), 11),
            Block(0, "Parágrafo", "Seção larga", (40, 220, 560, 250), 16),
            Block(0, "Parágrafo", "Esquerda 2", (40, 280, 280, 420), 11),
            Block(0, "Parágrafo", "Direita 2", (330, 280, 560, 420), 11),
            Block(0, "Imagem", "", (40, 440, 560, 600), 0),
        ]
        ordered = _reading_order(blocks, width)
        self.assertEqual(
            [block.text or "imagem" for block in ordered],
            ["Título largo", "Esquerda 1", "Direita 1", "Seção larga", "Esquerda 2", "Direita 2", "imagem"],
        )
        self.assertIs(ordered[0], blocks[0])
        self.assertIs(ordered[4], blocks[4])

    def test_page_role_detection_prefers_specific_labels(self):
        cases = (
            ("índice remissivo em página inicial", 6, "Índice remissivo Acontecimentos 120", ["Índice remissivo", "Acontecimentos 120"], "Índice remissivo"),
            ("bibliografia", 16, "Bibliografia ALMEIDA, M. 2020", ["Bibliografia", "ALMEIDA, M. 2020"], "Bibliografia"),
            ("sumário", 3, "Sumário Capítulo 1 5", ["Sumário", "Capítulo 1 5"], "Sumário"),
            ("índice como título isolado", 3, "Índice A 1 B 9", ["Índice", "A 1 B 9"], "Sumário"),
            ("conteúdo em prosa", 6, "Este capítulo apresenta o conteúdo principal da obra.", ["Este capítulo apresenta o conteúdo principal da obra."], "Conteúdo"),
        )
        for name, page, text, headlines, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(_guess_page_role(page, text, 0.0, 100.0, headlines), expected)

    def test_tessdata_candidates_include_platform_locations(self):
        with patch.dict(os.environ, {"TESSDATA_PREFIX": "/opt/tess"}):
            candidates = [str(path) for path in _tessdata_candidates()]
        self.assertIn("/opt/tess", candidates)
        self.assertIn("/opt/tess/tessdata", candidates)
        self.assertIn("/opt/homebrew/share/tessdata", candidates)
        self.assertIn(r"C:\Program Files\Tesseract-OCR\tessdata", candidates)

    def test_repeated_embedded_images_are_stored_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = io.BytesIO()
            Image.new("RGB", (120, 120), (10, 200, 30)).save(logo, format="PNG")
            doc = pymupdf.open()
            for _ in range(2):
                page = doc.new_page(width=450, height=650)
                page.insert_text((72, 100), "Um parágrafo de corpo com texto suficiente.", fontsize=11)
                page.insert_image(pymupdf.Rect(72, 220, 300, 380), stream=logo.getvalue())
            source = root / "book.pdf"
            doc.save(source)
            doc.close()
            project = analyze_pdf(source)
            images = [block for block in project.blocks if block.role == "Imagem"]
            self.assertEqual(len(images), 2)
            self.assertIs(images[0].image, images[1].image)
            project.custom_cover = _cover_file(root)
            target = root / "book.epub"
            export_pdf(project, target)
            with zipfile.ZipFile(target) as archive:
                figures = [name for name in archive.namelist() if name.startswith("EPUB/images/")]
                self.assertEqual(len(figures), 1)
                references = set()
                for name in archive.namelist():
                    if name.endswith(".xhtml"):
                        references.update(
                            node.get("src") for node in ET.fromstring(archive.read(name)).findall(".//xhtml:img", NAMESPACES)
                        )
                self.assertEqual(references, {"../images/figure-00002.png"})

    def test_rendered_cover_page_is_not_repeated_in_the_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = pymupdf.open()
            doc.new_page().insert_text((72, 100), "Texto exclusivo da página de capa", fontsize=12)
            doc.new_page().insert_text((72, 100), "Texto do corpo do livro", fontsize=12)
            source = root / "book.pdf"
            doc.save(source)
            doc.close()
            project = PdfProject(
                source=source,
                title="Livro",
                blocks=[Block(0, "Parágrafo", "Texto exclusivo da página de capa"), Block(1, "Parágrafo", "Texto do corpo do livro")],
                page_roles=["Conteúdo", "Conteúdo"],
            )
            target = root / "book.epub"
            export_pdf(project, target)
            with zipfile.ZipFile(target) as archive:
                self.assertIn("EPUB/cover.png", archive.namelist())
                self.assertEqual([name for name in archive.namelist() if name.startswith("EPUB/images/")], [])
                body = " ".join(
                    "".join(ET.fromstring(archive.read(name)).itertext())
                    for name in archive.namelist() if name.startswith("EPUB/text/")
                )
                self.assertNotIn("página de capa", body)
                self.assertIn("Texto do corpo do livro", body)
            # Front-matter roles keep their previous place in the body.
            project.page_roles = ["Folha de rosto", "Conteúdo"]
            front_target = root / "front.epub"
            export_pdf(project, front_target)
            with zipfile.ZipFile(front_target) as archive:
                body = " ".join(
                    "".join(ET.fromstring(archive.read(name)).itertext())
                    for name in archive.namelist() if name.startswith("EPUB/text/")
                )
                self.assertIn("página de capa", body)

    def test_public_gallery_import_uses_visible_image_order(self):
        class Response:
            status_code = 200

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

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def get(self, url, **_kwargs):
                if url.endswith("/chapter"):
                    return Response("text/html", b'<img data-src="/pages/1.png"><img src="/pages/2.png">', url)
                return Response("image/png", self.image_data, url)

        with tempfile.TemporaryDirectory() as tmp:
            data = io.BytesIO()
            Image.new("RGB", (400, 600), "white").save(data, format="PNG")
            with patch("conversor.web_images.requests.Session", return_value=Session(data.getvalue())):
                report = import_images_from_urls(["https://example.org/chapter"], tmp)[0]
            pages = report.paths
            self.assertEqual([page.name for page in pages], ["page-0001.png", "page-0002.png"])
            self.assertEqual({page.parent.name for page in pages}, {"source-01"})
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
                pages = import_images_from_urls([original_url], tmp)[0].paths
            self.assertEqual([page.name for page in pages], ["page-0001.png", "page-0002.png"])
            self.assertEqual({page.parent.name for page in pages}, {"source-01"})
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

    def test_manga_streams_pages_from_disk_instead_of_holding_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages = []
            for index in range(1, 41):
                path = root / f"{index:03d}.png"
                Image.frombytes("RGB", (200, 300), os.urandom(200 * 300 * 3)).save(path)
                pages.append(path)
            total = sum(page.stat().st_size for page in pages)
            written = []
            original = zipfile.ZipFile.writestr

            def record(archive, name, data, *args, **kwargs):
                written.append((str(name), len(data)))
                return original(archive, name, data, *args, **kwargs)

            gc.collect()
            with patch.object(zipfile.ZipFile, "writestr", record):
                tracemalloc.start()
                try:
                    target = root / "comic.epub"
                    export_manga(MangaProject(title="Memória", pages=pages), target)
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
            # Page bytes never pass through Python as a whole-book buffer.
            self.assertEqual([name for name, _ in written if name.startswith("EPUB/images/")], [])
            self.assertLess(peak, total // 3)
            with zipfile.ZipFile(target) as archive:
                for index, page in enumerate(pages, 1):
                    info = archive.getinfo(f"EPUB/images/page-{index:04d}.png")
                    self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                    self.assertEqual(archive.read(info), page.read_bytes())

    def test_untouched_pages_are_copied_without_reencoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            png = root / "page.png"
            Image.new("RGBA", (120, 180), (10, 20, 30, 128)).save(png)
            jpeg = root / "page.jpg"
            Image.new("RGB", (130, 190), (40, 50, 60)).save(jpeg, quality=85)
            target = root / "comic.epub"
            export_manga(MangaProject(title="Cópia", pages=[png, jpeg]), target)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.read("EPUB/images/page-0001.png"), png.read_bytes())
                self.assertEqual(archive.read("EPUB/images/page-0002.jpg"), jpeg.read_bytes())
                page = ET.fromstring(archive.read("EPUB/pages/page-0001.xhtml"))
                self.assertEqual(page.find(".//{*}meta[@name='viewport']").attrib["content"], "width=120,height=180")

    def test_cmyk_jpeg_page_is_converted_to_rgb(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "print.jpg"
            Image.new("CMYK", (300, 400), (0, 0, 0, 0)).save(source, format="JPEG")
            target = root / "comic.epub"
            export_manga(MangaProject(title="CMYK", pages=[source]), target)
            with zipfile.ZipFile(target) as archive:
                with Image.open(io.BytesIO(archive.read("EPUB/images/page-0001.jpg"))) as page:
                    self.assertEqual(page.format, "JPEG")
                    self.assertEqual(page.mode, "RGB")
                    self.assertEqual(page.size, (300, 400))
                    self.assertGreater(page.getpixel((10, 10))[0], 240)

    def test_transparent_custom_cover_keeps_its_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cover = root / "cover.png"
            image = Image.new("RGBA", (120, 180), (0, 0, 0, 0))
            image.paste((255, 0, 0, 255), (30, 30, 90, 150))
            image.save(cover)
            project = PdfProject(
                source=root / "unused.pdf",
                title="Capa transparente",
                blocks=[Block(0, "Parágrafo", "Conteúdo")],
                page_roles=["Conteúdo"],
                custom_cover=cover,
            )
            target = root / "book.epub"
            export_pdf(project, target)
            with zipfile.ZipFile(target) as archive:
                with Image.open(io.BytesIO(archive.read("EPUB/cover.png"))) as exported:
                    self.assertEqual(exported.mode, "RGBA")
                    self.assertEqual(exported.getpixel((0, 0))[3], 0)
                    self.assertEqual(exported.getpixel((60, 90)), (255, 0, 0, 255))

    def test_missing_manga_page_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page = root / "page.png"
            Image.new("RGB", (120, 180), "red").save(page)
            target = root / "comic.epub"
            message = "Uma página da HQ não foi encontrada no disco. Adicione a imagem novamente antes de exportar."
            with self.assertRaises(ValueError) as caught:
                export_manga(MangaProject(title="Sumiu", pages=[page, root / "sumiu.png"]), target)
            self.assertEqual(str(caught.exception), message)
            self.assertEqual(translate_engine_message(message, "en"), "One comic page was not found on disk. Add the image again before exporting.")
            with self.assertRaises(ValueError) as caught:
                export_manga(MangaProject(title="Capa", pages=[page], custom_cover=root / "sumiu.png"), target)
            self.assertIn("capa personalizada", str(caught.exception).lower())
            self.assertFalse(target.exists())

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

    def test_comic_pdf_pages_render_to_the_target_edge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            document = pymupdf.open()
            document.new_page(width=120, height=180)
            document.new_page(width=1200, height=1800)
            source = root / "comic.pdf"
            document.save(source)
            document.close()
            pages = import_comic_pdf(source, root / "pages", longest_edge=600)
            for page in pages:
                with Image.open(page) as image:
                    self.assertEqual(max(image.size), 600)

    def _assert_epubcheck_ok(self, target):
        executable = shutil.which("epubcheck")
        if executable is None:
            return
        result = subprocess.run([executable, str(target)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_failed_export_keeps_previous_file_and_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cover = _cover_file(root)
            project = PdfProject(
                source=root / "book.pdf",
                title="Livro teste",
                custom_cover=cover,
                page_roles=["Conteúdo"],
                blocks=[Block(0, "Parágrafo", "Primeiro parágrafo.")],
            )
            target = root / "book.epub"
            target.write_bytes(b"EPUB anterior")
            with patch("ebooklib.epub.EpubWriter._write_opf", side_effect=OSError("disco cheio")):
                with self.assertRaises(OSError) as caught:
                    export_pdf(project, target)
                self.assertIn("Não foi possível gravar o EPUB", str(caught.exception))
                with self.assertRaises(OSError):
                    export_pdf(project, root / "novo.epub")
            self.assertEqual(target.read_bytes(), b"EPUB anterior")
            self.assertFalse((root / "novo.epub").exists())
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["book.epub", "cover.png"])

    def test_empty_titles_export_a_valid_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = PdfProject(
                source=root / "book.pdf",
                title="   ",
                author="  ",
                custom_cover=_cover_file(root),
                page_roles=["Conteúdo"],
                blocks=[
                    Block(0, "Capítulo", " \n "),
                    Block(0, "Parágrafo", "Primeiro parágrafo."),
                    Block(0, "Capítulo", "Capítulo real"),
                    Block(0, "Parágrafo", "Segundo parágrafo."),
                ],
            )
            target = root / "book.epub"
            export_pdf(project, target)
            with zipfile.ZipFile(target) as archive:
                links = _toc_links(archive)
                self.assertEqual([link.text for link in links], ["Sem título", "Capítulo real"])
                package = ET.fromstring(archive.read("EPUB/content.opf"))
                self.assertEqual(package.findtext(".//dc:title", namespaces=NAMESPACES), "Sem título")
                self.assertIsNone(package.findtext(".//dc:creator", namespaces=NAMESPACES))
                for link in links:
                    chapter = ET.fromstring(archive.read(f"EPUB/{link.attrib['href']}"))
                    self.assertEqual(chapter.findtext(".//xhtml:head/xhtml:title", namespaces=NAMESPACES), link.text)
                ncx = ET.fromstring(archive.read("EPUB/toc.ncx"))
                self.assertEqual(
                    [node.text for node in ncx.findall(".//ncx:navLabel/ncx:text", NAMESPACES)],
                    ["Sem título", "Capítulo real"],
                )
            self._assert_epubcheck_ok(target)

    def test_front_matter_role_resets_the_section_title(self):
        cases = (
            ("with_body", [Block(1, "Parágrafo", "Texto da capa interna.")], ["Livro teste", "Capa interna", "Livro teste"]),
            ("without_visible_block", [Block(1, "Ignorar", "Cabeçalho")], ["Livro teste", "Livro teste"]),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cover = _cover_file(root)
            for name, middle_blocks, expected in cases:
                with self.subTest(name=name):
                    project = PdfProject(
                        source=root / "book.pdf",
                        title="Livro teste",
                        custom_cover=cover,
                        page_roles=["Conteúdo", "Capa interna", "Conteúdo"],
                        blocks=[Block(0, "Parágrafo", "Primeiro parágrafo."), *middle_blocks, Block(2, "Parágrafo", "Texto do corpo.")],
                    )
                    target = root / f"{name}.epub"
                    export_pdf(project, target)
                    with zipfile.ZipFile(target) as archive:
                        links = _toc_links(archive)
                        self.assertEqual([link.text for link in links], expected)
                        last = ET.fromstring(archive.read(f"EPUB/{links[-1].attrib['href']}"))
                        self.assertIn("Texto do corpo.", "".join(last.itertext()))
                        if middle_blocks[0].role != "Ignorar":
                            middle = ET.fromstring(archive.read(f"EPUB/{links[1].attrib['href']}"))
                            self.assertIn("Texto da capa interna.", "".join(middle.itertext()))
                            self.assertNotIn("Texto do corpo.", "".join(middle.itertext()))

    def test_control_characters_are_stripped_from_titles_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = PdfProject(
                source=root / "book.pdf",
                title="Livro\x00 de\x01 teste",
                author="Autora\x02 teste",
                language="pt-BR\x00",
                custom_cover=_cover_file(root),
                page_roles=["Conteúdo"],
                blocks=[
                    Block(0, "Capítulo", "Capítulo\x0b 1"),
                    Block(0, "Parágrafo", "Texto\x00 do parágrafo."),
                ],
            )
            target = root / "book.epub"
            export_pdf(project, target)
            with zipfile.ZipFile(target) as archive:
                links = _toc_links(archive)
                self.assertEqual([link.text for link in links], ["Capítulo 1"])
                package = ET.fromstring(archive.read("EPUB/content.opf"))
                self.assertEqual(package.findtext(".//dc:title", namespaces=NAMESPACES), "Livro de teste")
                self.assertEqual(package.findtext(".//dc:creator", namespaces=NAMESPACES), "Autora teste")
                self.assertEqual(package.find(".//dc:language", NAMESPACES).text, "pt-BR")
                for name in archive.namelist():
                    if name.endswith((".xhtml", ".opf", ".ncx")):
                        self.assertNotIn(b"\x00", archive.read(name))
                        ET.fromstring(archive.read(name))
            self._assert_epubcheck_ok(target)

    def test_missing_page_role_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = PdfProject(
                source=root / "book.pdf",
                title="Livro teste",
                custom_cover=_cover_file(root),
                page_roles=["Conteúdo"],
                blocks=[Block(1, "Parágrafo", "Texto sem função de página.")],
            )
            target = root / "book.epub"
            with self.assertRaises(ValueError) as caught:
                export_pdf(project, target)
            self.assertEqual(
                str(caught.exception),
                "A estrutura do PDF está inconsistente: a página 2 não possui uma função definida.",
            )
            self.assertFalse(target.exists())

    def test_missing_cover_or_source_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing_cover = PdfProject(
                source=root / "book.pdf",
                title="Livro teste",
                custom_cover=root / "nao-existe.png",
                page_roles=["Conteúdo"],
                blocks=[Block(0, "Parágrafo", "Primeiro parágrafo.")],
            )
            with self.assertRaises(ValueError) as caught:
                export_pdf(missing_cover, root / "a.epub")
            self.assertIn("capa personalizada", str(caught.exception).lower())
            missing_source = PdfProject(
                source=root / "nao-existe.pdf",
                title="Livro teste",
                page_roles=["Conteúdo"],
                blocks=[Block(0, "Parágrafo", "Primeiro parágrafo.")],
            )
            with self.assertRaises(ValueError) as caught:
                export_pdf(missing_source, root / "b.epub")
            self.assertIn("pdf de origem", str(caught.exception).lower())
            self.assertFalse((root / "a.epub").exists())
            self.assertFalse((root / "b.epub").exists())

    def test_engine_messages_have_english_translation(self):
        self.assertEqual(translate_engine_message("O PDF está protegido por senha.", "en"), "The PDF is password protected.")


if __name__ == "__main__":
    unittest.main()
