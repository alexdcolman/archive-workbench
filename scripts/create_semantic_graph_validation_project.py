#!/usr/bin/env python3
"""Crea un proyecto descartable para validar SEM-01 y GRAPH-01 sin tocar project_data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from archive_workbench.authorities import create_authority, create_mention
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import (
    ArchivalUnit,
    DigitalObject,
    EditableObject,
    EditablePage,
    ExtractedObject,
    ExtractionPage,
    ExtractionRun,
    Project,
    SourceRegistration,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.identity import new_id
from archive_workbench.project_init import initialize_project
from archive_workbench.relations import create_entity_relation
from archive_workbench.semantic_evaluation import (
    evaluate_semantic_search,
    write_semantic_evaluation_report,
)
from archive_workbench.semantic_search import (
    SemanticProfileValues,
    build_semantic_index,
    save_semantic_profile,
)


class ControlledSemanticBackend:
    """Control determinista para validar el contrato, no un modelo recomendado."""

    @staticmethod
    def _vector(text: str) -> list[float]:
        value = text.casefold()
        cultural = sum(
            term in value for term in ("teat", "cultur", "investig", "vigil", "inteligencia")
        )
        economic = sum(
            term in value for term in ("carne", "precio", "econom", "mercado")
        )
        if cultural == 0 and economic == 0:
            return [0.5, 0.5]
        return [float(cultural), float(economic)]

    def encode_documents(self, texts, *, batch_size: int):
        return [self._vector(text) for text in texts]

    def encode_queries(self, texts, *, batch_size: int):
        return [self._vector(text) for text in texts]


def _create_document(
    session,
    *,
    project_id: str,
    source_key: str,
    filename: str,
    sha_character: str,
    title: str,
    text: str,
) -> EditableObject:
    unit = ArchivalUnit(
        id=new_id(),
        project_id=project_id,
        level_key="documento",
        title=title,
        created_by="validation_script",
        updated_by="validation_script",
    )
    digital = DigitalObject(
        id=new_id(),
        project_id=project_id,
        media_type="pdf",
        original_filename=filename,
        sha256=sha_character * 64,
        byte_size=1,
        page_count=1,
    )
    session.add_all([unit, digital])
    session.flush()
    session.add(
        SourceRegistration(
            id=new_id(),
            project_id=project_id,
            source_type="test_corpus",
            source_key=source_key,
            digital_object_id=digital.id,
            archival_unit_id=unit.id,
            source_payload_json={"validation": "SEM-01/GRAPH-01"},
            registered_by="validation_script",
        )
    )
    run = ExtractionRun(
        id=new_id(),
        digital_object_id=digital.id,
        profile_key="validation",
        engine="tesseract_tsv",
        source_sha256=digital.sha256,
        options_json={"validation": True},
        options_hash=hashlib.sha256(source_key.encode("utf-8")).hexdigest(),
        status="completed",
        is_current=True,
        total_pages=1,
        total_objects=1,
        total_paragraphs=1,
        total_characters=len(text),
        warnings_json=[],
        created_by="validation_script",
    )
    session.add(run)
    session.flush()
    extraction_page = ExtractionPage(
        id=new_id(),
        extraction_run_id=run.id,
        page_number=1,
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
        page_number=1,
        order_index=0,
        object_type="paragraph",
        original_text=text,
        geometry_json=[],
        attributes_json={"validation": True},
    )
    session.add(extracted)
    session.flush()
    editable_page = EditablePage(
        id=new_id(),
        digital_object_id=digital.id,
        page_number=1,
        source_extraction_run_id=run.id,
        source_extraction_page_id=extraction_page.id,
        status="active",
        review_status="approved",
        review_note="Página controlada para SEM-01 y GRAPH-01.",
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
        page_number=1,
        source_extracted_object_id=extracted.id,
        source_origin_id=extracted.origin_id,
        current_text=text,
        current_object_type="paragraph",
        current_order_index=0,
        current_geometry_json=[],
        current_attributes_json={"validation": True},
        lifecycle_status="active",
        review_status="approved",
        revision_number=1,
        created_by="validation_script",
        updated_by="validation_script",
    )
    session.add(editable)
    session.flush()
    return editable


def create_validation_project(destination: Path, *, force: bool) -> dict[str, object]:
    destination = destination.expanduser().resolve()
    if destination.exists():
        if not force:
            raise SystemExit(
                f"El destino ya existe: {destination}. Usá --force solo si autorizás recrearlo."
            )
        shutil.rmtree(destination)
    repository_root = Path(__file__).resolve().parents[1]
    initialize_project(destination, template_root=repository_root / "config")
    upgrade_database(destination)
    decisions = load_decisions(destination / "config" / "decisions.yaml")
    backend = ControlledSemanticBackend()

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            session.add(
                Project(
                    id=decisions.project_id,
                    name="Validación SEM-01 y GRAPH-01",
                    decisions_json={},
                )
            )
            session.flush()
            cultural = _create_document(
                session,
                project_id=decisions.project_id,
                source_key="validacion_cultural",
                filename="validacion_cultural.pdf",
                sha_character="a",
                title="Informe cultural",
                text=(
                    "La Dirección de Inteligencia investigó la actividad teatral y cultural "
                    "de Persona Investigada."
                ),
            )
            economic = _create_document(
                session,
                project_id=decisions.project_id,
                source_key="validacion_economica",
                filename="validacion_economica.pdf",
                sha_character="b",
                title="Informe económico",
                text=(
                    "El Mercado Central registró el aumento del precio de la carne y mencionó "
                    "a Persona Investigada."
                ),
            )

            intelligence = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Dirección de Inteligencia",
                description="Entidad controlada para validar procedencia y aristas paralelas.",
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
            market = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Mercado Central",
                created_by="validation_script",
                review_status="approved",
            )
            create_mention(
                session,
                object_id=cultural.id,
                mention_text="Dirección de Inteligencia",
                authority_id=intelligence.id,
                created_by="validation_script",
            )
            create_mention(
                session,
                object_id=cultural.id,
                mention_text="Persona Investigada",
                authority_id=person.id,
                created_by="validation_script",
            )
            create_mention(
                session,
                object_id=economic.id,
                mention_text="Mercado Central",
                authority_id=market.id,
                created_by="validation_script",
            )
            create_mention(
                session,
                object_id=economic.id,
                mention_text="Persona Investigada",
                authority_id=person.id,
                created_by="validation_script",
            )
            for label, source, target, evidence in (
                ("fue investigada por", person, intelligence, "Informe cultural, página 1"),
                ("aparece en registros de", person, intelligence, "Registro controlado B"),
                ("vigiló a", intelligence, person, "Registro controlado C"),
            ):
                create_entity_relation(
                    session,
                    project_id=decisions.project_id,
                    source_authority_id=source.id,
                    relation_label=label,
                    target_kind="entity",
                    target_id=target.id,
                    evidence_note=evidence,
                    created_by="validation_script",
                    review_status="approved",
                )

            profile = save_semantic_profile(
                session,
                project_id=decisions.project_id,
                values=SemanticProfileValues(
                    name="Control SEM-01",
                    description="Perfil determinista exclusivo de la validación controlada.",
                    model_name="archive-workbench/control-keywords",
                    model_revision="1",
                    aggregation_level="object",
                    query_prefix="",
                    document_prefix="",
                ),
                changed_by="validation_script",
            )
            summary = build_semantic_index(
                session,
                project_root=destination,
                project_id=decisions.project_id,
                profile=profile,
                created_by="validation_script",
                backend=backend,
            )

            validation_dir = destination / "validation"
            validation_dir.mkdir(parents=True, exist_ok=True)
            corpus_path = validation_dir / "semantic_queries.jsonl"
            cases = [
                {
                    "case_id": "cultural",
                    "query": "vigilancia cultural",
                    "query_kind": "positive",
                    "fragment_type": "object",
                    "target_field": "object_id",
                    "expected": [cultural.id],
                },
                {
                    "case_id": "economica",
                    "query": "precio del mercado",
                    "query_kind": "positive",
                    "fragment_type": "object",
                    "target_field": "object_id",
                    "expected": [economic.id],
                },
                {
                    "case_id": "negativa",
                    "query": "astronomía planetaria",
                    "query_kind": "negative",
                    "fragment_type": "object",
                    "target_field": "object_id",
                    "expected": [],
                },
                {
                    "case_id": "ambigua",
                    "query": "cultura y mercado",
                    "query_kind": "ambiguous",
                    "fragment_type": "object",
                    "target_field": "object_id",
                    "expected": [cultural.id, economic.id],
                },
            ]
            corpus_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in cases),
                encoding="utf-8",
            )
            evaluation = evaluate_semantic_search(
                session,
                project_root=destination,
                project_id=decisions.project_id,
                profile=profile,
                corpus_path=corpus_path,
                thresholds=(0.7, 0.8),
                top_k=10,
                backend=backend,
            )
            report_path = write_semantic_evaluation_report(
                evaluation, validation_dir / "semantic_evaluation.json"
            )
            alternative = evaluate_semantic_search(
                session,
                project_root=destination,
                project_id=decisions.project_id,
                profile=profile,
                corpus_path=corpus_path,
                thresholds=(0.0, 0.8),
                top_k=10,
                backend=backend,
            )
            alternative_report_path = write_semantic_evaluation_report(
                alternative, validation_dir / "semantic_evaluation_alt.json"
            )
            manifest = {
                "destination": str(destination),
                "revision": current_revision(destination),
                "project_id": decisions.project_id,
                "semantic_profile_id": profile.id,
                "semantic_index_run_id": summary.run_id,
                "semantic_corpus": str(corpus_path),
                "semantic_report": str(report_path),
                "semantic_report_sha256": evaluation.report_sha256,
                "semantic_alternative_report": str(alternative_report_path),
                "semantic_alternative_report_sha256": alternative.report_sha256,
                "recommended_threshold": evaluation.payload["recommended_threshold"],
                "cultural_object_id": cultural.id,
                "economic_object_id": economic.id,
                "parallel_relation_count": 3,
            }
            manifest_path = validation_dir / "manifest.json"
            manifest["manifest_path"] = str(manifest_path)
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    finally:
        engine.dispose()
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = create_validation_project(args.destination, force=args.force)
    print(f"Proyecto descartable creado: {result['destination']}")
    print(f"Revisión de base: {result['revision']}")
    print(f"Perfil semántico: {result['semantic_profile_id']}")
    print(f"Informe semántico: {result['semantic_report']}")
    print(f"Informe alternativo: {result['semantic_alternative_report']}")
    recommended = result["recommended_threshold"]
    print(
        "Umbral controlado recomendado: "
        f"{recommended['value']} · F1 {recommended['micro']['f1']}"
    )
    print(f"Relaciones paralelas controladas: {result['parallel_relation_count']}")
    print(f"Manifiesto: {result['manifest_path']}")
    print("project_data no fue leído ni modificado.")


if __name__ == "__main__":
    main()
