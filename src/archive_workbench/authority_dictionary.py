from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, BinaryIO, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.authorities import (
    ALIAS_TYPES,
    AUTHORITY_REVIEW_STATUSES,
    AUTHORITY_TYPES,
    add_authority_alias,
    create_authority,
    normalize_authority_text,
)
from archive_workbench.db.models import (
    ArchivalUnit,
    AuthorityAlias,
    AuthorityRecord,
    DigitalObject,
    DocumentPart,
    EntityRelation,
)
from archive_workbench.relations import create_entity_relation
from archive_workbench.temporal import parse_temporal_expression

DICTIONARY_SCHEMA_VERSION = "1.0"
DICTIONARY_SCHEMA_ID = "https://archive-workbench.local/schema/authority-dictionary-1.0.json"

AuthorityType = Literal["person", "organization", "place", "event", "work", "other"]
AuthorityReviewStatus = Literal["unreviewed", "reviewed", "approved"]
AliasType = Literal["variant", "abbreviation", "acronym", "former_name", "title", "other"]
AuthorityResolutionAction = Literal["auto", "use_existing", "create_new", "skip"]
RelationResolutionAction = Literal["auto", "create_parallel", "skip"]
RelationTargetKind = Literal["authority", "archival_unit", "document_part"]
CharacteristicValue = str | int | float | bool | list[str]

_LOCAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DictionarySource(StrictModel):
    title: str = Field(min_length=1)
    organization: str | None = None
    url: str | None = None
    reference: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    note: str | None = None


class AuthorityResolution(StrictModel):
    action: AuthorityResolutionAction = "auto"
    authority_id: str | None = None

    @model_validator(mode="after")
    def validate_authority_id(self) -> AuthorityResolution:
        if self.action == "use_existing" and not self.authority_id:
            raise ValueError("use_existing requiere authority_id")
        if self.action != "use_existing" and self.authority_id:
            raise ValueError("authority_id solo se usa con use_existing")
        return self


class DictionaryAlias(StrictModel):
    value: str = Field(min_length=1)
    alias_type: AliasType = "variant"
    note: str | None = None
    allow_ambiguous: bool = False


class DictionaryAuthority(StrictModel):
    local_id: str = Field(min_length=1)
    entity_type: AuthorityType
    preferred_name: str = Field(min_length=1)
    description: str | None = None
    characteristics: dict[str, CharacteristicValue] = Field(default_factory=dict)
    temporal_expression: str | None = None
    temporal_note: str | None = None
    review_status: AuthorityReviewStatus = "unreviewed"
    aliases: list[DictionaryAlias] = Field(default_factory=list)
    source_note: str | None = None
    resolution: AuthorityResolution = Field(default_factory=AuthorityResolution)

    @model_validator(mode="after")
    def validate_local_id(self) -> DictionaryAuthority:
        if not _LOCAL_ID_PATTERN.fullmatch(self.local_id):
            raise ValueError(
                "local_id debe comenzar con letra o número y usar solo letras, números, . _ : -"
            )
        return self


class RelationEvidence(StrictModel):
    note: str | None = None
    source_url: str | None = None
    source_reference: str | None = None

    @model_validator(mode="after")
    def require_evidence(self) -> RelationEvidence:
        if not any((self.note, self.source_url, self.source_reference)):
            raise ValueError(
                "Cada relación necesita evidencia: note, source_url o source_reference"
            )
        return self

    def render(self) -> str:
        parts: list[str] = []
        if self.note:
            parts.append(self.note)
        if self.source_reference:
            parts.append(f"Referencia: {self.source_reference}")
        if self.source_url:
            parts.append(f"Fuente: {self.source_url}")
        return " · ".join(parts)


class RelationResolution(StrictModel):
    action: RelationResolutionAction = "auto"


class DictionaryRelation(StrictModel):
    local_id: str = Field(min_length=1)
    source_local_id: str = Field(min_length=1)
    relation_label: str = Field(min_length=1)
    target_kind: RelationTargetKind = "authority"
    target_local_id: str | None = None
    target_id: str | None = None
    evidence: RelationEvidence
    temporal_expression: str | None = None
    temporal_note: str | None = None
    review_status: AuthorityReviewStatus = "unreviewed"
    resolution: RelationResolution = Field(default_factory=RelationResolution)

    @model_validator(mode="after")
    def validate_target(self) -> DictionaryRelation:
        if not _LOCAL_ID_PATTERN.fullmatch(self.local_id):
            raise ValueError(
                "local_id debe comenzar con letra o número y usar solo letras, números, . _ : -"
            )
        if self.target_kind == "authority":
            if bool(self.target_local_id) == bool(self.target_id):
                raise ValueError(
                    "Una relación a authority requiere exactamente uno de target_local_id o target_id"
                )
        else:
            if not self.target_id or self.target_local_id:
                raise ValueError(
                    f"Una relación a {self.target_kind} requiere target_id y no target_local_id"
                )
        return self


