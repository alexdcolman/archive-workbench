#!/usr/bin/env python3
"""Prepara una plantilla de seis zonas para retomar OCR-01D después del fix RC2."""

from __future__ import annotations

import argparse
from pathlib import Path

from archive_workbench.region_extraction import load_region_template
from archive_workbench.regional_workflow import (
    draft_from_region,
    template_from_drafts,
    write_region_template,
)


def prepare(destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    source = destination / "config" / "regions" / "ocr01d_controlada.yaml"
    if not source.is_file():
        raise SystemExit(f"No existe la plantilla controlada esperada: {source}")

    target = destination / "config" / "regions" / "ocr01d_controlada_resume.yaml"
    if target.exists():
        loaded = load_region_template(target)
        if len(loaded.regions) == 6 and any(
            row.semantic_role == "illustration" for row in loaded.regions
        ):
            print(f"Sin cambios: {target}")
            return target
        raise SystemExit(
            f"La plantilla de reanudación ya existe con otro contenido: {target}"
        )

    base = load_region_template(source)
    drafts = [draft_from_region(row) for row in base.regions]
    drafts.append(
        {
            "region_key": "ilustracion_controlada",
            "label": "Ilustración controlada",
            "page": 1,
            "reading_order": 50,
            "bbox": {"x0": 0.10, "y0": 0.49, "x1": 0.45, "y1": 0.72},
            "mode": "manual",
            "semantic_role": "illustration",
            "ocr": None,
            "initial_text": "",
            "note": "Zona dibujada manualmente durante la validación RC1.",
        }
    )
    template = template_from_drafts(
        source_key=base.source_key,
        drafts=drafts,
        template_key="ocr01d_controlada_resume",
        profile_key=base.profile_key,
    )
    write_region_template(target, template)
    print(f"Creado: {target}")
    print("Órdenes:", [row.reading_order for row in template.regions])
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.destination)


if __name__ == "__main__":
    main()
