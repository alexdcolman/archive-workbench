from __future__ import annotations

import csv
import json
from pathlib import Path

from archive_workbench.corpus_export import (
    ExportProfileValues,
    build_export_rows,
    export_run_rows,
    preview_export,
    run_export,
    save_export_profile,
)
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import EditableObject, EditablePage
from tests.test_search import _seed_search_project


def _profile(session, *, aggregation: str = "document", **kwargs):
    return save_export_profile(
        session,
        project_id="search_project",
        values=ExportProfileValues(
            name=f"Perfil {aggregation}",
            aggregation_level=aggregation,
            **kwargs,
        ),
        changed_by="tests",
    )


def test_export_profile_groups_document_and_uses_corrected_text(tmp_path: Path) -> None:
    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(session)
            rows = build_export_rows(session, project_id="search_project", profile=profile)
    finally:
        engine.dispose()
    assert len(rows) == 1
    assert rows[0].object_ids == [object_id]
    assert rows[0].texto == "La actividad teatral fue investigada"
    assert rows[0].titulo == "Documento teatral"
    assert rows[0].tags == ["teatro", "vigilancia"]


def test_export_filters_review_status_and_supports_original_text(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            original = _profile(
                session,
                aggregation="object",
                text_policy="original_only",
                include_review_statuses=("approved",),
            )
            rows = build_export_rows(session, project_id="search_project", profile=original)
            assert rows[0].texto == "actividad subversiva"
            original.include_review_statuses_json = ["needs_review"]
            session.flush()
            assert build_export_rows(session, project_id="search_project", profile=original) == []
    finally:
        engine.dispose()


def test_page_export_inserts_marker_and_separators(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            existing = session.query(EditableObject).one()
            page = session.get(EditablePage, existing.editable_page_id)
            second = EditableObject(
                id="second-object",
                editable_page_id=existing.editable_page_id,
                digital_object_id=existing.digital_object_id,
                page_number=1,
                source_extracted_object_id=None,
                source_origin_id=None,
                current_text="Segundo párrafo",
                current_object_type="paragraph",
                current_order_index=1,
                current_geometry_json=[],
                current_attributes_json={},
                lifecycle_status="active",
                review_status="approved",
                revision_number=1,
                created_by="tests",
                updated_by="tests",
            )
            session.add(second)
            session.flush()
            profile = _profile(
                session,
                aggregation="page",
                include_page_markers=True,
                object_separator=" | ",
            )
            rows = build_export_rows(session, project_id="search_project", profile=profile)
    finally:
        engine.dispose()
    assert rows[0].texto == "[Página 1]\nLa actividad teatral fue investigada | Segundo párrafo"
    assert rows[0].object_count == 2


def test_run_export_writes_jsonl_and_registers_hashes(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(session)
            result = run_export(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                output_relative_path="exports/corpus",
                created_by="tests",
            )
            history = export_run_rows(session, project_id="search_project")
    finally:
        engine.dispose()
    assert result.output_path == root / "exports" / "corpus.jsonl"
    payload = json.loads(result.output_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["codigo"].startswith("document:")
    assert payload["texto"] == "La actividad teatral fue investigada"
    assert payload["export_schema_version"] == "1.1"
    assert payload["record_type"] == "archive_workbench.corpus_export_record"
    assert payload["project_id"] == "search_project"
    assert payload["export_run_id"] == result.run_id
    assert payload["exported_at"]
    assert payload["corpus_state_sha256"] == result.corpus_state_sha256
    assert payload["export_profile_name"] == profile.name
    assert payload["export_configuration"]["aggregation_level"] == "document"
    assert payload["text_policy"] == "corrected_fallback_original"
    assert payload["original_filenames"]
    assert payload["original_sha256s"]
    assert payload["media_types"]
    assert payload["source_documents"][0]["digital_object_id"] == payload["digital_object_id"]
    assert payload["source_documents"][0]["original_filename"] in payload["original_filenames"]
    assert payload["source_documents"][0]["sha256"] in payload["original_sha256s"]
    assert payload["archival_unit_title"]
    assert payload["archival_unit_level"]
    assert payload["page_numbers"] == [1]
    assert payload["object_provenance"][0]["object_id"] == payload["object_ids"][0]
    assert payload["object_provenance"][0]["digital_object_id"] == payload["digital_object_id"]
    assert payload["object_provenance"][0]["source_key"] == payload["source_key"]
    assert payload["object_provenance"][0]["text_source"] == "corrected"
    assert history[0].output_sha256 == result.output_sha256
    assert len(result.corpus_state_sha256) == 64


def test_run_export_writes_csv_lists_as_json(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(session, aggregation="object", output_format="csv")
            result = run_export(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                output_relative_path="exports/corpus.csv",
                created_by="tests",
            )
    finally:
        engine.dispose()
    with result.output_path.open(encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert json.loads(row["tags"]) == ["teatro", "vigilancia"]
    assert json.loads(row["source_documents"])[0]["original_filename"]


def test_preview_does_not_write_or_register_run(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(session)
            preview = preview_export(session, project_id="search_project", profile=profile, limit=1)
            history = export_run_rows(session, project_id="search_project")
    finally:
        engine.dispose()
    assert preview.total_records == 1
    assert len(preview.records) == 1
    assert history == []


def test_export_filters_by_entity_period_and_includes_temporal_metadata(tmp_path: Path) -> None:
    from datetime import date
    from archive_workbench.authorities import create_authority, create_mention

    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            entity = create_authority(
                session,
                project_id="search_project",
                entity_type="event",
                preferred_name="Actividad teatral",
                temporal_expression="años setenta",
                created_by="tests",
            )
            create_mention(
                session,
                object_id=object_id,
                mention_text="teatral",
                authority_id=entity.id,
                created_by="tests",
            )
            profile = _profile(
                session,
                aggregation="object",
                temporal_start=date(1975, 1, 1),
                temporal_end=date(1975, 12, 31),
            )
            rows = build_export_rows(session, project_id="search_project", profile=profile)
            profile.temporal_start = date(1985, 1, 1)
            profile.temporal_end = date(1985, 12, 31)
            session.flush()
            outside = build_export_rows(session, project_id="search_project", profile=profile)
        assert rows[0].object_ids == [object_id]
        assert rows[0].entity_temporal_ranges == ["Actividad teatral: años setenta"]
        assert outside == []
    finally:
        engine.dispose()


def test_export_profile_archive_restore_and_delete_preserve_run_history(tmp_path: Path) -> None:
    from archive_workbench.corpus_export import (
        delete_export_profile,
        export_profile_rows,
        set_export_profile_archived,
    )

    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(session)
            result = run_export(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                output_relative_path="exports/lifecycle.jsonl",
                created_by="tests",
            )
            profile_id = profile.id
            set_export_profile_archived(
                session,
                project_id="search_project",
                profile_id=profile_id,
                archived=True,
                changed_by="tests",
            )
            assert export_profile_rows(session, project_id="search_project") == []
            archived = export_profile_rows(
                session,
                project_id="search_project",
                include_archived=True,
            )
            assert archived[0].lifecycle_status == "archived"
            try:
                run_export(
                    session,
                    project_root=root,
                    project_id="search_project",
                    profile=archived[0],
                    output_relative_path="exports/blocked.jsonl",
                    created_by="tests",
                )
            except ValueError as exc:
                assert "archivado" in str(exc)
            else:
                raise AssertionError("Un perfil archivado no debe ejecutar exportaciones")

            set_export_profile_archived(
                session,
                project_id="search_project",
                profile_id=profile_id,
                archived=False,
                changed_by="tests",
            )
            assert export_profile_rows(session, project_id="search_project")[0].id == profile_id
            set_export_profile_archived(
                session,
                project_id="search_project",
                profile_id=profile_id,
                archived=True,
                changed_by="tests",
            )
            deleted_name = delete_export_profile(
                session,
                project_id="search_project",
                profile_id=profile_id,
            )
            assert deleted_name == "Perfil document"
            history = export_run_rows(session, project_id="search_project")
            assert history[0].run_id == result.run_id
            assert history[0].profile_id is None
            assert history[0].profile_name == "Perfil document"
        assert (root / "exports/lifecycle.jsonl").is_file()
    finally:
        engine.dispose()


def test_export_execution_requires_current_quality_authorization(tmp_path: Path) -> None:
    import pytest

    root = tmp_path / "authorized_export_project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(session)
            assert preview_export(
                session,
                project_id="search_project",
                profile=profile,
                limit=1,
            ).total_records == 1

            profile.text_policy = "original_only"
            session.flush()
            with pytest.raises(ValueError, match="autorización vigente"):
                preview_export(
                    session,
                    project_id="search_project",
                    profile=profile,
                    limit=1,
                )
            with pytest.raises(ValueError, match="autorización vigente"):
                run_export(
                    session,
                    project_root=root,
                    project_id="search_project",
                    profile=profile,
                    output_relative_path="exports/no_autorizada.jsonl",
                    created_by="tests",
                )

            save_export_profile(
                session,
                project_id="search_project",
                profile_id=profile.id,
                values=ExportProfileValues(
                    name=profile.name,
                    text_policy="original_only",
                ),
                changed_by="tests",
            )
            preview = preview_export(
                session,
                project_id="search_project",
                profile=profile,
                limit=1,
            )
            assert preview.records[0].texto == "actividad subversiva"
    finally:
        engine.dispose()


def _seed_visual_export_material(root: Path) -> tuple[str, str]:
    import hashlib

    from PIL import Image

    from archive_workbench.db.models import (
        DerivativeAsset,
        ExtractionPage,
        ExtractionRegion,
        ExtractionRun,
        PreprocessingRun,
    )
    from archive_workbench.identity import new_id

    primary_id, page_id = _seed_search_project(root)
    image_relative = Path("derived/preprocessing/visual_test/page_0001_ocr.png")
    image_path = root / image_relative
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (400, 300), "white")
    image.save(image_path, format="PNG")
    image_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()

    crop_relative = Path("derived/extractions/visual_test/regions/page_0001/r1.png")
    crop_path = root / crop_relative
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    image.crop((40, 60, 200, 150)).save(crop_path, format="PNG")

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            page = session.get(EditablePage, page_id)
            assert page is not None
            run = session.get(ExtractionRun, page.source_extraction_run_id)
            extraction_page = session.get(ExtractionPage, page.source_extraction_page_id)
            assert run is not None and extraction_page is not None

            prep = PreprocessingRun(
                id=new_id(),
                digital_object_id=page.digital_object_id,
                source_sha256="a" * 64,
                profile_key="visual-test",
                options_json={},
                options_hash="c" * 64,
                backend="tests",
                status="completed",
                is_current=True,
                output_root="derived/preprocessing/visual_test",
                warnings_json=[],
            )
            session.add(prep)
            session.flush()
            asset = DerivativeAsset(
                id=new_id(),
                preprocessing_run_id=prep.id,
                digital_object_id=page.digital_object_id,
                page_number=1,
                kind="ocr",
                relative_path=image_relative.as_posix(),
                mime_type="image/png",
                sha256=image_sha,
                byte_size=image_path.stat().st_size,
                width=400,
                height=300,
                dpi=150,
                rotation_applied=0,
                analysis_json={},
                transformations_json={},
                backend="tests",
            )
            session.add(asset)
            session.flush()
            extraction_page.source_asset_id = asset.id
            run.preprocessing_run_id = prep.id

            session.add(
                ExtractionRegion(
                    id=new_id(),
                    extraction_run_id=run.id,
                    page_number=1,
                    region_key="r1",
                    label="Recuadro lateral",
                    mode="ocr",
                    object_type="paragraph",
                    reading_order=0,
                    bbox_json={"x": 0.1, "y": 0.2, "width": 0.4, "height": 0.3},
                    profile_json={"semantic_role": "sidebar"},
                    crop_path=crop_relative.as_posix(),
                    object_count=1,
                    character_count=10,
                    status="completed",
                )
            )
            figure_id = new_id()
            session.add(
                EditableObject(
                    id=figure_id,
                    editable_page_id=page.id,
                    digital_object_id=page.digital_object_id,
                    page_number=1,
                    source_extracted_object_id=None,
                    source_origin_id=None,
                    current_text="",
                    current_object_type="figure",
                    current_order_index=1,
                    current_geometry_json=[
                        {
                            "page": 1,
                            "polygon": [[0.55, 0.2], [0.9, 0.2], [0.9, 0.7], [0.55, 0.7]],
                            "coordinate_space": "normalized",
                        }
                    ],
                    current_attributes_json={},
                    lifecycle_status="active",
                    review_status="approved",
                    revision_number=1,
                    created_by="tests",
                    updated_by="tests",
                )
            )
            session.add(
                EditableObject(
                    id=new_id(),
                    editable_page_id=page.id,
                    digital_object_id=page.digital_object_id,
                    page_number=1,
                    source_extracted_object_id=None,
                    source_origin_id=None,
                    current_text="Texto adicional que sirve solamente como contexto.",
                    current_object_type="paragraph",
                    current_order_index=2,
                    current_geometry_json=[],
                    current_attributes_json={},
                    lifecycle_status="active",
                    review_status="needs_review",
                    revision_number=1,
                    created_by="tests",
                    updated_by="tests",
                )
            )
            session.flush()
            return primary_id, figure_id
    finally:
        engine.dispose()


def test_visual_zip_exports_pages_regions_figures_and_structured_context(tmp_path: Path) -> None:
    import zipfile

    root = tmp_path / "project"
    primary_id, figure_id = _seed_visual_export_material(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(
                session,
                aggregation="object",
                include_review_statuses=("approved",),
            )
            result = run_export(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                output_relative_path="exports/texto_imagenes",
                output_format="visual_zip",
                created_by="tests",
            )
    finally:
        engine.dispose()

    assert result.output_path.suffix == ".zip"
    assert result.page_image_count == 1
    assert result.region_image_count == 1
    assert result.figure_image_count == 1
    assert result.context_object_count == 2

    with zipfile.ZipFile(result.output_path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "text/records.jsonl" in names
        assert "context/objects.jsonl" in names
        assert any(name.startswith("images/pages/") for name in names)
        assert any(name.startswith("images/regions/") for name in names)
        assert any(name.startswith("images/figures/") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        context_rows = [
            json.loads(line)
            for line in archive.read("context/objects.jsonl").decode("utf-8").splitlines()
        ]

    assert manifest["package_type"] == "archive_workbench_text_and_images"
    assert manifest["asset_counts"] == {"figures": 1, "pages": 1, "regions": 1}
    assert manifest["text"]["record_count"] == 1
    assert manifest["context"]["object_count"] == 2
    assert {item["kind"] for item in manifest["assets"]} == {"page", "region", "figure"}
    figure = next(item for item in manifest["assets"] if item["kind"] == "figure")
    assert figure["editable_object_id"] == figure_id
    assert figure["primary_record_ids"] == [f"object:{primary_id}"]
    extra = next(item for item in context_rows if "Texto adicional" in item["text"])
    assert extra["included_in_primary_export"] is False
    assert extra["primary_record_ids"] == []


def test_visual_zip_rejects_modified_registered_page_asset(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_visual_export_material(root)
    image_path = root / "derived/preprocessing/visual_test/page_0001_ocr.png"
    image_path.write_bytes(image_path.read_bytes() + b"tampered")
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(
                session,
                aggregation="object",
                include_review_statuses=("approved",),
            )
            import pytest

            with pytest.raises(ValueError, match="modificado"):
                run_export(
                    session,
                    project_root=root,
                    project_id="search_project",
                    profile=profile,
                    output_relative_path="exports/texto_imagenes.zip",
                    output_format="visual_zip",
                    created_by="tests",
                )
    finally:
        engine.dispose()
