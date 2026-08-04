from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

PAGE_REVIEW_STATUSES = ("unreviewed", "needs_review", "reviewed", "approved")
DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES = ("approved",)
ANALYSIS_QUALITY_POLICY_VERSION = "analysis_quality_v2"

_PAGE_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "reviewed": "Revisada",
    "approved": "Aprobada",
}


@dataclass(frozen=True, slots=True)
class AutomaticAnalysisSpec:
    """Contrato de calidad que debe declarar todo análisis automático."""

    key: str
    label: str
    implementation_status: str


_AUTOMATIC_ANALYSIS_SPECS = (
    AutomaticAnalysisSpec("corpus_export", "Exportación de corpus", "implemented"),
    AutomaticAnalysisSpec("semantic_index", "Índice y búsqueda semántica", "implemented"),
    AutomaticAnalysisSpec("mention_suggestions", "Sugerencias automáticas de menciones", "implemented"),
    AutomaticAnalysisSpec("summary", "Resúmenes automáticos", "contract_ready"),
    AutomaticAnalysisSpec("statistics", "Estadísticas automáticas", "contract_ready"),
    AutomaticAnalysisSpec("open_discovery", "Descubrimiento abierto", "implemented"),
    AutomaticAnalysisSpec("assisted_import", "Importaciones asistidas", "contract_ready"),
    AutomaticAnalysisSpec("llm_tool", "Herramientas LLM", "contract_ready"),
    AutomaticAnalysisSpec("rag", "Sistema RAG", "contract_ready"),
    AutomaticAnalysisSpec("integration", "Integraciones automáticas", "contract_ready"),
)
AUTOMATIC_ANALYSIS_SPECS = {spec.key: spec for spec in _AUTOMATIC_ANALYSIS_SPECS}


@dataclass(frozen=True, slots=True)
class AnalysisQualityScope:
    """Alcance de calidad reproducible para análisis automáticos."""

    page_review_statuses: tuple[str, ...]

    @property
    def is_default(self) -> bool:
        return self.page_review_statuses == DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES

    @property
    def includes_all(self) -> bool:
        return not self.page_review_statuses

    @property
    def is_broader_than_default(self) -> bool:
        return not self.is_default

    @property
    def key(self) -> str:
        if self.includes_all:
            return "all"
        if self.is_default:
            return "approved_only"
        return "broader"

    @property
    def label(self) -> str:
        if self.includes_all:
            return "Todas las páginas, incluso las no aprobadas"
        labels = [_PAGE_LABELS[value] for value in self.page_review_statuses]
        return "Páginas " + ", ".join(label.lower() for label in labels)


@dataclass(frozen=True, slots=True)
class AutomaticAnalysisAuthorizationValues:
    """Datos mínimos para autorizar y auditar una ejecución automática."""

    analysis_kind: str
    page_review_statuses: tuple[str, ...]
    broader_scope_confirmed: bool
    confirmed_by: str
    confirmation_reason: str | None
    source: str
    target_type: str | None = None
    target_id: str | None = None
    parameters_sha256: str | None = None


def automatic_analysis_spec(kind: str) -> AutomaticAnalysisSpec:
    try:
        return AUTOMATIC_ANALYSIS_SPECS[kind]
    except KeyError as exc:
        raise ValueError(
            "Tipo de análisis automático no registrado en la política común: " + kind
        ) from exc


