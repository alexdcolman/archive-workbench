from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from PIL import Image, ImageOps

from archive_workbench.preprocessing_dewarp import (
    DewarpEstimate,
    apply_estimated_dewarp,
    estimate_vertical_dewarp,
    render_dewarp_diagnostic,
)
from archive_workbench.tesseract_engine import otsu_threshold


GEOMETRY_MODE_LABELS = {
    "none": "Sin corrección geométrica",
    "conservative": "Orientación, inclinación y líneas (conservador)",
    "conservative_dewarp": "Orientación, inclinación, curvatura y líneas (conservador)",
}


@dataclass(slots=True)
class GeometryResult:
    image: Image.Image
    mask: Image.Image
    orientation_detected: int = 0
    orientation_confidence: float = 0.0
    orientation_applied: int = 0
    orientation_min_confidence: float = 0.0
    deskew_detected_angle: float = 0.0
    deskew_angle: float = 0.0
    deskew_confidence: float = 0.0
    deskew_min_confidence: float = 0.0
    lines_detected: int = 0
    lines_removed: int = 0
    removed_pixels: int = 0
    dewarp: DewarpEstimate | None = None
    dewarp_diagnostic: Image.Image | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def analysis(self) -> dict[str, Any]:
        return {
            "algorithm_version": "geometry_conservative_v2",
            "orientation_detected": self.orientation_detected,
            "orientation_confidence": round(self.orientation_confidence, 6),
            "orientation_min_confidence": round(self.orientation_min_confidence, 6),
            "deskew_detected_angle": round(self.deskew_detected_angle, 3),
            "deskew_angle": round(self.deskew_angle, 3),
            "deskew_confidence": round(self.deskew_confidence, 6),
            "deskew_min_confidence": round(self.deskew_min_confidence, 6),
            "lines_detected": self.lines_detected,
            "lines_removed": self.lines_removed,
            "removed_pixels": self.removed_pixels,
            **(self.dewarp.analysis if self.dewarp is not None else {
                "dewarp_detected": False,
                "dewarp_applied": False,
                "dewarp_confidence": 0.0,
                "dewarp_support_strips": 0,
                "dewarp_total_strips": 0,
                "dewarp_max_displacement_px": 0.0,
                "dewarp_max_displacement_ratio": 0.0,
                "dewarp_fit_quality": 0.0,
                "dewarp_median_improvement": 0.0,
                "dewarp_curvature_ratio": 0.0,
                "dewarp_coefficients": [0.0, 0.0, 0.0],
                "dewarp_reason": "disabled",
                "dewarp_strip_offsets": [],
            }),
        }

    @property
    def transformations(self) -> dict[str, Any]:
        return {
            "orientation": {
                "applied": bool(self.orientation_applied),
                "candidate_degrees": self.orientation_detected,
                "rotation_degrees": self.orientation_applied,
                "confidence": round(self.orientation_confidence, 6),
                "threshold": round(self.orientation_min_confidence, 6),
                "reason": (
                    "confidence_above_threshold"
                    if self.orientation_applied
                    else (
                        "confidence_below_threshold"
                        if self.orientation_detected
                        else "no_rotation_candidate"
                    )
                ),
            },
            "deskew": {
                "applied": abs(self.deskew_angle) > 0.001,
                "candidate_degrees": round(self.deskew_detected_angle, 3),
                "rotation_degrees": round(self.deskew_angle, 3),
                "confidence": round(self.deskew_confidence, 6),
                "threshold": round(self.deskew_min_confidence, 6),
                "reason": (
                    "confidence_above_threshold"
                    if abs(self.deskew_angle) > 0.001
                    else (
                        "confidence_below_threshold"
                        if abs(self.deskew_detected_angle) >= 0.4
                        else "no_skew_candidate"
                    )
                ),
            },
            "dewarp": (
                self.dewarp.transformation
                if self.dewarp is not None
                else {
                    "applied": False,
                    "detected": False,
                    "confidence": 0.0,
                    "max_displacement_px": 0.0,
                    "support_strips": 0,
                    "fit_quality": 0.0,
                    "curvature_ratio": 0.0,
                    "coefficients": [0.0, 0.0, 0.0],
                    "reason": "disabled",
                }
            ),
            "line_removal": {
                "applied": self.lines_removed > 0,
                "lines_removed": self.lines_removed,
                "removed_pixels": self.removed_pixels,
                "reason": (
                    "conservative_candidates_removed"
                    if self.lines_removed
                    else "no_safe_line_candidates"
                ),
            },
        }


