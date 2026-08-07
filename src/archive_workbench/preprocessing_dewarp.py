from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageOps

from archive_workbench.tesseract_engine import otsu_threshold


@dataclass(slots=True)
class DewarpEstimate:
    detected: bool
    applied: bool
    confidence: float
    support_strips: int
    total_strips: int
    max_displacement_px: float
    max_displacement_ratio: float
    fit_quality: float
    median_improvement: float
    curvature_ratio: float
    coefficients: tuple[float, float, float]
    strip_offsets: list[dict[str, float | int | bool]]
    reason: str
    warnings: list[str]

    @property
    def analysis(self) -> dict[str, Any]:
        return {
            "dewarp_detected": self.detected,
            "dewarp_applied": self.applied,
            "dewarp_confidence": round(self.confidence, 6),
            "dewarp_support_strips": self.support_strips,
            "dewarp_total_strips": self.total_strips,
            "dewarp_max_displacement_px": round(self.max_displacement_px, 3),
            "dewarp_max_displacement_ratio": round(self.max_displacement_ratio, 6),
            "dewarp_fit_quality": round(self.fit_quality, 6),
            "dewarp_median_improvement": round(self.median_improvement, 6),
            "dewarp_curvature_ratio": round(self.curvature_ratio, 6),
            "dewarp_coefficients": [round(value, 8) for value in self.coefficients],
            "dewarp_reason": self.reason,
            "dewarp_strip_offsets": self.strip_offsets,
        }

    @property
    def transformation(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "detected": self.detected,
            "confidence": round(self.confidence, 6),
            "max_displacement_px": round(self.max_displacement_px, 3),
            "support_strips": self.support_strips,
            "fit_quality": round(self.fit_quality, 6),
            "curvature_ratio": round(self.curvature_ratio, 6),
            "coefficients": [round(value, 8) for value in self.coefficients],
            "reason": self.reason,
        }


def _pixel_values(image: Image.Image) -> list[int]:
    getter = getattr(image, "get_flattened_data", None)
    if getter is not None:
        return list(getter())
    return list(image.getdata())


def _working_gray(image: Image.Image, *, max_edge: int = 1100) -> Image.Image:
    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    longest = max(gray.size)
    if longest > max_edge:
        scale = max_edge / longest
        gray = gray.resize(
            (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))),
            Image.Resampling.BILINEAR,
        )
    return gray


def _binary_ink(image: Image.Image) -> tuple[list[list[int]], int, int]:
    threshold = min(otsu_threshold(image), 210)
    pixels = _pixel_values(image)
    width, height = image.size
    matrix = [
        [1 if pixels[y * width + x] <= threshold else 0 for x in range(width)]
        for y in range(height)
    ]
    return matrix, width, height


def _smooth(values: list[float], radius: int = 2) -> list[float]:
    if not values:
        return []
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    out: list[float] = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        out.append((prefix[end] - prefix[start]) / max(1, end - start))
    return out


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    centered = [value - mean for value in values]
    norm = math.sqrt(sum(value * value for value in centered))
    if norm <= 1e-9:
        return [0.0 for _ in centered]
    return [value / norm for value in centered]


