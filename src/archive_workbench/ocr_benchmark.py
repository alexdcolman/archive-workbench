from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.contracts.extraction import (
    OcrBenchmarkManifest,
    OcrBenchmarkProfile,
    OcrCandidateMetrics,
)
from archive_workbench.db.models import (
    DerivativeAsset,
    DigitalObject,
    PreprocessingRun,
    SourceRegistration,
)
from archive_workbench.identity import sha256_file
from archive_workbench.tesseract_engine import (
    prepare_image_variant,
    run_tesseract_page,
    text_quality_metrics,
)


@dataclass(slots=True)
class OcrBenchmarkSummary:
    source_key: str
    benchmark_id: str
    output_root: str
    candidates: list[OcrCandidateMetrics] = field(default_factory=list)


def load_ocr_benchmark_profile(path: str | Path) -> OcrBenchmarkProfile:
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"El perfil de benchmark debe ser un objeto YAML: {source}")
    return OcrBenchmarkProfile.model_validate(payload)


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


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
    assets = session.scalars(
        select(DerivativeAsset)
        .where(
            DerivativeAsset.preprocessing_run_id == preprocessing.id,
            DerivativeAsset.kind == "ocr",
        )
        .order_by(DerivativeAsset.page_number)
    ).all()
    if pages:
        available = {asset.page_number for asset in assets}
        missing = pages - available
        if missing:
            raise ValueError(f"Páginas inexistentes: {', '.join(map(str, sorted(missing)))}")
        assets = [asset for asset in assets if asset.page_number in pages]
    return registration, digital, preprocessing, list(assets)


def _summary_markdown(manifest: OcrBenchmarkManifest, previews: dict[str, str]) -> str:
    ordered = sorted(manifest.candidates, key=lambda item: item.heuristic_score, reverse=True)
    lines = [
        f"# Benchmark OCR: {manifest.source_key}",
        "",
        "El puntaje es heurístico: ordena candidatos para revisión, no mide exactitud contra una transcripción verdadera.",
        "",
        "| Candidato | Página | Variante | PSM | Caracteres | Palabras | Confianza | Puntaje |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for candidate in ordered:
        confidence = "-" if candidate.mean_confidence is None else f"{candidate.mean_confidence:.1f}"
        lines.append(
            f"| `{candidate.candidate_id}` | {candidate.page} | {candidate.image_variant} | "
            f"{candidate.psm} | {candidate.character_count} | {candidate.word_count} | "
            f"{confidence} | {candidate.heuristic_score:.3f} |"
        )
    for candidate in ordered:
        preview = previews.get(candidate.candidate_id, "").strip()
        if len(preview) > 1500:
            preview = preview[:1500] + "\n[…]"
        lines.extend(
            [
                "",
                f"## {candidate.candidate_id}",
                "",
                "```text",
                preview,
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def run_ocr_benchmark(
    session: Session,
    *,
    project_root: str | Path,
    source_key: str,
    profile: OcrBenchmarkProfile,
    pages: set[int] | None = None,
) -> OcrBenchmarkSummary:
    root = Path(project_root)
    registration, digital, preprocessing, assets = _source_and_assets(
        session, source_key=source_key, pages=set(pages or [])
    )
    benchmark_id = str(uuid4())
    output_dir = root / "ocr_benchmarks" / digital.id / benchmark_id
    variants_dir = output_dir / "variants"
    candidates_dir = output_dir / "candidates"
    output_dir.mkdir(parents=True, exist_ok=False)

    candidates: list[OcrCandidateMetrics] = []
    previews: dict[str, str] = {}
    for asset in assets:
        source = root / asset.relative_path
        if not source.is_file():
            raise RuntimeError(f"Falta el derivado OCR: {asset.relative_path}")
        if sha256_file(source) != asset.sha256:
            raise RuntimeError(f"El derivado OCR fue modificado: {asset.relative_path}")
        for variant in profile.image_variants:
            variant_path = variants_dir / f"page_{asset.page_number:04d}_{variant}.png"
            prepare_image_variant(source, variant_path, variant)
            for psm in profile.psm_modes:
                result = run_tesseract_page(
                    variant_path,
                    page_number=asset.page_number,
                    tesseract_command=profile.tesseract_command,
                    languages=profile.languages,
                    psm=psm,
                    image_variant=variant,
                    timeout_seconds=profile.timeout_seconds,
                )
                candidate_id = f"p{asset.page_number:04d}_{variant}_psm{psm}"
                tsv_path = candidates_dir / f"{candidate_id}.tsv"
                text_path = candidates_dir / f"{candidate_id}.txt"
                tsv_path.parent.mkdir(parents=True, exist_ok=True)
                tsv_path.write_text(result.tsv_text, encoding="utf-8")
                text_path.write_text(result.full_text, encoding="utf-8")
                metrics = text_quality_metrics(result.full_text, result.lines)
                candidate = OcrCandidateMetrics(
                    candidate_id=candidate_id,
                    page=asset.page_number,
                    psm=psm,
                    image_variant=variant,
                    text_path=_relative(text_path, root),
                    tsv_path=_relative(tsv_path, root),
                    image_path=_relative(variant_path, root),
                    **metrics,
                )
                candidates.append(candidate)
                previews[candidate_id] = result.full_text

    manifest = OcrBenchmarkManifest(
        benchmark_id=benchmark_id,
        digital_object_id=digital.id,
        source_key=registration.source_key,
        preprocessing_run_id=preprocessing.id,
        source_sha256=digital.sha256,
        profile=profile,
        created_at=datetime.now(timezone.utc),
        candidates=candidates,
        output_root=_relative(output_dir, root),
    )
    (output_dir / "manifest.json").write_text(
        manifest.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
    )
    (output_dir / "summary.md").write_text(
        _summary_markdown(manifest, previews), encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in sorted(candidates, key=lambda x: x.heuristic_score, reverse=True)],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return OcrBenchmarkSummary(
        source_key=source_key,
        benchmark_id=benchmark_id,
        output_root=_relative(output_dir, root),
        candidates=sorted(candidates, key=lambda item: item.heuristic_score, reverse=True),
    )
