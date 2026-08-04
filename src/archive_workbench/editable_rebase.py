from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher, unified_diff
import hashlib
import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive_workbench.authorities import _append_mention_revision, normalize_authority_text
from archive_workbench.contracts.decisions import ProjectDecisions
from archive_workbench.db.models import (
    EditableObject,
    EditableObjectComment,
    EditableObjectTag,
    EditablePage,
    EditablePageAction,
    EntityMention,
    DocumentPart,
    AuthorityRecord,
    ExtractedObject,
    ExtractionPage,
    ExtractionPageSelection,
    utc_now,
)
from archive_workbench.editing import _allowed_object_type, _append_page_revision, _append_revision
from archive_workbench.extraction import select_extraction_pages
from archive_workbench.identity import new_id

_TOKEN_RE = re.compile(r"\s+|[^\s]+", re.UNICODE)


@dataclass(slots=True)
class RebaseObjectPreview:
    order_index: int
    source_object_id: str
    object_type: str
    candidate_text: str
    rebased_text: str
    carried_annotations: int = 0


@dataclass(slots=True)
class RebaseMentionCandidate:
    target_index: int
    start_offset: int
    end_offset: int
    matched_text: str
    context: str
    method: str
    score: float


@dataclass(slots=True)
class RebaseProjectionCandidate:
    target_index: int
    order_index: int
    text: str
    overlap_score: float
    text_score: float
    combined_score: float


@dataclass(slots=True)
class RebaseProjectionConflict:
    conflict_id: str
    source_object_id: str
    source_order_index: int
    source_text: str
    reason: str
    candidates: list[RebaseProjectionCandidate]


@dataclass(slots=True)
class RebaseMentionConflict:
    mention_id: str
    mention_text: str
    authority_id: str | None
    authority_name: str | None
    status: str
    reason_code: str
    reason: str
    source_context: str
    predicted_target_index: int | None
    candidates: list[RebaseMentionCandidate]


@dataclass(slots=True)
class RebaseTextConflict:
    conflict_id: str
    reason_code: str
    reason: str
    base_text: str
    human_text: str
    candidate_text: str
    context: str


@dataclass(slots=True)
class RebaseMetadataOption:
    value: str | None
    label: str


@dataclass(slots=True)
class RebaseMetadataConflict:
    conflict_id: str
    target_index: int
    kind: str
    reason: str
    options: list[RebaseMetadataOption]
    source_object_ids: list[str]


@dataclass(slots=True)
class RebaseAttributeOption:
    option_key: str
    label: str
    action: str
    value: Any = None
    source_object_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RebaseAttributeConflict:
    conflict_id: str
    target_index: int
    attribute_key: str
    reason: str
    options: list[RebaseAttributeOption]
    source_object_ids: list[str]


@dataclass(slots=True)
class RebasePreview:
    source_key: str
    page: int
    candidate_run_id: str
    editable_page_id: str
    expected_page_revision: int
    can_apply: bool
    conflicts: list[str]
    text_conflicts: list[RebaseTextConflict]
    projection_conflicts: list[RebaseProjectionConflict]
    mention_conflicts: list[RebaseMentionConflict]
    metadata_conflicts: list[RebaseMetadataConflict]
    attribute_conflicts: list[RebaseAttributeConflict]
    base_text: str
    editable_text: str
    candidate_text: str
    rebased_text: str
    candidate_objects: list[RebaseObjectPreview]
    old_object_count: int
    new_object_count: int
    human_change_count: int
    mention_count: int
    comment_count: int
    tag_count: int
    document_part_count: int
    structural_action_count: int
    unified_text_diff: str
    _plan: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(slots=True)
class RebaseResult:
    selection_changed: bool
    editable_page_id: str
    old_objects_retired: int
    new_objects_created: int
    mentions_relocated: int
    mentions_rejected: int
    comments_relocated: int
    tags_relocated: int
    tags_deduplicated: int
    document_parts_relocated: int
    structural_actions_absorbed: int
    projection_resolutions_applied: int
    metadata_resolutions_applied: int
    attribute_resolutions_applied: int


_STRUCTURAL_ATTRIBUTE_KEYS = {
    "manually_added",
    "geometry_pending",
    "split_from_object_id",
    "merged_from_object_ids",
    "rebased_from_object_ids",
    "lineage_events",
}


