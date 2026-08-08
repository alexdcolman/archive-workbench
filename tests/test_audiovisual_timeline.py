from __future__ import annotations

import json
import zipfile
from pathlib import Path

from sqlalchemy import inspect, select

from archive_workbench.audiovisual import (
    archive_timeline_annotation,
    assign_speaker_from_time,
    create_timeline_annotation,
    export_transcript_segments_bytes,
    register_transcription_backend,
    timeline_annotation_rows,
    transcript_with_timeline_marks,
    transcribe_audiovisual,
)
from archive_workbench.contracts.audiovisual import TranscriptionRequest
from archive_workbench.audiovisual_review_component import build_synchronized_review_payload
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import (
    AudiovisualMedia,
    AudiovisualTimelineAnnotation,
    AudiovisualTimelineAnnotationRevision,
    AuthorityRecord,
    DigitalObject,
)
from archive_workbench.exchange import _editable_state_payload, ensure_exchange_workspace
from archive_workbench.identity import new_id
from archive_workbench.state_adoption import _synchronize_editable_state, create_state_adoption_package
from tests.test_audiovisual import _FakeBackend, _project


def test_0046_adds_timeline_annotation_tables(tmp_path: Path) -> None:
    root = tmp_path / "project"
    upgrade_database(root, revision="0045_audiovisual_transcription")
    assert current_revision(root) == "0045_audiovisual_transcription"

    upgrade_database(root)
    assert current_revision(root) == "0046_audiovisual_timeline_annotations"

    engine = create_sqlite_engine(database_path(root))
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {
        "audiovisual_timeline_annotations",
        "audiovisual_timeline_annotation_revisions",
    } <= tables