class AuthorityDictionary(StrictModel):
    schema_version: Literal["1.0"] = DICTIONARY_SCHEMA_VERSION
    dictionary_id: str = Field(min_length=1)
    dictionary_name: str = Field(min_length=1)
    target_project_id: str | None = None
    source: DictionarySource
    authorities: list[DictionaryAuthority] = Field(default_factory=list)
    relations: list[DictionaryRelation] = Field(default_factory=list)


@dataclass(slots=True)
class AuthorityDictionaryIssue:
    severity: str
    code: str
    section: str
    item_id: str | None
    field: str | None
    message: str
    candidate_ids: tuple[str, ...] = ()


@dataclass(slots=True)
class AuthorityImportPlan:
    local_id: str
    preferred_name: str
    entity_type: str
    action: str
    existing_authority_id: str | None = None
    candidate_ids: tuple[str, ...] = ()
    aliases_to_add: tuple[DictionaryAlias, ...] = ()
    aliases_unchanged: tuple[str, ...] = ()


@dataclass(slots=True)
class RelationImportPlan:
    local_id: str
    relation_label: str
    action: str
    source_local_id: str
    source_authority_id: str | None
    target_kind: str
    target_local_id: str | None
    target_id: str | None
    duplicate_relation_id: str | None = None


@dataclass(slots=True)
class AuthorityDictionaryReport:
    schema_version: str
    dictionary_id: str
    dictionary_name: str
    dictionary_sha256: str
    target_project_id: str | None
    valid: bool
    authority_plans: list[AuthorityImportPlan]
    relation_plans: list[RelationImportPlan]
    issues: list[AuthorityDictionaryIssue]

    @property
    def error_count(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    @property
    def authority_create_count(self) -> int:
        return sum(plan.action == "create" for plan in self.authority_plans)

    @property
    def authority_reuse_count(self) -> int:
        return sum(plan.action == "reuse" for plan in self.authority_plans)

    @property
    def authority_skip_count(self) -> int:
        return sum(plan.action == "skip" for plan in self.authority_plans)

    @property
    def alias_add_count(self) -> int:
        return sum(len(plan.aliases_to_add) for plan in self.authority_plans)

    @property
    def relation_create_count(self) -> int:
        return sum(plan.action == "create" for plan in self.relation_plans)

    @property
    def relation_skip_count(self) -> int:
        return sum(plan.action in {"skip", "skip_duplicate"} for plan in self.relation_plans)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dictionary_id": self.dictionary_id,
            "dictionary_name": self.dictionary_name,
            "dictionary_sha256": self.dictionary_sha256,
            "target_project_id": self.target_project_id,
            "valid": self.valid,
            "counts": {
                "authorities": len(self.authority_plans),
                "authorities_create": self.authority_create_count,
                "authorities_reuse": self.authority_reuse_count,
                "authorities_skip": self.authority_skip_count,
                "aliases_add": self.alias_add_count,
                "relations": len(self.relation_plans),
                "relations_create": self.relation_create_count,
                "relations_skip": self.relation_skip_count,
                "errors": self.error_count,
                "warnings": self.warning_count,
            },
            "authorities": [
                {
                    "local_id": plan.local_id,
                    "preferred_name": plan.preferred_name,
                    "entity_type": plan.entity_type,
                    "action": plan.action,
                    "existing_authority_id": plan.existing_authority_id,
                    "candidate_ids": list(plan.candidate_ids),
                    "aliases_to_add": [alias.value for alias in plan.aliases_to_add],
                    "aliases_unchanged": list(plan.aliases_unchanged),
                }
                for plan in self.authority_plans
            ],
            "relations": [
                {
                    "local_id": plan.local_id,
                    "relation_label": plan.relation_label,
                    "action": plan.action,
                    "source_local_id": plan.source_local_id,
                    "source_authority_id": plan.source_authority_id,
                    "target_kind": plan.target_kind,
                    "target_local_id": plan.target_local_id,
                    "target_id": plan.target_id,
                    "duplicate_relation_id": plan.duplicate_relation_id,
                }
                for plan in self.relation_plans
            ],
            "issues": [
                {
                    "severity": issue.severity,
                    "code": issue.code,
                    "section": issue.section,
                    "item_id": issue.item_id,
                    "field": issue.field,
                    "message": issue.message,
                    "candidate_ids": list(issue.candidate_ids),
                }
                for issue in self.issues
            ],
        }


@dataclass(slots=True)
class AuthorityDictionaryApplyResult:
    authorities_created: int
    authorities_reused: int
    authorities_skipped: int
    aliases_added: int
    relations_created: int
    relations_skipped: int
    local_to_authority_id: dict[str, str] = field(default_factory=dict)


