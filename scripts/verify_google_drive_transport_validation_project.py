#!/usr/bin/env python3
"""Verifica la validación manual de INT-01 sin acceder a Google Drive ni a credenciales."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from sqlalchemy import select

from archive_workbench.db import create_sqlite_engine, current_revision, database_path, session_scope
from archive_workbench.db.models import ExchangeBundleRecord, ExchangeDryRun, ExchangeWorkspace, Project
from archive_workbench.exchange import inspect_change_bundle, sha256_file

EXPECTED_REVISION = "0047_authority_relation_profiles"
VALIDATION_FILE = Path("exchange/google_drive_validation.json")


def verify(project_root: Path) -> dict[str, object]:
    project_root = project_root.expanduser().resolve()
    db_path = database_path(project_root)
    failures: list[str] = []

    validation_path = project_root / VALIDATION_FILE
    if not validation_path.is_file():
        return {
            "ok": False,
            "project": str(project_root),
            "failures": [f"No existe {validation_path}."],
        }
    try:
        expected = json.loads(validation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "project": str(project_root),
            "failures": [f"No pude leer los datos de validación: {exc}"],
        }

    if not db_path.is_file():
        return {
            "ok": False,
            "project": str(project_root),
            "failures": ["No existe la base SQLite."],
        }

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

    expected_bundle_id = str(expected.get("bundle_id") or "")
    expected_sha = str(expected.get("bundle_sha256") or "")
    expected_project_id = str(expected.get("project_id") or "")
    expected_sender_workspace = str(expected.get("sender_workspace_id") or "")
    expected_receiver_workspace = str(expected.get("receiver_workspace_id") or "")

    downloaded_dir = project_root / "exchange" / "drive_downloads"
    matching_downloads: list[dict[str, object]] = []
    invalid_downloads: list[str] = []
    if downloaded_dir.is_dir():
        for path in sorted(downloaded_dir.glob("*.zip")):
            try:
                inspection = inspect_change_bundle(path)
                digest = sha256_file(path)
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                invalid_downloads.append(f"{path.name}: {exc}")
                continue
            if inspection.manifest.bundle_id == expected_bundle_id:
                matching_downloads.append(
                    {
                        "path": str(path),
                        "sha256": digest,
                        "project_id": inspection.manifest.project_id,
                        "source_workspace_id": inspection.manifest.source_workspace_id,
                        "base_state_sha256": inspection.manifest.base_checkpoint_state_sha256,
                    }
                )
    if not matching_downloads:
        failures.append("No se encontró en exchange/drive_downloads el bundle esperado.")
    elif not any(row["sha256"] == expected_sha for row in matching_downloads):
        failures.append("El bundle descargado esperado no conserva el SHA-256 original.")

    engine = create_sqlite_engine(db_path)
    project = None
    workspace = None
    dry = None
    record = None
    try:
        with session_scope(engine) as session:
            project = session.scalar(select(Project))
            workspace = session.scalar(select(ExchangeWorkspace))
            if expected_bundle_id:
                dry = session.scalar(
                    select(ExchangeDryRun).where(ExchangeDryRun.bundle_id == expected_bundle_id)
                )
                record = session.scalar(
                    select(ExchangeBundleRecord).where(
                        ExchangeBundleRecord.bundle_id == expected_bundle_id
                    )
                )
    finally:
        engine.dispose()

    if project is None or project.id != expected_project_id:
        failures.append("La copia receptora no conserva el proyecto esperado.")
    if workspace is None or workspace.id != expected_receiver_workspace:
        failures.append("La copia receptora no conserva la identidad de intercambio esperada.")
    if dry is None:
        failures.append("No se encontró el dry-run del bundle descargado.")
    else:
        if dry.source_workspace_id != expected_sender_workspace:
            failures.append("El dry-run no reconoce la copia emisora esperada.")
        if dry.base_match_status != "matched":
            failures.append(
                f"La base del paquete no quedó reconocida como matched: {dry.base_match_status}."
            )
        if dry.overall_status != "empty":
            failures.append(
                f"El paquete de control vacío debía quedar en estado empty: {dry.overall_status}."
            )
        if dict(dry.counts_json or {}) != {
            "apply": 0,
            "duplicate": 0,
            "review": 0,
            "conflict": 0,
        }:
            failures.append(f"Conteos inesperados en dry-run: {dry.counts_json!r}.")
    if record is None:
        failures.append("No se encontró el registro incoming del bundle.")
    else:
        if record.direction != "incoming":
            failures.append(f"Dirección inesperada del bundle: {record.direction}.")
        if record.bundle_sha256 != expected_sha:
            failures.append("El registro incoming no conserva el SHA-256 esperado.")
        if record.status != "assessed":
            failures.append(f"Estado inesperado del registro incoming: {record.status}.")

    return {
        "ok": not failures,
        "project": str(project_root),
        "revision": revision,
        "quick_check": quick,
        "foreign_key_violations": len(fk),
        "expected_bundle_id": expected_bundle_id,
        "expected_bundle_sha256": expected_sha,
        "drive_downloads": matching_downloads,
        "invalid_drive_downloads": invalid_downloads,
        "receiver_workspace_id": workspace.id if workspace else None,
        "incoming_record": (
            {
                "direction": record.direction,
                "status": record.status,
                "bundle_sha256": record.bundle_sha256,
            }
            if record
            else None
        ),
        "dry_run": (
            {
                "source_workspace_id": dry.source_workspace_id,
                "base_match_status": dry.base_match_status,
                "base_match_method": dry.base_match_method,
                "overall_status": dry.overall_status,
                "counts": dict(dry.counts_json or {}),
            }
            if dry
            else None
        ),
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
