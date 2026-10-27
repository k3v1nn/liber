# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import hashlib
import html
import os
import re
import statistics
from collections import defaultdict
from pathlib import Path

import pymupdf

from .models import Block, PdfProject


CHAPTER_RE = re.compile(r"^(?:cap[ií]tulo|chapter|parte|part)\s+(?:[\divxlcdm]+|\d+|[a-z]+)\b", re.I)
SECTION_RE = re.compile(r"^\d+(?:\.\d+)+\s+\S")
PAGE_NUMBER_RE = re.compile(r"^(?:p[aá]g(?:ina)?\.?\s*)?[\divxlcdm\d]{1,8}$", re.I)
TOC_PHRASE_RE = re.compile(r"\b(sum[aá]rio|table of contents)\b", re.I)
INDEX_PHRASE_RE = re.compile(r"\b[ií]ndice remissivo\b", re.I)
BIBLIOGRAPHY_PHRASE_RE = re.compile(r"\b(bibliografia|refer[eê]ncias)\b", re.I)
# Bare headings that may label a table of contents. They are only trusted when they stand
# alone at the top of the page, because the same words show up in ordinary prose.
TOC_HEADINGS = frozenset({"sumário", "sumario", "table of contents", "contents", "índice", "indice", "conteúdo", "conteudo"})


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _join_lines(lines: list[dict]) -> str:
    result = ""
    for line in lines:
        part = "".join(span.get("text", "") for span in line.get("spans", []))
        part = _normalize(part)
        if not part:
            continue
        if result.endswith("-") and part[0].islower():
            result = result[:-1] + part
        elif result:
            result += " " + part
        else:
            result = part
    return result


def _styled_lines(lines: list[dict]) -> str:
    rows = []
    for line in lines:
        fragments = []
        for span in line.get("spans", []):
            value = span.get("text", "")
            if not value:
                continue
            escaped = html.escape(value, quote=False)
            font = span.get("font", "").lower()
            flags = int(span.get("flags", 0))
            if flags & 2 or "italic" in font or "oblique" in font:
                escaped = f"<em>{escaped}</em>"
            if flags & 16 or "bold" in font:
                escaped = f"<strong>{escaped}</strong>"
            fragments.append(escaped)
        if fragments:
            rows.append("".join(fragments).strip())
    return " ".join(rows)


def _column_order(blocks: list[Block], page_width: float) -> list[Block]:
    """Left column first, then the right column, each from top to bottom."""
    return sorted(
        blocks,
        key=lambda b: (0 if (b.bbox[0] + b.bbox[2]) / 2 < page_width * 0.5 else 1, b.bbox[1], b.bbox[0]),
    )


def _reading_order(blocks: list[Block], page_width: float) -> list[Block]:
    """Order two-column pages left to right, splicing full-width blocks in at their y."""
    text = [b for b in blocks if b.text and b.role != "Ignorar"]
    narrow = [b for b in text if b.bbox[2] - b.bbox[0] < page_width * 0.55]
    left = [b for b in narrow if (b.bbox[0] + b.bbox[2]) / 2 < page_width * 0.5]
    right = [b for b in narrow if (b.bbox[0] + b.bbox[2]) / 2 >= page_width * 0.5]
    if len(left) < 2 or len(right) < 2:
        return sorted(blocks, key=lambda b: (round(b.bbox[1] / 5), b.bbox[0]))
    breaks = sorted(
        (b for b in blocks if b.bbox[2] - b.bbox[0] >= page_width * 0.55),
        key=lambda b: (b.bbox[1], b.bbox[0]),
    )
    # Blocks are compared by identity: two equal paragraphs must never hide each other.
    break_ids = {id(b) for b in breaks}
    pending = [b for b in blocks if id(b) not in break_ids]
    ordered: list[Block] = []
    top = float("-inf")
    for marker in breaks:
        ordered.extend(_column_order([b for b in pending if top <= b.bbox[1] < marker.bbox[1]], page_width))
        ordered.append(marker)
        top = marker.bbox[1]
        pending = [b for b in pending if b.bbox[1] >= top]
    ordered.extend(_column_order(pending, page_width))
    return ordered


def _heading_label(text: str) -> str:
    return re.sub(r"[\s:.\-–—]+$", "", _normalize(text)).casefold()


