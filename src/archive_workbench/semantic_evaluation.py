from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy.orm import Session

from archive_workbench.db.models import SemanticSearchProfile
from archive_workbench.semantic_search import (
    EmbeddingBackend,
    SEMANTIC_AGGREGATION_LEVELS,
    SemanticSearchResult,
    profile_snapshot,
    semantic_index_status,
    semantic_search,
)

SEMANTIC_EVALUATION_SCHEMA_VERSION = 1
SEMANTIC_QUERY_KINDS = ("positive", "negative", "ambiguous")
SEMANTIC_TARGET_FIELDS = ("chunk_id", "record_id", "source_key", "object_id")
DEFAULT_SEMANTIC_THRESHOLDS = (0.0, 0.5, 0.7, 0.8, 0.9)


@dataclass(frozen=True, slots=True)
class SemanticEvaluationCase:
    case_id: str
    query: str
    query_kind: str
    fragment_type: str
    target_field: str
    expected: tuple[str, ...]
    notes: str | None


@dataclass(frozen=True, slots=True)
class SemanticEvaluationCorpus:
    path: Path
    sha256: str
    cases: tuple[SemanticEvaluationCase, ...]


@dataclass(frozen=True, slots=True)
class SemanticEvaluationResult:
    payload: dict[str, Any]

    @property
    def report_sha256(self) -> str:
        return str(self.payload["report_sha256"])


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} debe ser una cadena")
    clean = " ".join(value.split())
    if not clean:
        raise ValueError(f"{field} no puede quedar vacío")
    return clean


