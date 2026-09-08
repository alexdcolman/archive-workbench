#!/usr/bin/env python3
"""Crea un proyecto sintético y portable para validar la candidata de Archive Workbench."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import fitz
from sqlalchemy import select

from archive_workbench.authorities import create_authority, create_mention
from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.test_corpus import TestCorpus
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
)
from archive_workbench.db.models import (
    DigitalObject,
    EditableObject,
    ExtractedObject,
    ExtractionPage,
    ExtractionRun,
    SourceRegistration,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import bootstrap_editable_layer
from archive_workbench.extraction import select_extraction_pages
from archive_workbench.identity import new_id
from archive_workbench.project_setup import create_ready_project
from archive_workbench.relations import create_entity_relation

EXPECTED_REVISION = "0047_authority_relation_profiles"
PROJECT_NAME = "Proyecto de ejemplo Archive Workbench"
PROJECT_ID = "archive_workbench_ejemplo"
ACTOR = "archive-workbench-release-example"

DOCUMENTS = (
    {
        "source_key": "ejemplo_actividad_cultural",
        "filename": "actividad_cultural.pdf",
        "title": "Nota sobre actividad cultural",
        "text": (
            "El Centro Cultural Horizonte comunicó a Marina López la realización de una "
            "muestra documental en Villa Ejemplo el 12 de mayo de 1984."
        ),
        "archival_location": {
            "fondo": "Fondo de ejemplo",
            "serie": "Correspondencia institucional",
            "caja": "Caja 1",
            "documento": "Nota sobre actividad cultural",
        },
    },
    {
        "source_key": "ejemplo_reunion_vecinal",
        "filename": "reunion_vecinal.pdf",
        "title": "Informe de reunión vecinal",
        "text": (
            "La Comisión Vecinal del Puerto registró una reunión con Marina López y el "
            "Centro Cultural Horizonte sobre la conservación de fotografías barriales."
        ),
        "archival_location": {
            "fondo": "Fondo de ejemplo",
            "serie": "Informes de actividades",
            "caja": "Caja 2",
            "documento": "Informe de reunión vecinal",
        },
    },
)


def _write_pdf(path: Path, *, title: str, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 84), title, fontsize=16)
    result = page.insert_textbox(
        fitz.Rect(72, 125, 523, 760),
        text,
        fontsize=12,
        lineheight=1.35,
    )
    if result < 0:
        document.close()
        raise RuntimeError(f"No se pudo componer el PDF sintético: {path.name}")
    document.save(path)
    document.close()


def _corpus() -> TestCorpus:
    documents = []
    for item in DOCUMENTS:
        documents.append(
            {
                "test_id": item["source_key"],
                "local_path": f"corpus/{item['filename']}",
                "short_description": item["title"],
                "archival_location": item["archival_location"],
                "input_characteristics": {
                    "format": "pdf",
                    "scanned": False,
                    "digital_text_layer": True,
                    "multipage_tiff": False,
                    "poor_contrast": False,
                    "skewed_pages": False,
                    "landscape_pages": False,
                    "mixed_orientations": False,
                    "text_orientation": "upright",
                    "typewritten": True,
                    "handwritten_notes": False,
                    "stamps": False,
                    "tables_or_forms": False,
                    "multiple_internal_documents": False,
                    "unknown": False,
                },
                "expected_extraction": {
                    "minimum_page_coverage_percent": 100,
                    "reading_order_should_be_correct": True,
                    "preserve_stamps_as_regions": True,
                    "preserve_handwriting_as_regions": True,
                    "transcribe_handwriting_automatically": False,
                    "expected_object_types": ["paragraph"],
                    "objects_that_may_be_hidden_by_default": [],
                    "critical_text_examples": [item["text"]],
                    "known_difficulties": [],
                },
                "manual_ground_truth": {
                    "pages_reviewed": [1],
                    "expected_internal_parts": [],
                    "expected_tables": [],
                    "expected_notes": [],
                },
                "acceptance_notes": "Contenido íntegramente sintético para el proyecto de ejemplo.",
            }
        )
    return TestCorpus.model_validate(
        {
            "corpus_name": "Proyecto de ejemplo de Archive Workbench",
            "created_by": ACTOR,
            "created_at": datetime.now(timezone.utc),
            "documents": documents,
        }
    )


def _seed_extraction(
    session, *, digital: DigitalObject, source_key: str, text: str
) -> ExtractionRun:
    run = ExtractionRun(
        id=new_id(),
        digital_object_id=digital.id,
        profile_key="release_example_text_layer_v1",
        engine="controlled_example",
        engine_version="1",
        source_sha256=digital.sha256,
        options_json={"release_example": True, "source": "digital_text_layer"},
        options_hash=hashlib.sha256(source_key.encode("utf-8")).hexdigest(),
        status="completed",
        is_current=True,
        total_pages=1,
        total_objects=1,
        total_paragraphs=1,
        total_characters=len(text),
        warnings_json=[],
        created_by=ACTOR,
    )
    session.add(run)
    session.flush()

    page = ExtractionPage(
        id=new_id(),
        extraction_run_id=run.id,
        page_number=1,
        object_count=1,
        character_count=len(text),
        status="completed",
    )
    session.add(page)
    session.flush()

    session.add(
        ExtractedObject(
            id=new_id(),
            origin_id=new_id(),
            extraction_run_id=run.id,
            digital_object_id=digital.id,
            page_number=1,
            order_index=0,
            object_type="paragraph",
            original_text=text,
            geometry_json=[],
            attributes_json={"release_example": True},
            source_label="Texto digital sintético",
            confidence=1.0,
            language="es",
        )
    )
    session.flush()
    return run


def _write_readme(destination: Path) -> None:
    text = """PROYECTO DE EJEMPLO · ARCHIVE WORKBENCH

