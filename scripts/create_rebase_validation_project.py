#!/usr/bin/env python3
"""Crea un proyecto descartable para validar proyección y atributos del rebase."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil

import fitz
from sqlalchemy import select

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.test_corpus import TestCorpus
from archive_workbench.db import (
    create_sqlite_engine,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import (
    DigitalObject,
    EditableObject,
    EditableObjectComment,
    EditableObjectTag,
    ExtractedObject,
    ExtractionPage,
    ExtractionRun,
    SourceRegistration,
    utc_now,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import _append_revision, bootstrap_editable_layer
from archive_workbench.extraction import select_extraction_pages
from archive_workbench.identity import new_id
from archive_workbench.project_init import initialize_project


def _write_demo_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=700, height=500)
    page.insert_text((70, 90), "Proyecto descartable de validacion del rebase", fontsize=18)
    page.insert_text((70, 160), "Bloque alfa original", fontsize=14)
    page.insert_text((70, 220), "Bloque beta original", fontsize=14)
    page.insert_text((70, 320), "La candidata tendra una estructura deliberadamente distinta.")
    document.save(path)
    document.close()


def _corpus() -> TestCorpus:
    return TestCorpus.model_validate(
        {
            "corpus_name": "Validacion de rebase",
            "created_by": "archive-workbench-demo",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "rebase_demo",
                    "local_path": "corpus/rebase_demo.pdf",
                    "short_description": "Caso descartable de proyeccion y atributos",
                    "archival_location": {
                        "fondo": "Demo",
                        "legajo": "Rebase",
                        "documento": "Validacion",
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


def _seed_run(
    session,
    *,
    digital: DigitalObject,
    profile_key: str,
    engine: str,
    rows: list[tuple[str, str, dict]],
    options_hash: str,
) -> ExtractionRun:
    run = ExtractionRun(
        id=new_id(),
        digital_object_id=digital.id,
        profile_key=profile_key,
        engine=engine,
        engine_version="demo",
        source_sha256=digital.sha256,
        options_json={"demo": True},
        options_hash=options_hash,
        status="completed",
        is_current=False,
        created_by="archive-workbench-demo",
        total_pages=1,
        total_objects=len(rows),
        total_paragraphs=len(rows),
        total_characters=sum(len(text) for _kind, text, _attrs in rows),
        warnings_json=[],
        quality_status="needs_review",
    )
    session.add(run)
    session.flush()
    session.add(
        ExtractionPage(
            id=new_id(),
            extraction_run_id=run.id,
            page_number=1,
            object_count=len(rows),
            character_count=sum(len(text) for _kind, text, _attrs in rows),
            status="completed",
        )
    )
    for order, (object_type, text, attributes) in enumerate(rows):
        session.add(
            ExtractedObject(
                id=new_id(),
                origin_id=new_id(),
                extraction_run_id=run.id,
                digital_object_id=digital.id,
                page_number=1,
                order_index=order,
                object_type=object_type,
                original_text=text,
                geometry_json=[],
                attributes_json=attributes,
                source_label="Demo",
                confidence=0.9,
                language="es",
            )
        )
    session.flush()
    return run


def create_demo(destination: Path, *, force: bool) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if destination.exists():
        if not force:
            raise SystemExit(
                f"El destino ya existe: {destination}. Use --force para recrearlo."
            )
        shutil.rmtree(destination)

    initialize_project(destination, template_root=repo_root / "config")
    _write_demo_pdf(destination / "corpus" / "rebase_demo.pdf")
    upgrade_database(destination)
    decisions = load_decisions(destination / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=destination,
                decisions=decisions,
                corpus=_corpus(),
            )
            registration = session.scalar(
                select(SourceRegistration).where(
                    SourceRegistration.source_key == "rebase_demo"
                )
            )
            if registration is None or registration.digital_object_id is None:
                raise RuntimeError("No pudo registrarse el documento de demostracion.")
            digital = session.get(DigitalObject, registration.digital_object_id)
            if digital is None:
                raise RuntimeError("No pudo localizarse el objeto digital de demostracion.")

            old_run = _seed_run(
                session,
                digital=digital,
                profile_key="demo_ocr_anterior",
                engine="tesseract_tsv",
                rows=[
                    ("paragraph", "Bloque alfa original", {}),
                    ("paragraph", "Bloque beta original", {}),
                ],
                options_hash="a" * 64,
            )
            new_run = _seed_run(
                session,
                digital=digital,
                profile_key="demo_surya_candidata",
                engine="surya_cli",
                rows=[
                    (
                        "paragraph",
                        "Destino comun completamente distinto para las dos anotaciones",
                        {
                            "classification": {
                                "origin": "surya",
                                "value": "candidate",
                            },
                            "layout_role": "body",
                        },
                    ),
                    (
                        "paragraph",
                        "Segundo bloque candidato sin correspondencia literal",
                        {"layout_role": "footer"},
                    ),
                ],
                options_hash="b" * 64,
            )
            select_extraction_pages(
                session,
                source_key="rebase_demo",
                selected_by="archive-workbench-demo",
                run_id=old_run.id,
                pages={1},
                note="Base anterior del caso descartable",
            )
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="archive-workbench-demo",
                source_keys={"rebase_demo"},
            )
            objects = session.scalars(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            ).all()
            values = ["A", "B"]
            for index, (obj, value) in enumerate(zip(objects, values), start=1):
                base_revision = obj.revision_number
                obj.current_attributes_json = {
                    **(obj.current_attributes_json or {}),
                    "classification": {"origin": "human", "value": value},
                    "shared_review": {"priority": "high"},
                    "demo_attribute": True,
                }
                obj.revision_number += 1
                obj.updated_by = "archive-workbench-demo"
                obj.updated_at = utc_now()
                _append_revision(
                    session,
                    obj,
                    operation="edit",
                    created_by="archive-workbench-demo",
                    note="Atributos especializados para la validacion descartable.",
                    base_revision_number=base_revision,
                )
                session.add(
                    EditableObjectComment(
                        id=new_id(),
                        editable_object_id=obj.id,
                        body=f"Comentario de prueba {index}",
                        created_by="archive-workbench-demo",
                    )
                )
                session.add(
                    EditableObjectTag(
                        id=new_id(),
                        editable_object_id=obj.id,
                        tag=f"demo-{index}",
                        normalized_tag=f"demo-{index}",
                        tag_kind="workflow",
                        created_by="archive-workbench-demo",
                    )
                )

            print(f"Proyecto creado: {destination}")
            print("Fuente: rebase_demo")
            print("Pagina: 1")
            print(f"Corrida candidata: {new_run.id}")
            print("Abra Procesamiento > Seleccion canonica y elija demo_surya_candidata.")
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("project_data_rebase_validation"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    create_demo(args.destination.resolve(), force=args.force)


if __name__ == "__main__":
    main()
