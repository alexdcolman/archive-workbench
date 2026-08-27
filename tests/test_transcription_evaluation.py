from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import wave

import yaml
from sqlalchemy import select

import archive_workbench.audiovisual as audiovisual_module

from archive_workbench.audiovisual import (
    register_transcription_backend,
    transcript_document_text,
    transcript_segment_rows,
    transcribe_audiovisual,
    update_transcript_document,
    update_transcript_segment,
)
from archive_workbench.catalog import ensure_project
from archive_workbench.catalog_management import create_archival_unit, register_local_file
from archive_workbench.contracts.audiovisual import TranscriptSegmentInput, TranscriptionRequest
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import AudiovisualMedia, TranscriptionRun
from archive_workbench.decisions import load_decisions
from archive_workbench.project_init import initialize_project
from archive_workbench.transcription_evaluation import (
    evaluate_transcription_run,
    evaluation_sample,
    original_transcript_text,
)


class _EvaluationBackend:
    key = "evaluation_backend"

    def version(self) -> str:
        return "evaluation-1"

    def transcribe(self, source: Path, *, model_name: str, device: str, language, options):
        return [
            TranscriptSegmentInput(start_time=0.0, end_time=1.0, text="La memoria conserva voces"),
            TranscriptSegmentInput(start_time=1.4, end_time=2.5, text="y documentos importantes"),
            TranscriptSegmentInput(start_time=3.0, end_time=4.2, text="para esta historia"),
            TranscriptSegmentInput(start_time=5.0, end_time=6.0, text="archivo y testimonio"),
            TranscriptSegmentInput(start_time=7.0, end_time=8.0, text="cierre de muestra"),
            TranscriptSegmentInput(start_time=9.0, end_time=10.0, text="segmento final"),
        ]


class _MergedEvaluationBackend:
    key = "merged_evaluation_backend"

    def version(self) -> str:
        return "evaluation-1"

    def transcribe(self, source: Path, *, model_name: str, device: str, language, options):
        return [
            TranscriptSegmentInput(
                start_time=0.0,
                end_time=10.0,
                text=(
                    "La memoria conserva voces y documentos importantes para esta historia "
                    "archivo y testimonio cierre de muestra segmento final"
                ),
            )
        ]


def _write_wav(path: Path, *, seconds: int = 10) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"\x00\x00" * rate * seconds)


def _project(tmp_path: Path):
    root = tmp_path / "project"
    initialize_project(root, template_root=Path(__file__).parents[1] / "config")
    decisions_path = root / "config" / "decisions.yaml"
    data = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    data["project_id"] = "av03_test_project"
    data["project_name"] = "Proyecto AV-03"
    decisions_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    upgrade_database(root)
    decisions = load_decisions(decisions_path)
    audio = root / "corpus" / "audiovisual" / "control.wav"
    _write_wav(audio)
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        ensure_project(session, decisions)
        root_level = next(
            level
            for level in sorted(decisions.archival_levels, key=lambda item: item.display_order)
            if level.enabled and not level.parent_keys
        )
        unit = create_archival_unit(
            session,
            decisions=decisions,
            project_id=decisions.project_id,
            parent_id=None,
            level_key=root_level.key,
            title="Audiovisual",
            created_by="test",
        )
        result = register_local_file(
            session,
            project_root=root,
            project_id=decisions.project_id,
            archival_unit_id=unit.id,
            relative_path=audio.relative_to(root).as_posix(),
            registered_by="test",
        )
        media = session.scalar(
            select(AudiovisualMedia).where(AudiovisualMedia.digital_object_id == result.digital_object_id)
        )
        assert media is not None
        media_id = media.id
    return root, engine, media_id



def test_gpu_memory_monitor_uses_direct_pid_when_visible(monkeypatch) -> None:
    monkeypatch.setattr(audiovisual_module.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(
        audiovisual_module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "123, /opt/archive-workbench/.venv/bin/python, 4096\n", ""
        ),
    )
    assert audiovisual_module._gpu_memory_mib_for_pid(123) == 4096.0


def test_gpu_memory_monitor_maps_container_pid_by_unique_process_name(monkeypatch) -> None:
    monkeypatch.setenv("ARCHIVE_WORKBENCH_RUNTIME_VARIANT", "gpu")
    monkeypatch.setattr(audiovisual_module.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    process_name = f"/opt/archive-workbench/.venv/bin/{Path(sys.executable).name}"
    monkeypatch.setattr(
        audiovisual_module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, f"1227410, {process_name}, 5394\n", ""
        ),
    )
    assert audiovisual_module._gpu_memory_mib_for_pid(74) == 5394.0


