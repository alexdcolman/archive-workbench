from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    ArchivalUnit,
    DigitalObject,
    Project,
    SourceRegistration,
    WorkAssignment,
    WorkAssignmentRevision,
    utc_now,
)
from archive_workbench.identity import new_id
from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES

ASSIGNMENT_KINDS = ("processing", "primary_review", "cross_review")
ASSIGNMENT_STATUSES = (
    "planned",
    "in_progress",
    "submitted",
    "completed",
    "blocked",
    "cancelled",
)
ASSIGNMENT_PRIORITIES = ("low", "normal", "high", "urgent")
CROSS_REVIEW_OUTCOMES = ("accepted", "changes_requested", "not_applicable")
ACTIVE_ASSIGNMENT_STATUSES = ("planned", "in_progress", "submitted", "blocked")
_UNSET = object()


@dataclass(slots=True)
class WorkAssignmentRow:
    assignment_id: str
    project_id: str
    source_type: str
    source_key: str
    title: str
    archival_path: str
    page_start: int | None
    page_end: int | None
    assignment_kind: str
    assignee: str
    status: str
    priority: str
    due_at: datetime | None
    parent_assignment_id: str | None
    parent_assignee: str | None
    outcome: str | None
    note: str | None
    submitted_at: datetime | None
    completed_at: datetime | None
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime
    revision: int

    @property
    def scope_label(self) -> str:
        if self.page_start is None:
            return "Documento completo"
        if self.page_start == self.page_end:
            return f"Página {self.page_start}"
        return f"Páginas {self.page_start}–{self.page_end}"


@dataclass(slots=True)
class WorkloadSummaryRow:
    assignee: str
    total: int
    planned: int
    in_progress: int
    submitted: int
    blocked: int
    completed: int
    cancelled: int
    primary_review: int
    cross_review: int
    processing: int
    overdue: int


@dataclass(slots=True)
class CrossReviewCandidateRow:
    assignment_id: str
    source_key: str
    title: str
    archival_path: str
    page_start: int | None
    page_end: int | None
    assignee: str
    status: str
    submitted_at: datetime | None
    active_cross_reviews: int
    completed_cross_reviews: int


@dataclass(slots=True)
class WorkAssignmentRevisionRow:
    revision_number: int
    operation: str
    snapshot: dict[str, object]
    note: str | None
    changed_by: str
    changed_at: datetime


