from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    DerivativeAsset,
    DigitalObject,
    ExtractedObject,
    ExtractionPage,
    ExtractionPageSelection,
    ExtractionPageQualityAssessment,
    ExtractionRun,
    SourceRegistration,
)
from archive_workbench.identity import new_id
from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.structure_quality import structural_quality_metrics

ALGORITHM_VERSION = "page_quality_v2"
QUALITY_CLEAR = "clear"
QUALITY_ATTENTION = "attention"
QUALITY_CRITICAL = "critical"

_FLAG_LABELS = {
    "no_text": "No se reconoció texto suficiente.",
    "low_contrast": "La imagen tiene poco contraste.",
    "likely_blur": "La imagen parece desenfocada o con bordes débiles.",
    "very_dark": "La página es demasiado oscura.",
    "washed_out": "La página está muy clara o lavada.",
    "high_noise": "Se detectó ruido visual elevado.",
    "fragmented_text": "El texto aparece demasiado fragmentado.",
    "tiny_objects": "Hay demasiados objetos de uno o pocos caracteres.",
    "overlapping_boxes": "Varios bounding boxes se solapan de forma significativa.",
    "suspicious_symbols": "La salida contiene una proporción alta de símbolos sospechosos.",
    "legal_ordinal_review": "Hay números de artículo compatibles con ordinales mal reconocidos.",
    "checkbox_state_review": "Se detectaron casilleros o marcas cuyo estado requiere revisión visual.",
}

_SUGGESTIONS = {
    "no_text": "Comprobar orientación y comparar PSM 11 u OCR regional.",
    "low_contrast": "Probar escala de grises con autocontraste antes del OCR.",
    "likely_blur": "Revisar la resolución del derivado; evitar restauración generativa.",
    "very_dark": "Probar autocontraste o binarización Otsu conservadora.",
    "washed_out": "Probar autocontraste y revisar si el original tiene información recuperable.",
    "high_noise": "Probar reducción de ruido conservadora antes del OCR.",
    "fragmented_text": "Comparar granularidad párrafo y PSM 3, 4 o 6.",
    "tiny_objects": "Revisar layout, manchas y caracteres aislados antes de aceptar la corrida.",
    "overlapping_boxes": "Comparar otra corrida y revisar layout u orden de lectura.",
    "suspicious_symbols": "Comparar otra variante de imagen o perfil OCR.",
    "legal_ordinal_review": "Revisar los ordinales sobre la imagen; no corregirlos automáticamente.",
    "checkbox_state_review": "Confirmar cada casillero en la imagen y registrar marcado, no marcado o indeterminado.",
}


@dataclass(slots=True)
class PageQualityResult:
    assessment_id: str
    extraction_page_id: str
    status: str
    score: float
    metrics: dict[str, Any]
    flags: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    assessed_by: str = "system"
    assessed_at: datetime | None = None
    algorithm_version: str = ALGORITHM_VERSION

    @property
    def flag_messages(self) -> list[str]:
        return [_FLAG_LABELS.get(flag, flag) for flag in self.flags]


