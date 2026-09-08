from __future__ import annotations

from pathlib import Path

import pytest


# OPS-02: cada módulo de prueba pertenece a exactamente un nivel operativo.
# La clasificación es deliberadamente central para que una prueba nueva no quede
# fuera de los comandos estables por omisión.
TEST_LEVELS: dict[str, frozenset[str]] = {
    "fast": frozenset(
        {
            "test_contracts.py",
            "test_decisions.py",
            "test_documentation.py",
            "test_inspection.py",
            "test_jsonl.py",
            "test_merge.py",
            "test_packaging.py",
            "test_runtime_environment.py",
            "test_structure_quality.py",
            "test_temporal.py",
            "test_test_corpus.py",
            "test_ui_navigation.py",
        }
    ),
    "integration": frozenset(
        {
            "test_analysis_quality.py",
            "test_audiovisual.py",
            "test_audiovisual_timeline.py",
            "test_authority_dictionary.py",
            "test_candidate_review.py",
            "test_catalog_management.py",
            "test_catalog_templates.py",
            "test_container_distribution.py",
            "test_corpus_export.py",
            "test_database.py",
            "test_dewarp.py",
            "test_discovery_grouping.py",
            "test_document_plans.py",
            "test_editing.py",
            "test_extraction.py",
            "test_form_structure.py",
            "test_google_drive_transport.py",
            "test_graph.py",
            "test_layout_structure.py",
            "test_mention_repairs.py",
            "test_ocr_quality.py",
            "test_open_discovery.py",
            "test_operational.py",
            "test_platform_import.py",
            "test_preprocessing.py",
            "test_processing.py",
            "test_project_admin.py",
            "test_project_init.py",
            "test_project_setup.py",
            "test_rebase_structural_metadata.py",
            "test_region_extraction.py",
            "test_regional_workflow.py",
            "test_relations.py",
            "test_review.py",
            "test_search.py",
            "test_semantic_search.py",
            "test_work.py",
        }
    ),
    "slow": frozenset(
        {
            "test_discovery_evaluation.py",
            "test_exchange.py",
            "test_ocr_truth_benchmark.py",
            "test_semantic_evaluation.py",
            "test_surya_extraction.py",
            "test_transcription_evaluation.py",
        }
    ),
}


def _level_for_test_module(path: Path) -> str:
    filename = path.name
    levels = [level for level, filenames in TEST_LEVELS.items() if filename in filenames]
    if len(levels) != 1:
        detail = "ninguno" if not levels else ", ".join(levels)
        raise pytest.UsageError(
            f"OPS-02: {filename} debe pertenecer a exactamente un nivel; encontrado: {detail}."
        )
    return levels[0]


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(getattr(pytest.mark, _level_for_test_module(item.path)))
