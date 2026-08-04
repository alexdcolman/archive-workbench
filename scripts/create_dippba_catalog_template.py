#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from archive_workbench.catalog_templates import export_catalog_template_bytes
from archive_workbench.decisions import load_decisions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera la primera plantilla XLSX de prueba del fondo DIPPBA."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Repositorio o proyecto que contiene config/decisions.yaml",
    )
    parser.add_argument(
        "--seed",
        type=Path,
        default=None,
        help="JSON fuente; por defecto usa config/catalog_templates/dippba_public_seed.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Archivo XLSX de salida",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    decisions_path = project_root / "config" / "decisions.yaml"
    seed_path = args.seed or (
        project_root / "config" / "catalog_templates" / "dippba_public_seed.json"
    )
    if not decisions_path.is_file():
        parser.error(f"No existe {decisions_path}")
    if not seed_path.is_file():
        parser.error(f"No existe {seed_path}")

    decisions = load_decisions(decisions_path)
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    content = export_catalog_template_bytes(
        None,
        decisions=decisions,
        project_id=decisions.project_id,
        include_catalog=False,
        template_name=seed["template_name"],
        target_project_id=seed.get("target_project_id", "*"),
        target_project_name=seed.get("target_project_name"),
        source_url=seed.get("source_url"),
        source_retrieved_at=seed.get("source_retrieved_at"),
        source_note=seed.get("source_note"),
        structure_parent_overrides=seed.get("structure_parent_overrides"),
        seed_rows=seed.get("rows", []),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(content)
    print(f"Plantilla escrita: {args.output}")
    print(f"Filas de catálogo: {len(seed.get('rows', []))}")
    print(f"Fuente principal: {seed.get('source_url', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