def _normalized_bbox(geometry: list[dict[str, Any]], page_number: int) -> tuple[float, float, float, float] | None:
    boxes: list[tuple[float, float, float, float]] = []
    for item in geometry or []:
        if int(item.get("page") or 0) != page_number:
            continue
        if item.get("coordinate_space") != "normalized":
            continue
        polygon = item.get("polygon") or []
        if len(polygon) < 4:
            continue
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
        left, right = max(0.0, min(xs)), min(1.0, max(xs))
        top, bottom = max(0.0, min(ys)), min(1.0, max(ys))
        if right > left and bottom > top:
            boxes.append((left, top, right, bottom))
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _iou(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _image_metrics(path: Path) -> dict[str, float | int]:
    with Image.open(path) as source:
        gray = ImageOps.grayscale(source)
        gray.thumbnail((1600, 1600))
        stats = ImageStat.Stat(gray)
        mean_brightness = stats.mean[0] / 255.0
        contrast = stats.stddev[0] / 127.5
        histogram = gray.histogram()
        pixels = max(1, sum(histogram))
        dark_ratio = sum(histogram[:32]) / pixels
        light_ratio = sum(histogram[224:]) / pixels
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_stats = ImageStat.Stat(edges)
        edge_mean = edge_stats.mean[0] / 255.0
        edge_variance = edge_stats.var[0] / (255.0 * 255.0)
        median = gray.filter(ImageFilter.MedianFilter(size=3))
        noise = ImageStat.Stat(ImageChops.difference(gray, median)).mean[0] / 255.0
        return {
            "image_width": int(source.width),
            "image_height": int(source.height),
            "mean_brightness": round(mean_brightness, 6),
            "contrast": round(contrast, 6),
            "dark_pixel_ratio": round(dark_ratio, 6),
            "light_pixel_ratio": round(light_ratio, 6),
            "edge_mean": round(edge_mean, 6),
            "edge_variance": round(edge_variance, 6),
            "noise_ratio": round(noise, 6),
        }


def _object_metrics(objects: list[ExtractedObject], page_number: int) -> dict[str, float | int]:
    texts = [str(item.original_text or "") for item in objects]
    stripped = [text.strip() for text in texts]
    visible = [char for text in stripped for char in text if not char.isspace()]
    object_count = len(objects)
    character_count = sum(len(text) for text in texts)
    nonempty = [text for text in stripped if text]
    tiny_ratio = sum(len(text) <= 3 for text in nonempty) / len(nonempty) if nonempty else 0.0
    short_ratio = sum(len(text) <= 12 for text in nonempty) / len(nonempty) if nonempty else 0.0
    suspicious = sum(
        not (char.isalnum() or char in ".,;:!?¿¡'\"()[]{}-/°ºª%+&@#—…")
        for char in visible
    )
    suspicious_ratio = suspicious / len(visible) if visible else 0.0
    boxes = [
        box
        for item in objects
        if (box := _normalized_bbox(list(item.geometry_json or []), page_number)) is not None
    ]
    overlapping: set[int] = set()
    for index, first in enumerate(boxes):
        for other_index in range(index + 1, len(boxes)):
            if _iou(first, boxes[other_index]) >= 0.15:
                overlapping.add(index)
                overlapping.add(other_index)
    overlap_ratio = len(overlapping) / len(boxes) if boxes else 0.0
    chars_per_object = character_count / object_count if object_count else 0.0
    return {
        "object_count": object_count,
        "character_count": character_count,
        "characters_per_object": round(chars_per_object, 3),
        "empty_object_count": sum(not text for text in stripped),
        "tiny_object_ratio": round(tiny_ratio, 6),
        "short_object_ratio": round(short_ratio, 6),
        "suspicious_symbol_ratio": round(suspicious_ratio, 6),
        "bbox_count": len(boxes),
        "overlapping_bbox_ratio": round(overlap_ratio, 6),
        "mean_confidence": round(
            mean([float(item.confidence) for item in objects if item.confidence is not None]), 6
        ) if any(item.confidence is not None for item in objects) else None,
    }


def evaluate_page_quality(*, image_path: Path, objects: list[ExtractedObject], page_number: int) -> tuple[str, float, dict[str, Any], list[str], list[str]]:
    metrics: dict[str, Any] = {"page_number": page_number}
    metrics.update(_image_metrics(image_path))
    metrics.update(_object_metrics(objects, page_number))
    metrics.update(structural_quality_metrics(objects, page_number=page_number))

    flags: list[str] = []
    if metrics["character_count"] < 20:
        flags.append("no_text")
    if metrics["contrast"] < 0.06 and metrics["edge_mean"] < 0.012:
        flags.append("low_contrast")
    if metrics["edge_variance"] < 0.004 and metrics["character_count"] >= 20:
        flags.append("likely_blur")
    if metrics["mean_brightness"] < 0.22 or metrics["dark_pixel_ratio"] > 0.55:
        flags.append("very_dark")
    if (
        metrics["mean_brightness"] > 0.97
        and metrics["light_pixel_ratio"] > 0.96
        and metrics["edge_mean"] < 0.01
    ):
        flags.append("washed_out")
    if metrics["noise_ratio"] > 0.055:
        flags.append("high_noise")
    if metrics["object_count"] >= 8 and metrics["characters_per_object"] < 18:
        flags.append("fragmented_text")
    if metrics["tiny_object_ratio"] > 0.25 and metrics["object_count"] >= 4:
        flags.append("tiny_objects")
    if metrics["overlapping_bbox_ratio"] > 0.20 and metrics["bbox_count"] >= 3:
        flags.append("overlapping_boxes")
    if metrics["suspicious_symbol_ratio"] > 0.08 and metrics["character_count"] >= 20:
        flags.append("suspicious_symbols")
    if metrics["legal_ordinal_candidate_count"]:
        flags.append("legal_ordinal_review")
    if metrics["checkbox_candidate_count"]:
        flags.append("checkbox_state_review")

    penalties = {
        "no_text": 0.55,
        "low_contrast": 0.14,
        "likely_blur": 0.16,
        "very_dark": 0.20,
        "washed_out": 0.15,
        "high_noise": 0.12,
        "fragmented_text": 0.10,
        "tiny_objects": 0.10,
        "overlapping_boxes": 0.12,
        "suspicious_symbols": 0.12,
        "legal_ordinal_review": 0.04,
        "checkbox_state_review": 0.04,
    }
    score = max(0.0, min(1.0, 1.0 - sum(penalties[flag] for flag in flags)))
    if "no_text" in flags or score < 0.40:
        status = QUALITY_CRITICAL
    elif flags or score < 0.75:
        status = QUALITY_ATTENTION
    else:
        status = QUALITY_CLEAR
    suggestions = list(dict.fromkeys(_SUGGESTIONS[flag] for flag in flags))
    return status, round(score, 6), metrics, flags, suggestions


def _asset_path(session: Session, *, project_root: Path, page: ExtractionPage) -> Path:
    asset = session.get(DerivativeAsset, page.source_asset_id) if page.source_asset_id else None
    if asset is None:
        raise ValueError("La página no tiene una imagen derivada vinculada")
    path = project_root / asset.relative_path
    if not path.is_file():
        raise ValueError(f"No se encontró la imagen derivada: {asset.relative_path}")
    return path


def latest_page_quality_assessment(
    session: Session, extraction_page_id: str
) -> PageQualityResult | None:
    row = session.scalar(
        select(ExtractionPageQualityAssessment)
        .where(
            ExtractionPageQualityAssessment.extraction_page_id == extraction_page_id,
            ExtractionPageQualityAssessment.is_current.is_(True),
        )
        .order_by(ExtractionPageQualityAssessment.assessed_at.desc())
    )
    if row is None:
        return None
    return PageQualityResult(
        assessment_id=row.id,
        extraction_page_id=row.extraction_page_id,
        status=row.status,
        score=row.score,
        metrics=dict(row.metrics_json or {}),
        flags=list(row.flags_json or []),
        suggestions=list(row.suggestions_json or []),
        assessed_by=row.assessed_by,
        assessed_at=row.assessed_at,
        algorithm_version=row.algorithm_version,
    )


def assess_extraction_page_quality(
    session: Session,
    *,
    project_root: str | Path,
    extraction_page_id: str,
    assessed_by: str,
) -> PageQualityResult:
    page = session.get(ExtractionPage, extraction_page_id)
    if page is None:
        raise ValueError("Página de extracción inexistente")
    objects = list(
        session.scalars(
            select(ExtractedObject)
            .where(
                ExtractedObject.extraction_run_id == page.extraction_run_id,
                ExtractedObject.page_number == page.page_number,
            )
            .order_by(ExtractedObject.order_index, ExtractedObject.id)
        ).all()
    )
    path = _asset_path(session, project_root=Path(project_root).resolve(), page=page)
    status, score, metrics, flags, suggestions = evaluate_page_quality(
        image_path=path,
        objects=objects,
        page_number=page.page_number,
    )
    session.execute(
        update(ExtractionPageQualityAssessment)
        .where(
            ExtractionPageQualityAssessment.extraction_page_id == page.id,
            ExtractionPageQualityAssessment.is_current.is_(True),
        )
        .values(is_current=False)
    )
    row = ExtractionPageQualityAssessment(
        id=new_id(),
        extraction_page_id=page.id,
        algorithm_version=ALGORITHM_VERSION,
        status=status,
        score=score,
        metrics_json=metrics,
        flags_json=flags,
        suggestions_json=suggestions,
        is_current=True,
        assessed_by=assessed_by or "local_user",
    )
    session.add(row)
    session.flush()
    return latest_page_quality_assessment(session, page.id)  # type: ignore[return-value]

def assess_source_page_quality(
    session: Session,
    *,
    project_root: str | Path,
    source_key: str,
    pages: set[int] | None,
    run_id: str | None,
    assessed_by: str,
) -> list[PageQualityResult]:
    digital = session.scalar(
        select(DigitalObject)
        .join(SourceRegistration, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            SourceRegistration.source_key == source_key,
        )
    )
    if digital is None:
        raise ValueError(f"source_key no registrado: {source_key}")

    requested = set(pages or [])
    if run_id:
        run = session.get(ExtractionRun, run_id)
        if run is None or run.digital_object_id != digital.id:
            raise ValueError("La corrida no pertenece al documento indicado")
        statement = select(ExtractionPage).where(
            ExtractionPage.extraction_run_id == run.id
        )
        if requested:
            statement = statement.where(ExtractionPage.page_number.in_(requested))
        targets = list(session.scalars(statement.order_by(ExtractionPage.page_number)).all())
    else:
        statement = (
            select(ExtractionPage)
            .join(
                ExtractionPageSelection,
                ExtractionPageSelection.extraction_page_id == ExtractionPage.id,
            )
            .where(ExtractionPageSelection.digital_object_id == digital.id)
        )
        if requested:
            statement = statement.where(ExtractionPageSelection.page_number.in_(requested))
        targets = list(session.scalars(statement.order_by(ExtractionPage.page_number)).all())

    if requested:
        found = {item.page_number for item in targets}
        missing = requested - found
        if missing:
            raise ValueError(
                "No se encontraron las páginas solicitadas en esa versión: "
                + ", ".join(map(str, sorted(missing)))
            )
    if not targets:
        raise ValueError(
            "No hay páginas para evaluar. Indicá --run-id o seleccioná una extracción canónica."
        )
    return [
        assess_extraction_page_quality(
            session,
            project_root=project_root,
            extraction_page_id=item.id,
            assessed_by=assessed_by,
        )
        for item in targets
    ]