def _is_toc_heading(lines: list[str]) -> bool:
    return any(_heading_label(line) in TOC_HEADINGS for line in lines)


def _guess_page_role(page: int, text: str, image_area: float, page_area: float, lines: list[str]) -> str:
    head = text[:350].lower()
    if page < 3 and image_area > page_area * 0.45 and len(text) < 180:
        return "Capa externa" if page == 0 else "Capa interna"
    # Specific labels first: an index or a bibliography can start early in short books, and
    # the generic words below must not claim those pages.
    if INDEX_PHRASE_RE.search(head):
        return "Índice remissivo"
    if BIBLIOGRAPHY_PHRASE_RE.search(head):
        return "Bibliografia"
    if page < 15:
        if TOC_PHRASE_RE.search(head) or _is_toc_heading(lines):
            return "Sumário"
        if re.search(r"\b(copyright|direitos reservados|isbn|ficha catalogr[aá]fica)\b", head):
            return "Créditos"
        if re.search(r"\b(dedicat[oó]ria|dedico)\b", head) and len(text) < 900:
            return "Dedicatória"
        if len(text) < 280 and page < 5 and text:
            return "Folha de rosto"
    return "Conteúdo"


def _tessdata_candidates() -> list[Path]:
    prefix = os.environ.get("TESSDATA_PREFIX")
    candidates = [
        Path(__file__).resolve().parent.parent / "resources" / "tessdata",
        Path("/usr/share/tesseract/tessdata"),
        Path("/usr/share/tesseract-ocr/5/tessdata"),
        Path("/opt/homebrew/share/tessdata"),
        Path(r"C:\Program Files\Tesseract-OCR\tessdata"),
    ]
    if prefix:
        candidates[1:1] = [Path(prefix), Path(prefix) / "tessdata"]
    return candidates


def _tessdata() -> Path | None:
    return next(
        (path for path in _tessdata_candidates() if (path / "eng.traineddata").is_file() or (path / "por.traineddata").is_file()),
        None,
    )


def _ocr_languages(tessdata: Path) -> str:
    return "+".join(language for language in ("por", "eng") if (tessdata / f"{language}.traineddata").is_file())


