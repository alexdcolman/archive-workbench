#!/usr/bin/env python3
"""Crea una base descartable para validar OCR-01C sin tocar project_data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import fitz
from sqlalchemy import select
import yaml

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.test_corpus import TestCorpus
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import (
    DigitalObject,
    EditableObject,
    EditablePage,
    ExtractedObject,
    ExtractionPage,
    ExtractionPageSelection,
    ExtractionRun,
    SourceRegistration,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import bootstrap_editable_layer
from archive_workbench.identity import new_id, sha256_file
from archive_workbench.layout_structure import layout_proposal, layout_structure
from archive_workbench.project_init import initialize_project
from archive_workbench.review import review_page_view
from archive_workbench.version import __version__


def _write_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((45, 45), "VALIDACIÓN OCR-01C: DOS COLUMNAS", fontsize=15)
    left_rows = [
        (105, "Primera parte de un párrafo"),
        (135, "continuación y cierre."),
        (210, "Segundo bloque izquierdo."),
    ]
    right_rows = [
        (105, "Texto derecho superior."),
        (180, "Texto duplicado."),
        (180, "Texto duplicado."),
        (250, "Texto derecho inferior."),
    ]
    for y, text in left_rows:
        page.insert_text((55, y), text, fontsize=11)
    for index, (y, text) in enumerate(right_rows):
        x = 330 + (2 if index == 2 else 0)
        page.insert_text((x, y + (1 if index == 2 else 0)), text, fontsize=11)
    document.save(path)
    document.close()


def _geometry(left: float, top: float, right: float, bottom: float) -> list[dict]:
    return [
        {
            "page": 1,
            "polygon": [[left, top], [right, top], [right, bottom], [left, bottom]],
            "coordinate_space": "normalized",
        }
    ]


def _corpus() -> TestCorpus:
    return TestCorpus.model_validate(
        {
            "corpus_name": "Validación OCR-01C",
            "created_by": "validation_script",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "layout_dos_columnas",
                    "local_path": "corpus/layout/dos_columnas.pdf",
                    "short_description": "Página controlada con dos columnas, fragmentación y duplicación",
                    "archival_location": {
                        "fondo": "Validación OCR-01C",
                        "serie": "Layout",
                        "documento": "Dos columnas controladas",
                    },
                    "input_characteristics": {
                        "format": "pdf",
                        "scanned": True,
                        "digital_text_layer": False,
                        "multipage_tiff": False,
                        "poor_contrast": False,
                        "skewed_pages": False,
                        "landscape_pages": False,
                        "mixed_orientations": False,
                        "typewritten": True,
                        "handwritten_notes": False,
                        "stamps": False,
                        "tables_or_forms": False,
                        "multiple_internal_documents": False,
                    },
                    "expected_extraction": {"minimum_page_coverage_percent": 95},
                }
            ],
        }
    )


def _seed_extraction(session) -> str:
    registration = session.scalar(
        select(SourceRegistration).where(
            SourceRegistration.source_key == "layout_dos_columnas"
        )
    )
    if registration is None or registration.digital_object_id is None:
        raise RuntimeError("No se registró el objeto digital de validación")
    digital = session.get(DigitalObject, registration.digital_object_id)
    if digital is None:
        raise RuntimeError("No se encontró el objeto digital de validación")

    # El orden OCR inicial alterna columnas y deja el duplicado activo.
    definitions = [
        ("right_top", "Texto derecho superior.", _geometry(0.56, 0.115, 0.91, 0.145)),
        ("left_fragment_1", "Primera parte de un párrafo", _geometry(0.08, 0.115, 0.43, 0.145)),
        ("right_duplicate_1", "Texto duplicado.", _geometry(0.56, 0.205, 0.88, 0.235)),
        ("left_fragment_2", "continuación y cierre.", _geometry(0.08, 0.148, 0.43, 0.178)),
        ("right_duplicate_2", "Texto duplicado.", _geometry(0.562, 0.206, 0.878, 0.234)),
        ("left_second", "Segundo bloque izquierdo.", _geometry(0.08, 0.245, 0.43, 0.275)),
        ("right_bottom", "Texto derecho inferior.", _geometry(0.56, 0.295, 0.91, 0.325)),
    ]

    run = ExtractionRun(
        id=new_id(),
        digital_object_id=digital.id,
        profile_key="ocr01c_validation",
        engine="controlled_fixture",
        engine_version="1",
        source_sha256=digital.sha256,
        options_json={"fixture": "ocr01c"},
        options_hash="4" * 64,
        status="completed",
        is_current=True,
        created_by="validation_script",
        total_pages=1,
        total_objects=len(definitions),
        total_paragraphs=len(definitions),
        total_characters=sum(len(item[1]) for item in definitions),
        warnings_json=[],
        quality_status="needs_review",
    )
    session.add(run)
    session.flush()
    extraction_page = ExtractionPage(
        id=new_id(),
        extraction_run_id=run.id,
        page_number=1,
        object_count=len(definitions),
        character_count=sum(len(item[1]) for item in definitions),
        status="completed",
    )
    session.add(extraction_page)
    session.flush()

    for order_index, (key, text, geometry) in enumerate(definitions):
        session.add(
            ExtractedObject(
                id=new_id(),
                origin_id=new_id(),
                extraction_run_id=run.id,
                digital_object_id=digital.id,
                page_number=1,
                order_index=order_index,
                object_type="paragraph",
                original_text=text,
                geometry_json=geometry,
                attributes_json={"validation_key": key},
            )
        )
    session.add(
        ExtractionPageSelection(
            id=new_id(),
            digital_object_id=digital.id,
            page_number=1,
            extraction_run_id=run.id,
            extraction_page_id=extraction_page.id,
            selected_by="validation_script",
            note="Selección controlada para validar OCR-01C",
        )
    )
    session.flush()
    return digital.id


def create_validation_project(destination: Path) -> dict[str, object]:
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise SystemExit(
            f"El destino ya existe: {destination}. Elegí otra ruta; "
            "el script no elimina ni reemplaza proyectos."
        )

    repository_root = Path(__file__).resolve().parents[1]
    initialize_project(destination, template_root=repository_root / "config")
    decisions_path = destination / "config" / "decisions.yaml"
    payload = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    payload["project_name"] = "Proyecto de validación OCR-01C"
    payload["project_id"] = "ocr01c_layout_structure_validation"
    decisions_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    pdf_path = destination / "corpus" / "layout" / "dos_columnas.pdf"
    _write_pdf(pdf_path)
    original_sha256 = sha256_file(pdf_path)

    upgrade_database(destination)
    decisions = load_decisions(decisions_path)
    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=destination,
                decisions=decisions,
                corpus=_corpus(),
            )
            _seed_extraction(session)
        with session_scope(engine) as session:
            bootstrap = bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="validation_script",
                source_keys={"layout_dos_columnas"},
            )
        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            if page is None:
                raise RuntimeError("No se creó la página editable")
            proposal = layout_proposal(session, editable_page_id=page.id)
            structure = layout_structure(session, editable_page_id=page.id)
            objects = session.scalars(
                select(EditableObject)
                .where(
                    EditableObject.editable_page_id == page.id,
                    EditableObject.lifecycle_status == "active",
                )
                .order_by(EditableObject.current_order_index)
            ).all()
            review_view = review_page_view(
                session,
                project_root=destination,
                source_key="layout_dos_columnas",
                page=1,
            )
    finally:
        engine.dispose()

    if bootstrap.pages_created != 1 or bootstrap.objects_created != 7:
        raise RuntimeError("La capa editable controlada no se creó como se esperaba")
    if len(proposal.columns) != 2:
        raise RuntimeError("La propuesta no detectó las dos columnas controladas")
    if len(proposal.fragment_candidates) != 1:
        raise RuntimeError("La propuesta no detectó la fragmentación controlada")
    if len(proposal.duplicate_candidates) != 1:
        raise RuntimeError("La propuesta no detectó el duplicado controlado")
    if structure.columns:
        raise RuntimeError("La propuesta se volvió canónica sin confirmación")
    if review_view.preview_path is None or not review_view.preview_path.is_file():
        raise RuntimeError("La vista de revisión no pudo mostrar la página original")
    if sha256_file(pdf_path) != original_sha256:
        raise RuntimeError("El original fue modificado")

    result: dict[str, object] = {
        "version": __version__,
        "revision": current_revision(destination),
        "destination": str(destination),
        "documents": 1,
        "editable_pages": bootstrap.pages_created,
        "editable_objects": len(objects),
        "proposed_columns": len(proposal.columns),
        "changed_positions": proposal.changed_positions,
        "fragment_candidates": len(proposal.fragment_candidates),
        "duplicate_candidates": len(proposal.duplicate_candidates),
        "confirmed_columns": len(structure.columns),
        "review_image_available": True,
        "review_image_path": str(review_view.preview_path.relative_to(destination)),
        "original_sha256": original_sha256,
        "originals_unchanged": True,
        "project_data_touched": False,
    }
    (destination / "validation_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(create_validation_project(args.destination), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
