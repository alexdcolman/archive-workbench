from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from archive_workbench.analysis_audit import automatic_analysis_authorization_rows
from archive_workbench.analysis_quality import (
    ANALYSIS_QUALITY_POLICY_VERSION,
    AUTOMATIC_ANALYSIS_SPECS,
    DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES,
    analysis_quality_scope,
    normalize_page_review_statuses,
    quality_scope_caption,
    quality_scope_snapshot,
    validate_automatic_analysis_authorization,
    validate_automatic_quality_scope,
)
from archive_workbench.cli import app
from archive_workbench.corpus_export import (
    ExportProfileValues,
    profile_snapshot as export_profile_snapshot,
    save_export_profile,
)
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.semantic_search import (
    SemanticProfileValues,
    profile_snapshot as semantic_profile_snapshot,
    save_semantic_profile,
)
from tests.test_search import _seed_search_project


def test_quality_scope_defaults_to_approved_and_preserves_canonical_order() -> None:
    assert DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES == ("approved",)
    assert ExportProfileValues(name="Seguro").include_page_review_statuses == ("approved",)
    assert SemanticProfileValues(name="Seguro").include_page_review_statuses == ("approved",)
    assert normalize_page_review_statuses(("approved", "reviewed", "approved")) == (
        "reviewed",
        "approved",
    )
    default = analysis_quality_scope(("approved",))
    assert default.is_default
    assert default.key == "approved_only"
    assert not default.is_broader_than_default
    assert quality_scope_caption(("approved",)) == (
        "Alcance de calidad: solo páginas aprobadas."
    )


def test_broader_automatic_scope_requires_confirmation_and_reason() -> None:
    with pytest.raises(ValueError, match="confirmá explícitamente"):
        validate_automatic_quality_scope(
            ("reviewed", "approved"),
            broader_scope_confirmed=False,
        )
    with pytest.raises(ValueError, match="fundamento breve"):
        validate_automatic_quality_scope(
            ("reviewed", "approved"),
            broader_scope_confirmed=True,
        )
    with pytest.raises(ValueError, match="confirmá explícitamente"):
        validate_automatic_quality_scope((), broader_scope_confirmed=False)

    confirmed = validate_automatic_quality_scope(
        ("reviewed", "approved"),
        broader_scope_confirmed=True,
        confirmation_reason="Incluye páginas revisadas para comparar cobertura.",
    )
    assert confirmed.page_review_statuses == ("reviewed", "approved")


def test_all_current_and_planned_automatic_analyses_share_the_contract() -> None:
    assert set(AUTOMATIC_ANALYSIS_SPECS) == {
        "corpus_export",
        "semantic_index",
        "mention_suggestions",
        "summary",
        "statistics",
        "open_discovery",
        "assisted_import",
        "llm_tool",
        "rag",
        "integration",
    }
    for kind in AUTOMATIC_ANALYSIS_SPECS:
        snapshot = quality_scope_snapshot(
            analysis_kind=kind,
            page_review_statuses=("approved",),
        )
        assert snapshot["policy_version"] == ANALYSIS_QUALITY_POLICY_VERSION
        assert snapshot["analysis_kind"] == kind
        assert snapshot["scope_key"] == "approved_only"

    with pytest.raises(ValueError, match="no registrado"):
        validate_automatic_analysis_authorization(
            analysis_kind="unknown",
            page_review_statuses=("approved",),
            confirmed_by="tests",
            source="api",
        )


