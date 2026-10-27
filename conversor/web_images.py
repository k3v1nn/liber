# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import io
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import unquote, urljoin, urlparse

import requests
from lxml import etree, html
from PIL import Image, ImageOps


MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_GALLERY_IMAGES = 300
MAX_IMAGE_PIXELS = 80_000_000
MIN_IMAGE_SIDE = 300
# Per-URL budget: a gallery that hangs must not freeze the whole import.
URL_DEADLINE = 180.0
REQUEST_TIMEOUT = 20.0
DOWNLOAD_WORKERS = 6
RETRY_ATTEMPTS = 2
RETRY_BACKOFF = 0.4
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
HEADERS = {"User-Agent": "ConversorEPUB/0.1 (+local personal importer)"}
ORIENTATION_TAG = 0x0112
FORMAT_EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp"}
# Formats saved exactly as downloaded unless orientation or color mode forces a rewrite.
KEEP_ORIGINAL_FORMATS = frozenset(FORMAT_EXTENSIONS)

INVALID_URL_MESSAGE = "Informe um endereço HTTP ou HTTPS."
NOT_HTML_MESSAGE = "O endereço não contém uma página HTML ou imagem."
PAGE_TOO_LARGE_MESSAGE = "A página HTML é grande demais para importar com segurança."
NO_IMAGES_MESSAGE = "Nenhuma imagem foi encontrada na página."
NO_DOWNLOADED_MESSAGE = "Nenhuma imagem pôde ser baixada desta página."
NETWORK_MESSAGE = "Não foi possível acessar o endereço."
TIMEOUT_MESSAGE = "O endereço demorou demais para responder."
ALL_FAILED_MESSAGE = "Nenhuma imagem pôde ser importada dos endereços informados."
PAGE_PROGRESS_MESSAGE = "Baixando imagens da página..."
IMAGE_PROGRESS_MESSAGE = "Baixando imagem..."

ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class ImportReport:
    url: str
    title: str
    paths: list[Path]
    skipped: int
    truncated: bool
    error: str | None = None


class ImportCancelled(Exception):
    """Raised when the caller cancels an import that is still running."""


class _UrlFailed(Exception):
    """Internal: one URL could not be imported; the others must continue."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _request_timeout(deadline: float) -> float | None:
    remaining = deadline - time.monotonic()
    return None if remaining <= 0 else min(REQUEST_TIMEOUT, remaining)


def _sniff_image_format(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "GIF"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def _looks_like_html(data: bytes) -> bool:
    return data.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<")


def _content_type(response) -> str:
    return (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or parsed.netloc or url
    name = Path(unquote(parsed.path)).name
    return f"{host}/{name}" if name else host


def _clean_title(text: str) -> str:
    return " ".join(text.split())[:200]


def _page_title(tree) -> str:
    title = _clean_title(" ".join(tree.xpath("//title[1]//text()")))
    if title:
        return title
    meta = tree.xpath("//meta[@property='og:title']/@content") or tree.xpath("//meta[@name='og:title']/@content")
    return _clean_title(" ".join(meta))


def _read_body(response, limit: int, is_cancelled: Callable[[], bool]) -> bytes | None:
    """Read a response body, or return None when it exceeds `limit`."""
    data = bytearray()
    for chunk in response.iter_content(64 * 1024):
        if is_cancelled():
            raise ImportCancelled()
        data.extend(chunk)
        if len(data) > limit:
            return None
    return bytes(data)


def _retry_pause(attempt: int, deadline: float, is_cancelled: Callable[[], bool]) -> bool:
    delay = RETRY_BACKOFF * (attempt + 1)
    end = time.monotonic() + delay
    if end >= deadline:
        return False
    while (remaining := end - time.monotonic()) > 0:
        if is_cancelled():
            raise ImportCancelled()
        time.sleep(min(0.05, remaining))
    return True


def _store_image(data: bytes, folder: Path, index: int) -> Path | None:
    """Validate one downloaded image and store it as a temporary download-* file."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE:
                return None
            if width * height > MAX_IMAGE_PIXELS:
                return None
            image_format = (image.format or "").upper()
            orientation = 1
            if image_format == "JPEG":
                orientation = image.getexif().get(ORIENTATION_TAG) or 1
            # Preview and EPUB export call ImageOps.exif_transpose while reading, so untouched
            # PNG/WebP/GIF orientation tags still render correctly; only JPEG is fixed here.
            keep_original = (
                image_format in KEEP_ORIGINAL_FORMATS
                and image.mode != "CMYK"
                and not (image_format == "JPEG" and orientation != 1)
            )
            if keep_original:
                target = folder / f"download-{index:04d}{FORMAT_EXTENSIONS[image_format]}"
                target.write_bytes(data)
                return target
            # A rewrite is unavoidable: readers ignore EXIF orientation and cannot show CMYK.
            image.load()
            ImageOps.exif_transpose(image, in_place=True)
            if image.mode not in {"1", "L", "LA", "P", "RGB", "RGBA"}:
                image = image.convert("RGB")
            if image_format == "JPEG":
                target = folder / f"download-{index:04d}.jpg"
                image.save(target, format="JPEG", quality=95)
            else:
                target = folder / f"download-{index:04d}.png"
                image.save(target, format="PNG", optimize=True)
            return target
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError, SyntaxError):
        return None


