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

    installer_path = root / "scripts/install_surya_runtime.sh"
    assert installer_path.stat().st_mode & 0o111
    installer = installer_path.read_text(encoding="utf-8")
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
        assert "surya_keep_server: false" in profile
        assert 'surya_torch_device: "cpu"' in profile
        assert "surya_clean_library_path: true" in profile
        assert 'fallback_profile: "config/extraction_docling_es.yaml"' in profile

    processing_source = (root / "src" / "archive_workbench" / "processing_app.py").read_text(encoding="utf-8")
    assert 'update={"surya_keep_server": len(source_keys) > 1}' in processing_source
    assert "stop_surya_servers()" in processing_source
    assert "finally:\n        if cleanup_surya:\n            stop_surya_servers()" in processing_source
    assert 'resource_cleanup="automatic_after_job"' in processing_source

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
        / "0045_audiovisual_transcription.py"
    )
    timeline_migration = (
        root
        / "src"
        / "archive_workbench"
        / "migrations"
        / "versions"
        / "0047_authority_relation_profiles.py"
    )

    assert data["project"]["version"] == "0.89.0"
    assert '__version__ = "0.89.0"' in version_source
    assert migration.is_file()
    assert 'down_revision = "0044_layout_structure_review"' in migration.read_text(
        encoding="utf-8"
    )
    assert timeline_migration.is_file()
    assert 'down_revision = "0046_audiovisual_timeline_annotations"' in timeline_migration.read_text(
        encoding="utf-8"
    )
    assert (root / "src" / "archive_workbench" / "audiovisual.py").is_file()
    assert (root / "src" / "archive_workbench" / "audiovisual_app.py").is_file()
    assert (root / "src" / "archive_workbench" / "audiovisual_review_component.py").is_file()
    assert (root / "src" / "archive_workbench" / "contracts" / "audiovisual.py").is_file()
    assert (root / "scripts" / "create_audiovisual_validation_project.py").is_file()
    assert (root / "scripts" / "verify_audiovisual_validation_project.py").is_file()
    assert (root / "examples" / "av01_validation" / "testimonio_controlado.wav").is_file()
    assert (root / "examples" / "av01_validation" / "testimonio_controlado.mp4").is_file()
    assert data["project"]["optional-dependencies"]["audiovisual"] == [
        "faster-whisper>=1.1,<2"
    ]
    assert data["project"]["optional-dependencies"]["platform"] == [
        "yt-dlp[default,deno]>=2026.7.4,<2027"
    ]
    assert (root / "src" / "archive_workbench" / "platform_import.py").is_file()
    assert (root / "src" / "archive_workbench" / "contracts" / "platform.py").is_file()
    assert (root / "src" / "archive_workbench" / "transcription_evaluation.py").is_file()
    assert (root / "src" / "archive_workbench" / "google_drive_transport.py").is_file()
    drive_creator = root / "scripts" / "create_google_drive_transport_validation_projects.py"
    drive_verifier = root / "scripts" / "verify_google_drive_transport_validation_project.py"
    for script in (drive_creator, drive_verifier):
        assert script.is_file()
        assert script.stat().st_mode & 0o111
    visual_creator = root / "scripts" / "create_visual_export_validation_project.py"
    visual_verifier = root / "scripts" / "verify_visual_export_validation_project.py"
    for script in (visual_creator, visual_verifier):
        assert script.is_file()
        assert script.stat().st_mode & 0o111
    assert (root / "src" / "archive_workbench" / "visual_export.py").is_file()
    av03_creator = root / "scripts" / "create_transcription_evaluation_validation_project.py"
    av03_verifier = root / "scripts" / "verify_transcription_evaluation_validation_project.py"
    for script in (av03_creator, av03_verifier):
        assert script.is_file()
        assert script.stat().st_mode & 0o111
    timeline_creator = root / "scripts" / "create_audiovisual_timeline_validation_project.py"
    timeline_verifier = root / "scripts" / "verify_audiovisual_timeline_validation_project.py"
    for script in (timeline_creator, timeline_verifier):
        assert script.is_file()
        assert script.stat().st_mode & 0o111
    sync_creator = root / "scripts" / "create_synchronized_review_validation_project.py"
    sync_verifier = root / "scripts" / "verify_synchronized_review_validation_project.py"
    for script in (sync_creator, sync_verifier):
        assert script.is_file()
        assert script.stat().st_mode & 0o111
    recognition_creator = root / "scripts" / "create_recognition_comparison_validation_project.py"
    recognition_verifier = root / "scripts" / "verify_recognition_comparison_validation_project.py"
    for script in (recognition_creator, recognition_verifier):
        assert script.is_file()
        assert script.stat().st_mode & 0o111
    assert (root / "tests" / "test_audiovisual_timeline.py").is_file()
    assert (root / "src" / "archive_workbench" / "contracts" / "forms.py").is_file()
    assert (root / "src" / "archive_workbench" / "form_structure.py").is_file()
    assert (root / "src" / "archive_workbench" / "contracts" / "layout.py").is_file()
    assert (root / "src" / "archive_workbench" / "layout_structure.py").is_file()
    assert (root / "scripts" / "create_layout_structure_validation_project.py").is_file()
    assert (root / "scripts" / "verify_layout_structure_validation_project.py").is_file()
    assert (root / "scripts" / "update_assistant_guidance_0800.py").is_file()
    assert (root / "src" / "archive_workbench" / "regional_workflow.py").is_file()
    assert (root / "src" / "archive_workbench" / "region_canvas.py").is_file()
    assert (root / "scripts" / "create_regional_ocr_validation_project.py").is_file()
    assert (root / "scripts" / "verify_regional_ocr_validation_project.py").is_file()
    assert (root / "scripts" / "update_assistant_guidance_0810.py").is_file()
    assert (root / "src" / "archive_workbench" / "preprocessing_geometry.py").is_file()
    assert (root / "src" / "archive_workbench" / "preprocessing_dewarp.py").is_file()
    assert (root / "scripts" / "create_dewarp_validation_project.py").is_file()
    assert (root / "scripts" / "verify_dewarp_validation_project.py").is_file()
    assert (root / "src" / "archive_workbench" / "ocr_truth_benchmark.py").is_file()
    assert (root / "src" / "archive_workbench" / "contracts" / "ocr_truth.py").is_file()
    assert (root / "config" / "ocr_benchmark_truth.yaml").is_file()
    assert (root / "config" / "ocr_benchmark_truth.template.yaml").is_file()
    assert (root / "scripts" / "create_ocr_truth_benchmark_validation_project.py").is_file()
    assert (root / "scripts" / "verify_ocr_truth_benchmark_validation_project.py").is_file()
    assert (root / "docs" / "referencia" / "BENCHMARK_OCR_VERDAD_TERRENO.md").is_file()
    processing_app = (root / "src" / "archive_workbench" / "processing_app.py").read_text(
        encoding="utf-8"
    )
    assert "Mostrar diagnóstico geométrico vigente" in processing_app
    assert 'st.expander("Diagnóstico geométrico vigente"' not in processing_app
    assert "Previsualización sin cambios" in processing_app
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
    geometry_validator = root / "scripts" / "create_preprocessing_geometry_validation_project.py"
    assert geometry_validator.is_file()
    geometry_source = geometry_validator.read_text(encoding="utf-8")
    assert "el script no elimina ni reemplaza proyectos" in geometry_source
    assert "project_data_touched" in geometry_source
    assert "orientation_rotation" in geometry_source
    assert "crossing_line_removed" in geometry_source
    form_validator = root / "scripts" / "create_form_structure_validation_project.py"
    assert form_validator.is_file()
    form_validator_source = form_validator.read_text(encoding="utf-8")
    assert "el script no elimina ni reemplaza proyectos" in form_validator_source
    assert "project_data_touched" in form_validator_source
    assert "candidate_count" in form_validator_source
    assert "confirmed_controls" in form_validator_source
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
        assert (assistant_root / "00_CHECKLIST_CAMBIOS.md").is_file()
        assert (assistant_root / "05_CRITERIOS_INTERFAZ.md").is_file()
        assert (assistant_root / "06_RELEVO_NUEVA_CONVERSACION.md").is_file()
        security = (assistant_root / "07_SEGURIDAD_ARCHIVOS_Y_REPOSITORIO.md").read_text(encoding="utf-8")
        assert "incluye `.assistant` completa y vigente" in security
        assert "se conserva y mantiene actualizada también en la copia local de trabajo" in security
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


