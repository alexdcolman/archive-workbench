from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable


_ARTICLE_PATTERN = re.compile(
    r"\bart(?:[íi]culo|\.)\s+(?P<number>\d{2,3})\s*(?:[.º°]|[-–—:])",
    re.IGNORECASE,
)
_COMBINED_CHECKBOX_PATTERN = re.compile(
    r"^\s*(?P<marker>\[\s*[xX]?\s*\]|[☒☑✓✔■●☐□○×])\s*(?P<label>.+?)\s*$"
)
_CHECKED_MARKERS = {"x", "×", "☒", "☑", "✓", "✔", "■", "●", "[x]"}
_UNCHECKED_MARKERS = {"☐", "□", "○", "[ ]"}


@dataclass(frozen=True, slots=True)
class _Box:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True, slots=True)
class _ObjectView:
    object_id: str
    order_index: int
    object_type: str
    text: str
    source_label: str | None
    geometry: list[dict[str, Any]]
    attributes: dict[str, Any]


class _CheckboxHtmlParser(HTMLParser):
    """Extrae controles HTML conservando solo estado y rótulo visible."""

    _LABEL_END_TAGS = {"label", "li", "td", "th", "p", "div"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.controls: list[dict[str, str | None]] = []
        self._pending: dict[str, str | None] | None = None
        self._text: list[str] = []

    def _flush(self) -> None:
        if self._pending is None:
            return
        visible_label = re.sub(r"\s+", " ", " ".join(self._text)).strip()
        label = self._pending.get("label") or visible_label or None
        self.controls.append({**self._pending, "label": label})
        self._pending = None
        self._text = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "input":
            return
        values = {str(key).casefold(): value for key, value in attrs}
        input_type = str(values.get("type") or "").casefold()
        if input_type not in {"checkbox", "radio"} and "checked" not in values:
            return
        self._flush()
        aria_checked = str(values.get("aria-checked") or "").casefold()
        if aria_checked == "mixed":
            state = "indeterminate"
        elif "checked" in values or aria_checked == "true":
            state = "marked"
        else:
            state = "unmarked"
        self._pending = {
            "state": state,
            "label": (
                str(values.get("aria-label") or values.get("value") or "").strip() or None
            ),
            "marker": f"<{input_type or 'input'}>",
        }

    def handle_data(self, data: str) -> None:
        if self._pending is not None and data.strip():
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._pending is not None and tag.casefold() in self._LABEL_END_TAGS:
            self._flush()

    def close(self) -> None:
        super().close()
        self._flush()


def _view(item: Any) -> _ObjectView:
    attributes = dict(
        getattr(
            item,
            "current_attributes_json",
            getattr(item, "attributes_json", getattr(item, "attributes", {})),
        )
        or {}
    )
    source_label = getattr(item, "source_label", None)
    if source_label is None:
        source_label = attributes.get("source_label")
    return _ObjectView(
        object_id=str(getattr(item, "id", getattr(item, "object_id", ""))),
        order_index=int(
            getattr(item, "current_order_index", getattr(item, "order_index", 0))
        ),
        object_type=str(
            getattr(
                item,
                "current_object_type",
                getattr(item, "object_type", "unknown"),
            )
            or "unknown"
        ),
        text=str(
            getattr(
                item,
                "current_text",
                getattr(item, "original_text", getattr(item, "text", "")),
            )
            or ""
        ),
        source_label=str(source_label) if source_label is not None else None,
        geometry=list(
            getattr(
                item,
                "current_geometry_json",
                getattr(item, "geometry_json", getattr(item, "geometry", [])),
            )
            or []
        ),
        attributes=attributes,
    )


def _normalized_box(item: _ObjectView, page_number: int) -> _Box | None:
    boxes: list[_Box] = []
    for geometry in item.geometry:
        if int(geometry.get("page") or 0) != page_number:
            continue
        if geometry.get("coordinate_space") != "normalized":
            continue
        polygon = geometry.get("polygon") or []
        if len(polygon) < 4:
            continue
        try:
            xs = [float(point[0]) for point in polygon]
            ys = [float(point[1]) for point in polygon]
        except (TypeError, ValueError, IndexError):
            continue
        left, right = max(0.0, min(xs)), min(1.0, max(xs))
        top, bottom = max(0.0, min(ys)), min(1.0, max(ys))
        if right > left and bottom > top:
            boxes.append(_Box(left, top, right, bottom))
    if not boxes:
        return None
    return _Box(
        min(box.left for box in boxes),
        min(box.top for box in boxes),
        max(box.right for box in boxes),
        max(box.bottom for box in boxes),
    )


def _longest_consecutive_run(values: list[int]) -> set[int]:
    unique = sorted(set(values))
    best: list[int] = []
    current: list[int] = []
    for value in unique:
        if current and value != current[-1] + 1:
            if len(current) > len(best):
                best = current
            current = []
        current.append(value)
    if len(current) > len(best):
        best = current
    return set(best)


def legal_ordinal_candidates(objects: Iterable[Any]) -> list[dict[str, Any]]:
    """Detecta secuencias compatibles con ordinales OCRizados como dos cifras.

    La regla exige al menos tres encabezados cuyos dígitos iniciales formen una secuencia
    consecutiva, mientras los números completos no formen una secuencia ordinaria. Solo genera
    una alerta; nunca modifica el texto.
    """

    matches: list[dict[str, Any]] = []
    views = sorted((_view(value) for value in objects), key=lambda value: value.order_index)
    for item in views:
        for match in _ARTICLE_PATTERN.finditer(item.text):
            number_text = match.group("number")
            if len(number_text) != 2:
                continue
            matches.append(
                {
                    "object_id": item.object_id,
                    "order_index": item.order_index,
                    "text": match.group(0).strip(),
                    "number": int(number_text),
                    "leading_digit": int(number_text[0]),
                }
            )
    if len(matches) < 3:
        return []
    leading_run = _longest_consecutive_run([item["leading_digit"] for item in matches])
    if len(leading_run) < 3:
        return []
    selected = [item for item in matches if item["leading_digit"] in leading_run]
    complete_numbers = [item["number"] for item in selected]
    if all(
        next_number == number + 1
        for number, next_number in zip(complete_numbers, complete_numbers[1:])
    ):
        return []
    return [
        {
            "object_id": item["object_id"],
            "text": item["text"],
            "detected_number": item["number"],
            "possible_ordinal": f"{item['leading_digit']}º",
            "reason": "secuencia compatible con un símbolo ordinal leído como otro dígito",
        }
        for item in selected
    ]


def _marker_state(marker: str) -> str | None:
    normalized = re.sub(r"\s+", " ", marker.strip()).casefold()
    if normalized in _CHECKED_MARKERS:
        return "marked"
    if normalized in _UNCHECKED_MARKERS:
        return "unmarked"
    return None


def _html_controls(item: _ObjectView) -> list[dict[str, str | None]]:
    html = str(item.attributes.get("html") or "")
    if "<input" not in html.casefold():
        return []
    parser = _CheckboxHtmlParser()
    parser.feed(html)
    parser.close()
    return parser.controls


def _nearest_label(
    marker: _ObjectView,
    marker_box: _Box,
    objects: list[_ObjectView],
    boxes: dict[str, _Box | None],
) -> tuple[_ObjectView | None, str]:
    candidates: list[tuple[float, _ObjectView]] = []
    for item in objects:
        if item.object_id == marker.object_id or not item.text.strip():
            continue
        box = boxes.get(item.object_id)
        if box is None:
            continue
        horizontal_gap = box.left - marker_box.right
        vertical_gap = abs(box.center_y - marker_box.center_y)
        aligned = vertical_gap <= max(0.035, box.height, marker_box.height)
        if -0.01 <= horizontal_gap <= 0.30 and aligned:
            distance = max(horizontal_gap, 0.0) + vertical_gap * 2
            candidates.append((distance, item))
    if candidates:
        candidates.sort(key=lambda pair: (pair[0], pair[1].order_index))
        return candidates[0][1], "spatial"
    later = [
        item
        for item in objects
        if item.order_index > marker.order_index
        and item.text.strip()
        and len(item.text.strip()) <= 120
    ]
    return (later[0], "reading_order") if later else (None, "unlinked")


def checkbox_candidates(objects: Iterable[Any], *, page_number: int) -> list[dict[str, Any]]:
    """Señala controles HTML, símbolos explícitos o marcas pequeñas próximas a rótulos.

    Las asociaciones son candidatas para revisión, no estados canónicos. Un casillero vacío sin
    representación OCR o HTML sigue siendo indetectable.
    """

    views = sorted((_view(value) for value in objects), key=lambda value: value.order_index)
    boxes = {item.object_id: _normalized_box(item, page_number) for item in views}
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for item in views:
        for control_index, control in enumerate(_html_controls(item)):
            state = str(control.get("state") or "indeterminate")
            label = str(control.get("label") or "").strip() or None
            marker = str(control.get("marker") or "<input>")
            key = (item.object_id, label.casefold() if label else "", state)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "marker_object_id": item.object_id,
                    "label_object_id": item.object_id,
                    "control_index": control_index,
                    "state": state,
                    "label": label,
                    "method": "html_control",
                    "marker": marker,
                }
            )

        text = item.text.strip()
        if not text:
            continue
        combined = _COMBINED_CHECKBOX_PATTERN.match(text)
        if combined:
            state = _marker_state(combined.group("marker"))
            label = combined.group("label").strip()
            if state is not None and label:
                key = (item.object_id, label.casefold(), state)
                if key not in seen:
                    seen.add(key)
                    results.append(
                        {
                            "marker_object_id": item.object_id,
                            "label_object_id": item.object_id,
                            "state": state,
                            "label": label,
                            "method": "explicit_text",
                            "marker": combined.group("marker").strip(),
                        }
                    )
                continue

        state = _marker_state(text)
        if state is None:
            continue
        box = boxes.get(item.object_id)
        source_is_form = (
            item.object_type == "form_field"
            or (item.source_label or "").casefold() == "form"
        )
        marker_is_unambiguous = text not in {"x", "X", "×"}
        marker_is_small = bool(
            box and box.area <= 0.012 and box.width <= 0.12 and box.height <= 0.12
        )
        if not (source_is_form or marker_is_unambiguous or marker_is_small):
            continue
        if box:
            label_item, method = _nearest_label(item, box, views, boxes)
        else:
            label_item, method = None, "reading_order"
        label = label_item.text.strip() if label_item is not None else ""
        key = (item.object_id, label.casefold(), state)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "marker_object_id": item.object_id,
                "label_object_id": label_item.object_id if label_item is not None else None,
                "state": state,
                "label": label or None,
                "method": method,
                "marker": text,
            }
        )
    return results


def structural_quality_metrics(objects: Iterable[Any], *, page_number: int) -> dict[str, Any]:
    materialized = list(objects)
    ordinals = legal_ordinal_candidates(materialized)
    checkboxes = checkbox_candidates(materialized, page_number=page_number)
    return {
        "legal_ordinal_candidates": ordinals,
        "legal_ordinal_candidate_count": len(ordinals),
        "checkbox_candidates": checkboxes,
        "checkbox_candidate_count": len(checkboxes),
        "checkbox_marked_count": sum(item["state"] == "marked" for item in checkboxes),
        "checkbox_unmarked_count": sum(
            item["state"] == "unmarked" for item in checkboxes
        ),
        "checkbox_indeterminate_count": sum(
            item["state"] == "indeterminate" for item in checkboxes
        ),
    }
