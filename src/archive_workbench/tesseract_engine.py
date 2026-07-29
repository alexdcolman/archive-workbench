from __future__ import annotations

import csv
import io
import json
import math
import shutil
import subprocess
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from PIL import Image, ImageOps

from archive_workbench.contracts.extraction import ExtractedObjectRecord, PageGeometry
from archive_workbench.identity import stable_id
from uuid import NAMESPACE_URL


@dataclass(slots=True)
class TesseractLine:
    block_num: int
    paragraph_num: int
    line_num: int
    text: str
    left: int
    top: int
    right: int
    bottom: int
    confidence: float | None
    word_count: int


@dataclass(slots=True)
class TesseractPageResult:
    page_number: int
    width: int
    height: int
    psm: int
    image_variant: str
    lines: list[TesseractLine]
    full_text: str
    tsv_text: str
    command: list[str]
    stderr: str


def otsu_threshold(image: Image.Image) -> int:
    histogram = image.histogram()
    total = sum(histogram)
    if total == 0:
        return 127
    weighted_sum = sum(index * count for index, count in enumerate(histogram))
    background_weight = 0
    background_sum = 0.0
    best_variance = -1.0
    best_threshold = 127
    for threshold, count in enumerate(histogram):
        background_weight += count
        if background_weight == 0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight == 0:
            break
        background_sum += threshold * count
        background_mean = background_sum / background_weight
        foreground_mean = (weighted_sum - background_sum) / foreground_weight
        between = background_weight * foreground_weight * (background_mean - foreground_mean) ** 2
        if between > best_variance:
            best_variance = between
            best_threshold = threshold
    return best_threshold


def prepare_image_variant(source: Path, destination: Path, variant: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if variant == "original":
        try:
            destination.hardlink_to(source)
        except OSError:
            shutil.copy2(source, destination)
        return destination

    with Image.open(source) as image:
        gray = ImageOps.grayscale(image)
        gray = ImageOps.autocontrast(gray)
        if variant == "grayscale_autocontrast":
            output = gray
        elif variant == "otsu":
            threshold = otsu_threshold(gray)
            output = gray.point(lambda value: 255 if value > threshold else 0, mode="1")
        else:
            raise ValueError(f"Variante de imagen desconocida: {variant}")
        output.save(destination, format="PNG", optimize=False)
    return destination


def _integer(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default) or default))
    except (TypeError, ValueError):
        return default


def _float(row: dict[str, str], key: str) -> float | None:
    try:
        value = float(row.get(key, ""))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def parse_tesseract_tsv(tsv_text: str) -> list[TesseractLine]:
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t", quoting=csv.QUOTE_NONE)
    groups: OrderedDict[tuple[int, int, int], list[dict[str, Any]]] = OrderedDict()
    for row in reader:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        level = _integer(row, "level")
        if level not in {0, 5}:
            continue
        key = (
            _integer(row, "block_num"),
            _integer(row, "par_num"),
            _integer(row, "line_num"),
        )
        left = _integer(row, "left")
        top = _integer(row, "top")
        width = max(0, _integer(row, "width"))
        height = max(0, _integer(row, "height"))
        groups.setdefault(key, []).append(
            {
                "text": text,
                "left": left,
                "top": top,
                "right": left + width,
                "bottom": top + height,
                "confidence": _float(row, "conf"),
                "word_num": _integer(row, "word_num"),
            }
        )

    lines: list[TesseractLine] = []
    for (block_num, paragraph_num, line_num), words in groups.items():
        words.sort(key=lambda item: (item["word_num"], item["left"]))
        confidences = [item["confidence"] for item in words if item["confidence"] is not None]
        lines.append(
            TesseractLine(
                block_num=block_num,
                paragraph_num=paragraph_num,
                line_num=line_num,
                text=" ".join(item["text"] for item in words),
                left=min(item["left"] for item in words),
                top=min(item["top"] for item in words),
                right=max(item["right"] for item in words),
                bottom=max(item["bottom"] for item in words),
                confidence=mean(confidences) if confidences else None,
                word_count=len(words),
            )
        )
    return lines


def run_tesseract_page(
    image_path: Path,
    *,
    page_number: int,
    tesseract_command: str,
    languages: list[str],
    psm: int,
    image_variant: str,
    timeout_seconds: int,
) -> TesseractPageResult:
    command = [
        tesseract_command,
        str(image_path),
        "stdout",
        "-l",
        "+".join(languages),
        "--psm",
        str(psm),
        "tsv",
    ]
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"No se encontró '{tesseract_command}' en PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Tesseract superó {timeout_seconds} segundos en la página {page_number}"
        ) from exc
    if result.returncode != 0:
        diagnostic = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"Tesseract terminó con código {result.returncode} en página {page_number}: {diagnostic}"
        )

    with Image.open(image_path) as image:
        width, height = image.size
    lines = parse_tesseract_tsv(result.stdout)
    return TesseractPageResult(
        page_number=page_number,
        width=width,
        height=height,
        psm=psm,
        image_variant=image_variant,
        lines=lines,
        full_text="\n".join(line.text for line in lines),
        tsv_text=result.stdout,
        command=command,
        stderr=result.stderr or "",
    )


