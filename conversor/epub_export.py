# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import hashlib
import html
import io
import os
import re
import tempfile
import uuid
import zipfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from ebooklib import epub
from PIL import Image, ImageOps

from .models import Block, MangaProject, PdfProject
from .pdf_analysis import render_page


STYLES = """
body { font-family: serif; line-height: 1.5; margin: 0 4%; }
h1, h2 { line-height: 1.2; break-after: avoid; }
p { margin: 0 0 0.35em; text-indent: 1.2em; }
h1 + p, h2 + p { text-indent: 0; }
figure { margin: 1em 0; text-align: center; }
figure img { max-width: 100%; height: auto; }
aside { font-size: 0.9em; }
p.caption { font-size: 0.9em; text-align: center; text-indent: 0; }
"""

# Fixed-layout pages: no reader margins, so the page image fills the viewport instead of
# being letterboxed inside the reader's own text frame.
PAGE_STYLES = """
html, body { margin: 0; padding: 0; width: 100%; height: 100%; }
body { overflow: hidden; }
img { display: block; width: 100%; height: 100%; object-fit: contain; }
"""


class MangaWriter(epub.EpubWriter):
    """EbookLib writer for fixed-layout comics.

    EbookLib keeps every item content in memory and writes it with ``writestr``, so a long
    comic would hold every page in RAM. Page images are already compressed files on disk, so
    this writer copies them straight into the archive from their path, one at a time.

    It also sets the itemref property EbookLib does not expose through its spine API.
    """

    def __init__(self, name, book, options=None, image_sources=None):
        super().__init__(name, book, options)
        self._image_sources = dict(image_sources or {})

    def _write_opf_spine(self, root, ncx_id):
        super()._write_opf_spine(root, ncx_id)
        spine = root.find("spine")
        for itemref in spine:
            if itemref.get("idref", "").startswith("page-"):
                itemref.set("properties", "rendition:layout-pre-paginated")

    def _write_items(self):
        """Same archive layout as EbookLib, with page images streamed from disk."""
        for item in self.book.get_items():
            if isinstance(item, epub.EpubNcx):
                self.out.writestr(self._archive_name(item.file_name), self._get_ncx())
            elif isinstance(item, epub.EpubNav):
                self.out.writestr(self._archive_name(item.file_name), self._get_nav(item))
            elif item.manifest:
                source = self._image_sources.get(item.file_name)
                if source is None:
                    self.out.writestr(self._archive_name(item.file_name), item.get_content())
                else:
                    self.out.write(source, self._archive_name(item.file_name), compress_type=zipfile.ZIP_STORED)
            else:
                self.out.writestr(item.file_name, item.get_content())

    def _archive_name(self, file_name: str) -> str:
        return f"{self.book.FOLDER_NAME}/{file_name}"


# Characters that are not allowed in XML 1.0 documents, which makes epubcheck reject the file.
_INVALID_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
FALLBACK_TITLE = "Sem título"


def _clean_text(value: str) -> str:
    return _INVALID_XML_CHARS.sub("", value or "")


def _clean_title(value: str, fallback: str = FALLBACK_TITLE) -> str:
    title = " ".join(_clean_text(value or "").split())
    return title or fallback


def _safe_text(value: str) -> str:
    return html.escape(_clean_text(value), quote=False)


