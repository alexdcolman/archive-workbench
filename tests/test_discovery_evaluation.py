from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from archive_workbench.cli import app
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.discovery_evaluation import (
    compare_evaluation_reports,
    evaluate_discovery_provider,
    load_evaluation_corpus,
    write_evaluation_report,
)
from archive_workbench.discovery_providers import detect_with_provider
from archive_workbench.open_discovery import (
    DiscoveryProfileValues,
    discovery_candidate_rows,
    run_open_discovery,
    save_discovery_profile,
)
from tests.test_open_discovery import _seed_discovery_project

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "config" / "discovery_evaluation_corpus.jsonl"
DISC03_CORPUS = ROOT / "config" / "discovery_evaluation_corpus_disc03.jsonl"
DISC03_REAL_PATTERN_CORPUS = ROOT / "config" / "discovery_evaluation_corpus_disc03_real_patterns.jsonl"
DISC03_RC68_CORPUS = ROOT / "config" / "discovery_evaluation_corpus_disc03_rc68.jsonl"
DISC03_LOCAL_FAMILIES = ("actor", "space", "time", "event", "action_process", "work")


class _FakeEntity:
    def __init__(self, text: str, start: int, label: str) -> None:
        self.text = text
        self.start_char = start
        self.end_char = start + len(text)
        self.label_ = label


class _FakeSpacyPipeline:
    meta = {"version": "9.9.9"}

    def __call__(self, text: str):
        exact = "Valentina Orbe"
        return SimpleNamespace(
            ents=[_FakeEntity(exact, text.index(exact), "PER")]
        )


def test_initial_evaluation_corpus_covers_every_family_and_preserves_offsets() -> None:
    corpus = load_evaluation_corpus(CORPUS)
    families = {
        annotation.family
        for record in corpus.records
        for annotation in record.annotations
    }
    assert families == {
        "actor",
        "space",
        "time",
        "event",
        "action_process",
        "work",
        "other",
    }
    assert len(corpus.sha256) == 64
    for record in corpus.records:
        assert record.source["kind"] == "synthetic_control"
        for annotation in record.annotations:
            assert record.text[annotation.start : annotation.end] == annotation.text


def test_local_provider_evaluation_reports_metrics_by_family() -> None:
    result = evaluate_discovery_provider(
        CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v1",
    )
    payload = result.payload
    assert payload["corpus"]["record_count"] == 7
    assert payload["corpus"]["annotation_count"] == 7
    assert payload["metrics"]["micro"] == {
        "true_positive": 6,
        "false_positive": 0,
        "false_negative": 1,
        "precision": 1.0,
        "recall": 0.857143,
        "f1": 0.923077,
    }
    assert payload["metrics"]["by_family"]["other"]["recall"] == 0.0
    assert payload["errors"][0]["kind"] == "false_negative"
    assert payload["errors"][0]["expected"]["text"] == "ZX-9"
    assert len(payload["parameters"]["sha256"]) == 64
    assert len(result.report_sha256) == 64


