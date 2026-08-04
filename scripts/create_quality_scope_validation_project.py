#!/usr/bin/env python3
"""Crea una copia descartable para validar alcances de calidad automáticos."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from sqlalchemy import delete, select

from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    CorpusExportProfile,
    CorpusExportRun,
    EditablePage,
    SemanticIndexRun,
    SemanticSearchProfile,
)


def create_validation_copy(source: Path, destination: Path, *, force: bool) -> dict[str, object]:
    source = source.resolve()
    destination = destination.resolve()
    if not database_path(source).exists():
        raise SystemExit(f"No se encontró una base de proyecto en: {source}")
    if destination.exists():
        if not force:
            raise SystemExit(
                f"El destino ya existe: {destination}. Usá --force para recrearlo."
            )
        shutil.rmtree(destination)
    shutil.copytree(source, destination)

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            session.execute(delete(SemanticIndexRun))
            session.execute(delete(SemanticSearchProfile))
            session.execute(delete(CorpusExportRun))
            session.execute(delete(CorpusExportProfile))

            page = session.scalar(
                select(EditablePage)
                .where(EditablePage.status == "active")
                .order_by(EditablePage.page_number, EditablePage.id)
                .limit(1)
            )
            if page is None:
                raise RuntimeError("La copia no contiene páginas editables activas.")
            page.review_status = "approved"
            session.flush()

            result = {
                "destination": destination,
                "approved_page_id": page.id,
                "approved_page_number": page.page_number,
            }
    finally:
        engine.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = create_validation_copy(args.source, args.destination, force=args.force)
    print(f"Proyecto descartable creado: {result['destination']}")
    print(
        "Página aprobada para la prueba: "
        f"{result['approved_page_number']} ({result['approved_page_id']})"
    )
    print("Perfiles de exportación y búsqueda semántica reiniciados en la copia.")


if __name__ == "__main__":
    main()
