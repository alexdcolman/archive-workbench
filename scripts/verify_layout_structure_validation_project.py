#!/usr/bin/env python3
"""Verifica la validación manual OCR-01C con mensajes diagnósticos explícitos."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from sqlalchemy import select

from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import EditableObject, EditablePage, ExtractedObject
from archive_workbench.layout_structure import (
    layout_proposal,
    layout_structure,
    layout_structure_history,
)

_EXPECTED_ACTIONS = {
    "apply_layout_proposal": "Confirmó columnas y aplicó el orden",
    "rename_layout_column": "Renombró una columna",
    "merge_layout_fragment": "Combinó una fragmentación",
    "archive_layout_duplicate": "Archivó un duplicado",
}


def _check(condition: bool, label: str, *, actual: object | None = None) -> bool:
    if condition:
        print(f"  OK: {label}")
        return True
    suffix = "" if actual is None else f" · valor actual: {actual!r}"
    print(f"  ERROR: {label}{suffix}")
    return False


def verify(destination: Path) -> int:
    destination = destination.expanduser().resolve()
    db_path = database_path(destination)
    export_root = destination / "exports" / "editable" / "layout_dos_columnas"
    summary_path = destination / "validation_summary.json"

    print("Verificación OCR-01C")
    print(f"Proyecto: {destination}")
    print(f"Base: {db_path}")

    failures = 0
    if not db_path.is_file():
        print("  ERROR: no existe la base de validación")
        return 1

    connection = sqlite3.connect(db_path)
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
    finally:
        connection.close()

    failures += not _check(quick_check == "ok", "PRAGMA quick_check: ok", actual=quick_check)
    failures += not _check(
        revision == "0045_audiovisual_transcription",
        "revisión 0045_audiovisual_transcription",
        actual=revision,
    )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            if page is None:
                print("  ERROR: no existe una página editable")
                return 1
            structure = layout_structure(session, editable_page_id=page.id)
            proposal = layout_proposal(session, editable_page_id=page.id)
            history = layout_structure_history(session, editable_page_id=page.id)
            editable = session.scalars(
                select(EditableObject).where(
                    EditableObject.editable_page_id == page.id
                )
            ).all()
            extracted = session.scalars(
                select(ExtractedObject).order_by(ExtractedObject.order_index)
            ).all()
    finally:
        engine.dispose()

    active_columns = {
        row.label: row
        for row in structure.columns
        if row.lifecycle_status == "active"
    }
    print("\nColumnas activas:")
    for label, column in active_columns.items():
        print(f"  - {label}: {len(column.object_ids)} objeto(s)")

    expected_columns = {"Columna 1", "Columna 2", "Margen derecho"}
    failures += not _check(
        set(active_columns) == expected_columns,
        "columnas activas: Columna 1, Columna 2 y Margen derecho",
        actual=sorted(active_columns),
    )

    right_bottom = next(
        (
            row
            for row in editable
            if (row.current_attributes_json or {}).get("validation_key")
            == "right_bottom"
        ),
        None,
    )
    if right_bottom is None:
        failures += 1
        print("  ERROR: no se encontró el objeto controlado Texto derecho inferior.")
    else:
        labels_for_right_bottom = [
            label
            for label, column in active_columns.items()
            if right_bottom.id in column.object_ids
        ]
        failures += not _check(
            "Margen derecho" in labels_for_right_bottom,
            "Texto derecho inferior. está asignado a Margen derecho",
            actual=labels_for_right_bottom,
        )

    active_objects = [row for row in editable if row.lifecycle_status == "active"]
    failures += not _check(
        len(active_objects) == 5,
        "quedan cinco objetos editables activos",
        actual=len(active_objects),
    )
    failures += not _check(
        len(proposal.fragment_candidates) == 0,
        "no quedan fragmentaciones pendientes",
        actual=len(proposal.fragment_candidates),
    )
    failures += not _check(
        len(proposal.duplicate_candidates) == 0,
        "no quedan duplicaciones pendientes",
        actual=len(proposal.duplicate_candidates),
    )
    failures += not _check(
        proposal.changed_positions == 0,
        "el orden vigente coincide con la propuesta",
        actual=proposal.changed_positions,
    )

    operations = [row.operation for row in history]
    actions = [str((row.details or {}).get("action") or "") for row in history]
    print("\nHistorial específico de Orden y estructura (verificado en la base):")
    for action, label in _EXPECTED_ACTIONS.items():
        present = action in actions
        print(f"  {'OK' if present else 'ERROR'}: {label}")
        failures += not present

    combined_creation = "create_and_assign_layout_column" in actions
    separate_creation = (
        "create_layout_column" in actions and "assign_layout_column" in actions
    )
    creation_ok = combined_creation or separate_creation
    creation_label = (
        "Creó una columna manual y asignó el objeto seleccionado"
        if combined_creation
        else "Creó una columna manual + Asignó el objeto seleccionado a una columna"
    )
    print(f"  {'OK' if creation_ok else 'ERROR'}: {creation_label}")
    failures += not creation_ok

    for operation, label in (("undo", "Deshizo la última acción"), ("redo", "Rehizo la última acción")):
        present = operation in operations
        print(f"  {'OK' if present else 'ERROR'}: {label}")
        failures += not present

    expected_source_texts = [
        "Texto derecho superior.",
        "Primera parte de un párrafo",
        "Texto duplicado.",
        "continuación y cierre.",
        "Texto duplicado.",
        "Segundo bloque izquierdo.",
        "Texto derecho inferior.",
    ]
    source_texts = [row.original_text for row in extracted]
    failures += not _check(
        len(extracted) == 7 and source_texts == expected_source_texts,
        "los siete objetos OCR de origen permanecen intactos",
        actual=source_texts,
    )

    manifest_path = export_root / "manifest.json"
    layouts_path = export_root / "layout_structures.jsonl"
    failures += not _check(manifest_path.is_file(), "existe manifest.json", actual=manifest_path)
    failures += not _check(
        layouts_path.is_file(),
        "existe layout_structures.jsonl",
        actual=layouts_path,
    )
    if manifest_path.is_file() and layouts_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        exported = [
            json.loads(line)
            for line in layouts_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        failures += not _check(
            manifest.get("schema_version") == "1.4",
            "schema de exportación 1.4",
            actual=manifest.get("schema_version"),
        )
        failures += not _check(
            manifest.get("layout_structure_count") == 1 and len(exported) == 1,
            "se exportó una estructura de layout",
            actual={
                "manifest_count": manifest.get("layout_structure_count"),
                "rows": len(exported),
            },
        )

    if not summary_path.is_file():
        failures += 1
        print(f"  ERROR: no existe {summary_path}")
    else:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        original_path = destination / "corpus" / "layout" / "dos_columnas.pdf"
        digest = sha256(original_path.read_bytes()).hexdigest()
        failures += not _check(
            digest == summary.get("original_sha256"),
            "el PDF original conserva su SHA-256",
            actual=digest,
        )
        failures += not _check(
            summary.get("project_data_touched") is False,
            "project_data_touched: false",
            actual=summary.get("project_data_touched"),
        )

    print()
    if failures:
        if "Marginal" in active_columns and "Margen derecho" not in active_columns:
            print("PASO PENDIENTE IDENTIFICADO:")
            print("  1. Abrí Revisar documentos > Orden y estructura.")
            print("  2. En el bloque 2, abrí «Renombrar o archivar columnas confirmadas».")
            print("  3. En la tarjeta «Marginal», cambiá Nombre a «Margen derecho».")
            print("  4. Pulsá «Guardar nombre».")
            print("  5. Volvé a ejecutar este diagnóstico.")
            print()
        print(f"RESULTADO: {failures} control(es) no coinciden. No avances con project_data.")
        return 1
    print("RESULTADO: validación OCR-01C completa y consistente.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(verify(args.destination))


if __name__ == "__main__":
    main()
