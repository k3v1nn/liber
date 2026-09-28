# SPDX-License-Identifier: AGPL-3.0-only
"""Turn PDF pages into ordered images for a fixed-layout comic EPUB."""

from __future__ import annotations

from pathlib import Path

import pymupdf


def import_comic_pdf(source: str | Path, directory: str | Path, longest_edge: int = 2200) -> list[Path]:
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    pages: list[Path] = []
    try:
        with pymupdf.open(source) as document:
            if document.needs_pass:
                raise ValueError("O PDF está protegido por senha.")
            if not document.page_count:
                raise ValueError("O PDF não contém páginas.")
            for number, page in enumerate(document, 1):
                edge = max(page.rect.width, page.rect.height)
                if edge <= 0:
                    raise ValueError(f"A página {number} do PDF tem tamanho inválido.")
                scale = longest_edge / edge
                destination = output / f"page-{number:05d}.png"
                pages.append(destination)
                page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False).save(destination)
    except Exception:
        for destination in pages:
            destination.unlink(missing_ok=True)
        raise
    return pages
