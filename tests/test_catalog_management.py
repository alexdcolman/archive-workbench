from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image
import pytest
from sqlalchemy import select

from archive_workbench.catalog import ensure_project
from archive_workbench.catalog_app import (
    _catalog_document_cached_thumbnail_data_url,
    _catalog_document_thumbnail_data_url,
)
from archive_workbench.catalog_documents import (
    DocumentComponentDraft,
    DocumentGroupDraft,
    create_document_groups,
    natural_filename_key,
    organization_source_rows,
    record_level_options,
)
from archive_workbench.catalog_management import (
    archival_field_rows,
    archival_revision_rows,
    catalog_summary,
    archival_unit_delete_blockers,
    catalog_unit_rows,
    change_archival_unit_level,
    create_archival_unit,
    delete_archival_unit,
    move_archival_unit,
    undo_last_archival_move,
    unlink_digital_object_from_unit,
    remove_file_instance,
    register_external_file,
    register_local_file,
    register_uploaded_file,
    search_catalog_units,
    unit_digital_objects,
    update_archival_unit,
)
from archive_workbench.db import (
    create_sqlite_engine,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.extraction import _selected_registrations
from archive_workbench.identity import new_id
from archive_workbench.exchange import ensure_exchange_workspace
from archive_workbench.db.models import (
    ArchivalDocumentComponent,
    ArchivalUnit,
    DigitalObject,
    DigitalObjectUnitLink,
    ExchangeChangeEvent,
    FileInstance,
    SourceRegistration,
    DerivativeAsset,
    PreprocessingRun,
)


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



def test_catalog_document_source_names_use_natural_numeric_order() -> None:
    names = [
        "legajo n° 15 A.C.1.tiff",
        "legajo n° 15 A.C.10.tiff",
        "legajo n° 15 A.C.100.tiff",
        "legajo n° 15 A.C.2.tiff",
        "legajo n° 15 A.C.11.tiff",
    ]
    assert sorted(names, key=natural_filename_key) == [
        "legajo n° 15 A.C.1.tiff",
        "legajo n° 15 A.C.2.tiff",
        "legajo n° 15 A.C.10.tiff",
        "legajo n° 15 A.C.11.tiff",
        "legajo n° 15 A.C.100.tiff",
    ]


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


def test_document_can_be_created_as_child_of_selected_box_and_move_can_be_undone(
    tmp_path: Path,
) -> None:
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
            caja_1 = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=fondo.id,
                level_key="caja",
                title="Caja 1",
                created_by="Alex",
            )
            caja_2 = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=fondo.id,
                level_key="caja",
                title="Caja 2",
                created_by="Alex",
            )
            documento = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=caja_1.id,
                level_key="documento",
                title="Informe",
                created_by="Alex",
            )
            assert documento.parent_id == caja_1.id
            move_archival_unit(
                session,
                decisions=decisions,
                unit_id=documento.id,
                new_parent_id=caja_2.id,
                changed_by="Alex",
            )
            assert documento.parent_id == caja_2.id
            undo_last_archival_move(
                session,
                decisions=decisions,
                unit_id=documento.id,
                changed_by="Alex",
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
                relative_path="corpus/retirable.pdf",
            )
            unlink = unlink_digital_object_from_unit(
                session, link_id=result.link_id, removed_by="Alex"
            )
            assert unlink.remaining_links == 0
            assert session.get(DigitalObject, result.digital_object_id) is not None
            assert session.get(DigitalObjectUnitLink, result.link_id) is None
            assert pdf_path.exists()
            removal = remove_file_instance(
                session,
                project_root=root,
                file_instance_id=result.file_instance_id,
                delete_physical=False,
                removed_by="Alex",
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
                relative_path="corpus/eliminar.pdf",
            )
            removal = remove_file_instance(
                session,
                project_root=root,
                file_instance_id=result.file_instance_id,
                delete_physical=True,
                removed_by="Alex",
            )
            assert removal.physical_deleted is True
            assert not pdf_path.exists()
    finally:
        engine.dispose()


