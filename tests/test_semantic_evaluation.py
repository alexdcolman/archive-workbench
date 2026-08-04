from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from archive_workbench.cli import app
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import EditableObject, EditablePage
from archive_workbench.identity import new_id
from archive_workbench.semantic_evaluation import (
    compare_semantic_evaluation_reports,
    evaluate_semantic_search,
    load_semantic_evaluation_corpus,
    write_semantic_evaluation_report,
)
from archive_workbench.semantic_search import (
    SemanticProfileValues,
    build_semantic_index,
    save_semantic_profile,
)
from tests.test_search import _seed_search_project


class EvaluationBackend:
    @staticmethod
    def _vector(text: str) -> list[float]:
        value = text.casefold()
        cultural = sum(term in value for term in ("teat", "cultur", "investig", "vigil"))
        economic = sum(term in value for term in ("carne", "precio", "econom", "mercado"))
        if cultural == 0 and economic == 0:
            return [0.5, 0.5]
        return [float(cultural), float(economic)]

    def encode_documents(self, texts, *, batch_size: int):
        return [self._vector(text) for text in texts]

    def encode_queries(self, texts, *, batch_size: int):
        return [self._vector(text) for text in texts]


def _seed_economic_object(root: Path) -> str:
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page is not None
            row = EditableObject(
                id=new_id(),
                editable_page_id=page.id,
                digital_object_id=page.digital_object_id,
                page_number=page.page_number,
                source_extracted_object_id=None,
                source_origin_id=None,
                current_text="El precio de la carne aumentó en el mercado local",
                current_object_type="paragraph",
                current_order_index=1,
                current_geometry_json=[],
                current_attributes_json={"manual": True},
                lifecycle_status="active",
                review_status="approved",
                revision_number=1,
                created_by="tests",
                updated_by="tests",
            )
            session.add(row)
            session.flush()
            return row.id
    finally:
        engine.dispose()


def _write_corpus(path: Path, cultural_id: str, economic_id: str) -> None:
    rows = [
        {
            "case_id": "cultural",
            "query": "vigilancia cultural",
            "query_kind": "positive",
            "fragment_type": "object",
            "target_field": "object_id",
            "expected": [cultural_id],
        },
        {
            "case_id": "economica",
            "query": "precio del mercado",
            "query_kind": "positive",
            "fragment_type": "object",
            "target_field": "object_id",
            "expected": [economic_id],
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
            "expected": [cultural_id, economic_id],
            "notes": "Ambas respuestas son pertinentes.",
        },
    ]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_semantic_evaluation_calibrates_thresholds_and_preserves_scope(tmp_path: Path) -> None:
    root = tmp_path / "project"
    cultural_id, _page_id = _seed_search_project(root)
    economic_id = _seed_economic_object(root)
    corpus = tmp_path / "queries.jsonl"
    _write_corpus(corpus, cultural_id, economic_id)
    backend = EvaluationBackend()
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_semantic_profile(
                session,
                project_id="search_project",
                values=SemanticProfileValues(
                    name="Evaluación",
                    model_name="fake/model",
                    model_revision="test",
                    aggregation_level="object",
                    query_prefix="",
                    document_prefix="",
                ),
                changed_by="tests",
            )
            summary = build_semantic_index(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                created_by="tests",
                backend=backend,
            )
            result = evaluate_semantic_search(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                corpus_path=corpus,
                thresholds=(0.7, 0.8),
                top_k=10,
                backend=backend,
            )
    finally:
        engine.dispose()

    payload = result.payload
    assert payload["index"]["run_id"] == summary.run_id
    assert payload["profile"]["model_name"] == "fake/model"
    assert payload["corpus"]["fragment_type"] == "object"
    assert payload["recommended_threshold"]["value"] == 0.7
    assert payload["recommended_threshold"]["micro"] == {
        "true_positive": 4,
        "false_positive": 2,
        "false_negative": 0,
        "precision": 0.666667,
        "recall": 1.0,
        "f1": 0.8,
    }
    at_08 = next(
        row for row in payload["metrics_by_threshold"] if row["threshold"] == 0.8
    )
    assert at_08["micro"]["false_positive"] == 0
    assert at_08["micro"]["false_negative"] == 2
    assert at_08["by_query_kind"]["ambiguous"]["case_count"] == 1
    assert "no constituye un umbral universal" in payload["recommended_threshold"]["scope_note"]


