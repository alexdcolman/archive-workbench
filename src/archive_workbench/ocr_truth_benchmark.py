from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Callable, Iterable, Sequence, TypeVar
from uuid import uuid4

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.contracts.extraction import ExtractionProfile
from archive_workbench.contracts.ocr_truth import (
    OcrTruthBenchmarkManifest,
    OcrTruthBenchmarkProfile,
    OcrTruthCandidateMetrics,
    OcrTruthEngineAggregate,
    OcrTruthEngineSpec,
    OcrTruthReference,
)
from archive_workbench.db.models import (
    DerivativeAsset,
    DigitalObject,
    PreprocessingRun,
    SourceRegistration,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.extraction import (
    extraction_doctor,
    load_extraction_profile,
    normalize_docling_page,
    run_docling_cli_batch,
)
from archive_workbench.identity import sha256_file
from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.surya_engine import normalize_surya_page, run_surya_cli_batch, surya_version
from archive_workbench.tesseract_engine import prepare_image_variant, run_tesseract_page

T = TypeVar("T")


@dataclass(slots=True)
class OcrTruthDoctorRow:
    engine_key: str
    profile_path: str
    profile_key: str
    backend: str
    ready: bool
    checks: list[tuple[str, bool, str, bool]] = field(default_factory=list)


@dataclass(slots=True)
class OcrTruthBenchmarkSummary:
    source_key: str
    benchmark_id: str
    output_root: str
    references: list[OcrTruthReference] = field(default_factory=list)
    candidates: list[OcrTruthCandidateMetrics] = field(default_factory=list)
    aggregates: list[OcrTruthEngineAggregate] = field(default_factory=list)


def load_ocr_truth_benchmark_profile(path: str | Path) -> OcrTruthBenchmarkProfile:
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"El perfil de benchmark debe ser un objeto YAML: {source}")
    return OcrTruthBenchmarkProfile.model_validate(payload)


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _profile_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def _ground_truth_path(
    project_root: Path,
    profile: OcrTruthBenchmarkProfile,
    *,
    source_key: str,
    page: int,
) -> Path:
    base = _profile_path(project_root, profile.ground_truth_root).resolve()
    path = (base / source_key / f"page_{page:04d}.txt").resolve()
    if base not in path.parents:
        raise ValueError("El source_key produce una ruta de verdad terreno inválida")
    return path


def normalize_ocr_text(text: str, profile: OcrTruthBenchmarkProfile) -> str:
    normalized = unicodedata.normalize(profile.unicode_form, text.replace("\r\n", "\n").replace("\r", "\n"))
    if profile.collapse_whitespace:
        normalized = " ".join(normalized.split())
    else:
        normalized = normalized.strip()
    if not profile.case_sensitive:
        normalized = normalized.casefold()
    return normalized


def edit_distance(reference: Sequence[T], candidate: Sequence[T]) -> int:
    """Levenshtein con memoria O(min(n, m)); sirve para caracteres y palabras."""
    if len(reference) < len(candidate):
        reference, candidate = candidate, reference
    previous = list(range(len(candidate) + 1))
    for row_index, ref_item in enumerate(reference, start=1):
        current = [row_index]
        for col_index, cand_item in enumerate(candidate, start=1):
            substitution = previous[col_index - 1] + (ref_item != cand_item)
            insertion = current[col_index - 1] + 1
            deletion = previous[col_index] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def error_metrics(
    reference_text: str,
    candidate_text: str,
    profile: OcrTruthBenchmarkProfile,
) -> dict[str, int | float]:
    reference = normalize_ocr_text(reference_text, profile)
    candidate = normalize_ocr_text(candidate_text, profile)
    if not reference:
        raise ValueError("La verdad terreno no puede estar vacía")
    reference_words = reference.split()
    candidate_words = candidate.split()
    char_distance = edit_distance(reference, candidate)
    word_distance = edit_distance(reference_words, candidate_words)
    return {
        "reference_character_count": len(reference),
        "candidate_character_count": len(candidate),
        "reference_word_count": len(reference_words),
        "candidate_word_count": len(candidate_words),
        "character_edit_distance": char_distance,
        "word_edit_distance": word_distance,
        "cer": char_distance / len(reference),
        "wer": word_distance / len(reference_words) if reference_words else 0.0,
    }