def test_gpu_memory_monitor_keeps_container_fallback_ambiguous(monkeypatch) -> None:
    monkeypatch.setenv("ARCHIVE_WORKBENCH_RUNTIME_VARIANT", "gpu")
    monkeypatch.setattr(audiovisual_module.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    process_name = f"/opt/archive-workbench/.venv/bin/{Path(sys.executable).name}"
    monkeypatch.setattr(
        audiovisual_module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            f"1227410, {process_name}, 5394\n1227420, {process_name}, 2048\n",
            "",
        ),
    )
    assert audiovisual_module._gpu_memory_mib_for_pid(74) is None

def test_transcription_run_records_runtime_metrics_without_schema_change(tmp_path: Path) -> None:
    root, engine, media_id = _project(tmp_path)
    register_transcription_backend(_EvaluationBackend())
    try:
        with session_scope(engine) as session:
            run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media_id,
                request=TranscriptionRequest(
                    backend="evaluation_backend",
                    model_name="fixture",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8", "vad_filter": True},
                ),
                actor="test",
            )
            assert run.status == "completed"
            metrics = run.options_json["_runtime_metrics"]
            assert metrics["wall_seconds"] >= 0
            assert metrics["process_cpu_seconds"] >= 0
            assert metrics["average_cpu_cores"] is None or metrics["average_cpu_cores"] >= 0
            assert "peak_rss_mib" in metrics
            assert metrics["peak_gpu_memory_mib"] is None
    finally:
        engine.dispose()


def test_evaluation_uses_deterministic_five_segment_sample_and_human_corrections(tmp_path: Path) -> None:
    root, engine, media_id = _project(tmp_path)
    register_transcription_backend(_EvaluationBackend())
    try:
        with session_scope(engine) as session:
            run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media_id,
                request=TranscriptionRequest(
                    backend="evaluation_backend",
                    model_name="fixture",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8", "vad_filter": True},
                ),
                actor="test",
            )
            rows = transcript_segment_rows(session, run_id=run.id)
            sample = evaluation_sample(rows, sample_size=5)
            assert [item.segment_index for item in sample] == [0, 1, 2, 4, 5]

            for item in sample:
                row = next(row for row in rows if row.segment_id == item.segment_id)
                corrected = row.original_text
                if item.ordinal == 1:
                    corrected = "La memoria conserva las voces"
                update_transcript_segment(
                    session,
                    segment_id=row.segment_id,
                    corrected_text=corrected,
                    review_status="reviewed",
                    actor="test",
                    note="Muestra AV-03",
                )

            evaluation = evaluate_transcription_run(session, run_id=run.id, sample_size=5)
            assert evaluation.sample_size == 5
            assert evaluation.reviewed_sample_count == 5
            assert evaluation.sample_complete is True
            assert evaluation.sample_cer is not None and evaluation.sample_cer > 0
            assert evaluation.sample_wer is not None and evaluation.sample_wer > 0
            assert evaluation.segment_count == 6
            assert evaluation.total_gap_seconds > 0
            assert evaluation.realtime_factor is not None
            assert b'"sample_complete": true' in evaluation.to_json_bytes()
    finally:
        engine.dispose()



def test_continuous_transcript_edit_updates_only_changed_temporal_anchors(tmp_path: Path) -> None:
    root, engine, media_id = _project(tmp_path)
    register_transcription_backend(_EvaluationBackend())
    try:
        with session_scope(engine) as session:
            run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media_id,
                request=TranscriptionRequest(
                    backend="evaluation_backend",
                    model_name="fixture",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8", "vad_filter": True},
                ),
                actor="test",
            )
            before = transcript_document_text(session, run_id=run.id)
            assert "La memoria conserva voces y documentos importantes" in before

            edited = before.replace(
                "La memoria conserva voces y documentos importantes",
                "La memoria conserva voces, documentos y testimonios importantes",
            )
            result = update_transcript_document(
                session,
                run_id=run.id,
                corrected_text=edited,
                actor="alex",
            )

            assert result.total_segment_count == 6
            assert result.changed_segment_count >= 1
            assert transcript_document_text(session, run_id=run.id) == edited
            rows = transcript_segment_rows(session, run_id=run.id)
            assert [row.start_time for row in rows] == [0.0, 1.4, 3.0, 5.0, 7.0, 9.0]
            assert [row.end_time for row in rows] == [1.0, 2.5, 4.2, 6.0, 8.0, 10.0]
            assert any(row.revision_number > 1 for row in rows)
    finally:
        engine.dispose()