def test_export_and_semantic_profiles_record_append_only_authorizations(
    tmp_path: Path,
) -> None:
    root = tmp_path / "quality_profile_project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            with pytest.raises(ValueError, match="confirmá explícitamente"):
                save_export_profile(
                    session,
                    project_id="search_project",
                    values=ExportProfileValues(
                        name="Exportación ampliada",
                        include_page_review_statuses=("reviewed", "approved"),
                    ),
                    changed_by="tests",
                    broader_quality_scope_confirmed=False,
                )
            with pytest.raises(ValueError, match="fundamento breve"):
                save_export_profile(
                    session,
                    project_id="search_project",
                    values=ExportProfileValues(
                        name="Exportación ampliada",
                        include_page_review_statuses=("reviewed", "approved"),
                    ),
                    changed_by="tests",
                    broader_quality_scope_confirmed=True,
                )
            export_profile = save_export_profile(
                session,
                project_id="search_project",
                values=ExportProfileValues(
                    name="Exportación ampliada",
                    include_page_review_statuses=("reviewed", "approved"),
                ),
                changed_by="tests",
                broader_quality_scope_confirmed=True,
                quality_scope_reason="Comparación metodológica con páginas revisadas.",
                quality_scope_source="ui",
            )

            semantic_profile = save_semantic_profile(
                session,
                project_id="search_project",
                values=SemanticProfileValues(
                    name="Semántica aprobada",
                    include_page_review_statuses=("approved",),
                ),
                changed_by="tests",
                quality_scope_source="cli",
            )

            rows = automatic_analysis_authorization_rows(
                session,
                project_id="search_project",
                limit=20,
            )
            assert len(rows) == 2
            by_kind = {row.analysis_kind: row for row in rows}
            assert by_kind["corpus_export"].scope_key == "broader"
            assert by_kind["corpus_export"].confirmation_reason == (
                "Comparación metodológica con páginas revisadas."
            )
            assert by_kind["corpus_export"].source == "ui"
            assert by_kind["semantic_index"].scope_key == "approved_only"
            assert by_kind["semantic_index"].source == "cli"

            export_snapshot = export_profile_snapshot(export_profile)
            semantic_snapshot = semantic_profile_snapshot(semantic_profile)
            assert export_snapshot["analysis_quality"]["analysis_kind"] == (
                "corpus_export"
            )
            assert semantic_snapshot["analysis_quality"]["analysis_kind"] == (
                "semantic_index"
            )
    finally:
        engine.dispose()


def test_quality_controls_do_not_depend_on_reactive_state_inside_forms() -> None:
    root = Path(__file__).parents[1]
    export_source = (root / "src/archive_workbench/export_app.py").read_text(
        encoding="utf-8"
    )
    semantic_source = (root / "src/archive_workbench/semantic_app.py").read_text(
        encoding="utf-8"
    )
    authority_source = (root / "src/archive_workbench/authority_app.py").read_text(
        encoding="utf-8"
    )
    admin_source = (root / "src/archive_workbench/admin_app.py").read_text(
        encoding="utf-8"
    )
    audit_source = (root / "src/archive_workbench/analysis_audit.py").read_text(
        encoding="utf-8"
    )
    export_domain_source = (
        root / "src/archive_workbench/corpus_export.py"
    ).read_text(encoding="utf-8")
    semantic_domain_source = (
        root / "src/archive_workbench/semantic_search.py"
    ).read_text(encoding="utf-8")

    for source in (export_source, semantic_source):
        assert "Confirmo que deseo incluir páginas no aprobadas" in source
        assert "Fundamento del alcance ampliado" in source
        assert "broader_quality_scope_confirmed=" in source
        assert 'quality_scope_source="ui"' in source
        assert "st.form_submit_button" in source

    assert "Confirmo que deseo buscar menciones en páginas no aprobadas" in authority_source
    assert "candidate_quality_scope.is_default" in authority_source
    assert "candidate_quality_reason" in authority_source
    assert "record_mention_suggestion_authorization" in authority_source
    candidate_search = authority_source[
        authority_source.index('st.subheader("Encontrar nuevas menciones en el corpus")'):
        authority_source.index('if reset_col.button(')
    ]
    assert 'disabled=' not in candidate_search
    assert 'search_disabled' not in candidate_search
    assert "Auditoría de análisis" in admin_source
    assert "automatic_analysis_authorization_rows" in admin_source
    assert "require_automatic_analysis_authorization" in audit_source
    assert "_require_export_profile_authorization" in export_domain_source
    assert "_require_semantic_profile_authorization" in semantic_domain_source


def test_cli_requires_explicit_broader_scope_flags_and_exposes_audit() -> None:
    root = Path(__file__).parents[1]
    source = (root / "src/archive_workbench/cli.py").read_text(encoding="utf-8")
    assert '"--confirm-broader-quality-scope"' in source
    assert '"--quality-reason"' in source
    assert '@app.command("analysis-quality-audit")' in source


def test_cli_lists_persisted_analysis_authorizations(tmp_path: Path) -> None:
    root = tmp_path / "audit_cli_project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            save_export_profile(
                session,
                project_id="search_project",
                values=ExportProfileValues(
                    name="Perfil auditado",
                    include_page_review_statuses=("reviewed", "approved"),
                ),
                changed_by="alex",
                broader_quality_scope_confirmed=True,
                quality_scope_reason="Validación auditable desde pruebas.",
                quality_scope_source="cli",
            )
    finally:
        engine.dispose()

    result = CliRunner().invoke(app, ["analysis-quality-audit", str(root)])
    assert result.exit_code == 0, result.output
    assert "corpus_export" in result.output
    assert "broader" in result.output
    assert "fundamento: Validación auditable desde pruebas." in result.output
    assert "Total mostrado: 1 autorizaciones" in result.output
