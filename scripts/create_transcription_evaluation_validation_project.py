#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

from archive_workbench.db import current_revision, database_path
from archive_workbench.identity import sha256_file

EXPECTED_PLATFORM_ID = "CwWKigBOfjQ"
EXPECTED_CHANNEL_ID = "UCsZG_7l0cYIEtJNhajrFPYg"


def _source_snapshot(root: Path) -> dict[str, object]:
    db = database_path(root)
    if not db.is_file():
        raise RuntimeError(f"No existe la base fuente: {db}")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        quick = conn.execute("PRAGMA quick_check").fetchone()[0]
        fk = list(conn.execute("PRAGMA foreign_key_check"))
        registrations = conn.execute(
            "SELECT source_payload_json FROM source_registrations ORDER BY registered_at"
        ).fetchall()
        platform = None
        for row in registrations:
            payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            if isinstance(payload, dict) and isinstance(payload.get("platform_import"), dict):
                candidate = payload["platform_import"]
                if candidate.get("platform_id") == EXPECTED_PLATFORM_ID:
                    platform = candidate
                    break
        if platform is None:
            raise RuntimeError(
                "La base fuente no contiene el video validado de AV-02 (CwWKigBOfjQ)."
            )
        transcriptions = conn.execute("SELECT COUNT(*) FROM transcription_runs").fetchone()[0]
        media = conn.execute(
            """
            SELECT am.id, fi.relative_path, d.sha256
            FROM audiovisual_media am
            JOIN digital_objects d ON d.id = am.digital_object_id
            JOIN file_instances fi ON fi.digital_object_id = d.id
            WHERE d.id = (
                SELECT digital_object_id
                FROM source_registrations
                WHERE json_extract(source_payload_json, '$.platform_import.platform_id') = ?
                ORDER BY registered_at DESC
                LIMIT 1
            )
            ORDER BY fi.id
            LIMIT 1
            """,
            (EXPECTED_PLATFORM_ID,),
        ).fetchone()
        if media is None:
            raise RuntimeError("No se pudo localizar el archivo local del video AV-02.")
        media_path = root / media[1]
        if not media_path.is_file():
            raise RuntimeError(f"Falta el archivo audiovisual fuente: {media_path}")
        observed_sha = sha256_file(media_path)
        if observed_sha != media[2]:
            raise RuntimeError("El SHA-256 del video fuente no coincide con DigitalObject.")
        return {
            "quick_check": quick,
            "foreign_key_violations": len(fk),
            "platform": platform.get("platform"),
            "platform_id": platform.get("platform_id"),
            "channel_id": platform.get("channel_id"),
            "title": platform.get("title"),
            "relative_path": media[1],
            "sha256": observed_sha,
            "transcription_run_count": transcriptions,
        }
    finally:
        conn.close()


def create_validation_project(source: Path, destination: Path) -> dict[str, object]:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_dir():
        raise RuntimeError(f"No existe el proyecto AV-02 fuente: {source}")
    if destination.exists():
        raise RuntimeError(
            f"El destino ya existe y no se reemplazó: {destination}. Elegí otra ruta o conservá la base existente."
        )
    revision = current_revision(source)
    if revision not in {"0045_audiovisual_transcription", "0046_audiovisual_timeline_annotations", "0047_authority_relation_profiles"}:
        raise RuntimeError(f"La base fuente está en una revisión inesperada: {revision}")
    snapshot = _source_snapshot(source)
    if snapshot["quick_check"] != "ok" or snapshot["foreign_key_violations"] != 0:
        raise RuntimeError("La base AV-02 fuente no supera sus controles de integridad.")
    if snapshot["channel_id"] != EXPECTED_CHANNEL_ID:
        raise RuntimeError("El video AV-02 no pertenece al canal esperado de la validación.")
    if snapshot["transcription_run_count"] != 0:
        raise RuntimeError(
            "La base AV-02 fuente ya contiene transcripciones. AV-03 necesita copiar el estado anterior a la primera corrida."
        )

    shutil.copytree(source, destination, copy_function=shutil.copy2)
    copied = _source_snapshot(destination)
    if copied["sha256"] != snapshot["sha256"]:
        raise RuntimeError("El video cambió durante la copia de la base de validación.")

    return {
        "source": str(source),
        "destination": str(destination),
        "revision": current_revision(destination),
        "platform_id": copied["platform_id"],
        "channel_id": copied["channel_id"],
        "title": copied["title"],
        "relative_path": copied["relative_path"],
        "sha256": copied["sha256"],
        "transcription_run_count": copied["transcription_run_count"],
        "quick_check": copied["quick_check"],
        "foreign_key_violations": copied["foreign_key_violations"],
        "note": "se copió la base descartable AV-02; no se modificó ni eliminó el proyecto fuente y project_data no fue leído ni modificado",
        "project_data_touched": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        result = create_validation_project(args.source, args.destination)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
