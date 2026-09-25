# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import html
import io
import uuid
from pathlib import Path

from ebooklib import epub
from PIL import Image

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


class MangaWriter(epub.EpubWriter):
    """EbookLib does not expose fixed-layout itemref properties in its spine API."""

    def _write_opf_spine(self, root, ncx_id):
        super()._write_opf_spine(root, ncx_id)
        spine = root.find("spine")
        for itemref in spine:
            if itemref.get("idref", "").startswith("page-"):
                itemref.set("properties", "rendition:layout-pre-paginated")


def _safe_text(value: str) -> str:
    return html.escape(value, quote=False)


def _image_png(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        result = io.BytesIO()
        image.convert("RGB").save(result, format="PNG", optimize=True)
        return result.getvalue()


def _base_book(title: str, author: str, language: str) -> epub.EpubBook:
    book = epub.EpubBook()
    book.set_identifier(f"urn:uuid:{uuid.uuid4()}")
    book.set_title(title.strip() or "Sem título")
    book.set_language(language.strip() or "pt-BR")
    if author.strip():
        book.add_author(author.strip())
    return book


def _add_image(book: epub.EpubBook, data: bytes, name: str) -> str:
    image = epub.EpubImage()
    image.file_name = f"images/{name}.png"
    image.media_type = "image/png"
    image.content = _image_png(data)
    book.add_item(image)
    return image.file_name


def _block_html(book: epub.EpubBook, block: Block, image_number: int) -> str:
    if block.role == "Ignorar":
        return ""
    if block.role == "Imagem" and block.image:
        source = _add_image(book, block.image, f"figure-{image_number:05d}")
        return f'<figure><img src="../{source}" alt="Ilustração da página {block.page + 1}"/></figure>'
    text = block.rich_html if block.rich_html and block.text == block.source_text else _safe_text(block.text.strip())
    if not text:
        return ""
    tag = {"Capítulo": "h1", "Seção": "h2", "Nota": "aside"}.get(block.role, "p")
    css_class = ' class="caption"' if block.role == "Legenda" else ""
    return f"<{tag}{css_class}>{text}</{tag}>"


def _section_groups(project: PdfProject) -> list[tuple[str, list[Block]]]:
    sections: list[tuple[str, list[Block]]] = []
    current_title = project.title
    current: list[Block] = []
    last_page = -1
    for block in project.blocks:
        if block.page != last_page:
            role = project.page_roles[block.page]
            if role != "Conteúdo" and role != "Capa externa" and current:
                sections.append((current_title, current))
                current = []
                current_title = role
            last_page = block.page
        if block.role == "Capítulo" and current:
            sections.append((current_title, current))
            current = []
            current_title = block.text[:100]
        if block.role != "Ignorar" and not (project.page_roles[block.page] == "Capa externa" and block.page == project.cover_page):
            current.append(block)
    if current:
        sections.append((current_title, current))
    return sections


def export_pdf(project: PdfProject, destination: str | Path) -> None:
    if not any(b.role != "Ignorar" and (b.text or b.image) for b in project.blocks):
        raise ValueError("Não há conteúdo extraído para exportar. Um PDF escaneado precisa de OCR.")
    book = _base_book(project.title, project.author, project.language)
    cover = _image_png(project.custom_cover.read_bytes()) if project.custom_cover else render_page(project.source, project.cover_page, width=1100)
    book.set_cover("cover.png", cover, create_page=False)
    css = epub.EpubItem(uid="style", file_name="styles/book.css", media_type="text/css", content=STYLES)
    book.add_item(css)
    chapters: list[epub.EpubHtml] = []
    image_number = 0
    for index, (title, blocks) in enumerate(_section_groups(project), 1):
        body = []
        for block in blocks:
            image_number += 1
            body.append(_block_html(book, block, image_number))
        if not any(body):
            continue
        chapter = epub.EpubHtml(title=title, file_name=f"text/section-{index:04d}.xhtml", lang=project.language)
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
    epub.write_epub(str(destination), book, {})


def _manga_image(path: Path) -> tuple[bytes, str, str]:
    with Image.open(path) as image:
        image.load()
        output = io.BytesIO()
        if image.format == "PNG":
            image.save(output, format="PNG", optimize=True)
            return output.getvalue(), "png", "image/png"
        if image.format == "JPEG":
            image.save(output, format="JPEG", quality=94, optimize=True)
            return output.getvalue(), "jpg", "image/jpeg"
        if "A" in image.getbands():
            image.save(output, format="PNG", optimize=True)
            return output.getvalue(), "png", "image/png"
        image.convert("RGB").save(output, format="JPEG", quality=94, optimize=True)
        return output.getvalue(), "jpg", "image/jpeg"


def export_manga(project: MangaProject, destination: str | Path) -> None:
    if not project.pages:
        raise ValueError("Adicione páginas antes de exportar.")
    if not 0 <= project.cover_index < len(project.pages):
        raise ValueError("A capa selecionada não existe.")
    book = _base_book(project.title, project.author, project.language)
    book.set_direction("rtl" if project.right_to_left else "ltr")
    cover_data, cover_ext, _ = _manga_image(project.custom_cover or project.pages[project.cover_index])
    book.set_cover(f"cover.{cover_ext}", cover_data, create_page=False)
    pages: list[epub.EpubHtml] = []
    for index, source in enumerate(project.pages, 1):
        data, extension, mime = _manga_image(source)
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
        image_item = epub.EpubImage()
        image_item.file_name = f"images/page-{index:04d}.{extension}"
        image_item.media_type = mime
        image_item.content = data
        book.add_item(image_item)
        page_title = project.chapter_titles.get(str(source), f"Página {index}")
        page = epub.EpubHtml(uid=f"page-{index:04d}", title=page_title, file_name=f"pages/page-{index:04d}.xhtml", lang=project.language)
        page.add_meta(name="viewport", content=f"width={width},height={height}")
        page.content = (
            "<html xmlns='http://www.w3.org/1999/xhtml'><head></head><body>"
            f"<img src='../{image_item.file_name}' alt='Página {index}' style='display:block;width:100%;height:100%;object-fit:contain'/>"
            "</body></html>"
        )
        book.add_item(page)
        pages.append(page)
    chapter_entries = [page for index, page in enumerate(pages) if str(project.pages[index]) in project.chapter_titles]
    book.toc = tuple(chapter_entries or pages[:1])
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *pages]
    writer = MangaWriter(str(destination), book, {})
    writer.process()
    writer.write()
