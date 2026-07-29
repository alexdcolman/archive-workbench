from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from archive_workbench.contracts.common import ContractModel


class PlannedDocumentPart(ContractModel):
    part_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1)
    part_type: str = "document"
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    page_sequence: list[int] = Field(default_factory=list)
    status: Literal["provisional", "confirmed"] = "provisional"
    notes: str | None = None

    @model_validator(mode="after")
    def validate_pages(self) -> "PlannedDocumentPart":
        has_range = self.page_start is not None or self.page_end is not None
        if has_range and (self.page_start is None or self.page_end is None):
            raise ValueError("page_start y page_end deben aparecer juntos")
        if self.page_start is not None and self.page_end is not None:
            if self.page_end < self.page_start:
                raise ValueError("page_end no puede ser menor que page_start")
        if not has_range and not self.page_sequence:
            raise ValueError("La parte debe indicar un rango o page_sequence")
        if len(set(self.page_sequence)) != len(self.page_sequence):
            raise ValueError("page_sequence no debe contener páginas duplicadas")
        if any(page < 1 for page in self.page_sequence):
            raise ValueError("page_sequence solo admite páginas mayores o iguales a 1")
        if has_range and self.page_sequence:
            assert self.page_start is not None and self.page_end is not None
            expected = set(range(self.page_start, self.page_end + 1))
            if set(self.page_sequence) != expected:
                raise ValueError(
                    "page_sequence debe contener exactamente las páginas del rango físico"
                )
        return self

    @property
    def pages(self) -> set[int]:
        if self.page_sequence:
            return set(self.page_sequence)
        assert self.page_start is not None and self.page_end is not None
        return set(range(self.page_start, self.page_end + 1))

    @property
    def logical_pages(self) -> list[int]:
        if self.page_sequence:
            return list(self.page_sequence)
        assert self.page_start is not None and self.page_end is not None
        return list(range(self.page_start, self.page_end + 1))

    @property
    def physical_page_start(self) -> int:
        return min(self.pages)

    @property
    def physical_page_end(self) -> int:
        return max(self.pages)


class PagePlanAssignment(ContractModel):
    assignment_key: str = Field(min_length=1, max_length=120)
    pages: list[int] = Field(default_factory=list)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    mode: Literal["pending", "ocr", "regions", "manual", "skip"] = "pending"
    profile: str | None = None
    region_template: str | None = None
    part_key: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_assignment(self) -> "PagePlanAssignment":
        has_list = bool(self.pages)
        has_range = self.page_start is not None or self.page_end is not None
        if has_list and has_range:
            raise ValueError("Use pages o page_start/page_end, no ambos")
        if not has_list and not has_range:
            raise ValueError("La asignación debe indicar páginas")
        if has_range:
            if self.page_start is None or self.page_end is None:
                raise ValueError("page_start y page_end deben aparecer juntos")
            if self.page_end < self.page_start:
                raise ValueError("page_end no puede ser menor que page_start")
        if len(set(self.pages)) != len(self.pages):
            raise ValueError("La lista pages no debe contener duplicados")
        if any(page < 1 for page in self.pages):
            raise ValueError("Las páginas deben ser mayores o iguales a 1")
        if self.mode == "ocr" and not self.profile:
            raise ValueError("Las asignaciones OCR requieren profile")
        if self.mode == "regions" and not self.region_template:
            raise ValueError("Las asignaciones regions requieren region_template")
        if self.mode != "ocr" and self.profile:
            raise ValueError("profile solo corresponde al modo ocr")
        if self.mode != "regions" and self.region_template:
            raise ValueError("region_template solo corresponde al modo regions")
        return self

    @property
    def expanded_pages(self) -> set[int]:
        if self.pages:
            return set(self.pages)
        assert self.page_start is not None and self.page_end is not None
        return set(range(self.page_start, self.page_end + 1))


class DocumentProcessingPlan(ContractModel):
    schema_version: str = "1.1"
    plan_key: str = Field(min_length=1, max_length=120)
    source_key: str = Field(min_length=1)
    expected_page_count: int = Field(ge=1)
    status: Literal["draft", "ready"] = "draft"
    benchmark_pages: list[int] = Field(default_factory=list)
    parts: list[PlannedDocumentPart] = Field(default_factory=list)
    assignments: list[PagePlanAssignment] = Field(default_factory=list)
    created_by: str = "local_user"
    notes: str | None = None

    @model_validator(mode="after")
    def validate_plan(self) -> "DocumentProcessingPlan":
        if len(set(self.benchmark_pages)) != len(self.benchmark_pages):
            raise ValueError("benchmark_pages no debe contener duplicados")
        if any(page < 1 or page > self.expected_page_count for page in self.benchmark_pages):
            raise ValueError("benchmark_pages contiene páginas fuera del documento")

        part_keys: set[str] = set()
        part_pages: dict[str, set[int]] = {}
        occupied_parts: set[int] = set()
        for part in self.parts:
            if part.part_key in part_keys:
                raise ValueError(f"part_key repetido: {part.part_key}")
            part_keys.add(part.part_key)
            pages = part.pages
            if max(pages) > self.expected_page_count:
                raise ValueError(f"La parte {part.part_key} excede el total de páginas")
            overlap = occupied_parts & pages
            if overlap:
                raise ValueError(
                    f"Las partes documentales se superponen en páginas: {sorted(overlap)}"
                )
            occupied_parts |= pages
            part_pages[part.part_key] = pages

        assignment_keys: set[str] = set()
        occupied_assignments: set[int] = set()
        for assignment in self.assignments:
            if assignment.assignment_key in assignment_keys:
                raise ValueError(f"assignment_key repetido: {assignment.assignment_key}")
            assignment_keys.add(assignment.assignment_key)
            pages = assignment.expanded_pages
            if max(pages) > self.expected_page_count:
                raise ValueError(
                    f"La asignación {assignment.assignment_key} excede el total de páginas"
                )
            overlap = occupied_assignments & pages
            if overlap:
                raise ValueError(
                    f"Las asignaciones se superponen en páginas: {sorted(overlap)}"
                )
            occupied_assignments |= pages
            if assignment.part_key and assignment.part_key not in part_keys:
                raise ValueError(
                    f"La asignación {assignment.assignment_key} referencia una parte inexistente"
                )
            if assignment.part_key and not pages <= part_pages[assignment.part_key]:
                outside = sorted(pages - part_pages[assignment.part_key])
                raise ValueError(
                    f"La asignación {assignment.assignment_key} incluye páginas fuera de la parte "
                    f"{assignment.part_key}: {outside}"
                )

        if self.status == "ready":
            pending = [a.assignment_key for a in self.assignments if a.mode == "pending"]
            if pending:
                raise ValueError("Un plan ready no puede contener asignaciones pending")
            expected = set(range(1, self.expected_page_count + 1))
            missing = sorted(expected - occupied_assignments)
            if missing:
                raise ValueError(f"El plan ready deja páginas sin asignar: {missing}")
        return self

    @property
    def assigned_pages(self) -> set[int]:
        pages: set[int] = set()
        for assignment in self.assignments:
            pages |= assignment.expanded_pages
        return pages

    def resolve_path(self, project_root: Path, value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else project_root / candidate