def test_continuous_transcript_edit_can_remove_hallucinated_text_without_losing_run(tmp_path: Path) -> None:
    root, engine, media_id = _project(tmp_path)
    register_transcription_backend(_EvaluationBackend())
    try:
        with session_scope(engine) as session:
            run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media_id,
                request=TranscriptionRequest(
                    backend="evaluation_backend",
                    model_name="fixture",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8", "vad_filter": True},
                ),
                actor="test",
            )
            before = transcript_document_text(session, run_id=run.id)
            edited = before.replace("archivo y testimonio ", "")
            update_transcript_document(
                session,
                run_id=run.id,
                corrected_text=edited,
                actor="alex",
            )
            assert transcript_document_text(session, run_id=run.id) == edited
            assert len(transcript_segment_rows(session, run_id=run.id)) == 6
    finally:
        engine.dispose()

def test_original_transcript_text_ignores_human_corrections(tmp_path: Path) -> None:
    root, engine, media_id = _project(tmp_path)
    register_transcription_backend(_EvaluationBackend())
    try:
        with session_scope(engine) as session:
            run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media_id,
                request=TranscriptionRequest(
                    backend="evaluation_backend",
                    model_name="fixture",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8", "vad_filter": True},
                ),
                actor="test",
            )
            row = transcript_segment_rows(session, run_id=run.id)[0]
            update_transcript_segment(
                session,
                segment_id=row.segment_id,
                corrected_text="La memoria conserva las voces",
                review_status="reviewed",
                actor="test",
            )
            assert "La memoria conserva voces" in original_transcript_text(session, run_id=run.id)
            assert "La memoria conserva las voces" not in original_transcript_text(
                session, run_id=run.id
            )
            assert "La memoria conserva las voces" in transcript_document_text(session, run_id=run.id)
    finally:
        engine.dispose()


def test_reference_comparison_uses_original_text_even_for_reference_run(tmp_path: Path) -> None:
    from archive_workbench.transcription_evaluation import compare_transcription_to_reviewed_reference

    root, engine, media_id = _project(tmp_path)
    register_transcription_backend(_EvaluationBackend())
    try:
        with session_scope(engine) as session:
            run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media_id,
                request=TranscriptionRequest(
                    backend="evaluation_backend",
                    model_name="fixture",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8", "vad_filter": True},
                ),
                actor="test",
            )
            rows = transcript_segment_rows(session, run_id=run.id)
            for item in evaluation_sample(rows, sample_size=5):
                row = next(row for row in rows if row.segment_id == item.segment_id)
                corrected = (
                    "La memoria conserva las voces" if item.ordinal == 1 else row.original_text
                )
                update_transcript_segment(
                    session,
                    segment_id=row.segment_id,
                    corrected_text=corrected,
                    review_status="reviewed",
                    actor="test",
                )
            comparison = compare_transcription_to_reviewed_reference(
                session,
                reference_run_id=run.id,
                candidate_run_id=run.id,
                sample_size=5,
            )
            assert comparison.wer is not None and comparison.wer > 0
            assert comparison.windows[0].candidate_text == "La memoria conserva voces"
            assert comparison.windows[0].reference_text == "La memoria conserva las voces"
            assert all(window.scoreable for window in comparison.windows)
    finally:
        engine.dispose()


def test_reference_comparison_does_not_score_coarse_overlapping_segment(tmp_path: Path) -> None:
    from archive_workbench.transcription_evaluation import compare_transcription_to_reviewed_reference

    root, engine, media_id = _project(tmp_path)
    register_transcription_backend(_EvaluationBackend())
    register_transcription_backend(_MergedEvaluationBackend())
    try:
        with session_scope(engine) as session:
            reference = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media_id,
                request=TranscriptionRequest(
                    backend="evaluation_backend",
                    model_name="reference",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8", "vad_filter": True},
                ),
                actor="test",
            )
            rows = transcript_segment_rows(session, run_id=reference.id)
            for item in evaluation_sample(rows, sample_size=5):
                row = next(row for row in rows if row.segment_id == item.segment_id)
                update_transcript_segment(
                    session,
                    segment_id=row.segment_id,
                    corrected_text=row.original_text,
                    review_status="reviewed",
                    actor="test",
                )
            candidate = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media_id,
                request=TranscriptionRequest(
                    backend="merged_evaluation_backend",
                    model_name="candidate",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8", "vad_filter": True},
                ),
                actor="test",
            )
            comparison = compare_transcription_to_reviewed_reference(
                session,
                reference_run_id=reference.id,
                candidate_run_id=candidate.id,
                sample_size=5,
            )
            assert comparison.wer is None
            assert comparison.cer is None
            assert comparison.candidate_words > 0
            assert comparison.reference_words > 0
            assert all(window.candidate_context_text for window in comparison.windows)
            assert any(not window.scoreable for window in comparison.windows)
            assert all(
                window.candidate_context_text == window.candidate_text
                for window in comparison.windows
            )
    finally:
        engine.dispose()