def _pixel_values(image: Image.Image) -> list[int]:
    getter = getattr(image, "get_flattened_data", None)
    if getter is not None:
        return list(getter())
    return list(image.getdata())

def _working_gray(image: Image.Image, *, max_edge: int = 900) -> Image.Image:
    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    longest = max(gray.size)
    if longest > max_edge:
        scale = max_edge / longest
        gray = gray.resize(
            (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))),
            Image.Resampling.BILINEAR,
        )
    return gray


def _ink_matrix(image: Image.Image) -> tuple[list[list[int]], int, int, int]:
    gray = _working_gray(image)
    threshold = otsu_threshold(gray)
    # Evita convertir ruido claro en tinta en páginas casi blancas.
    threshold = min(threshold, 210)
    pixels = _pixel_values(gray)
    width, height = gray.size
    matrix = [
        [1 if pixels[y * width + x] <= threshold else 0 for x in range(width)]
        for y in range(height)
    ]
    return matrix, width, height, sum(sum(row) for row in matrix)


def _projection_score(image: Image.Image) -> tuple[float, float, float]:
    matrix, width, height, total = _ink_matrix(image)
    if total < max(24, width * height * 0.0003):
        return 0.0, 0.0, 0.0
    rows = [sum(row) for row in matrix]
    cols = [sum(matrix[y][x] for y in range(height)) for x in range(width)]

    row_blank = sum(value == 0 for value in rows) / max(1, height)
    col_blank = sum(value == 0 for value in cols) / max(1, width)
    row_groups = len(_candidate_groups([value > 1 for value in rows]))
    col_groups = len(_candidate_groups([value > 1 for value in cols]))
    group_balance = (col_groups - row_groups) / max(1, col_groups + row_groups)
    horizontalness = 5.0 * (row_blank - col_blank) + group_balance

    y_centroid = sum((index + 0.5) * value for index, value in enumerate(rows)) / total / height
    x_centroid = sum((index + 0.5) * value for index, value in enumerate(cols)) / total / width
    top_bias = max(-0.5, min(0.5, 0.5 - y_centroid))
    left_bias = max(-0.5, min(0.5, 0.5 - x_centroid))
    score = 3.0 * horizontalness + 0.9 * top_bias + 0.08 * left_bias
    return score, horizontalness, total / (width * height)


def detect_orientation(image: Image.Image) -> tuple[int, float, dict[int, float]]:
    # Se trabaja sobre una copia reducida: los originales grandes nunca se convierten en
    # matrices Python completas solo para decidir su orientación.
    work = _working_gray(image, max_edge=900).convert("RGB")
    # Se neutralizan primero marcos y líneas largas para que no dominen la dirección del texto.
    cleaned, _mask, _detected, _removed, _pixels = remove_long_lines(
        work,
        min_length_ratio=0.55,
        max_thickness_px=10,
        max_intersection_ratio=0.06,
    )
    scores: dict[int, float] = {}
    for angle in (0, 90, 180, 270):
        candidate = cleaned if angle == 0 else cleaned.rotate(angle, expand=True, fillcolor="white")
        score, _row_mod, density = _projection_score(candidate)
        if density <= 0.0:
            scores[angle] = 0.0
        else:
            scores[angle] = score
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_angle, best_score = ranked[0]
    second_score = ranked[1][1]
    perpendicular = max(
        score
        for angle, score in scores.items()
        if (angle - best_angle) % 180 == 90
    )
    direction_margin = max(0.0, best_score - second_score)
    axis_margin = max(0.0, best_score - perpendicular)
    direction_confidence = min(1.0, direction_margin / 0.5)
    axis_confidence = min(1.0, axis_margin / 1.0)
    confidence = min(direction_confidence, axis_confidence)
    return best_angle, confidence, scores


def _deskew_score(image: Image.Image) -> float:
    matrix, width, height, total = _ink_matrix(image)
    if total < max(24, width * height * 0.0003):
        return 0.0
    rows = [sum(row) for row in matrix]
    # La energía cuadrática de las proyecciones aumenta cuando las líneas quedan horizontales.
    return sum(value * value for value in rows) / (total * total + 1.0)


