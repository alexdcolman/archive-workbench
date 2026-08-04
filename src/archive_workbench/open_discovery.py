from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
import re
import unicodedata
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.analysis_audit import (
    record_automatic_analysis_authorization,
    require_automatic_analysis_authorization,
)
from archive_workbench.analysis_quality import (
    DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES,
    quality_scope_snapshot,
    validate_automatic_quality_scope,
)
from archive_workbench.db.models import (
    AuthorityAlias,
    AuthorityRecord,
    DigitalObject,
    DiscoveryCandidate,
    DiscoveryDecision,
    DiscoveryProfile,
    DiscoveryRun,
    EditableObject,
    EditablePage,
    EntityMention,
    Project,
    SourceRegistration,
    utc_now,
)
from archive_workbench.exchange import current_editable_state_sha256
from archive_workbench.identity import new_id

DISCOVERY_FAMILIES = (
    "actor",
    "space",
    "time",
    "event",
    "action_process",
    "work",
    "other",
)
DISCOVERY_PROVIDER_KEY = "local_deterministic"
DISCOVERY_PROVIDER_VERSION = "local_rules_v1"
DISCOVERY_METHOD = "conservative_regex_rules"
OBJECT_REVIEW_STATUSES = ("unreviewed", "needs_review", "reviewed", "approved")

_FAMILY_LABELS = {
    "actor": "Actor",
    "space": "Espacio",
    "time": "Tiempo",
    "event": "Acontecimiento",
    "action_process": "Acción o proceso",
    "work": "Obra",
    "other": "Otra clase",
}

_MONTHS = (
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|"
    "octubre|noviembre|diciembre"
)
_WORD = r"A-ZÁÉÍÓÚÜÑa-záéíóúüñ0-9"
_CAPITALIZED = rf"[A-ZÁÉÍÓÚÜÑ][{_WORD}'’-]*"
_CAPITALIZED_PHRASE = rf"{_CAPITALIZED}(?:\s+(?:de|del|la|las|los|y|e|{_CAPITALIZED})){{0,6}}"

_TIME_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "calendar_date",
        re.compile(r"\b(?:[0-3]?\d)[/-](?:[01]?\d)[/-](?:18|19|20)\d{2}\b", re.I),
        0.99,
        "Fecha numérica explícita.",
    ),
    (
        "calendar_date",
        re.compile(rf"\b(?:[0-3]?\d)\s+de\s+(?:{_MONTHS})(?:\s+de\s+(?:18|19|20)\d{{2}})?\b", re.I),
        0.99,
        "Fecha expresada con día y mes.",
    ),
    (
        "year",
        re.compile(r"\b(?:18|19|20)\d{2}\b"),
        0.95,
        "Año de cuatro cifras.",
    ),
    (
        "period",
        re.compile(
            r"\b(?:años?|década de los)\s+"
            r"(?:sesenta|setenta|ochenta|noventa|dos mil)\b",
            re.I,
        ),
        0.93,
        "Período histórico expresado léxicamente.",
    ),
    (
        "interval",
        re.compile(r"\bentre\s+(?:18|19|20)\d{2}\s+y\s+(?:18|19|20)\d{2}\b", re.I),
        0.97,
        "Intervalo temporal explícito.",
    ),
)

_ACTOR_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "person",
        re.compile(
            rf"\b(?:Sr\.?|Sra\.?|Dr\.?|Dra\.?|doctor|doctora|presidente|presidenta|"
            rf"ministro|ministra|general|coronel|profesor|profesora)\s+"
            rf"{_CAPITALIZED}(?:\s+{_CAPITALIZED}){{1,3}}\b"
        ),
        0.91,
        "Nombre propio introducido por un tratamiento o cargo explícito.",
    ),
    (
        "organization",
        re.compile(
            rf"\b(?:Ministerio|Secretaría|Universidad|Partido|Sindicato|Comisión|Junta|"
            rf"Asociación|Fundación|Instituto|Dirección|Departamento)\s+(?:de|del|la|las|los)?\s*"
            rf"{_CAPITALIZED}(?:\s+(?:de|del|la|las|los|y|e|{_CAPITALIZED})){{0,5}}\b"
        ),
        0.94,
        "Denominación institucional introducida por una clase organizacional explícita.",
    ),
    (
        "collective",
        re.compile(
            r"\b(?:los|las)\s+(?:trabajadores|estudiantes|familiares|vecinos|militantes|"
            r"detenidos|exiliados|docentes|investigadores)\b",
            re.I,
        ),
        0.82,
        "Colectivo humano expresado mediante una referencia nominal explícita.",
    ),
)