def test_register_external_file_copies_and_registers_without_modifying_source(
    tmp_path: Path,
) -> None:
    root, decisions, engine = _setup(tmp_path)
    source = tmp_path / "outside" / "documento.pdf"
    _write_pdf(source, "contenido externo")
    source_before = source.read_bytes()
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
            result = register_external_file(
                session,
                project_root=root,
                project_id=decisions.project_id,
                archival_unit_id=unit.id,
                source_path=source,
                destination_dir="corpus/lote",
                page_start=1,
                page_end=1,
                registered_by="Alex",
            )
            relative = result.relative_path
        assert relative == "corpus/lote/documento.pdf"
        assert (root / relative).read_bytes() == source_before
        assert source.read_bytes() == source_before
        with session_scope(engine) as session:
            assert (
                session.scalar(select(FileInstance).where(FileInstance.relative_path == relative))
                is not None
            )
    finally:
        engine.dispose()


def test_change_level_is_validated_and_audited(tmp_path: Path) -> None:
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
                title="rememorARTE",
                created_by="Alex",
            )
            changed = change_archival_unit_level(
                session,
                decisions=decisions,
                unit_id=fondo.id,
                new_level_key="coleccion",
                changed_by="Alex",
            )
            assert changed.level_key == "coleccion"
            assert changed.id == fondo.id
            assert archival_revision_rows(session, fondo.id)[0].operation == "change_level"
    finally:
        engine.dispose()


def test_change_level_rejects_incompatible_children(tmp_path: Path) -> None:
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
            create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=fondo.id,
                level_key="caja",
                title="Caja",
                created_by="Alex",
            )
            with pytest.raises(ValueError, match="unidades hijas"):
                change_archival_unit_level(
                    session,
                    decisions=decisions,
                    unit_id=fondo.id,
                    new_level_key="coleccion",
                    changed_by="Alex",
                )
    finally:
        engine.dispose()


def test_delete_archival_unit_only_when_empty(tmp_path: Path) -> None:
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
                title="Vacío",
                created_by="Alex",
            )
            assert archival_unit_delete_blockers(session, fondo.id) == []
            assert delete_archival_unit(session, unit_id=fondo.id, deleted_by="Alex") == "Vacío"
            assert session.get(ArchivalUnit, fondo.id) is None
            assert session.get(ArchivalUnit, archivo.id) is not None
    finally:
        engine.dispose()


def test_delete_archival_unit_rejects_children_and_digital_links(tmp_path: Path) -> None:
    root, decisions, engine = _setup(tmp_path)
    _write_pdf(root / "corpus" / "vinculado.pdf", "contenido")
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
            create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=fondo.id,
                level_key="documento",
                title="Hijo",
                created_by="Alex",
            )
            register_local_file(
                session,
                project_root=root,
                project_id=decisions.project_id,
                archival_unit_id=fondo.id,
                relative_path="corpus/vinculado.pdf",
            )
            blockers = archival_unit_delete_blockers(session, fondo.id)
            assert any("hija" in item for item in blockers)
            assert any("contenidos digitales" in item for item in blockers)
            with pytest.raises(ValueError, match="no puede eliminarse"):
                delete_archival_unit(session, unit_id=fondo.id, deleted_by="Alex")
    finally:
        engine.dispose()


def test_organization_source_rows_exposes_current_preview_derivative(tmp_path: Path) -> None:
    root, decisions, engine = _setup(tmp_path)
    source_path = root / "corpus" / "001.tiff"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 120), "white").save(source_path, format="TIFF")
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=None, level_key="archivo", title="Archivo", created_by="Alex")
            fondo = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=archivo.id, level_key="fondo", title="Fondo", created_by="Alex")
            caja = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=fondo.id, level_key="caja", title="Caja", created_by="Alex")
            legajo = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=caja.id, level_key="legajo", title="Legajo", created_by="Alex")
            registered = register_local_file(
                session,
                project_root=root,
                project_id=decisions.project_id,
                archival_unit_id=legajo.id,
                relative_path="corpus/001.tiff",
                registered_by="Alex",
            )
            run_id = new_id()
            session.add(
                PreprocessingRun(
                    id=run_id,
                    digital_object_id=registered.digital_object_id,
                    source_sha256="0" * 64,
                    profile_key="test",
                    options_json={},
                    options_hash="1" * 64,
                    backend="test",
                    status="completed",
                    is_current=True,
                    output_root="derivatives/test",
                )
            )
            session.flush()
            session.add(
                DerivativeAsset(
                    id=new_id(),
                    preprocessing_run_id=run_id,
                    digital_object_id=registered.digital_object_id,
                    page_number=1,
                    kind="preview",
                    relative_path="derivatives/test/page_0001_preview.jpg",
                    mime_type="image/jpeg",
                    sha256="2" * 64,
                    byte_size=123,
                    width=600,
                    height=900,
                    backend="test",
                )
            )
            session.flush()
            rows = organization_source_rows(
                session, project_id=decisions.project_id, parent_unit_id=legajo.id
            )
        assert len(rows) == 1
        assert rows[0].preview_relative_path == "derivatives/test/page_0001_preview.jpg"
    finally:
        engine.dispose()


