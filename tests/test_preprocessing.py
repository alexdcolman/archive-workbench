from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import DerivativeAsset, PreprocessingRun
from archive_workbench.decisions import load_decisions
from archive_workbench.contracts.preprocessing import DerivativeProfile
from archive_workbench.preprocessing import (
    _render_raster_pyvips,
    prepare_derivatives,
    preprocessing_status_rows,
)


def _write_pdf(path: Path, pages: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for number in range(1, pages + 1):
        page = document.new_page(width=800, height=500)
        page.insert_text((60, 80), f"Página de prueba {number}")
    document.save(path)
    document.close()


def _write_tiff(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1200, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.text((50, 50), "Texto horizontal legible", fill="black")
    image.save(path, format="TIFF", dpi=(300, 300), compression="tiff_deflate")

def _write_raster(path: Path, *, image_format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (320, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 20), "Texto de prueba", fill="black")
    image.save(path, format=image_format)


def _corpus(documents: list[dict]) -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Prueba de derivados",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": documents,
        }
    )


def _document(test_id: str, local_path: str, fmt: str, title: str) -> dict:
    return {
        "test_id": test_id,
        "local_path": local_path,
        "short_description": title,
        "archival_location": {
            "fondo": "SiCH",
            "caja": "Caja 1",
            "documento": title,
        },
        "input_characteristics": {
            "format": fmt,
            "scanned": True,
            "digital_text_layer": False,
            "multipage_tiff": False,
            "poor_contrast": False,
            "skewed_pages": False,
            "landscape_pages": True,
            "mixed_orientations": False,
            "text_orientation": "upright",
            "typewritten": True,
            "handwritten_notes": False,
            "stamps": False,
            "tables_or_forms": False,
            "multiple_internal_documents": False,
        },
        "expected_extraction": {"minimum_page_coverage_percent": 95},
    }


def test_pdf_derivatives_are_created_and_reused(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_pdf(root / "corpus/caja/a.pdf", pages=2)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    corpus = _corpus([_document("pdf_a", "corpus/caja/a.pdf", "pdf", "PDF A")])

    upgrade_database(root)
    assert current_revision(root) == "0047_authority_relation_profiles"
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        with session_scope(engine) as session:
            first = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
            )
        with session_scope(engine) as session:
            second = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
            )
        with session_scope(engine) as session:
            runs = session.scalars(select(PreprocessingRun)).all()
            assets = session.scalars(select(DerivativeAsset)).all()
    finally:
        engine.dispose()

    assert first.runs_created == 1
    assert first.assets_created == 4
    assert first.failed == 0
    assert second.runs_reused == 1
    assert len(runs) == 1
    assert len(assets) == 4
    assert sum(asset.kind == "ocr" for asset in assets) == 2
    assert sum(asset.kind == "preview" for asset in assets) == 2
    assert all((root / asset.relative_path).is_file() for asset in assets)
    assert (root / runs[0].manifest_path).is_file()


def test_tiff_derivatives_keep_native_orientation_and_resolution(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_tiff(root / "corpus/legajo/a.tiff")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    decisions.tiff.use_pyvips_when_available = False
    corpus = _corpus([_document("tiff_a", "corpus/legajo/a.tiff", "tiff", "TIFF A")])

    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        with session_scope(engine) as session:
            summary = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
            )
        with session_scope(engine) as session:
            assets = session.scalars(select(DerivativeAsset)).all()
            status = preprocessing_status_rows(session)
    finally:
        engine.dispose()

    assert summary.runs_created == 1
    assert summary.failed == 0
    assert len(assets) == 2
    ocr = next(asset for asset in assets if asset.kind == "ocr")
    preview = next(asset for asset in assets if asset.kind == "preview")
    assert (ocr.width, ocr.height) == (1200, 600)
    assert ocr.rotation_applied == 0
    assert preview.width > preview.height
    assert status[0].run_status == "completed"
    assert status[0].assets == 2