_SPACE_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "place",
        re.compile(
            rf"\b(?:ciudad|provincia|localidad|barrio|partido|departamento|municipio)\s+de\s+"
            rf"{_CAPITALIZED_PHRASE}\b"
        ),
        0.94,
        "Topónimo introducido por una clase espacial explícita.",
    ),
    (
        "building",
        re.compile(
            rf"\b(?:sede|edificio|cárcel|comisaría|hospital|escuela|universidad)"
            rf"\s+(?:de|del|la)?\s*"
            rf"{_CAPITALIZED_PHRASE}\b"
        ),
        0.88,
        "Espacio institucional o edificio introducido por un patrón explícito.",
    ),
)

_EVENT_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "event",
        re.compile(
            rf"\b(?i:golpe de Estado|huelga|manifestación|reunión|operativo|elección|juicio|"
            rf"detención|allanamiento|acto|congreso|asamblea)(?:\s+{_CAPITALIZED}){{0,3}}\b"
        ),
        0.86,
        "Construcción nominal que designa un acontecimiento explícito.",
    ),
)

_ACTION_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "process",
        re.compile(
            r"\b(?:investigación|persecución|organización|movilización|censura|represión|"
            r"vigilancia|clasificación|archivo|depuración|intervención|exilio|resistencia)"
            r"(?:\s+(?:política|social|documental|administrativa|estatal|clandestina))?\b",
            re.I,
        ),
        0.82,
        "Sustantivo de acción o proceso incluido en el vocabulario conservador del proveedor.",
    ),
)

_WORK_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    (
        "quoted_work",
        re.compile(r"[“\"]([^“”\"\n]{3,160})[”\"]"),
        0.9,
        "Secuencia entrecomillada tratada como posible título de obra.",
    ),
)


@dataclass(slots=True)
class DiscoveryProfileValues:
    name: str
    description: str | None = None
    families: tuple[str, ...] = DISCOVERY_FAMILIES[:-1]
    include_object_types: tuple[str, ...] = ()
    include_object_review_statuses: tuple[str, ...] = ()
    include_page_review_statuses: tuple[str, ...] = DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES
    minimum_confidence: float = 0.75
    provider_key: str = DISCOVERY_PROVIDER_KEY
    provider_version: str = DISCOVERY_PROVIDER_VERSION


@dataclass(frozen=True, slots=True)
class DiscoveryRunSummary:
    run_id: str
    profile_id: str
    profile_name: str
    object_count: int
    candidate_count: int
    family_counts: dict[str, int]
    corpus_state_sha256: str
    parameters_sha256: str


@dataclass(frozen=True, slots=True)
class DiscoveryRunRow:
    run_id: str
    profile_id: str
    profile_name: str
    status: str
    provider_key: str
    provider_version: str
    object_count: int
    candidate_count: int
    family_counts: dict[str, int]
    page_review_statuses: tuple[str, ...]
    corpus_state_sha256: str
    parameters_sha256: str
    created_by: str
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class DiscoveryCandidateRow:
    candidate_id: str
    run_id: str
    profile_id: str
    exact_text: str
    semantic_family: str
    family_label: str
    suggested_subtype: str
    confidence: float | None
    explanation: str
    source_key: str | None
    original_filename: str
    page_number: int
    editable_object_id: str
    editable_page_id: str
    object_revision_number: int
    page_revision_number: int
    start_offset: int
    end_offset: int
    context_before: str
    context_after: str
    provider_key: str
    provider_version: str
    method: str
    parameters_sha256: str
    status: str
    decision_count: int
    latest_decision_type: str | None
    effective_text: str
    effective_family: str
    effective_subtype: str
    is_stale: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class _Detection:
    start: int
    end: int
    exact_text: str
    family: str
    subtype: str
    confidence: float
    explanation: str


def family_label(value: str) -> str:
    return _FAMILY_LABELS.get(value, value)