def test_catalog_document_thumbnail_cache_reuses_unchanged_file_and_invalidates_change(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    path = root / "derivatives" / "preview.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (120, 180), "white").save(path)
    _catalog_document_cached_thumbnail_data_url.cache_clear()

    first = _catalog_document_thumbnail_data_url(root, "derivatives/preview.png")
    second = _catalog_document_thumbnail_data_url(root, "derivatives/preview.png")
    warm = _catalog_document_cached_thumbnail_data_url.cache_info()

    assert first is not None
    assert second == first
    assert warm.misses == 1
    assert warm.hits == 1

    Image.new("RGB", (140, 200), "black").save(path)
    changed = _catalog_document_thumbnail_data_url(root, "derivatives/preview.png")
    refreshed = _catalog_document_cached_thumbnail_data_url.cache_info()

    assert changed is not None
    assert changed != first
    assert refreshed.misses == 2


def test_organize_linked_files_into_ordered_document_units(tmp_path: Path) -> None:
    root, decisions, engine = _setup(tmp_path)
    first_path = root / "corpus" / "001_programa.pdf"
    second_path = root / "corpus" / "002_programa.pdf"
    _write_pdf(first_path, "PROGRAMA DE ACTIVIDADES")
    _write_pdf(second_path, "Continuación")
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
            caja = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=fondo.id,
                level_key="caja",
                title="Caja",
                created_by="Alex",
            )
            legajo = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=caja.id,
                level_key="legajo",
                title="15 - Actividades culturales",
                created_by="Alex",
            )
            first = register_local_file(
                session,
                project_root=root,
                project_id=decisions.project_id,
                archival_unit_id=legajo.id,
                relative_path="corpus/001_programa.pdf",
                registered_by="Alex",
            )
            second = register_local_file(
                session,
                project_root=root,
                project_id=decisions.project_id,
                archival_unit_id=legajo.id,
                relative_path="corpus/002_programa.pdf",
                registered_by="Alex",
            )

            rows = organization_source_rows(
                session,
                project_id=decisions.project_id,
                parent_unit_id=legajo.id,
            )
            assert [row.original_filename for row in rows] == [
                "001_programa.pdf",
                "002_programa.pdf",
            ]
            assert rows[0].suggested_title == "001 programa"
            assert rows[0].preview_relative_path is None
            assert rows[0].organized_count == 0
            assert "documento" in record_level_options(decisions, legajo.level_key)

            result = create_document_groups(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_unit_id=legajo.id,
                document_level_key="documento",
                groups=[
                    DocumentGroupDraft(
                        title="Programa de actividades culturales",
                        components=(
                            DocumentComponentDraft(first.digital_object_id),
                            DocumentComponentDraft(second.digital_object_id),
                        ),
                    )
                ],
                created_by="Alex",
            )
            created_id = result.created[0].archival_unit_id
            created = session.get(ArchivalUnit, created_id)
            components = session.scalars(
                select(ArchivalDocumentComponent)
                .where(ArchivalDocumentComponent.archival_unit_id == created_id)
                .order_by(ArchivalDocumentComponent.sequence_position)
            ).all()
            links = session.scalars(
                select(DigitalObjectUnitLink).where(
                    DigitalObjectUnitLink.archival_unit_id == created_id
                )
            ).all()

            assert created is not None
            assert created.parent_id == legajo.id
            assert created.level_key == "documento"
            assert [row.digital_object_id for row in components] == [
                first.digital_object_id,
                second.digital_object_id,
            ]
            assert [row.sequence_position for row in components] == [1, 2]
            assert {row.relation_type for row in links} == {"is_part_of"}

            rows_after = organization_source_rows(
                session,
                project_id=decisions.project_id,
                parent_unit_id=legajo.id,
            )
            assert [row.organized_count for row in rows_after] == [1, 1]
    finally:
        engine.dispose()


