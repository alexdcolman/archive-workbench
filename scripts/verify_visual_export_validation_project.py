#!/usr/bin/env python3
"""Verifica la exportación EXP-01 creada en el proyecto descartable."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path, PurePosixPath

from sqlalchemy import select

from archive_workbench.db import create_sqlite_engine, current_revision, database_path, session_scope
from archive_workbench.db.models import CorpusExportRun

EXPECTED_REVISION = "0047_authority_relation_profiles"
VALIDATION_FILE = Path("exports/exp01_validation.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(project_root: Path) -> dict[str, object]:
    project_root = project_root.expanduser().resolve()
    failures: list[str] = []
    validation_path = project_root / VALIDATION_FILE
    if not validation_path.is_file():
        return {"ok": False, "project": str(project_root), "failures": [f"Falta {validation_path}."]}
    expected = json.loads(validation_path.read_text(encoding="utf-8"))
    db_path = database_path(project_root)
    if not db_path.is_file():
        return {"ok": False, "project": str(project_root), "failures": ["Falta la base SQLite."]}

    with sqlite3.connect(db_path) as conn:
        quick = conn.execute("PRAGMA quick_check").fetchone()[0]
        fk = list(conn.execute("PRAGMA foreign_key_check"))
    revision = current_revision(project_root)
    if revision != EXPECTED_REVISION:
        failures.append(f"Revisión esperada {EXPECTED_REVISION}; actual: {revision}.")
    if quick != "ok":
        failures.append(f"PRAGMA quick_check devolvió {quick!r}.")
    if fk:
        failures.append(f"Hay {len(fk)} violaciones de claves foráneas.")

    original_path = project_root / str(expected["original_relative_path"])
    source_page_path = project_root / str(expected["page_asset_relative_path"])
    original_sha = _sha256(original_path) if original_path.is_file() else None
    source_page_sha = _sha256(source_page_path) if source_page_path.is_file() else None
    if original_sha != expected["original_sha256"]:
        failures.append("El original de validación cambió durante la prueba.")
    if source_page_sha != expected["page_asset_sha256"]:
        failures.append("La imagen de página usada por la extracción cambió durante la prueba.")

    engine = create_sqlite_engine(db_path)
    run = None
    try:
        with session_scope(engine) as session:
            run = session.scalar(
                select(CorpusExportRun)
                .where(
                    CorpusExportRun.project_id == expected["project_id"],
                    CorpusExportRun.output_format == "visual_zip",
                )
                .order_by(CorpusExportRun.created_at.desc(), CorpusExportRun.id.desc())
            )
    finally:
        engine.dispose()

    manifest = None
    package_path = None
    asset_summary: dict[str, int] = {}
    context_only_found = False
    if run is None:
        failures.append("No se encontró una exportación 'Exportar texto e imágenes (ZIP)'.")
    else:
        package_path = project_root / run.output_relative_path
        if not package_path.is_file():
            failures.append(f"No existe el ZIP registrado: {run.output_relative_path}.")
        elif _sha256(package_path) != run.output_sha256:
            failures.append("El SHA-256 del ZIP ya no coincide con el registro de exportación.")
        else:
            try:
                with zipfile.ZipFile(package_path) as archive:
                    names = archive.namelist()
                    for name in names:
                        pure = PurePosixPath(name)
                        if pure.is_absolute() or ".." in pure.parts:
                            failures.append(f"El ZIP contiene una ruta insegura: {name}.")
                    required = {
                        "manifest.json",
                        "text/records.jsonl",
                        "context/objects.jsonl",
                        "context/pages.jsonl",
                        "context/documents.jsonl",
                    }
                    missing = sorted(required - set(names))
                    if missing:
                        failures.append("Faltan archivos internos: " + ", ".join(missing) + ".")
                    manifest = json.loads(archive.read("manifest.json"))
                    if manifest.get("package_type") != "archive_workbench_text_and_images":
                        failures.append("El manifest no identifica el tipo de paquete esperado.")
                    if manifest.get("project_id") != expected["project_id"]:
                        failures.append("El manifest no conserva el proyecto esperado.")
                    text_meta = manifest.get("text") or {}
                    text_bytes = archive.read(str(text_meta.get("path") or "text/records.jsonl"))
                    if hashlib.sha256(text_bytes).hexdigest() != text_meta.get("sha256"):
                        failures.append("La huella de los registros textuales internos no coincide.")
                    context_meta = manifest.get("context") or {}
                    for path_key, hash_key in (
                        ("objects_path", "objects_sha256"),
                        ("pages_path", "pages_sha256"),
                        ("documents_path", "documents_sha256"),
                    ):
                        internal_path = str(context_meta.get(path_key) or "")
                        if internal_path and hashlib.sha256(archive.read(internal_path)).hexdigest() != context_meta.get(hash_key):
                            failures.append(f"La huella interna no coincide para {internal_path}.")
                    for asset in manifest.get("assets") or []:
                        internal = str(asset.get("path") or "")
                        if internal not in names:
                            failures.append(f"Falta el recurso visual {internal}.")
                            continue
                        payload = archive.read(internal)
                        if hashlib.sha256(payload).hexdigest() != asset.get("sha256"):
                            failures.append(f"La huella no coincide para {internal}.")
                        kind = str(asset.get("kind") or "")
                        asset_summary[kind] = asset_summary.get(kind, 0) + 1
                    context_rows = [
                        json.loads(line)
                        for line in archive.read("context/objects.jsonl").decode("utf-8").splitlines()
                        if line.strip()
                    ]
                    context_only_found = any(
                        row.get("object_id") == expected["context_object_id"]
                        and row.get("included_in_primary_export") is False
                        for row in context_rows
                    )
            except (OSError, ValueError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
                failures.append(f"No se pudo verificar el ZIP: {exc}")

    counts = expected["expected"]
    expected_assets = {
        "page": int(counts["pages"]),
        "region": int(counts["regions"]),
        "figure": int(counts["figures"]),
    }
    if manifest is not None:
        if manifest.get("text", {}).get("record_count") != counts["records"]:
            failures.append("La cantidad de registros principales no coincide.")
        if manifest.get("context", {}).get("object_count") != counts["context_objects"]:
            failures.append("La cantidad de objetos de contexto no coincide.")
        if asset_summary != expected_assets:
            failures.append(f"Recursos visuales inesperados: {asset_summary!r}.")
        if not context_only_found:
            failures.append("El objeto de contexto no quedó separado del contenido principal.")

    return {
        "ok": not failures,
        "project": str(project_root),
        "revision": revision,
        "quick_check": quick,
        "foreign_key_violations": len(fk),
        "original_sha256": original_sha,
        "page_source_sha256": source_page_sha,
        "export": (
            {
                "run_id": run.id,
                "path": str(package_path),
                "sha256": run.output_sha256,
                "records": run.row_count,
                "characters": run.character_count,
            }
            if run is not None and package_path is not None
            else None
        ),
        "assets": asset_summary,
        "context_only_object_verified": context_only_found,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()
    result = verify(args.project_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