@pytest.mark.parametrize(
    ("suffix", "image_format"),
    [("png", "PNG"), ("jpg", "JPEG"), ("jpeg", "JPEG"), ("webp", "WEBP")],
)
def test_declared_raster_formats_create_document_derivatives(
    tmp_path: Path, suffix: str, image_format: str
) -> None:
    root = tmp_path / "project"
    relative = f"corpus/imagenes/control.{suffix}"
    _write_raster(root / relative, image_format=image_format)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    decisions.tiff.use_pyvips_when_available = False
    corpus = _corpus([_document(f"image_{suffix}", relative, "image", f"Imagen {suffix}")])

    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        with session_scope(engine) as session:
            summary = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
            )
        with session_scope(engine) as session:
            assets = session.scalars(select(DerivativeAsset)).all()
    finally:
        engine.dispose()

    assert summary.runs_created == 1
    assert summary.failed == 0
    assert len(assets) == 2
    assert {asset.kind for asset in assets} == {"ocr", "preview"}
    assert all((root / asset.relative_path).is_file() for asset in assets)


def test_bmp_is_rejected_by_document_preprocessing_even_for_legacy_image_record(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    relative = "corpus/imagenes/control.bmp"
    _write_raster(root / relative, image_format="BMP")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    corpus = _corpus([_document("image_bmp", relative, "image", "Imagen BMP")])

    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
            run = session.scalar(select(PreprocessingRun))
            assert run is None
            from archive_workbench.db.models import DigitalObject

            digital = session.scalar(select(DigitalObject))
            assert digital is not None
            digital.media_type = "image"
        with session_scope(engine) as session:
            summary = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
            )
    finally:
        engine.dispose()

    assert summary.failed == 1
    assert summary.runs_created == 0
    assert "Formato no admitido" in summary.warnings[0]
    assert "PDF, TIFF, PNG, JPEG o WebP" in summary.warnings[0]


def test_pyvips_sequential_tiff_reopens_page_for_preview(tmp_path: Path) -> None:
    class FakeImage:
        def __init__(self, *, width: int = 1200, height: int = 600) -> None:
            self.width = width
            self.height = height
            self.bands = 3
            self.xres = 300 / 25.4
            self.yres = 300 / 25.4
            self.consumed = False

        def flatten(self, **_kwargs):
            return self

        def colourspace(self, _space: str):
            return self

        def resize(self, scale: float):
            if self.consumed:
                raise RuntimeError("out of order read: sequential image reused")
            return FakeImage(
                width=max(1, round(self.width * scale)),
                height=max(1, round(self.height * scale)),
            )

        def write_to_file(self, path: str, **_kwargs) -> None:
            if self.consumed:
                raise RuntimeError("out of order read: sequential image reused")
            self.consumed = True
            Path(path).write_bytes(b"fake-vips-output")

    class FakeVipsImageFactory:
        calls: list[dict[str, object]] = []

        @classmethod
        def new_from_file(cls, _path: str, **kwargs):
            cls.calls.append(dict(kwargs))
            return FakeImage()

    class FakePyvips:
        Image = FakeVipsImageFactory

    root = tmp_path / "project"
    source = root / "corpus/legajo/a.tiff"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"source-placeholder")
    output = root / "derivatives/test"
    profile = DerivativeProfile(
        preview_dpi=150,
        ocr_dpi=300,
        preview_format="webp",
        ocr_format="png",
    )

    assets, warnings, backend, _version = _render_raster_pyvips(
        source,
        page_count=1,
        project_root=root,
        output_dir=output,
        run_id="run_test",
        digital_object_id="digital_test",
        profile=profile,
        pyvips=FakePyvips,
    )

    assert backend == "pyvips"
    assert warnings == []
    assert len(assets) == 2
    assert {asset.kind for asset in assets} == {"ocr", "preview"}
    assert len(FakeVipsImageFactory.calls) == 2
    assert all(call["access"] == "sequential" for call in FakeVipsImageFactory.calls)
    assert all(call["page"] == 0 for call in FakeVipsImageFactory.calls)
    assert all(call["n"] == 1 for call in FakeVipsImageFactory.calls)
    assert all((root / asset.relative_path).is_file() for asset in assets)