def load_semantic_evaluation_corpus(path: Path) -> SemanticEvaluationCorpus:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"No existe el corpus de evaluación semántica: {resolved}")
    cases: list[SemanticEvaluationCase] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(
        resolved.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"JSON inválido en {resolved.name}, línea {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(f"La línea {line_number} debe contener un objeto JSON")
        case_id = _clean_string(row.get("case_id"), field=f"línea {line_number}.case_id")
        if case_id in seen_ids:
            raise ValueError(f"case_id duplicado: {case_id}")
        query = _clean_string(row.get("query"), field=f"{case_id}.query")
        query_kind = _clean_string(
            row.get("query_kind"), field=f"{case_id}.query_kind"
        )
        if query_kind not in SEMANTIC_QUERY_KINDS:
            raise ValueError(
                f"{case_id}.query_kind debe ser positive, negative o ambiguous"
            )
        fragment_type = _clean_string(
            row.get("fragment_type"), field=f"{case_id}.fragment_type"
        )
        if fragment_type not in SEMANTIC_AGGREGATION_LEVELS:
            raise ValueError(
                f"{case_id}.fragment_type no corresponde a un nivel semántico admitido"
            )
        target_field = _clean_string(
            row.get("target_field"), field=f"{case_id}.target_field"
        )
        if target_field not in SEMANTIC_TARGET_FIELDS:
            raise ValueError(
                f"{case_id}.target_field debe ser uno de: "
                + ", ".join(SEMANTIC_TARGET_FIELDS)
            )
        expected_raw = row.get("expected")
        if not isinstance(expected_raw, list):
            raise ValueError(f"{case_id}.expected debe ser una lista")
        expected = tuple(
            dict.fromkeys(
                _clean_string(value, field=f"{case_id}.expected")
                for value in expected_raw
            )
        )
        if query_kind == "negative" and expected:
            raise ValueError(f"{case_id}: una consulta negative debe tener expected vacío")
        if query_kind != "negative" and not expected:
            raise ValueError(
                f"{case_id}: una consulta {query_kind} debe declarar resultados esperados"
            )
        notes_raw = row.get("notes")
        if notes_raw is not None and not isinstance(notes_raw, str):
            raise ValueError(f"{case_id}.notes debe ser una cadena o null")
        notes = " ".join(notes_raw.split()) if notes_raw and notes_raw.strip() else None
        seen_ids.add(case_id)
        cases.append(
            SemanticEvaluationCase(
                case_id=case_id,
                query=query,
                query_kind=query_kind,
                fragment_type=fragment_type,
                target_field=target_field,
                expected=expected,
                notes=notes,
            )
        )
    if not cases:
        raise ValueError("El corpus de evaluación semántica no contiene consultas")
    return SemanticEvaluationCorpus(
        path=resolved,
        sha256=_file_sha256(resolved),
        cases=tuple(cases),
    )


def _metric(tp: int, fp: int, fn: int) -> dict[str, int | float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def _thresholds(values: Iterable[float]) -> tuple[float, ...]:
    parsed = sorted({round(float(value), 6) for value in values})
    if not parsed:
        raise ValueError("La evaluación requiere al menos un umbral")
    if parsed[0] < -1.0 or parsed[-1] > 1.0:
        raise ValueError("Los umbrales deben estar entre -1 y 1")
    return tuple(parsed)


def _target_values(result: SemanticSearchResult, field: str) -> tuple[str, ...]:
    if field == "chunk_id":
        return (result.chunk_id,)
    if field == "record_id":
        return (result.record_id,)
    if field == "source_key":
        return (
            result.source_key
            if result.source_key
            else f"<sin-source-key>:{result.chunk_id}",
        )
    if field == "object_id":
        return tuple(result.object_ids) or (f"<sin-object-id>:{result.chunk_id}",)
    raise ValueError(f"Campo de evaluación semántica inválido: {field}")


def _ranked_targets(
    results: Sequence[SemanticSearchResult], *, target_field: str
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for rank, result in enumerate(results, start=1):
        for value in _target_values(result, target_field):
            current = rows.get(value)
            candidate = {
                "value": value,
                "score": round(float(result.score), 8),
                "rank": rank,
                "chunk_id": result.chunk_id,
                "record_id": result.record_id,
                "source_key": result.source_key,
                "object_ids": list(result.object_ids),
                "title": result.title,
                "page_start": result.page_start,
                "page_end": result.page_end,
            }
            if current is None or candidate["score"] > current["score"]:
                rows[value] = candidate
    return sorted(rows.values(), key=lambda row: (-row["score"], row["rank"], row["value"]))


def _case_metric(
    case: SemanticEvaluationCase,
    ranked: Sequence[dict[str, Any]],
    *,
    threshold: float,
) -> dict[str, Any]:
    expected = set(case.expected)
    predicted = {
        str(row["value"]) for row in ranked if float(row["score"]) >= threshold
    }
    metric = _metric(
        len(expected & predicted),
        len(predicted - expected),
        len(expected - predicted),
    )
    metric.update(
        {
            "case_id": case.case_id,
            "query_kind": case.query_kind,
            "expected": sorted(expected),
            "predicted": sorted(predicted),
        }
    )
    return metric


def _aggregate_case_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, int | float]:
    return _metric(
        sum(int(row["true_positive"]) for row in rows),
        sum(int(row["false_positive"]) for row in rows),
        sum(int(row["false_negative"]) for row in rows),
    )


def evaluate_semantic_search(
    session: Session,
    *,
    project_root: Path,
    project_id: str,
    profile: SemanticSearchProfile,
    corpus_path: Path,
    thresholds: Iterable[float] = DEFAULT_SEMANTIC_THRESHOLDS,
    top_k: int = 20,
    backend: EmbeddingBackend | None = None,
    device: str = "auto",
) -> SemanticEvaluationResult:
    if profile.project_id != project_id:
        raise ValueError("El perfil semántico pertenece a otro proyecto")
    if not 1 <= top_k <= 500:
        raise ValueError("top_k debe estar entre 1 y 500")
    selected_thresholds = _thresholds(thresholds)
    corpus = load_semantic_evaluation_corpus(corpus_path)
    cases = tuple(
        case for case in corpus.cases if case.fragment_type == profile.aggregation_level
    )
    if not cases:
        raise ValueError(
            "El corpus no contiene consultas para el nivel de agrupación del perfil: "
            f"{profile.aggregation_level}"
        )
    status = semantic_index_status(
        session,
        project_root=project_root,
        project_id=project_id,
        profile=profile,
    )
    if not status.is_current or status.latest_run_id is None:
        raise ValueError(f"El índice no está listo: {status.reason}. Reconstruí el índice.")

    case_rows: list[dict[str, Any]] = []
    for case in cases:
        results = semantic_search(
            session,
            project_root=project_root,
            project_id=project_id,
            profile=profile,
            query=case.query,
            top_k=top_k,
            minimum_score=-1.0,
            backend=backend,
            device=device,
        )
        ranked = _ranked_targets(results, target_field=case.target_field)
        expected_scores = [
            float(row["score"]) for row in ranked if row["value"] in set(case.expected)
        ]
        unexpected_scores = [
            float(row["score"]) for row in ranked if row["value"] not in set(case.expected)
        ]
        case_rows.append(
            {
                "case_id": case.case_id,
                "query": case.query,
                "query_kind": case.query_kind,
                "fragment_type": case.fragment_type,
                "target_field": case.target_field,
                "expected": list(case.expected),
                "notes": case.notes,
                "best_expected_score": max(expected_scores) if expected_scores else None,
                "best_unexpected_score": max(unexpected_scores) if unexpected_scores else None,
                "score_margin": (
                    round(max(expected_scores) - max(unexpected_scores), 8)
                    if expected_scores and unexpected_scores
                    else None
                ),
                "ranked_targets": ranked,
            }
        )

    threshold_rows: list[dict[str, Any]] = []
    case_by_id = {case.case_id: case for case in cases}
    for threshold in selected_thresholds:
        per_case = [
            _case_metric(
                case_by_id[str(row["case_id"])],
                row["ranked_targets"],
                threshold=threshold,
            )
            for row in case_rows
        ]
        by_kind = {
            kind: _aggregate_case_metrics(
                [row for row in per_case if row["query_kind"] == kind]
            )
            for kind in SEMANTIC_QUERY_KINDS
        }
        for kind in SEMANTIC_QUERY_KINDS:
            by_kind[kind]["case_count"] = sum(
                case.query_kind == kind for case in cases
            )
        threshold_rows.append(
            {
                "threshold": threshold,
                "micro": _aggregate_case_metrics(per_case),
                "by_query_kind": by_kind,
                "cases": per_case,
            }
        )

    recommended = max(
        threshold_rows,
        key=lambda row: (
            float(row["micro"]["f1"]),
            float(row["micro"]["precision"]),
            float(row["micro"]["recall"]),
            float(row["threshold"]),
        ),
    )
    parameters = {
        "schema_version": SEMANTIC_EVALUATION_SCHEMA_VERSION,
        "corpus_sha256": corpus.sha256,
        "project_id": project_id,
        "profile": profile_snapshot(profile),
        "index_run_id": status.latest_run_id,
        "index_corpus_state_sha256": status.corpus_state_sha256,
        "top_k": top_k,
        "thresholds": list(selected_thresholds),
    }
    parameters_sha256 = sha256(
        json.dumps(
            parameters,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    payload: dict[str, Any] = {
        "schema_version": SEMANTIC_EVALUATION_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": {
            "path": str(corpus.path),
            "sha256": corpus.sha256,
            "case_count": len(corpus.cases),
            "evaluated_case_count": len(cases),
            "fragment_type": profile.aggregation_level,
        },
        "project": {
            "project_id": project_id,
            "root": str(project_root.resolve()),
        },
        "profile": profile_snapshot(profile),
        "index": {
            "run_id": status.latest_run_id,
            "corpus_state_sha256": status.corpus_state_sha256,
            "vector_count": status.vector_count,
            "dimensions": status.dimensions,
        },
        "parameters": {
            "top_k": top_k,
            "thresholds": list(selected_thresholds),
            "sha256": parameters_sha256,
        },
        "recommended_threshold": {
            "value": recommended["threshold"],
            "micro": recommended["micro"],
            "scope_note": (
                "Recomendación limitada a este corpus, perfil, modelo, revisión de índice "
                "y conjunto de umbrales; no constituye un umbral universal."
            ),
        },
        "metrics_by_threshold": threshold_rows,
        "cases": case_rows,
    }
    stable_payload = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    stable_payload.pop("generated_at", None)
    stable_payload["corpus"].pop("path", None)
    stable_payload["project"].pop("root", None)
    payload["report_sha256"] = sha256(
        json.dumps(
            stable_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return SemanticEvaluationResult(payload=payload)


def write_semantic_evaluation_report(
    result: SemanticEvaluationResult, output: Path
) -> Path:
    resolved = output.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(result.payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return resolved


def load_semantic_evaluation_report(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"No existe el informe de evaluación semántica: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Informe JSON inválido: {resolved}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SEMANTIC_EVALUATION_SCHEMA_VERSION
    ):
        raise ValueError(f"Esquema de evaluación semántica no admitido: {resolved}")
    for key in (
        "corpus",
        "profile",
        "index",
        "parameters",
        "recommended_threshold",
        "metrics_by_threshold",
        "report_sha256",
    ):
        if key not in payload:
            raise ValueError(f"Informe incompleto: falta {key} en {resolved}")
    return payload


def compare_semantic_evaluation_reports(paths: Iterable[Path]) -> dict[str, Any]:
    loaded = [
        (path.expanduser().resolve(), load_semantic_evaluation_report(path))
        for path in paths
    ]
    if len(loaded) < 2:
        raise ValueError("La comparación requiere al menos dos informes")
    corpus_hashes = {payload["corpus"]["sha256"] for _, payload in loaded}
    if len(corpus_hashes) != 1:
        raise ValueError("Los informes no corresponden al mismo corpus de consultas")
    fragment_types = {payload["corpus"]["fragment_type"] for _, payload in loaded}
    if len(fragment_types) != 1:
        raise ValueError("Los informes no evalúan el mismo tipo de fragmento")
    rows: list[dict[str, Any]] = []
    for path, payload in loaded:
        recommended = payload["recommended_threshold"]
        micro = recommended["micro"]
        profile = payload["profile"]
        rows.append(
            {
                "path": str(path),
                "profile_id": profile["id"],
                "profile_name": profile["name"],
                "profile_revision": profile["revision"],
                "model_name": profile["model_name"],
                "model_revision": profile["model_revision"],
                "aggregation_level": profile["aggregation_level"],
                "index_run_id": payload["index"]["run_id"],
                "parameters_sha256": payload["parameters"]["sha256"],
                "report_sha256": payload["report_sha256"],
                "recommended_threshold": recommended["value"],
                "precision": micro["precision"],
                "recall": micro["recall"],
                "f1": micro["f1"],
                "false_positive": micro["false_positive"],
                "false_negative": micro["false_negative"],
            }
        )
    return {
        "schema_version": SEMANTIC_EVALUATION_SCHEMA_VERSION,
        "corpus_sha256": next(iter(corpus_hashes)),
        "fragment_type": next(iter(fragment_types)),
        "reports": rows,
        "scope_note": (
            "La comparación conserva perfiles, modelos, revisiones de índice y parámetros; "
            "no declara un modelo superior fuera del corpus evaluado."
        ),
    }
