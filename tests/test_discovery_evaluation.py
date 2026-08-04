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