def _attribute_signature(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _human_specialized_attributes(
    row: EditableObject,
    source: ExtractedObject | None,
) -> dict[str, Any]:
    """Devuelve atributos activos que no provienen sin cambios del OCR anterior.

    Los atributos de procedencia se reconstruyen desde la candidata. Los eventos de
    linaje se conservan por separado en la auditoría del rebase, porque ya no deben
    actuar como estado estructural vigente sobre el bloque nuevo.
    """

    from archive_workbench.candidate_review import _editable_attributes

    current = dict(row.current_attributes_json or {})
    baseline = _editable_attributes(source) if source is not None else {}
    specialized: dict[str, Any] = {}
    for key, value in current.items():
        if key in _STRUCTURAL_ATTRIBUTE_KEYS:
            continue
        if key.startswith("source_"):
            continue
        if key in baseline and baseline[key] == value:
            continue
        specialized[key] = value
    return specialized


def _join_texts(rows: list[Any], attr: str) -> tuple[str, list[tuple[int, int]]]:
    pieces: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    for index, row in enumerate(rows):
        if index:
            pieces.append("\n\n")
            cursor += 2
        text = str(getattr(row, attr) or "")
        start = cursor
        pieces.append(text)
        cursor += len(text)
        spans.append((start, cursor))
    return "".join(pieces), spans


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def _boundary_map(opcodes: list[tuple[str, int, int, int, int]], source_length: int) -> list[int]:
    mapping = [0] * (source_length + 1)
    filled = [False] * (source_length + 1)
    for tag, i1, i2, j1, j2 in opcodes:
        if i1 == i2:
            mapping[i1] = j2
            filled[i1] = True
            continue
        span = i2 - i1
        target_span = j2 - j1
        for pos in range(i1, i2 + 1):
            if tag == "equal":
                mapped = j1 + (pos - i1)
            else:
                ratio = (pos - i1) / span
                mapped = round(j1 + ratio * target_span)
            mapping[pos] = mapped
            filled[pos] = True
    last = 0
    for index in range(source_length + 1):
        if filled[index]:
            last = mapping[index]
        else:
            mapping[index] = last
    return mapping


def _text_conflict_id(
    *,
    base_start: int,
    base_end: int,
    candidate_start: int,
    candidate_end: int,
    base_text: str,
    human_text: str,
    candidate_text: str,
) -> str:
    payload = "\x1f".join(
        [
            str(base_start),
            str(base_end),
            str(candidate_start),
            str(candidate_end),
            base_text,
            human_text,
            candidate_text,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _validated_text_resolution(
    resolution: dict[str, Any] | None,
    *,
    conflict_id: str,
    base_text: str,
    human_text: str,
    candidate_text: str,
) -> tuple[list[str] | None, dict[str, Any] | None, str | None]:
    if not resolution:
        return None, None, None
    action = str(resolution.get("action") or "").strip().lower()
    expected_candidate = resolution.get("expected_candidate_text")
    if expected_candidate is not None and str(expected_candidate) != candidate_text:
        return None, None, "La candidata cambió desde que se eligió la resolución textual."
    expected_human = resolution.get("expected_human_text")
    if expected_human is not None and str(expected_human) != human_text:
        return None, None, "La edición humana cambió desde que se eligió la resolución textual."
    if action == "keep_candidate":
        return [], {
            "conflict_id": conflict_id,
            "action": action,
            "method": str(resolution.get("method") or "manual_keep_candidate"),
        }, None
    if action == "apply_human":
        return _TOKEN_RE.findall(human_text), {
            "conflict_id": conflict_id,
            "action": action,
            "method": str(resolution.get("method") or "manual_apply_human"),
        }, None
    if action == "manual_text":
        manual_text = str(resolution.get("manual_text") or "")
        return _TOKEN_RE.findall(manual_text), {
            "conflict_id": conflict_id,
            "action": action,
            "method": str(resolution.get("method") or "manual_custom_text"),
            "manual_text": manual_text,
        }, None
    return None, None, "La resolución textual elegida no tiene una acción válida."


def _merge_human_changes(
    base: str,
    edited: str,
    candidate: str,
    *,
    text_resolutions: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, list[RebaseTextConflict], list[str], int, list[dict[str, Any]]]:
    if edited == base:
        return candidate, [], [], 0, []
    resolution_map = text_resolutions or {}
    base_tokens = _TOKEN_RE.findall(base)
    edited_tokens = _TOKEN_RE.findall(edited)
    candidate_tokens = _TOKEN_RE.findall(candidate)
    human_opcodes = SequenceMatcher(None, base_tokens, edited_tokens, autojunk=False).get_opcodes()
    base_candidate = SequenceMatcher(None, base_tokens, candidate_tokens, autojunk=False).get_opcodes()
    boundary = _boundary_map(base_candidate, len(base_tokens))
    replacements: list[tuple[int, int, list[str], str]] = []
    text_conflicts: list[RebaseTextConflict] = []
    conflicts: list[str] = []
    resolution_plan: list[dict[str, Any]] = []
    changes = 0
    for tag, i1, i2, j1, j2 in human_opcodes:
        if tag == "equal":
            continue
        changes += 1
        c1 = boundary[i1]
        c2 = boundary[i2]
        base_segment = "".join(base_tokens[i1:i2])
        edited_segment = "".join(edited_tokens[j1:j2])
        candidate_segment = "".join(candidate_tokens[c1:c2])
        if _normalized(candidate_segment) == _normalized(edited_segment):
            continue
        if tag == "insert" or _normalized(candidate_segment) == _normalized(base_segment):
            replacements.append((c1, c2, edited_tokens[j1:j2], base_segment))
            continue
        similarity_to_edit = SequenceMatcher(
            None, _normalized(candidate_segment), _normalized(edited_segment), autojunk=False
        ).ratio()
        if similarity_to_edit >= 0.96:
            replacements.append((c1, c2, edited_tokens[j1:j2], base_segment))
            continue

        conflict_id = _text_conflict_id(
            base_start=i1,
            base_end=i2,
            candidate_start=c1,
            candidate_end=c2,
            base_text=base_segment,
            human_text=edited_segment,
            candidate_text=candidate_segment,
        )
        context = " ".join(base_segment.split())[:160] or "inserción entre fragmentos"
        replacement, decision, resolution_error = _validated_text_resolution(
            resolution_map.get(conflict_id),
            conflict_id=conflict_id,
            base_text=base_segment,
            human_text=edited_segment,
            candidate_text=candidate_segment,
        )
        if resolution_error:
            text_conflicts.append(
                RebaseTextConflict(
                    conflict_id=conflict_id,
                    reason_code="invalid_resolution",
                    reason=resolution_error,
                    base_text=base_segment,
                    human_text=edited_segment,
                    candidate_text=candidate_segment,
                    context=context,
                )
            )
            continue
        if decision is not None:
            resolution_plan.append(decision)
            if decision["action"] != "keep_candidate":
                replacements.append((c1, c2, replacement or [], base_segment))
            continue
        text_conflicts.append(
            RebaseTextConflict(
                conflict_id=conflict_id,
                reason_code="overlapping_text_change",
                reason=(
                    "La corrección humana y la candidata modificaron de manera distinta "
                    "el mismo tramo. Elegí cuál conservar o escribí el texto resultante."
                ),
                base_text=base_segment,
                human_text=edited_segment,
                candidate_text=candidate_segment,
                context=context,
            )
        )

    replacements.sort(key=lambda item: (item[0], item[1]))
    for previous, current in zip(replacements, replacements[1:]):
        if current[0] < previous[1]:
            conflicts.append(
                "Dos correcciones humanas resueltas se proyectan sobre el mismo tramo de la candidata."
            )
            break
    if conflicts or text_conflicts:
        return candidate, text_conflicts, conflicts, changes, resolution_plan
    merged = list(candidate_tokens)
    for c1, c2, replacement, _base_segment in reversed(replacements):
        merged[c1:c2] = replacement
    return "".join(merged), [], [], changes, resolution_plan

def _map_span(source: str, target: str, start: int, end: int) -> tuple[int, int]:
    opcodes = SequenceMatcher(None, source, target, autojunk=False).get_opcodes()
    boundary = _boundary_map(opcodes, len(source))
    return boundary[max(0, min(start, len(source)))], boundary[max(0, min(end, len(source)))]


def _best_target(spans: list[tuple[int, int]], start: int, end: int) -> int | None:
    best_index = None
    best_overlap = 0
    for index, (left, right) in enumerate(spans):
        overlap = max(0, min(end, right) - max(start, left))
        if overlap > best_overlap:
            best_overlap = overlap
            best_index = index
    if best_index is not None:
        return best_index
    if not spans:
        return None
    midpoint = (start + end) / 2
    distances = [abs(((left + right) / 2) - midpoint) for left, right in spans]
    return min(range(len(spans)), key=distances.__getitem__)



def _context(text: str, start: int, end: int, *, radius: int = 70) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = " ".join(text[left:right].split())
    if left:
        snippet = "…" + snippet
    if right < len(text):
        snippet += "…"
    return snippet


def _literal_occurrences(text: str, needle: str) -> list[tuple[int, int, str]]:
    if not needle:
        return []
    matches = [
        (match.start(), match.end(), match.group(0))
        for match in re.finditer(re.escape(needle), text)
    ]
    if matches:
        return matches
    return [
        (match.start(), match.end(), match.group(0))
        for match in re.finditer(re.escape(needle), text, flags=re.IGNORECASE)
    ]


def _flexible_occurrences(text: str, needle: str) -> list[tuple[int, int, str]]:
    words = re.findall(r"[\wÀ-ÖØ-öø-ÿ]+", needle, flags=re.UNICODE)
    if not words:
        return []
    pattern = r"\b" + r"[\W_]+".join(re.escape(word) for word in words) + r"\b"
    return [
        (match.start(), match.end(), match.group(0))
        for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.UNICODE)
    ]


def _fuzzy_candidates(
    text: str,
    needle: str,
    *,
    target_index: int,
    limit: int = 3,
) -> list[RebaseMentionCandidate]:
    needle_tokens = re.findall(r"\S+", needle)
    tokens = list(re.finditer(r"\S+", text))
    if not needle_tokens or not tokens:
        return []
    wanted = len(needle_tokens)
    candidates: list[RebaseMentionCandidate] = []
    for width in sorted({max(1, wanted - 1), wanted, wanted + 1}):
        for start_index in range(0, max(0, len(tokens) - width + 1)):
            group = tokens[start_index : start_index + width]
            start = group[0].start()
            end = group[-1].end()
            matched = text[start:end]
            score = SequenceMatcher(
                None, _normalized(needle), _normalized(matched), autojunk=False
            ).ratio()
            if score < 0.58:
                continue
            candidates.append(
                RebaseMentionCandidate(
                    target_index=target_index,
                    start_offset=start,
                    end_offset=end,
                    matched_text=matched,
                    context=_context(text, start, end),
                    method="similitud textual",
                    score=score,
                )
            )
    candidates.sort(key=lambda item: (-item.score, item.start_offset, item.end_offset))
    unique: list[RebaseMentionCandidate] = []
    seen: set[tuple[int, int]] = set()
    for item in candidates:
        key = (item.start_offset, item.end_offset)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _mention_candidates(
    rebased_text: str,
    spans: list[tuple[int, int]],
    mention_text: str,
    *,
    predicted_target_index: int | None,
    limit: int = 8,
) -> list[RebaseMentionCandidate]:
    found: list[RebaseMentionCandidate] = []
    for target_index, (left, right) in enumerate(spans):
        target_text = rebased_text[left:right]
        occurrences = _literal_occurrences(target_text, mention_text)
        method = "coincidencia exacta"
        if not occurrences:
            occurrences = _flexible_occurrences(target_text, mention_text)
            method = "coincidencia normalizada"
        for start, end, matched in occurrences:
            found.append(
                RebaseMentionCandidate(
                    target_index=target_index,
                    start_offset=start,
                    end_offset=end,
                    matched_text=matched,
                    context=_context(target_text, start, end),
                    method=method,
                    score=1.0 if method == "coincidencia exacta" else 0.97,
                )
            )
    if not found:
        target_order = list(range(len(spans)))
        if predicted_target_index is not None and predicted_target_index in target_order:
            target_order.remove(predicted_target_index)
            target_order.insert(0, predicted_target_index)
        for target_index in target_order:
            left, right = spans[target_index]
            found.extend(
                _fuzzy_candidates(
                    rebased_text[left:right],
                    mention_text,
                    target_index=target_index,
                    limit=3,
                )
            )
    found.sort(
        key=lambda item: (
            -item.score,
            0 if item.target_index == predicted_target_index else 1,
            item.target_index,
            item.start_offset,
        )
    )
    unique: list[RebaseMentionCandidate] = []
    seen: set[tuple[int, int, int]] = set()
    for item in found:
        key = (item.target_index, item.start_offset, item.end_offset)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _validated_mention_resolution(
    resolution: dict[str, Any] | None,
    *,
    mention: EntityMention,
    rebased_text: str,
    spans: list[tuple[int, int]],
) -> tuple[dict[str, Any] | None, str | None]:
    if not resolution:
        return None, None
    action = str(resolution.get("action") or "").strip().lower()
    if action == "reject":
        return {
            "mention_id": mention.id,
            "action": "reject",
            "method": str(resolution.get("method") or "manual"),
        }, None
    if action != "relocate":
        return None, "La resolución elegida no tiene una acción válida."
    try:
        target_index = int(resolution["target_index"])
        start_offset = int(resolution["start_offset"])
        end_offset = int(resolution["end_offset"])
    except (KeyError, TypeError, ValueError):
        return None, "La resolución manual no define un destino completo."
    if target_index < 0 or target_index >= len(spans):
        return None, "El bloque elegido ya no existe en la vista previa."
    left, right = spans[target_index]
    target_text = rebased_text[left:right]
    if start_offset < 0 or end_offset <= start_offset or end_offset > len(target_text):
        return None, "Los offsets elegidos están fuera del bloque candidato."
    matched_text = target_text[start_offset:end_offset]
    expected_text = resolution.get("matched_text")
    if expected_text is not None and str(expected_text) != matched_text:
        return None, "El texto candidato cambió desde que se eligió la resolución."
    return {
        "mention_id": mention.id,
        "action": "relocate",
        "target_index": target_index,
        "start_offset": start_offset,
        "end_offset": end_offset,
        "mention_text": matched_text,
        "method": str(resolution.get("method") or "manual"),
    }, None


def _projection_conflict_id(*, source_object_id: str, candidate_ids: list[str]) -> str:
    payload = "\x1f".join([source_object_id, *candidate_ids])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _projection_candidates(
    *,
    source_text: str,
    mapped_start: int,
    mapped_end: int,
    rebased_text: str,
    spans: list[tuple[int, int]],
    candidate_rows: list[ExtractedObject],
    limit: int = 5,
) -> list[RebaseProjectionCandidate]:
    mapped_length = max(1, mapped_end - mapped_start)
    normalized_source = _normalized(source_text)
    candidates: list[RebaseProjectionCandidate] = []
    for index, ((left, right), row) in enumerate(zip(spans, candidate_rows)):
        overlap = max(0, min(mapped_end, right) - max(mapped_start, left))
        overlap_score = min(1.0, overlap / mapped_length)
        target_text = rebased_text[left:right]
        text_score = SequenceMatcher(
            None,
            normalized_source,
            _normalized(target_text),
            autojunk=False,
        ).ratio()
        combined = (0.65 * overlap_score) + (0.35 * text_score)
        candidates.append(
            RebaseProjectionCandidate(
                target_index=index,
                order_index=row.order_index,
                text=target_text,
                overlap_score=overlap_score,
                text_score=text_score,
                combined_score=combined,
            )
        )
    candidates.sort(
        key=lambda item: (
            -item.combined_score,
            -item.text_score,
            item.order_index,
            item.target_index,
        )
    )
    return candidates[:limit]


def _validated_projection_resolution(
    resolution: dict[str, Any] | None,
    *,
    conflict_id: str,
    candidates: list[RebaseProjectionCandidate],
    candidate_rows: list[ExtractedObject],
) -> tuple[int | None, dict[str, Any] | None, str | None]:
    if not resolution:
        return None, None, None
    if str(resolution.get("action") or "").strip().lower() != "map":
        return None, None, "La resolución de proyección no tiene una acción válida."
    expected_ids = resolution.get("expected_candidate_ids")
    current_ids = [row.id for row in candidate_rows]
    if expected_ids is not None and list(expected_ids) != current_ids:
        return None, None, "Los bloques candidatos cambiaron desde que se eligió el destino."
    try:
        target_index = int(resolution["target_index"])
    except (KeyError, TypeError, ValueError):
        return None, None, "La resolución de proyección no define un bloque de destino."
    valid_targets = {item.target_index for item in candidates}
    if target_index not in valid_targets:
        return None, None, "El bloque elegido ya no está disponible entre los destinos revisados."
    return target_index, {
        "conflict_id": conflict_id,
        "action": "map",
        "target_index": target_index,
        "method": str(resolution.get("method") or "manual_object_projection"),
    }, None


def _metadata_conflict_id(*, target_index: int, kind: str, values: list[str | None]) -> str:
    payload = "\x1f".join(
        [str(target_index), kind, *["<none>" if value is None else str(value) for value in values]]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _validated_metadata_resolution(
    resolution: dict[str, Any] | None,
    *,
    conflict_id: str,
    options: list[RebaseMetadataOption],
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    if not resolution:
        return None, None, None
    if str(resolution.get("action") or "").strip().lower() != "select":
        return None, None, "La resolución de metadatos no tiene una acción válida."
    expected_values = resolution.get("expected_values")
    current_values = [item.value for item in options]
    if expected_values is not None and list(expected_values) != current_values:
        return None, None, "Las opciones de metadatos cambiaron desde que se tomó la decisión."
    selected = resolution.get("value")
    if selected not in current_values:
        return None, None, "El valor elegido ya no está disponible para este bloque."
    return selected, {
        "conflict_id": conflict_id,
        "action": "select",
        "value": selected,
        "method": str(resolution.get("method") or "manual_metadata_selection"),
    }, None


def _attribute_conflict_id(
    *,
    target_index: int,
    attribute_key: str,
    options: list[RebaseAttributeOption],
) -> str:
    payload = "\x1f".join(
        [
            str(target_index),
            attribute_key,
            *[
                f"{item.option_key}:{item.action}:{_attribute_signature(item.value)}"
                for item in options
            ],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _validated_attribute_resolution(
    resolution: dict[str, Any] | None,
    *,
    conflict_id: str,
    options: list[RebaseAttributeOption],
) -> tuple[bool, Any, dict[str, Any] | None, str | None]:
    if not resolution:
        return False, None, None, None
    action = str(resolution.get("action") or "").strip().lower()
    expected_keys = resolution.get("expected_option_keys")
    current_keys = [item.option_key for item in options]
    if expected_keys is not None and list(expected_keys) != current_keys:
        return False, None, None, (
            "Las opciones del atributo cambiaron desde que se tomó la decisión."
        )
    if action == "select":
        option_key = str(resolution.get("option_key") or "")
        selected = next((item for item in options if item.option_key == option_key), None)
        if selected is None:
            return False, None, None, (
                "El valor elegido ya no está disponible para este atributo."
            )
        if selected.action == "remove":
            return False, None, {
                "conflict_id": conflict_id,
                "action": "remove",
                "option_key": option_key,
                "method": str(
                    resolution.get("method") or "manual_attribute_selection"
                ),
            }, None
        return True, selected.value, {
            "conflict_id": conflict_id,
            "action": "set",
            "option_key": option_key,
            "value": selected.value,
            "method": str(resolution.get("method") or "manual_attribute_selection"),
        }, None
    if action == "manual_json":
        expected_keys = resolution.get("expected_option_keys")
        current_keys = [item.option_key for item in options]
        if expected_keys is not None and list(expected_keys) != current_keys:
            return False, None, None, (
                "Las opciones del atributo cambiaron desde que se escribió el valor manual."
            )
        return True, resolution.get("value"), {
            "conflict_id": conflict_id,
            "action": "set",
            "value": resolution.get("value"),
            "method": str(resolution.get("method") or "manual_attribute_json"),
        }, None
    return False, None, None, "La resolución del atributo no tiene una acción válida."


def _candidate_rows(session: Session, run_id: str, page: int) -> list[ExtractedObject]:
    return session.scalars(
        select(ExtractedObject)
        .where(
            ExtractedObject.extraction_run_id == run_id,
            ExtractedObject.page_number == page,
        )
        .order_by(ExtractedObject.order_index, ExtractedObject.id)
    ).all()


def _active_editable_rows(session: Session, page_id: str) -> list[EditableObject]:
    return session.scalars(
        select(EditableObject)
        .where(
            EditableObject.editable_page_id == page_id,
            EditableObject.lifecycle_status == "active",
        )
        .order_by(EditableObject.current_order_index, EditableObject.id)
    ).all()


def preview_editable_rebase(
    session: Session,
    *,
    source_key: str,
    page: int,
    candidate_run_id: str,
    mention_resolutions: dict[str, dict[str, Any]] | None = None,
    text_resolutions: dict[str, dict[str, Any]] | None = None,
    projection_resolutions: dict[str, dict[str, Any]] | None = None,
    metadata_resolutions: dict[str, dict[str, Any]] | None = None,
    attribute_resolutions: dict[str, dict[str, Any]] | None = None,
) -> RebasePreview:
    from archive_workbench.candidate_review import (
        _candidate_page,
        _editable_attributes,
        _registration,
    )

    resolution_map = mention_resolutions or {}
    projection_resolution_map = projection_resolutions or {}
    metadata_resolution_map = metadata_resolutions or {}
    attribute_resolution_map = attribute_resolutions or {}
    _registration_row, digital, _unit = _registration(session, source_key)
    run, candidate_page = _candidate_page(
        session,
        digital_object_id=digital.id,
        page=page,
        run_id=candidate_run_id,
    )
    editable_page = session.scalar(
        select(EditablePage).where(
            EditablePage.digital_object_id == digital.id,
            EditablePage.page_number == page,
        )
    )
    if editable_page is None:
        raise ValueError("La página todavía no tiene una capa editable para rebasar.")
    if editable_page.source_extraction_page_id == candidate_page.id:
        raise ValueError("La candidata ya es la base de la página editable.")

    old_source_rows = _candidate_rows(session, editable_page.source_extraction_run_id, page)
    editable_rows = _active_editable_rows(session, editable_page.id)
    candidate_rows = _candidate_rows(session, run.id, page)
    if not old_source_rows or not editable_rows or not candidate_rows:
        raise ValueError("El rebase requiere una base anterior, una edición activa y una candidata completa.")

    base_text, _base_spans = _join_texts(old_source_rows, "original_text")
    editable_text, editable_spans = _join_texts(editable_rows, "current_text")
    candidate_text, candidate_spans = _join_texts(candidate_rows, "original_text")
    (
        rebased_text,
        text_conflicts,
        conflicts,
        human_change_count,
        text_resolution_plan,
    ) = _merge_human_changes(
        base_text,
        editable_text,
        candidate_text,
        text_resolutions=text_resolutions,
    )

    action_count = int(
        session.scalar(
            select(func.count())
            .select_from(EditablePageAction)
            .where(EditablePageAction.editable_page_id == editable_page.id)
        )
        or 0
    )
    # El historial estructural no es, por sí mismo, un conflicto. La fuente de verdad
    # es el snapshot activo actual. Las incompatibilidades reales se detectan abajo
    # al proyectar objetos, anotaciones y metadatos sobre los bloques candidatos.

    rebased_candidate_spans = [
        _map_span(candidate_text, rebased_text, start, end) for start, end in candidate_spans
    ]
    object_targets: dict[str, int] = {}
    annotation_counts = [0 for _ in candidate_rows]
    object_metadata: dict[int, list[EditableObject]] = {
        index: [] for index in range(len(candidate_rows))
    }

    editable_ids = [row.id for row in editable_rows]
    mention_rows = session.scalars(
        select(EntityMention)
        .where(
            EntityMention.editable_object_id.in_(editable_ids),
            EntityMention.status != "rejected",
        )
        .order_by(EntityMention.editable_object_id, EntityMention.start_offset, EntityMention.id)
    ).all()
    comment_rows = session.scalars(
        select(EditableObjectComment).where(
            EditableObjectComment.editable_object_id.in_(editable_ids)
        )
    ).all()
    tag_rows = session.scalars(
        select(EditableObjectTag).where(EditableObjectTag.editable_object_id.in_(editable_ids))
    ).all()
    by_object_mentions: dict[str, list[EntityMention]] = {}
    for mention in mention_rows:
        by_object_mentions.setdefault(mention.editable_object_id, []).append(mention)
    by_object_comments: dict[str, list[EditableObjectComment]] = {}
    for comment in comment_rows:
        by_object_comments.setdefault(comment.editable_object_id, []).append(comment)
    by_object_tags: dict[str, list[EditableObjectTag]] = {}
    for tag in tag_rows:
        by_object_tags.setdefault(tag.editable_object_id, []).append(tag)

    authority_ids = {mention.authority_id for mention in mention_rows if mention.authority_id}
    authority_names = {
        authority.id: authority.preferred_name
        for authority in session.scalars(
            select(AuthorityRecord).where(AuthorityRecord.id.in_(authority_ids))
        ).all()
    }

    old_source_by_id = {row.id: row for row in old_source_rows}
    specialized_attributes_by_object = {
        row.id: _human_specialized_attributes(
            row, old_source_by_id.get(row.source_extracted_object_id or "")
        )
        for row in editable_rows
    }
    projection_conflicts: list[RebaseProjectionConflict] = []
    projection_resolution_plan: list[dict[str, Any]] = []

    mention_plan: list[dict[str, Any]] = []
    mention_conflicts: list[RebaseMentionConflict] = []
    mention_by_id = {mention.id: mention for mention in mention_rows}
    mention_contexts: dict[str, str] = {}
    mention_predictions: dict[str, int | None] = {}
    mention_candidates: dict[str, list[RebaseMentionCandidate]] = {}

    for row, (start, end) in zip(editable_rows, editable_spans):
        mapped_start, mapped_end = _map_span(editable_text, rebased_text, start, end)
        source = old_source_by_id.get(row.source_extracted_object_id or "")
        human_type_override = source is None or row.current_object_type != source.object_type
        has_metadata = bool(
            row.document_part_id
            or row.review_status != "unreviewed"
            or human_type_override
            or by_object_mentions.get(row.id)
            or by_object_comments.get(row.id)
            or by_object_tags.get(row.id)
            or specialized_attributes_by_object.get(row.id)
        )
        projection_candidates = _projection_candidates(
            source_text=row.current_text,
            mapped_start=mapped_start,
            mapped_end=mapped_end,
            rebased_text=rebased_text,
            spans=rebased_candidate_spans,
            candidate_rows=candidate_rows,
        )
        target_index = projection_candidates[0].target_index if projection_candidates else None
        weak_projection = bool(
            has_metadata
            and projection_candidates
            and projection_candidates[0].text_score < 0.20
        )
        ambiguous_projection = bool(
            has_metadata
            and len(projection_candidates) > 1
            and projection_candidates[0].combined_score < 0.55
            and (
                projection_candidates[0].combined_score
                - projection_candidates[1].combined_score
            ) < 0.06
        )
        if weak_projection or ambiguous_projection:
            conflict_id = _projection_conflict_id(
                source_object_id=row.id,
                candidate_ids=[item.id for item in candidate_rows],
            )
            resolved_target, decision, resolution_error = _validated_projection_resolution(
                projection_resolution_map.get(conflict_id),
                conflict_id=conflict_id,
                candidates=projection_candidates,
                candidate_rows=candidate_rows,
            )
            if resolution_error:
                projection_conflicts.append(
                    RebaseProjectionConflict(
                        conflict_id=conflict_id,
                        source_object_id=row.id,
                        source_order_index=row.current_order_index,
                        source_text=row.current_text,
                        reason=resolution_error,
                        candidates=projection_candidates,
                    )
                )
                continue
            if decision is not None:
                projection_resolution_plan.append(decision)
                target_index = resolved_target
            else:
                projection_conflicts.append(
                    RebaseProjectionConflict(
                        conflict_id=conflict_id,
                        source_object_id=row.id,
                        source_order_index=row.current_order_index,
                        source_text=row.current_text,
                        reason=(
                            "El objeto contiene anotaciones o metadatos, pero su texto cambió "
                            "demasiado para elegir un bloque candidato sin revisión."
                            if weak_projection
                            else (
                                "Dos bloques candidatos tienen una proyección demasiado similar "
                                "para trasladar anotaciones automáticamente."
                            )
                        ),
                        candidates=projection_candidates,
                    )
                )
                continue
        if target_index is None:
            if has_metadata:
                conflicts.append(
                    f"No pudo relocalizarse el objeto editable {row.current_order_index + 1} con sus anotaciones."
                )
            continue
        object_targets[row.id] = target_index
        object_metadata[target_index].append(row)
        annotation_counts[target_index] += (
            len(by_object_mentions.get(row.id, []))
            + len(by_object_comments.get(row.id, []))
            + len(by_object_tags.get(row.id, []))
            + len(specialized_attributes_by_object.get(row.id, {}))
            + (1 if row.document_part_id else 0)
        )

        for mention in by_object_mentions.get(row.id, []):
            source_start = mention.start_offset or 0
            source_end = mention.end_offset or source_start
            mention_contexts[mention.id] = _context(row.current_text, source_start, source_end)
            mention_predictions[mention.id] = target_index
            candidates = _mention_candidates(
                rebased_text,
                rebased_candidate_spans,
                mention.mention_text,
                predicted_target_index=target_index,
            )
            mention_candidates[mention.id] = candidates

            resolved, resolution_error = _validated_mention_resolution(
                resolution_map.get(mention.id),
                mention=mention,
                rebased_text=rebased_text,
                spans=rebased_candidate_spans,
            )
            if resolution_error:
                mention_conflicts.append(
                    RebaseMentionConflict(
                        mention_id=mention.id,
                        mention_text=mention.mention_text,
                        authority_id=mention.authority_id,
                        authority_name=authority_names.get(mention.authority_id),
                        status=mention.status,
                        reason_code="invalid_resolution",
                        reason=resolution_error,
                        source_context=mention_contexts[mention.id],
                        predicted_target_index=target_index,
                        candidates=candidates,
                    )
                )
                continue
            if resolved is not None:
                mention_plan.append(resolved)
                continue

            if mention.start_offset is None or mention.end_offset is None:
                mention_conflicts.append(
                    RebaseMentionConflict(
                        mention_id=mention.id,
                        mention_text=mention.mention_text,
                        authority_id=mention.authority_id,
                        authority_name=authority_names.get(mention.authority_id),
                        status=mention.status,
                        reason_code="missing_offsets",
                        reason=(
                            "La mención no tiene offsets en la edición anterior. "
                            "Debe elegirse un destino o rechazarse explícitamente."
                        ),
                        source_context=mention_contexts[mention.id],
                        predicted_target_index=target_index,
                        candidates=candidates,
                    )
                )
                continue

            high_confidence = [
                item
                for item in candidates
                if item.method in {"coincidencia exacta", "coincidencia normalizada"}
            ]
            if len(high_confidence) == 1:
                item = high_confidence[0]
                mention_plan.append(
                    {
                        "mention_id": mention.id,
                        "action": "relocate",
                        "target_index": item.target_index,
                        "start_offset": item.start_offset,
                        "end_offset": item.end_offset,
                        "mention_text": item.matched_text,
                        "method": "automatic_global_match",
                    }
                )
                continue

            reason_code = "ambiguous_match" if len(high_confidence) > 1 else "missing_exact"
            reason = (
                "La mención aparece en más de un destino posible y requiere elegir uno."
                if high_confidence
                else (
                    "La mención ya no aparece exactamente en la nueva base. "
                    "Debe elegirse una sugerencia, marcar un fragmento exacto o rechazarla."
                )
            )
            mention_conflicts.append(
                RebaseMentionConflict(
                    mention_id=mention.id,
                    mention_text=mention.mention_text,
                    authority_id=mention.authority_id,
                    authority_name=authority_names.get(mention.authority_id),
                    status=mention.status,
                    reason_code=reason_code,
                    reason=reason,
                    source_context=mention_contexts[mention.id],
                    predicted_target_index=target_index,
                    candidates=candidates,
                )
            )

    # Dos menciones activas no pueden conservar exactamente el mismo anclaje. Si ocurre,
    # ninguna de las dos se decide de manera implícita: ambas requieren una resolución.
    active_plan = [item for item in mention_plan if item.get("action") == "relocate"]
    duplicate_groups: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for item in active_plan:
        key = (item["target_index"], item["start_offset"], item["end_offset"])
        duplicate_groups.setdefault(key, []).append(item)
    duplicate_ids: set[str] = set()
    for group in duplicate_groups.values():
        if len(group) < 2:
            continue
        duplicate_ids.update(item["mention_id"] for item in group)
        for item in group:
            mention = mention_by_id[item["mention_id"]]
            mention_conflicts.append(
                RebaseMentionConflict(
                    mention_id=mention.id,
                    mention_text=mention.mention_text,
                    authority_id=mention.authority_id,
                    authority_name=authority_names.get(mention.authority_id),
                    status=mention.status,
                    reason_code="duplicate_target",
                    reason=(
                        "Dos menciones activas quedarían sobre el mismo fragmento. "
                        "Elegí cuál conservar, relocalizá una de ellas o rechazá el duplicado."
                    ),
                    source_context=mention_contexts.get(mention.id, mention.mention_text),
                    predicted_target_index=mention_predictions.get(mention.id),
                    candidates=mention_candidates.get(mention.id, []),
                )
            )
    if duplicate_ids:
        mention_plan = [
            item for item in mention_plan if item.get("mention_id") not in duplicate_ids
        ]

    part_ids = {row.document_part_id for row in editable_rows if row.document_part_id}
    part_labels = {
        part.id: f"{part.title} · {part.part_key}"
        for part in session.scalars(select(DocumentPart).where(DocumentPart.id.in_(part_ids))).all()
    }
    metadata_conflicts: list[RebaseMetadataConflict] = []
    metadata_plan: dict[int, dict[str, Any]] = {}
    metadata_resolution_plan: list[dict[str, Any]] = []

    def resolve_metadata(
        *,
        target_index: int,
        kind: str,
        values: list[str | None],
        labels: dict[str | None, str],
        reason: str,
        source_object_ids: list[str],
    ) -> str | None:
        unique_values = list(dict.fromkeys(values))
        options = [
            RebaseMetadataOption(value=value, label=labels.get(value, str(value)))
            for value in unique_values
        ]
        conflict_id = _metadata_conflict_id(
            target_index=target_index, kind=kind, values=unique_values
        )
        selected, decision, error = _validated_metadata_resolution(
            metadata_resolution_map.get(conflict_id),
            conflict_id=conflict_id,
            options=options,
        )
        if error:
            metadata_conflicts.append(
                RebaseMetadataConflict(
                    conflict_id=conflict_id,
                    target_index=target_index,
                    kind=kind,
                    reason=error,
                    options=options,
                    source_object_ids=source_object_ids,
                )
            )
            return None
        if decision is not None:
            metadata_resolution_plan.append(decision)
            return selected
        metadata_conflicts.append(
            RebaseMetadataConflict(
                conflict_id=conflict_id,
                target_index=target_index,
                kind=kind,
                reason=reason,
                options=options,
                source_object_ids=source_object_ids,
            )
        )
        return None

    for index, rows in object_metadata.items():
        source_ids = [row.id for row in rows]
        parts = list(dict.fromkeys(row.document_part_id for row in rows if row.document_part_id))
        if len(parts) <= 1:
            selected_part = parts[0] if parts else None
        else:
            selected_part = resolve_metadata(
                target_index=index,
                kind="document_part",
                values=[*parts, None],
                labels={**part_labels, None: "Sin asignación a parte documental"},
                reason=(
                    "Varios objetos que convergen en este bloque pertenecen a partes "
                    "documentales distintas. Elegí cuál conservar o dejalo sin asignación."
                ),
                source_object_ids=source_ids,
            )

        statuses = list(
            dict.fromkeys(row.review_status for row in rows if row.review_status != "unreviewed")
        )
        if len(statuses) <= 1:
            selected_status = statuses[0] if statuses else "unreviewed"
        else:
            selected_status = resolve_metadata(
                target_index=index,
                kind="review_status",
                values=[*statuses, "unreviewed"],
                labels={
                    "unreviewed": "Sin revisar",
                    "in_review": "En revisión",
                    "reviewed": "Revisado",
                    "approved": "Aprobado",
                    "rejected": "Rechazado",
                },
                reason=(
                    "Varios objetos que convergen en este bloque tienen estados de revisión "
                    "diferentes. Elegí el estado resultante."
                ),
                source_object_ids=source_ids,
            )

        candidate_type = candidate_rows[index].object_type
        human_type_overrides: list[str] = []
        for row in rows:
            source = old_source_by_id.get(row.source_extracted_object_id or "")
            if source is None or row.current_object_type != source.object_type:
                human_type_overrides.append(row.current_object_type)
        human_type_overrides = list(dict.fromkeys(human_type_overrides))
        type_values = list(dict.fromkeys([candidate_type, *human_type_overrides]))
        if len(type_values) <= 1:
            selected_type = candidate_type
        else:
            selected_type = resolve_metadata(
                target_index=index,
                kind="object_type",
                values=type_values,
                labels={value: value for value in type_values},
                reason=(
                    "La clasificación humana del bloque no coincide con la clasificación de la "
                    "candidata. Elegí el tipo que debe quedar."
                ),
                source_object_ids=source_ids,
            )

        metadata_plan[index] = {
            "document_part_id": selected_part,
            "review_status": selected_status,
            "object_type": selected_type,
        }

    attribute_conflicts: list[RebaseAttributeConflict] = []
    attribute_plan: dict[int, dict[str, Any]] = {}
    attribute_resolution_plan: list[dict[str, Any]] = []
    specialized_attribute_count = 0

    for index, rows in object_metadata.items():
        candidate_attributes = dict(_editable_attributes(candidate_rows[index]))
        merged_attributes = dict(candidate_attributes)
        values_by_key: dict[str, list[tuple[str, Any]]] = {}
        for row in rows:
            for key, value in specialized_attributes_by_object.get(row.id, {}).items():
                values_by_key.setdefault(key, []).append((row.id, value))

        for attribute_key, source_values in sorted(values_by_key.items()):
            specialized_attribute_count += 1
            distinct_human: dict[str, dict[str, Any]] = {}
            for source_object_id, value in source_values:
                signature = _attribute_signature(value)
                entry = distinct_human.setdefault(
                    signature, {"value": value, "source_object_ids": []}
                )
                entry["source_object_ids"].append(source_object_id)

            candidate_present = attribute_key in candidate_attributes
            candidate_value = candidate_attributes.get(attribute_key)
            candidate_signature = (
                _attribute_signature(candidate_value) if candidate_present else None
            )
            human_signatures = list(distinct_human)

            if len(human_signatures) == 1 and (
                not candidate_present or candidate_signature == human_signatures[0]
            ):
                merged_attributes[attribute_key] = distinct_human[human_signatures[0]][
                    "value"
                ]
                continue

            options: list[RebaseAttributeOption] = []
            if candidate_present:
                options.append(
                    RebaseAttributeOption(
                        option_key="candidate",
                        label=(
                            "Conservar el valor de la candidata: "
                            f"{_attribute_signature(candidate_value)[:240]}"
                        ),
                        action="set",
                        value=candidate_value,
                    )
                )
            human_option_position = 0
            for signature in human_signatures:
                if candidate_present and signature == candidate_signature:
                    continue
                human_option_position += 1
                entry = distinct_human[signature]
                position = human_option_position
                options.append(
                    RebaseAttributeOption(
                        option_key=f"human_{position}_{hashlib.sha256(signature.encode('utf-8')).hexdigest()[:10]}",
                        label=(
                            "Conservar el valor humano "
                            f"({len(entry['source_object_ids'])} objeto/s): {signature[:240]}"
                        ),
                        action="set",
                        value=entry["value"],
                        source_object_ids=list(entry["source_object_ids"]),
                    )
                )
            options.append(
                RebaseAttributeOption(
                    option_key="remove",
                    label="No trasladar este atributo al bloque nuevo",
                    action="remove",
                )
            )
            conflict_id = _attribute_conflict_id(
                target_index=index,
                attribute_key=attribute_key,
                options=options,
            )
            has_value, selected_value, decision, error = _validated_attribute_resolution(
                attribute_resolution_map.get(conflict_id),
                conflict_id=conflict_id,
                options=options,
            )
            if error:
                attribute_conflicts.append(
                    RebaseAttributeConflict(
                        conflict_id=conflict_id,
                        target_index=index,
                        attribute_key=attribute_key,
                        reason=error,
                        options=options,
                        source_object_ids=[row.id for row in rows],
                    )
                )
                continue
            if decision is None:
                reason = (
                    "Varios objetos que convergen en este bloque tienen valores diferentes "
                    "para el mismo atributo especializado."
                    if len(human_signatures) > 1
                    else (
                        "El atributo especializado de la edición humana no coincide con el "
                        "valor producido por la candidata."
                    )
                )
                attribute_conflicts.append(
                    RebaseAttributeConflict(
                        conflict_id=conflict_id,
                        target_index=index,
                        attribute_key=attribute_key,
                        reason=reason,
                        options=options,
                        source_object_ids=[row.id for row in rows],
                    )
                )
                continue
            attribute_resolution_plan.append(
                {**decision, "attribute_key": attribute_key, "target_index": index}
            )
            if has_value:
                merged_attributes[attribute_key] = selected_value
            else:
                merged_attributes.pop(attribute_key, None)

        attribute_plan[index] = merged_attributes

    object_previews: list[RebaseObjectPreview] = []
    for index, (source, (start, end)) in enumerate(zip(candidate_rows, rebased_candidate_spans)):
        object_previews.append(
            RebaseObjectPreview(
                order_index=source.order_index,
                source_object_id=source.id,
                object_type=str(
                    metadata_plan.get(index, {}).get("object_type") or source.object_type
                ),
                candidate_text=source.original_text,
                rebased_text=rebased_text[start:end],
                carried_annotations=annotation_counts[index],
            )
        )

    diff = "\n".join(
        unified_diff(
            candidate_text.splitlines(),
            rebased_text.splitlines(),
            fromfile="candidata Surya",
            tofile="resultado del rebase",
            lineterm="",
        )
    )
    conflicts = list(dict.fromkeys(conflicts))
    unique_mention_conflicts: list[RebaseMentionConflict] = []
    seen_conflicts: set[tuple[str, str]] = set()
    for item in mention_conflicts:
        key = (item.mention_id, item.reason_code)
        if key in seen_conflicts:
            continue
        seen_conflicts.add(key)
        unique_mention_conflicts.append(item)
    plan = {
        "candidate_page_id": candidate_page.id,
        "candidate_object_ids": [row.id for row in candidate_rows],
        "rebased_candidate_spans": rebased_candidate_spans,
        "object_targets": object_targets,
        "mention_plan": mention_plan,
        "manual_mention_resolution_count": sum(
            item.get("method") != "automatic_global_match" for item in mention_plan
        ),
        "text_resolution_plan": text_resolution_plan,
        "manual_text_resolution_count": len(text_resolution_plan),
        "projection_resolution_plan": projection_resolution_plan,
        "manual_projection_resolution_count": len(projection_resolution_plan),
        "metadata_plan": metadata_plan,
        "metadata_resolution_plan": metadata_resolution_plan,
        "manual_metadata_resolution_count": len(metadata_resolution_plan),
        "attribute_plan": attribute_plan,
        "attribute_resolution_plan": attribute_resolution_plan,
        "manual_attribute_resolution_count": len(attribute_resolution_plan),
        "specialized_attribute_count": specialized_attribute_count,
        "structural_action_count": action_count,
    }
    return RebasePreview(
        source_key=source_key,
        page=page,
        candidate_run_id=candidate_run_id,
        editable_page_id=editable_page.id,
        expected_page_revision=editable_page.revision_number,
        can_apply=(
            not conflicts
            and not text_conflicts
            and not projection_conflicts
            and not unique_mention_conflicts
            and not metadata_conflicts
            and not attribute_conflicts
        ),
        conflicts=conflicts,
        text_conflicts=text_conflicts,
        projection_conflicts=projection_conflicts,
        mention_conflicts=unique_mention_conflicts,
        metadata_conflicts=metadata_conflicts,
        attribute_conflicts=attribute_conflicts,
        base_text=base_text,
        editable_text=editable_text,
        candidate_text=candidate_text,
        rebased_text=rebased_text,
        candidate_objects=object_previews,
        old_object_count=len(editable_rows),
        new_object_count=len(candidate_rows),
        human_change_count=human_change_count,
        mention_count=len(mention_rows),
        comment_count=len(comment_rows),
        tag_count=len(tag_rows),
        document_part_count=sum(row.document_part_id is not None for row in editable_rows),
        structural_action_count=action_count,
        unified_text_diff=diff,
        _plan=plan,
    )


def _release_reused_source_links(
    session: Session,
    *,
    editable_page_id: str,
    candidate_source_ids: set[str],
    active_old_ids: set[str],
    changed_by: str,
) -> int:
    """Libera vínculos OCR históricos antes de reutilizar una candidata.

    ``editable_objects`` conserva una unicidad histórica por página y objeto OCR.
    Para permitir secuencias A → B → A sin recrear la tabla, el vínculo fuerte
    permanece únicamente en la representación vigente. La procedencia de las
    representaciones retiradas se conserva explícitamente en sus atributos y
    revisiones append-only.
    """
    if not candidate_source_ids:
        return 0
    rows = session.scalars(
        select(EditableObject)
        .where(
            EditableObject.editable_page_id == editable_page_id,
            EditableObject.source_extracted_object_id.in_(candidate_source_ids),
        )
        .order_by(EditableObject.created_at, EditableObject.id)
    ).all()
    released = 0
    for row in rows:
        source_id = row.source_extracted_object_id
        if source_id is None:
            continue
        attributes = dict(row.current_attributes_json or {})
        previous_ids = attributes.get("historical_source_extracted_object_ids", [])
        if not isinstance(previous_ids, list):
            previous_ids = [previous_ids] if previous_ids else []
        historical_ids = list(dict.fromkeys([*previous_ids, source_id]))
        attributes["historical_source_extracted_object_ids"] = historical_ids
        row.current_attributes_json = attributes
        row.source_extracted_object_id = None
        row.updated_by = changed_by
        row.updated_at = utc_now()
        released += 1

        # Los objetos activos serán auditados inmediatamente como retirados por
        # el propio rebase. Los históricos reciben una revisión específica.
        if row.id not in active_old_ids:
            base_revision = row.revision_number
            row.revision_number += 1
            _append_revision(
                session,
                row,
                operation="rebase_source_release",
                created_by=changed_by,
                note=(
                    "Vínculo OCR histórico liberado para reutilizar la misma "
                    "candidata en un nuevo rebase."
                ),
                base_revision_number=base_revision,
            )
    session.flush()
    return released


def apply_editable_rebase(
    session: Session,
    *,
    decisions: ProjectDecisions,
    source_key: str,
    page: int,
    candidate_run_id: str,
    expected_page_revision: int,
    rebased_by: str,
    note: str | None = None,
    mention_resolutions: dict[str, dict[str, Any]] | None = None,
    text_resolutions: dict[str, dict[str, Any]] | None = None,
    projection_resolutions: dict[str, dict[str, Any]] | None = None,
    metadata_resolutions: dict[str, dict[str, Any]] | None = None,
    attribute_resolutions: dict[str, dict[str, Any]] | None = None,
) -> RebaseResult:
    preview = preview_editable_rebase(
        session,
        source_key=source_key,
        page=page,
        candidate_run_id=candidate_run_id,
        mention_resolutions=mention_resolutions,
        text_resolutions=text_resolutions,
        projection_resolutions=projection_resolutions,
        metadata_resolutions=metadata_resolutions,
        attribute_resolutions=attribute_resolutions,
    )
    if preview.expected_page_revision != expected_page_revision:
        raise ValueError(
            "La página cambió desde la vista previa; vuelva a preparar el rebase antes de aplicarlo."
        )
    if not preview.can_apply:
        raise ValueError("El rebase contiene conflictos y no puede aplicarse automáticamente.")

    from archive_workbench.candidate_review import _candidate_page, _editable_attributes, _registration

    _registration_row, digital, _unit = _registration(session, source_key)
    run, candidate_page = _candidate_page(
        session,
        digital_object_id=digital.id,
        page=page,
        run_id=candidate_run_id,
    )
    editable_page = session.get(EditablePage, preview.editable_page_id)
    if editable_page is None:
        raise RuntimeError("La página editable dejó de existir durante el rebase.")
    old_rows = _active_editable_rows(session, editable_page.id)
    candidate_rows = _candidate_rows(session, run.id, page)
    source_links_released = _release_reused_source_links(
        session,
        editable_page_id=editable_page.id,
        candidate_source_ids={row.id for row in candidate_rows},
        active_old_ids={row.id for row in old_rows},
        changed_by=rebased_by,
    )

    _selected_run, changed = select_extraction_pages(
        session,
        source_key=source_key,
        selected_by=rebased_by,
        run_id=run.id,
        pages={page},
        note=note or "Candidata seleccionada para rebasar la edición existente.",
    )
    selection = session.scalar(
        select(ExtractionPageSelection).where(
            ExtractionPageSelection.digital_object_id == digital.id,
            ExtractionPageSelection.page_number == page,
        )
    )
    if selection is None:
        raise RuntimeError("No pudo materializarse la selección canónica.")

    new_objects: list[EditableObject] = []
    for source, preview_object in zip(candidate_rows, preview.candidate_objects):
        object_type = source.object_type
        try:
            _allowed_object_type(decisions, object_type)
        except ValueError:
            object_type = "paragraph"
            _allowed_object_type(decisions, object_type)
        mapped_old = [
            row for row in old_rows if preview._plan["object_targets"].get(row.id) == len(new_objects)
        ]
        resolved_metadata = preview._plan["metadata_plan"].get(
            len(new_objects),
            {
                "document_part_id": None,
                "review_status": "unreviewed",
                "object_type": object_type,
            },
        )
        object_type = str(resolved_metadata.get("object_type") or object_type)
        try:
            _allowed_object_type(decisions, object_type)
        except ValueError:
            object_type = "paragraph"
            _allowed_object_type(decisions, object_type)
        obj = EditableObject(
            id=new_id(),
            editable_page_id=editable_page.id,
            digital_object_id=digital.id,
            page_number=page,
            document_part_id=resolved_metadata.get("document_part_id"),
            source_extracted_object_id=source.id,
            source_origin_id=source.origin_id,
            current_text=preview_object.rebased_text,
            current_object_type=object_type,
            current_order_index=source.order_index,
            current_geometry_json=source.geometry_json or [],
            current_attributes_json={
                **preview._plan["attribute_plan"].get(
                    len(new_objects), _editable_attributes(source)
                ),
                "rebased_from_object_ids": [row.id for row in mapped_old],
            },
            lifecycle_status="active",
            review_status=str(resolved_metadata.get("review_status") or "unreviewed"),
            revision_number=1,
            created_by=rebased_by,
            created_at=utc_now(),
            updated_by=rebased_by,
            updated_at=utc_now(),
        )
        session.add(obj)
        session.flush()
        _append_revision(
            session,
            obj,
            operation="rebase_import",
            created_by=rebased_by,
            note="Objeto creado desde la candidata y las correcciones humanas rebasadas.",
            base_revision_number=None,
        )
        new_objects.append(obj)

    comments_relocated = 0
    tags_relocated = 0
    tags_deduplicated = 0
    document_parts_relocated = 0
    target_tag_keys: dict[int, set[tuple[str, str]]] = {
        index: set() for index in range(len(new_objects))
    }
    for old in old_rows:
        target_index = preview._plan["object_targets"].get(old.id)
        if target_index is not None:
            target = new_objects[target_index]
            for comment in session.scalars(
                select(EditableObjectComment).where(
                    EditableObjectComment.editable_object_id == old.id
                )
            ).all():
                comment.editable_object_id = target.id
                comments_relocated += 1
            for tag in session.scalars(
                select(EditableObjectTag).where(EditableObjectTag.editable_object_id == old.id)
            ).all():
                key = (tag.tag_kind, tag.normalized_tag)
                if key in target_tag_keys[target_index]:
                    # El duplicado permanece unido al objeto histórico retirado. No se borra.
                    tags_deduplicated += 1
                    continue
                target_tag_keys[target_index].add(key)
                tag.editable_object_id = target.id
                tags_relocated += 1
            if old.document_part_id is not None:
                document_parts_relocated += 1
        base_revision = old.revision_number
        old.lifecycle_status = "deleted"
        old.revision_number += 1
        old.updated_by = rebased_by
        old.updated_at = utc_now()
        _append_revision(
            session,
            old,
            operation="rebase_retired",
            created_by=rebased_by,
            note="Objeto anterior retirado después de rebasar la edición.",
            base_revision_number=base_revision,
        )

    mentions_relocated = 0
    mentions_rejected = 0
    for item in preview._plan["mention_plan"]:
        mention = session.get(EntityMention, item["mention_id"])
        if mention is None:
            raise RuntimeError("Una mención dejó de existir durante el rebase.")
        if item.get("action") == "reject":
            mention.status = "rejected"
            mention.revision += 1
            mention.updated_by = rebased_by
            mention.updated_at = utc_now()
            _append_mention_revision(
                session,
                mention,
                operation="rebase_reject_conflict",
                changed_by=rebased_by,
                note=(
                    "Mención rechazada explícitamente durante la resolución "
                    "de conflictos del rebase."
                ),
            )
            mentions_rejected += 1
            continue
        target = new_objects[item["target_index"]]
        mention.editable_object_id = target.id
        mention.start_offset = item["start_offset"]
        mention.end_offset = item["end_offset"]
        mention.mention_text = item["mention_text"]
        mention.normalized_text = normalize_authority_text(item["mention_text"])
        mention.object_revision_number = target.revision_number
        mention.revision += 1
        mention.updated_by = rebased_by
        mention.updated_at = utc_now()
        operation = (
            "rebase_relocate"
            if item.get("method") == "automatic_global_match"
            else "rebase_relocate_manual"
        )
        _append_mention_revision(
            session,
            mention,
            operation=operation,
            changed_by=rebased_by,
            note=(
                "Mención relocalizada durante el rebase de la edición "
                f"mediante {item.get('method') or 'resolución manual'}."
            ),
        )
        mentions_relocated += 1

    previous_run_id = editable_page.source_extraction_run_id
    previous_page_id = editable_page.source_extraction_page_id
    base_page_revision = editable_page.revision_number
    editable_page.source_extraction_run_id = run.id
    editable_page.source_extraction_page_id = candidate_page.id
    editable_page.source_selection_id = selection.id
    editable_page.status = "active"
    editable_page.revision_number += 1
    editable_page.updated_at = utc_now()
    _append_page_revision(
        session,
        editable_page,
        operation="rebase",
        created_by=rebased_by,
        note=note or "Edición humana rebasada sobre una nueva extracción candidata.",
        details={
            "strategy": "three_way_text_rebase",
            "previous_extraction_run_id": previous_run_id,
            "previous_extraction_page_id": previous_page_id,
            "old_editable_object_ids": [row.id for row in old_rows],
            "new_editable_object_ids": [row.id for row in new_objects],
            "human_change_count": preview.human_change_count,
            "mentions_relocated": mentions_relocated,
            "mentions_rejected": mentions_rejected,
            "manual_mention_resolution_count": preview._plan[
                "manual_mention_resolution_count"
            ],
            "manual_text_resolution_count": preview._plan[
                "manual_text_resolution_count"
            ],
            "manual_projection_resolution_count": preview._plan[
                "manual_projection_resolution_count"
            ],
            "projection_resolution_methods": [
                item.get("method") for item in preview._plan["projection_resolution_plan"]
            ],
            "manual_metadata_resolution_count": preview._plan[
                "manual_metadata_resolution_count"
            ],
            "metadata_resolution_methods": [
                item.get("method") for item in preview._plan["metadata_resolution_plan"]
            ],
            "manual_attribute_resolution_count": preview._plan[
                "manual_attribute_resolution_count"
            ],
            "attribute_resolution_methods": [
                item.get("method") for item in preview._plan["attribute_resolution_plan"]
            ],
            "specialized_attribute_count": preview._plan[
                "specialized_attribute_count"
            ],
            "structural_actions_absorbed": preview.structural_action_count,
            "text_resolution_methods": [
                item.get("method") for item in preview._plan["text_resolution_plan"]
            ],
            "comments_relocated": comments_relocated,
            "tags_relocated": tags_relocated,
            "tags_deduplicated": tags_deduplicated,
            "document_parts_relocated": document_parts_relocated,
            "source_links_released": source_links_released,
        },
        base_revision_number=base_page_revision,
    )
    session.flush()
    return RebaseResult(
        selection_changed=bool(changed),
        editable_page_id=editable_page.id,
        old_objects_retired=len(old_rows),
        new_objects_created=len(new_objects),
        mentions_relocated=mentions_relocated,
        mentions_rejected=mentions_rejected,
        comments_relocated=comments_relocated,
        tags_relocated=tags_relocated,
        tags_deduplicated=tags_deduplicated,
        document_parts_relocated=document_parts_relocated,
        structural_actions_absorbed=preview.structural_action_count,
        projection_resolutions_applied=preview._plan[
            "manual_projection_resolution_count"
        ],
        metadata_resolutions_applied=preview._plan["manual_metadata_resolution_count"],
        attribute_resolutions_applied=preview._plan[
            "manual_attribute_resolution_count"
        ],
    )