def test_semantic_evaluation_report_is_reproducible_and_comparable(tmp_path: Path) -> None:
    root = tmp_path / "project"
    cultural_id, _page_id = _seed_search_project(root)
    economic_id = _seed_economic_object(root)
    corpus = tmp_path / "queries.jsonl"
    _write_corpus(corpus, cultural_id, economic_id)
    backend = EvaluationBackend()
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_semantic_profile(
                session,
                project_id="search_project",
                values=SemanticProfileValues(
                    name="Evaluación",
                    model_name="fake/model",
                    model_revision="test",
                    aggregation_level="object",
                    query_prefix="",
                    document_prefix="",
                ),
                changed_by="tests",
            )
            build_semantic_index(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                created_by="tests",
                backend=backend,
            )
            first = evaluate_semantic_search(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                corpus_path=corpus,
                thresholds=(0.7, 0.8),
                backend=backend,
            )
            second = evaluate_semantic_search(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                corpus_path=corpus,
                thresholds=(0.7, 0.8),
                backend=backend,
            )
    finally:
        engine.dispose()

    assert first.report_sha256 == second.report_sha256
    first_path = write_semantic_evaluation_report(first, tmp_path / "first.json")
    second_path = write_semantic_evaluation_report(second, tmp_path / "second.json")
    comparison = compare_semantic_evaluation_reports([first_path, second_path])
    assert comparison["corpus_sha256"] == first.payload["corpus"]["sha256"]
    assert comparison["fragment_type"] == "object"
    assert len(comparison["reports"]) == 2
    assert comparison["reports"][0]["recommended_threshold"] == 0.7


def test_semantic_evaluation_corpus_rejects_invalid_negative_case(tmp_path: Path) -> None:
    corpus = tmp_path / "invalid.jsonl"
    corpus.write_text(
        json.dumps(
            {
                "case_id": "negative-with-target",
                "query": "consulta ajena",
                "query_kind": "negative",
                "fragment_type": "object",
                "target_field": "record_id",
                "expected": ["unexpected"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        load_semantic_evaluation_corpus(corpus)
    except ValueError as exc:
        assert "negative debe tener expected vacío" in str(exc)
    else:
        raise AssertionError("El corpus inválido fue aceptado")


def test_semantic_evaluation_compare_cli_writes_report(tmp_path: Path) -> None:
    report = {
        "schema_version": 1,
        "corpus": {"sha256": "same-corpus", "fragment_type": "object"},
        "profile": {
            "id": "profile-1",
            "name": "Perfil",
            "revision": 1,
            "model_name": "fake/model",
            "model_revision": "test",
            "aggregation_level": "object",
        },
        "index": {"run_id": "run-1"},
        "parameters": {"top_k": 20, "thresholds": [0.7], "sha256": "params-1"},
        "recommended_threshold": {
            "value": 0.7,
            "micro": {
                "true_positive": 2,
                "false_positive": 1,
                "false_negative": 0,
                "precision": 0.666667,
                "recall": 1.0,
                "f1": 0.8,
            },
        },
        "metrics_by_threshold": [],
        "report_sha256": "ignored-on-load",
    }
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    output = tmp_path / "comparison.json"
    first.write_text(json.dumps(report), encoding="utf-8")
    report["parameters"]["sha256"] = "params-2"
    report["recommended_threshold"]["value"] = 0.8
    second.write_text(json.dumps(report), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "semantic-evaluation-compare",
            str(first),
            str(second),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "comparación escrita" in result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["corpus_sha256"] == "same-corpus"
    assert [row["recommended_threshold"] for row in payload["reports"]] == [0.7, 0.8]