def detect_deskew(
    image: Image.Image,
    *,
    max_degrees: float,
    step: float = 0.5,
) -> tuple[float, float, dict[float, float]]:
    work = _working_gray(image, max_edge=1000)
    angles: list[float] = []
    current = -max_degrees
    while current <= max_degrees + 1e-9:
        angles.append(round(current, 3))
        current += step
    if 0.0 not in angles:
        angles.append(0.0)
    scores: dict[float, float] = {}
    for angle in sorted(set(angles)):
        candidate = (
            work
            if abs(angle) < 1e-9
            else work.rotate(angle, expand=True, resample=Image.Resampling.BILINEAR, fillcolor=255)
        )
        scores[angle] = _deskew_score(candidate)
    best_angle, best_score = max(scores.items(), key=lambda item: item[1])
    base_score = scores.get(0.0, 0.0)
    improvement = max(0.0, best_score - base_score)
    confidence = improvement / (base_score + 1e-9) if base_score > 0 else 0.0
    return best_angle, min(1.0, confidence), scores


def _binary_ink(image: Image.Image) -> tuple[list[list[int]], int, int]:
    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    threshold = min(otsu_threshold(gray), 210)
    pixels = _pixel_values(gray)
    width, height = gray.size
    matrix = [
        [1 if pixels[y * width + x] <= threshold else 0 for x in range(width)]
        for y in range(height)
    ]
    return matrix, width, height