def _download_image(
    session: requests.Session,
    url: str,
    referer: str,
    folder: Path,
    index: int,
    deadline: float,
    is_cancelled: Callable[[], bool],
) -> Path | None:
    data = _fetch_image(session, url, referer, deadline, is_cancelled)
    return None if data is None else _store_image(data, folder, index)


def _fetch_image(
    session: requests.Session,
    url: str,
    referer: str,
    deadline: float,
    is_cancelled: Callable[[], bool],
) -> bytes | None:
    """Fetch one image, retrying only transient network and server failures."""
    for attempt in range(RETRY_ATTEMPTS + 1):
        if is_cancelled():
            raise ImportCancelled()
        timeout = _request_timeout(deadline)
        if timeout is None:
            return None
        retry = False
        try:
            with session.get(url, timeout=timeout, stream=True, headers={"Referer": referer}) as response:
                if response.status_code in RETRY_STATUS:
                    if attempt >= RETRY_ATTEMPTS:
                        return None
                    retry = True
                else:
                    response.raise_for_status()
                    content_type = _content_type(response)
                    sniff = not content_type.startswith("image/")
                    if sniff and content_type not in {"", "application/octet-stream", "binary/octet-stream"}:
                        return None
                    data = _read_body(response, MAX_IMAGE_BYTES, is_cancelled)
                    if data is None or (sniff and _sniff_image_format(data) is None):
                        return None
                    return data
        except requests.TooManyRedirects:
            return None
        except requests.HTTPError:
            # Retryable statuses are handled above; any other 4xx/5xx is a permanent skip.
            return None
        except requests.RequestException:
            if attempt >= RETRY_ATTEMPTS or _request_timeout(deadline) is None:
                return None
            retry = True
        except OSError:
            return None
        if retry and not _retry_pause(attempt, deadline, is_cancelled):
            return None
    return None


def _download_candidates(
    session: requests.Session,
    candidates: Sequence[str],
    folder: Path,
    referer: str,
    notify: ProgressCallback,
    is_cancelled: Callable[[], bool],
    deadline: float,
) -> list[Path | None]:
    """Download every candidate with a small pool; results stay in page order."""
    total = len(candidates)
    notify(0, total, PAGE_PROGRESS_MESSAGE)
    results: list[Path | None] = [None] * total
    if not total:
        return results
    pool = ThreadPoolExecutor(max_workers=min(DOWNLOAD_WORKERS, total))
    pending = {
        pool.submit(_download_image, session, candidate, referer, folder, index + 1, deadline, is_cancelled): index
        for index, candidate in enumerate(candidates)
    }
    finished_count = 0
    interrupted = True
    try:
        while pending:
            if is_cancelled():
                raise ImportCancelled()
            finished, _ = wait(set(pending), timeout=0.1, return_when=FIRST_COMPLETED)
            for future in finished:
                index = pending.pop(future)
                try:
                    results[index] = future.result()
                except ImportCancelled:
                    raise
                except Exception:  # a broken image must never abort the gallery
                    results[index] = None
                finished_count += 1
                notify(finished_count, total, f"Imagem {finished_count} de {total}")
        interrupted = False
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        if interrupted:
            for leftover in folder.glob("download-*"):
                leftover.unlink(missing_ok=True)
    return results


def _finalize(temporary: Sequence[Path | None], folder: Path) -> list[Path]:
    """Rename surviving downloads to compact, sequential page names."""
    paths: list[Path] = []
    for item in temporary:
        if item is None:
            continue
        target = folder / f"page-{len(paths) + 1:04d}{item.suffix}"
        item.replace(target)
        paths.append(target)
    return paths


def _candidates(tree, page_url: str) -> tuple[list[str], bool]:
    base = page_url
    bases = tree.xpath("//base[@href]/@href")
    if bases:
        resolved = urljoin(page_url, bases[0].strip())
        if _http_url(resolved):
            base = resolved
    seen: set[str] = set()
    candidates: list[str] = []
    truncated = False
    for element in tree.xpath("//img"):
        source = element.get("data-src") or element.get("data-original") or element.get("src")
        if not source and element.get("srcset"):
            source = element.get("srcset").split(",")[-1].strip().split(" ")[0]
        if not source:
            continue
        absolute = urljoin(base, source.strip())
        if not _http_url(absolute) or absolute in seen:
            continue
        seen.add(absolute)
        if len(candidates) >= MAX_GALLERY_IMAGES:
            truncated = True
            break
        candidates.append(absolute)
    return candidates, truncated


