"""Bound work before decoding/rendering; native metadata parsing still needs isolation.

The synchronous Python APIs are useful to trusted callers. The supported local
CLI/server invoke them in workers with wall, CPU and address-space limits.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import stat
import warnings
from typing import Any


class ResourceLimitError(ValueError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class SourcePolicy:
    source_bytes: int = 20 * 1024 * 1024
    reference_bytes: int = 12 * 1024 * 1024
    aggregate_bytes: int = 32 * 1024 * 1024
    pixels: int = 16_000_000
    aggregate_pixels: int = 32_000_000
    decoded_bytes: int = 128 * 1024 * 1024
    aggregate_decoded_bytes: int = 256 * 1024 * 1024
    dimension_px: int = 20_000
    pdf_pages: int = 64
    min_dpi: float = 36
    max_dpi: float = 300
    pdf_dimension_pt: float = 14_400
    sections: int = 300
    trace_rows: int = 4_000_000
    table_cells: int = 512
    cell_pixels: int = 4_000_000
    aggregate_cell_pixels: int = 32_000_000


DEFAULT_POLICY = SourcePolicy()
IMAGE_EXTENSIONS = {'PNG': '.png', 'JPEG': '.jpg', 'TIFF': '.tiff', 'BMP': '.bmp', 'WEBP': '.webp'}


def _reject(message: str, kind: str = 'resource_limit') -> None:
    raise ResourceLimitError(kind, message)


def _finite(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def source_extension(header: bytes) -> str:
    """Cheap content routing only. Full parser validation happens in the worker."""
    if header.startswith(b'%PDF-'):
        return '.pdf'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if header.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if header[:4] in (b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+'):
        return '.tiff'
    if header.startswith(b'BM'):
        return '.bmp'
    if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
        return '.webp'
    _reject('Use a supported PNG, JPEG, TIFF, BMP, WebP image or PDF.', 'unsupported_source')


def _pixel_budget(width: int, height: int, policy: SourcePolicy) -> dict:
    if width < 1 or height < 1 or max(width, height) > policy.dimension_px:
        _reject('Source dimensions exceed the configured pixel dimension limit.')
    pixels = width * height
    # Budget full colour plus simultaneous conversion; kernel/NumPy memory is
    # additionally constrained by the worker, not inferred solely from pixels.
    decoded = pixels * 8
    if pixels > policy.pixels or decoded > policy.decoded_bytes:
        _reject('Source exceeds the configured pixel or decoded-byte budget.')
    return {'width_px': width, 'height_px': height, 'pixels': pixels, 'decoded_bytes_estimate': decoded}


def inspect_source(path: Path, settings: dict, *, role: str = 'source', policy: SourcePolicy = DEFAULT_POLICY) -> dict:
    """Inspect bounded metadata, without rendering PDFs or decoding image arrays.

    Even metadata libraries parse untrusted bytes. Call inside the isolated worker
    when handling an untrusted document; this function is not an OS sandbox.
    """
    if not isinstance(settings, dict):
        _reject('Source settings must be an object.', 'invalid_source')
    path = Path(path)
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            _reject('Source must be a regular file.', 'invalid_source')
        maximum = policy.reference_bytes if role == 'station_reference' else policy.source_bytes
        if not 0 < info.st_size <= maximum:
            _reject(f'{role} exceeds the configured file-byte budget.')
        with path.open('rb') as stream:
            extension = source_extension(stream.read(16))
    except OSError as exc:
        raise ResourceLimitError('unreadable_source', 'Source could not be read.') from exc
    record = {'role': role, 'file_bytes': info.st_size}
    if extension == '.pdf':
        dpi = settings.get('render_dpi', 144)
        page_index = settings.get('page_index', 0)
        if not _finite(dpi) or not policy.min_dpi <= dpi <= policy.max_dpi:
            _reject(f'PDF render_dpi must be finite and in {policy.min_dpi:g}..{policy.max_dpi:g}.')
        if not isinstance(page_index, int) or isinstance(page_index, bool) or page_index < 0:
            _reject('PDF page_index must be a nonnegative integer.', 'invalid_source')
        try:
            import fitz
        except ImportError as exc:
            raise ResourceLimitError('missing_dependency', 'PDF support requires the optional documents dependencies.') from exc
        try:
            with fitz.open(path) as document:
                if document.needs_pass:
                    _reject('Encrypted PDFs are not supported.', 'unsupported_source')
                if not 1 <= document.page_count <= policy.pdf_pages:
                    _reject('PDF page count exceeds the configured budget.')
                if page_index >= document.page_count:
                    _reject('Selected PDF page does not exist.', 'invalid_source')
                # Check every page dimension so a reference/thumbnail cannot later
                # select an unchecked oversized page. This loop is bounded above.
                selected = None
                for index in range(document.page_count):
                    rect = document[index].rect
                    dimensions = (float(rect.width), float(rect.height))
                    if any(not math.isfinite(d) or d <= 0 or d > policy.pdf_dimension_pt for d in dimensions):
                        _reject('PDF page dimensions exceed the configured budget.')
                    if index == page_index:
                        selected = dimensions
                width, height = (math.ceil(d * float(dpi) / 72) for d in selected)
                record.update(kind='pdf', format='PDF', page_count=document.page_count, page_index=page_index, render_dpi=float(dpi))
                record.update(_pixel_budget(width, height, policy))
        except ResourceLimitError:
            raise
        except Exception as exc:
            raise ResourceLimitError('unreadable_source', 'PDF metadata could not be read.') from exc
    else:
        try:
            from PIL import Image
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    if image.format not in IMAGE_EXTENSIONS:
                        _reject('Image format is not supported.', 'unsupported_source')
                    record.update(kind='raster', format=image.format)
                    record.update(_pixel_budget(image.width, image.height, policy))
                    # Only the first frame was used historically; reject hidden
                    # additional frames instead of implying they were inspected.
                    if getattr(image, 'n_frames', 1) != 1:
                        _reject('Multi-frame raster documents are unsupported; provide one selected page.', 'unsupported_source')
                    image.verify()
        except ResourceLimitError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ResourceLimitError('resource_limit', 'Image decompression dimensions exceed the safety limit.') from exc
        except Exception as exc:
            raise ResourceLimitError('unreadable_source', 'Image metadata or file structure could not be read.') from exc
    return record


def _roi(value: Any, width: int, height: int) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4 or not all(_finite(v) and int(v) == v for v in value):
        _reject('Regions must contain four finite integer pixel coordinates.', 'invalid_region')
    left, top, right, bottom = map(int, value)
    if not 0 <= left < right <= width or not 0 <= top < bottom <= height:
        _reject('A declared region lies outside the selected source page.', 'invalid_region')
    return left, top, right, bottom


def validate_sources(spec: dict, base_dir: Path, policy: SourcePolicy = DEFAULT_POLICY) -> dict:
    """Preflight primary, reference and aggregate work before any preview/inference."""
    if not isinstance(spec, dict):
        _reject('Specification must be an object.', 'invalid_source')
    records = {}
    for role in ('source', 'station_reference'):
        source = spec.get(role)
        if source is None and role == 'station_reference':
            continue
        if not isinstance(source, dict) or not isinstance(source.get('file'), str) or not source['file']:
            _reject(f'{role}.file must name a document.', 'invalid_source')
        records[role] = inspect_source(Path(base_dir) / source['file'], source, role=role, policy=policy)
    for key, maximum in (('file_bytes', policy.aggregate_bytes), ('pixels', policy.aggregate_pixels), ('decoded_bytes_estimate', policy.aggregate_decoded_bytes)):
        if sum(record[key] for record in records.values()) > maximum:
            _reject(f'Combined sources exceed the configured {key} budget.')
    sections = spec.get('sections', [])
    if not isinstance(sections, list) or len(sections) > policy.sections:
        _reject('Section count exceeds the configured job budget.')
    source = records['source']
    width, height = source['width_px'], source['height_px']
    rows = cells = cell_pixels = 0
    for section in sections:
        if not isinstance(section, dict):
            _reject('Each section must be an object.', 'invalid_region')
        if 'roi_px' in section:
            left, top, right, bottom = _roi(section['roi_px'], width, height)
            rows += bottom - top
        if spec.get('input_mode') == 'offset_table_ocr':
            entries = section.get('cells', [])
            if not isinstance(entries, list):
                _reject('Table cells must be a list.', 'invalid_region')
            cells += len(entries)
            if cells > policy.table_cells:
                _reject('Table cell count exceeds the configured whole-job budget.')
            for cell in entries:
                if not isinstance(cell, dict):
                    _reject('Each table cell must be an object.', 'invalid_region')
                left, top, right, bottom = _roi(cell.get('roi_px'), width, height)
                factor = max(1, math.ceil(120 / (bottom - top)))
                expanded = ((right - left) * factor + 36) * ((bottom - top) * factor + 36)
                if expanded > policy.cell_pixels:
                    _reject('An enlarged OCR crop exceeds the per-cell pixel budget.')
                cell_pixels += expanded
    if rows > policy.trace_rows or cell_pixels > policy.aggregate_cell_pixels:
        _reject('Combined trace/OCR work exceeds the whole-job budget.')
    records['work'] = {'trace_rows': rows, 'table_cells': cells, 'expanded_cell_pixels': cell_pixels}
    records['policy'] = asdict(policy)
    return records