def test_evaluation_rejects_annotation_whose_offsets_do_not_match(tmp_path: Path) -> None:
    path = tmp_path / "invalid.jsonl"
    path.write_text(
        json.dumps(
            {
                "record_id": "bad",
                "text": "Texto breve",
                "source": {"kind": "test"},
                "annotations": [
                    {
                        "start": 0,
                        "end": 5,
                        "text": "Otra",
                        "family": "other",
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="texto exacto no coincide"):
        load_evaluation_corpus(path)


def test_spacy_adapter_uses_same_detection_contract(monkeypatch) -> None:
    import archive_workbench.discovery_providers as providers

    monkeypatch.setattr(providers.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        providers,
        "_load_spacy_pipeline",
        lambda _model_name: _FakeSpacyPipeline(),
    )
    text = "La investigadora Valentina Orbe llegó."
    contract, rows = detect_with_provider(
        text,
        families=("actor",),
        provider_key="spacy_ner",
        provider_version="modelo_control@9.9.9",
    )
    assert contract.method == "spacy_doc_ents"
    assert contract.model_name == "modelo_control"
    assert rows[0].exact_text == "Valentina Orbe"
    assert rows[0].family == "actor"
    assert rows[0].confidence is None


def test_spacy_profile_persists_provider_and_model_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    import archive_workbench.discovery_providers as providers

    monkeypatch.setattr(providers.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        providers,
        "_load_spacy_pipeline",
        lambda _model_name: _FakeSpacyPipeline(),
    )
    root = tmp_path / "spacy_project"
    _seed_discovery_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(
                    name="spaCy control",
                    families=("actor",),
                    provider_key="spacy_ner",
                    provider_version="modelo_control@9.9.9",
                ),
                changed_by="tests",
            )
            summary = run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            rows = discovery_candidate_rows(
                session,
                project_id="search_project",
                run_id=summary.run_id,
            )
            assert rows
            assert all(row.provider_key == "spacy_ner" for row in rows)
            assert all(row.provider_version == "modelo_control@9.9.9" for row in rows)
            assert all(row.method == "spacy_doc_ents" for row in rows)
    finally:
        engine.dispose()


def test_report_hash_does_not_depend_on_corpus_path(tmp_path: Path) -> None:
    copied = tmp_path / "copied-corpus.jsonl"
    copied.write_bytes(CORPUS.read_bytes())
    original = evaluate_discovery_provider(
        CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v1",
    )
    relocated = evaluate_discovery_provider(
        copied,
        provider_key="local_deterministic",
        provider_version="local_rules_v1",
    )
    assert original.report_sha256 == relocated.report_sha256


def test_reports_compare_only_when_the_corpus_is_identical(tmp_path: Path) -> None:
    result = evaluate_discovery_provider(
        CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v1",
    )
    first = write_evaluation_report(result, tmp_path / "first.json")
    second = write_evaluation_report(result, tmp_path / "second.json")
    comparison = compare_evaluation_reports((first, second))
    assert comparison["corpus_sha256"] == result.payload["corpus"]["sha256"]
    assert len(comparison["reports"]) == 2
    assert (
        comparison["reports"][0]["parameters_sha256"]
        == comparison["reports"][1]["parameters_sha256"]
    )


def test_discovery_evaluate_cli_writes_reproducible_report(tmp_path: Path) -> None:
    output = tmp_path / "evaluation.json"
    result = CliRunner().invoke(
        app,
        [
            "discovery-evaluate",
            str(CORPUS),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["provider"]["key"] == "local_deterministic"
    assert "precisión=1.000000" in result.output


def test_disc03_diverse_corpus_keeps_holdout_cases_and_multiple_genres() -> None:
    corpus = load_evaluation_corpus(DISC03_CORPUS)
    genres = {str(record.source.get("genre")) for record in corpus.records}
    cases = {str(record.source.get("case")) for record in corpus.records}
    assert len(corpus.records) == 46
    assert len(genres) >= 7
    assert {
        "holdout_numeric_model",
        "holdout_postposed_person",
        "holdout_bare_toponym",
        "holdout_work_without_class",
        "holdout_event_variant",
        "holdout_finite_action",
    } <= cases
    assert any(not record.annotations for record in corpus.records)


def test_disc03_v2_improves_diverse_audit_without_rewriting_v1() -> None:
    v1 = evaluate_discovery_provider(
        DISC03_CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v1",
        families=DISC03_LOCAL_FAMILIES,
    )
    v2 = evaluate_discovery_provider(
        DISC03_CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v2",
        families=DISC03_LOCAL_FAMILIES,
    )
    assert v1.payload["metrics"]["micro"] == {
        "true_positive": 25,
        "false_positive": 13,
        "false_negative": 11,
        "precision": 0.657895,
        "recall": 0.694444,
        "f1": 0.675676,
    }
    assert v2.payload["metrics"]["micro"] == {
        "true_positive": 31,
        "false_positive": 1,
        "false_negative": 5,
        "precision": 0.96875,
        "recall": 0.861111,
        "f1": 0.911765,
    }
    assert v2.payload["metrics"]["micro"]["f1"] > v1.payload["metrics"]["micro"]["f1"]
    remaining = {
        ((row.get("prediction") or {}).get("text"), (row.get("expected") or {}).get("text"))
        for row in v2.payload["errors"]
    }
    assert ("1984", None) in remaining
    assert (None, "María López") in remaining
    assert (None, "Buenos Aires") in remaining
    assert (None, "Operación Masacre") in remaining
    assert (None, "marcha estudiantil") in remaining
    assert (None, "clasificó") in remaining


def test_disc03_v3_closes_rc66_holdouts_without_changing_v1_v2_metrics() -> None:
    v1 = evaluate_discovery_provider(
        DISC03_CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v1",
        families=DISC03_LOCAL_FAMILIES,
    )
    v2 = evaluate_discovery_provider(
        DISC03_CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v2",
        families=DISC03_LOCAL_FAMILIES,
    )
    v3 = evaluate_discovery_provider(
        DISC03_CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v3",
        families=DISC03_LOCAL_FAMILIES,
    )
    assert v1.payload["metrics"]["micro"]["f1"] == 0.675676
    assert v2.payload["metrics"]["micro"]["f1"] == 0.911765
    assert v3.payload["metrics"]["micro"] == {
        "true_positive": 36,
        "false_positive": 0,
        "false_negative": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }


def test_disc03_real_pattern_regression_is_synthetic_and_separate_from_real_corpus() -> None:
    corpus = load_evaluation_corpus(DISC03_REAL_PATTERN_CORPUS)
    assert len(corpus.records) == 41
    assert all(record.source.get("kind") == "synthetic_real_pattern_audit" for record in corpus.records)
    assert all("pilot_data" not in json.dumps(record.source) for record in corpus.records)
    cases = {str(record.source.get("case")) for record in corpus.records}
    assert {
        "time-domingo-person",
        "time-abbrev-range",
        "work-group-vs-work",
        "actor-testimony",
        "space-deictic",
        "event-put-in-motion",
        "action-repress-generic",
    } <= cases


def test_disc03_v3_handles_patterns_observed_in_real_document_and_audiovisual_audits() -> None:
    v2 = evaluate_discovery_provider(
        DISC03_REAL_PATTERN_CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v2",
        families=DISC03_LOCAL_FAMILIES,
    )
    v3 = evaluate_discovery_provider(
        DISC03_REAL_PATTERN_CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v3",
        families=DISC03_LOCAL_FAMILIES,
    )
    assert v2.payload["metrics"]["micro"] == {
        "true_positive": 15,
        "false_positive": 7,
        "false_negative": 18,
        "precision": 0.681818,
        "recall": 0.454545,
        "f1": 0.545455,
    }
    assert v3.payload["metrics"]["micro"] == {
        "true_positive": 33,
        "false_positive": 0,
        "false_negative": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }


def test_local_provider_v3_preserves_v1_and_v2_as_explicit_historical_versions() -> None:
    text = 'La obra "Crónica del domingo" se presentó en 1959-60.'
    contracts = {}
    detections = {}
    for version in ("local_rules_v1", "local_rules_v2", "local_rules_v3"):
        contract, rows = detect_with_provider(
            text,
            families=("time", "work"),
            provider_key="local_deterministic",
            provider_version=version,
        )
        contracts[version] = contract
        detections[version] = {(row.family, row.exact_text) for row in rows}
    assert contracts["local_rules_v1"].version == "local_rules_v1"
    assert contracts["local_rules_v2"].version == "local_rules_v2"
    assert contracts["local_rules_v3"].version == "local_rules_v3"
    assert ("time", "domingo") in detections["local_rules_v2"]
    assert ("time", "domingo") not in detections["local_rules_v3"]
    assert ("time", "1959-60") in detections["local_rules_v3"]
    assert ("work", "Crónica del domingo") in detections["local_rules_v3"]




def test_disc03_rc68_v4_repairs_entity_boundaries_and_quoted_work_precision() -> None:
    corpus = load_evaluation_corpus(DISC03_RC68_CORPUS)
    assert len(corpus.records) == 17
    assert all(
        record.source.get("kind") == "synthetic_rc68_precision_boundary"
        for record in corpus.records
    )
    result = evaluate_discovery_provider(
        DISC03_RC68_CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v4",
        families=DISC03_LOCAL_FAMILIES,
    )
    assert result.payload["metrics"]["micro"] == {
        "true_positive": 11,
        "false_positive": 0,
        "false_negative": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }


def test_local_provider_v4_and_v5_preserve_history_and_fix_reported_boundaries() -> None:
    text = (
        "La Secretaría General de la Presidencia de la Nación emitió la nota. "
        "Atentado contra Dr. Guillermo W. KLEIN. "
        "El curso estuvo a cargo de la profesora Encarnación Díaz de Mulhall. "
        "Asistió el Sr. Reberte Equiza- Esquel. "
        'La revista Horizonte dijo: "La situación exige prudencia". '
        'Se estrenó la obra "La casa vacía".'
    )
    contracts = {}
    detections = {}
    for version in (
        "local_rules_v1",
        "local_rules_v2",
        "local_rules_v3",
        "local_rules_v4",
        "local_rules_v5",
    ):
        contract, rows = detect_with_provider(
            text,
            families=("actor", "work"),
            provider_key="local_deterministic",
            provider_version=version,
        )
        contracts[version] = contract
        detections[version] = {(row.family, row.exact_text) for row in rows}
    assert [contracts[version].version for version in contracts] == [
        "local_rules_v1",
        "local_rules_v2",
        "local_rules_v3",
        "local_rules_v4",
        "local_rules_v5",
    ]
    assert ("actor", "Secretaría General de la Presidencia de la Nación") in detections["local_rules_v4"]
    assert ("actor", "Dr. Guillermo W. KLEIN") in detections["local_rules_v4"]
    assert ("actor", "profesora Encarnación Díaz de Mulhall") in detections["local_rules_v4"]
    assert ("actor", "Sr. Reberte Equiza") in detections["local_rules_v4"]
    assert ("work", "La situación exige prudencia") not in detections["local_rules_v4"]
    assert ("work", "La casa vacía") in detections["local_rules_v4"]
    assert ("actor", "Secretaría General de la Presidencia de la Nación") in detections["local_rules_v5"]
    assert ("actor", "Dr. Guillermo W. KLEIN") in detections["local_rules_v5"]
    assert ("actor", "profesora Encarnación Díaz de Mulhall") in detections["local_rules_v5"]
    assert ("actor", "Sr. Reberte Equiza") in detections["local_rules_v5"]
    assert ("work", "La situación exige prudencia") not in detections["local_rules_v5"]
    assert ("work", "La casa vacía") in detections["local_rules_v5"]
    assert ("actor", "Secretaría General de la Presidencia de la") in detections["local_rules_v3"]
    assert ("actor", "Dr. Guillermo W") in detections["local_rules_v3"]
    assert ("actor", "profesora Encarnación Díaz") in detections["local_rules_v3"]
    assert ("actor", "Sr. Reberte Equiza- Esquel") in detections["local_rules_v3"]

def test_local_provider_v5_does_not_turn_unrelated_quotes_into_works_from_distant_context() -> None:
    text = (
        'Se analizó la obra completa en el informe. '
        'El testigo se identificó como "El Flaco", de Trelew. '
        'La organización llamó "Plan de acción", de Trelew, a su campaña.'
    )
    _contract_v4, v4 = detect_with_provider(
        text,
        families=("work",),
        provider_key="local_deterministic",
        provider_version="local_rules_v4",
    )
    _contract_v5, v5 = detect_with_provider(
        text,
        families=("work",),
        provider_key="local_deterministic",
        provider_version="local_rules_v5",
    )
    assert {row.exact_text for row in v4} == {"El Flaco", "Plan de acción"}
    assert not v5


def test_disc03_evaluation_errors_preserve_source_metadata() -> None:
    result = evaluate_discovery_provider(
        DISC03_CORPUS,
        provider_key="local_deterministic",
        provider_version="local_rules_v2",
        families=DISC03_LOCAL_FAMILIES,
    )
    false_positive = next(
        row for row in result.payload["errors"] if row["kind"] == "false_positive"
    )
    assert false_positive["prediction"]["source"]["genre"] == "technical"
    assert false_positive["prediction"]["source"]["case"] == "holdout_numeric_model"


def test_local_provider_versions_preserve_historical_v1_behavior() -> None:
    text = 'El testigo dijo: “No vi nada esa noche”. El archivo fue revisado en el expediente 1976/4.'
    _contract_v1, v1 = detect_with_provider(
        text,
        families=("work", "action_process", "time"),
        provider_key="local_deterministic",
        provider_version="local_rules_v1",
    )
    _contract_v2, v2 = detect_with_provider(
        text,
        families=("work", "action_process", "time"),
        provider_key="local_deterministic",
        provider_version="local_rules_v2",
    )
    assert {(row.family, row.exact_text) for row in v1} >= {
        ("work", "No vi nada esa noche"),
        ("action_process", "archivo"),
        ("time", "1976"),
    }
    assert not {
        ("work", "No vi nada esa noche"),
        ("action_process", "archivo"),
        ("time", "1976"),
    } & {(row.family, row.exact_text) for row in v2}


def test_v2_time_filter_does_not_depend_on_work_family_being_selected() -> None:
    _contract, rows = detect_with_provider(
        'El informe “Balance anual 1984” quedó incorporado.',
        families=("time",),
        provider_key="local_deterministic",
        provider_version="local_rules_v2",
    )
    assert not [row for row in rows if row.family == "time" and row.exact_text == "1984"]