def test_audiovisual_ui_exposes_av03_evaluation_without_duplication() -> None:
    root = Path(__file__).parents[1]
    ui = (root / "src" / "archive_workbench" / "audiovisual_app.py").read_text(encoding="utf-8")

    for literal in (
        "Evaluar la calidad de esta versión de la transcripción",
        "Tiempo y uso de memoria de esta transcripción automática",
        "Tiempo de procesamiento respecto de la duración del audio",
        "Pico de memoria RAM durante la transcripción",
        "Cómo quedó dividida la transcripción",
        "Cinco fragmentos revisados para comparar transcripciones",
        "Transcripción completa",
        "Guardar las correcciones de esta transcripción",
        "Caracteres diferentes respecto de la referencia",
        "Palabras diferentes respecto de la referencia",
        "Descargar evaluación de transcripción",
        "Comparar esta versión con otra transcripción del mismo audio",
        "Ver comparación de los cinco fragmentos revisados",
        "Ver transcripciones automáticas completas",
        "Descargar large-v3 original",
    ):
        assert literal in ui
    for obsolete in (
        "Factor tiempo-real",
        "Muestra reproducible de corrección humana",
        "Navegar por tiempos y segmentos",
        "Segmento temporal",
        "CER de corrección",
        "WER de corrección",
        "Descargar evaluación AV-03",
        "Ver comparación de las cinco referencias humanas",
        "Probar reconocimiento de mayor calidad (GPU)",
    ):
        assert obsolete not in ui
    assert 'evaluation_key = f"av_evaluation_open_{selected_run_id}"' in ui
    assert 'st.session_state[evaluation_key] = False' in ui
    assert 'comparison_open = st.toggle(' in ui
    assert '"Comparar esta versión con otra transcripción del mismo audio"' in ui
    assert "Corregilos con el bloque principal" not in ui
    assert "Corrección del segmento" not in ui
    assert "st.session_state[editor_key] = transcript_text.strip()" not in ui
    assert 'getattr(st, "iframe", None)' in ui
    assert "iframe(script, height=1, width=1)" in ui
    assert "component_html(script, height=1, width=1)" in ui
    assert "height=0" not in ui
    assert "Salida large-v3 en el mismo tramo temporal" in ui
    assert "large-v3 original alineado" not in ui
    assert "WER large-v3" not in ui


def test_run_comparison_reuses_reviewed_reference_windows(tmp_path: Path) -> None:
    from archive_workbench.transcription_evaluation import (
        compare_transcription_to_reviewed_reference,
        reviewed_reference_run_id,
    )

    root, engine, media_id = _project(tmp_path)
    register_transcription_backend(_EvaluationBackend())
    try:
        with session_scope(engine) as session:
            reference = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media_id,
                request=TranscriptionRequest(
                    backend="evaluation_backend",
                    model_name="baseline",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8", "vad_filter": True},
                ),
                actor="test",
            )
            rows = transcript_segment_rows(session, run_id=reference.id)
            for item in evaluation_sample(rows, sample_size=5):
                row = next(row for row in rows if row.segment_id == item.segment_id)
                update_transcript_segment(
                    session,
                    segment_id=row.segment_id,
                    corrected_text=row.original_text,
                    review_status="reviewed",
                    actor="test",
                    note="referencia",
                )

            candidate = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media_id,
                request=TranscriptionRequest(
                    backend="evaluation_backend",
                    model_name="candidate",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8", "vad_filter": True},
                ),
                actor="test",
            )
            assert reviewed_reference_run_id(session, media_id=media_id) == reference.id
            comparison = compare_transcription_to_reviewed_reference(
                session,
                reference_run_id=reference.id,
                candidate_run_id=candidate.id,
                sample_size=5,
            )
            assert comparison.sample_size == 5
            assert comparison.wer == 0
            assert comparison.cer == 0
            assert len(comparison.windows) == 5
    finally:
        engine.dispose()


def test_audiovisual_ui_exposes_gpu_quality_comparison() -> None:
    root = Path(__file__).parents[1]
    ui = (root / "src" / "archive_workbench" / "audiovisual_app.py").read_text(encoding="utf-8")
    backend = (root / "src" / "archive_workbench" / "audiovisual.py").read_text(encoding="utf-8")

    for literal in (
        "Comparar esta versión con otra transcripción del mismo audio",
        "Vocabulario esperado (opcional)",
        "Generar comparación con large-v3 en GPU",
        'model_name="large-v3"',
        'device="cuda"',
        '"compute_type": "float16"',
        '"_av03_profile": quality_profile',
        "selected_is_large_gpu",
        "La versión seleccionada ya fue creada con large-v3 en GPU",
    ):
        assert literal in ui
    assert "Probar reconocimiento de mayor calidad (GPU)" not in ui
    assert 'transcribe_kwargs["hotwords"] = hotwords' in backend