Este proyecto contiene exclusivamente datos sintéticos. Sirve para abrir la aplicación,
recorrer el catálogo, revisar texto, explorar entidades, menciones y relaciones, y comprobar
la persistencia local sin usar materiales reales.

Contenido:
- dos PDF sintéticos de una página;
- dos unidades documentales con texto editable;
- cuatro entidades de ejemplo;
- seis menciones vinculadas;
- tres relaciones analíticas.

La base SQLite y los originales pertenecen únicamente a este proyecto de ejemplo.
No se utilizan ni se copian datos de pilot_data ni de ningún proyecto real.
"""
    (destination / "README_EJEMPLO.txt").write_text(text, encoding="utf-8")


def _make_archive(destination: Path, archive: Path) -> Path:
    archive = archive.expanduser().resolve()
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.suffix.casefold() != ".zip":
        archive = archive.with_suffix(".zip")
    base = archive.with_suffix("")
    produced = Path(
        shutil.make_archive(
            str(base),
            "zip",
            root_dir=destination.parent,
            base_dir=destination.name,
        )
    )
    return produced


def create_release_example(
    destination: Path,
    *,
    force: bool,
    archive: Path | None = None,
) -> dict[str, object]:
    destination = destination.expanduser().resolve()
    if destination.exists():
        if not force:
            raise SystemExit(
                f"El destino ya existe: {destination}. Usá --force sólo para recrear este ejemplo."
            )
        shutil.rmtree(destination)

    create_ready_project(
        destination,
        project_name=PROJECT_NAME,
        project_id=PROJECT_ID,
    )
    revision = current_revision(destination)
    if revision != EXPECTED_REVISION:
        raise RuntimeError(
            f"Revisión inesperada después de crear el proyecto: {revision!r}; "
            f"se esperaba {EXPECTED_REVISION!r}"
        )

    for item in DOCUMENTS:
        _write_pdf(
            destination / "corpus" / item["filename"],
            title=item["title"],
            text=item["text"],
        )

    decisions = load_decisions(destination / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            registration_summary = register_test_corpus(
                session,
                project_root=destination,
                decisions=decisions,
                corpus=_corpus(),
            )

            objects_by_source: dict[str, EditableObject] = {}
            for item in DOCUMENTS:
                registration = session.scalar(
                    select(SourceRegistration).where(
                        SourceRegistration.project_id == PROJECT_ID,
                        SourceRegistration.source_key == item["source_key"],
                    )
                )
                if registration is None or registration.digital_object_id is None:
                    raise RuntimeError(
                        f"No se registró el documento sintético {item['source_key']!r}"
                    )
                digital = session.get(DigitalObject, registration.digital_object_id)
                if digital is None:
                    raise RuntimeError(
                        f"No se encontró el objeto digital de {item['source_key']!r}"
                    )
                run = _seed_extraction(
                    session,
                    digital=digital,
                    source_key=item["source_key"],
                    text=item["text"],
                )
                select_extraction_pages(
                    session,
                    source_key=item["source_key"],
                    selected_by=ACTOR,
                    run_id=run.id,
                    pages={1},
                    note="Extracción controlada del proyecto de ejemplo.",
                )

            bootstrap = bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by=ACTOR,
                source_keys={item["source_key"] for item in DOCUMENTS},
            )

            for item in DOCUMENTS:
                registration = session.scalar(
                    select(SourceRegistration).where(
                        SourceRegistration.project_id == PROJECT_ID,
                        SourceRegistration.source_key == item["source_key"],
                    )
                )
                if registration is None or registration.digital_object_id is None:
                    raise RuntimeError("Registro de origen ausente después del bootstrap")
                editable = session.scalar(
                    select(EditableObject).where(
                        EditableObject.digital_object_id == registration.digital_object_id,
                        EditableObject.lifecycle_status == "active",
                    )
                )
                if editable is None:
                    raise RuntimeError(f"No se creó el texto editable de {item['source_key']!r}")
                objects_by_source[item["source_key"]] = editable

            marina = create_authority(
                session,
                project_id=PROJECT_ID,
                entity_type="person",
                preferred_name="Marina López",
                description="Persona ficticia utilizada exclusivamente en el proyecto de ejemplo.",
                created_by=ACTOR,
                review_status="approved",
            )
            centro = create_authority(
                session,
                project_id=PROJECT_ID,
                entity_type="organization",
                preferred_name="Centro Cultural Horizonte",
                description="Organización ficticia utilizada exclusivamente en el proyecto de ejemplo.",
                created_by=ACTOR,
                review_status="approved",
            )
            comision = create_authority(
                session,
                project_id=PROJECT_ID,
                entity_type="organization",
                preferred_name="Comisión Vecinal del Puerto",
                description="Organización ficticia utilizada exclusivamente en el proyecto de ejemplo.",
                created_by=ACTOR,
                review_status="approved",
            )
            villa = create_authority(
                session,
                project_id=PROJECT_ID,
                entity_type="place",
                preferred_name="Villa Ejemplo",
                description="Lugar ficticio utilizado exclusivamente en el proyecto de ejemplo.",
                created_by=ACTOR,
                review_status="approved",
            )

            cultural = objects_by_source["ejemplo_actividad_cultural"]
            vecinal = objects_by_source["ejemplo_reunion_vecinal"]

            create_mention(
                session,
                object_id=cultural.id,
                mention_text="Centro Cultural Horizonte",
                authority_id=centro.id,
                created_by=ACTOR,
            )
            create_mention(
                session,
                object_id=cultural.id,
                mention_text="Marina López",
                authority_id=marina.id,
                created_by=ACTOR,
            )
            create_mention(
                session,
                object_id=cultural.id,
                mention_text="Villa Ejemplo",
                authority_id=villa.id,
                created_by=ACTOR,
            )
            create_mention(
                session,
                object_id=vecinal.id,
                mention_text="Comisión Vecinal del Puerto",
                authority_id=comision.id,
                created_by=ACTOR,
            )
            create_mention(
                session,
                object_id=vecinal.id,
                mention_text="Marina López",
                authority_id=marina.id,
                created_by=ACTOR,
            )
            create_mention(
                session,
                object_id=vecinal.id,
                mention_text="Centro Cultural Horizonte",
                authority_id=centro.id,
                created_by=ACTOR,
            )

            create_entity_relation(
                session,
                project_id=PROJECT_ID,
                source_authority_id=marina.id,
                relation_label="participó en actividades de",
                target_kind="entity",
                target_id=centro.id,
                evidence_note="Nota sobre actividad cultural, página 1.",
                created_by=ACTOR,
                review_status="approved",
            )
            create_entity_relation(
                session,
                project_id=PROJECT_ID,
                source_authority_id=comision.id,
                relation_label="se reunió con",
                target_kind="entity",
                target_id=marina.id,
                evidence_note="Informe de reunión vecinal, página 1.",
                created_by=ACTOR,
                review_status="approved",
            )
            create_entity_relation(
                session,
                project_id=PROJECT_ID,
                source_authority_id=comision.id,
                relation_label="colaboró con",
                target_kind="entity",
                target_id=centro.id,
                evidence_note="Informe de reunión vecinal, página 1.",
                created_by=ACTOR,
                review_status="approved",
            )

            manifest = {
                "schema": "archive_workbench_release_example_v1",
                "project_name": PROJECT_NAME,
                "project_id": PROJECT_ID,
                "database_revision": revision,
                "synthetic_data_only": True,
                "documents_registered": registration_summary.documents_registered,
                "editable_pages_created": bootstrap.pages_created,
                "editable_objects_created": bootstrap.objects_created,
                "authorities": 4,
                "mentions": 6,
                "relations": 3,
                "source_keys": [item["source_key"] for item in DOCUMENTS],
            }
    finally:
        engine.dispose()

    _write_readme(destination)
    manifest_path = destination / "release_example_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    archive_path = _make_archive(destination, archive) if archive is not None else None
    result = {
        **manifest,
        "destination": str(destination),
        "manifest": str(manifest_path),
        "archive": str(archive_path) if archive_path is not None else None,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = create_release_example(
        args.destination,
        force=args.force,
        archive=args.archive,
    )
    print(f"Proyecto creado: {result['destination']}")
    print(f"Revisión de base: {result['database_revision']}")
    print(f"Documentos: {result['documents_registered']}")
    print(f"Objetos editables: {result['editable_objects_created']}")
    print("Entidades / menciones / relaciones: 4 / 6 / 3")
    print(f"Manifiesto: {result['manifest']}")
    if result["archive"]:
        print(f"ZIP portable: {result['archive']}")
    print("Contenido sintético: sí")
    print("pilot_data no fue leído ni modificado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