def test_regional_ocr_validation_scripts_are_packaged_and_executable() -> None:
    root = Path(__file__).parents[1]
    creator = root / "scripts" / "create_regional_ocr_validation_project.py"
    resume = root / "scripts" / "prepare_regional_ocr_validation_resume.py"
    verifier = root / "scripts" / "verify_regional_ocr_validation_project.py"
    guidance = root / "scripts" / "update_assistant_guidance_0810.py"

    for script in (creator, resume, verifier, guidance):
        assert script.is_file()
        assert script.stat().st_mode & 0o111

    creator_source = creator.read_text(encoding="utf-8")
    resume_source = resume.read_text(encoding="utf-8")
    verifier_source = verifier.read_text(encoding="utf-8")
    assert "el script no elimina ni reemplaza proyectos" in creator_source
    assert "project_data_touched" in creator_source
    assert "manual_region_to_add" in creator_source
    assert "ocr01d_controlada_resume.yaml" in resume_source
    assert '"reading_order": 50' in resume_source
    assert "RESULTADO: validación OCR-01D completa y consistente." in verifier_source
    assert "la selección canónica permanece vacía" in verifier_source


def test_dewarp_validation_scripts_are_packaged_and_executable() -> None:
    root = Path(__file__).parents[1]
    creator = root / "scripts" / "create_dewarp_validation_project.py"
    verifier = root / "scripts" / "verify_dewarp_validation_project.py"

    for script in (creator, verifier):
        assert script.is_file()
        assert script.stat().st_mode & 0o111

    creator_source = creator.read_text(encoding="utf-8")
    verifier_source = verifier.read_text(encoding="utf-8")
    assert "el script no elimina ni reemplaza proyectos" in creator_source
    assert "project_data_touched" in creator_source
    assert "expected_curved_applied" in creator_source
    assert "RESULTADO: validación OCR-01E completa y consistente." in verifier_source
    assert "la selección canónica permanece vacía" in verifier_source