def result_to_json(result: TesseractPageResult) -> dict[str, Any]:
    return {
        "engine": "tesseract_tsv",
        "page": result.page_number,
        "width": result.width,
        "height": result.height,
        "psm": result.psm,
        "image_variant": result.image_variant,
        "command": result.command,
        "stderr": result.stderr,
        "full_text": result.full_text,
        "lines": [
            {
                "block_num": line.block_num,
                "paragraph_num": line.paragraph_num,
                "line_num": line.line_num,
                "text": line.text,
                "bbox": [line.left, line.top, line.right, line.bottom],
                "confidence": line.confidence,
                "word_count": line.word_count,
            }
            for line in result.lines
        ],
    }


def normalize_tesseract_result(
    result: TesseractPageResult,
    *,
    digital_object_id: str,
    extraction_run_id: str,
    order_start: int = 0,
    granularity: str = "line",
) -> list[ExtractedObjectRecord]:
    if granularity not in {"line", "paragraph"}:
        raise ValueError(f"Granularidad Tesseract desconocida: {granularity}")

    if granularity == "line":
        groups: list[tuple[tuple[int, int, int], list[TesseractLine]]] = [
            ((line.block_num, line.paragraph_num, line.line_num), [line])
            for line in result.lines
        ]
    else:
        grouped: OrderedDict[tuple[int, int, int], list[TesseractLine]] = OrderedDict()
        for line in result.lines:
            key = (line.block_num, line.paragraph_num, 0)
            grouped.setdefault(key, []).append(line)
        groups = list(grouped.items())

    records: list[ExtractedObjectRecord] = []
    for index, ((block_num, paragraph_num, line_num), lines) in enumerate(groups):
        left = min(line.left for line in lines)
        top = min(line.top for line in lines)
        right = max(line.right for line in lines)
        bottom = max(line.bottom for line in lines)
        confidences = [line.confidence for line in lines if line.confidence is not None]
        confidence = mean(confidences) / 100.0 if confidences else None
        text = "\n".join(line.text for line in lines)
        object_id = stable_id(
            NAMESPACE_URL,
            "archive-workbench",
            digital_object_id,
            result.page_number,
            "tesseract",
            result.psm,
            result.image_variant,
            granularity,
            block_num,
            paragraph_num,
            line_num,
        )
        polygon = [
            (left / result.width, top / result.height),
            (right / result.width, top / result.height),
            (right / result.width, bottom / result.height),
            (left / result.width, bottom / result.height),
        ]
        records.append(
            ExtractedObjectRecord(
                object_id=object_id,
                digital_object_id=digital_object_id,
                extraction_run_id=extraction_run_id,
                order_index=order_start + index,
                object_type="paragraph",
                original_text=text,
                geometry=[PageGeometry(page=result.page_number, polygon=polygon)],
                source_label=(
                    "tesseract_paragraph" if granularity == "paragraph" else "tesseract_line"
                ),
                confidence=confidence,
                language=None,
                attributes={
                    "backend": "tesseract_tsv",
                    "psm": result.psm,
                    "image_variant": result.image_variant,
                    "granularity": granularity,
                    "block_num": block_num,
                    "paragraph_num": paragraph_num,
                    "line_num": line_num if granularity == "line" else None,
                    "line_count": len(lines),
                    "line_texts": [line.text for line in lines],
                    "word_count": sum(line.word_count for line in lines),
                },
            )
        )
    return records


def text_quality_metrics(text: str, lines: list[TesseractLine]) -> dict[str, float | int | None]:
    visible = [char for char in text if not char.isspace()]
    character_count = len(text)
    word_count = sum(line.word_count for line in lines)
    confidences = [line.confidence for line in lines if line.confidence is not None]
    mean_confidence = mean(confidences) if confidences else None
    high_confidence_ratio = (
        sum(confidence >= 70 for confidence in confidences) / len(confidences)
        if confidences
        else None
    )
    alphanumeric_ratio = (
        sum(char.isalnum() for char in visible) / len(visible) if visible else 0.0
    )
    suspicious = sum(
        not (char.isalnum() or char in ".,;:!?¿¡'\"()[]{}-/°ºª%+&@#") for char in visible
    )
    suspicious_symbol_ratio = suspicious / len(visible) if visible else 0.0
    confidence_component = (mean_confidence or 0.0) / 100.0
    high_component = high_confidence_ratio or 0.0
    volume_component = min(math.log1p(word_count) / math.log1p(120), 1.0)
    heuristic_score = (
        0.45 * confidence_component
        + 0.20 * high_component
        + 0.20 * alphanumeric_ratio
        + 0.15 * volume_component
        - 0.25 * suspicious_symbol_ratio
    )
    heuristic_score = min(max(heuristic_score, 0.0), 1.0)
    return {
        "character_count": character_count,
        "word_count": word_count,
        "line_count": len(lines),
        "mean_confidence": mean_confidence,
        "high_confidence_ratio": high_confidence_ratio,
        "alphanumeric_ratio": alphanumeric_ratio,
        "suspicious_symbol_ratio": suspicious_symbol_ratio,
        "heuristic_score": heuristic_score,
    }


def write_tesseract_raw(result: TesseractPageResult, raw_dir: Path) -> tuple[Path, Path, Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    stem = f"page_{result.page_number:04d}"
    json_path = raw_dir / f"{stem}.json"
    tsv_path = raw_dir / f"{stem}.tsv"
    text_path = raw_dir / f"{stem}.txt"
    json_path.write_text(json.dumps(result_to_json(result), ensure_ascii=False, indent=2), encoding="utf-8")
    tsv_path.write_text(result.tsv_text, encoding="utf-8")
    text_path.write_text(result.full_text, encoding="utf-8")
    return json_path, tsv_path, text_path
