from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from archive_workbench.analysis_quality import (
    ANALYSIS_QUALITY_POLICY_VERSION,
    AutomaticAnalysisAuthorizationValues,
    analysis_quality_scope,
    automatic_analysis_parameters_sha256,
    automatic_analysis_spec,
    normalize_page_review_statuses,
    validate_automatic_analysis_authorization,
)
from archive_workbench.db.models import AutomaticAnalysisAuthorization, utc_now
from archive_workbench.identity import new_id


@dataclass(frozen=True, slots=True)
class AutomaticAnalysisAuthorizationRow:
    authorization_id: str
    analysis_kind: str
    analysis_label: str
    page_review_statuses: tuple[str, ...]
    scope_key: str
    broader_scope_confirmed: bool
    confirmed_by: str
    confirmation_reason: str | None
    source: str
    target_type: str | None
    target_id: str | None
    parameters_sha256: str | None
    created_at: datetime


def record_automatic_analysis_authorization(
    session: Session,
    *,
    project_id: str,
    analysis_kind: str,
    page_review_statuses: tuple[str, ...],
    broader_scope_confirmed: bool = False,
    confirmed_by: str,
    confirmation_reason: str | None = None,
    source: str,
    target_type: str | None = None,
    target_id: str | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> AutomaticAnalysisAuthorization:
    values: AutomaticAnalysisAuthorizationValues = (
        validate_automatic_analysis_authorization(
            analysis_kind=analysis_kind,
            page_review_statuses=page_review_statuses,
            broader_scope_confirmed=broader_scope_confirmed,
            confirmed_by=confirmed_by,
            confirmation_reason=confirmation_reason,
            source=source,
            target_type=target_type,
            target_id=target_id,
            parameters=parameters,
        )
    )
    scope = analysis_quality_scope(values.page_review_statuses)
    row = AutomaticAnalysisAuthorization(
        id=new_id(),
        project_id=project_id,
        policy_version=ANALYSIS_QUALITY_POLICY_VERSION,
        analysis_kind=values.analysis_kind,
        page_review_statuses_json=list(values.page_review_statuses),
        scope_key=scope.key,
        broader_scope_confirmed=values.broader_scope_confirmed,
        confirmed_by=values.confirmed_by,
        confirmation_reason=values.confirmation_reason,
        source=values.source,
        target_type=values.target_type,
        target_id=values.target_id,
        parameters_sha256=values.parameters_sha256,
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


@dataclass(frozen=True, slots=True)
class AutomaticAnalysisAuthorizationFilterOptions:
    analysis_kinds: tuple[tuple[str, str], ...]
    confirmed_by: tuple[str, ...]
    sources: tuple[str, ...]
    scope_keys: tuple[str, ...]


def automatic_analysis_authorization_filter_options(
    session: Session,
    *,
    project_id: str,
) -> AutomaticAnalysisAuthorizationFilterOptions:
    kinds = tuple(
        str(value)
        for value in session.scalars(
            select(AutomaticAnalysisAuthorization.analysis_kind)
            .where(AutomaticAnalysisAuthorization.project_id == project_id)
            .distinct()
            .order_by(AutomaticAnalysisAuthorization.analysis_kind)
        ).all()
        if str(value).strip()
    )
    confirmed_by = tuple(
        str(value)
        for value in session.scalars(
            select(AutomaticAnalysisAuthorization.confirmed_by)
            .where(AutomaticAnalysisAuthorization.project_id == project_id)
            .distinct()
            .order_by(AutomaticAnalysisAuthorization.confirmed_by)
        ).all()
        if str(value).strip()
    )
    sources = tuple(
        str(value)
        for value in session.scalars(
            select(AutomaticAnalysisAuthorization.source)
            .where(AutomaticAnalysisAuthorization.project_id == project_id)
            .distinct()
            .order_by(AutomaticAnalysisAuthorization.source)
        ).all()
        if str(value).strip()
    )
    scope_keys = tuple(
        str(value)
        for value in session.scalars(
            select(AutomaticAnalysisAuthorization.scope_key)
            .where(AutomaticAnalysisAuthorization.project_id == project_id)
            .distinct()
            .order_by(AutomaticAnalysisAuthorization.scope_key)
        ).all()
        if str(value).strip()
    )
    return AutomaticAnalysisAuthorizationFilterOptions(
        analysis_kinds=tuple((kind, automatic_analysis_spec(kind).label) for kind in kinds),
        confirmed_by=confirmed_by,
        sources=sources,
        scope_keys=scope_keys,
    )


def automatic_analysis_authorization_rows(
    session: Session,
    *,
    project_id: str,
    analysis_kind: str | None = None,
    confirmed_by: str | None = None,
    source: str | None = None,
    scope_key: str | None = None,
    query: str | None = None,
    limit: int = 100,
) -> list[AutomaticAnalysisAuthorizationRow]:
    statement = select(AutomaticAnalysisAuthorization).where(
        AutomaticAnalysisAuthorization.project_id == project_id
    )
    if analysis_kind:
        statement = statement.where(
            AutomaticAnalysisAuthorization.analysis_kind == analysis_kind
        )
    if confirmed_by:
        statement = statement.where(
            AutomaticAnalysisAuthorization.confirmed_by == confirmed_by
        )
    if source:
        statement = statement.where(AutomaticAnalysisAuthorization.source == source)
    if scope_key:
        statement = statement.where(
            AutomaticAnalysisAuthorization.scope_key == scope_key
        )
    clean_query = " ".join((query or "").split()).lower()
    if clean_query:
        pattern = f"%{clean_query}%"
        statement = statement.where(
            or_(
                AutomaticAnalysisAuthorization.analysis_kind.ilike(pattern),
                AutomaticAnalysisAuthorization.confirmed_by.ilike(pattern),
                AutomaticAnalysisAuthorization.confirmation_reason.ilike(pattern),
                AutomaticAnalysisAuthorization.target_type.ilike(pattern),
                AutomaticAnalysisAuthorization.target_id.ilike(pattern),
            )
        )
    rows = session.scalars(
        statement.order_by(
            AutomaticAnalysisAuthorization.created_at.desc(),
            AutomaticAnalysisAuthorization.id.desc(),
        ).limit(max(1, int(limit)))
    ).all()
    result: list[AutomaticAnalysisAuthorizationRow] = []
    for row in rows:
        spec = automatic_analysis_spec(row.analysis_kind)
        result.append(
            AutomaticAnalysisAuthorizationRow(
                authorization_id=row.id,
                analysis_kind=row.analysis_kind,
                analysis_label=spec.label,
                page_review_statuses=tuple(row.page_review_statuses_json or []),
                scope_key=row.scope_key,
                broader_scope_confirmed=bool(row.broader_scope_confirmed),
                confirmed_by=row.confirmed_by,
                confirmation_reason=row.confirmation_reason,
                source=row.source,
                target_type=row.target_type,
                target_id=row.target_id,
                parameters_sha256=row.parameters_sha256,
                created_at=row.created_at,
            )
        )
    return result

def require_automatic_analysis_authorization(
    session: Session,
    *,
    project_id: str,
    analysis_kind: str,
    page_review_statuses: tuple[str, ...],
    target_type: str,
    target_id: str,
    parameters: Mapping[str, Any],
    remediation: str,
) -> AutomaticAnalysisAuthorization:
    """Impide ejecutar una configuración que no tenga autorización vigente.

    Las autorizaciones se comparan por política, tipo de análisis, destino,
    estados de página y huella de los parámetros funcionales. De este modo,
    una fila histórica no autoriza silenciosamente una configuración distinta.
    """

    automatic_analysis_spec(analysis_kind)
    statuses = normalize_page_review_statuses(page_review_statuses)
    parameters_sha256 = automatic_analysis_parameters_sha256(parameters)
    rows = session.scalars(
        select(AutomaticAnalysisAuthorization)
        .where(
            AutomaticAnalysisAuthorization.project_id == project_id,
            AutomaticAnalysisAuthorization.policy_version
            == ANALYSIS_QUALITY_POLICY_VERSION,
            AutomaticAnalysisAuthorization.analysis_kind == analysis_kind,
            AutomaticAnalysisAuthorization.target_type == target_type,
            AutomaticAnalysisAuthorization.target_id == target_id,
            AutomaticAnalysisAuthorization.parameters_sha256 == parameters_sha256,
        )
        .order_by(
            AutomaticAnalysisAuthorization.created_at.desc(),
            AutomaticAnalysisAuthorization.id.desc(),
        )
    ).all()
    for row in rows:
        if tuple(row.page_review_statuses_json or ()) == statuses:
            return row
    raise ValueError(
        "No existe una autorización vigente para ejecutar este análisis con "
        "la configuración actual. " + remediation
    )
