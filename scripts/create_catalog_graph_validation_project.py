#!/usr/bin/env python3
"""Crea un proyecto descartable para validar CAT-02 y GRAPH-02 sin tocar project_data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import fitz
import yaml

from archive_workbench.authorities import create_authority, create_mention
from archive_workbench.catalog import ensure_project
from archive_workbench.catalog_management import create_archival_unit, register_local_file
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import (
    DigitalObject,
    DocumentPart,
    EditableObject,
    EditablePage,
    ExtractedObject,
    ExtractionPage,
    ExtractionRun,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.graph import build_graph, export_graph, graph_consistency_issues
from archive_workbench.identity import new_id
from archive_workbench.project_init import initialize_project
from archive_workbench.relations import create_entity_relation


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page_1 = document.new_page(width=595, height=842)
    page_1.insert_text(
        (60, 90),
        "La Dirección de Inteligencia produjo este informe sobre Persona Investigada.",
    )
    page_2 = document.new_page(width=595, height=842)
    page_2.insert_text(
        (60, 90),
        "El Archivo Provincial recibió el documento y registró su transferencia.",
    )
    document.save(path)
    document.close()


def _create_editable_object(
    session,
    *,
    run: ExtractionRun,
    digital: DigitalObject,
    page_number: int,
    text: str,
    document_part_id: str | None,
) -> EditableObject:
    extraction_page = ExtractionPage(
        id=new_id(),
        extraction_run_id=run.id,
        page_number=page_number,
        object_count=1,
        character_count=len(text),
        status="completed",
    )
    session.add(extraction_page)
    session.flush()
    extracted = ExtractedObject(
        id=new_id(),
        origin_id=new_id(),
        extraction_run_id=run.id,
        digital_object_id=digital.id,
        page_number=page_number,
        order_index=0,
        object_type="paragraph",
        original_text=text,
        geometry_json=[],
        attributes_json={"validation": "CAT-02/GRAPH-02"},
    )
    session.add(extracted)
    session.flush()
    editable_page = EditablePage(
        id=new_id(),
        digital_object_id=digital.id,
        page_number=page_number,
        source_extraction_run_id=run.id,
        source_extraction_page_id=extraction_page.id,
        status="active",
        review_status="approved",
        review_note="Página controlada para CAT-02 y GRAPH-02.",
        reviewed_by="validation_script",
        reviewed_at=datetime.now(timezone.utc),
        bootstrapped_by="validation_script",
    )
    session.add(editable_page)
    session.flush()
    editable = EditableObject(
        id=new_id(),
        editable_page_id=editable_page.id,
        digital_object_id=digital.id,
        page_number=page_number,
        document_part_id=document_part_id,
        source_extracted_object_id=extracted.id,
        source_origin_id=extracted.origin_id,
        current_text=text,
        current_object_type="paragraph",
        current_order_index=0,
        current_geometry_json=[],
        current_attributes_json={"validation": "CAT-02/GRAPH-02"},
        lifecycle_status="active",
        review_status="approved",
        revision_number=1,
        created_by="validation_script",
        updated_by="validation_script",
    )
    session.add(editable)
    session.flush()
    return editable


def create_validation_project(destination: Path) -> dict[str, object]:
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise SystemExit(
            f"El destino ya existe: {destination}. Elegí otra ruta; el script no elimina ni reemplaza proyectos."
        )

    repository_root = Path(__file__).resolve().parents[1]
    initialize_project(destination, template_root=repository_root / "config")
    decisions_path = destination / "config" / "decisions.yaml"
    decisions_payload = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    decisions_payload["project_name"] = "Proyecto de validación CAT-02 y GRAPH-02"
    decisions_payload["project_id"] = "cat02_graph02_validation"
    decisions_path.write_text(
        yaml.safe_dump(decisions_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    source_path = destination / "originals" / "informe_controlado.pdf"
    _write_pdf(source_path)
    upgrade_database(destination)
    decisions = load_decisions(decisions_path)

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            ensure_project(session, decisions)
            archive = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo de validación",
                reference_code="VAL",
                created_by="validation_script",
            )
            fund = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=archive.id,
                level_key="fondo",
                title="Fondo institucional controlado",
                reference_code="VAL-FI",
                created_by="validation_script",
            )
            series = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=fund.id,
                level_key="serie",
                title="Informes de inteligencia",
                reference_code="VAL-FI-S1",
                created_by="validation_script",
            )
            unit = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=series.id,
                level_key="documento",
                title="Informe controlado de dos páginas",
                reference_code="VAL-FI-S1-D1",
                created_by="validation_script",
            )
            registration = register_local_file(
                session,
                project_root=destination,
                project_id=decisions.project_id,
                archival_unit_id=unit.id,
                relative_path="originals/informe_controlado.pdf",
                relation_type="represents",
                registered_by="validation_script",
            )
            digital = session.get(DigitalObject, registration.digital_object_id)
            assert digital is not None
            part = DocumentPart(
                id=new_id(),
                digital_object_id=digital.id,
                part_key="parte-informe",
                title="Informe principal",
                part_type="document",
                page_start=1,
                page_end=1,
                page_sequence_json=[1],
                status="confirmed",
                notes="Parte controlada para distinguir documento y contenido interno.",
                created_by="validation_script",
            )
            session.add(part)
            session.flush()

            run = ExtractionRun(
                id=new_id(),
                digital_object_id=digital.id,
                profile_key="validation",
                engine="tesseract_tsv",
                source_sha256=digital.sha256,
                options_json={"validation": "CAT-02/GRAPH-02"},
                options_hash=hashlib.sha256(b"CAT-02/GRAPH-02").hexdigest(),
                status="completed",
                is_current=True,
                total_pages=2,
                total_objects=2,
                total_paragraphs=2,
                total_characters=155,
                warnings_json=[],
                created_by="validation_script",
            )
            session.add(run)
            session.flush()
            part_text = (
                "La Dirección de Inteligencia produjo este informe sobre Persona Investigada."
            )
            document_text = (
                "El Archivo Provincial recibió el documento y registró su transferencia."
            )
            part_object = _create_editable_object(
                session,
                run=run,
                digital=digital,
                page_number=1,
                text=part_text,
                document_part_id=part.id,
            )
            document_object = _create_editable_object(
                session,
                run=run,
                digital=digital,
                page_number=2,
                text=document_text,
                document_part_id=None,
            )

            intelligence = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Dirección de Inteligencia",
                description="Autoridad controlada que desempeña roles en períodos distintos.",
                created_by="validation_script",
                review_status="approved",
            )
            person = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="person",
                preferred_name="Persona Investigada",
                created_by="validation_script",
                review_status="approved",
            )
            provincial_archive = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Archivo Provincial",
                created_by="validation_script",
                review_status="approved",
            )

            create_mention(
                session,
                object_id=part_object.id,
                mention_text="Dirección de Inteligencia",
                authority_id=intelligence.id,
                created_by="validation_script",
            )
            create_mention(
                session,
                object_id=part_object.id,
                mention_text="Persona Investigada",
                authority_id=person.id,
                created_by="validation_script",
            )
            create_mention(
                session,
                object_id=document_object.id,
                mention_text="Archivo Provincial",
                authority_id=provincial_archive.id,
                created_by="validation_script",
            )

            analytical = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=person.id,
                relation_kind="analytical",
                relation_label="fue investigada por",
                target_kind="entity",
                target_id=intelligence.id,
                evidence_note="Informe controlado, página 1.",
                provenance_note="Lectura analítica del equipo de validación.",
                temporal_expression="1975",
                created_by="validation_script",
                review_status="approved",
            )
            producer = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=intelligence.id,
                relation_kind="producer",
                relation_label="texto libre descartado",
                target_kind="archival_unit",
                target_id=unit.id,
                evidence_note="Membrete de la primera página.",
                provenance_note="Descripción archivística de control VAL-FI-S1-D1.",
                temporal_expression="1974 - 1976",
                temporal_note="Período de producción documentado.",
                created_by="validation_script",
                review_status="approved",
            )
            former_manager = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=intelligence.id,
                relation_kind="manager",
                relation_label="otro texto libre descartado",
                target_kind="archival_unit",
                target_id=unit.id,
                evidence_note="Acta de transferencia de 1977.",
                provenance_note="Expediente de transferencia VAL-1977-01.",
                temporal_expression="1977 - 1983",
                temporal_note="Gestión anterior conservada como vínculo histórico.",
                created_by="validation_script",
                review_status="approved",
            )
            current_manager = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=provincial_archive.id,
                relation_kind="manager",
                relation_label="texto libre descartado",
                target_kind="archival_unit",
                target_id=unit.id,
                evidence_note="Resolución de transferencia definitiva.",
                provenance_note="Resolución provincial VAL-1984-02.",
                temporal_expression="desde 1984",
                temporal_note="Gestión vigente en el corpus controlado.",
                created_by="validation_script",
                review_status="approved",
            )

            view = build_graph(
                session,
                project_id=decisions.project_id,
                max_nodes=100,
            )
            issues = graph_consistency_issues(session, project_id=decisions.project_id)
            expected_edge_types = {
                "hierarchy",
                "document",
                "part",
                "mention",
                "analytical",
                "producer",
                "manager",
            }
            actual_edge_types = {edge.edge_type for edge in view.edges}
            missing_edge_types = sorted(expected_edge_types - actual_edge_types)
            if missing_edge_types:
                raise RuntimeError(
                    "La validación no produjo las capas esperadas: "
                    + ", ".join(missing_edge_types)
                )
            error_issues = [issue for issue in issues if issue.severity == "error"]
            if error_issues:
                raise RuntimeError(
                    "La validación produjo errores de consistencia: "
                    + "; ".join(issue.code for issue in error_issues)
                )

            validation_dir = destination / "validation"
            validation_dir.mkdir(parents=True, exist_ok=True)
            graph_paths = export_graph(
                view,
                output_dir=validation_dir / "graph_exports",
                issues=issues,
            )
            manifest = {
                "version": "0.77.0",
                "database_revision": current_revision(destination),
                "project_root": str(destination),
                "project_name": decisions.project_name,
                "project_id": decisions.project_id,
                "project_data_touched": False,
                "archival_unit_id": unit.id,
                "digital_object_id": digital.id,
                "document_part_id": part.id,
                "source_key": registration.source_key,
                "authority_ids": {
                    "producer_and_former_manager": intelligence.id,
                    "person": person.id,
                    "current_manager": provincial_archive.id,
                },
                "relation_ids": {
                    "analytical": analytical.id,
                    "producer": producer.id,
                    "former_manager": former_manager.id,
                    "current_manager": current_manager.id,
                },
                "expected_edge_types": sorted(expected_edge_types),
                "actual_edge_types": sorted(actual_edge_types),
                "node_kinds": sorted({node.kind for node in view.nodes}),
                "node_count": len(view.nodes),
                "edge_count": len(view.edges),
                "consistency_errors": 0,
                "graph_exports": [str(path) for path in graph_paths],
            }
            manifest_path = validation_dir / "manifest.json"
            _write_json(manifest_path, manifest)
            manifest["manifest"] = str(manifest_path)
            return manifest
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="Ruta nueva fuera del repositorio para el proyecto descartable.",
    )
    args = parser.parse_args()
    manifest = create_validation_project(args.destination)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
