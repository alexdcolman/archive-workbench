#!/usr/bin/env python3
"""Verifica el congelamiento de contratos públicos y esquema previsto para 1.0."""

from __future__ import annotations

import hashlib
import json

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

    actual_revision = head_revision()
    if actual_revision != DATABASE_REVISION_V1:
        raise RuntimeError(
            f"Cambió la revisión SQLite congelada para 1.0: {actual_revision!r} "
            f"!= {DATABASE_REVISION_V1!r}"
        )


def main() -> int:
    verify()
    print(f"CONTRATOS PUBLICOS {PUBLIC_CONTRACT_VERSION}: OK")
    print(f"Contratos: {len(PUBLIC_CONTRACT_EXPORTS_V1)}")
    print(f"Revisión SQLite: {DATABASE_REVISION_V1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
