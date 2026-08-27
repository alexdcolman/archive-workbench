from __future__ import annotations

import shutil
from pathlib import Path


PROJECT_DIRS = (
    "data/pdfs",
    "data/tiff",
    "data/other",
    "extraction",
    "derivatives",
    "derivatives/audiovisual",
    "transcripts",
    "ocr_benchmarks",
    "ground_truth/ocr",
    "region_previews",
    "indexes",
    "exchange/incoming",
    "exchange/outgoing",
    "backups",
    "logs",
    "config",
    "corpus",
)


def initialize_project(
    destination: str | Path,
    template_root: str | Path | None = None,
    *,
    allow_existing: bool = False,
) -> Path:
    root = Path(destination)
    if root.exists() and not allow_existing:
        raise FileExistsError(
            f"La ruta ya existe: {root}. Elegí otra carpeta o usá la operación explícita para completar un proyecto existente."
        )
    root.mkdir(parents=True, exist_ok=allow_existing)
    for relative in PROJECT_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)

    if template_root is not None:
        templates = Path(template_root)
        for target_name in (
            "decisions.yaml",
            "test_corpus.yaml",
            "extraction.yaml",
            "extraction_docling_es.yaml",
            "extraction_surya_es.yaml",
            "extraction_tesseract.yaml",
            "extraction_press_columns.yaml",
            "ocr_benchmark.yaml",
            "ocr_benchmark_truth.yaml",
            "regions_leg_17_leg_15_a_c_6.yaml",
        ):
            completed = templates / target_name
            generic = templates / target_name.replace(".yaml", ".template.yaml")
            source = completed if completed.exists() else generic
            target = root / "config" / target_name
            if source.exists() and not target.exists():
                shutil.copy2(source, target)
    return root