def test_modified_source_is_not_preprocessed_under_old_identity(tmp_path: Path) -> None:
    root = tmp_path / "project"
    source = root / "corpus/caja/a.pdf"
    _write_pdf(source, pages=1)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    corpus = _corpus([_document("pdf_a", "corpus/caja/a.pdf", "pdf", "PDF A")])

    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        _write_pdf(source, pages=2)
        with session_scope(engine) as session:
            summary = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
            )
        with session_scope(engine) as session:
            runs = session.scalars(select(PreprocessingRun)).all()
    finally:
        engine.dispose()

    assert summary.failed == 1
    assert summary.runs_created == 0
    assert runs == []
    assert "cambió desde su registro" in summary.warnings[0]


def test_conservative_ocr_treatment_is_versioned_and_reusable(tmp_path: Path) -> None:
    from archive_workbench.preprocessing import profile_for_ocr_treatment

    root = tmp_path / "project"
    source = root / "corpus/legajo/low_contrast.tiff"
    source.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("L", (600, 300), 190)
    draw = ImageDraw.Draw(image)
    draw.text((40, 60), "Texto de contraste moderado", fill=135)
    image.save(source, format="TIFF", dpi=(300, 300), compression="tiff_deflate")

    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    decisions.tiff.use_pyvips_when_available = False
    corpus = _corpus(
        [_document("low_contrast", "corpus/legajo/low_contrast.tiff", "tiff", "Bajo contraste")]
    )

    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        with session_scope(engine) as session:
            original = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile_for_ocr_treatment(decisions, "original"),
            )
        with session_scope(engine) as session:
            treated = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile_for_ocr_treatment(decisions, "grayscale_autocontrast"),
            )
        with session_scope(engine) as session:
            runs = list(session.scalars(select(PreprocessingRun).order_by(PreprocessingRun.created_at)))
            assets = list(session.scalars(select(DerivativeAsset)))
            current = next(run for run in runs if run.is_current)
            original_run = next(run for run in runs if run.profile_key == "default")
            treated_run = next(
                run for run in runs if run.profile_key == "ocr_grayscale_autocontrast"
            )
            original_assets = {
                asset.kind: asset for asset in assets if asset.preprocessing_run_id == original_run.id
            }
            treated_assets = {
                asset.kind: asset for asset in assets if asset.preprocessing_run_id == treated_run.id
            }

        assert original.runs_created == 1
        assert treated.runs_created == 1
        assert len(runs) == 2
        assert current.id == treated_run.id
        assert treated_run.options_json["ocr_treatment"] == "grayscale_autocontrast"
        assert original_assets["preview"].sha256 == treated_assets["preview"].sha256
        assert original_assets["ocr"].sha256 != treated_assets["ocr"].sha256

        with session_scope(engine) as session:
            reused = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile_for_ocr_treatment(decisions, "original"),
            )
        with session_scope(engine) as session:
            current_after_reuse = session.scalar(
                select(PreprocessingRun).where(PreprocessingRun.is_current.is_(True))
            )
    finally:
        engine.dispose()

    assert reused.runs_reused == 1
    assert current_after_reuse is not None
    assert current_after_reuse.profile_key == "default"