def _source_and_assets(
    session: Session,
    *,
    source_key: str,
    pages: set[int],
) -> tuple[SourceRegistration, DigitalObject, PreprocessingRun, list[DerivativeAsset]]:
    row = session.execute(
        select(SourceRegistration, DigitalObject)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            SourceRegistration.source_key == source_key,
        )
    ).one_or_none()
    if row is None:
        raise ValueError(f"source_key no registrado: {source_key}")
    registration, digital = row
    preprocessing = session.scalar(
        select(PreprocessingRun)
        .where(
            PreprocessingRun.digital_object_id == digital.id,
            PreprocessingRun.is_current.is_(True),
            PreprocessingRun.status.in_(["completed", "completed_with_warnings"]),
        )
        .order_by(PreprocessingRun.created_at.desc())
    )
    if preprocessing is None:
        raise RuntimeError(f"{source_key} no tiene derivados vigentes")
    assets = list(
        session.scalars(
            select(DerivativeAsset)
            .where(
                DerivativeAsset.preprocessing_run_id == preprocessing.id,
                DerivativeAsset.kind == "ocr",
            )
            .order_by(DerivativeAsset.page_number)
        ).all()
    )
    available = {asset.page_number for asset in assets}
    missing = pages - available
    if missing:
        raise ValueError(f"Páginas sin derivado OCR: {', '.join(map(str, sorted(missing)))}")
    if pages:
        assets = [asset for asset in assets if asset.page_number in pages]
    return registration, digital, preprocessing, assets


def load_ground_truth_references(
    *,
    project_root: Path,
    profile: OcrTruthBenchmarkProfile,
    source_key: str,
    pages: Iterable[int],
) -> tuple[list[OcrTruthReference], dict[int, str]]:
    references: list[OcrTruthReference] = []
    texts: dict[int, str] = {}
    for page in sorted(set(pages)):
        path = _ground_truth_path(project_root, profile, source_key=source_key, page=page)
        if not path.is_file():
            raise ValueError(
                f"Falta verdad terreno para {source_key}, página {page}: "
                f"{_relative(path, project_root)}"
            )
        text = path.read_text(encoding="utf-8")
        normalized = normalize_ocr_text(text, profile)
        if not normalized:
            raise ValueError(f"La verdad terreno está vacía: {_relative(path, project_root)}")
        texts[page] = text
        references.append(
            OcrTruthReference(
                source_key=source_key,
                page=page,
                path=_relative(path, project_root),
                sha256=sha256_file(path),
                character_count=len(normalized),
                word_count=len(normalized.split()),
            )
        )
    return references, texts


def benchmark_doctor(
    *,
    project_root: str | Path,
    profile: OcrTruthBenchmarkProfile,
) -> list[OcrTruthDoctorRow]:
    root = Path(project_root)
    rows: list[OcrTruthDoctorRow] = []
    for spec in profile.engines:
        if not spec.enabled:
            continue
        extraction_profile = load_extraction_profile(_profile_path(root, spec.profile_path))
        expected = {
            "tesseract": "tesseract_tsv",
            "docling": "docling_cli",
            "surya": "surya_cli",
        }[spec.engine_key]
        if extraction_profile.backend != expected:
            raise ValueError(
                f"{spec.engine_key} apunta a backend {extraction_profile.backend}; se esperaba {expected}"
            )
        report = extraction_doctor(extraction_profile)
        rows.append(
            OcrTruthDoctorRow(
                engine_key=spec.engine_key,
                profile_path=spec.profile_path,
                profile_key=extraction_profile.profile_key,
                backend=extraction_profile.backend,
                ready=report.ready,
                checks=[
                    (
                        check.name,
                        check.ok,
                        "idiomas requeridos disponibles"
                        if check.name == "Idiomas OCR" and check.ok
                        else check.detail,
                        check.required,
                    )
                    for check in report.checks
                ],
            )
        )
    return rows


