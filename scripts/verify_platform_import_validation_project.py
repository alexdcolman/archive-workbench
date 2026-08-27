#!/usr/bin/env python3
"""Diagnóstico explícito de la validación manual AV-02 sobre un proyecto descartable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select, text

from archive_workbench.db import create_sqlite_engine, current_revision, database_path, session_scope
from archive_workbench.db.models import (
    AudiovisualMedia,
    DigitalObject,
    FileInstance,
    SourceRegistration,
    TranscriptionRun,
)
from archive_workbench.identity import sha256_file

EXPECTED_REVISION = "0047_authority_relation_profiles"
EXPECTED_CHANNEL_ID = "UCsZG_7l0cYIEtJNhajrFPYg"
EXPECTED_ACCESS_CONDITIONS = "Material autorizado para prueba AV-02."


def verify(root: Path) -> tuple[bool, dict[str, object]]:
    root = root.expanduser().resolve()
    failures: list[str] = []
    details: dict[str, object] = {"project": str(root)}

    if root.name == "project_data" or "archive_app/project_data" in root.as_posix():
        failures.append("La ruta apunta a project_data; esta verificación solo admite una base descartable.")
        return False, {**details, "failures": failures, "ok": False}
    if not root.is_dir():
        failures.append("El proyecto de validación no existe.")
        return False, {**details, "failures": failures, "ok": False}

    summary_path = root / "validation_summary.json"
    if not summary_path.is_file():
        failures.append("Falta validation_summary.json creado por el preparador AV-02.")
        return False, {**details, "failures": failures, "ok": False}

    revision = current_revision(root)
    details["revision"] = revision
    if revision != EXPECTED_REVISION:
        failures.append(f"Revisión inesperada: {revision!r}; se esperaba {EXPECTED_REVISION!r}.")

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            integrity = session.execute(text("PRAGMA quick_check")).scalar_one()
            foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()
            details["quick_check"] = integrity
            details["foreign_key_violations"] = len(foreign_keys)
            if integrity != "ok":
                failures.append(f"PRAGMA quick_check devolvió {integrity!r}.")
            if foreign_keys:
                failures.append(f"PRAGMA foreign_key_check devolvió {len(foreign_keys)} violaciones.")

            registrations = session.scalars(
                select(SourceRegistration)
                .where(SourceRegistration.project_id == "av02_platform_validation")
                .order_by(SourceRegistration.registered_at, SourceRegistration.id)
            ).all()
            platform_rows = [
                row
                for row in registrations
                if (row.source_payload_json or {}).get("origin") == "platform_import"
            ]
            details["platform_import_count"] = len(platform_rows)
            if len(platform_rows) != 1:
                failures.append(
                    f"Se esperaba exactamente una incorporación de plataforma y hay {len(platform_rows)}."
                )
            else:
                registration = platform_rows[0]
                platform = (registration.source_payload_json or {}).get("platform_import") or {}
                if not isinstance(platform, dict):
                    platform = {}
                details["platform"] = platform.get("platform")
                details["platform_id"] = platform.get("platform_id")
                details["source_url"] = platform.get("webpage_url")
                details["channel"] = platform.get("channel") or platform.get("uploader")
                details["channel_id"] = platform.get("channel_id") or platform.get("uploader_id")
                details["upload_date"] = platform.get("upload_date")
                details["access_conditions"] = platform.get("access_conditions")
                details["yt_dlp_version"] = platform.get("yt_dlp_version")
                details["authorization_confirmed"] = platform.get("authorization_confirmed")

                if platform.get("platform") != "youtube":
                    failures.append(f"La plataforma registrada no es YouTube: {platform.get('platform')!r}.")
                if not platform.get("platform_id"):
                    failures.append("Falta el identificador estable de plataforma.")
                if (platform.get("channel_id") or platform.get("uploader_id")) != EXPECTED_CHANNEL_ID:
                    failures.append(
                        "El material incorporado no corresponde al canal de validación acordado."
                    )
                if platform.get("access_conditions") != EXPECTED_ACCESS_CONDITIONS:
                    failures.append("Las condiciones de acceso/autorización no coinciden con la prueba.")
                if platform.get("authorization_confirmed") is not True:
                    failures.append("No quedó registrada la confirmación explícita de autorización.")

                if registration.digital_object_id is None:
                    failures.append("El registro de plataforma no quedó vinculado a un objeto digital.")
                else:
                    digital = session.get(DigitalObject, registration.digital_object_id)
                    if digital is None:
                        failures.append("Falta el DigitalObject de la incorporación.")
                    else:
                        details["digital_media_type"] = digital.media_type
                        details["digital_sha256"] = digital.sha256
                        if digital.media_type != "video":
                            failures.append(
                                f"La validación esperaba video y se registró {digital.media_type!r}."
                            )
                        file_row = session.scalar(
                            select(FileInstance)
                            .where(FileInstance.digital_object_id == digital.id)
                            .order_by(FileInstance.relative_path)
                        )
                        if file_row is None:
                            failures.append("Falta FileInstance para el video incorporado.")
                        else:
                            source = root / file_row.relative_path
                            details["relative_path"] = file_row.relative_path
                            if not source.is_file():
                                failures.append(f"Falta el archivo local incorporado: {file_row.relative_path}.")
                            else:
                                observed = sha256_file(source)
                                details["observed_sha256"] = observed
                                if observed != digital.sha256:
                                    failures.append("El SHA-256 del archivo local no coincide con DigitalObject.")
                                if observed != platform.get("incorporated_sha256"):
                                    failures.append("El SHA-256 local no coincide con la procedencia remota registrada.")

                        media = session.scalar(
                            select(AudiovisualMedia).where(
                                AudiovisualMedia.digital_object_id == digital.id
                            )
                        )
                        if media is None:
                            failures.append("El video no ingresó al circuito audiovisual de AV-01.")
                        else:
                            details["media_id"] = media.id
                            details["media_title"] = media.title
                            details["duration_seconds"] = media.duration_seconds
                            details["media_provenance"] = media.provenance
                            details["media_rights"] = media.rights
                            if not media.duration_seconds:
                                failures.append("FFprobe no registró la duración del video.")
                            if media.provenance != platform.get("webpage_url"):
                                failures.append("La ficha audiovisual no conserva la URL de procedencia.")
                            if media.rights != EXPECTED_ACCESS_CONDITIONS:
                                failures.append("La ficha audiovisual no conserva las condiciones de acceso.")
                            runs = session.scalars(
                                select(TranscriptionRun).where(
                                    TranscriptionRun.audiovisual_media_id == media.id
                                )
                            ).all()
                            details["transcription_run_count"] = len(runs)
                            if runs:
                                failures.append(
                                    "AV-02 inició una transcripción automática; debe dejarla para AV-01/AV-03."
                                )
    finally:
        engine.dispose()

    details["failures"] = failures
    details["ok"] = not failures
    return not failures, details


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()
    ok, details = verify(args.project_root)
    print(json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
