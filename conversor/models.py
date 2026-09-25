# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


BLOCK_ROLES = ("Parágrafo", "Capítulo", "Seção", "Nota", "Legenda", "Imagem", "Ignorar")
PAGE_ROLES = (
    "Conteúdo", "Capa externa", "Capa interna", "Folha de rosto", "Créditos",
    "Dedicatória", "Epígrafe", "Sumário", "Bibliografia", "Índice remissivo",
)


@dataclass
class Block:
    page: int
    role: str
    text: str = ""
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    font_size: float = 0
    image: bytes | None = None
    image_ext: str | None = None
    source_text: str = ""
    rich_html: str = ""


@dataclass
class PdfProject:
    source: Path
    title: str
    author: str = ""
    language: str = "pt-BR"
    blocks: list[Block] = field(default_factory=list)
    page_roles: list[str] = field(default_factory=list)
    scanned_pages: list[int] = field(default_factory=list)
    ocr_pages: list[int] = field(default_factory=list)
    cover_page: int = 0
    custom_cover: Path | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class MangaProject:
    title: str = ""
    author: str = ""
    language: str = "pt-BR"
    pages: list[Path] = field(default_factory=list)
    right_to_left: bool = True
    cover_index: int = 0
    custom_cover: Path | None = None
    chapter_titles: dict[str, str] = field(default_factory=dict)