def _image_png(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        ImageOps.exif_transpose(image, in_place=True)
        result = io.BytesIO()
        # Transparency has to survive: a cover with a cut-out design would turn black.
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            image.convert("RGBA").save(result, format="PNG", optimize=True)
        else:
            image.convert("RGB").save(result, format="PNG", optimize=True)
        return result.getvalue()


def _base_book(title: str, author: str, language: str) -> epub.EpubBook:
    book = epub.EpubBook()
    book.set_identifier(f"urn:uuid:{uuid.uuid4()}")
    book.set_title(_clean_title(title))
    book.set_language(_clean_title(language, "pt-BR"))
    clean_author = " ".join(_clean_text(author).split())
    if clean_author:
        book.add_author(clean_author)
    return book


def _add_image(book: epub.EpubBook, data: bytes, name: str, cache: dict[bytes, str]) -> str:
    digest = hashlib.sha256(data).digest()
    if digest in cache:
        return cache[digest]
    image = epub.EpubImage()
    image.file_name = f"images/{name}.png"
    image.media_type = "image/png"
    image.content = _image_png(data)
    book.add_item(image)
    cache[digest] = image.file_name
    return image.file_name


def _block_html(book: epub.EpubBook, block: Block, image_number: int, images: dict[bytes, str]) -> str:
    if block.role == "Ignorar":
        return ""
    if block.role == "Imagem" and block.image:
        source = _add_image(book, block.image, f"figure-{image_number:05d}", images)
        return f'<figure><img src="../{source}" alt="Ilustração da página {block.page + 1}"/></figure>'
    text = _clean_text(block.rich_html) if block.rich_html and block.text == block.source_text else _safe_text(block.text.strip())
    if not text:
        return ""
    tag = {"Capítulo": "h1", "Seção": "h2", "Nota": "aside"}.get(block.role, "p")
    css_class = ' class="caption"' if block.role == "Legenda" else ""
    return f"<{tag}{css_class}>{text}</{tag}>"


def _page_role(project: PdfProject, page: int) -> str:
    if not 0 <= page < len(project.page_roles):
        raise ValueError(f"A estrutura do PDF está inconsistente: a página {page + 1} não possui uma função definida.")
    return project.page_roles[page]


def _skipped_cover_page(project: PdfProject) -> int | None:
    """Page whose blocks must stay out of the body because the cover already shows them.

    Cover and front-matter roles keep their previous treatment: only the outer cover leaves
    the reading flow. A Conteúdo page used as the cover, however, would show its text twice
    (inside the cover picture and again in the body), so it is rendered once as the cover.
    """
    role = project.page_roles[project.cover_page] if 0 <= project.cover_page < len(project.page_roles) else None
    if project.custom_cover or role != "Conteúdo":
        return project.cover_page if role == "Capa externa" else None
    has_other_content = any(
        block.page != project.cover_page and block.role != "Ignorar" and (block.text or block.image) for block in project.blocks
    )
    return project.cover_page if has_other_content else None


def _section_groups(project: PdfProject) -> list[tuple[str, list[Block]]]:
    sections: list[tuple[str, list[Block]]] = []
    book_title = _clean_title(project.title)
    current_title = book_title
    current: list[Block] = []
    front_matter = False
    last_page = -1
    skipped_page = _skipped_cover_page(project)
    for block in project.blocks:
        if block.page == skipped_page:
            continue
        role = _page_role(project, block.page)
        if block.page != last_page:
            if role == "Conteúdo":
                if front_matter:
                    if current:
                        sections.append((current_title, current))
                        current = []
                    front_matter = False
                    current_title = book_title
            elif role != "Capa externa":
                if current:
                    sections.append((current_title, current))
                    current = []
                front_matter = True
                current_title = _clean_title(role, book_title)
            last_page = block.page
        if block.role == "Capítulo":
            chapter_title = _clean_title(block.text[:100], "")
            if chapter_title:
                if current:
                    sections.append((current_title, current))
                    current = []
                front_matter = False
                current_title = chapter_title
        if block.role != "Ignorar":
            current.append(block)
    if current:
        sections.append((current_title, current))
    return sections


def _atomic_write(destination: str | Path, write: Callable[[str], object]) -> None:
    target = Path(destination)
    try:
        handle, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    except OSError as exc:
        raise OSError(f"Não foi possível gravar o EPUB em {target}.") from exc
    os.close(handle)
    try:
        write(temp_name)
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(temp_name, 0o666 & ~umask)
        os.replace(temp_name, target)
    except OSError as exc:
        with suppress(OSError):
            os.unlink(temp_name)
        raise OSError(f"Não foi possível gravar o EPUB em {target}. Verifique o espaço em disco e a permissão da pasta.") from exc
    except BaseException:
        with suppress(OSError):
            os.unlink(temp_name)
        raise


def _cover_image(project: PdfProject) -> bytes:
    if project.custom_cover:
        if not project.custom_cover.is_file():
            raise ValueError("A capa personalizada não foi encontrada. Escolha outra imagem ou remova a seleção.")
        return _image_png(project.custom_cover.read_bytes())
    if not project.source.is_file():
        raise ValueError("O PDF de origem não foi encontrado. Analise o arquivo novamente antes de exportar.")
    return render_page(project.source, project.cover_page, width=1100)


def export_pdf(project: PdfProject, destination: str | Path) -> None:
    if not any(b.role != "Ignorar" and (b.text or b.image) for b in project.blocks):
        raise ValueError("Não há conteúdo extraído para exportar. Um PDF escaneado precisa de OCR.")
    book = _base_book(project.title, project.author, project.language)
    book.set_cover("cover.png", _cover_image(project), create_page=False)
    css = epub.EpubItem(uid="style", file_name="styles/book.css", media_type="text/css", content=STYLES)
    book.add_item(css)
    chapters: list[epub.EpubHtml] = []
    image_number = 0
    images: dict[bytes, str] = {}
    for index, (title, blocks) in enumerate(_section_groups(project), 1):
        body = []
        for block in blocks:
            image_number += 1
            body.append(_block_html(book, block, image_number, images))
        if not any(body):
            continue
        chapter = epub.EpubHtml(title=title, file_name=f"text/section-{index:04d}.xhtml", lang=_clean_title(project.language, "pt-BR"))
        chapter.content = "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>{}</title></head><body>{}</body></html>".format(
            _safe_text(title), "\n".join(body)
        )
        chapter.add_link(href="../styles/book.css", rel="stylesheet", type="text/css")
        book.add_item(chapter)
        chapters.append(chapter)
    if not chapters:
        raise ValueError("Nenhuma seção válida foi produzida.")
    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapters]
    _atomic_write(destination, lambda temp: epub.write_epub(temp, book, {"raise_exceptions": True}))