def _clean_actor(value: str) -> str:
    return value.strip() or "local_user"


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _iso_datetime(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value is not None else None


def _archival_paths(session: Session, project_id: str) -> dict[str, str]:
    units = session.scalars(
        select(ArchivalUnit).where(ArchivalUnit.project_id == project_id)
    ).all()
    by_id = {unit.id: unit for unit in units}
    cache: dict[str, str] = {}

    def resolve(unit_id: str) -> str:
        if unit_id in cache:
            return cache[unit_id]
        labels: list[str] = []
        current = by_id.get(unit_id)
        seen: set[str] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            labels.append(current.title)
            current = by_id.get(current.parent_id) if current.parent_id else None
        cache[unit_id] = " / ".join(reversed(labels))
        return cache[unit_id]

    return {unit_id: resolve(unit_id) for unit_id in by_id}


def _registration(
    session: Session, *, project_id: str, source_type: str, source_key: str
) -> SourceRegistration:
    row = session.scalar(
        select(SourceRegistration).where(
            SourceRegistration.project_id == project_id,
            SourceRegistration.source_type == source_type,
            SourceRegistration.source_key == source_key,
        )
    )
    if row is None:
        raise ValueError(f"Documento no registrado: {source_type}/{source_key}")
    return row


def _validate_scope(
    session: Session,
    *,
    registration: SourceRegistration,
    page_start: int | None,
    page_end: int | None,
) -> None:
    if (page_start is None) != (page_end is None):
        raise ValueError("page_start y page_end deben indicarse juntos")
    if page_start is None:
        return
    if page_start < 1 or page_end is None or page_end < page_start:
        raise ValueError("El rango de páginas es inválido")
    if registration.digital_object_id:
        digital = session.get(DigitalObject, registration.digital_object_id)
        if digital and digital.page_count is not None and page_end > digital.page_count:
            raise ValueError(
                f"El rango excede las {digital.page_count} páginas registradas"
            )


def _same_scope(left: WorkAssignment, right: WorkAssignment) -> bool:
    return (
        left.source_type == right.source_type
        and left.source_key == right.source_key
        and left.page_start == right.page_start
        and left.page_end == right.page_end
    )


def _assignment_snapshot(assignment: WorkAssignment) -> dict[str, object]:
    return {
        "project_id": assignment.project_id,
        "source_type": assignment.source_type,
        "source_key": assignment.source_key,
        "page_start": assignment.page_start,
        "page_end": assignment.page_end,
        "assignment_kind": assignment.assignment_kind,
        "assignee": assignment.assignee,
        "status": assignment.status,
        "priority": assignment.priority,
        "due_at": _iso_datetime(assignment.due_at),
        "parent_assignment_id": assignment.parent_assignment_id,
        "outcome": assignment.outcome,
        "note": assignment.note,
        "submitted_at": _iso_datetime(assignment.submitted_at),
        "completed_at": _iso_datetime(assignment.completed_at),
    }


def _append_assignment_revision(
    session: Session,
    assignment: WorkAssignment,
    *,
    operation: str,
    changed_by: str,
    note: str | None = None,
) -> WorkAssignmentRevision:
    row = WorkAssignmentRevision(
        id=new_id(),
        assignment_id=assignment.id,
        revision_number=assignment.revision,
        operation=operation,
        snapshot_json=_assignment_snapshot(assignment),
        note=note.strip() if note and note.strip() else None,
        changed_by=_clean_actor(changed_by),
        changed_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def _validate_parent(
    session: Session,
    *,
    project_id: str,
    assignment_kind: str,
    assignee: str,
    source_type: str,
    source_key: str,
    page_start: int | None,
    page_end: int | None,
    parent_assignment_id: str | None,
) -> WorkAssignment | None:
    if assignment_kind != "cross_review":
        if parent_assignment_id is not None:
            raise ValueError("Solo una revisión cruzada puede depender de otra asignación")
        return None
    if parent_assignment_id is None:
        raise ValueError("La revisión cruzada debe indicar la asignación primaria")
    parent = session.get(WorkAssignment, parent_assignment_id)
    if parent is None or parent.project_id != project_id:
        raise ValueError("La asignación primaria no existe en este proyecto")
    if parent.assignment_kind != "primary_review":
        raise ValueError("La revisión cruzada debe depender de una revisión primaria")
    probe = WorkAssignment(
        id="probe",
        project_id=project_id,
        source_type=source_type,
        source_key=source_key,
        page_start=page_start,
        page_end=page_end,
        assignment_kind=assignment_kind,
        assignee=assignee,
        status="planned",
        priority="normal",
        created_by="probe",
        updated_by="probe",
        revision=1,
    )
    if not _same_scope(parent, probe):
        raise ValueError("La revisión cruzada debe cubrir el mismo documento y páginas")
    if parent.assignee.casefold() == assignee.casefold():
        raise ValueError("La revisión cruzada debe asignarse a otra persona")
    return parent


def create_work_assignment(
    session: Session,
    *,
    project_id: str,
    source_type: str,
    source_key: str,
    assignment_kind: str,
    assignee: str,
    created_by: str,
    page_start: int | None = None,
    page_end: int | None = None,
    priority: str = "normal",
    due_at: datetime | None = None,
    parent_assignment_id: str | None = None,
    note: str | None = None,
) -> WorkAssignment:
    if session.get(Project, project_id) is None:
        raise ValueError(f"Proyecto inexistente: {project_id}")
    if assignment_kind not in ASSIGNMENT_KINDS:
        raise ValueError(f"Tipo de asignación inválido: {assignment_kind}")
    if priority not in ASSIGNMENT_PRIORITIES:
        raise ValueError(f"Prioridad inválida: {priority}")
    clean_assignee = assignee.strip()
    if not clean_assignee:
        raise ValueError("La asignación debe tener responsable")
    registration = _registration(
        session,
        project_id=project_id,
        source_type=source_type,
        source_key=source_key,
    )
    _validate_scope(
        session,
        registration=registration,
        page_start=page_start,
        page_end=page_end,
    )
    _validate_parent(
        session,
        project_id=project_id,
        assignment_kind=assignment_kind,
        assignee=clean_assignee,
        source_type=source_type,
        source_key=source_key,
        page_start=page_start,
        page_end=page_end,
        parent_assignment_id=parent_assignment_id,
    )
    duplicate = session.scalar(
        select(WorkAssignment).where(
            WorkAssignment.project_id == project_id,
            WorkAssignment.source_type == source_type,
            WorkAssignment.source_key == source_key,
            WorkAssignment.page_start.is_(None)
            if page_start is None
            else WorkAssignment.page_start == page_start,
            WorkAssignment.page_end.is_(None)
            if page_end is None
            else WorkAssignment.page_end == page_end,
            WorkAssignment.assignment_kind == assignment_kind,
            func.lower(WorkAssignment.assignee) == clean_assignee.casefold(),
            WorkAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        )
    )
    if duplicate is not None:
        raise ValueError("Ya existe una asignación activa equivalente para esa persona")
    actor = _clean_actor(created_by)
    assignment = WorkAssignment(
        id=new_id(),
        project_id=project_id,
        source_type=source_type,
        source_key=source_key,
        page_start=page_start,
        page_end=page_end,
        assignment_kind=assignment_kind,
        assignee=clean_assignee,
        status="planned",
        priority=priority,
        due_at=due_at,
        parent_assignment_id=parent_assignment_id,
        outcome=None,
        note=note.strip() if note and note.strip() else None,
        submitted_at=None,
        completed_at=None,
        created_by=actor,
        created_at=utc_now(),
        updated_by=actor,
        updated_at=utc_now(),
        revision=1,
    )
    session.add(assignment)
    session.flush()
    _append_assignment_revision(
        session, assignment, operation="create", changed_by=actor, note=note
    )
    return assignment


def create_cross_review_assignment(
    session: Session,
    *,
    primary_assignment_id: str,
    assignee: str,
    created_by: str,
    priority: str | None = None,
    due_at: datetime | None = None,
    note: str | None = None,
) -> WorkAssignment:
    parent = session.get(WorkAssignment, primary_assignment_id)
    if parent is None:
        raise ValueError(f"Asignación primaria inexistente: {primary_assignment_id}")
    if parent.assignment_kind != "primary_review":
        raise ValueError("La asignación seleccionada no es una revisión primaria")
    if parent.status not in {"submitted", "completed"}:
        raise ValueError("La revisión primaria debe estar enviada o completada")
    return create_work_assignment(
        session,
        project_id=parent.project_id,
        source_type=parent.source_type,
        source_key=parent.source_key,
        page_start=parent.page_start,
        page_end=parent.page_end,
        assignment_kind="cross_review",
        assignee=assignee,
        created_by=created_by,
        priority=priority or parent.priority,
        due_at=due_at,
        parent_assignment_id=parent.id,
        note=note,
    )


def update_work_assignment(
    session: Session,
    *,
    assignment_id: str,
    expected_revision: int,
    changed_by: str,
    assignee: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    due_at: datetime | None | object = _UNSET,
    outcome: str | None | object = _UNSET,
    assignment_note: str | None | object = _UNSET,
    change_note: str | None = None,
) -> WorkAssignment:
    assignment = session.get(WorkAssignment, assignment_id)
    if assignment is None:
        raise ValueError(f"Asignación inexistente: {assignment_id}")
    if assignment.revision != expected_revision:
        raise ValueError(
            f"La asignación está en revisión {assignment.revision}; "
            f"se esperaba {expected_revision}"
        )
    if assignee is not None:
        clean = assignee.strip()
        if not clean:
            raise ValueError("La asignación debe tener responsable")
        if assignment.assignment_kind == "cross_review" and assignment.parent_assignment_id:
            parent = session.get(WorkAssignment, assignment.parent_assignment_id)
            if parent and parent.assignee.casefold() == clean.casefold():
                raise ValueError("La revisión cruzada debe asignarse a otra persona")
        assignment.assignee = clean
    if priority is not None:
        if priority not in ASSIGNMENT_PRIORITIES:
            raise ValueError(f"Prioridad inválida: {priority}")
        assignment.priority = priority
    if due_at is not _UNSET:
        assignment.due_at = due_at  # type: ignore[assignment]
    if assignment_note is not _UNSET:
        value = assignment_note
        assignment.note = value.strip() if isinstance(value, str) and value.strip() else None
    now = utc_now()
    if status is not None:
        if status not in ASSIGNMENT_STATUSES:
            raise ValueError(f"Estado de asignación inválido: {status}")
        assignment.status = status
        if status == "submitted" and assignment.submitted_at is None:
            assignment.submitted_at = now
        if status == "completed":
            assignment.completed_at = now
            if assignment.submitted_at is None:
                assignment.submitted_at = now
        elif assignment.completed_at is not None:
            assignment.completed_at = None
    if outcome is not _UNSET:
        value = outcome
        if value is not None and value not in CROSS_REVIEW_OUTCOMES:
            raise ValueError(f"Resultado de revisión cruzada inválido: {value}")
        if assignment.assignment_kind != "cross_review" and value is not None:
            raise ValueError("Solo una revisión cruzada puede registrar resultado")
        assignment.outcome = value  # type: ignore[assignment]
    if assignment.assignment_kind == "cross_review" and assignment.status == "completed":
        if assignment.outcome not in CROSS_REVIEW_OUTCOMES:
            raise ValueError("Una revisión cruzada completada debe registrar resultado")
    assignment.revision += 1
    assignment.updated_by = _clean_actor(changed_by)
    assignment.updated_at = now
    session.flush()
    _append_assignment_revision(
        session,
        assignment,
        operation="update",
        changed_by=changed_by,
        note=change_note,
    )
    return assignment


def work_assignment_rows(
    session: Session,
    *,
    project_id: str,
    assignees: Iterable[str] | None = None,
    statuses: Iterable[str] | None = None,
    assignment_kinds: Iterable[str] | None = None,
    source_key: str | None = None,
    include_cancelled: bool = True,
) -> list[WorkAssignmentRow]:
    paths = _archival_paths(session, project_id)
    parent_alias = WorkAssignment.__table__.alias("parent_assignment")
    statement = (
        select(WorkAssignment, SourceRegistration, ArchivalUnit, parent_alias.c.assignee)
        .join(
            SourceRegistration,
            (SourceRegistration.project_id == WorkAssignment.project_id)
            & (SourceRegistration.source_type == WorkAssignment.source_type)
            & (SourceRegistration.source_key == WorkAssignment.source_key),
        )
        .outerjoin(ArchivalUnit, ArchivalUnit.id == SourceRegistration.archival_unit_id)
        .outerjoin(parent_alias, parent_alias.c.id == WorkAssignment.parent_assignment_id)
        .where(WorkAssignment.project_id == project_id)
    )
    if assignees:
        names = [item.strip().casefold() for item in assignees if item.strip()]
        if names:
            statement = statement.where(func.lower(WorkAssignment.assignee).in_(names))
    if statuses:
        selected = [item for item in statuses if item in ASSIGNMENT_STATUSES]
        if selected:
            statement = statement.where(WorkAssignment.status.in_(selected))
    elif not include_cancelled:
        statement = statement.where(WorkAssignment.status != "cancelled")
    if assignment_kinds:
        kinds = [item for item in assignment_kinds if item in ASSIGNMENT_KINDS]
        if kinds:
            statement = statement.where(WorkAssignment.assignment_kind.in_(kinds))
    if source_key:
        statement = statement.where(WorkAssignment.source_key == source_key)
    rows = session.execute(
        statement.order_by(
            WorkAssignment.status,
            WorkAssignment.priority.desc(),
            WorkAssignment.due_at,
            WorkAssignment.updated_at.desc(),
        )
    ).all()
    return [
        WorkAssignmentRow(
            assignment_id=assignment.id,
            project_id=assignment.project_id,
            source_type=assignment.source_type,
            source_key=assignment.source_key,
            title=unit.title if unit else assignment.source_key,
            archival_path=paths.get(unit.id, unit.title) if unit else assignment.source_key,
            page_start=assignment.page_start,
            page_end=assignment.page_end,
            assignment_kind=assignment.assignment_kind,
            assignee=assignment.assignee,
            status=assignment.status,
            priority=assignment.priority,
            due_at=assignment.due_at,
            parent_assignment_id=assignment.parent_assignment_id,
            parent_assignee=parent_assignee,
            outcome=assignment.outcome,
            note=assignment.note,
            submitted_at=assignment.submitted_at,
            completed_at=assignment.completed_at,
            created_by=assignment.created_by,
            created_at=assignment.created_at,
            updated_by=assignment.updated_by,
            updated_at=assignment.updated_at,
            revision=assignment.revision,
        )
        for assignment, _registration_row, unit, parent_assignee in rows
    ]


def workload_summary_rows(
    session: Session, *, project_id: str, now: datetime | None = None
) -> list[WorkloadSummaryRow]:
    current = now or utc_now()
    assignments = session.scalars(
        select(WorkAssignment).where(WorkAssignment.project_id == project_id)
    ).all()
    by_assignee: dict[str, list[WorkAssignment]] = {}
    for row in assignments:
        by_assignee.setdefault(row.assignee, []).append(row)
    result: list[WorkloadSummaryRow] = []
    for assignee, rows in sorted(by_assignee.items(), key=lambda item: item[0].casefold()):
        result.append(
            WorkloadSummaryRow(
                assignee=assignee,
                total=len(rows),
                planned=sum(row.status == "planned" for row in rows),
                in_progress=sum(row.status == "in_progress" for row in rows),
                submitted=sum(row.status == "submitted" for row in rows),
                blocked=sum(row.status == "blocked" for row in rows),
                completed=sum(row.status == "completed" for row in rows),
                cancelled=sum(row.status == "cancelled" for row in rows),
                primary_review=sum(row.assignment_kind == "primary_review" for row in rows),
                cross_review=sum(row.assignment_kind == "cross_review" for row in rows),
                processing=sum(row.assignment_kind == "processing" for row in rows),
                overdue=sum(
                    row.due_at is not None
                    and _as_utc(row.due_at) < _as_utc(current)
                    and row.status in ACTIVE_ASSIGNMENT_STATUSES
                    for row in rows
                ),
            )
        )
    return result


def cross_review_candidate_rows(
    session: Session, *, project_id: str
) -> list[CrossReviewCandidateRow]:
    parents = work_assignment_rows(
        session,
        project_id=project_id,
        statuses=("submitted", "completed"),
        assignment_kinds=("primary_review",),
    )
    children = session.scalars(
        select(WorkAssignment).where(
            WorkAssignment.project_id == project_id,
            WorkAssignment.assignment_kind == "cross_review",
        )
    ).all()
    by_parent: dict[str, list[WorkAssignment]] = {}
    for child in children:
        if child.parent_assignment_id:
            by_parent.setdefault(child.parent_assignment_id, []).append(child)
    return [
        CrossReviewCandidateRow(
            assignment_id=row.assignment_id,
            source_key=row.source_key,
            title=row.title,
            archival_path=row.archival_path,
            page_start=row.page_start,
            page_end=row.page_end,
            assignee=row.assignee,
            status=row.status,
            submitted_at=row.submitted_at,
            active_cross_reviews=sum(
                child.status in ACTIVE_ASSIGNMENT_STATUSES
                for child in by_parent.get(row.assignment_id, [])
            ),
            completed_cross_reviews=sum(
                child.status == "completed"
                for child in by_parent.get(row.assignment_id, [])
            ),
        )
        for row in parents
    ]


def work_assignment_revision_rows(
    session: Session, *, assignment_id: str
) -> list[WorkAssignmentRevisionRow]:
    rows = session.scalars(
        select(WorkAssignmentRevision)
        .where(WorkAssignmentRevision.assignment_id == assignment_id)
        .order_by(WorkAssignmentRevision.revision_number.desc())
    ).all()
    return [
        WorkAssignmentRevisionRow(
            revision_number=row.revision_number,
            operation=row.operation,
            snapshot=row.snapshot_json or {},
            note=row.note,
            changed_by=row.changed_by,
            changed_at=row.changed_at,
        )
        for row in rows
    ]


def assignment_assignees(session: Session, *, project_id: str) -> list[str]:
    rows = session.scalars(
        select(WorkAssignment.assignee)
        .where(WorkAssignment.project_id == project_id)
        .distinct()
        .order_by(WorkAssignment.assignee)
    ).all()
    return [str(row) for row in rows]