def test_apply_ocr_treatment_keeps_dimensions_and_uses_conservative_modes() -> None:
    from archive_workbench.preprocessing import apply_ocr_treatment

    source = Image.new("RGB", (120, 80), (180, 180, 180))
    draw = ImageDraw.Draw(source)
    draw.rectangle((20, 20, 100, 60), fill=(110, 110, 110))

    original = apply_ocr_treatment(source, "original")
    autocontrast = apply_ocr_treatment(source, "grayscale_autocontrast")
    otsu = apply_ocr_treatment(source, "otsu")
    denoised = apply_ocr_treatment(source, "denoise_autocontrast")

    assert original.size == autocontrast.size == otsu.size == denoised.size == source.size
    assert original.mode == "RGB"
    assert autocontrast.mode == "L"
    assert otsu.mode == "1"
    assert denoised.mode == "L"
    assert otsu.getextrema() == (0, 255)


def test_pre_036_original_profile_is_reused_without_duplicate_run(tmp_path: Path) -> None:
    from archive_workbench.identity import sha256_json
    from archive_workbench.preprocessing import profile_for_ocr_treatment

    root = tmp_path / "project"
    _write_pdf(root / "corpus/caja/legacy.pdf", pages=1)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    corpus = _corpus([_document("legacy", "corpus/caja/legacy.pdf", "pdf", "Legacy")])

    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        with session_scope(engine) as session:
            prepare_derivatives(session, project_root=root, decisions=decisions)
        with session_scope(engine) as session:
            run = session.scalar(select(PreprocessingRun))
            assert run is not None
            legacy_options = dict(run.options_json)
            for key in (
                "ocr_treatment",
                "geometry_mode",
                "orientation_min_confidence",
                "deskew_max_degrees",
                "deskew_min_confidence",
                "line_min_length_ratio",
                "line_max_thickness_px",
                "dewarp_strips",
                "dewarp_max_displacement_ratio",
                "dewarp_min_displacement_px",
                "dewarp_min_confidence",
            ):
                legacy_options.pop(key, None)
            run.options_json = legacy_options
            run.options_hash = sha256_json(legacy_options)
        with session_scope(engine) as session:
            summary = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile_for_ocr_treatment(decisions, "original"),
            )
        with session_scope(engine) as session:
            runs = list(session.scalars(select(PreprocessingRun)))
    finally:
        engine.dispose()

    assert summary.runs_created == 0
    assert summary.runs_reused == 1
    assert len(runs) == 1


def _synthetic_text_page(*, frame: bool = False) -> Image.Image:
    image = Image.new("RGB", (900, 1200), "white")
    draw = ImageDraw.Draw(image)
    for row in range(12):
        y = 80 + row * 65
        x = 70
        for word, width in enumerate((120, 85, 160, 95, 130)):
            draw.rectangle((x, y, x + width, y + 18), fill="black")
            # Huecos internos simulan letras sin depender de fuentes del sistema.
            for offset in range(12, width, 22):
                draw.rectangle((x + offset, y + 4, x + offset + 6, y + 18), fill="white")
            x += width + 24 + (word % 2) * 8
    if frame:
        draw.rectangle((20, 20, 880, 1180), outline="black", width=3)
    return image


def test_conservative_geometry_detects_orientation_deskew_and_safe_lines() -> None:
    from archive_workbench.preprocessing_geometry import (
        apply_conservative_geometry,
        detect_orientation,
    )

    base = _synthetic_text_page(frame=True)
    for expected in (0, 90, 180, 270):
        candidate = base.rotate(-expected, expand=True, fillcolor="white")
        detected, confidence, _scores = detect_orientation(candidate)
        assert detected == expected
        assert confidence >= 0.12

    source = base.rotate(-90, expand=True, fillcolor="white")
    result = apply_conservative_geometry(
        source,
        orientation_min_confidence=0.12,
        deskew_max_degrees=5.0,
        deskew_min_confidence=0.08,
        line_min_length_ratio=0.65,
        line_max_thickness_px=8,
    )

    assert result.orientation_detected == 90
    assert result.orientation_applied == 90
    assert result.orientation_confidence >= 0.12
    assert result.image.height > result.image.width
    assert result.lines_detected >= 4
    assert result.lines_removed >= 4
    assert result.removed_pixels > 0
    assert result.mask.getextrema() == (0, 255)
    assert result.transformations["orientation"]["applied"] is True
    assert result.transformations["orientation"]["reason"] == "confidence_above_threshold"
    assert result.transformations["line_removal"]["applied"] is True

    skewed = _synthetic_text_page().rotate(3.0, expand=True, fillcolor="white")
    deskewed = apply_conservative_geometry(
        skewed,
        orientation_min_confidence=0.12,
        deskew_max_degrees=5.0,
        deskew_min_confidence=0.08,
        line_min_length_ratio=0.65,
        line_max_thickness_px=8,
    )
    assert deskewed.deskew_angle == -3.0
    assert deskewed.deskew_confidence >= 0.08
    assert deskewed.transformations["deskew"]["applied"] is True