def _parse_page(page_data: bytes, page_url: str) -> tuple[str, list[str], bool]:
    if not page_data.strip():
        raise _UrlFailed(NOT_HTML_MESSAGE)
    try:
        tree = html.fromstring(page_data)
    except (etree.ParserError, etree.XMLSyntaxError, ValueError):
        raise _UrlFailed(NOT_HTML_MESSAGE) from None
    candidates, truncated = _candidates(tree, page_url)
    title = _page_title(tree) or urlparse(page_url).hostname or page_url
    return title, candidates, truncated


def _direct_image_report(data: bytes | None, url: str, folder: Path, notify: ProgressCallback) -> ImportReport:
    notify(0, 1, IMAGE_PROGRESS_MESSAGE)
    if data is None:
        raise _UrlFailed(NOT_HTML_MESSAGE)
    temporary = _store_image(data, folder, 1)
    if temporary is None:
        raise _UrlFailed(NOT_HTML_MESSAGE)
    notify(1, 1, IMAGE_PROGRESS_MESSAGE)
    return ImportReport(url=url, title=_title_from_url(url), paths=_finalize([temporary], folder), skipped=0, truncated=False)


def _import_one(
    session: requests.Session,
    url: str,
    folder: Path,
    notify: ProgressCallback,
    is_cancelled: Callable[[], bool],
) -> ImportReport:
    if not _http_url(url):
        raise _UrlFailed(INVALID_URL_MESSAGE)
    deadline = time.monotonic() + URL_DEADLINE
    folder.mkdir(parents=True, exist_ok=True)
    timeout = _request_timeout(deadline)
    if timeout is None:
        raise _UrlFailed(TIMEOUT_MESSAGE)
    try:
        with session.get(url, timeout=timeout, stream=True) as response:
            response.raise_for_status()
            page_url = response.url
            content_type = _content_type(response)
            if content_type.startswith("image/"):
                return _direct_image_report(_read_body(response, MAX_IMAGE_BYTES, is_cancelled), url, folder, notify)
            if content_type in {"", "application/octet-stream", "binary/octet-stream"}:
                body = _read_body(response, MAX_IMAGE_BYTES, is_cancelled)
                if body is None:
                    raise _UrlFailed(NOT_HTML_MESSAGE)
                if _sniff_image_format(body) is not None:
                    return _direct_image_report(body, url, folder, notify)
                if not _looks_like_html(body):
                    raise _UrlFailed(NOT_HTML_MESSAGE)
                if len(body) > MAX_PAGE_BYTES:
                    raise _UrlFailed(PAGE_TOO_LARGE_MESSAGE)
                page_data = body
            elif "html" in content_type:
                page_data = _read_body(response, MAX_PAGE_BYTES, is_cancelled)
                if page_data is None:
                    raise _UrlFailed(PAGE_TOO_LARGE_MESSAGE)
            else:
                raise _UrlFailed(NOT_HTML_MESSAGE)
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        raise _UrlFailed(NETWORK_MESSAGE if status is None else f"Falha ao acessar o endereço (HTTP {status}).") from error
    except requests.Timeout as error:
        raise _UrlFailed(TIMEOUT_MESSAGE) from error
    except requests.RequestException as error:
        raise _UrlFailed(NETWORK_MESSAGE) from error
    title, candidates, truncated = _parse_page(page_data, page_url)
    if not candidates:
        raise _UrlFailed(NO_IMAGES_MESSAGE)
    results = _download_candidates(session, candidates, folder, page_url, notify, is_cancelled, deadline)
    paths = _finalize(results, folder)
    if not paths:
        raise _UrlFailed(NO_DOWNLOADED_MESSAGE)
    return ImportReport(url=url, title=title, paths=paths, skipped=len(candidates) - len(paths), truncated=truncated)


def import_images_from_urls(
    urls: Sequence[str],
    directory: str | Path,
    *,
    progress: ProgressCallback | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[ImportReport]:
    """Import direct image links or the visible <img> elements of public pages.

    Each URL is saved in its own ``source-NN`` subfolder. One failed URL never aborts the
    others; a report carries the reason in ``error``. This intentionally does not bypass
    authentication or crawl other chapters, and the caller reviews the pages before export.
    """
    targets = [str(url).strip() for url in urls]
    if not targets:
        raise ValueError(INVALID_URL_MESSAGE)
    cancelled = is_cancelled or (lambda: False)
    notify = progress or (lambda done, total, message: None)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    reports: list[ImportReport] = []
    with requests.Session() as session:
        session.headers.update(HEADERS)
        for position, url in enumerate(targets, 1):
            if cancelled():
                raise ImportCancelled()
            try:
                reports.append(_import_one(session, url, directory / f"source-{position:02d}", notify, cancelled))
            except _UrlFailed as failure:
                reports.append(
                    ImportReport(url=url, title=_title_from_url(url), paths=[], skipped=0, truncated=False, error=failure.message)
                )
    if not any(report.paths for report in reports):
        if len(reports) == 1 and reports[0].error:
            raise ValueError(reports[0].error)
        raise ValueError(ALL_FAILED_MESSAGE)
    return reports