def _clean_text(value: str, *, field: str, maximum: int) -> str:
    clean = " ".join((value or "").split())
    if not clean:
        raise ValueError(f"{field} no puede quedar vacío")
    if len(clean) > maximum:
        raise ValueError(f"{field} no puede superar {maximum} caracteres")
    return clean


def _normalize_surface(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_marks.casefold().split()).strip(" .,:;()[]{}\"'“”")


def _validate_profile(
    values: DiscoveryProfileValues,
    *,
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
) -> DiscoveryProfileValues:
    families = tuple(value for value in DISCOVERY_FAMILIES if value in set(values.families))
    if not families:
        raise ValueError("El perfil debe incluir al menos una familia semántica")
    invalid_families = set(values.families) - set(DISCOVERY_FAMILIES)
    if invalid_families:
        raise ValueError(
            "Familias semánticas inválidas: " + ", ".join(sorted(invalid_families))
        )
    invalid_object_statuses = set(values.include_object_review_statuses) - set(
        OBJECT_REVIEW_STATUSES
    )
    if invalid_object_statuses:
        raise ValueError(
            "Estados de revisión de objeto inválidos: "
            + ", ".join(sorted(invalid_object_statuses))
        )
    page_scope = validate_automatic_quality_scope(
        values.include_page_review_statuses,
        broader_scope_confirmed=broader_quality_scope_confirmed,
        confirmation_reason=quality_scope_reason,
    )
    confidence = float(values.minimum_confidence)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("La confianza mínima debe estar entre 0 y 1")
    if values.provider_key != DISCOVERY_PROVIDER_KEY:
        raise ValueError("La primera fase solo admite el proveedor local determinista")
    if values.provider_version != DISCOVERY_PROVIDER_VERSION:
        raise ValueError("Versión del proveedor local no admitida")
    return DiscoveryProfileValues(
        name=_clean_text(values.name, field="El nombre del perfil", maximum=200),
        description=(
            " ".join(values.description.split())
            if values.description and values.description.strip()
            else None
        ),
        families=families,
        include_object_types=tuple(sorted(set(values.include_object_types))),
        include_object_review_statuses=tuple(
            value
            for value in OBJECT_REVIEW_STATUSES
            if value in set(values.include_object_review_statuses)
        ),
        include_page_review_statuses=page_scope.page_review_statuses,
        minimum_confidence=confidence,
        provider_key=values.provider_key,
        provider_version=values.provider_version,
    )


def profile_values(profile: DiscoveryProfile) -> DiscoveryProfileValues:
    return DiscoveryProfileValues(
        name=profile.name,
        description=profile.description,
        families=tuple(profile.families_json or ()),
        include_object_types=tuple(profile.include_object_types_json or ()),
        include_object_review_statuses=tuple(
            profile.include_object_review_statuses_json or ()
        ),
        include_page_review_statuses=tuple(profile.include_page_review_statuses_json or ()),
        minimum_confidence=float(profile.minimum_confidence),
        provider_key=profile.provider_key,
        provider_version=profile.provider_version,
    )


def discovery_profile_authorization_parameters(
    profile: DiscoveryProfile,
) -> dict[str, Any]:
    payload = asdict(profile_values(profile))
    for key in (
        "families",
        "include_object_types",
        "include_object_review_statuses",
        "include_page_review_statuses",
    ):
        payload[key] = list(payload[key])
    payload["method"] = DISCOVERY_METHOD
    payload["analysis_quality"] = quality_scope_snapshot(
        analysis_kind="open_discovery",
        page_review_statuses=profile.include_page_review_statuses_json or (),
    )
    return payload


def profile_snapshot(profile: DiscoveryProfile) -> dict[str, Any]:
    payload = discovery_profile_authorization_parameters(profile)
    payload.update({"id": profile.id, "revision": profile.revision})
    return payload


