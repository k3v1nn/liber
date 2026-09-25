# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import io
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from lxml import html
from PIL import Image


MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_GALLERY_IMAGES = 300
HEADERS = {"User-Agent": "ConversorEPUB/0.1 (+local personal importer)"}


def _http_url(url: str) -> bool:
    return urlparse(url).scheme in {"http", "https"}


def _download_image(session: requests.Session, url: str, destination: Path) -> bool:
    try:
        with session.get(url, timeout=20, stream=True) as response:
            response.raise_for_status()
            if not response.headers.get("Content-Type", "").lower().startswith("image/"):
                return False
            data = bytearray()
            for chunk in response.iter_content(64 * 1024):
                data.extend(chunk)
                if len(data) > MAX_IMAGE_BYTES:
                    return False
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if min(image.size) < 300:
                return False
            image.save(destination, format="PNG", optimize=True)
        return True
    except (requests.RequestException, OSError, ValueError):
        return False


def import_images_from_url(url: str, folder: str | Path) -> list[Path]:
    """Import direct image links or the visible <img> elements of one public page.

    This intentionally does not bypass authentication or crawl other chapters.
    The caller reviews the resulting list before export.
    """
    if not _http_url(url):
        raise ValueError("Informe um endereço HTTP ou HTTPS.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    with session.get(url, timeout=20, stream=True) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type.startswith("image/"):
            target = folder / "page-0001.png"
            return [target] if _download_image(session, url, target) else []
        if "html" not in content_type:
            raise ValueError("O endereço não contém uma página HTML ou imagem.")
        page_data = bytearray()
        for chunk in response.iter_content(64 * 1024):
            page_data.extend(chunk)
            if len(page_data) > 5 * 1024 * 1024:
                raise ValueError("A página HTML é grande demais para importar com segurança.")
    tree = html.fromstring(bytes(page_data))
    candidates: list[str] = []
    for element in tree.xpath("//img"):
        source = element.get("data-src") or element.get("data-original") or element.get("src")
        if not source and element.get("srcset"):
            source = element.get("srcset").split(",")[-1].strip().split(" ")[0]
        if source:
            absolute = urljoin(url, source)
            if _http_url(absolute) and absolute not in candidates:
                candidates.append(absolute)
        if len(candidates) >= MAX_GALLERY_IMAGES:
            break
    paths: list[Path] = []
    for candidate in candidates:
        target = folder / f"page-{len(paths) + 1:04d}.png"
        if _download_image(session, candidate, target):
            paths.append(target)
    return paths
