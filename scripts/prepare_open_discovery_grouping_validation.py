#!/usr/bin/env python3
"""Prepara el estado controlado para validar DISC-01C sin repetir la detección original."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from sqlalchemy import func, select

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
)
from archive_workbench.db.models import (
    AuthorityRecord,
    DiscoveryCandidate,
    DiscoveryCandidateContinuity,
    DiscoveryCandidateGroup,
    DiscoveryContextRecord,
    DiscoveryDecision,
    DiscoveryGroupAction,
    DiscoveryGroupMembership,
    DiscoveryRun,
    EditableObject,
    EntityMention,
    EntityRelation,
    utc_now,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import add_editable_object, update_editable_object
from archive_workbench.exchange import current_editable_state_sha256
from archive_workbench.identity import new_id


def _count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _clone_candidate(
    source: DiscoveryCandidate,
    *,
    run_id: str,
    editable_object: EditableObject | None = None,
    exact_text: str | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
) -> DiscoveryCandidate:
    target_object = editable_object
    return DiscoveryCandidate(
        id=new_id(),
        project_id=source.project_id,
        run_id=run_id,
        profile_id=source.profile_id,
        editable_object_id=(target_object.id if target_object else source.editable_object_id),
        editable_page_id=(
            target_object.editable_page_id if target_object else source.editable_page_id
        ),
        digital_object_id=(
            target_object.digital_object_id if target_object else source.digital_object_id
        ),
        document_part_id=(
            target_object.document_part_id if target_object else source.document_part_id
        ),
        source_key=source.source_key,
        original_filename=source.original_filename,
        page_number=(target_object.page_number if target_object else source.page_number),
        object_revision_number=(
            target_object.revision_number if target_object else source.object_revision_number
        ),
        page_revision_number=source.page_revision_number,
        start_offset=(source.start_offset if start_offset is None else start_offset),
        end_offset=(source.end_offset if end_offset is None else end_offset),
        exact_text=(source.exact_text if exact_text is None else exact_text),
        context_before="",
        context_after="",
        semantic_family=source.semantic_family,
        suggested_subtype=source.suggested_subtype,
        confidence=source.confidence,
        method="disc01c_controlled_duplicate",
        provider_key="validation_script",
        provider_version="disc01c_v1",
        model_name=None,
        model_version=None,
        explanation="Candidato controlado para validar agrupamiento entre corridas.",
        parameters_sha256=sha256(
            f"disc01c:{source.id}:{run_id}:{exact_text or source.exact_text}".encode()
        ).hexdigest(),
        status="pending",
        created_at=utc_now(),
    )


def prepare_grouping_validation(root: Path) -> dict[str, object]:
    root = root.resolve()
    if current_revision(root) != "0040_discovery_grouping_continuity":
        raise RuntimeError(
            "La copia debe estar migrada a 0040_discovery_grouping_continuity."
        )
    validation_b = json.loads(
        (root / "validation" / "disc01b.json").read_text(encoding="utf-8")
    )
    output = root / "validation" / "disc01c.json"
    if output.exists():
        raise RuntimeError("DISC-01C ya fue preparada en esta copia.")
    decisions_config = load_decisions(root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            assert _count(session, DiscoveryDecision) >= 8
            assert _count(session, DiscoveryCandidateGroup) == 0
            assert _count(session, DiscoveryGroupMembership) == 0
            assert _count(session, DiscoveryGroupAction) == 0
            assert _count(session, DiscoveryCandidateContinuity) == 0

            ids = dict(validation_b["candidate_ids_by_text"])
            controlled = {
                text: session.get(DiscoveryCandidate, candidate_id)
                for text, candidate_id in ids.items()
            }
            if any(row is None for row in controlled.values()):
                raise RuntimeError("Faltan candidatos controlados de DISC-01B.")
            source_run = session.get(DiscoveryRun, validation_b["run_id"])
            assert source_run is not None
            source_object = session.get(
                EditableObject, validation_b["controlled_object_id"]
            )
            assert source_object is not None
            source_key = controlled["Dra. Valentina Orbe"].source_key
            if not source_key:
                raise RuntimeError("El candidato controlado no conserva source_key.")

            variant_object = add_editable_object(
                session,
                decisions=decisions_config,
                source_key=source_key,
                page=source_object.page_number,
                object_type=source_object.current_object_type,
                text="Dra Valentina Orbe participó de la revisión normalizada.",
                created_by="validation_script",
                after_object_id=source_object.id,
                note="Objeto controlado para DISC-01C.",
                document_part_id=source_object.document_part_id,
            )
            variant_object.review_status = "approved"
            variant_text = "Dra Valentina Orbe"
            variant_start = variant_object.current_text.index(variant_text)

            duplicate_run = DiscoveryRun(
                id=new_id(),
                project_id=source_run.project_id,
                profile_id=source_run.profile_id,
                authorization_id=source_run.authorization_id,
                profile_name="Validación DISC-01C duplicados",
                profile_snapshot_json={
                    **dict(source_run.profile_snapshot_json or {}),
                    "validation_phase": "DISC-01C",
                },
                provider_key="validation_script",
                provider_version="disc01c_v1",
                method="controlled_duplicate_candidates",
                parameters_sha256=sha256(b"disc01c-controlled-duplicates").hexdigest(),
                corpus_state_sha256=current_editable_state_sha256(
                    session, source_run.project_id
                ),
                page_review_statuses_json=list(source_run.page_review_statuses_json or ()),
                status="completed",
                object_count=2,
                candidate_count=3,
                family_counts_json={"actor": 2, "work": 1},
                created_by="validation_script",
                started_at=utc_now(),
                finished_at=utc_now(),
                error_message=None,
            )
            session.add(duplicate_run)
            session.flush()

            duplicate_ministry = _clone_candidate(
                controlled["Ministerio de Archivos Imaginarios"],
                run_id=duplicate_run.id,
            )
            duplicate_work = _clone_candidate(
                controlled["Cuaderno del Delta"],
                run_id=duplicate_run.id,
            )
            normalized_person = _clone_candidate(
                controlled["Dra. Valentina Orbe"],
                run_id=duplicate_run.id,
                editable_object=variant_object,
                exact_text=variant_text,
                start_offset=variant_start,
                end_offset=variant_start + len(variant_text),
            )
            session.add_all([duplicate_ministry, duplicate_work, normalized_person])
            session.flush()

            previous_revision = source_object.revision_number
            update_editable_object(
                session,
                decisions=decisions_config,
                object_id=source_object.id,
                expected_revision=previous_revision,
                edited_by="validation_script",
                text="Prefacio agregado para DISC-01C. " + source_object.current_text,
                note="Genera candidatos obsoletos controlados para validar continuidad.",
            )
            session.flush()

            counts = {
                "authority_records": _count(session, AuthorityRecord),
                "entity_mentions": _count(session, EntityMention),
                "entity_relations": _count(session, EntityRelation),
                "discovery_decisions": _count(session, DiscoveryDecision),
                "discovery_context_records": _count(session, DiscoveryContextRecord),
                "discovery_runs": _count(session, DiscoveryRun),
                "discovery_candidates": _count(session, DiscoveryCandidate),
            }
            payload = {
                "project_root": str(root),
                "revision": current_revision(root),
                "project_id": source_run.project_id,
                "source_run_id": source_run.id,
                "duplicate_run_id": duplicate_run.id,
                "controlled_object_id": source_object.id,
                "controlled_object_revision_before": previous_revision,
                "controlled_object_revision_after": source_object.revision_number,
                "variant_object_id": variant_object.id,
                "candidate_ids": {
                    "ministry_original": controlled[
                        "Ministerio de Archivos Imaginarios"
                    ].id,
                    "ministry_duplicate": duplicate_ministry.id,
                    "person_original": controlled["Dra. Valentina Orbe"].id,
                    "person_normalized_variant": normalized_person.id,
                    "work_original": controlled["Cuaderno del Delta"].id,
                    "work_duplicate": duplicate_work.id,
                    "manual_event": controlled["operativo Horizonte"].id,
                },
                "additional_candidate_id": None,
                "counts_after_preparation": counts,
            }
            # La decisión accidental del usuario puede no existir en tests automatizados.
            manifestation = session.scalar(
                select(DiscoveryCandidate).where(
                    DiscoveryCandidate.project_id == source_run.project_id,
                    DiscoveryCandidate.exact_text == "manifestación",
                )
            )
            if manifestation is not None:
                payload["additional_candidate_id"] = manifestation.id
    finally:
        engine.dispose()

    payload["validation_path"] = str(output)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "project_root",
        nargs="?",
        type=Path,
        default=Path("project_data_open_discovery_validation"),
    )
    args = parser.parse_args()
    result = prepare_grouping_validation(args.project_root)
    print("Copia preparada:", result["project_root"])
    print("Revisión:", result["revision"])
    print("Corrida original:", result["source_run_id"])
    print("Corrida controlada adicional:", result["duplicate_run_id"])
    print("Candidatos totales después de preparar:", result["counts_after_preparation"]["discovery_candidates"])
    print("Revisión textual controlada:", result["controlled_object_revision_before"], "→", result["controlled_object_revision_after"])
    print("Datos de validación:", result["validation_path"])
    print("No se creó ningún grupo, pertenencia, acción de grupo ni continuidad.")


if __name__ == "__main__":
    main()
