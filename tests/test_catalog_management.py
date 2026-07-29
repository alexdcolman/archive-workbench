from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from sqlalchemy import select

from archive_workbench.catalog import ensure_project
from archive_workbench.catalog_management import (
    archival_field_rows,
    archival_revision_rows,
    catalog_summary,
    catalog_unit_rows,
    create_archival_unit,
    move_archival_unit,
    undo_last_archival_move,
    unlink_digital_object_from_unit,
    remove_file_instance,
    register_local_file,
    register_uploaded_file,
    search_catalog_units,
    unit_digital_objects,
    update_archival_unit,
)
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.decisions import load_decisions
from archive_workbench.extraction import _selected_registrations
from archive_workbench.db.models import ArchivalUnit, DigitalObject, DigitalObjectUnitLink, FileInstance, SourceRegistration


def _write_pdf(path: Path, text: str = "prueba") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=500, height=400)
    page.insert_text((50, 80), text)
    document.save(path)
    document.close()


def _setup(tmp_path: Path):
    root = tmp_path / "project"
    upgrade_database(root)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        ensure_project(session, decisions)
    return root, decisions, engine


def test_create_update_move_and_history(tmp_path: Path) -> None:
    root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo Provincial",
                created_by="Alex",
            )
            fondo = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=archivo.id,
                level_key="fondo",
                title="Fondo Policía",
                created_by="Alex",
            )
            caja = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=fondo.id,
                level_key="caja",
                title="Caja 1",
                created_by="Alex",
            )
            legajo = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=caja.id,
                level_key="legajo",
                title="Legajo 17",
                created_by="Alex",
            )
            update_archival_unit(
                session,
                decisions=decisions,
                unit_id=legajo.id,
                changed_by="Alex",
                title="Legajo 17 corregido",
                reference_code="APM-POL-17",
                registration_status="provisional",
                completion_confirmed=False,
                field_values={
                    "extent": {"state": "provided", "values": ["59 páginas"]},
                    "scope_content": {
                        "state": "provided",
                        "values": ["Informes", "Correspondencia"],
                    },
                },
                note="Primera descripción",
            )
            move_archival_unit(
                session,
                decisions=decisions,
                unit_id=legajo.id,
                new_parent_id=fondo.id,
                changed_by="Alex",
            )
            fields = archival_field_rows(session, legajo.id)
            revisions = archival_revision_rows(session, legajo.id)
            rows = catalog_unit_rows(session, decisions.project_id)
        assert [row.value for row in fields if row.field_key == "scope_content"] == [
            "Informes",
            "Correspondencia",
        ]
        assert [row.operation for row in revisions] == ["move", "update", "create"]
        row = next(item for item in rows if item.id == legajo.id)
        assert row.parent_id == fondo.id
        assert row.title == "Legajo 17 corregido"
        assert row.revision == 3
    finally:
        engine.dispose()


def test_hierarchy_validation_rejects_invalid_parent_and_cycle(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo",
                created_by="Alex",
            )
            fondo = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=archivo.id,
                level_key="fondo",
                title="Fondo",
                created_by="Alex",
            )
            serie = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=fondo.id,
                level_key="serie",
                title="Serie",
                created_by="Alex",
            )
            with pytest.raises(ValueError, match="necesita una unidad padre"):
                create_archival_unit(
                    session,
                    decisions=decisions,
                    project_id=decisions.project_id,
                    parent_id=None,
                    level_key="documento",
                    title="Documento suelto",
                    created_by="Alex",
                )
            with pytest.raises(ValueError, match="descendiente"):
                move_archival_unit(
                    session,
                    decisions=decisions,
                    unit_id=fondo.id,
                    new_parent_id=serie.id,
                    changed_by="Alex",
                )
    finally:
        engine.dispose()