def test_one_multipage_file_can_be_split_into_multiple_catalog_documents(tmp_path: Path) -> None:
    root, decisions, engine = _setup(tmp_path)
    pdf_path = root / "corpus" / "boletin.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for index in range(1, 5):
        page = document.new_page(width=500, height=400)
        page.insert_text((50, 80), f"Documento página {index}")
    document.save(pdf_path)
    document.close()
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=None, level_key="archivo", title="Archivo", created_by="Alex")
            fondo = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=archivo.id, level_key="fondo", title="Fondo", created_by="Alex")
            caja = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=fondo.id, level_key="caja", title="Caja", created_by="Alex")
            legajo = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=caja.id, level_key="legajo", title="Legajo", created_by="Alex")
            registered = register_local_file(
                session,
                project_root=root,
                project_id=decisions.project_id,
                archival_unit_id=legajo.id,
                relative_path="corpus/boletin.pdf",
                registered_by="Alex",
            )
            result = create_document_groups(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_unit_id=legajo.id,
                document_level_key="documento",
                groups=(
                    DocumentGroupDraft(
                        title="Documento A",
                        components=(DocumentComponentDraft(registered.digital_object_id, 1, 2),),
                    ),
                    DocumentGroupDraft(
                        title="Documento B",
                        components=(DocumentComponentDraft(registered.digital_object_id, 3, 4),),
                    ),
                ),
                created_by="Alex",
            )
            assert len(result.created) == 2
            components = session.scalars(
                select(ArchivalDocumentComponent)
                .where(
                    ArchivalDocumentComponent.archival_unit_id.in_(
                        [row.archival_unit_id for row in result.created]
                    )
                )
                .order_by(ArchivalDocumentComponent.page_start)
            ).all()
            assert [(row.page_start, row.page_end) for row in components] == [(1, 2), (3, 4)]
            links = session.scalars(
                select(DigitalObjectUnitLink).where(
                    DigitalObjectUnitLink.archival_unit_id.in_(
                        [row.archival_unit_id for row in result.created]
                    )
                )
            ).all()
            assert {row.relation_type for row in links} == {"contains"}
    finally:
        engine.dispose()


def test_document_component_creation_is_recorded_for_exchange(tmp_path: Path) -> None:
    root, decisions, engine = _setup(tmp_path)
    _write_pdf(root / "corpus" / "doc.pdf", "Documento")
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=None, level_key="archivo", title="Archivo", created_by="Alex")
            fondo = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=archivo.id, level_key="fondo", title="Fondo", created_by="Alex")
            caja = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=fondo.id, level_key="caja", title="Caja", created_by="Alex")
            legajo = create_archival_unit(session, decisions=decisions, project_id=decisions.project_id, parent_id=caja.id, level_key="legajo", title="Legajo", created_by="Alex")
            registered = register_local_file(session, project_root=root, project_id=decisions.project_id, archival_unit_id=legajo.id, relative_path="corpus/doc.pdf", registered_by="Alex")
            ensure_exchange_workspace(session, workspace_name="tests", changed_by="Alex")
            create_document_groups(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_unit_id=legajo.id,
                document_level_key="documento",
                groups=(DocumentGroupDraft(title="Documento", components=(DocumentComponentDraft(registered.digital_object_id),)),),
                created_by="Alex",
            )
            event = session.scalar(
                select(ExchangeChangeEvent)
                .where(ExchangeChangeEvent.entity_type == "archival_document_component")
                .order_by(ExchangeChangeEvent.sequence_number.desc())
            )
            assert event is not None
            assert event.operation == "create"
            assert event.changed_fields_json["sequence_position"] == [None, 1]
    finally:
        engine.dispose()
