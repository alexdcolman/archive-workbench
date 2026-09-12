#!/usr/bin/env python3
"""Verifica contratos públicos 1.0 y que su revisión base siga en la cadena SQLite."""

from __future__ import annotations

import hashlib
from importlib.resources import as_file, files
import json

from alembic.config import Config
from alembic.script import ScriptDirectory

import archive_workbench.contracts as contracts
from archive_workbench.contracts.stable_v1 import (
    DATABASE_REVISION_V1,
    PUBLIC_CONTRACT_EXPORTS_V1,
    PUBLIC_CONTRACT_SCHEMA_SHA256_V1,
    PUBLIC_CONTRACT_VERSION,
)
from archive_workbench.db.migrations import head_revision


def schema_sha256(model: type) -> str:
    payload = json.dumps(
        model.model_json_schema(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _migration_revisions() -> set[str]:
    migrations_ref = files("archive_workbench").joinpath("migrations")
    with as_file(migrations_ref) as migrations_path:
        cfg = Config()
        cfg.set_main_option("script_location", str(migrations_path))
        script = ScriptDirectory.from_config(cfg)
        head = script.get_current_head()
        if head is None:
            raise RuntimeError("No se pudo determinar la revisión SQLite actual")
        return {str(revision.revision) for revision in script.walk_revisions("base", head)}


def verify() -> None:
    actual_exports = tuple(contracts.__all__)
    if actual_exports != PUBLIC_CONTRACT_EXPORTS_V1:
        raise RuntimeError("Cambió la lista u orden de contratos públicos congelados para 1.0")

    mismatches: list[str] = []
    for name in PUBLIC_CONTRACT_EXPORTS_V1:
        model = getattr(contracts, name)
        actual = schema_sha256(model)
        expected = PUBLIC_CONTRACT_SCHEMA_SHA256_V1[name]
        if actual != expected:
            mismatches.append(f"{name}: {actual} != {expected}")
    if mismatches:
        raise RuntimeError(
            "Cambió el schema de contratos públicos congelados:\n" + "\n".join(mismatches)
        )

    # DATABASE_REVISION_V1 es la revisión congelada del release 1.0. Las versiones
    # 1.x posteriores pueden agregar migraciones, pero no pueden perder esa revisión
    # de la cadena que permite actualizar proyectos 1.0 de forma explícita.
    if DATABASE_REVISION_V1 not in _migration_revisions():
        raise RuntimeError(
            "La revisión SQLite congelada para 1.0 ya no pertenece a la cadena de migraciones: "
            f"{DATABASE_REVISION_V1!r}"
        )


def main() -> int:
    verify()
    print(f"CONTRATOS PUBLICOS {PUBLIC_CONTRACT_VERSION}: OK")
    print(f"Contratos: {len(PUBLIC_CONTRACT_EXPORTS_V1)}")
    print(f"Revisión base 1.0: {DATABASE_REVISION_V1}")
    print(f"Revisión SQLite actual: {head_revision()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