def test_register_file_deduplicates_content_and_searches_catalog(tmp_path: Path) -> None:
    root, decisions, engine = _setup(tmp_path)
    _write_pdf(root / "corpus" / "documento.pdf", "contenido policial")
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo",
                created_by="Alex",
            )
            fondo = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=archivo.id,
                level_key="fondo",
                title="Fondo Policía",
                created_by="Alex",
            )
            caja1 = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=fondo.id,
                level_key="caja",
                title="Caja secreta",
                created_by="Alex",
            )
            caja2 = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=fondo.id,
                level_key="caja",
                title="Caja duplicada",
                created_by="Alex",
            )
            first = register_local_file(
                session,
                project_root=root,
                project_id=decisions.project_id,
                archival_unit_id=caja1.id,
                relative_path="corpus/documento.pdf",
            )
            second = register_local_file(
                session,
                project_root=root,
                project_id=decisions.project_id,
                archival_unit_id=caja2.id,
                relative_path="corpus/documento.pdf",
            )
            objects1 = unit_digital_objects(session, caja1.id)
            objects2 = unit_digital_objects(session, caja2.id)
            found = search_catalog_units(
                session,
                project_id=decisions.project_id,
                query="documento.pdf",
            )
            summary = catalog_summary(session, decisions.project_id)
        assert first.digital_object_created is True
        assert second.digital_object_created is False
        assert second.duplicate_content is True
        assert first.source_key == second.source_key
        assert objects1[0].id == objects2[0].id
        assert {row.id for row in found} == {caja1.id, caja2.id}
        assert summary.digital_objects == 1
        assert summary.file_instances == 1
    finally:
        engine.dispose()


def test_catalog_registered_file_is_available_to_document_pipeline(tmp_path: Path) -> None:
    root, decisions, engine = _setup(tmp_path)
    pdf_path = root / "corpus" / "catalogado.pdf"
    _write_pdf(pdf_path, "documento catalogado")
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo",
                created_by="Alex",
            )
            result = register_local_file(
                session,
                project_root=root,
                project_id=decisions.project_id,
                archival_unit_id=archivo.id,
                relative_path="corpus/catalogado.pdf",
                registered_by="Alex",
            )
            registration = session.scalar(
                select(SourceRegistration).where(
                    SourceRegistration.project_id == decisions.project_id,
                    SourceRegistration.source_key == result.source_key,
                )
            )
            selected = _selected_registrations(session, {result.source_key})
        assert registration is not None
        assert registration.source_type == "catalog"
        assert registration.registered_by == "Alex"
        assert registration.source_payload_json["local_path"] == "corpus/catalogado.pdf"
        assert [row[0].source_key for row in selected] == [result.source_key]
    finally:
        engine.dispose()


def test_complete_registration_requires_manual_confirmation(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo",
                created_by="Alex",
            )
            with pytest.raises(ValueError, match="confirmación manual"):
                update_archival_unit(
                    session,
                    decisions=decisions,
                    unit_id=archivo.id,
                    changed_by="Alex",
                    title=archivo.title,
                    reference_code=None,
                    registration_status="complete",
                    completion_confirmed=False,
                    field_values={},
                )
            updated = update_archival_unit(
                session,
                decisions=decisions,
                unit_id=archivo.id,
                changed_by="Alex",
                title=archivo.title,
                reference_code=None,
                registration_status="provisional",
                completion_confirmed=True,
                field_values={},
            )
            assert updated.registration_status == "complete"
            assert updated.completion_confirmed_by == "Alex"
    finally:
        engine.dispose()


def test_catalog_migration_preserves_populated_0018_database(tmp_path: Path) -> None:
    from sqlalchemy import inspect

    root = tmp_path / "project"
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root, revision="0018_exchange_resolution_usability")
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            ensure_project(session, decisions)
            unit = ArchivalUnit(
                id="11111111-1111-4111-8111-111111111111",
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo existente",
                registration_status="incomplete",
                completion_confirmed=False,
                created_by="Alex",
                updated_by="Alex",
                revision=1,
            )
            session.add(unit)
    finally:
        engine.dispose()

    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            preserved = session.get(ArchivalUnit, "11111111-1111-4111-8111-111111111111")
            assert preserved is not None
            assert preserved.title == "Archivo existente"
        assert "archival_unit_revisions" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_uploaded_file_is_copied_under_project_and_registered(tmp_path: Path) -> None:
    root, decisions, engine = _setup(tmp_path)
    source = tmp_path / "outside.pdf"
    _write_pdf(source, "archivo seleccionado")
    content = source.read_bytes()
    try:
        with session_scope(engine) as session:
            unit = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo",
                created_by="Alex",
            )
            first = register_uploaded_file(
                session,
                project_root=root,
                project_id=decisions.project_id,
                archival_unit_id=unit.id,
                original_filename="seleccionado.pdf",
                content=content,
                destination_dir="corpus/importados",
                registered_by="Alex",
            )
            second = register_uploaded_file(
                session,
                project_root=root,
                project_id=decisions.project_id,
                archival_unit_id=unit.id,
                original_filename="seleccionado.pdf",
                content=content,
                destination_dir="corpus/importados",
                registered_by="Alex",
            )
        assert first.relative_path == "corpus/importados/seleccionado.pdf"
        assert (root / first.relative_path).read_bytes() == content
        assert first.reused_existing_path is False
        assert second.relative_path == first.relative_path
        assert second.reused_existing_path is True
        assert second.registration.digital_object_id == first.registration.digital_object_id
    finally:
        engine.dispose()


