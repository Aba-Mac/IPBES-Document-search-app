"""
ocr.py
======

Production-grade OCR pipeline for the Parliamentary Document Search project.

This module is responsible for:

* Detecting whether a PDF is digital-native or scanned.
* Running OCRmyPDF only when OCR is required.
* Preserving searchable PDFs without unnecessary processing.
* Returning a consistent internal representation for downstream
  extraction regardless of ingestion path.
* Providing detailed logging and robust error handling.

The extraction pipeline is intentionally separated into two stages:

    PDF
      │
      ▼
    OCR (this module)
      │
      ▼
    extract.py
      │
      ▼
    clean.py
      │
      ▼
    chunk.py

The module never performs text extraction itself. It only ensures that
the document is searchable before extraction begins.

Requirements
------------

External executable:

    ocrmypdf

Python packages:

    fitz (PyMuPDF)
    pypdf
    loguru

Author
------
Production implementation for Shiny for Python deployment.

"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import fitz


###############################################################################
# Logging
###############################################################################

logger = logging.getLogger(__name__)


###############################################################################
# Exceptions
###############################################################################


class OCRException(Exception):
    """Base exception for OCR operations."""


class OCRExecutableNotFoundError(OCRException):
    """Raised when OCRmyPDF is unavailable."""


class OCRTimeoutError(OCRException):
    """Raised when OCR processing exceeds the configured timeout."""


class PDFInspectionError(OCRException):
    """Raised when a PDF cannot be analysed."""


class OCRFailedError(OCRException):
    """Raised when OCRmyPDF returns a non-zero exit code."""


###############################################################################
# Configuration
###############################################################################


@dataclass(slots=True, frozen=True)
class OCRConfig:
    """
    Runtime configuration for OCR processing.

    Parameters
    ----------
    dpi:
        Target rendering DPI used by OCRmyPDF.

    language:
        Tesseract language string.

    rotate_pages:
        Automatically detect rotated pages.

    deskew:
        Deskew scanned pages.

    clean:
        Enable OCRmyPDF cleaning.

    optimize:
        OCRmyPDF optimisation level.

    jobs:
        Parallel worker count.

    timeout:
        Maximum runtime in seconds.

    force_ocr:
        Always OCR regardless of PDF type.

    skip_text:
        Skip OCR on pages already containing text.

    invalidate_digital_threshold:
        Minimum average characters/page required before a PDF
        is considered digital-native.

    image_ratio_threshold:
        Percentage of pages dominated by raster images before
        the document is considered scanned.

    """

    dpi: int = 300

    language: str = "eng"

    rotate_pages: bool = True

    deskew: bool = True

    clean: bool = True

    optimize: int = 1

    jobs: int = 4

    timeout: int = 1800

    force_ocr: bool = False

    skip_text: bool = True

    invalidate_digital_threshold: int = 50

    image_ratio_threshold: float = 0.70


###############################################################################
# Internal models
###############################################################################


@dataclass(slots=True)
class PageInspection:
    """
    Inspection results for one page.
    """

    page_number: int

    text_characters: int

    image_count: int

    drawing_count: int

    width: float

    height: float

    is_text_page: bool

    image_area_ratio: float


@dataclass(slots=True)
class PDFInspection:
    """
    Aggregate PDF inspection results.
    """

    path: Path

    page_count: int

    pages: list[PageInspection]

    total_characters: int

    total_images: int

    digital_pages: int

    scanned_pages: int

    is_digital: bool

    needs_ocr: bool

    metadata: dict[str, str | None]

    sha256: str


@dataclass(slots=True)
class OCRResult:
    """
    Result returned after OCR stage.

    Regardless of whether OCR was executed, downstream modules
    always receive this object.
    """

    original_pdf: Path

    processed_pdf: Path

    inspection: PDFInspection

    ocr_performed: bool

    elapsed_seconds: float


###############################################################################
# Utilities
###############################################################################


def _sha256(path: Path) -> str:
    """
    Compute SHA256 for a PDF.

    Parameters
    ----------
    path
        PDF path.

    Returns
    -------
    str
    """

    digest = hashlib.sha256()

    with path.open("rb") as stream:

        while True:

            chunk = stream.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def _safe_metadata(document: fitz.Document) -> dict[str, str | None]:
    """
    Extract document metadata.

    Missing fields are normalised to None.
    """

    metadata = document.metadata or {}

    fields = (
        "title",
        "author",
        "creator",
        "producer",
        "subject",
        "keywords",
        "creationDate",
        "modDate",
    )

    return {field: metadata.get(field) or None for field in fields}


def _page_image_ratio(page: fitz.Page) -> float:
    """
    Estimate image coverage on a page.

    Returns
    -------
    float
        Fraction of page occupied by raster images.

    Notes
    -----
    This is a heuristic used only for OCR decisions.
    """

    page_area = page.rect.width * page.rect.height

    if page_area == 0:
        return 0.0

    total = 0.0

    try:

        for image in page.get_image_rects():

            for rect in image:
                total += rect.width * rect.height

    except Exception:

        return 0.0

    return min(total / page_area, 1.0)


def _has_sufficient_text(
    page: fitz.Page,
    minimum_characters: int,
) -> tuple[bool, int]:
    """
    Determine whether a page already contains meaningful text.

    Parameters
    ----------
    page
        PyMuPDF page.

    minimum_characters
        Character threshold.

    Returns
    -------
    tuple
        (is_text_page, character_count)
    """

    try:

        text = page.get_text("text")

    except Exception:

        return False, 0

    character_count = len(text.strip())

    return character_count >= minimum_characters, character_count


def _validate_input_pdf(path: Path) -> None:
    """
    Validate a PDF before inspection.
    """

    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() != ".pdf":
        raise ValueError(f"{path} is not a PDF")

    if path.stat().st_size == 0:
        raise ValueError(f"{path} is empty")


def _ensure_ocrmypdf_available() -> None:
    """
    Verify OCRmyPDF executable is available.
    """

    executable = shutil.which("ocrmypdf")

    if executable is None:
        raise OCRExecutableNotFoundError(
            "OCRmyPDF executable not found on PATH."
        )


###############################################################################
# PDF inspection
###############################################################################


def inspect_pdf(
    pdf_path: Path,
    config: OCRConfig = OCRConfig(),
) -> PDFInspection:
    """
    Analyse a PDF and determine whether OCR is required.

    The inspection phase uses PyMuPDF only and does not modify
    the document.

    Parameters
    ----------
    pdf_path
        PDF to inspect.

    config
        OCR configuration.

    Returns
    -------
    PDFInspection

    Raises
    ------
    PDFInspectionError
    """

    _validate_input_pdf(pdf_path)

    logger.info("Inspecting PDF %s", pdf_path)

    try:

        document = fitz.open(pdf_path)

    except Exception as exc:

        raise PDFInspectionError(
            f"Unable to open PDF: {pdf_path}"
        ) from exc

    pages: list[PageInspection] = []

    total_characters = 0

    total_images = 0

    digital_pages = 0

    scanned_pages = 0

    for page_number in range(len(document)):

        page = document.load_page(page_number)

        is_text_page, characters = _has_sufficient_text(
            page,
            config.invalidate_digital_threshold,
        )

        image_ratio = _page_image_ratio(page)

        image_count = len(page.get_images(full=True))

        drawing_count = len(page.get_drawings())

        if is_text_page:

            digital_pages += 1

        elif image_ratio >= config.image_ratio_threshold:

            scanned_pages += 1

        page_info = PageInspection(

            page_number=page_number + 1,

            text_characters=characters,

            image_count=image_count,

            drawing_count=drawing_count,

            width=page.rect.width,

            height=page.rect.height,

            is_text_page=is_text_page,

            image_area_ratio=image_ratio,

        )

        pages.append(page_info)

        total_characters += characters

        total_images += image_count

    is_digital = digital_pages >= scanned_pages

    needs_ocr = config.force_ocr or not is_digital

    inspection = PDFInspection(
        path=pdf_path,
        page_count=len(document),
        pages=pages,
        total_characters=total_characters,
        total_images=total_images,
        digital_pages=digital_pages,
        scanned_pages=scanned_pages,
        is_digital=is_digital,
        needs_ocr=needs_ocr,
        metadata=_safe_metadata(document),
        sha256=_sha256(pdf_path),
    )

    document.close()

    logger.info(
        "Inspection complete: pages=%d digital=%d scanned=%d needs_ocr=%s",
        inspection.page_count,
        inspection.digital_pages,
        inspection.scanned_pages,
        inspection.needs_ocr,
    )

    return inspection


###############################################################################
# OCR execution
###############################################################################


def _build_ocr_command(
    input_pdf: Path,
    output_pdf: Path,
    config: OCRConfig,
) -> list[str]:
    """
    Construct OCRmyPDF command line.
    """

    command = [
        "ocrmypdf",
        "--language",
        config.language,
        "--jobs",
        str(config.jobs),
        "--optimize",
        str(config.optimize),
        "--output-type",
        "pdf",
        "--dpi",
        str(config.dpi),
    ]

    if config.rotate_pages:
        command.append("--rotate-pages")

    if config.deskew:
        command.append("--deskew")

    if config.clean:
        command.append("--clean")

    if config.skip_text:
        command.append("--skip-text")

    command.extend(
        [
            str(input_pdf),
            str(output_pdf),
        ]
    )

    return command


def _run_ocr_command(
    command: list[str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """
    Execute an OCRmyPDF command.

    Parameters
    ----------
    command
        Fully constructed OCRmyPDF command.

    timeout
        Maximum execution time in seconds.

    Returns
    -------
    subprocess.CompletedProcess

    Raises
    ------
    OCRTimeoutError
        If OCR exceeds the configured timeout.

    OCRFailedError
        If OCRmyPDF returns a non-zero exit code.
    """

    logger.info("Running OCRmyPDF.")

    logger.debug("Command: %s", " ".join(command))

    try:

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    except subprocess.TimeoutExpired as exc:

        raise OCRTimeoutError(
            f"OCR exceeded timeout ({timeout} seconds)."
        ) from exc

    except OSError as exc:

        raise OCRFailedError(
            "Unable to execute OCRmyPDF."
        ) from exc

    if completed.returncode != 0:

        logger.error(
            "OCRmyPDF failed with exit code %s",
            completed.returncode,
        )

        if completed.stderr:
            logger.error(completed.stderr)

        raise OCRFailedError(
            completed.stderr.strip()
            if completed.stderr
            else "OCRmyPDF returned a non-zero exit status."
        )

    return completed


def _validate_output_pdf(path: Path) -> None:
    """
    Validate the OCR output.

    Parameters
    ----------
    path
        Output PDF path.

    Raises
    ------
    OCRFailedError
        If the output file is missing or invalid.
    """

    if not path.exists():

        raise OCRFailedError(
            "OCR completed but no output PDF was created."
        )

    if path.stat().st_size == 0:

        raise OCRFailedError(
            "OCR output PDF is empty."
        )

    try:

        document = fitz.open(path)

        page_count = len(document)

        document.close()

    except Exception as exc:

        raise OCRFailedError(
            "OCR output is not a valid PDF."
        ) from exc

    if page_count == 0:

        raise OCRFailedError(
            "OCR output PDF contains zero pages."
        )


def run_ocr(
    input_pdf: Path,
    output_pdf: Path,
    config: OCRConfig = OCRConfig(),
) -> Path:
    """
    Execute OCRmyPDF.

    Parameters
    ----------
    input_pdf
        Input PDF.

    output_pdf
        Output searchable PDF.

    config
        OCR configuration.

    Returns
    -------
    Path
        Output PDF.

    Raises
    ------
    OCRException
    """

    _ensure_ocrmypdf_available()

    _validate_input_pdf(input_pdf)

    command = _build_ocr_command(
        input_pdf=input_pdf,
        output_pdf=output_pdf,
        config=config,
    )

    start = time.perf_counter()

    completed = _run_ocr_command(
        command,
        timeout=config.timeout,
    )

    elapsed = time.perf_counter() - start

    logger.info(
        "OCR completed successfully in %.2f seconds.",
        elapsed,
    )

    if completed.stdout:

        logger.debug(completed.stdout)

    _validate_output_pdf(output_pdf)

    return output_pdf


def ensure_searchable_pdf(
    pdf_path: Path,
    *,
    output_directory: Path | None = None,
    config: OCRConfig = OCRConfig(),
) -> OCRResult:
    """
    Ensure a PDF is searchable.

    Digital-native PDFs are returned unchanged.

    Scanned PDFs are processed through OCRmyPDF.

    Parameters
    ----------
    pdf_path
        Input PDF.

    output_directory
        Optional directory for OCR output.

    config
        OCR configuration.

    Returns
    -------
    OCRResult
        Canonical OCR result used by downstream extraction.
    """

    inspection = inspect_pdf(
        pdf_path=pdf_path,
        config=config,
    )

    start = time.perf_counter()

    if not inspection.needs_ocr:

        logger.info(
            "Document already contains searchable text."
        )

        return OCRResult(
            original_pdf=pdf_path,
            processed_pdf=pdf_path,
            inspection=inspection,
            ocr_performed=False,
            elapsed_seconds=time.perf_counter() - start,
        )

    if output_directory is None:

        output_directory = Path(tempfile.mkdtemp())

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_pdf = (
        output_directory
        / f"{pdf_path.stem}_ocr.pdf"
    )

    run_ocr(
        input_pdf=pdf_path,
        output_pdf=output_pdf,
        config=config,
    )

    final_inspection = inspect_pdf(
        output_pdf,
        config=config,
    )

    return OCRResult(
        original_pdf=pdf_path,
        processed_pdf=output_pdf,
        inspection=final_inspection,
        ocr_performed=True,
        elapsed_seconds=time.perf_counter() - start,
    )


__all__ = [
    "OCRConfig",
    "OCRException",
    "OCRExecutableNotFoundError",
    "OCRFailedError",
    "OCRResult",
    "OCRTimeoutError",
    "PDFInspection",
    "PDFInspectionError",
    "PageInspection",
    "ensure_searchable_pdf",
    "inspect_pdf",
    "run_ocr",
]