def _candidate_groups(flags: list[bool]) -> list[tuple[int, int]]:
    groups: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(flags + [False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            groups.append((start, index - 1))
            start = None
    return groups


def _horizontal_intersection_ratio(
    matrix: list[list[int]], width: int, height: int, start: int, end: int
) -> float:
    above = max(0, start - 4)
    below = min(height - 1, end + 4)
    intersections = 0
    tested = 0
    for x in range(width):
        on_line = any(matrix[y][x] for y in range(start, end + 1))
        if not on_line:
            continue
        tested += 1
        has_above = any(matrix[y][x] for y in range(above, start))
        has_below = any(matrix[y][x] for y in range(end + 1, below + 1))
        if has_above and has_below:
            intersections += 1
    return intersections / max(1, tested)


def _vertical_intersection_ratio(
    matrix: list[list[int]], width: int, height: int, start: int, end: int
) -> float:
    left = max(0, start - 4)
    right = min(width - 1, end + 4)
    intersections = 0
    tested = 0
    for y in range(height):
        on_line = any(matrix[y][x] for x in range(start, end + 1))
        if not on_line:
            continue
        tested += 1
        has_left = any(matrix[y][x] for x in range(left, start))
        has_right = any(matrix[y][x] for x in range(end + 1, right + 1))
        if has_left and has_right:
            intersections += 1
    return intersections / max(1, tested)


def remove_long_lines(
    image: Image.Image,
    *,
    min_length_ratio: float,
    max_thickness_px: int,
    max_intersection_ratio: float = 0.025,
) -> tuple[Image.Image, Image.Image, int, int, int]:
    source = image.convert("RGB")
    longest_edge = max(source.size)
    scale = min(1.0, 1600 / longest_edge) if longest_edge else 1.0
    if scale < 0.999:
        work = source.resize(
            (
                max(1, round(source.width * scale)),
                max(1, round(source.height * scale)),
            ),
            Image.Resampling.BILINEAR,
        )
    else:
        work = source
    matrix, width, height = _binary_ink(work)

    def longest_run(values: list[int]) -> int:
        best = 0
        current = 0
        for value in values:
            if value:
                current += 1
                best = max(best, current)
            else:
                current = 0
        return best

    horizontal_flags = [
        longest_run(row) >= width * min_length_ratio for row in matrix
    ]
    vertical_flags = [
        longest_run([matrix[y][x] for y in range(height)])
        >= height * min_length_ratio
        for x in range(width)
    ]
    scaled_thickness = max(1, math.ceil(max_thickness_px * scale))
    candidates: list[tuple[str, int, int]] = []
    for group_start, group_end in _candidate_groups(horizontal_flags):
        if group_end - group_start + 1 <= scaled_thickness:
            candidates.append(("horizontal", group_start, group_end))
    for group_start, group_end in _candidate_groups(vertical_flags):
        if group_end - group_start + 1 <= scaled_thickness:
            candidates.append(("vertical", group_start, group_end))

    accepted: list[tuple[str, int, int]] = []
    for direction, group_start, group_end in candidates:
        ratio = (
            _horizontal_intersection_ratio(
                matrix, width, height, group_start, group_end
            )
            if direction == "horizontal"
            else _vertical_intersection_ratio(
                matrix, width, height, group_start, group_end
            )
        )
        if ratio <= max_intersection_ratio:
            accepted.append((direction, group_start, group_end))

    mask = Image.new("L", source.size, 255)
    output = source.copy()
    mask_pixels = mask.load()
    output_pixels = output.load()
    gray = ImageOps.grayscale(source)
    gray_pixels = gray.load()
    threshold = min(otsu_threshold(gray), 210)
    removed = 0

    def full_range(group_start: int, group_end: int, limit: int) -> tuple[int, int]:
        if scale >= 0.999:
            return group_start, group_end
        full_start = max(0, math.floor(group_start / scale))
        full_end = min(limit - 1, math.ceil((group_end + 1) / scale) - 1)
        return full_start, full_end

    for direction, group_start, group_end in accepted:
        if direction == "horizontal":
            full_start, full_end = full_range(group_start, group_end, source.height)
            for y in range(full_start, full_end + 1):
                for x in range(source.width):
                    if gray_pixels[x, y] <= threshold:
                        mask_pixels[x, y] = 0
                        output_pixels[x, y] = (255, 255, 255)
                        removed += 1
        else:
            full_start, full_end = full_range(group_start, group_end, source.width)
            for x in range(full_start, full_end + 1):
                for y in range(source.height):
                    if gray_pixels[x, y] <= threshold:
                        mask_pixels[x, y] = 0
                        output_pixels[x, y] = (255, 255, 255)
                        removed += 1
    return output, mask, len(candidates), len(accepted), removed


def apply_conservative_geometry(
    image: Image.Image,
    *,
    orientation_min_confidence: float,
    deskew_max_degrees: float,
    deskew_min_confidence: float,
    line_min_length_ratio: float,
    line_max_thickness_px: int,
    enable_dewarp: bool = False,
    dewarp_strips: int = 17,
    dewarp_max_displacement_ratio: float = 0.035,
    dewarp_min_displacement_px: float = 2.0,
    dewarp_min_confidence: float = 0.45,
) -> GeometryResult:
    current = image.convert("RGB")
    result = GeometryResult(
        image=current,
        mask=Image.new("L", current.size, 255),
        orientation_min_confidence=orientation_min_confidence,
        deskew_min_confidence=deskew_min_confidence,
    )

    angle, confidence, _scores = detect_orientation(current)
    result.orientation_detected = int(angle)
    result.orientation_confidence = confidence
    if angle != 0 and confidence >= orientation_min_confidence:
        current = current.rotate(
            angle,
            expand=True,
            resample=Image.Resampling.BICUBIC,
            fillcolor="white",
        )
        result.orientation_applied = int(angle)
    elif angle != 0:
        result.warnings.append(
            f"Orientación candidata {angle}° omitida por confianza insuficiente "
            f"({confidence:.3f} < {orientation_min_confidence:.3f})."
        )

    deskew_angle, deskew_confidence, _deskew_scores = detect_deskew(
        current, max_degrees=deskew_max_degrees
    )
    result.deskew_detected_angle = float(deskew_angle)
    result.deskew_confidence = deskew_confidence
    if (
        abs(deskew_angle) >= 0.4
        and abs(deskew_angle) <= deskew_max_degrees
        and deskew_confidence >= deskew_min_confidence
    ):
        current = current.rotate(
            deskew_angle,
            expand=True,
            resample=Image.Resampling.BICUBIC,
            fillcolor="white",
        )
        result.deskew_angle = float(deskew_angle)
    elif abs(deskew_angle) >= 0.4:
        result.warnings.append(
            f"Deskew candidato {deskew_angle:.1f}° omitido por confianza insuficiente "
            f"({deskew_confidence:.3f} < {deskew_min_confidence:.3f})."
        )

    if enable_dewarp:
        dewarp = estimate_vertical_dewarp(
            current,
            strips=dewarp_strips,
            max_displacement_ratio=dewarp_max_displacement_ratio,
            min_displacement_px=dewarp_min_displacement_px,
            min_confidence=dewarp_min_confidence,
        )
        result.dewarp = dewarp
        result.dewarp_diagnostic = render_dewarp_diagnostic(current, dewarp)
        result.warnings.extend(dewarp.warnings)
        if dewarp.applied:
            current = apply_estimated_dewarp(current, dewarp)

    cleaned, mask, detected, removed, removed_pixels = remove_long_lines(
        current,
        min_length_ratio=line_min_length_ratio,
        max_thickness_px=line_max_thickness_px,
    )
    result.image = cleaned
    result.mask = mask
    result.lines_detected = detected
    result.lines_removed = removed
    result.removed_pixels = removed_pixels
    return result