def analyze_pdf(path: str | Path) -> PdfProject:
    source = Path(path)
    with pymupdf.open(source) as doc:
        if doc.needs_pass:
            raise ValueError("O PDF está protegido por senha.")
        if not doc.page_count:
            raise ValueError("O PDF não contém páginas.")
        metadata = doc.metadata or {}
        title = _normalize(metadata.get("title") or "") or source.stem
        project = PdfProject(source=source, title=title, author=_normalize(metadata.get("author") or ""))
        tessdata = _tessdata()
        blocks_by_page: list[list[Block]] = []
        sizes: list[float] = []
        edges: dict[str, set[int]] = defaultdict(set)
        images_by_hash: dict[bytes, bytes] = {}

        for page_number, page in enumerate(doc):
            raw = page.get_text("dict")
            page_area = page.rect.width * page.rect.height
            image_area = sum(
                max(0, item["bbox"][2] - item["bbox"][0]) * max(0, item["bbox"][3] - item["bbox"][1])
                for item in raw.get("blocks", []) if item.get("type") == 1 and "bbox" in item
            )
            original_text = "".join(
                span.get("text", "")
                for item in raw.get("blocks", []) if item.get("type") == 0
                for line in item.get("lines", []) for span in line.get("spans", [])
            )
            # Only an image-dominated page is a scan: poetry, dividers and other sparse vector
            # pages also carry little text, but they have nothing for OCR to recover.
            if len(original_text.strip()) < 30 and image_area > page_area * 0.5:
                project.scanned_pages.append(page_number + 1)
                if tessdata:
                    try:
                        textpage = page.get_textpage_ocr(language=_ocr_languages(tessdata), dpi=200, full=True, tessdata=str(tessdata))
                        recognized = page.get_text("dict", textpage=textpage)
                        recognized_text = "".join(
                            span.get("text", "")
                            for item in recognized.get("blocks", []) if item.get("type") == 0
                            for line in item.get("lines", []) for span in line.get("spans", [])
                        )
                        if len(recognized_text.strip()) > len(original_text.strip()):
                            raw = recognized
                            project.ocr_pages.append(page_number + 1)
                    except Exception as exc:
                        project.warnings.append(f"OCR falhou na página {page_number + 1}: {exc}")
            page_blocks: list[Block] = []
            for item in raw.get("blocks", []):
                bbox = tuple(item.get("bbox", (0, 0, 0, 0)))
                if item.get("type") == 0:
                    lines = item.get("lines", [])
                    value = _join_lines(lines)
                    if not value:
                        continue
                    spans = [s for line in lines for s in line.get("spans", [])]
                    size = max((float(s.get("size", 0)) for s in spans), default=0)
                    sizes.extend(float(s.get("size", 0)) for s in spans if s.get("text", "").strip())
                    rich = _styled_lines(lines)
                    if _normalize(html.unescape(re.sub(r"<[^>]+>", "", rich))) != value:
                        rich = ""
                    page_blocks.append(Block(page_number, "Parágrafo", value, bbox, size, source_text=value, rich_html=rich))
                    if bbox[1] < page.rect.height * 0.08 or bbox[3] > page.rect.height * 0.92:
                        edges[_normalize(value).casefold()].add(page_number)
                elif item.get("type") == 1 and item.get("image"):
                    if page_number + 1 not in project.ocr_pages and (bbox[2] - bbox[0]) > page.rect.width * 0.2:
                        # A logo or ornament repeated on many pages is stored once.
                        digest = hashlib.sha256(item["image"]).digest()
                        page_blocks.append(Block(page_number, "Imagem", bbox=bbox, image=images_by_hash.setdefault(digest, item["image"])))
            page_blocks = _reading_order(page_blocks, page.rect.width)
            blocks_by_page.append(page_blocks)
            text = " ".join(b.text for b in page_blocks if b.text)
            headlines = [b.text for b in page_blocks if b.text][:3]
            project.page_roles.append(_guess_page_role(page_number, text, image_area, page_area, headlines))

        common_edges = {value for value, pages in edges.items() if value and len(pages) >= 3}
        body_size = statistics.median(sizes) if sizes else 11.0
        for page_number, page_blocks in enumerate(blocks_by_page):
            page = doc[page_number]
            image_blocks = [block for block in page_blocks if block.role == "Imagem"]
            for block in page_blocks:
                if block.text:
                    key = _normalize(block.text).casefold()
                    at_edge = block.bbox[1] < page.rect.height * 0.08 or block.bbox[3] > page.rect.height * 0.92
                    if at_edge and (key in common_edges or PAGE_NUMBER_RE.fullmatch(key)):
                        block.role = "Ignorar"
                    elif CHAPTER_RE.match(block.text) or (len(block.text) < 100 and block.font_size >= body_size * 1.42 and block.bbox[1] < page.rect.height * 0.55):
                        block.role = "Capítulo"
                    elif SECTION_RE.match(block.text) or (len(block.text) < 100 and block.font_size >= body_size * 1.18):
                        block.role = "Seção"
                    elif block.font_size < body_size * 0.82 and block.bbox[1] > page.rect.height * 0.68:
                        block.role = "Nota"
                    elif len(block.text) < 180 and any(
                        abs(block.bbox[1] - image.bbox[3]) < 35
                        and block.bbox[0] < image.bbox[2]
                        and block.bbox[2] > image.bbox[0]
                        for image in image_blocks
                    ):
                        block.role = "Legenda"
                project.blocks.append(block)

        if len(project.scanned_pages) > doc.page_count / 2 and len(project.ocr_pages) < len(project.scanned_pages) / 2:
            project.warnings.append("A maior parte do PDF parece escaneada, e o OCR não conseguiu recuperar texto suficiente.")
        elif project.ocr_pages:
            project.warnings.append(f"OCR aplicado às páginas: {', '.join(map(str, project.ocr_pages[:12]))}.")
        elif project.scanned_pages:
            project.warnings.append(f"Páginas com pouco texto detectadas: {', '.join(map(str, project.scanned_pages[:12]))}.")
        if not project.blocks:
            project.warnings.append("Não foi possível extrair blocos de conteúdo deste PDF.")
        if project.page_roles and "Capa externa" not in project.page_roles:
            project.warnings.append("Capa não identificada com segurança; a primeira página foi escolhida como sugestão.")
        return project


def render_page(path: Path, page_number: int, width: int = 650) -> bytes:
    with pymupdf.open(path) as doc:
        page = doc[page_number]
        scale = width / page.rect.width
        return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
