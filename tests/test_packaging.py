from pathlib import Path
import tomllib

from packaging.specifiers import SpecifierSet
from packaging.version import Version


def test_surya_runtime_packaging_is_compatible_and_isolated() -> None:
    root = Path(__file__).parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    dependencies = data["project"]["dependencies"]
    surya_dependencies = data["project"]["optional-dependencies"]["surya"]
    pillow_requirement = next(item for item in dependencies if item.startswith("Pillow"))
    pillow_specifier = SpecifierSet(pillow_requirement.removeprefix("Pillow"))

    assert Version("10.2.0") in pillow_specifier
    assert Version("10.4.0") in pillow_specifier
    assert Version("12.3.0") in pillow_specifier
    assert surya_dependencies == ["surya-ocr==0.22.1"]

    installer = (root / "scripts/install_surya_runtime.sh").read_text(encoding="utf-8")
    assert ".venv-surya" in installer
    assert "--dry-run" in installer
    assert '"${PIP[@]}" check' in installer
    assert 'TARGET="${ROOT}[surya]"' in installer

    assert ".venv-surya/" in (root / ".gitignore").read_text(encoding="utf-8")
    for profile_name in (
        "extraction.yaml",
        "extraction.template.yaml",
        "extraction_surya_es.yaml",
        "extraction_surya_es.template.yaml",
    ):
        profile = (root / "config" / profile_name).read_text(encoding="utf-8")
        assert 'surya_command: ".venv-surya/bin/surya_ocr"' in profile
        assert "surya_keep_server: true" in profile
        assert 'surya_torch_device: "cpu"' in profile
        assert "surya_clean_library_path: true" in profile
        assert 'fallback_profile: "config/extraction_docling_es.yaml"' in profile

    fallback = (root / "config/extraction_docling_es.yaml").read_text(encoding="utf-8")
    assert 'profile_key: "docling_tesseract_es_fallback_v1"' in fallback
    assert 'backend: "docling_cli"' in fallback


def test_rebase_validation_project_generator_is_packaged() -> None:
    root = Path(__file__).parents[1]
    script = root / "scripts" / "create_rebase_validation_project.py"
    source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "project_data_rebase_validation" in source
    assert "demo_surya_candidata" in source
    assert "classification" in source
    assert "bootstrap_editable_layer" in source


def test_mention_repair_validation_project_generator_is_packaged() -> None:
    root = Path(__file__).parents[1]
    script = root / "scripts" / "create_mention_repair_validation_project.py"
    source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "project_data_mention_repair_validation" in source
    assert "Prefijo descartable de validación" in source
    assert "create_mention" in source
    assert "mention_repair_cases" in source
    assert "Offsets almacenados" in source
    assert "Offsets proyectados" in source
    assert "_append_revision" in source


def test_missing_authority_validation_project_generator_is_packaged() -> None:
    root = Path(__file__).parents[1]
    script = root / "scripts" / "create_missing_authority_validation_project.py"
    source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "project_data_missing_authority_validation" in source
    assert "Mencion descartable alfa para vincular" in source
    assert "Mencion descartable beta para devolver a pendiente" in source
    assert "Entidad de destino para reparación" in source
    assert "missing_authority" in source
    assert "_append_mention_revision" in source


def test_duplicate_mention_validation_project_generator_is_packaged() -> None:
    root = Path(__file__).parents[1]
    script = root / "scripts" / "create_duplicate_mention_validation_project.py"
    source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "project_data_duplicate_mention_validation" in source
    assert "Mencion duplicada alfa para conservar la vigente" in source
    assert "Mencion duplicada beta para conservar la historica" in source
    assert "duplicate_relocation" in source
    assert "_append_mention_revision" in source


def test_unresolved_mention_validation_project_generator_is_packaged() -> None:
    root = Path(__file__).parents[1]
    script = root / "scripts" / "create_unresolved_mention_validation_project.py"
    source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "project_data_unresolved_mention_validation" in source
    assert "MENCION AMBIGUA REPETIDA" in source
    assert "FRAGMENTO RETIRADO DEL TEXTO VIGENTE" in source
    assert "unresolved_relocation" in source
    assert "_append_revision" in source


def test_snapshot_divergence_validation_project_generator_is_packaged() -> None:
    root = Path(__file__).parents[1]
    script = root / "scripts" / "create_snapshot_divergence_validation_project.py"
    source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "project_data_snapshot_divergence_validation" in source
    assert "Mencion divergente alfa para conservar fila vigente" in source
    assert "Mencion divergente beta para restaurar historial" in source
    assert "snapshot_divergence" in source
    assert "can_resolve_snapshot_divergence" in source