def _engine_version(engine_key: str, extraction_profile: ExtractionProfile) -> str | None:
    if engine_key == "surya":
        return surya_version(extraction_profile.surya_command)
    if engine_key == "docling":
        try:
            return metadata.version("docling")
        except metadata.PackageNotFoundError:
            return None
    if engine_key == "tesseract":
        try:
            result = subprocess.run(
                [extraction_profile.tesseract_command, "--version"],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        first = (result.stdout or result.stderr or "").splitlines()
        return first[0].strip() if result.returncode == 0 and first else None
    return None


def _join_objects(records) -> str:
    ordered = sorted(records, key=lambda item: item.order_index)
    return "\n".join(item.original_text.strip() for item in ordered if item.original_text.strip())


def _run_tesseract(
    *,
    page: int,
    source_image: Path,
    output_dir: Path,
    extraction_profile: ExtractionProfile,
    runner,
) -> tuple[str, list[Path], Path | None]:
    variant_path = output_dir / "input.png"
    prepare_image_variant(source_image, variant_path, extraction_profile.image_variant)
    result = runner(
        variant_path,
        page_number=page,
        tesseract_command=extraction_profile.tesseract_command,
        languages=extraction_profile.ocr_languages,
        psm=extraction_profile.psm if extraction_profile.psm is not None else 3,
        image_variant=extraction_profile.image_variant,
        timeout_seconds=extraction_profile.document_timeout_seconds,
    )
    text_path = output_dir / "text.txt"
    tsv_path = output_dir / "raw.tsv"
    text_path.write_text(result.full_text, encoding="utf-8")
    tsv_path.write_text(result.tsv_text, encoding="utf-8")
    log_path = output_dir / "engine.log"
    log_path.write_text("$ " + " ".join(result.command) + "\n" + (result.stderr or ""), encoding="utf-8")
    return result.full_text, [tsv_path], log_path


def _run_docling(
    *,
    page: int,
    source_image: Path,
    output_dir: Path,
    extraction_profile: ExtractionProfile,
    decisions,
    runner,
) -> tuple[str, list[Path], Path | None, str | None, str | None, float]:
    started = time.perf_counter()
    outputs, version, log_text = runner(
        [(page, source_image)], output_dir / "work", extraction_profile
    )
    elapsed = time.perf_counter() - started
    raw_source = outputs[page]
    raw_path = output_dir / "raw.json"
    shutil.copy2(raw_source, raw_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    records = normalize_docling_page(
        payload,
        digital_object_id="benchmark",
        extraction_run_id="benchmark",
        page_number=page,
        width=_image_size(source_image)[0],
        height=_image_size(source_image)[1],
        decisions=decisions,
    )
    text = _join_objects(records)
    text_path = output_dir / "text.txt"
    text_path.write_text(text, encoding="utf-8")
    log_path = output_dir / "engine.log"
    log_path.write_text(log_text or "", encoding="utf-8")
    return text, [raw_path], log_path, version, None, elapsed


def _run_surya(
    *,
    page: int,
    source_image: Path,
    output_dir: Path,
    extraction_profile: ExtractionProfile,
    decisions,
    runner,
) -> tuple[str, list[Path], Path | None, str | None, str | None, float]:
    input_image = source_image
    if extraction_profile.image_variant != "original":
        input_image = output_dir / "input.png"
        prepare_image_variant(source_image, input_image, extraction_profile.image_variant)
    started = time.perf_counter()
    outputs, version, log_text = runner(
        [(page, input_image)], output_dir / "work", extraction_profile
    )
    elapsed = time.perf_counter() - started
    raw_source = outputs[page]
    raw_path = output_dir / "raw.json"
    shutil.copy2(raw_source, raw_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    width, height = _image_size(source_image)
    records = normalize_surya_page(
        payload,
        digital_object_id="benchmark",
        extraction_run_id="benchmark",
        page_number=page,
        width=width,
        height=height,
        decisions=decisions,
    )
    text = _join_objects(records)
    text_path = output_dir / "text.txt"
    text_path.write_text(text, encoding="utf-8")
    log_path = output_dir / "engine.log"
    log_path.write_text(log_text or "", encoding="utf-8")
    return text, [raw_path], log_path, version, None, elapsed


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return image.size


def _aggregate(candidates: list[OcrTruthCandidateMetrics]) -> list[OcrTruthEngineAggregate]:
    result: list[OcrTruthEngineAggregate] = []
    for engine_key in ("tesseract", "docling", "surya"):
        rows = [item for item in candidates if item.engine_key == engine_key]
        if not rows:
            continue
        ref_chars = sum(item.reference_character_count for item in rows)
        ref_words = sum(item.reference_word_count for item in rows)
        char_distance = sum(item.character_edit_distance for item in rows)
        word_distance = sum(item.word_edit_distance for item in rows)
        result.append(
            OcrTruthEngineAggregate(
                engine_key=engine_key,
                profile_key=rows[0].profile_key,
                pages=len(rows),
                reference_character_count=ref_chars,
                candidate_character_count=sum(item.candidate_character_count for item in rows),
                reference_word_count=ref_words,
                candidate_word_count=sum(item.candidate_word_count for item in rows),
                character_edit_distance=char_distance,
                word_edit_distance=word_distance,
                cer=char_distance / ref_chars if ref_chars else 0.0,
                wer=word_distance / ref_words if ref_words else 0.0,
                elapsed_seconds=sum(item.elapsed_seconds for item in rows),
            )
        )
    return sorted(result, key=lambda item: (item.cer, item.wer, item.engine_key))


def _summary_markdown(manifest: OcrTruthBenchmarkManifest) -> str:
    lines = [
        f"# Benchmark OCR con verdad terreno: {manifest.source_key}",
        "",
        "CER y WER se calculan sobre texto Unicode normalizado y espacios equivalentes. "
        "El ordenamiento no modifica la selección canónica ni declara un motor preferido para otros documentos.",
        "",
        "## Resultado agregado",
        "",
        "| Motor | Perfil | Páginas | CER | WER | Tiempo (s) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in manifest.aggregates:
        lines.append(
            f"| {item.engine_key} | `{item.profile_key}` | {item.pages} | "
            f"{item.cer:.4f} | {item.wer:.4f} | {item.elapsed_seconds:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Resultado por página",
            "",
            "| Página | Motor | CER | WER | Caracteres ref./OCR | Palabras ref./OCR | Tiempo (s) |",
            "|---:|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in sorted(manifest.candidates, key=lambda row: (row.page, row.cer, row.engine_key)):
        lines.append(
            f"| {item.page} | {item.engine_key} | {item.cer:.4f} | {item.wer:.4f} | "
            f"{item.reference_character_count}/{item.candidate_character_count} | "
            f"{item.reference_word_count}/{item.candidate_word_count} | {item.elapsed_seconds:.2f} |"
        )
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, candidates: list[OcrTruthCandidateMetrics]) -> None:
    fieldnames = [
        "page",
        "engine_key",
        "profile_key",
        "backend",
        "engine_version",
        "cer",
        "wer",
        "character_edit_distance",
        "word_edit_distance",
        "reference_character_count",
        "candidate_character_count",
        "reference_word_count",
        "candidate_word_count",
        "elapsed_seconds",
        "text_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in sorted(candidates, key=lambda row: (row.page, row.cer, row.engine_key)):
            data = item.model_dump(mode="json")
            writer.writerow({key: data.get(key) for key in fieldnames})


def run_ocr_truth_benchmark(
    session: Session,
    *,
    project_root: str | Path,
    source_key: str,
    profile: OcrTruthBenchmarkProfile,
    pages: set[int] | None = None,
    tesseract_runner=run_tesseract_page,
    docling_runner=run_docling_cli_batch,
    surya_runner=run_surya_cli_batch,
) -> OcrTruthBenchmarkSummary:
    root = Path(project_root)
    requested_pages = set(pages or [])
    if not requested_pages:
        truth_root = _profile_path(root, profile.ground_truth_root) / source_key
        requested_pages = {
            int(match.group(1))
            for path in truth_root.glob("page_*.txt")
            if (match := re.fullmatch(r"page_(\d{4})\.txt", path.name))
        }
    if not requested_pages:
        raise ValueError(f"No se encontraron páginas de verdad terreno para {source_key}")

    registration, digital, preprocessing, assets = _source_and_assets(
        session, source_key=source_key, pages=requested_pages
    )
    references, truth_texts = load_ground_truth_references(
        project_root=root,
        profile=profile,
        source_key=source_key,
        pages=requested_pages,
    )
    references_by_page = {item.page: item for item in references}

    resolved_profiles: dict[str, ExtractionProfile] = {}
    for spec in profile.engines:
        if not spec.enabled:
            continue
        extraction_profile = load_extraction_profile(_profile_path(root, spec.profile_path))
        expected_backend = {
            "tesseract": "tesseract_tsv",
            "docling": "docling_cli",
            "surya": "surya_cli",
        }[spec.engine_key]
        if extraction_profile.backend != expected_backend:
            raise ValueError(
                f"{spec.engine_key} usa {extraction_profile.backend}; se esperaba {expected_backend}"
            )
        doctor = extraction_doctor(extraction_profile)
        failed_checks = [check for check in doctor.checks if check.required and not check.ok]
        if failed_checks:
            details = "; ".join(f"{check.name}: {check.detail}" for check in failed_checks)
            raise RuntimeError(f"Motor {spec.engine_key} no disponible: {details}")
        resolved_profiles[spec.engine_key] = extraction_profile

    benchmark_id = str(uuid4())
    output_dir = root / "ocr_benchmarks" / digital.id / f"truth_{benchmark_id}"
    output_dir.mkdir(parents=True, exist_ok=False)
    truth_snapshot_dir = output_dir / "ground_truth"
    truth_snapshot_dir.mkdir(parents=True)
    for reference in references:
        source = root / reference.path
        shutil.copy2(source, truth_snapshot_dir / f"page_{reference.page:04d}.txt")

    decisions = load_decisions(root / "config" / "decisions.yaml")
    candidates: list[OcrTruthCandidateMetrics] = []
    asset_by_page = {asset.page_number: asset for asset in assets}

    for spec in profile.engines:
        if not spec.enabled:
            continue
        extraction_profile = resolved_profiles[spec.engine_key]

        for page in sorted(requested_pages):
            asset = asset_by_page[page]
            source_image = root / asset.relative_path
            if not source_image.is_file():
                raise RuntimeError(f"Falta el derivado OCR: {asset.relative_path}")
            if sha256_file(source_image) != asset.sha256:
                raise RuntimeError(f"El derivado OCR fue modificado: {asset.relative_path}")
            engine_dir = output_dir / "engines" / spec.engine_key / f"page_{page:04d}"
            engine_dir.mkdir(parents=True, exist_ok=False)

            if spec.engine_key == "tesseract":
                started = time.perf_counter()
                text, raw_paths, log_path = _run_tesseract(
                    page=page,
                    source_image=source_image,
                    output_dir=engine_dir,
                    extraction_profile=extraction_profile,
                    runner=tesseract_runner,
                )
                elapsed = time.perf_counter() - started
                version = None
            elif spec.engine_key == "docling":
                text, raw_paths, log_path, version, _note, elapsed = _run_docling(
                    page=page,
                    source_image=source_image,
                    output_dir=engine_dir,
                    extraction_profile=extraction_profile,
                    decisions=decisions,
                    runner=docling_runner,
                )
            else:
                text, raw_paths, log_path, version, _note, elapsed = _run_surya(
                    page=page,
                    source_image=source_image,
                    output_dir=engine_dir,
                    extraction_profile=extraction_profile,
                    decisions=decisions,
                    runner=surya_runner,
                )

            text_path = engine_dir / "text.txt"
            reference = references_by_page[page]
            metrics = error_metrics(truth_texts[page], text, profile)
            candidates.append(
                OcrTruthCandidateMetrics(
                    engine_key=spec.engine_key,
                    profile_key=extraction_profile.profile_key,
                    backend=extraction_profile.backend,
                    engine_version=version or _engine_version(spec.engine_key, extraction_profile),
                    page=page,
                    reference_sha256=reference.sha256,
                    elapsed_seconds=elapsed,
                    text_path=_relative(text_path, root),
                    raw_paths=[_relative(path, root) for path in raw_paths],
                    log_path=_relative(log_path, root) if log_path else None,
                    **metrics,
                )
            )

    aggregates = _aggregate(candidates)
    manifest = OcrTruthBenchmarkManifest(
        benchmark_id=benchmark_id,
        digital_object_id=digital.id,
        source_key=registration.source_key,
        preprocessing_run_id=preprocessing.id,
        source_sha256=digital.sha256,
        profile=profile,
        references=references,
        candidates=candidates,
        aggregates=aggregates,
        output_root=_relative(output_dir, root),
    )
    (output_dir / "manifest.json").write_text(
        manifest.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(_summary_markdown(manifest), encoding="utf-8")
    _write_csv(output_dir / "summary.csv", candidates)
    return OcrTruthBenchmarkSummary(
        source_key=source_key,
        benchmark_id=benchmark_id,
        output_root=_relative(output_dir, root),
        references=references,
        candidates=candidates,
        aggregates=aggregates,
    )
