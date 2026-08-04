from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from archive_workbench.discovery_providers import (
    DiscoveryProviderContract,
    detect_with_provider,
    provider_contract,
)
from archive_workbench.open_discovery import DISCOVERY_FAMILIES

EVALUATION_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class EvaluationAnnotation:
    start: int
    end: int
    text: str
    family: str
    subtype: str | None


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    record_id: str
    text: str
    source: dict[str, Any]
    annotations: tuple[EvaluationAnnotation, ...]


@dataclass(frozen=True, slots=True)
class EvaluationCorpus:
    path: Path
    sha256: str
    records: tuple[EvaluationRecord, ...]


@dataclass(frozen=True, slots=True)
class EvaluationResult:
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


def _require_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} debe ser un entero")
    return value


def load_evaluation_corpus(path: Path) -> EvaluationCorpus:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"No existe el corpus de evaluación: {resolved}")
    records: list[EvaluationRecord] = []
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
        record_id = str(row.get("record_id") or "").strip()
        text = row.get("text")
        source = row.get("source")
        annotations = row.get("annotations")
        if not record_id:
            raise ValueError(f"Falta record_id en la línea {line_number}")
        if record_id in seen_ids:
            raise ValueError(f"record_id duplicado: {record_id}")
        if not isinstance(text, str) or not text:
            raise ValueError(f"{record_id}: text debe ser una cadena no vacía")
        if not isinstance(source, dict) or not source:
            raise ValueError(f"{record_id}: source debe conservar procedencia")
        if not isinstance(annotations, list):
            raise ValueError(f"{record_id}: annotations debe ser una lista")
        parsed: list[EvaluationAnnotation] = []
        for index, item in enumerate(annotations):
            prefix = f"{record_id}.annotations[{index}]"
            if not isinstance(item, dict):
                raise ValueError(f"{prefix} debe ser un objeto")
            start = _require_int(item.get("start"), field=f"{prefix}.start")
            end = _require_int(item.get("end"), field=f"{prefix}.end")
            exact = item.get("text")
            family = str(item.get("family") or "").strip()
            subtype_raw = item.get("subtype")
            subtype = str(subtype_raw).strip() if subtype_raw is not None else None
            if start < 0 or end <= start or end > len(text):
                raise ValueError(f"{prefix}: offsets fuera del texto")
            if not isinstance(exact, str) or text[start:end] != exact:
                raise ValueError(
                    f"{prefix}: el texto exacto no coincide con text[start:end]"
                )
            if family not in DISCOVERY_FAMILIES:
                raise ValueError(f"{prefix}: familia inválida: {family}")
            parsed.append(
                EvaluationAnnotation(
                    start=start,
                    end=end,
                    text=exact,
                    family=family,
                    subtype=subtype or None,
                )
            )
        seen_ids.add(record_id)
        records.append(
            EvaluationRecord(
                record_id=record_id,
                text=text,
                source=source,
                annotations=tuple(parsed),
            )
        )
    if not records:
        raise ValueError("El corpus de evaluación no contiene registros")
    return EvaluationCorpus(
        path=resolved,
        sha256=_file_sha256(resolved),
        records=tuple(records),
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


def _contract_payload(contract: DiscoveryProviderContract) -> dict[str, Any]:
    return {
        "key": contract.key,
        "version": contract.version,
        "method": contract.method,
        "model_name": contract.model_name,
        "model_version": contract.model_version,
        "supported_families": list(contract.supported_families),
    }


def evaluate_discovery_provider(
    corpus_path: Path,
    *,
    provider_key: str,
    provider_version: str,
    families: Iterable[str] = DISCOVERY_FAMILIES,
    minimum_confidence: float = 0.0,
) -> EvaluationResult:
    selected_families = tuple(
        family for family in DISCOVERY_FAMILIES if family in set(families)
    )
    invalid = set(families) - set(DISCOVERY_FAMILIES)
    if invalid:
        raise ValueError("Familias inválidas: " + ", ".join(sorted(invalid)))
    if not selected_families:
        raise ValueError("La evaluación debe incluir al menos una familia")
    if not 0.0 <= float(minimum_confidence) <= 1.0:
        raise ValueError("La confianza mínima debe estar entre 0 y 1")

    corpus = load_evaluation_corpus(corpus_path)
    contract = provider_contract(provider_key, provider_version)
    expected_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []

    for record in corpus.records:
        for annotation in record.annotations:
            if annotation.family not in selected_families:
                continue
            expected_rows.append(
                {
                    "record_id": record.record_id,
                    "start": annotation.start,
                    "end": annotation.end,
                    "text": annotation.text,
                    "family": annotation.family,
                    "subtype": annotation.subtype,
                    "source": record.source,
                }
            )
        runtime_contract, detections = detect_with_provider(
            record.text,
            families=selected_families,
            provider_key=provider_key,
            provider_version=provider_version,
            allow_unsupported=True,
        )
        contract = runtime_contract
        for detection in detections:
            if (
                detection.confidence is not None
                and detection.confidence < float(minimum_confidence)
            ):
                continue
            prediction_rows.append(
                {
                    "record_id": record.record_id,
                    "start": detection.start,
                    "end": detection.end,
                    "text": detection.exact_text,
                    "family": detection.family,
                    "subtype": detection.subtype,
                    "confidence": detection.confidence,
                    "explanation": detection.explanation,
                }
            )

    expected_keys = {
        (row["record_id"], row["start"], row["end"], row["family"])
        for row in expected_rows
    }
    prediction_keys = {
        (row["record_id"], row["start"], row["end"], row["family"])
        for row in prediction_rows
    }
    matched = expected_keys & prediction_keys

    by_family: dict[str, dict[str, int | float]] = {}
    for family in selected_families:
        expected_family = {key for key in expected_keys if key[3] == family}
        predicted_family = {key for key in prediction_keys if key[3] == family}
        by_family[family] = _metric(
            len(expected_family & predicted_family),
            len(predicted_family - expected_family),
            len(expected_family - predicted_family),
        )
        by_family[family]["support"] = len(expected_family)

    micro = _metric(
        len(matched),
        len(prediction_keys - expected_keys),
        len(expected_keys - prediction_keys),
    )
    macro_families = [
        family
        for family in selected_families
        if by_family[family]["support"] or any(
            key[3] == family for key in prediction_keys
        )
    ]
    macro = {
        metric: round(
            sum(float(by_family[family][metric]) for family in macro_families)
            / len(macro_families),
            6,
        )
        if macro_families
        else 0.0
        for metric in ("precision", "recall", "f1")
    }
    macro["family_count"] = len(macro_families)

    expected_by_span = {
        (row["record_id"], row["start"], row["end"]): row for row in expected_rows
    }
    predicted_by_span = {
        (row["record_id"], row["start"], row["end"]): row
        for row in prediction_rows
    }
    errors: list[dict[str, Any]] = []
    for row in prediction_rows:
        key = (row["record_id"], row["start"], row["end"], row["family"])
        if key in expected_keys:
            expected = expected_by_span[(row["record_id"], row["start"], row["end"])]
            if expected.get("subtype") and expected.get("subtype") != row.get("subtype"):
                errors.append(
                    {
                        "kind": "subtype_mismatch",
                        "prediction": row,
                        "expected": expected,
                    }
                )
            continue
        same_span = expected_by_span.get((row["record_id"], row["start"], row["end"]))
        errors.append(
            {
                "kind": "family_mismatch" if same_span else "false_positive",
                "prediction": row,
                "expected": same_span,
            }
        )
    for row in expected_rows:
        key = (row["record_id"], row["start"], row["end"], row["family"])
        if key in prediction_keys:
            continue
        same_span = predicted_by_span.get((row["record_id"], row["start"], row["end"]))
        errors.append(
            {
                "kind": "false_negative",
                "expected": row,
                "prediction": same_span,
            }
        )

    parameters = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "corpus_sha256": corpus.sha256,
        "provider": _contract_payload(contract),
        "families": list(selected_families),
        "minimum_confidence": float(minimum_confidence),
    }
    parameters_sha256 = sha256(
        json.dumps(
            parameters,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    payload: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": {
            "path": str(corpus.path),
            "sha256": corpus.sha256,
            "record_count": len(corpus.records),
            "annotation_count": len(expected_rows),
        },
        "provider": _contract_payload(contract),
        "parameters": {
            "families": list(selected_families),
            "minimum_confidence": float(minimum_confidence),
            "sha256": parameters_sha256,
        },
        "metrics": {
            "micro": micro,
            "macro": macro,
            "by_family": by_family,
        },
        "expected": expected_rows,
        "predictions": prediction_rows,
        "errors": errors,
    }
    stable_payload = json.loads(json.dumps(payload, ensure_ascii=False))
    stable_payload.pop("generated_at", None)
    stable_payload["corpus"].pop("path", None)
    payload["report_sha256"] = sha256(
        json.dumps(
            stable_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return EvaluationResult(payload=payload)


def write_evaluation_report(result: EvaluationResult, output: Path) -> Path:
    resolved = output.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(result.payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return resolved


def load_evaluation_report(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"No existe el informe de evaluación: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Informe JSON inválido: {resolved}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        raise ValueError(f"Esquema de evaluación no admitido: {resolved}")
    for key in ("corpus", "provider", "parameters", "metrics", "report_sha256"):
        if key not in payload:
            raise ValueError(f"Informe incompleto: falta {key} en {resolved}")
    return payload


def compare_evaluation_reports(paths: Iterable[Path]) -> dict[str, Any]:
    loaded = [(path.expanduser().resolve(), load_evaluation_report(path)) for path in paths]
    if len(loaded) < 2:
        raise ValueError("La comparación requiere al menos dos informes")
    corpus_hashes = {payload["corpus"]["sha256"] for _, payload in loaded}
    if len(corpus_hashes) != 1:
        raise ValueError("Los informes no corresponden al mismo corpus")
    rows = []
    for path, payload in loaded:
        micro = payload["metrics"]["micro"]
        rows.append(
            {
                "path": str(path),
                "provider_key": payload["provider"]["key"],
                "provider_version": payload["provider"]["version"],
                "method": payload["provider"]["method"],
                "parameters_sha256": payload["parameters"]["sha256"],
                "report_sha256": payload["report_sha256"],
                "precision": micro["precision"],
                "recall": micro["recall"],
                "f1": micro["f1"],
            }
        )
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "corpus_sha256": next(iter(corpus_hashes)),
        "reports": rows,
    }