def _read_source(source: Path | bytes | bytearray | BinaryIO) -> bytes:
    if isinstance(source, Path):
        return source.read_bytes()
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    return source.read()


def load_authority_dictionary(source: Path | bytes | bytearray | BinaryIO) -> AuthorityDictionary:
    raw = _read_source(source)
    try:
        return AuthorityDictionary.model_validate_json(raw)
    except ValidationError as exc:
        details = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            details.append(f"{location}: {error['msg']}")
        raise ValueError("Diccionario inválido: " + "; ".join(details)) from exc
    except ValueError as exc:
        raise ValueError(f"JSON inválido: {exc}") from exc


def authority_dictionary_schema() -> dict[str, Any]:
    schema = AuthorityDictionary.model_json_schema()
    schema["$id"] = DICTIONARY_SCHEMA_ID
    schema["title"] = "Archive Workbench authority dictionary 1.0"
    return schema


def authority_dictionary_schema_bytes() -> bytes:
    return (
        json.dumps(authority_dictionary_schema(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def authority_dictionary_example() -> dict[str, Any]:
    return {
        "schema_version": DICTIONARY_SCHEMA_VERSION,
        "dictionary_id": "ejemplo_autoridades_v1",
        "dictionary_name": "Diccionario de autoridades de ejemplo",
        "target_project_id": "*",
        "source": {
            "title": "Ejemplo distribuible de Archive Workbench",
            "organization": "Equipo de investigación",
            "url": "https://example.org/diccionario",
            "created_by": "equipo_local",
            "note": "Reemplazar estos registros por información verificada.",
        },
        "authorities": [
            {
                "local_id": "org_dippba",
                "entity_type": "organization",
                "preferred_name": (
                    "Dirección de Inteligencia de la Policía de la Provincia de Buenos Aires"
                ),
                "description": "Organismo productor de documentación de inteligencia.",
                "temporal_expression": "1956 - 1998",
                "review_status": "unreviewed",
                "aliases": [
                    {
                        "value": "DIPPBA",
                        "alias_type": "acronym",
                        "note": "Sigla de uso extendido.",
                    }
                ],
            },
            {
                "local_id": "obra_informe",
                "entity_type": "work",
                "preferred_name": "Informe de ejemplo",
                "characteristics": {"tipo_documental": "informe", "idioma": "es"},
                "review_status": "unreviewed",
            },
        ],
        "relations": [
            {
                "local_id": "rel_produjo",
                "source_local_id": "org_dippba",
                "relation_label": "produjo",
                "target_kind": "authority",
                "target_local_id": "obra_informe",
                "evidence": {
                    "note": "Relación incluida únicamente como ejemplo de formato.",
                    "source_url": "https://example.org/diccionario",
                },
                "review_status": "unreviewed",
            }
        ],
    }


def authority_dictionary_example_bytes() -> bytes:
    return (
        json.dumps(authority_dictionary_example(), ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def _canonical_hash(dictionary: AuthorityDictionary) -> str:
    payload = json.dumps(
        dictionary.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _issue(
    issues: list[AuthorityDictionaryIssue],
    severity: str,
    code: str,
    section: str,
    item_id: str | None,
    field_name: str | None,
    message: str,
    candidate_ids: tuple[str, ...] = (),
) -> None:
    issues.append(
        AuthorityDictionaryIssue(
            severity=severity,
            code=code,
            section=section,
            item_id=item_id,
            field=field_name,
            message=message,
            candidate_ids=candidate_ids,
        )
    )


def _normalized_relation_label(value: str) -> str:
    return normalize_authority_text(value)


def _normalized_optional(value: str | None) -> str:
    return normalize_authority_text(value or "")


def _format_characteristics(values: Mapping[str, CharacteristicValue]) -> str | None:
    if not values:
        return None
    lines = ["Características importadas:"]
    for key in sorted(values):
        value = values[key]
        rendered = ", ".join(value) if isinstance(value, list) else str(value)
        lines.append(f"- {key}: {rendered}")
    return "\n".join(lines)


def _composed_description(authority: DictionaryAuthority) -> str | None:
    blocks = [item for item in (authority.description, _format_characteristics(authority.characteristics)) if item]
    return "\n\n".join(blocks) if blocks else None


def _provenance_note(
    dictionary: AuthorityDictionary,
    *,
    item_id: str,
    item_note: str | None = None,
) -> str:
    parts = [
        f"Importado desde diccionario {dictionary.dictionary_id}",
        f"Elemento local: {item_id}",
        f"Fuente: {dictionary.source.title}",
    ]
    if dictionary.source.organization:
        parts.append(f"Organización: {dictionary.source.organization}")
    if dictionary.source.reference:
        parts.append(f"Referencia: {dictionary.source.reference}")
    if dictionary.source.url:
        parts.append(f"URL: {dictionary.source.url}")
    if item_note:
        parts.append(item_note)
    return " · ".join(parts)


def _target_tuple(relation: EntityRelation) -> tuple[str, str]:
    if relation.target_authority_id:
        return "authority", relation.target_authority_id
    if relation.target_archival_unit_id:
        return "archival_unit", relation.target_archival_unit_id
    if relation.target_document_part_id:
        return "document_part", relation.target_document_part_id
    return "invalid", ""


def _authority_indexes(
    session: Session, project_id: str
) -> tuple[
    dict[str, AuthorityRecord],
    dict[str, list[AuthorityAlias]],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    authorities = session.scalars(
        select(AuthorityRecord)
        .where(AuthorityRecord.project_id == project_id)
        .order_by(AuthorityRecord.id)
    ).all()
    by_id = {authority.id: authority for authority in authorities}
    aliases = session.scalars(
        select(AuthorityAlias).where(AuthorityAlias.authority_id.in_(by_id))
    ).all() if by_id else []
    aliases_by_authority: dict[str, list[AuthorityAlias]] = {key: [] for key in by_id}
    preferred_index: dict[str, set[str]] = {}
    alias_index: dict[str, set[str]] = {}
    for authority in authorities:
        preferred_index.setdefault(authority.normalized_name, set()).add(authority.id)
    for alias in aliases:
        aliases_by_authority.setdefault(alias.authority_id, []).append(alias)
        alias_index.setdefault(alias.normalized_alias, set()).add(alias.authority_id)
    return by_id, aliases_by_authority, preferred_index, alias_index


def _candidate_ids_for_authority(
    authority: DictionaryAuthority,
    preferred_index: Mapping[str, set[str]],
    alias_index: Mapping[str, set[str]],
) -> tuple[str, ...]:
    surfaces = {normalize_authority_text(authority.preferred_name)}
    surfaces.update(normalize_authority_text(alias.value) for alias in authority.aliases)
    candidates: set[str] = set()
    for surface in surfaces:
        candidates.update(preferred_index.get(surface, set()))
        candidates.update(alias_index.get(surface, set()))
    return tuple(sorted(candidates))


def _validate_temporal(
    value: str | None,
    *,
    issues: list[AuthorityDictionaryIssue],
    section: str,
    item_id: str,
    field_name: str,
) -> None:
    try:
        parse_temporal_expression(value)
    except ValueError as exc:
        _issue(issues, "error", "invalid_temporal_expression", section, item_id, field_name, str(exc))


def _authority_action(
    authority: DictionaryAuthority,
    *,
    by_id: Mapping[str, AuthorityRecord],
    preferred_index: Mapping[str, set[str]],
    alias_index: Mapping[str, set[str]],
    issues: list[AuthorityDictionaryIssue],
) -> tuple[str, str | None, tuple[str, ...]]:
    candidates = _candidate_ids_for_authority(authority, preferred_index, alias_index)
    resolution = authority.resolution
    if resolution.action == "skip":
        return "skip", None, candidates
    if resolution.action == "use_existing":
        existing = by_id.get(resolution.authority_id or "")
        if existing is None:
            _issue(
                issues,
                "error",
                "unknown_existing_authority",
                "authorities",
                authority.local_id,
                "resolution.authority_id",
                "La autoridad indicada no existe en este proyecto.",
            )
            return "error", None, candidates
        surfaces = {normalize_authority_text(authority.preferred_name)}
        surfaces.update(normalize_authority_text(alias.value) for alias in authority.aliases)
        existing_surfaces = {existing.normalized_name}
        existing_surfaces.update(
            surface for surface, ids in alias_index.items() if existing.id in ids
        )
        if not surfaces.intersection(existing_surfaces):
            _issue(
                issues,
                "error",
                "explicit_match_without_shared_name",
                "authorities",
                authority.local_id,
                "resolution.authority_id",
                "La autoridad indicada no comparte nombre preferido ni alias con el registro importado.",
                (existing.id,),
            )
            return "error", None, candidates
        if existing.entity_type != authority.entity_type:
            _issue(
                issues,
                "error",
                "authority_type_mismatch",
                "authorities",
                authority.local_id,
                "entity_type",
                f"El registro existente es {existing.entity_type}, no {authority.entity_type}.",
                (existing.id,),
            )
            return "error", None, candidates
        return "reuse", existing.id, candidates
    if resolution.action == "create_new":
        if candidates:
            _issue(
                issues,
                "warning",
                "explicit_create_near_existing",
                "authorities",
                authority.local_id,
                "resolution.action",
                "Se creará una autoridad nueva pese a existir superficies coincidentes.",
                candidates,
            )
        return "create", None, candidates

    preferred_norm = normalize_authority_text(authority.preferred_name)
    exact_preferred = sorted(preferred_index.get(preferred_norm, set()))
    compatible = [
        authority_id
        for authority_id in exact_preferred
        if by_id[authority_id].entity_type == authority.entity_type
    ]
    if len(candidates) == 0:
        return "create", None, candidates
    if len(candidates) == 1 and compatible == list(candidates):
        return "reuse", candidates[0], candidates
    _issue(
        issues,
        "error",
        "authority_conflict_requires_resolution",
        "authorities",
        authority.local_id,
        "resolution",
        "Hay coincidencias existentes ambiguas. Indicá use_existing con authority_id, create_new o skip.",
        candidates,
    )
    return "error", None, candidates


def _plan_aliases(
    authority: DictionaryAuthority,
    *,
    action: str,
    target_authority_id: str | None,
    aliases_by_authority: Mapping[str, list[AuthorityAlias]],
    preferred_index: Mapping[str, set[str]],
    alias_index: Mapping[str, set[str]],
    issues: list[AuthorityDictionaryIssue],
) -> tuple[tuple[DictionaryAlias, ...], tuple[str, ...]]:
    seen: set[str] = set()
    to_add: list[DictionaryAlias] = []
    unchanged: list[str] = []
    preferred_norm = normalize_authority_text(authority.preferred_name)
    existing_on_target = {
        row.normalized_alias for row in aliases_by_authority.get(target_authority_id or "", [])
    }
    target_preferred = {
        surface
        for surface, ids in preferred_index.items()
        if target_authority_id and target_authority_id in ids
    }
    for alias in authority.aliases:
        normalized = normalize_authority_text(alias.value)
        if normalized in seen:
            _issue(
                issues,
                "error",
                "duplicate_alias_in_record",
                "authorities",
                authority.local_id,
                "aliases",
                f"El alias {alias.value!r} está repetido dentro del registro.",
            )
            continue
        seen.add(normalized)
        if normalized == preferred_norm or normalized in target_preferred:
            unchanged.append(alias.value)
            _issue(
                issues,
                "warning",
                "alias_equals_preferred_name",
                "authorities",
                authority.local_id,
                "aliases",
                f"El alias {alias.value!r} coincide con el nombre preferido y se omitirá.",
            )
            continue
        if normalized in existing_on_target:
            unchanged.append(alias.value)
            continue
        other_ids = set(preferred_index.get(normalized, set())) | set(alias_index.get(normalized, set()))
        if target_authority_id:
            other_ids.discard(target_authority_id)
        if other_ids and not alias.allow_ambiguous:
            _issue(
                issues,
                "error",
                "alias_conflict_requires_permission",
                "authorities",
                authority.local_id,
                "aliases",
                f"El alias {alias.value!r} ya identifica otra autoridad. Marcá allow_ambiguous=true solo si está verificado.",
                tuple(sorted(other_ids)),
            )
            continue
        if other_ids:
            _issue(
                issues,
                "warning",
                "ambiguous_alias_allowed",
                "authorities",
                authority.local_id,
                "aliases",
                f"El alias ambiguo {alias.value!r} se importará por autorización explícita.",
                tuple(sorted(other_ids)),
            )
        if action in {"create", "reuse"}:
            to_add.append(alias)
    return tuple(to_add), tuple(unchanged)


def validate_authority_dictionary(
    session: Session,
    *,
    project_id: str,
    source: Path | bytes | bytearray | BinaryIO,
) -> AuthorityDictionaryReport:
    dictionary = load_authority_dictionary(source)
    issues: list[AuthorityDictionaryIssue] = []
    if dictionary.target_project_id not in (None, "*", project_id):
        _issue(
            issues,
            "error",
            "target_project_mismatch",
            "dictionary",
            None,
            "target_project_id",
            f"El diccionario apunta a {dictionary.target_project_id}, no a {project_id}.",
        )

    by_id, aliases_by_authority, preferred_index, alias_index = _authority_indexes(
        session, project_id
    )
    local_ids: set[str] = set()
    relation_local_ids: set[str] = set()
    imported_preferred: dict[str, str] = {}
    authority_plans: list[AuthorityImportPlan] = []
    plan_by_local: dict[str, AuthorityImportPlan] = {}

    for authority in dictionary.authorities:
        if authority.local_id in local_ids:
            _issue(
                issues,
                "error",
                "duplicate_authority_local_id",
                "authorities",
                authority.local_id,
                "local_id",
                "El local_id está repetido.",
            )
        local_ids.add(authority.local_id)
        preferred_norm = normalize_authority_text(authority.preferred_name)
        previous_local = imported_preferred.get(preferred_norm)
        if previous_local and previous_local != authority.local_id:
            _issue(
                issues,
                "error",
                "duplicate_imported_preferred_name",
                "authorities",
                authority.local_id,
                "preferred_name",
                f"El nombre preferido ya fue usado por {previous_local}.",
            )
        imported_preferred[preferred_norm] = authority.local_id
        _validate_temporal(
            authority.temporal_expression,
            issues=issues,
            section="authorities",
            item_id=authority.local_id,
            field_name="temporal_expression",
        )
        action, existing_id, candidates = _authority_action(
            authority,
            by_id=by_id,
            preferred_index=preferred_index,
            alias_index=alias_index,
            issues=issues,
        )
        if action == "reuse" and existing_id:
            existing = by_id[existing_id]
            imported_description = _composed_description(authority)
            differences: list[str] = []
            if imported_description and imported_description != existing.description:
                differences.append("descripción/características")
            if authority.temporal_expression and authority.temporal_expression != existing.temporal_expression:
                differences.append("temporalidad")
            if differences:
                _issue(
                    issues,
                    "warning",
                    "existing_authority_not_overwritten",
                    "authorities",
                    authority.local_id,
                    None,
                    "Se reutilizará la autoridad sin sobrescribir " + ", ".join(differences) + ".",
                    (existing_id,),
                )
        aliases_to_add, aliases_unchanged = _plan_aliases(
            authority,
            action=action,
            target_authority_id=existing_id,
            aliases_by_authority=aliases_by_authority,
            preferred_index=preferred_index,
            alias_index=alias_index,
            issues=issues,
        )
        plan = AuthorityImportPlan(
            local_id=authority.local_id,
            preferred_name=authority.preferred_name,
            entity_type=authority.entity_type,
            action=action,
            existing_authority_id=existing_id,
            candidate_ids=candidates,
            aliases_to_add=aliases_to_add,
            aliases_unchanged=aliases_unchanged,
        )
        authority_plans.append(plan)
        plan_by_local[authority.local_id] = plan

    # Detect collisions among imported aliases and imported preferred names.
    imported_surface_owner: dict[str, str] = dict(imported_preferred)
    for authority in dictionary.authorities:
        for alias in authority.aliases:
            normalized = normalize_authority_text(alias.value)
            owner = imported_surface_owner.get(normalized)
            if owner and owner != authority.local_id and not alias.allow_ambiguous:
                _issue(
                    issues,
                    "error",
                    "imported_surface_conflict",
                    "authorities",
                    authority.local_id,
                    "aliases",
                    f"El alias {alias.value!r} coincide con una superficie de {owner}.",
                )
            elif owner and owner != authority.local_id:
                _issue(
                    issues,
                    "warning",
                    "imported_ambiguous_alias_allowed",
                    "authorities",
                    authority.local_id,
                    "aliases",
                    f"El alias ambiguo {alias.value!r} fue autorizado explícitamente.",
                )
            else:
                imported_surface_owner[normalized] = authority.local_id

    existing_relations = session.scalars(
        select(EntityRelation).where(
            EntityRelation.project_id == project_id,
            EntityRelation.lifecycle_status == "active",
        )
    ).all()
    existing_base: dict[tuple[str, str, str, str], list[EntityRelation]] = {}
    for relation in existing_relations:
        kind, target_id = _target_tuple(relation)
        key = (
            relation.source_authority_id,
            _normalized_relation_label(relation.relation_label),
            kind,
            target_id,
        )
        existing_base.setdefault(key, []).append(relation)

    relation_plans: list[RelationImportPlan] = []
    imported_relation_signatures: set[tuple[str, str, str, str, str, str]] = set()
    for relation in dictionary.relations:
        if relation.local_id in relation_local_ids:
            _issue(
                issues,
                "error",
                "duplicate_relation_local_id",
                "relations",
                relation.local_id,
                "local_id",
                "El local_id de relación está repetido.",
            )
        relation_local_ids.add(relation.local_id)
        _validate_temporal(
            relation.temporal_expression,
            issues=issues,
            section="relations",
            item_id=relation.local_id,
            field_name="temporal_expression",
        )
        source_plan = plan_by_local.get(relation.source_local_id)
        source_authority_id: str | None = None
        action = "create"
        if source_plan is None:
            _issue(
                issues,
                "error",
                "unknown_relation_source",
                "relations",
                relation.local_id,
                "source_local_id",
                f"No existe la autoridad local {relation.source_local_id}.",
            )
            action = "error"
        elif source_plan.action in {"skip", "error"}:
            _issue(
                issues,
                "error",
                "unavailable_relation_source",
                "relations",
                relation.local_id,
                "source_local_id",
                "La autoridad de origen se omite o tiene conflictos.",
            )
            action = "error"
        else:
            source_authority_id = source_plan.existing_authority_id

        resolved_target_id = relation.target_id
        target_local_id = relation.target_local_id
        if relation.target_kind == "authority" and target_local_id:
            target_plan = plan_by_local.get(target_local_id)
            if target_plan is None:
                _issue(
                    issues,
                    "error",
                    "unknown_relation_target",
                    "relations",
                    relation.local_id,
                    "target_local_id",
                    f"No existe la autoridad local {target_local_id}.",
                )
                action = "error"
            elif target_plan.action in {"skip", "error"}:
                _issue(
                    issues,
                    "error",
                    "unavailable_relation_target",
                    "relations",
                    relation.local_id,
                    "target_local_id",
                    "La autoridad de destino se omite o tiene conflictos.",
                )
                action = "error"
            else:
                resolved_target_id = target_plan.existing_authority_id
        elif relation.target_kind == "authority" and resolved_target_id:
            target = by_id.get(resolved_target_id)
            if target is None:
                _issue(
                    issues,
                    "error",
                    "unknown_target_authority",
                    "relations",
                    relation.local_id,
                    "target_id",
                    "La autoridad de destino no existe en este proyecto.",
                )
                action = "error"
        elif relation.target_kind == "archival_unit" and resolved_target_id:
            target = session.get(ArchivalUnit, resolved_target_id)
            if target is None or target.project_id != project_id:
                _issue(
                    issues,
                    "error",
                    "unknown_target_archival_unit",
                    "relations",
                    relation.local_id,
                    "target_id",
                    "La unidad archivística de destino no existe en este proyecto.",
                )
                action = "error"
        elif relation.target_kind == "document_part" and resolved_target_id:
            target = session.get(DocumentPart, resolved_target_id)
            digital = session.get(DigitalObject, target.digital_object_id) if target else None
            if target is None or digital is None or digital.project_id != project_id:
                _issue(
                    issues,
                    "error",
                    "unknown_target_document_part",
                    "relations",
                    relation.local_id,
                    "target_id",
                    "La parte documental de destino no existe en este proyecto.",
                )
                action = "error"

        if (
            relation.target_kind == "authority"
            and relation.target_local_id
            and relation.target_local_id == relation.source_local_id
        ):
            _issue(
                issues,
                "error",
                "self_relation",
                "relations",
                relation.local_id,
                "target_local_id",
                "Una autoridad no puede relacionarse consigo misma.",
            )
            action = "error"
        elif (
            relation.target_kind == "authority"
            and source_authority_id
            and resolved_target_id
            and source_authority_id == resolved_target_id
        ):
            _issue(
                issues,
                "error",
                "self_relation",
                "relations",
                relation.local_id,
                "target_id",
                "Una autoridad no puede relacionarse consigo misma.",
            )
            action = "error"

        duplicate_relation_id: str | None = None
        target_key = resolved_target_id or f"local:{target_local_id}"
        source_key = source_authority_id or f"local:{relation.source_local_id}"
        signature = (
            source_key,
            _normalized_relation_label(relation.relation_label),
            relation.target_kind,
            target_key,
            _normalized_optional(relation.temporal_expression),
            _normalized_optional(relation.evidence.render()),
        )
        if signature in imported_relation_signatures:
            _issue(
                issues,
                "error",
                "duplicate_imported_relation",
                "relations",
                relation.local_id,
                None,
                "La misma relación ya aparece en este diccionario.",
            )
            action = "error"
        imported_relation_signatures.add(signature)

        if action == "create" and source_authority_id and resolved_target_id:
            base_key = (
                source_authority_id,
                _normalized_relation_label(relation.relation_label),
                relation.target_kind,
                resolved_target_id,
            )
            nearby = existing_base.get(base_key, [])
            exact = next(
                (
                    row
                    for row in nearby
                    if _normalized_optional(row.temporal_expression)
                    == _normalized_optional(relation.temporal_expression)
                    and _normalized_optional(row.evidence_note)
                    == _normalized_optional(relation.evidence.render())
                ),
                None,
            )
            if exact is not None:
                action = "skip_duplicate"
                duplicate_relation_id = exact.id
            elif nearby:
                if relation.resolution.action == "create_parallel":
                    _issue(
                        issues,
                        "warning",
                        "parallel_relation_authorized",
                        "relations",
                        relation.local_id,
                        "resolution.action",
                        "Se creará una relación paralela porque difiere la evidencia o temporalidad.",
                        tuple(row.id for row in nearby),
                    )
                elif relation.resolution.action == "skip":
                    action = "skip"
                else:
                    _issue(
                        issues,
                        "error",
                        "relation_conflict_requires_resolution",
                        "relations",
                        relation.local_id,
                        "resolution",
                        "Ya existe una relación equivalente con evidencia o temporalidad distinta. Elegí create_parallel o skip.",
                        tuple(row.id for row in nearby),
                    )
                    action = "error"
        elif action == "create" and relation.resolution.action == "skip":
            action = "skip"

        relation_plans.append(
            RelationImportPlan(
                local_id=relation.local_id,
                relation_label=relation.relation_label,
                action=action,
                source_local_id=relation.source_local_id,
                source_authority_id=source_authority_id,
                target_kind=relation.target_kind,
                target_local_id=target_local_id,
                target_id=resolved_target_id,
                duplicate_relation_id=duplicate_relation_id,
            )
        )

    valid = not any(issue.severity == "error" for issue in issues)
    return AuthorityDictionaryReport(
        schema_version=dictionary.schema_version,
        dictionary_id=dictionary.dictionary_id,
        dictionary_name=dictionary.dictionary_name,
        dictionary_sha256=_canonical_hash(dictionary),
        target_project_id=dictionary.target_project_id,
        valid=valid,
        authority_plans=authority_plans,
        relation_plans=relation_plans,
        issues=issues,
    )


def apply_authority_dictionary(
    session: Session,
    *,
    project_id: str,
    source: Path | bytes | bytearray | BinaryIO,
    changed_by: str,
) -> AuthorityDictionaryApplyResult:
    raw = _read_source(source)
    dictionary = load_authority_dictionary(raw)
    report = validate_authority_dictionary(session, project_id=project_id, source=raw)
    if not report.valid:
        first = next(issue for issue in report.issues if issue.severity == "error")
        item = f" {first.item_id}" if first.item_id else ""
        raise ValueError(f"El diccionario contiene errores ({first.section}{item}): {first.message}")

    actor = changed_by.strip() or "local_user"
    authority_input = {item.local_id: item for item in dictionary.authorities}
    authority_plan = {item.local_id: item for item in report.authority_plans}
    local_to_authority_id: dict[str, str] = {}
    created = reused = skipped = aliases_added = 0

    for local_id, plan in authority_plan.items():
        item = authority_input[local_id]
        if plan.action == "skip":
            skipped += 1
            continue
        if plan.action == "reuse":
            authority_id = plan.existing_authority_id
            if authority_id is None:
                raise RuntimeError(f"Plan de reutilización sin authority_id: {local_id}")
            reused += 1
        elif plan.action == "create":
            authority = create_authority(
                session,
                project_id=project_id,
                entity_type=item.entity_type,
                preferred_name=item.preferred_name,
                description=_composed_description(item),
                temporal_expression=item.temporal_expression,
                temporal_note=item.temporal_note,
                review_status=item.review_status,
                created_by=actor,
                note=_provenance_note(
                    dictionary,
                    item_id=item.local_id,
                    item_note=item.source_note,
                ),
            )
            authority_id = authority.id
            created += 1
        else:
            raise RuntimeError(f"Plan de autoridad no aplicable: {local_id} ({plan.action})")
        local_to_authority_id[local_id] = authority_id
        for alias in plan.aliases_to_add:
            add_authority_alias(
                session,
                authority_id=authority_id,
                alias=alias.value,
                alias_type=alias.alias_type,
                created_by=actor,
                note=_provenance_note(
                    dictionary,
                    item_id=item.local_id,
                    item_note=alias.note or item.source_note,
                ),
            )
            aliases_added += 1

    relation_input = {item.local_id: item for item in dictionary.relations}
    relations_created = relations_skipped = 0
    for plan in report.relation_plans:
        if plan.action in {"skip", "skip_duplicate"}:
            relations_skipped += 1
            continue
        if plan.action != "create":
            raise RuntimeError(f"Plan de relación no aplicable: {plan.local_id} ({plan.action})")
        item = relation_input[plan.local_id]
        source_id = local_to_authority_id[item.source_local_id]
        if item.target_kind == "authority" and item.target_local_id:
            target_id = local_to_authority_id[item.target_local_id]
        else:
            target_id = item.target_id
        if target_id is None:
            raise RuntimeError(f"Relación sin destino resuelto: {item.local_id}")
        create_entity_relation(
            session,
            project_id=project_id,
            source_authority_id=source_id,
            relation_label=item.relation_label,
            target_kind="entity" if item.target_kind == "authority" else item.target_kind,
            target_id=target_id,
            evidence_note=item.evidence.render(),
            temporal_expression=item.temporal_expression,
            temporal_note=item.temporal_note,
            review_status=item.review_status,
            created_by=actor,
            note=_provenance_note(dictionary, item_id=item.local_id),
        )
        relations_created += 1

    return AuthorityDictionaryApplyResult(
        authorities_created=created,
        authorities_reused=reused,
        authorities_skipped=skipped,
        aliases_added=aliases_added,
        relations_created=relations_created,
        relations_skipped=relations_skipped,
        local_to_authority_id=local_to_authority_id,
    )


__all__ = [
    "DICTIONARY_SCHEMA_VERSION",
    "AuthorityDictionary",
    "AuthorityDictionaryApplyResult",
    "AuthorityDictionaryReport",
    "apply_authority_dictionary",
    "authority_dictionary_example",
    "authority_dictionary_example_bytes",
    "authority_dictionary_schema",
    "authority_dictionary_schema_bytes",
    "load_authority_dictionary",
    "validate_authority_dictionary",
]