def _correlation(reference: list[float], candidate: list[float], shift: int) -> float:
    if shift >= 0:
        ref_start = 0
        candidate_start = shift
        length = min(len(reference), len(candidate) - shift)
    else:
        ref_start = -shift
        candidate_start = 0
        length = min(len(reference) + shift, len(candidate))
    if length < max(20, len(reference) // 3):
        return -1.0
    return sum(
        reference[ref_start + offset] * candidate[candidate_start + offset]
        for offset in range(length)
    )


def _solve_3x3(matrix: list[list[float]], vector: list[float]) -> tuple[float, float, float]:
    augmented = [row[:] + [value] for row, value in zip(matrix, vector, strict=True)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-12:
            return 0.0, 0.0, 0.0
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                current - factor * source
                for current, source in zip(augmented[row], augmented[column], strict=True)
            ]
    return augmented[0][3], augmented[1][3], augmented[2][3]


def _quadratic_fit(points: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    # y = a*x^2 + b*x + c, weighted least squares.
    sums = {
        power: sum(weight * (x ** power) for x, _y, weight in points)
        for power in range(5)
    }
    rhs = [
        sum(weight * y * (x ** power) for x, y, weight in points)
        for power in (2, 1, 0)
    ]
    matrix = [
        [sums[4], sums[3], sums[2]],
        [sums[3], sums[2], sums[1]],
        [sums[2], sums[1], sums[0]],
    ]
    return _solve_3x3(matrix, rhs)


def _curve(coefficients: tuple[float, float, float], x: float) -> float:
    a, b, c = coefficients
    return a * x * x + b * x + c


def _empty_estimate(*, strips: int, reason: str, warning: str | None = None) -> DewarpEstimate:
    return DewarpEstimate(
        detected=False,
        applied=False,
        confidence=0.0,
        support_strips=0,
        total_strips=strips,
        max_displacement_px=0.0,
        max_displacement_ratio=0.0,
        fit_quality=0.0,
        median_improvement=0.0,
        curvature_ratio=0.0,
        coefficients=(0.0, 0.0, 0.0),
        strip_offsets=[],
        reason=reason,
        warnings=[warning] if warning else [],
    )


def estimate_vertical_dewarp(
    image: Image.Image,
    *,
    strips: int = 17,
    max_displacement_ratio: float = 0.035,
    min_displacement_px: float = 2.0,
    min_confidence: float = 0.45,
) -> DewarpEstimate:
    """Estima una curvatura vertical suave sin modificar la imagen.

    El modelo solo corrige desplazamientos verticales que cambian de forma suave a lo
    ancho de la página. No intenta reconstruir perspectiva, pliegues locales ni texto.
    """
    strips = max(9, int(strips) | 1)
    work = _working_gray(image)
    matrix, width, height = _binary_ink(work)
    total_ink = sum(sum(row) for row in matrix)
    if total_ink < max(180, width * height * 0.001):
        return _empty_estimate(
            strips=strips,
            reason="insufficient_ink",
            warning=(
                "Dewarp omitido: la página no contiene tinta suficiente para "
                "estimar curvatura."
            ),
        )

    strip_width = width / strips
    profiles: list[list[float]] = []
    ink_counts: list[int] = []
    for strip in range(strips):
        x0 = max(0, round(strip * strip_width))
        x1 = min(width, round((strip + 1) * strip_width))
        raw = [float(sum(matrix[y][x0:x1])) for y in range(height)]
        ink_counts.append(round(sum(raw)))
        profiles.append(_normalize(_smooth(raw, radius=2)))

    center = strips // 2
    central_indices = [index for index in range(center - 2, center + 3) if 0 <= index < strips]
    reference_raw = [
        sum(profiles[index][row] for index in central_indices) / len(central_indices)
        for row in range(height)
    ]
    reference = _normalize(reference_raw)
    if not any(abs(value) > 1e-9 for value in reference):
        return _empty_estimate(
            strips=strips,
            reason="missing_reference_profile",
            warning="Dewarp omitido: no se pudo construir un perfil central estable.",
        )

    max_shift = max(2, round(height * max_displacement_ratio))
    support_threshold = max(30, int((width / strips) * height * 0.0008))
    observations: list[tuple[float, float, float]] = []
    strip_rows: list[dict[str, float | int | bool]] = []
    improvements: list[float] = []

    for index, profile in enumerate(profiles):
        supported = ink_counts[index] >= support_threshold and any(
            abs(value) > 1e-9 for value in profile
        )
        x = (index + 0.5) / strips
        if not supported:
            strip_rows.append(
                {
                    "strip": index + 1,
                    "x": round(x, 6),
                    "supported": False,
                    "offset_px": 0.0,
                    "correlation": 0.0,
                    "improvement": 0.0,
                }
            )
            continue
        zero = _correlation(reference, profile, 0)
        scored = [
            (shift, _correlation(reference, profile, shift))
            for shift in range(-max_shift, max_shift + 1)
        ]
        best_shift, best = max(scored, key=lambda item: item[1])
        improvement = max(0.0, best - zero)
        weight = max(0.05, best + 1.0) * (1.0 + min(1.0, improvement * 6.0))
        observations.append((x, float(best_shift), weight))
        improvements.append(improvement)
        strip_rows.append(
            {
                "strip": index + 1,
                "x": round(x, 6),
                "supported": True,
                "offset_px": float(best_shift),
                "correlation": round(best, 6),
                "improvement": round(improvement, 6),
            }
        )

    minimum_support = max(7, round(strips * 0.55))
    if len(observations) < minimum_support:
        estimate = _empty_estimate(
            strips=strips,
            reason="insufficient_supported_strips",
            warning=(
                "Dewarp omitido: no hay suficientes franjas con texto para estimar una "
                "curvatura estable."
            ),
        )
        estimate.support_strips = len(observations)
        estimate.strip_offsets = strip_rows
        return estimate

    coefficients = _quadratic_fit(observations)
    center_value = _curve(coefficients, 0.5)
    coefficients = (
        coefficients[0],
        coefficients[1],
        coefficients[2] - center_value,
    )
    predicted = [_curve(coefficients, x) for x, _offset, _weight in observations]
    observed = [offset for _x, offset, _weight in observations]
    observed_mean = sum(observed) / len(observed)
    sse = sum(
        (actual - estimate) ** 2
        for actual, estimate in zip(observed, predicted, strict=True)
    )
    sst = sum((actual - observed_mean) ** 2 for actual in observed)
    fit_quality = max(0.0, min(1.0, 1.0 - sse / (sst + 1e-9))) if sst > 0 else 0.0

    sample_x = [index / 40 for index in range(41)]
    displacements = [_curve(coefficients, x) for x in sample_x]
    max_abs_work = max(abs(value) for value in displacements)
    edge_curve = abs((displacements[0] + displacements[-1]) / 2.0 - _curve(coefficients, 0.5))
    curvature_ratio = edge_curve / (max_abs_work + 1e-9)
    median_improvement = median(improvements) if improvements else 0.0
    support_ratio = len(observations) / strips
    improvement_score = min(1.0, median_improvement / 0.08)
    confidence = max(
        0.0,
        min(
            1.0,
            0.50 * fit_quality + 0.30 * improvement_score + 0.20 * support_ratio,
        ),
    )

    scale = image.height / height
    max_abs_full = max_abs_work * scale
    max_ratio_full = max_abs_full / max(1, image.height)
    detected = (
        max_abs_full >= min_displacement_px
        and max_ratio_full <= max_displacement_ratio * 1.05
        and fit_quality >= 0.45
        and curvature_ratio >= 0.45
    )
    applied = detected and confidence >= min_confidence
    if not detected:
        reason = "no_stable_curve_candidate"
    elif not applied:
        reason = "confidence_below_threshold"
    else:
        reason = "confidence_above_threshold"

    warnings: list[str] = []
    if detected and not applied:
        warnings.append(
            "Dewarp candidato omitido por confianza insuficiente "
            f"({confidence:.3f} < {min_confidence:.3f})."
        )

    scaled_coefficients = tuple(value * scale for value in coefficients)
    return DewarpEstimate(
        detected=detected,
        applied=applied,
        confidence=confidence,
        support_strips=len(observations),
        total_strips=strips,
        max_displacement_px=max_abs_full,
        max_displacement_ratio=max_ratio_full,
        fit_quality=fit_quality,
        median_improvement=median_improvement,
        curvature_ratio=curvature_ratio,
        coefficients=scaled_coefficients,
        strip_offsets=strip_rows,
        reason=reason,
        warnings=warnings,
    )


def displacement_function(estimate: DewarpEstimate) -> Callable[[float], float]:
    coefficients = estimate.coefficients
    return lambda x: _curve(coefficients, x)


def warp_vertical(
    image: Image.Image,
    displacement: Callable[[float], float],
    *,
    mesh_columns: int = 48,
) -> Image.Image:
    """Remapea verticalmente una imagen mediante una malla suave y fondo blanco."""
    source = image.convert("RGB")
    width, height = source.size
    mesh: list[tuple[tuple[int, int, int, int], tuple[float, ...]]] = []
    for index in range(mesh_columns):
        x0 = round(index * width / mesh_columns)
        x1 = round((index + 1) * width / mesh_columns)
        if x1 <= x0:
            continue
        d0 = displacement(x0 / max(1, width - 1))
        d1 = displacement(x1 / max(1, width - 1))
        mesh.append(
            (
                (x0, 0, x1, height),
                (
                    float(x0),
                    float(d0),
                    float(x0),
                    float(height + d0),
                    float(x1),
                    float(height + d1),
                    float(x1),
                    float(d1),
                ),
            )
        )
    return source.transform(
        source.size,
        Image.Transform.MESH,
        mesh,
        resample=Image.Resampling.BICUBIC,
        fillcolor="white",
    )


def apply_estimated_dewarp(image: Image.Image, estimate: DewarpEstimate) -> Image.Image:
    if not estimate.applied:
        return image.copy()
    return warp_vertical(image, displacement_function(estimate))


def render_dewarp_diagnostic(image: Image.Image, estimate: DewarpEstimate) -> Image.Image:
    longest = max(image.size)
    scale = min(1.0, 1400 / longest) if longest else 1.0
    if scale < 0.999:
        canvas = image.convert("RGB").resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    else:
        canvas = image.convert("RGB").copy()
    draw = ImageDraw.Draw(canvas)
    width, height = canvas.size
    displacement = displacement_function(estimate)
    line_color = (32, 91, 122) if estimate.applied else (150, 92, 45)
    for fraction in (0.2, 0.4, 0.6, 0.8):
        points = []
        base_y = height * fraction
        for x in range(0, width, max(1, width // 120)):
            full_x = x / max(scale, 1e-9)
            d = displacement(full_x / max(1, image.width - 1)) * scale
            points.append((x, base_y + d))
        if len(points) >= 2:
            draw.line(points, fill=line_color, width=max(1, round(2 * scale)))
    for index in range(estimate.total_strips + 1):
        x = round(index * width / estimate.total_strips)
        draw.line((x, 0, x, height), fill=(210, 210, 210), width=1)
    label = (
        f"dewarp {'aplicado' if estimate.applied else 'omitido'} · "
        f"confianza {estimate.confidence:.3f} · "
        f"desplazamiento {estimate.max_displacement_px:.1f}px"
    )
    draw.rectangle((8, 8, min(width - 8, 610), 34), fill="white", outline=(90, 90, 90))
    draw.text((14, 14), label, fill=(20, 20, 20))
    return canvas