_EXIF_ORIENTATION = 274


@dataclass(frozen=True)
class _MangaPage:
    """One page image ready for the archive: the original file or a normalized copy."""

    source: Path
    extension: str
    media_type: str
    width: int
    height: int


def _manga_page(path: Path, directory: Path, stem: str) -> _MangaPage:
    with Image.open(path) as image:
        orientation = image.getexif().get(_EXIF_ORIENTATION)
        width, height = image.size
        # Without a transform, the file on disk is exactly what goes into the EPUB.
        if orientation in (None, 1):
            if image.format == "PNG":
                return _MangaPage(path, "png", "image/png", width, height)
            if image.format == "JPEG" and image.mode in ("RGB", "L"):
                return _MangaPage(path, "jpg", "image/jpeg", width, height)
        ImageOps.exif_transpose(image, in_place=True)
        width, height = image.size
        if image.format == "PNG":
            destination = directory / f"{stem}.png"
            image.save(destination, format="PNG", optimize=True)
            return _MangaPage(destination, "png", "image/png", width, height)
        if "A" in image.getbands():
            destination = directory / f"{stem}.png"
            image.convert("RGBA").save(destination, format="PNG", optimize=True)
            return _MangaPage(destination, "png", "image/png", width, height)
        # CMYK JPEGs, common in print files, would show inverted colours if stored untouched.
        destination = directory / f"{stem}.jpg"
        image.convert("RGB").save(destination, format="JPEG", quality=94, optimize=True)
        return _MangaPage(destination, "jpg", "image/jpeg", width, height)


def export_manga(project: MangaProject, destination: str | Path) -> None:
    if not project.pages:
        raise ValueError("Adicione páginas antes de exportar.")
    if not 0 <= project.cover_index < len(project.pages):
        raise ValueError("A capa selecionada não existe.")
    if not all(source.is_file() for source in project.pages):
        raise ValueError("Uma página da HQ não foi encontrada no disco. Adicione a imagem novamente antes de exportar.")
    if project.custom_cover and not project.custom_cover.is_file():
        raise ValueError("A capa personalizada não foi encontrada. Escolha outra imagem ou remova a seleção.")
    book = _base_book(project.title, project.author, project.language)
    book.set_direction("rtl" if project.right_to_left else "ltr")
    # Fixed layout: readers must show one page at a time and must not add their own margins.
    book.add_metadata(None, "meta", "pre-paginated", {"property": "rendition:layout"})
    book.add_metadata(None, "meta", "auto", {"property": "rendition:spread"})
    book.add_item(epub.EpubItem(uid="page-style", file_name="styles/page.css", media_type="text/css", content=PAGE_STYLES))
    with tempfile.TemporaryDirectory(prefix="liber-manga-") as directory:
        workdir = Path(directory)
        prepared = [_manga_page(source, workdir, f"page-{index:04d}") for index, source in enumerate(project.pages, 1)]
        if project.custom_cover:
            cover = _manga_page(project.custom_cover, workdir, "cover")
            book.set_cover(f"cover.{cover.extension}", cover.source.read_bytes(), create_page=False)
        pages: list[epub.EpubHtml] = []
        chapter_entries: list[epub.EpubHtml] = []
        image_sources: dict[str, Path] = {}
        cover_item: epub.EpubImage | None = None
        for index, (source, prepared_page) in enumerate(zip(project.pages, prepared), 1):
            file_name = f"images/page-{index:04d}.{prepared_page.extension}"
            image_item = epub.EpubImage(uid=f"image-{index:04d}", file_name=file_name, media_type=prepared_page.media_type)
            if not project.custom_cover and index - 1 == project.cover_index:
                # The cover is this very page: point the manifest at it instead of storing a
                # second copy under cover.*.
                image_item.properties = ["cover-image"]
                cover_item = image_item
            book.add_item(image_item)
            image_sources[file_name] = prepared_page.source
            chapter_title = _clean_title(project.chapter_titles.get(str(source), ""), "")
            page_title = chapter_title or f"Página {index}"
            page = epub.EpubHtml(uid=f"page-{index:04d}", title=page_title, file_name=f"pages/page-{index:04d}.xhtml", lang=_clean_title(project.language, "pt-BR"))
            page.add_meta(name="viewport", content=f"width={prepared_page.width},height={prepared_page.height}")
            page.add_link(href="../styles/page.css", rel="stylesheet", type="text/css")
            page.content = f"<img src='../{file_name}' alt='Página {index}'/>"
            book.add_item(page)
            pages.append(page)
            if chapter_title:
                chapter_entries.append(page)
        if cover_item is not None:
            book.add_metadata(None, "meta", "", {"name": "cover", "content": cover_item.id})
        book.toc = tuple(chapter_entries or pages[:1])
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", *pages]

        def write(temp_name: str) -> None:
            writer = MangaWriter(temp_name, book, {"raise_exceptions": True}, image_sources)
            writer.process()
            writer.write()

        _atomic_write(destination, write)