def test_grouped_mention_validation_project_generator_is_packaged() -> None:
    root = Path(__file__).parents[1]
    script = root / "scripts" / "create_grouped_mention_validation_project.py"
    source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "project_data_grouped_mention_validation" in source
    assert "Mencion conjunta para elegir una entre tres" in source
    assert "Mencion segura agrupada alfa" in source
    assert "duplicate_group" in source
    assert "safe_relocation" in source
    assert "Entidad conjunta histórica beta" in source

def test_analysis_quality_audit_validation_project_generator_is_packaged() -> None:
    root = Path(__file__).parents[1]
    script = root / "scripts" / "create_analysis_quality_audit_validation_project.py"
    source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "--source" in source and "--destination" in source
    assert "AutomaticAnalysisAuthorization" in source
    assert "upgrade_database(destination)" in source
    assert "Perfiles, índices y autorizaciones anteriores reiniciados" in source


def test_version_docs_and_discovery_plan_are_packaged() -> None:
    root = Path(__file__).parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version_source = (root / "src" / "archive_workbench" / "version.py").read_text(
        encoding="utf-8"
    )
    migration = (
        root
        / "src"
        / "archive_workbench"
        / "migrations"
        / "versions"
        / "0041_catalog_authority_roles_graph_layers.py"
    )

    assert data["project"]["version"] == "0.77.0"
    assert '__version__ = "0.77.0"' in version_source
    assert migration.is_file()
    assert 'down_revision = "0040_discovery_grouping_continuity"' in migration.read_text(
        encoding="utf-8"
    )
    assert (root / "src" / "archive_workbench" / "lineage_recovery.py").is_file()
    assert (root / "src" / "archive_workbench" / "common_base.py").is_file()
    assert (root / "src" / "archive_workbench" / "state_adoption.py").is_file()
    assert (root / "src" / "archive_workbench" / "open_discovery.py").is_file()
    assert (root / "src" / "archive_workbench" / "discovery_app.py").is_file()
    assert (root / "src" / "archive_workbench" / "discovery_review.py").is_file()
    assert (root / "src" / "archive_workbench" / "discovery_grouping.py").is_file()
    assert (root / "src" / "archive_workbench" / "discovery_providers.py").is_file()
    assert (root / "src" / "archive_workbench" / "discovery_evaluation.py").is_file()
    assert (root / "config" / "discovery_evaluation_corpus.jsonl").is_file()
    assert (root / "src" / "archive_workbench" / "semantic_evaluation.py").is_file()
    assert (root / "config" / "semantic_evaluation_corpus.example.jsonl").is_file()
    assert (root / "src" / "archive_workbench" / "authority_dictionary.py").is_file()
    assert (
        root / "config" / "authority_dictionaries" / "authority_dictionary.schema.json"
    ).is_file()
    assert (root / "examples" / "diccionario_autoridades_ejemplo.json").is_file()
    dictionary_validator = root / "scripts" / "create_authority_dictionary_validation_project.py"
    assert dictionary_validator.is_file()
    dictionary_validator_source = dictionary_validator.read_text(encoding="utf-8")
    assert "project_data no fue leído ni modificado" in dictionary_validator_source
    assert "diccionario_conflicto_sin_resolver.json" in dictionary_validator_source
    assert "diccionario_relacion_sin_evidencia.json" in dictionary_validator_source
    assert (root / "src" / "archive_workbench" / "catalog_templates.py").is_file()
    assert (root / "config" / "catalog_templates" / "dippba_public_seed.json").is_file()
    assert (root / "examples" / "plantilla_catalogo_dippba.xlsx").is_file()
    catalog_validator = root / "scripts" / "create_catalog_template_validation_project.py"
    assert catalog_validator.is_file()
    catalog_validator_source = catalog_validator.read_text(encoding="utf-8")
    assert "project_data no fue leído ni modificado" in catalog_validator_source
    assert "plantilla_invalida_documento_bajo_fondo.xlsx" in catalog_validator_source
    assert "openpyxl>=3.1,<4" in data["project"]["dependencies"]
    semantic_validator = root / "scripts" / "create_semantic_graph_validation_project.py"
    assert semantic_validator.is_file()
    semantic_validator_source = semantic_validator.read_text(encoding="utf-8")
    assert "project_data no fue leído ni modificado" in semantic_validator_source
    assert "semantic_evaluation_alt.json" in semantic_validator_source
    catalog_graph_validator = root / "scripts" / "create_catalog_graph_validation_project.py"
    assert catalog_graph_validator.is_file()
    catalog_graph_source = catalog_graph_validator.read_text(encoding="utf-8")
    assert "el script no elimina ni reemplaza proyectos" in catalog_graph_source
    assert "CAT-02/GRAPH-02" in catalog_graph_source
    assert "project_data_touched" in catalog_graph_source
    assert "0041_catalog_authority_roles_graph_layers" not in catalog_graph_source
    assert data["project"]["optional-dependencies"]["discovery"] == [
        "spacy>=3.8,<4"
    ]
    assert (root / "scripts" / "create_open_discovery_validation_project.py").is_file()
    assert (root / "scripts" / "prepare_open_discovery_review_validation.py").is_file()
    assert (root / "scripts" / "prepare_open_discovery_grouping_validation.py").is_file()
    validator_c = root / "scripts" / "validate_open_discovery_disc01c.py"
    assert validator_c.is_file()
    validator_c_source = validator_c.read_text(encoding="utf-8")
    assert "DiscoveryCandidateContinuity" in validator_c_source
    assert "discovery_group_rows" in validator_c_source
    validator_b = root / "scripts" / "validate_open_discovery_disc01b.py"
    assert validator_b.is_file()
    validator_b_source = validator_b.read_text(encoding="utf-8")
    assert "EXPECTED_DECISIONS" in validator_b_source
    assert "discovery_context_records" in validator_b_source
    validator = root / "scripts" / "validate_open_discovery_disc01a.py"
    assert validator.is_file()
    validator_source = validator.read_text(encoding="utf-8")
    assert "controlled_candidates" in validator_source
    assert "editable_object_id" in validator_source
    assert (root / "docs" / "HISTORIAL_DE_CAMBIOS.md").is_file()
    assert (root / "docs" / "operativos" / "PENDIENTES_ACTIVOS.md").is_file()
    assert (root / "docs" / "operativos" / "ESTRATEGIA_DE_PRUEBAS.md").is_file()
    assert (root / "docs" / "operativos" / "ACTUALIZACION_ACTUAL.md").is_file()
    assert ".assistant/" in (root / ".gitignore").read_text(encoding="utf-8")
    assistant_root = root / ".assistant"
    if assistant_root.is_dir():
        assert (assistant_root / "00_LEER_PRIMERO.md").is_file()
        assert (assistant_root / "05_CRITERIOS_INTERFAZ.md").is_file()
        assert (assistant_root / "06_RELEVO_NUEVA_CONVERSACION.md").is_file()
    assert (
        root / "docs" / "referencia" / "RECUPERACION_LINAJE_EX_01.md"
    ).is_file()
    assert (
        root / "docs" / "referencia" / "DESCUBRIMIENTO_ABIERTO_DISC_01.md"
    ).is_file()
    assert (
        root / "scripts" / "create_lineage_diagnostic_validation_projects.py"
    ).is_file()
    assert (root / "src" / "archive_workbench" / "lineage_diagnostics.py").is_file()
    assert (root / "scripts" / "create_common_base_validation_projects.py").is_file()
    assert (root / "scripts" / "create_state_adoption_validation_projects.py").is_file()


def test_common_base_validation_project_generator_is_packaged() -> None:
    root = Path(__file__).parents[1]
    script = root / "scripts" / "create_common_base_validation_projects.py"
    source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "--initiator-destination" in source
    assert "--counterpart-destination" in source
    assert "ex01c-iniciadora" in source
    assert "ex01c-contraparte" in source
    assert "current_editable_state_sha256" in source
    assert "El proyecto fuente no fue modificado" in source


def test_state_adoption_validation_project_generator_is_packaged() -> None:
    root = Path(__file__).parents[1]
    script = root / "scripts" / "create_state_adoption_validation_projects.py"
    source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "--source-destination" in source
    assert "--target-destination" in source
    assert "ex01d-origen" in source
    assert "ex01d-destino" in source
    assert "create_state_adoption_package" in source
    assert "Estado remoto EX-01D" in source
    assert "Estado local EX-01D" in source
    assert "El proyecto fuente no fue modificado" in source