def save_discovery_profile(
    session: Session,
    *,
    project_id: str,
    values: DiscoveryProfileValues,
    changed_by: str,
    profile_id: str | None = None,
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
    quality_scope_source: str = "api",
) -> DiscoveryProfile:
    actor = _clean_text(changed_by, field="La persona responsable", maximum=200)
    clean = _validate_profile(
        values,
        broader_quality_scope_confirmed=broader_quality_scope_confirmed,
        quality_scope_reason=quality_scope_reason,
    )
    profile = session.get(DiscoveryProfile, profile_id) if profile_id else None
    if profile is None:
        profile = session.scalar(
            select(DiscoveryProfile).where(
                DiscoveryProfile.project_id == project_id,
                DiscoveryProfile.name == clean.name,
            )
        )
    now = utc_now()
    if profile is None:
        profile = DiscoveryProfile(
            id=new_id(),
            project_id=project_id,
            name=clean.name,
            description=clean.description,
            provider_key=clean.provider_key,
            provider_version=clean.provider_version,
            families_json=list(clean.families),
            include_object_types_json=list(clean.include_object_types),
            include_object_review_statuses_json=list(
                clean.include_object_review_statuses
            ),
            include_page_review_statuses_json=list(clean.include_page_review_statuses),
            minimum_confidence=clean.minimum_confidence,
            lifecycle_status="active",
            created_by=actor,
            created_at=now,
            updated_by=actor,
            updated_at=now,
            revision=1,
        )
        session.add(profile)
    else:
        if profile.project_id != project_id:
            raise ValueError("El perfil pertenece a otro proyecto")
        if profile.lifecycle_status != "active":
            raise ValueError("El perfil está archivado")
        duplicate = session.scalar(
            select(DiscoveryProfile).where(
                DiscoveryProfile.project_id == project_id,
                DiscoveryProfile.name == clean.name,
                DiscoveryProfile.id != profile.id,
            )
        )
        if duplicate is not None:
            raise ValueError(f"Ya existe otro perfil llamado {clean.name}")
        profile.name = clean.name
        profile.description = clean.description
        profile.provider_key = clean.provider_key
        profile.provider_version = clean.provider_version
        profile.families_json = list(clean.families)
        profile.include_object_types_json = list(clean.include_object_types)
        profile.include_object_review_statuses_json = list(
            clean.include_object_review_statuses
        )
        profile.include_page_review_statuses_json = list(
            clean.include_page_review_statuses
        )
        profile.minimum_confidence = clean.minimum_confidence
        profile.updated_by = actor
        profile.updated_at = now
        profile.revision += 1
    session.flush()
    record_automatic_analysis_authorization(
        session,
        project_id=project_id,
        analysis_kind="open_discovery",
        page_review_statuses=clean.include_page_review_statuses,
        broader_scope_confirmed=broader_quality_scope_confirmed,
        confirmed_by=actor,
        confirmation_reason=quality_scope_reason,
        source=quality_scope_source,
        target_type="discovery_profile",
        target_id=profile.id,
        parameters=discovery_profile_authorization_parameters(profile),
    )
    return profile


def discovery_profile_rows(
    session: Session, *, project_id: str, include_archived: bool = False
) -> list[DiscoveryProfile]:
    query = select(DiscoveryProfile).where(DiscoveryProfile.project_id == project_id)
    if not include_archived:
        query = query.where(DiscoveryProfile.lifecycle_status == "active")
    return session.scalars(query.order_by(DiscoveryProfile.name, DiscoveryProfile.id)).all()


def resolve_discovery_profile(
    session: Session, *, project_id: str, profile_ref: str
) -> DiscoveryProfile:
    profile = session.scalar(
        select(DiscoveryProfile).where(
            DiscoveryProfile.project_id == project_id,
            (DiscoveryProfile.id == profile_ref) | (DiscoveryProfile.name == profile_ref),
        )
    )
    if profile is None:
        raise ValueError(f"Perfil de descubrimiento inexistente: {profile_ref}")
    if profile.lifecycle_status != "active":
        raise ValueError(f"El perfil de descubrimiento está archivado: {profile.name}")
    return profile


def _require_profile_authorization(
    session: Session, *, project_id: str, profile: DiscoveryProfile
) -> Any:
    return require_automatic_analysis_authorization(
        session,
        project_id=project_id,
        analysis_kind="open_discovery",
        page_review_statuses=tuple(profile.include_page_review_statuses_json or ()),
        target_type="discovery_profile",
        target_id=profile.id,
        parameters=discovery_profile_authorization_parameters(profile),
        remediation=(
            "Guardá nuevamente el perfil de descubrimiento para registrar su alcance "
            "y sus parámetros funcionales."
        ),
    )


