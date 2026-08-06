#!/usr/bin/env python3
"""Crea una base descartable para validar OCR-01B sin tocar project_data."""

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
from archive_workbench.form_structure import form_candidates, form_structure
from archive_workbench.identity import new_id, sha256_file
from archive_workbench.project_init import initialize_project
from archive_workbench.version import __version__


def _write_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((55, 60), "FICHA DE VALIDACIÓN OCR-01B", fontsize=18)
    page.insert_text((55, 105), "Estado civil", fontsize=14)

    rows = [
        (145, True, "Soltero"),
        (185, False, "Casado"),
        (225, True, "Afiliado"),
        (265, False, "Beneficiario"),
    ]
    for y, marked, label in rows:
        page.draw_rect(fitz.Rect(58, y - 14, 74, y + 2), width=1.2)
        if marked:
            page.draw_line(fitz.Point(60, y - 7), fitz.Point(66, y), width=1.4)
            page.draw_line(fitz.Point(66, y), fitz.Point(72, y - 11), width=1.4)
        page.insert_text((88, y), label, fontsize=12)

    page.insert_text(
        (55, 325),
        "Observaciones: el casillero Beneficiario es visible, pero su marca no fue OCRizada.",
        fontsize=10,
    )
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
            "corpus_name": "Validación OCR-01B",
            "created_by": "validation_script",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "formulario_controlado",
                    "local_path": "corpus/formularios/ficha_validacion.pdf",
                    "short_description": "Ficha controlada con casilleros y grupo de formulario",
                    "archival_location": {
                        "fondo": "Validación OCR-01B",
                        "serie": "Formularios",
                        "documento": "Ficha de validación de casilleros",
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
                        "tables_or_forms": True,
                        "multiple_internal_documents": False,
                    },
                    "expected_extraction": {"minimum_page_coverage_percent": 95},
                }
            ],
        }
    )


def _seed_extraction(session) -> tuple[str, str]:
    registration = session.scalar(
        select(SourceRegistration).where(
            SourceRegistration.source_key == "formulario_controlado"
        )
    )
    if registration is None or registration.digital_object_id is None:
        raise RuntimeError("No se registró el objeto digital de validación")
    digital = session.get(DigitalObject, registration.digital_object_id)
    if digital is None:
        raise RuntimeError("No se encontró el objeto digital de validación")

    definitions = [
        (
            "title",
            "FICHA DE VALIDACIÓN OCR-01B",
            _geometry(0.09, 0.05, 0.58, 0.09),
            {},
        ),
        (
            "heading",
            "Estado civil",
            _geometry(0.09, 0.11, 0.30, 0.14),
            {},
        ),
        (
            "form_field",
            "[x] Soltero",
            _geometry(0.09, 0.155, 0.30, 0.185),
            {"source_label": "form"},
        ),
        (
            "form_field",
            "☐ Casado",
            _geometry(0.09, 0.202, 0.30, 0.232),
            {"source_label": "form"},
        ),
        (
            "form_field",
            "x",
            _geometry(0.095, 0.250, 0.120, 0.276),
            {"source_label": "form"},
        ),
        (
            "form_field",
            "Afiliado",
            _geometry(0.145, 0.248, 0.30, 0.278),
            {"source_label": "form"},
        ),
        (
            "form_field",
            "Beneficiario",
            _geometry(0.145, 0.296, 0.34, 0.326),
            {"source_label": "form", "manual_checkbox_visible": True},
        ),
        (
            "paragraph",
            "Observaciones: el casillero Beneficiario es visible, pero su marca no fue OCRizada.",
            _geometry(0.09, 0.37, 0.90, 0.41),
            {},
        ),
    ]

    run = ExtractionRun(
        id=new_id(),
        digital_object_id=digital.id,
        profile_key="ocr01b_validation",
        engine="controlled_fixture",
        engine_version="1",
        source_sha256=digital.sha256,
        options_json={"fixture": "ocr01b"},
        options_hash="3" * 64,
        status="completed",
        is_current=True,
        created_by="validation_script",
        total_pages=1,
        total_objects=len(definitions),
        total_paragraphs=1,
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

    for order_index, (object_type, text, geometry, attributes) in enumerate(definitions):
        session.add(
            ExtractedObject(
                id=new_id(),
                origin_id=new_id(),
                extraction_run_id=run.id,
                digital_object_id=digital.id,
                page_number=1,
                order_index=order_index,
                object_type=object_type,
                original_text=text,
                geometry_json=geometry,
                attributes_json=attributes,
            )
        )
    selection = ExtractionPageSelection(
        id=new_id(),
        digital_object_id=digital.id,
        page_number=1,
        extraction_run_id=run.id,
        extraction_page_id=extraction_page.id,
        selected_by="validation_script",
        note="Selección controlada para validar OCR-01B",
    )
    session.add(selection)
    session.flush()
    return digital.id, extraction_page.id


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
    decisions_payload = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    decisions_payload["project_name"] = "Proyecto de validación OCR-01B"
    decisions_payload["project_id"] = "ocr01b_form_structure_validation"
    decisions_path.write_text(
        yaml.safe_dump(decisions_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    pdf_path = destination / "corpus" / "formularios" / "ficha_validacion.pdf"
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
                source_keys={"formulario_controlado"},
            )
        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            if page is None:
                raise RuntimeError("No se creó la página editable")
            candidates = form_candidates(session, editable_page_id=page.id)
            structure = form_structure(session, editable_page_id=page.id)
            editable_objects = session.scalars(
                select(EditableObject).where(
                    EditableObject.editable_page_id == page.id,
                    EditableObject.lifecycle_status == "active",
                )
            ).all()
    finally:
        engine.dispose()

    if bootstrap.pages_created != 1 or bootstrap.objects_created != 8:
        raise RuntimeError("La capa editable controlada no se creó como se esperaba")
    if [(item.state, item.label) for item in candidates] != [
        ("marked", "Soltero"),
        ("unmarked", "Casado"),
        ("marked", "Afiliado"),
    ]:
        raise RuntimeError("Los candidatos controlados no coinciden con lo esperado")
    if structure.groups or structure.controls:
        raise RuntimeError("Los candidatos se volvieron canónicos sin confirmación")
    if sha256_file(pdf_path) != original_sha256:
        raise RuntimeError("El original fue modificado")

    result: dict[str, object] = {
        "version": __version__,
        "revision": current_revision(destination),
        "destination": str(destination),
        "documents": 1,
        "editable_pages": bootstrap.pages_created,
        "editable_objects": len(editable_objects),
        "candidate_count": len(candidates),
        "candidate_states": [item.state for item in candidates],
        "candidate_labels": [item.label for item in candidates],
        "confirmed_groups": len(structure.groups),
        "confirmed_controls": len(structure.controls),
        "manual_only_label": "Beneficiario",
        "original_sha256": original_sha256,
        "originals_unchanged": True,
        "project_data_touched": False,
    }
    (destination / "validation_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(create_validation_project(args.destination), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
