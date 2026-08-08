#!/usr/bin/env python3
"""Crea un proyecto descartable pequeño para validar EXP-01."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

from archive_workbench.corpus_export import ExportProfileValues, save_export_profile
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import (
    ArchivalUnit,
    DerivativeAsset,
    DigitalObject,
    EditableObject,
    EditablePage,
    ExtractedObject,
    ExtractionPage,
    ExtractionPageSelection,
    ExtractionRegion,
    ExtractionRun,
    FileInstance,
    PreprocessingRun,
    Project,
    SourceRegistration,
    utc_now,
)
from archive_workbench.identity import new_id
from archive_workbench.project_init import initialize_project

PROJECT_ID = "exp01-visual-export-validation"
PROFILE_NAME = "EXP-01 · Texto e imágenes"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_validation_project(destination: Path, *, force: bool = False) -> dict[str, object]:
    destination = destination.expanduser().resolve()
    if destination.exists():
        if not force:
            raise SystemExit(
                f"El destino ya existe: {destination}. Elegí otra ruta o usá --force explícitamente."
            )
        shutil.rmtree(destination)

    repository_root = Path(__file__).resolve().parents[1]
    initialize_project(destination, template_root=repository_root / "config")
    decisions_path = destination / "config" / "decisions.yaml"
    decisions = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    if not isinstance(decisions, dict):
        raise RuntimeError("La plantilla decisions.yaml no contiene un objeto YAML válido.")
    decisions["project_name"] = "Validación EXP-01"
    decisions["project_id"] = PROJECT_ID
    decisions_path.write_text(
        yaml.safe_dump(decisions, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    upgrade_database(destination)

    original_relative = Path("originals/exp01_pagina.png")
    original_path = destination / original_relative
    original_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 70, 930, 170), outline="black", width=4)
    draw.text((95, 100), "ARCHIVO DE PRUEBA EXP-01", fill="black")
    draw.rectangle((90, 230, 520, 390), outline="black", width=4)
    draw.text((115, 270), "REGION OCR", fill="black")
    draw.rectangle((610, 230, 900, 540), outline="black", width=6)
    draw.line((640, 500, 860, 270), fill="black", width=8)
    draw.line((640, 280, 860, 500), fill="black", width=8)
    image.save(original_path, format="PNG")
    original_sha = _sha256(original_path)

    page_relative = Path("derived/preprocessing/exp01/page_0001_ocr.png")
    page_path = destination / page_relative
    page_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original_path, page_path)
    page_sha = _sha256(page_path)

    region_relative = Path("derived/extractions/exp01/regions/page_0001/recuadro.png")
    region_path = destination / region_relative
    region_path.parent.mkdir(parents=True, exist_ok=True)
    image.crop((90, 230, 520, 390)).save(region_path, format="PNG")

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            project = Project(
                id=PROJECT_ID,
                name="Validación EXP-01",
                decisions_schema_version="1.0",
                decisions_json={},
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            unit = ArchivalUnit(
                id=new_id(),
                project_id=PROJECT_ID,
                level_key="documento",
                reference_code="EXP01-001",
                title="Documento de validación visual",
                created_by="validation",
                updated_by="validation",
            )
            digital = DigitalObject(
                id=new_id(),
                project_id=PROJECT_ID,
                media_type="image",
                original_filename=original_path.name,
                sha256=original_sha,
                byte_size=original_path.stat().st_size,
                page_count=1,
            )
            session.add(project)
            session.flush()
            session.add_all([unit, digital])
            session.flush()
            session.add(
                FileInstance(
                    id=new_id(),
                    digital_object_id=digital.id,
                    storage_root="project",
                    relative_path=original_relative.as_posix(),
                    presence="present",
                    byte_size_seen=original_path.stat().st_size,
                    mtime_ns=original_path.stat().st_mtime_ns,
                    last_seen_at=utc_now(),
                    verified_sha256=original_sha,
                )
            )
            registration = SourceRegistration(
                id=new_id(),
                project_id=PROJECT_ID,
                source_type="validation",
                source_key="exp01_visual",
                digital_object_id=digital.id,
                archival_unit_id=unit.id,
                source_payload_json={"purpose": "EXP-01 validation"},
                registered_by="validation",
            )
            session.add(registration)
            session.flush()

            preprocessing = PreprocessingRun(
                id=new_id(),
                digital_object_id=digital.id,
                source_sha256=original_sha,
                profile_key="exp01-validation",
                options_json={},
                options_hash="d" * 64,
                backend="validation",
                status="completed",
                is_current=True,
                output_root="derived/preprocessing/exp01",
                warnings_json=[],
            )
            session.add(preprocessing)
            session.flush()
            asset = DerivativeAsset(
                id=new_id(),
                preprocessing_run_id=preprocessing.id,
                digital_object_id=digital.id,
                page_number=1,
                kind="ocr",
                relative_path=page_relative.as_posix(),
                mime_type="image/png",
                sha256=page_sha,
                byte_size=page_path.stat().st_size,
                width=1000,
                height=700,
                dpi=150,
                rotation_applied=0,
                analysis_json={},
                transformations_json={},
                backend="validation",
            )
            session.add(asset)
            session.flush()

            run = ExtractionRun(
                id=new_id(),
                digital_object_id=digital.id,
                preprocessing_run_id=preprocessing.id,
                profile_key="exp01-validation",
                engine="validation",
                source_sha256=original_sha,
                options_json={},
                options_hash="e" * 64,
                status="completed",
                is_current=True,
                total_pages=1,
                total_objects=1,
                total_paragraphs=1,
                total_characters=72,
                warnings_json=[],
                created_by="validation",
            )
            session.add(run)
            session.flush()
            extraction_page = ExtractionPage(
                id=new_id(),
                extraction_run_id=run.id,
                page_number=1,
                source_asset_id=asset.id,
                object_count=1,
                character_count=72,
                status="completed",
            )
            session.add(extraction_page)
            session.flush()
            original_object = ExtractedObject(
                id=new_id(),
                origin_id=new_id(),
                extraction_run_id=run.id,
                digital_object_id=digital.id,
                page_number=1,
                order_index=0,
                object_type="paragraph",
                original_text="Texto OCR de prueba para la exportación de imágenes y contexto.",
                geometry_json=[
                    {
                        "page": 1,
                        "polygon": [[0.07, 0.1], [0.93, 0.1], [0.93, 0.24], [0.07, 0.24]],
                        "coordinate_space": "normalized",
                    }
                ],
                attributes_json={},
            )
            session.add(original_object)
            session.flush()

            editable_page = EditablePage(
                id=new_id(),
                digital_object_id=digital.id,
                page_number=1,
                source_extraction_run_id=run.id,
                source_extraction_page_id=extraction_page.id,
                status="active",
                review_status="approved",
                bootstrapped_by="validation",
            )
            session.add(editable_page)
            session.flush()
            selection = ExtractionPageSelection(
                id=new_id(),
                digital_object_id=digital.id,
                page_number=1,
                extraction_run_id=run.id,
                extraction_page_id=extraction_page.id,
                selected_by="validation",
            )
            session.add(selection)
            session.flush()

            primary_object = EditableObject(
                id=new_id(),
                editable_page_id=editable_page.id,
                digital_object_id=digital.id,
                page_number=1,
                source_extracted_object_id=original_object.id,
                source_origin_id=original_object.origin_id,
                current_text="Texto principal corregido para validar la exportación de texto e imágenes.",
                current_object_type="paragraph",
                current_order_index=0,
                current_geometry_json=original_object.geometry_json,
                current_attributes_json={},
                lifecycle_status="active",
                review_status="approved",
                revision_number=1,
                created_by="validation",
                updated_by="validation",
            )
            figure_object = EditableObject(
                id=new_id(),
                editable_page_id=editable_page.id,
                digital_object_id=digital.id,
                page_number=1,
                source_extracted_object_id=None,
                source_origin_id=None,
                current_text="",
                current_object_type="figure",
                current_order_index=1,
                current_geometry_json=[
                    {
                        "page": 1,
                        "polygon": [[0.61, 0.33], [0.90, 0.33], [0.90, 0.77], [0.61, 0.77]],
                        "coordinate_space": "normalized",
                    }
                ],
                current_attributes_json={"label": "Figura de control"},
                lifecycle_status="active",
                review_status="approved",
                revision_number=1,
                created_by="validation",
                updated_by="validation",
            )
            context_object = EditableObject(
                id=new_id(),
                editable_page_id=editable_page.id,
                digital_object_id=digital.id,
                page_number=1,
                source_extracted_object_id=None,
                source_origin_id=None,
                current_text="Este texto no entra al perfil principal y debe aparecer solamente como contexto.",
                current_object_type="paragraph",
                current_order_index=2,
                current_geometry_json=[],
                current_attributes_json={},
                lifecycle_status="active",
                review_status="needs_review",
                revision_number=1,
                created_by="validation",
                updated_by="validation",
            )
            session.add_all([primary_object, figure_object, context_object])
            session.add(
                ExtractionRegion(
                    id=new_id(),
                    extraction_run_id=run.id,
                    page_number=1,
                    region_key="recuadro",
                    label="Recuadro OCR",
                    mode="ocr",
                    object_type="paragraph",
                    reading_order=0,
                    bbox_json={"x": 0.09, "y": 0.33, "width": 0.43, "height": 0.23},
                    profile_json={"semantic_role": "sidebar"},
                    crop_path=region_relative.as_posix(),
                    object_count=1,
                    character_count=20,
                    status="completed",
                )
            )
            session.flush()

            profile = save_export_profile(
                session,
                project_id=PROJECT_ID,
                values=ExportProfileValues(
                    name=PROFILE_NAME,
                    description="Perfil controlado para validar EXP-01.",
                    aggregation_level="object",
                    text_policy="corrected_fallback_original",
                    output_format="jsonl",
                    include_review_statuses=("approved",),
                    include_page_review_statuses=("approved",),
                ),
                changed_by="validation",
                quality_scope_source="api",
            )
            profile_id = profile.id
            session.flush()
    finally:
        engine.dispose()

    payload = {
        "project_id": PROJECT_ID,
        "project_root": str(destination),
        "revision": current_revision(destination),
        "profile_id": profile_id,
        "profile_name": PROFILE_NAME,
        "source_key": "exp01_visual",
        "original_relative_path": original_relative.as_posix(),
        "original_sha256": original_sha,
        "page_asset_relative_path": page_relative.as_posix(),
        "page_asset_sha256": page_sha,
        "primary_object_id": primary_object.id,
        "figure_object_id": figure_object.id,
        "context_object_id": context_object.id,
        "expected": {
            "records": 1,
            "pages": 1,
            "regions": 1,
            "figures": 1,
            "context_objects": 2,
        },
    }
    validation_path = destination / "exports" / "exp01_validation.json"
    validation_path.parent.mkdir(parents=True, exist_ok=True)
    validation_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload["validation_path"] = str(validation_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = create_validation_project(args.destination, force=args.force)
    print(f"Proyecto de validación: {result['project_root']}")
    print(f"Perfil: {result['profile_name']}")
    print(f"Revisión: {result['revision']}")
    print(f"SHA-256 original: {result['original_sha256']}")
    print(f"SHA-256 página fuente: {result['page_asset_sha256']}")
    print(f"Datos de validación: {result['validation_path']}")
    print("No se usó ni modificó project_data.")


if __name__ == "__main__":
    main()