def _candidate_from_match(
    text: str,
    *,
    match: re.Match[str],
    family: str,
    subtype: str,
    confidence: float,
    explanation: str,
    capture_group: int | None = None,
) -> _Detection | None:
    start, end = match.span(capture_group or 0)
    exact = text[start:end]
    if not exact.strip():
        return None
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    exact = text[start:end]
    return _Detection(
        start=start,
        end=end,
        exact_text=exact,
        family=family,
        subtype=subtype,
        confidence=confidence,
        explanation=explanation,
    )


def _pattern_detections(
    text: str,
    *,
    family: str,
    patterns: Sequence[tuple[str, re.Pattern[str], float, str]],
    quoted_capture: bool = False,
) -> Iterable[_Detection]:
    for subtype, pattern, confidence, explanation in patterns:
        for match in pattern.finditer(text):
            detection = _candidate_from_match(
                text,
                match=match,
                family=family,
                subtype=subtype,
                confidence=confidence,
                explanation=explanation,
                capture_group=1 if quoted_capture else None,
            )
            if detection is not None:
                yield detection


def detect_local_candidates(text: str, *, families: Iterable[str]) -> list[_Detection]:
    selected = set(families)
    detections: list[_Detection] = []
    if "actor" in selected:
        detections.extend(_pattern_detections(text, family="actor", patterns=_ACTOR_PATTERNS))
    if "space" in selected:
        detections.extend(_pattern_detections(text, family="space", patterns=_SPACE_PATTERNS))
    if "time" in selected:
        detections.extend(_pattern_detections(text, family="time", patterns=_TIME_PATTERNS))
    if "event" in selected:
        detections.extend(_pattern_detections(text, family="event", patterns=_EVENT_PATTERNS))
    if "action_process" in selected:
        detections.extend(
            _pattern_detections(text, family="action_process", patterns=_ACTION_PATTERNS)
        )
    if "work" in selected:
        detections.extend(
            _pattern_detections(
                text,
                family="work",
                patterns=_WORK_PATTERNS,
                quoted_capture=True,
            )
        )
    deduplicated: dict[tuple[int, int, str, str], _Detection] = {}
    for item in detections:
        key = (item.start, item.end, item.family, item.subtype)
        previous = deduplicated.get(key)
        if previous is None or item.confidence > previous.confidence:
            deduplicated[key] = item
    ordered = sorted(
        deduplicated.values(),
        key=lambda item: (-item.confidence, item.start, -(item.end - item.start), item.family),
    )
    kept: list[_Detection] = []
    for item in ordered:
        if any(
            existing.family == item.family
            and existing.start <= item.start
            and existing.end >= item.end
            for existing in kept
        ):
            continue
        kept.append(item)
    return sorted(
        kept,
        key=lambda item: (item.start, item.end, item.family, item.subtype),
    )


def _known_surfaces(session: Session, project_id: str) -> set[str]:
    values: set[str] = set()
    authorities = session.scalars(
        select(AuthorityRecord).where(
            AuthorityRecord.project_id == project_id,
            AuthorityRecord.lifecycle_status == "active",
        )
    ).all()
    authority_ids = [row.id for row in authorities]
    for row in authorities:
        values.add(_normalize_surface(row.preferred_name))
    if authority_ids:
        aliases = session.scalars(
            select(AuthorityAlias).where(AuthorityAlias.authority_id.in_(authority_ids))
        ).all()
        for row in aliases:
            values.add(_normalize_surface(row.alias))
    return {value for value in values if value}


def _existing_mention_keys(session: Session) -> set[tuple[str, int, int]]:
    rows = session.scalars(
        select(EntityMention).where(
            EntityMention.status != "rejected",
            EntityMention.start_offset.is_not(None),
            EntityMention.end_offset.is_not(None),
        )
    ).all()
    return {
        (row.editable_object_id, int(row.start_offset), int(row.end_offset))
        for row in rows
    }


def _source_keys(session: Session, digital_ids: Iterable[str]) -> dict[str, str]:
    ids = tuple(dict.fromkeys(digital_ids))
    if not ids:
        return {}
    rows = session.scalars(
        select(SourceRegistration)
        .where(SourceRegistration.digital_object_id.in_(ids))
        .order_by(SourceRegistration.source_key, SourceRegistration.id)
    ).all()
    result: dict[str, str] = {}
    for row in rows:
        if row.digital_object_id and row.digital_object_id not in result:
            result[row.digital_object_id] = row.source_key
    return result