def test_timeline_marks_survive_retranscription_and_travel_in_state(tmp_path: Path) -> None:
    root, decisions, engine, result, _audio = _project(tmp_path)
    register_transcription_backend(_FakeBackend())
    try:
        with session_scope(engine) as session:
            digital = session.get(DigitalObject, result.digital_object_id)
            assert digital is not None
            media = session.scalar(
                select(AudiovisualMedia).where(AudiovisualMedia.digital_object_id == digital.id)
            )
            assert media is not None
            authority = AuthorityRecord(
                id=new_id(),
                project_id=decisions.project_id,
                entity_type="person",
                preferred_name="Horacio Bau",
                normalized_name="horacio bau",
                description=None,
                lifecycle_status="active",
                review_status="reviewed",
                created_by="test",
                updated_by="test",
                revision=1,
            )
            session.add(authority)
            session.flush()

            first_run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media.id,
                request=TranscriptionRequest(
                    backend="test_backend",
                    model_name="fixture",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8"},
                ),
                actor="test",
            )
            speaker = create_timeline_annotation(
                session,
                media_id=media.id,
                annotation_type="speaker",
                start_time=0.0,
                end_time=1.0,
                label="Horacio Bau",
                authority_id=authority.id,
                actor="alex",
            )
            note = create_timeline_annotation(
                session,
                media_id=media.id,
                annotation_type="annotation",
                start_time=0.5,
                end_time=1.0,
                label="sonríe",
                authority_id=None,
                actor="alex",
            )
            rows = timeline_annotation_rows(session, media_id=media.id)
            assert [row.annotation_type for row in rows] == ["speaker", "annotation"]
            assert rows[0].authority_name == "Horacio Bau"

            marked = transcript_with_timeline_marks(session, run_id=first_run.id)
            assert "Horacio Bau:" in marked
            assert "sonríe" in marked

            payload, count = export_transcript_segments_bytes(
                session,
                project_id=decisions.project_id,
                output_format="jsonl",
            )
            assert count == 2
            exported = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
            assert any(
                mark["label"] == "Horacio Bau"
                for row in exported
                for mark in row["timeline_annotations"]
            )
            assert any(
                mark["label"] == "sonríe"
                for row in exported
                for mark in row["timeline_annotations"]
            )

            second_run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media.id,
                request=TranscriptionRequest(
                    backend="test_backend",
                    model_name="fixture-2",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8"},
                ),
                actor="test",
            )
            assert second_run.id != first_run.id
            assert {row.annotation_id for row in timeline_annotation_rows(session, media_id=media.id)} == {
                speaker.id,
                note.id,
            }

            ensure_exchange_workspace(
                session, workspace_name="copia-timeline-origen", changed_by="test"
            )
            package = create_state_adoption_package(
                session,
                project_root=root,
                target_workspace_id=new_id(),
                target_workspace_name="copia-timeline-destino",
                created_by="test",
                creation_reason="Validar transporte de marcas temporales",
                package_confirmed=True,
                destination=root / "exchange" / "timeline_state_test.zip",
            )
            with zipfile.ZipFile(package.output_path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                state = json.loads(archive.read("state.json"))
            assert manifest["schema_version"] == "1.2"
            assert len(state["audiovisual_timeline_annotations"]) == 2
            assert len(state["audiovisual_timeline_annotation_revisions"]) == 2

            captured_state = _editable_state_payload(session, decisions.project_id)
            for row in session.scalars(select(AudiovisualTimelineAnnotationRevision)).all():
                session.delete(row)
            for row in session.scalars(select(AudiovisualTimelineAnnotation)).all():
                session.delete(row)
            session.flush()
            assert timeline_annotation_rows(session, media_id=media.id) == []
            _synchronize_editable_state(
                session,
                project_id=decisions.project_id,
                state=captured_state,
                actor="receiver",
            )
            restored = timeline_annotation_rows(session, media_id=media.id)
            assert {row.label for row in restored} == {"Horacio Bau", "sonríe"}

            archive_timeline_annotation(session, annotation_id=note.id, actor="alex")
            assert [row.annotation_id for row in timeline_annotation_rows(session, media_id=media.id)] == [
                speaker.id
            ]
            revisions = session.scalars(
                select(AudiovisualTimelineAnnotationRevision)
                .where(AudiovisualTimelineAnnotationRevision.annotation_id == note.id)
                .order_by(AudiovisualTimelineAnnotationRevision.revision_number)
            ).all()
            assert [row.operation for row in revisions] == ["create", "archive"]
    finally:
        engine.dispose()


def test_assign_speaker_from_time_closes_previous_turn(tmp_path: Path) -> None:
    root, decisions, engine, result, _audio = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            media = session.scalar(
                select(AudiovisualMedia).where(
                    AudiovisualMedia.digital_object_id == result.digital_object_id
                )
            )
            assert media is not None
            authority_a = AuthorityRecord(
                id=new_id(),
                project_id=decisions.project_id,
                entity_type="person",
                preferred_name="Horacio Bau",
                normalized_name="horacio bau",
                description=None,
                lifecycle_status="active",
                review_status="reviewed",
                created_by="test",
                updated_by="test",
                revision=1,
            )
            authority_b = AuthorityRecord(
                id=new_id(),
                project_id=decisions.project_id,
                entity_type="person",
                preferred_name="Entrevistadora",
                normalized_name="entrevistadora",
                description=None,
                lifecycle_status="active",
                review_status="reviewed",
                created_by="test",
                updated_by="test",
                revision=1,
            )
            session.add_all([authority_a, authority_b])
            session.flush()

            first = assign_speaker_from_time(
                session,
                media_id=media.id,
                time_seconds=0.2,
                label="Horacio Bau",
                authority_id=authority_a.id,
                actor="alex",
            )
            second = assign_speaker_from_time(
                session,
                media_id=media.id,
                time_seconds=0.8,
                label="Entrevistadora",
                authority_id=authority_b.id,
                actor="alex",
            )
            assert first.id != second.id
            rows = [
                row
                for row in timeline_annotation_rows(session, media_id=media.id)
                if row.annotation_type == "speaker"
            ]
            assert [(row.label, row.start_time, row.end_time) for row in rows] == [
                ("Horacio Bau", 0.2, 0.8),
                ("Entrevistadora", 0.8, float(media.duration_seconds)),
            ]
            revisions = session.scalars(
                select(AudiovisualTimelineAnnotationRevision)
                .where(AudiovisualTimelineAnnotationRevision.annotation_id == first.id)
                .order_by(AudiovisualTimelineAnnotationRevision.revision_number)
            ).all()
            assert [row.operation for row in revisions] == ["create", "update"]
    finally:
        engine.dispose()


def test_synchronized_review_payload_keeps_text_and_links() -> None:
    class Authority:
        id = "authority-1"
        preferred_name = "Horacio Bau"

    segments = [
        type(
            "Segment",
            (),
            {
                "segment_id": "segment-1",
                "start_time": 1.0,
                "end_time": 2.0,
                "text": "Texto corregido",
            },
        )()
    ]
    annotations = [
        type(
            "Mark",
            (),
            {
                "annotation_id": "mark-1",
                "annotation_type": "speaker",
                "start_time": 1.0,
                "end_time": 2.0,
                "label": "Horacio Bau",
                "authority_id": "authority-1",
                "authority_name": "Horacio Bau",
            },
        )()
    ]
    payload = build_synchronized_review_payload(segments, annotations, [Authority()])
    assert payload["segments"][0]["text"] == "Texto corregido"
    assert payload["annotations"][0]["authority_id"] == "authority-1"
    assert payload["speaker_options"] == [
        {
            "value": "authority:authority-1",
            "label": "Horacio Bau",
            "authority_id": "authority-1",
        }
    ]


def test_audiovisual_timeline_ui_is_synchronized_and_secondary_management() -> None:
    root = Path(__file__).parents[1]
    source = (root / "src" / "archive_workbench" / "audiovisual_app.py").read_text(
        encoding="utf-8"
    )
    component = (
        root / "src" / "archive_workbench" / "audiovisual_review_component.py"
    ).read_text(encoding="utf-8")

    for literal in (
        "Revisión sincronizada",
        "Hablante actual",
        "Asignar hablante desde aquí",
        "Agregar anotación aquí",
        "Gestionar anotaciones y hablantes",
        "Transcripción con hablantes y anotaciones",
    ):
        assert literal in source or literal in component

    assert "timeupdate" in component
    assert "scrollIntoView" in component
    assert "setTriggerValue('action'" in component
    assert "Tramo inicial" not in source
    assert "Tramo final" not in source
    assert "Guardar marca" not in source
    assert 'st.session_state[manage_key] = False' in source