def test_line_crossing_text_is_not_removed_and_blank_page_stays_unchanged() -> None:
    from archive_workbench.preprocessing_geometry import (
        apply_conservative_geometry,
        remove_long_lines,
    )

    image = _synthetic_text_page()
    draw = ImageDraw.Draw(image)
    draw.line((20, 90, 880, 90), fill="black", width=2)
    _cleaned, mask, detected, removed, removed_pixels = remove_long_lines(
        image,
        min_length_ratio=0.65,
        max_thickness_px=8,
    )
    assert detected >= 1
    assert removed == 0
    assert removed_pixels == 0
    assert mask.getextrema() == (255, 255)

    blank = Image.new("RGB", (600, 800), "white")
    result = apply_conservative_geometry(
        blank,
        orientation_min_confidence=0.12,
        deskew_max_degrees=5.0,
        deskew_min_confidence=0.08,
        line_min_length_ratio=0.65,
        line_max_thickness_px=8,
    )
    assert result.orientation_applied == 0
    assert result.transformations["orientation"]["reason"] == "no_rotation_candidate"
    assert result.deskew_angle == 0.0
    assert result.transformations["deskew"]["reason"] == "confidence_below_threshold"
    assert result.warnings
    assert result.lines_removed == 0
    assert result.image.size == blank.size


def test_geometry_profile_is_versioned_traced_and_reusable(tmp_path: Path) -> None:
    from archive_workbench.preprocessing import profile_for_preprocessing

    root = tmp_path / "project"
    source = root / "corpus/legajo/rotated.tiff"
    source.parent.mkdir(parents=True, exist_ok=True)
    _synthetic_text_page(frame=True).rotate(-90, expand=True, fillcolor="white").save(
        source,
        format="TIFF",
        dpi=(300, 300),
        compression="tiff_deflate",
    )
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    decisions.tiff.use_pyvips_when_available = False
    corpus = _corpus(
        [_document("rotated", "corpus/legajo/rotated.tiff", "tiff", "Rotada")]
    )

    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        profile = profile_for_preprocessing(decisions, "original", "conservative")
        with session_scope(engine) as session:
            first = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile,
            )
        with session_scope(engine) as session:
            second = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile,
            )
        with session_scope(engine) as session:
            run = session.scalar(select(PreprocessingRun))
            assets = list(session.scalars(select(DerivativeAsset)))
    finally:
        engine.dispose()

    assert first.runs_created == 1
    assert first.assets_created == 3
    assert second.runs_reused == 1
    assert run is not None
    assert run.profile_key == "geometry_conservative"
    assert run.options_json["geometry_mode"] == "conservative"
    by_kind = {asset.kind: asset for asset in assets}
    assert set(by_kind) == {"ocr", "preview", "diagnostic_mask"}
    assert by_kind["preview"].analysis_json == {}
    assert by_kind["ocr"].rotation_applied == 90
    assert by_kind["ocr"].analysis_json["orientation_detected"] == 90
    assert by_kind["ocr"].transformations_json["orientation"]["applied"] is True
    assert by_kind["diagnostic_mask"].analysis_json == by_kind["ocr"].analysis_json
    assert all((root / asset.relative_path).is_file() for asset in assets)
