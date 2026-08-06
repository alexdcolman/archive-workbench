from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from archive_workbench.contracts.regions import (
    NormalizedRegionBox,
    RegionDefinition,
    RegionOcrOptions,
    REGION_SEMANTIC_OBJECT_TYPES,
    RegionSemanticRole,
    RegionTemplate,
)
from archive_workbench.extraction import _current_assets
from archive_workbench.region_extraction import _registration_for_source, load_region_template


REGION_ROLE_LABELS: dict[str, str] = {
    "body_text": "Texto principal",
    "cover": "Portada",
    "page_header": "Encabezado de página",
    "page_footer": "Pie de página",
    "page_number": "Número de página",
    "stamp": "Sello",
    "signature": "Firma",
    "handwriting": "Manuscrito",
    "illustration": "Ilustración o imagen",
    "preprinted": "Elemento preimpreso",
}

REGION_ROLE_OBJECT_TYPES = REGION_SEMANTIC_OBJECT_TYPES

REGION_ROLE_DEFAULT_MODE: dict[str, str] = {
    "body_text": "ocr",
    "cover": "ocr",
    "page_header": "ocr",
    "page_footer": "ocr",
    "page_number": "ocr",
    "stamp": "manual",
    "signature": "manual",
    "handwriting": "manual",
    "illustration": "manual",
    "preprinted": "manual",
}


@dataclass(slots=True)
class RegionalPageAsset:
    page: int
    preview_relative_path: str
    ocr_relative_path: str
    width: int
    height: int


def regional_page_assets(session: Session, *, source_key: str) -> list[RegionalPageAsset]:
    _registration, digital, _unit = _registration_for_source(session, source_key)
    _run, ocr_assets, preview_assets = _current_assets(session, digital.id)
    previews = {item.page_number: item for item in preview_assets}
    output: list[RegionalPageAsset] = []
    for ocr_asset in ocr_assets:
        preview = previews.get(ocr_asset.page_number) or ocr_asset
        output.append(
            RegionalPageAsset(
                page=ocr_asset.page_number,
                preview_relative_path=preview.relative_path,
                ocr_relative_path=ocr_asset.relative_path,
                width=preview.width,
                height=preview.height,
            )
        )
    return output


def region_role_label(role: str | None) -> str:
    return REGION_ROLE_LABELS.get(role or "", role or "Sin clasificación")


def object_type_for_role(role: RegionSemanticRole | str) -> str:
    try:
        return REGION_ROLE_OBJECT_TYPES[str(role)]
    except KeyError as exc:
        raise ValueError(f"Clasificación regional desconocida: {role}") from exc


def draft_from_region(region: RegionDefinition) -> dict[str, Any]:
    return {
        "region_key": region.region_key,
        "label": region.label,
        "page": region.page,
        "reading_order": region.reading_order,
        "bbox": region.bbox.model_dump(mode="json"),
        "mode": region.mode,
        "semantic_role": region.semantic_role or "body_text",
        "hidden_by_default": region.hidden_by_default,
        "ocr": region.ocr.model_dump(mode="json") if region.ocr else None,
        "initial_text": region.initial_text,
        "note": region.note,
    }


def region_from_draft(draft: dict[str, Any], *, fallback_index: int) -> RegionDefinition:
    role = str(draft.get("semantic_role") or "body_text")
    mode = str(draft.get("mode") or REGION_ROLE_DEFAULT_MODE.get(role, "manual"))
    ocr_payload = draft.get("ocr")
    if mode == "ocr" and not ocr_payload:
        ocr_payload = RegionOcrOptions().model_dump(mode="json")
    if mode == "manual":
        ocr_payload = None
    return RegionDefinition(
        region_key=str(draft.get("region_key") or f"region_{fallback_index:03d}"),
        label=str(draft.get("label") or region_role_label(role)),
        page=int(draft["page"]),
        reading_order=int(draft.get("reading_order", fallback_index * 10)),
        bbox=NormalizedRegionBox.model_validate(draft["bbox"]),
        mode=mode,
        object_type=object_type_for_role(role),
        semantic_role=role,
        hidden_by_default=bool(draft.get("hidden_by_default", False)),
        ocr=RegionOcrOptions.model_validate(ocr_payload) if ocr_payload else None,
        initial_text=str(draft.get("initial_text") or ""),
        note=(str(draft["note"]).strip() if draft.get("note") else None),
    )


def template_from_drafts(
    *,
    source_key: str,
    drafts: list[dict[str, Any]],
    template_key: str,
    profile_key: str = "regional_visual_v1",
) -> RegionTemplate:
    if not drafts:
        raise ValueError("Debe definir al menos una zona regional.")
    regions = [
        region_from_draft(item, fallback_index=index)
        for index, item in enumerate(drafts, start=1)
    ]
    used_by_page: dict[int, set[int]] = {}
    normalized: list[RegionDefinition] = []
    for region in regions:
        used_orders = used_by_page.setdefault(region.page, set())
        reading_order = region.reading_order
        if reading_order in used_orders:
            reading_order = 10
            while reading_order in used_orders:
                reading_order += 10
            region = region.model_copy(update={"reading_order": reading_order})
        used_orders.add(region.reading_order)
        normalized.append(region)
    normalized.sort(key=lambda row: (row.page, row.reading_order))
    return RegionTemplate(
        schema_version="1.1",
        template_key=template_key,
        profile_key=profile_key,
        source_key=source_key,
        description="Zonas definidas visualmente desde Archive Workbench.",
        regions=normalized,
    )


def available_region_templates(project_root: str | Path, *, source_key: str) -> list[Path]:
    root = Path(project_root) / "config" / "regions"
    if not root.is_dir():
        return []
    output: list[Path] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            template = load_region_template(path)
        except (OSError, ValueError):
            continue
        if template.source_key == source_key:
            output.append(path)
    return output


def write_region_template(path: str | Path, template: RegionTemplate) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(
            template.model_dump(mode="json", exclude_none=True),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return destination