def _eligible_objects(
    session: Session, *, project_id: str, profile: DiscoveryProfile
) -> list[tuple[EditableObject, EditablePage, DigitalObject]]:
    query = (
        select(EditableObject, EditablePage, DigitalObject)
        .join(EditablePage, EditablePage.id == EditableObject.editable_page_id)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .where(
            DigitalObject.project_id == project_id,
            EditableObject.lifecycle_status == "active",
            EditablePage.status == "active",
        )
    )
    page_statuses = tuple(profile.include_page_review_statuses_json or ())
    if page_statuses:
        query = query.where(EditablePage.review_status.in_(page_statuses))
    object_types = tuple(profile.include_object_types_json or ())
    if object_types:
        query = query.where(EditableObject.current_object_type.in_(object_types))
    object_statuses = tuple(profile.include_object_review_statuses_json or ())
    if object_statuses:
        query = query.where(EditableObject.review_status.in_(object_statuses))
    return list(
        session.execute(
            query.order_by(
                DigitalObject.original_filename,
                EditableObject.page_number,
                EditableObject.current_order_index,
                EditableObject.id,
            )
        ).all()
    )


def run_open_discovery(
    session: Session,
    *,
    project_id: str,
    profile: DiscoveryProfile,
    created_by: str,
) -> DiscoveryRunSummary:
    actor = _clean_text(created_by, field="La persona responsable", maximum=200)
    if profile.project_id != project_id:
        raise ValueError("El perfil pertenece a otro proyecto")
    authorization = _require_profile_authorization(
        session, project_id=project_id, profile=profile
    )
    parameters = discovery_profile_authorization_parameters(profile)
    parameters_sha256 = sha256(
        json.dumps(
            parameters,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    started = utc_now()
    run = DiscoveryRun(
        id=new_id(),
        project_id=project_id,
        profile_id=profile.id,
        authorization_id=authorization.id,
        profile_name=profile.name,
        profile_snapshot_json=profile_snapshot(profile),
        provider_key=profile.provider_key,
        provider_version=profile.provider_version,
        method=DISCOVERY_METHOD,
        parameters_sha256=parameters_sha256,
        corpus_state_sha256=current_editable_state_sha256(session, project_id),
        page_review_statuses_json=list(profile.include_page_review_statuses_json or ()),
        status="running",
        object_count=0,
        candidate_count=0,
        family_counts_json={},
        created_by=actor,
        started_at=started,
        finished_at=None,
        error_message=None,
    )
    session.add(run)
    session.flush()

    rows = _eligible_objects(session, project_id=project_id, profile=profile)
    known_surfaces = _known_surfaces(session, project_id)
    existing_mentions = _existing_mention_keys(session)
    source_map = _source_keys(session, (row[2].id for row in rows))
    family_counts: dict[str, int] = {}
    candidate_count = 0
    try:
        for editable, page, digital in rows:
            text = editable.current_text or ""
            if not text.strip():
                continue
            for detection in detect_local_candidates(
                text, families=profile.families_json or ()
            ):
                if detection.confidence < float(profile.minimum_confidence):
                    continue
                if detection.family in {"actor", "space", "event", "work"}:
                    normalized = _normalize_surface(detection.exact_text)
                    if normalized in known_surfaces:
                        continue
                mention_key = (editable.id, detection.start, detection.end)
                if mention_key in existing_mentions:
                    continue
                context_before = text[max(0, detection.start - 90) : detection.start]
                context_after = text[detection.end : min(len(text), detection.end + 90)]
                candidate = DiscoveryCandidate(
                    id=new_id(),
                    project_id=project_id,
                    run_id=run.id,
                    profile_id=profile.id,
                    editable_object_id=editable.id,
                    editable_page_id=page.id,
                    digital_object_id=digital.id,
                    document_part_id=editable.document_part_id,
                    source_key=source_map.get(digital.id),
                    original_filename=digital.original_filename,
                    page_number=editable.page_number,
                    object_revision_number=editable.revision_number,
                    page_revision_number=page.revision_number,
                    start_offset=detection.start,
                    end_offset=detection.end,
                    exact_text=detection.exact_text,
                    context_before=context_before,
                    context_after=context_after,
                    semantic_family=detection.family,
                    suggested_subtype=detection.subtype,
                    confidence=detection.confidence,
                    method=DISCOVERY_METHOD,
                    provider_key=profile.provider_key,
                    provider_version=profile.provider_version,
                    model_name=None,
                    model_version=None,
                    explanation=detection.explanation,
                    parameters_sha256=parameters_sha256,
                    status="pending",
                    created_at=utc_now(),
                )
                session.add(candidate)
                candidate_count += 1
                family_counts[detection.family] = family_counts.get(detection.family, 0) + 1
        run.status = "completed"
        run.object_count = len(rows)
        run.candidate_count = candidate_count
        run.family_counts_json = dict(sorted(family_counts.items()))
        run.finished_at = utc_now()
        session.flush()
    except Exception as exc:
        run.status = "failed"
        run.object_count = len(rows)
        run.candidate_count = candidate_count
        run.family_counts_json = dict(sorted(family_counts.items()))
        run.finished_at = utc_now()
        run.error_message = str(exc)
        session.flush()
        raise
    return DiscoveryRunSummary(
        run_id=run.id,
        profile_id=profile.id,
        profile_name=profile.name,
        object_count=run.object_count,
        candidate_count=run.candidate_count,
        family_counts=dict(run.family_counts_json or {}),
        corpus_state_sha256=run.corpus_state_sha256,
        parameters_sha256=run.parameters_sha256,
    )


def discovery_run_rows(
    session: Session, *, project_id: str, limit: int = 50
) -> list[DiscoveryRunRow]:
    rows = session.scalars(
        select(DiscoveryRun)
        .where(DiscoveryRun.project_id == project_id)
        .order_by(DiscoveryRun.started_at.desc(), DiscoveryRun.id.desc())
        .limit(max(1, int(limit)))
    ).all()
    return [
        DiscoveryRunRow(
            run_id=row.id,
            profile_id=row.profile_id,
            profile_name=row.profile_name,
            status=row.status,
            provider_key=row.provider_key,
            provider_version=row.provider_version,
            object_count=row.object_count,
            candidate_count=row.candidate_count,
            family_counts=dict(row.family_counts_json or {}),
            page_review_statuses=tuple(row.page_review_statuses_json or ()),
            corpus_state_sha256=row.corpus_state_sha256,
            parameters_sha256=row.parameters_sha256,
            created_by=row.created_by,
            started_at=row.started_at,
            finished_at=row.finished_at,
            error_message=row.error_message,
        )
        for row in rows
    ]


def discovery_candidate_rows(
    session: Session,
    *,
    project_id: str,
    run_id: str | None = None,
    families: Iterable[str] = (),
    limit: int = 500,
) -> list[DiscoveryCandidateRow]:
    query = select(DiscoveryCandidate).where(DiscoveryCandidate.project_id == project_id)
    if run_id:
        query = query.where(DiscoveryCandidate.run_id == run_id)
    selected_families = tuple(dict.fromkeys(families))
    if selected_families:
        invalid = set(selected_families) - set(DISCOVERY_FAMILIES)
        if invalid:
            raise ValueError("Familias inválidas: " + ", ".join(sorted(invalid)))
        query = query.where(DiscoveryCandidate.semantic_family.in_(selected_families))
    rows = session.scalars(
        query.order_by(
            DiscoveryCandidate.created_at.desc(),
            DiscoveryCandidate.original_filename,
            DiscoveryCandidate.page_number,
            DiscoveryCandidate.start_offset,
            DiscoveryCandidate.id,
        ).limit(max(1, int(limit)))
    ).all()
    object_ids = {row.editable_object_id for row in rows}
    objects = {
        row.id: row
        for row in session.scalars(
            select(EditableObject).where(EditableObject.id.in_(object_ids))
        ).all()
    } if object_ids else {}
    candidate_ids = [row.id for row in rows]
    decisions = session.scalars(
        select(DiscoveryDecision)
        .where(DiscoveryDecision.candidate_id.in_(candidate_ids))
        .order_by(
            DiscoveryDecision.candidate_id,
            DiscoveryDecision.decision_number,
        )
    ).all() if candidate_ids else []
    decisions_by: dict[str, list[DiscoveryDecision]] = {}
    for decision in decisions:
        decisions_by.setdefault(decision.candidate_id, []).append(decision)
    result: list[DiscoveryCandidateRow] = []
    for row in rows:
        current = objects.get(row.editable_object_id)
        stale = current is None or current.revision_number != row.object_revision_number
        if current is not None and not stale:
            stale = current.current_text[row.start_offset : row.end_offset] != row.exact_text
        candidate_decisions = decisions_by.get(row.id, [])
        latest_decision = candidate_decisions[-1] if candidate_decisions else None
        result.append(
            DiscoveryCandidateRow(
                candidate_id=row.id,
                run_id=row.run_id,
                profile_id=row.profile_id,
                exact_text=row.exact_text,
                semantic_family=row.semantic_family,
                family_label=family_label(row.semantic_family),
                suggested_subtype=row.suggested_subtype,
                confidence=row.confidence,
                explanation=row.explanation,
                source_key=row.source_key,
                original_filename=row.original_filename,
                page_number=row.page_number,
                editable_object_id=row.editable_object_id,
                editable_page_id=row.editable_page_id,
                object_revision_number=row.object_revision_number,
                page_revision_number=row.page_revision_number,
                start_offset=row.start_offset,
                end_offset=row.end_offset,
                context_before=row.context_before,
                context_after=row.context_after,
                provider_key=row.provider_key,
                provider_version=row.provider_version,
                method=row.method,
                parameters_sha256=row.parameters_sha256,
                status=row.status,
                decision_count=len(candidate_decisions),
                latest_decision_type=(
                    latest_decision.decision_type if latest_decision else None
                ),
                effective_text=(
                    latest_decision.reviewed_text if latest_decision else row.exact_text
                ),
                effective_family=(
                    latest_decision.semantic_family
                    if latest_decision
                    else row.semantic_family
                ),
                effective_subtype=(
                    latest_decision.reviewed_subtype
                    if latest_decision
                    else row.suggested_subtype
                ),
                is_stale=stale,
                created_at=row.created_at,
            )
        )
    return result


def discovery_audit_payload(
    session: Session, *, project_id: str, run_id: str
) -> dict[str, Any]:
    run = session.get(DiscoveryRun, run_id)
    if run is None or run.project_id != project_id:
        raise ValueError("La corrida de descubrimiento no existe en este proyecto")
    candidates = discovery_candidate_rows(
        session, project_id=project_id, run_id=run_id, limit=100_000
    )
    return {
        "run": {
            "id": run.id,
            "profile_id": run.profile_id,
            "profile_name": run.profile_name,
            "profile_snapshot": run.profile_snapshot_json,
            "authorization_id": run.authorization_id,
            "provider_key": run.provider_key,
            "provider_version": run.provider_version,
            "method": run.method,
            "parameters_sha256": run.parameters_sha256,
            "corpus_state_sha256": run.corpus_state_sha256,
            "page_review_statuses": list(run.page_review_statuses_json or ()),
            "status": run.status,
            "object_count": run.object_count,
            "candidate_count": run.candidate_count,
            "family_counts": dict(run.family_counts_json or {}),
            "created_by": run.created_by,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "error_message": run.error_message,
        },
        "candidates": [
            {
                "id": row.candidate_id,
                "exact_text": row.exact_text,
                "family": row.semantic_family,
                "subtype": row.suggested_subtype,
                "confidence": row.confidence,
                "source_key": row.source_key,
                "original_filename": row.original_filename,
                "page_number": row.page_number,
                "editable_object_id": row.editable_object_id,
                "object_revision_number": row.object_revision_number,
                "start_offset": row.start_offset,
                "end_offset": row.end_offset,
                "provider_key": row.provider_key,
                "provider_version": row.provider_version,
                "method": row.method,
                "explanation": row.explanation,
                "parameters_sha256": row.parameters_sha256,
                "status": row.status,
                "decision_count": row.decision_count,
                "latest_decision_type": row.latest_decision_type,
                "effective_text": row.effective_text,
                "effective_family": row.effective_family,
                "effective_subtype": row.effective_subtype,
                "is_stale": row.is_stale,
            }
            for row in candidates
        ],
    }


def single_project_id(session: Session) -> str:
    project_ids = session.scalars(select(Project.id).order_by(Project.id)).all()
    if len(project_ids) != 1:
        raise ValueError("El proyecto debe contener exactamente una fila en projects")
    return project_ids[0]