def test_first_project_default_configuration_is_packaged() -> None:
    root = Path(__file__).parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = data["tool"]["setuptools"]["package-data"]["archive_workbench"]

    assert "default_config/*.yaml" in package_data
    defaults = root / "src" / "archive_workbench" / "default_config"
    for name in (
        "decisions.template.yaml",
        "extraction.template.yaml",
        "extraction_docling_es.template.yaml",
        "extraction_surya_es.template.yaml",
        "extraction_tesseract.template.yaml",
        "extraction_press_columns.template.yaml",
        "ocr_benchmark.template.yaml",
        "ocr_benchmark_truth.template.yaml",
        "regions_leg_17_leg_15_a_c_6.template.yaml",
        "test_corpus.template.yaml",
    ):
        assert (defaults / name).is_file(), name



def test_candidate_update_reconciles_only_known_relocations(tmp_path: Path) -> None:
    import json
    import shutil
    import subprocess
    import sys

    root = Path(__file__).parents[1]
    target = tmp_path / "repo"
    target.mkdir()
    shutil.copy2(root / "pyproject.toml", target / "pyproject.toml")

    manifest = json.loads(
        (root / "scripts" / "candidate_update_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["candidate"] == "0.89.0 RC82"
    assert len(manifest["relocations"]) == 5

    for item in manifest["relocations"]:
        historical = root / item["to"]
        old = target / item["from"]
        old.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(historical, old)

    local_marker = target / "pilot_data" / "LOCAL_DO_NOT_TOUCH.txt"
    local_marker.parent.mkdir(parents=True)
    local_marker.write_text("persistente", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "apply_candidate_update.py"),
            "--source",
            str(root),
            "--target",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert local_marker.read_text(encoding="utf-8") == "persistente"
    for item in manifest["relocations"]:
        assert not (target / item["from"]).exists()
        assert (target / item["to"]).is_file()

    operational_files = {
        path.name for path in (target / "docs" / "operativos").iterdir() if path.is_file()
    }
    assert operational_files == {
        "PENDIENTES_ACTIVOS.md",
        "IMPLEMENTACIONES_REALIZADAS.md",
        "ACTUALIZACION_ACTUAL.md",
        "ESTRATEGIA_DE_PRUEBAS.md",
        "GUIA_PRUEBA_PILOTO.md",
        "HOJA_DE_RUTA_PRE_RELEASE.md",
    }


def test_candidate_update_aborts_before_copy_if_known_old_file_was_modified(tmp_path: Path) -> None:
    import json
    import shutil
    import subprocess
    import sys

    root = Path(__file__).parents[1]
    target = tmp_path / "repo"
    target.mkdir()
    shutil.copy2(root / "pyproject.toml", target / "pyproject.toml")
    marker = target / "src" / "do_not_overwrite.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("antes", encoding="utf-8")

    manifest = json.loads(
        (root / "scripts" / "candidate_update_manifest.json").read_text(encoding="utf-8")
    )
    item = manifest["relocations"][0]
    old = target / item["from"]
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("contenido local modificado", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "apply_candidate_update.py"),
            "--source",
            str(root),
            "--target",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "No se tocará" in result.stderr
    assert marker.read_text(encoding="utf-8") == "antes"
    assert old.read_text(encoding="utf-8") == "contenido local modificado"
    assert not (target / "src" / "archive_workbench").exists()