def normalize_page_review_statuses(
    values: Iterable[str],
    *,
    default_when_empty: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    selected = tuple(dict.fromkeys(value for value in values if value))
    if not selected and default_when_empty is not None:
        selected = tuple(default_when_empty)
    invalid = set(selected) - set(PAGE_REVIEW_STATUSES)
    if invalid:
        raise ValueError(
            "Estado de revisión de página inválido: " + ", ".join(sorted(invalid))
        )
    return tuple(value for value in PAGE_REVIEW_STATUSES if value in selected)


def analysis_quality_scope(values: Iterable[str]) -> AnalysisQualityScope:
    return AnalysisQualityScope(normalize_page_review_statuses(values))


def _clean_actor(value: str) -> str:
    actor = " ".join((value or "").split())
    if not actor:
        raise ValueError("El análisis automático debe registrar una persona responsable")
    if len(actor) > 200:
        raise ValueError("La persona responsable no puede superar 200 caracteres")
    return actor


def _clean_reason(value: str | None) -> str | None:
    reason = " ".join((value or "").split())
    if not reason:
        return None
    if len(reason) > 2000:
        raise ValueError("El fundamento del alcance no puede superar 2000 caracteres")
    return reason


def validate_automatic_quality_scope(
    values: Iterable[str],
    *,
    broader_scope_confirmed: bool = False,
    confirmation_reason: str | None = None,
) -> AnalysisQualityScope:
    """Exige confirmación y fundamento para salir del alcance seguro.

    Un conjunto vacío significa todos los estados. No existe una ruta de
    compatibilidad programática que omita esta autorización.
    """

    scope = analysis_quality_scope(values)
    if scope.is_broader_than_default:
        if not broader_scope_confirmed:
            raise ValueError(
                "El análisis automático usa solamente páginas aprobadas de manera "
                "predeterminada. Para incluir otros estados, confirmá explícitamente "
                "el alcance ampliado."
            )
        if not _clean_reason(confirmation_reason):
            raise ValueError(
                "El alcance ampliado necesita un fundamento breve que quede registrado."
            )
    return scope


def automatic_analysis_parameters_sha256(
    parameters: Mapping[str, Any] | None,
) -> str | None:
    """Huella canónica de los parámetros que fueron autorizados."""

    if parameters is None:
        return None
    canonical = json.dumps(
        dict(parameters),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def validate_automatic_analysis_authorization(
    *,
    analysis_kind: str,
    page_review_statuses: Iterable[str],
    broader_scope_confirmed: bool = False,
    confirmed_by: str,
    confirmation_reason: str | None = None,
    source: str,
    target_type: str | None = None,
    target_id: str | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> AutomaticAnalysisAuthorizationValues:
    automatic_analysis_spec(analysis_kind)
    scope = validate_automatic_quality_scope(
        page_review_statuses,
        broader_scope_confirmed=broader_scope_confirmed,
        confirmation_reason=confirmation_reason,
    )
    actor = _clean_actor(confirmed_by)
    reason = _clean_reason(confirmation_reason)
    clean_source = " ".join((source or "").split())
    if clean_source not in {"ui", "cli", "api", "script"}:
        raise ValueError("Origen de autorización inválido: " + (clean_source or "[vacío]"))
    payload_hash = automatic_analysis_parameters_sha256(parameters)
    return AutomaticAnalysisAuthorizationValues(
        analysis_kind=analysis_kind,
        page_review_statuses=scope.page_review_statuses,
        broader_scope_confirmed=scope.is_broader_than_default,
        confirmed_by=actor,
        confirmation_reason=reason,
        source=clean_source,
        target_type=(" ".join(target_type.split()) if target_type else None),
        target_id=(" ".join(target_id.split()) if target_id else None),
        parameters_sha256=payload_hash,
    )


def quality_scope_snapshot(
    *, analysis_kind: str, page_review_statuses: Iterable[str]
) -> dict[str, Any]:
    spec = automatic_analysis_spec(analysis_kind)
    scope = analysis_quality_scope(page_review_statuses)
    return {
        "policy_version": ANALYSIS_QUALITY_POLICY_VERSION,
        "analysis_kind": spec.key,
        "analysis_label": spec.label,
        "page_review_statuses": list(scope.page_review_statuses),
        "scope_key": scope.key,
        "scope_label": scope.label,
    }


def quality_scope_caption(values: Iterable[str]) -> str:
    scope = analysis_quality_scope(values)
    if scope.is_default:
        return "Alcance de calidad: solo páginas aprobadas."
    return f"Alcance de calidad ampliado: {scope.label}."