def test_document_can_be_created_as_child_of_selected_box_and_move_can_be_undone(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(
                session, decisions=decisions, project_id=decisions.project_id,
                parent_id=None, level_key="archivo", title="Archivo", created_by="Alex",
            )
            fondo = create_archival_unit(
                session, decisions=decisions, project_id=decisions.project_id,
                parent_id=archivo.id, level_key="fondo", title="Fondo", created_by="Alex",
            )
            caja_1 = create_archival_unit(
                session, decisions=decisions, project_id=decisions.project_id,
                parent_id=fondo.id, level_key="caja", title="Caja 1", created_by="Alex",
            )
            caja_2 = create_archival_unit(
                session, decisions=decisions, project_id=decisions.project_id,
                parent_id=fondo.id, level_key="caja", title="Caja 2", created_by="Alex",
            )
            documento = create_archival_unit(
                session, decisions=decisions, project_id=decisions.project_id,
                parent_id=caja_1.id, level_key="documento", title="Informe", created_by="Alex",
            )
            assert documento.parent_id == caja_1.id
            move_archival_unit(
                session, decisions=decisions, unit_id=documento.id,
                new_parent_id=caja_2.id, changed_by="Alex",
            )
            assert documento.parent_id == caja_2.id
            undo_last_archival_move(
                session, decisions=decisions, unit_id=documento.id, changed_by="Alex",
            )
            assert documento.parent_id == caja_1.id
            assert archival_revision_rows(session, documento.id)[0].operation == "undo_move"
    finally:
        engine.dispose()


def test_unlink_and_remove_local_file_are_separate_operations(tmp_path: Path) -> None:
    root, decisions, engine = _setup(tmp_path)
    pdf_path = root / "corpus" / "retirable.pdf"
    _write_pdf(pdf_path, "contenido")
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(
                session, decisions=decisions, project_id=decisions.project_id,
                parent_id=None, level_key="archivo", title="Archivo", created_by="Alex",
            )
            result = register_local_file(
                session, project_root=root, project_id=decisions.project_id,
                archival_unit_id=archivo.id, relative_path="corpus/retirable.pdf",
            )
            unlink = unlink_digital_object_from_unit(
                session, link_id=result.link_id, removed_by="Alex"
            )
            assert unlink.remaining_links == 0
            assert session.get(DigitalObject, result.digital_object_id) is not None
            assert session.get(DigitalObjectUnitLink, result.link_id) is None
            assert pdf_path.exists()
            removal = remove_file_instance(
                session, project_root=root, file_instance_id=result.file_instance_id,
                delete_physical=False, removed_by="Alex",
            )
            assert removal.physical_deleted is False
            assert session.get(FileInstance, result.file_instance_id) is None
            assert pdf_path.exists()
    finally:
        engine.dispose()


def test_remove_file_instance_can_delete_physical_file_with_explicit_flag(tmp_path: Path) -> None:
    root, decisions, engine = _setup(tmp_path)
    pdf_path = root / "corpus" / "eliminar.pdf"
    _write_pdf(pdf_path, "contenido")
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(
                session, decisions=decisions, project_id=decisions.project_id,
                parent_id=None, level_key="archivo", title="Archivo", created_by="Alex",
            )
            result = register_local_file(
                session, project_root=root, project_id=decisions.project_id,
                archival_unit_id=archivo.id, relative_path="corpus/eliminar.pdf",
            )
            removal = remove_file_instance(
                session, project_root=root, file_instance_id=result.file_instance_id,
                delete_physical=True, removed_by="Alex",
            )
            assert removal.physical_deleted is True
            assert not pdf_path.exists()
    finally:
        engine.dispose()
