from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import date, datetime, time, timezone
import sys
from pathlib import Path
from uuid import UUID

import typer
from sqlalchemy import select

from archive_workbench.authorities import (
    ALIAS_TYPES,
    AUTHORITY_TYPES,
    add_authority_alias,
    authority_mention_candidates,
    authority_rows,
    create_authority,
    include_authority_mention_candidates,
    mention_rows,
    suggest_dictionary_mentions,
    suggest_dictionary_mentions_all,
)
from archive_workbench.relations import (
    RELATION_REVIEW_STATUSES,
    RELATION_TARGET_KINDS,
    create_entity_relation,
    entity_relation_rows,
)
from archive_workbench.catalog import (
    database_counts,
    inventory_rows,
    register_test_corpus,
    scan_file_instances,
)
from archive_workbench.catalog_management import (
    REGISTRATION_STATUSES,
    RELATION_TYPES,
    catalog_summary,
    register_local_file,
    search_catalog_units,
)
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import Project, SourceRegistration, WorkAssignment
from archive_workbench.decisions import load_decisions
from archive_workbench.document_plans import (
    create_document_plan_template,
    document_part_status_rows,
    execute_document_plan,
    import_document_plan,
    load_document_plan,
    plan_status_rows,
    render_contact_sheets,
    validate_plan_against_catalog,
    write_document_plan,
)
from archive_workbench.editing import (
    add_editable_object,
    bootstrap_editable_layer,
    editable_object_rows,
    editing_status_rows,
    export_editable_layer,
    object_revision_rows,
    revert_editable_object,
    set_editable_object_lifecycle,
    update_editable_object,
)
from archive_workbench.extraction import (
    extract_documents,
    extraction_doctor,
    extraction_history_rows,
    extraction_status_rows,
    selected_extraction_status_rows,
    select_extraction_pages,
    load_extraction_profile,
    review_current_extraction,
    restore_profile_page_selections,
)
from archive_workbench.graph import (
    build_graph,
    export_graph,
    graph_consistency_issues,
)
from archive_workbench.corpus_export import (
    AGGREGATION_LEVELS,
    OUTPUT_FORMATS,
    REVIEW_STATUSES as EXPORT_REVIEW_STATUSES,
    TEXT_POLICIES,
    ExportProfileValues,
    export_profile_rows,
    export_run_rows,
    preview_export,
    resolve_export_profile,
    run_export,
    save_export_profile,
)
from archive_workbench.inspection import inspect_input
from archive_workbench.ocr_benchmark import (
    load_ocr_benchmark_profile,
    run_ocr_benchmark,
)
from archive_workbench.preprocessing import prepare_derivatives, preprocessing_status_rows
from archive_workbench.work import (
    ASSIGNMENT_KINDS,
    ASSIGNMENT_PRIORITIES,
    ASSIGNMENT_STATUSES,
    CROSS_REVIEW_OUTCOMES,
    create_cross_review_assignment,
    create_work_assignment,
    update_work_assignment,
    work_assignment_rows,
    workload_summary_rows,
)
from archive_workbench.processing import (
    processing_inventory_rows,
    processing_job_item_rows,
    processing_job_rows,
)
from archive_workbench.region_extraction import (
    extract_regions,
    load_region_template,
    region_status_rows,
    render_region_template,
    validate_region_template,
)
from archive_workbench.project_init import initialize_project
from archive_workbench.operational import (
    operational_readiness,
    recovery_check_rows,
    run_project_backup_recovery_test,
)
from archive_workbench.project_admin import (
    check_project_health,
    create_project_backup,
    inspect_project_backup,
    list_project_backups,
    restore_project_backup,
)
from archive_workbench.test_corpus import load_test_corpus
from archive_workbench.search import (
    SEARCH_FIELDS,
    rebuild_search_index,
    search_editable_objects,
    search_index_status,
)
from archive_workbench.semantic_search import (
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_REVISION,
    SEMANTIC_AGGREGATION_LEVELS,
    SemanticProfileValues,
    build_semantic_index,
    ensure_default_semantic_profile,
    resolve_semantic_profile,
    save_semantic_profile,
    semantic_index_status,
    semantic_profile_rows,
    semantic_search,
)
from archive_workbench.exchange import (
    apply_change_bundle,
    bundle_application_rows,
    checkpoint_rows,
    create_exchange_checkpoint,
    conflict_field_rows,
    ensure_exchange_workspace,
    dry_run_change_bundle,
    exchange_status,
    export_change_bundle,
    finalize_bundle_resolutions,
    fork_exchange_workspace,
    incoming_bundle_rows,
    inspect_change_bundle,
    resolution_status,
    resolve_conflict_fields_bulk,
    save_conflict_resolution,
    skip_conflicted_event,
)

app = typer.Typer(no_args_is_help=True, help="Utilidades iniciales de Archive Workbench.")


@app.command("validate-decisions")
def validate_decisions(path: Path) -> None:
    """Valida la plantilla de decisiones del proyecto."""
    decisions = load_decisions(path)
    typer.echo(
        f"OK: {decisions.project_name} — "
        f"{len(decisions.archival_levels)} niveles, {len(decisions.object_types)} objetos"
    )


@app.command("validate-test-corpus")
def validate_test_corpus(path: Path) -> None:
    """Valida la definición del corpus de prueba."""
    corpus = load_test_corpus(path)
    typer.echo(f"OK: {corpus.corpus_name} — {len(corpus.documents)} documentos")


@app.command("inspect-test-corpus")
def inspect_test_corpus(
    path: Path,
    root: Path = typer.Option(Path("."), help="Raíz para resolver local_path"),
) -> None:
    """Inspecciona los archivos presentes del corpus y señala los que faltan."""
    corpus = load_test_corpus(path)
    missing = 0
    inspected = 0
    for document in corpus.documents:
        source = root / document.local_path
        if not source.is_file():
            missing += 1
            typer.echo(f"MISSING  {document.test_id}: {source}")
            continue
        result = inspect_input(source)
        inspected += 1
        ocr_pages = sum(page.likely_requires_ocr is True for page in result.pages)
        landscape = sum(page.landscape for page in result.pages)
        typer.echo(
            f"OK       {document.test_id}: {result.media_type.value}, "
            f"{result.page_count or 0} pág., OCR probable {ocr_pages}, apaisadas {landscape}"
        )
        for warning in result.warnings:
            typer.echo(f"         ⚠ {warning}")
    typer.echo(f"Resumen: {inspected} inspeccionados, {missing} faltantes")


@app.command("inspect-input")
def inspect_input_command(path: Path, pretty: bool = True) -> None:
    """Inspecciona un PDF, TIFF o imagen sin modificarlo."""
    inspection = inspect_input(path)
    payload = inspection.model_dump(mode="json", exclude_none=True)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))


@app.command("init-project")
def init_project(path: Path, templates: Path | None = None) -> None:
    """Crea la estructura inicial de carpetas de un proyecto."""
    root = initialize_project(path, templates)
    typer.echo(f"Proyecto inicializado en: {root}")


@app.command("db-upgrade")
def db_upgrade(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Crea o actualiza la base SQLite mediante migraciones Alembic."""
    db_path = upgrade_database(project_root)
    typer.echo(f"OK: base actualizada en {db_path}")
    typer.echo(f"Revisión: {current_revision(project_root)}")


@app.command("register-test-corpus")
def register_test_corpus_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    allow_missing: bool = typer.Option(
        False, help="Registra solo archivos presentes en lugar de fallar por ausencias"
    ),
) -> None:
    """Registra en SQLite los archivos y unidades del corpus de prueba."""
    decisions_path = project_root / "config" / "decisions.yaml"
    corpus_path = project_root / "config" / "test_corpus.yaml"
    decisions = load_decisions(decisions_path)
    corpus = load_test_corpus(corpus_path)
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = register_test_corpus(
                session,
                project_root=project_root,
                decisions=decisions,
                corpus=corpus,
                allow_missing=allow_missing,
            )
    finally:
        engine.dispose()
    typer.echo(
        "OK: "
        f"{summary.documents_registered}/{summary.documents_seen} documentos registrados; "
        f"objetos digitales +{summary.digital_objects_created} "
        f"(reutilizados {summary.digital_objects_reused}); "
        f"unidades +{summary.archival_units_created}; "
        f"archivos faltantes {summary.missing_files}."
    )


@app.command("scan-files")
def scan_files_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Verifica presencia e integridad de las copias locales registradas."""
    db_path = database_path(project_root)
    if not db_path.is_file():
        raise typer.BadParameter("La base todavía no existe; ejecute db-upgrade primero")
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            summary = scan_file_instances(session, project_root)
    finally:
        engine.dispose()
    typer.echo(
        f"OK: {summary.checked} revisados — presentes {summary.present}, "
        f"faltantes {summary.missing}, modificados {summary.modified}"
    )


@app.command("inventory")
def inventory_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Lista los documentos registrados y el estado de su copia local."""
    db_path = database_path(project_root)
    if not db_path.is_file():
        raise typer.BadParameter("La base todavía no existe; ejecute db-upgrade primero")
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            rows = inventory_rows(session)
    finally:
        engine.dispose()
    for row in rows:
        pages = "?" if row.page_count is None else str(row.page_count)
        typer.echo(
            f"{row.source_key} | {row.registration_status} | "
            f"{row.presence or 'sin_copia'} | {row.media_type or '?'} {pages} pág. | "
            f"{row.title} | {row.relative_path or '-'}"
        )
    typer.echo(f"Total: {len(rows)} documentos")


@app.command("catalog-tree")
def catalog_tree_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    query: str = typer.Option("", "--query", "-q", help="Texto a buscar"),
    level: str | None = typer.Option(None, "--level", help="Filtrar por nivel"),
    status: str | None = typer.Option(None, "--status", help="Filtrar por estado"),
) -> None:
    """Lista el índice jerárquico del catálogo con filtros opcionales."""
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    if level is not None and level not in {item.key for item in decisions.archival_levels}:
        raise typer.BadParameter(f"Nivel desconocido: {level}")
    if status is not None and status not in REGISTRATION_STATUSES:
        raise typer.BadParameter(
            "Estado inválido; use " + ", ".join(REGISTRATION_STATUSES)
        )
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = search_catalog_units(
                session,
                project_id=decisions.project_id,
                query=query,
                level_key=level,
                registration_status=status,
            )
            summary = catalog_summary(session, decisions.project_id)
    finally:
        engine.dispose()
    for row in rows:
        indent = "  " * row.depth
        code = f" [{row.reference_code}]" if row.reference_code else ""
        typer.echo(
            f"{indent}{row.level_key}: {row.title}{code} | {row.registration_status} | "
            f"objetos {row.digital_object_count} | {row.id}"
        )
    typer.echo(
        f"Total mostrado: {len(rows)} | catálogo {summary.units} unidades, "
        f"{summary.digital_objects} objetos digitales, {summary.missing_files} archivos ausentes"
    )


@app.command("catalog-register-file")
def catalog_register_file_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    unit_id: str = typer.Argument(..., help="UUID de la unidad archivística"),
    relative_path: str = typer.Argument(..., help="Ruta relativa al proyecto"),
    relation_type: str = typer.Option("represents", "--relation"),
    page_start: int | None = typer.Option(None, "--page-start", min=1),
    page_end: int | None = typer.Option(None, "--page-end", min=1),
    registered_by: str = typer.Option("local_user", "--registered-by"),
) -> None:
    """Registra un archivo local por SHA-256 y lo vincula con una unidad."""
    if relation_type not in RELATION_TYPES:
        raise typer.BadParameter(
            "Relación inválida; use " + ", ".join(RELATION_TYPES)
        )
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            result = register_local_file(
                session,
                project_root=project_root,
                project_id=decisions.project_id,
                archival_unit_id=unit_id,
                relative_path=relative_path,
                relation_type=relation_type,
                page_start=page_start,
                page_end=page_end,
                registered_by=registered_by,
            )
    except (ValueError, FileNotFoundError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: objeto {result.digital_object_id} | archivo {result.file_instance_id} | "
        f"vínculo {result.link_id} | fuente {result.source_key} | contenido "
        f"{'reutilizado' if result.duplicate_content else 'nuevo'}"
    )


@app.command("db-status")
def db_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Muestra revisión y conteos principales de la base."""
    db_path = database_path(project_root)
    if not db_path.is_file():
        typer.echo(f"SIN BASE: {db_path}")
        raise typer.Exit(code=1)
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            counts = database_counts(session)
    finally:
        engine.dispose()
    typer.echo(f"Base: {db_path}")
    typer.echo(f"Revisión: {current_revision(project_root)}")
    for key, value in counts.items():
        typer.echo(f"{key}: {value}")


@app.command("prepare-derivatives")
def prepare_derivatives_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: list[str] | None = typer.Option(
        None, "--source-key", help="Procesa solo uno o más identificadores del corpus"
    ),
    force: bool = typer.Option(False, help="Genera una nueva corrida aunque exista una equivalente"),
) -> None:
    """Genera PNG para OCR y previsualizaciones WebP/JPEG/PNG por página."""
    decisions_path = project_root / "config" / "decisions.yaml"
    decisions = load_decisions(decisions_path)
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = prepare_derivatives(
                session,
                project_root=project_root,
                decisions=decisions,
                source_keys=set(source_key or []),
                force=force,
            )
    finally:
        engine.dispose()
    typer.echo(
        f"OK: {summary.objects_seen} objetos — corridas nuevas {summary.runs_created}, "
        f"reutilizadas {summary.runs_reused}, fallidas {summary.failed}, "
        f"derivados creados {summary.assets_created}"
    )
    for warning in summary.warnings:
        typer.echo(f"⚠ {warning}")
    if summary.failed:
        raise typer.Exit(code=1)


@app.command("preprocessing-status")
def preprocessing_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Muestra el estado de los derivados vigentes por documento."""
    db_path = database_path(project_root)
    if not db_path.is_file():
        raise typer.BadParameter("La base todavía no existe; ejecute db-upgrade primero")
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            rows = preprocessing_status_rows(session)
    finally:
        engine.dispose()
    for row in rows:
        pages = "?" if row.page_count is None else str(row.page_count)
        typer.echo(
            f"{row.source_key} | {row.run_status or 'sin_derivados'} | "
            f"{row.media_type} {pages} pág. | assets {row.assets} | "
            f"{row.output_root or '-'} | {row.title}"
        )
    typer.echo(f"Total: {len(rows)} documentos")


@app.command("extraction-doctor")
def extraction_doctor_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    profile_path: Path | None = typer.Option(
        None, "--profile", help="Perfil YAML; por defecto config/extraction.yaml"
    ),
) -> None:
    """Comprueba las herramientas requeridas por un perfil de extracción."""
    selected_profile = profile_path or (project_root / "config" / "extraction.yaml")
    profile = load_extraction_profile(selected_profile)
    report = extraction_doctor(profile)
    for check in report.checks:
        marker = "OK" if check.ok else ("ERROR" if check.required else "INFO")
        typer.echo(f"{marker:5} {check.name}: {check.detail}")
    if not report.ready:
        raise typer.Exit(code=1)


@app.command("extract")
def extract_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: list[str] | None = typer.Option(
        None, "--source-key", help="Procesa solo uno o más identificadores del corpus"
    ),
    page: list[int] | None = typer.Option(
        None, "--page", help="Procesa solo páginas concretas de los documentos seleccionados"
    ),
    profile_path: Path | None = typer.Option(
        None, "--profile", help="Perfil YAML; por defecto config/extraction.yaml"
    ),
    force: bool = typer.Option(False, help="Genera otra versión aunque exista una equivalente"),
    device: str | None = typer.Option(
        None, "--device", help="Sobrescribe el dispositivo del perfil: auto, cpu o cuda"
    ),
    psm: int | None = typer.Option(
        None, "--psm", help="Sobrescribe el modo de segmentación Tesseract (0-13)"
    ),
    image_variant: str | None = typer.Option(
        None,
        "--image-variant",
        help="original, grayscale_autocontrast u otsu",
    ),
    created_by: str = typer.Option("local_user", help="Responsable de la corrida"),
    selection_policy: str = typer.Option(
        "if_unselected",
        "--selection-policy",
        help="never, if_unselected o replace para la selección canónica por página",
    ),
) -> None:
    """Ejecuta un backend de extracción sobre los derivados vigentes."""
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    selected_profile = profile_path or (project_root / "config" / "extraction.yaml")
    profile = load_extraction_profile(selected_profile)
    overrides = profile.model_dump()
    if device is not None:
        if device not in {"auto", "cpu", "cuda"}:
            raise typer.BadParameter("--device debe ser auto, cpu o cuda")
        overrides["device"] = device
    if psm is not None:
        if psm < 0 or psm > 13:
            raise typer.BadParameter("--psm debe estar entre 0 y 13")
        overrides["psm"] = psm
    if image_variant is not None:
        if image_variant not in {"original", "grayscale_autocontrast", "otsu"}:
            raise typer.BadParameter(
                "--image-variant debe ser original, grayscale_autocontrast u otsu"
            )
        overrides["image_variant"] = image_variant
    profile = type(profile).model_validate(overrides)
    doctor = extraction_doctor(profile)
    if not doctor.ready:
        for check in doctor.checks:
            if check.required and not check.ok:
                typer.echo(f"ERROR {check.name}: {check.detail}")
        raise typer.BadParameter("El entorno de extracción no está listo; ejecute extraction-doctor")
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = extract_documents(
                session,
                project_root=project_root,
                decisions=decisions,
                profile=profile,
                source_keys=set(source_key or []),
                selected_pages=set(page or []),
                force=force,
                created_by=created_by,
                selection_policy=selection_policy,
            )
    finally:
        engine.dispose()
    typer.echo(
        f"OK: {summary.objects_seen} objetos — corridas nuevas {summary.runs_created}, "
        f"reutilizadas {summary.runs_reused}, fallidas {summary.failed}; "
        f"páginas {summary.pages_processed}, objetos extraídos {summary.objects_created}, "
        f"caracteres {summary.characters_created}"
    )
    for warning in summary.warnings:
        typer.echo(f"⚠ {warning}")
    if summary.failed:
        raise typer.Exit(code=1)


@app.command("ocr-benchmark")
def ocr_benchmark_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str = typer.Option(..., "--source-key", help="Identificador del documento"),
    page: list[int] | None = typer.Option(
        None, "--page", help="Limita el benchmark a páginas concretas"
    ),
    profile_path: Path | None = typer.Option(
        None, "--profile", help="Perfil YAML; por defecto config/ocr_benchmark.yaml"
    ),
) -> None:
    """Compara PSM y variantes de imagen con Tesseract, sin cambiar la extracción vigente."""
    selected_profile = profile_path or (project_root / "config" / "ocr_benchmark.yaml")
    profile = load_ocr_benchmark_profile(selected_profile)
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = run_ocr_benchmark(
                session,
                project_root=project_root,
                source_key=source_key,
                profile=profile,
                pages=set(page or []),
            )
    finally:
        engine.dispose()
    typer.echo(f"OK: benchmark {summary.benchmark_id} — {len(summary.candidates)} candidatos")
    for candidate in summary.candidates[:10]:
        confidence = "-" if candidate.mean_confidence is None else f"{candidate.mean_confidence:.1f}"
        typer.echo(
            f"{candidate.candidate_id} | score {candidate.heuristic_score:.3f} | "
            f"conf {confidence} | palabras {candidate.word_count} | "
            f"caracteres {candidate.character_count}"
        )
    typer.echo(f"Salida: {summary.output_root}/summary.md")


@app.command("review-extraction")
def review_extraction_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str = typer.Option(..., "--source-key", help="Identificador del documento"),
    verdict: str = typer.Option(..., help="accepted, rejected, needs_review o unreviewed"),
    reviewed_by: str = typer.Option("local_user", help="Responsable de la revisión"),
    note: str | None = typer.Option(None, help="Observación breve"),
) -> None:
    """Marca la calidad de la extracción vigente sin borrar ninguna versión."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            run = review_current_extraction(
                session,
                source_key=source_key,
                verdict=verdict,
                reviewed_by=reviewed_by,
                note=note,
            )
    finally:
        engine.dispose()
    typer.echo(
        f"OK: extracción {run.id} de {source_key} marcada como {run.quality_status}"
    )


@app.command("extraction-history")
def extraction_history_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str | None = typer.Option(None, "--source-key"),
) -> None:
    """Lista todas las versiones de extracción, incluidas las rechazadas."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = extraction_history_rows(session, source_key=source_key)
    finally:
        engine.dispose()
    for row in rows:
        marker = "actual" if row.is_current else "histórica"
        typer.echo(
            f"{row.source_key} | {row.run_id} | {row.profile_key or '-'} | "
            f"{row.status} | calidad {row.quality_status} | {marker} | "
            f"páginas {row.pages} | objetos {row.objects} | caracteres {row.characters}"
        )
    typer.echo(f"Total: {len(rows)} corridas")


@app.command("select-extraction")
def select_extraction_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str = typer.Option(..., "--source-key"),
    profile_key: str | None = typer.Option(None, "--profile-key"),
    run_id: str | None = typer.Option(None, "--run-id"),
    page: list[int] | None = typer.Option(None, "--page"),
    selected_by: str = typer.Option("local_user", "--selected-by"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Selecciona la extracción canónica de una o más páginas."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            run, changed = select_extraction_pages(
                session,
                source_key=source_key,
                selected_by=selected_by,
                run_id=run_id,
                profile_key=profile_key,
                pages=set(page or []),
                note=note,
            )
    finally:
        engine.dispose()
    typer.echo(
        f"OK: {changed} página(s) seleccionadas desde {run.profile_key or run.id}"
    )


@app.command("restore-profile-pages")
def restore_profile_pages_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str = typer.Option(..., "--source-key"),
    profile_key: str = typer.Option(..., "--profile-key"),
    page: list[int] = typer.Option(..., "--page"),
    selected_by: str = typer.Option("local_user", "--selected-by"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Restaura páginas desde corridas históricas de un perfil estable."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            restored = restore_profile_page_selections(
                session,
                source_key=source_key,
                profile_key=profile_key,
                pages=set(page),
                selected_by=selected_by,
                note=note,
            )
    finally:
        engine.dispose()
    run_count = len({run_id for _, run_id in restored})
    typer.echo(
        f"OK: {len(restored)} página(s) restauradas desde {profile_key}; "
        f"corridas históricas utilizadas {run_count}"
    )


@app.command("selected-extraction-status")
def selected_extraction_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Muestra cobertura y perfiles seleccionados por página."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = selected_extraction_status_rows(session)
    finally:
        engine.dispose()
    for row in rows:
        total = "?" if row.page_count is None else str(row.page_count)
        missing = ",".join(map(str, row.missing_pages)) if row.missing_pages else "-"
        rejected = ",".join(map(str, row.rejected_pages)) if row.rejected_pages else "-"
        typer.echo(
            f"{row.source_key} | seleccionadas {row.selected_pages}/{total} | "
            f"faltantes {missing} | rechazadas {rejected} | "
            f"perfiles {', '.join(row.profiles) or '-'} | {row.title}"
        )
    typer.echo(f"Total: {len(rows)} documentos")


@app.command("extraction-status")
def extraction_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Muestra la extracción vigente de cada documento."""
    db_path = database_path(project_root)
    if not db_path.is_file():
        raise typer.BadParameter("La base todavía no existe; ejecute db-upgrade primero")
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            rows = extraction_status_rows(session)
    finally:
        engine.dispose()
    for row in rows:
        pages = "?" if row.page_count is None else str(row.page_count)
        typer.echo(
            f"{row.source_key} | {row.run_status or 'sin_extraccion'} | "
            f"{row.media_type} {pages} pág. | procesadas {row.pages} | "
            f"objetos {row.objects} | caracteres {row.characters} | "
            f"calidad {row.quality_status or '-'}"
            f"{'' if row.quality_score is None else f' ({row.quality_score:.3f})'} | "
            f"{row.profile_key or '-'} | {row.output_root or '-'} | {row.title}"
        )
    typer.echo(f"Total: {len(rows)} documentos")



@app.command("create-document-plan")
def create_document_plan_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str = typer.Option(..., "--source-key", help="Identificador del documento"),
    output: Path | None = typer.Option(None, "--output", help="Destino YAML del plan"),
    created_by: str = typer.Option("local_user", "--created-by"),
    sample_count: int = typer.Option(5, "--sample-count", min=1, max=12),
) -> None:
    """Crea un plan multipágina en borrador con páginas de benchmark representativas."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            plan = create_document_plan_template(
                session,
                source_key=source_key,
                created_by=created_by,
                sample_count=sample_count,
            )
    finally:
        engine.dispose()
    destination = output or (
        project_root / "config" / "document_plans" / f"{source_key}.yaml"
    )
    write_document_plan(destination, plan)
    typer.echo(
        f"OK: plan draft {plan.plan_key} — {plan.expected_page_count} páginas; "
        f"benchmark {','.join(map(str, plan.benchmark_pages))}"
    )
    typer.echo(f"Salida: {destination}")


@app.command("render-contact-sheets")
def render_contact_sheets_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str = typer.Option(..., "--source-key", help="Identificador del documento"),
    pages_per_sheet: int = typer.Option(12, "--pages-per-sheet", min=1, max=30),
    columns: int = typer.Option(3, min=1, max=6),
    thumb_width: int = typer.Option(420, "--thumb-width", min=100, max=1000),
) -> None:
    """Genera hojas de contacto a partir de los derivados de vista vigentes."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            results = render_contact_sheets(
                session,
                project_root=project_root,
                source_key=source_key,
                pages_per_sheet=pages_per_sheet,
                columns=columns,
                thumb_width=thumb_width,
            )
    finally:
        engine.dispose()
    for result in results:
        typer.echo(
            f"OK: hoja {result.sheet_number} | páginas "
            f"{result.pages[0]}-{result.pages[-1]} | {result.path}"
        )


@app.command("validate-document-plan")
def validate_document_plan_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    plan_path: Path = typer.Option(..., "--plan", help="Plan YAML"),
    require_ready: bool = typer.Option(False, "--require-ready"),
) -> None:
    """Valida rangos, cobertura, perfiles y plantillas regionales del plan."""
    plan = load_document_plan(plan_path)
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            validate_plan_against_catalog(
                session,
                project_root=project_root,
                plan=plan,
                require_ready=require_ready,
            )
    finally:
        engine.dispose()
    typer.echo(
        f"OK: {plan.plan_key} | {plan.status} | páginas asignadas "
        f"{len(plan.assigned_pages)}/{plan.expected_page_count} | partes {len(plan.parts)}"
    )


@app.command("import-document-plan")
def import_document_plan_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    plan_path: Path = typer.Option(..., "--plan", help="Plan YAML"),
) -> None:
    """Registra una versión del plan y sus partes documentales en SQLite."""
    plan = load_document_plan(plan_path)
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            result = import_document_plan(
                session,
                project_root=project_root,
                plan=plan,
                source_path=plan_path,
            )
    finally:
        engine.dispose()
    typer.echo(
        f"OK: plan {'reutilizado' if result.reused else 'importado'} {result.plan_id} | "
        f"asignaciones {result.assignments} | partes {result.parts}"
    )


@app.command("benchmark-plan-sample")
def benchmark_plan_sample_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    plan_path: Path = typer.Option(..., "--plan", help="Plan YAML"),
    profile_path: Path | None = typer.Option(
        None, "--profile", help="Perfil benchmark; por defecto config/ocr_benchmark.yaml"
    ),
) -> None:
    """Ejecuta el benchmark OCR solamente en las páginas representativas del plan."""
    plan = load_document_plan(plan_path)
    selected_profile = profile_path or (project_root / "config" / "ocr_benchmark.yaml")
    profile = load_ocr_benchmark_profile(selected_profile)
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            validate_plan_against_catalog(session, project_root=project_root, plan=plan)
            summary = run_ocr_benchmark(
                session,
                project_root=project_root,
                source_key=plan.source_key,
                profile=profile,
                pages=set(plan.benchmark_pages),
            )
    finally:
        engine.dispose()
    typer.echo(
        f"OK: benchmark {summary.benchmark_id} — {len(summary.candidates)} candidatos "
        f"en páginas {','.join(map(str, plan.benchmark_pages))}"
    )
    typer.echo(f"Salida: {summary.output_root}/summary.md")


@app.command("execute-document-plan")
def execute_document_plan_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    plan_path: Path = typer.Option(..., "--plan", help="Plan YAML listo"),
    created_by: str = typer.Option("local_user", "--created-by"),
    force: bool = typer.Option(False, help="Fuerza nuevas corridas en vez de reutilizar"),
) -> None:
    """Ejecuta cada grupo OCR/regional y actualiza la selección canónica por página."""
    plan = load_document_plan(plan_path)
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = execute_document_plan(
                session,
                project_root=project_root,
                decisions=decisions,
                plan=plan,
                plan_path=plan_path,
                created_by=created_by,
                force=force,
            )
    finally:
        engine.dispose()
    typer.echo(
        f"OK: plan {summary.plan_id} | OCR {summary.ocr_groups} grupos | "
        f"regiones {summary.region_groups} | manuales {summary.manual_pages} | "
        f"omitidas {summary.skipped_pages} | corridas nuevas {summary.runs_created}, "
        f"reutilizadas {summary.runs_reused}, fallidas {summary.failed} | "
        f"páginas procesadas {summary.pages_processed}"
    )
    for warning in summary.warnings:
        typer.echo(f"⚠ {warning}")
    if summary.manifest_path:
        typer.echo(f"Manifest: {summary.manifest_path}")
    if summary.failed:
        raise typer.Exit(code=1)


@app.command("document-plan-status")
def document_plan_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Muestra el plan vigente, su cobertura y sus modos por documento."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = plan_status_rows(session)
    finally:
        engine.dispose()
    for row in rows:
        modes = ",".join(f"{key}:{value}" for key, value in row.modes.items()) or "-"
        typer.echo(
            f"{row.source_key} | {row.status or 'sin_plan'} | {row.plan_key or '-'} | "
            f"asignadas {row.assigned_pages}/{row.page_count} | pendientes {row.pending_pages} | "
            f"partes {row.parts} | modos {modes} | {row.title}"
        )
    typer.echo(f"Total: {len(rows)} documentos")

@app.command("document-parts")
def document_parts_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str | None = typer.Option(None, "--source-key", help="Filtrar por documento"),
) -> None:
    """Muestra documentos internos y distingue orden físico de orden lógico."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = document_part_status_rows(session, source_key=source_key)
    finally:
        engine.dispose()
    for row in rows:
        physical = ",".join(map(str, row.physical_pages))
        logical = ",".join(map(str, row.logical_pages))
        reordered = " | reordenado" if row.physical_pages != row.logical_pages else ""
        typer.echo(
            f"{row.source_key} | {row.part_key} | {row.status} | {row.part_type} | "
            f"físicas {physical} | lógicas {logical}{reordered} | {row.title}"
        )
        if row.notes:
            typer.echo(f"    {row.notes}")
    typer.echo(f"Total: {len(rows)} partes")


@app.command("validate-region-template")
def validate_region_template_command(
    path: Path = typer.Argument(..., help="Plantilla YAML de regiones"),
    decisions_path: Path = typer.Option(
        Path("config/decisions.yaml"), "--decisions", help="Decisiones del proyecto"
    ),
) -> None:
    """Valida regiones, coordenadas, modos OCR/manual y tipos de objeto."""
    template = load_region_template(path)
    decisions = load_decisions(decisions_path)
    validate_region_template(template, decisions)
    pages = sorted({item.page for item in template.regions})
    typer.echo(
        f"OK: {template.template_key} — {len(template.regions)} regiones, "
        f"páginas {', '.join(map(str, pages))}"
    )


@app.command("render-regions")
def render_regions_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    template_path: Path = typer.Option(..., "--template", help="Plantilla YAML de regiones"),
) -> None:
    """Dibuja las regiones sobre el derivado de vista sin modificarlo."""
    template = load_region_template(template_path)
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    validate_region_template(template, decisions)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            results = render_region_template(
                session, project_root=project_root, template=template
            )
    finally:
        engine.dispose()
    for result in results:
        typer.echo(f"OK: página {result.page} -> {result.path}")


@app.command("extract-regions")
def extract_regions_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    template_path: Path = typer.Option(..., "--template", help="Plantilla YAML de regiones"),
    created_by: str = typer.Option("local_user", "--created-by"),
    selection_policy: str = typer.Option(
        "replace", "--selection-policy", help="never, if_unselected o replace"
    ),
    force: bool = typer.Option(False, help="Crea otra corrida aunque exista una equivalente"),
) -> None:
    """Extrae zonas OCR y registra sellos/manuscritos como regiones manuales."""
    upgrade_database(project_root)
    template = load_region_template(template_path)
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    validate_region_template(template, decisions)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = extract_regions(
                session,
                project_root=project_root,
                decisions=decisions,
                template=template,
                created_by=created_by,
                selection_policy=selection_policy,
                force=force,
            )
    finally:
        engine.dispose()
    typer.echo(
        "OK: "
        f"corridas nuevas {summary.runs_created}, reutilizadas {summary.runs_reused}, "
        f"fallidas {summary.failed}; páginas {summary.pages_processed}, "
        f"objetos {summary.objects_created}, caracteres {summary.characters_created}"
    )
    for warning in summary.warnings:
        typer.echo(f"⚠ {warning}")


@app.command("region-status")
def region_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str | None = typer.Option(None, "--source-key"),
) -> None:
    """Lista las regiones de la extracción vigente y su estado."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = region_status_rows(session, source_key=source_key)
    finally:
        engine.dispose()
    for row in rows:
        typer.echo(
            f"{row.source_key} | pág. {row.page} | {row.region_key} | {row.mode} | "
            f"{row.object_type} | {row.status} | objetos {row.objects} | "
            f"caracteres {row.characters} | {row.label}"
        )
        if row.warning:
            typer.echo(f"    ⚠ {row.warning}")
    typer.echo(f"Total: {len(rows)} regiones")


@app.command("editor-bootstrap")
def editor_bootstrap_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: list[str] | None = typer.Option(None, "--source-key"),
    page: list[int] | None = typer.Option(None, "--page"),
    created_by: str = typer.Option("local_user", "--created-by"),
) -> None:
    """Crea la capa editable desde las extracciones seleccionadas sin tocar el OCR."""
    upgrade_database(project_root)
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by=created_by,
                source_keys=set(source_key or []),
                pages=set(page or []),
            )
    finally:
        engine.dispose()
    typer.echo(
        "OK: "
        f"documentos {summary.documents_seen} | páginas nuevas {summary.pages_created}, "
        f"reutilizadas {summary.pages_reused}, desactualizadas {summary.pages_stale} | "
        f"objetos {summary.objects_created} | revisiones {summary.revisions_created}"
    )
    for warning in summary.warnings:
        typer.echo(f"⚠ {warning}")


@app.command("editor-status")
def editor_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Muestra cobertura editable, objetos, revisiones y cambios de selección OCR."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = editing_status_rows(session)
    finally:
        engine.dispose()
    for row in rows:
        total = "?" if row.page_count is None else str(row.page_count)
        stale = ",".join(map(str, row.stale_pages)) if row.stale_pages else "-"
        typer.echo(
            f"{row.source_key} | editables {row.editable_pages}/{total} | "
            f"seleccionadas OCR {row.selected_pages}/{total} | desactualizadas {stale} | "
            f"objetos activos {row.active_objects}, eliminados {row.deleted_objects} | "
            f"revisiones {row.revisions} | {row.title}"
        )
    typer.echo(f"Total: {len(rows)} documentos")


@app.command("editable-objects")
def editable_objects_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str = typer.Option(..., "--source-key"),
    page: int | None = typer.Option(None, "--page"),
    include_deleted: bool = typer.Option(False, "--include-deleted"),
    full_text: bool = typer.Option(False, "--full-text"),
) -> None:
    """Lista IDs, revisiones y texto actual para preparar correcciones."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = editable_object_rows(
                session,
                source_key=source_key,
                page=page,
                include_deleted=include_deleted,
            )
    finally:
        engine.dispose()
    for row in rows:
        text = row.text.replace("\n", " ↵ ")
        if not full_text and len(text) > 120:
            text = text[:117] + "..."
        part = f" | parte {row.document_part_key}" if row.document_part_key else ""
        typer.echo(
            f"{row.object_id} | pág. {row.page} | orden {row.order_index} | "
            f"{row.object_type} | {row.lifecycle_status} | rev {row.revision_number}"
            f"{part} | {text}"
        )
    typer.echo(f"Total: {len(rows)} objetos")


def _resolve_text_input(text: str | None, text_file: Path | None) -> str | None:
    if text is not None and text_file is not None:
        raise typer.BadParameter("Use --text o --text-file, no ambos")
    if text_file is not None:
        if not text_file.exists():
            raise typer.BadParameter(
                f"El archivo indicado en --text-file no existe: {text_file}"
            )
        if not text_file.is_file():
            raise typer.BadParameter(
                f"La ruta indicada en --text-file no es un archivo: {text_file}"
            )
        try:
            return text_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise typer.BadParameter(
                f"El archivo de texto no está codificado como UTF-8: {text_file}"
            ) from exc
        except OSError as exc:
            raise typer.BadParameter(
                f"No se pudo leer --text-file {text_file}: {exc}"
            ) from exc
    return text


def _validate_uuid_option(value: str, *, option_name: str) -> str:
    try:
        UUID(value)
    except (ValueError, AttributeError) as exc:
        raise typer.BadParameter(
            f"{option_name} debe ser un UUID real obtenido con editable-objects; "
            f"se recibió: {value}"
        ) from exc
    return value


@app.command("edit-object")
def edit_object_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    object_id: str = typer.Option(..., "--object-id"),
    base_revision: int = typer.Option(..., "--base-revision", min=1),
    edited_by: str = typer.Option("local_user", "--edited-by"),
    text: str | None = typer.Option(None, "--text"),
    text_file: Path | None = typer.Option(None, "--text-file"),
    object_type: str | None = typer.Option(None, "--object-type"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Crea una nueva revisión de texto o tipo con control de concurrencia."""
    object_id = _validate_uuid_option(object_id, option_name="--object-id")
    value = _resolve_text_input(text, text_file)
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            obj = update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=base_revision,
                edited_by=edited_by,
                text=value,
                object_type=object_type,
                note=note,
            )
    finally:
        engine.dispose()
    typer.echo(f"OK: {obj.id} actualizado a revisión {obj.revision_number}")


@app.command("add-editable-object")
def add_editable_object_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str = typer.Option(..., "--source-key"),
    page: int = typer.Option(..., "--page", min=1),
    object_type: str = typer.Option("paragraph", "--object-type"),
    created_by: str = typer.Option("local_user", "--created-by"),
    text: str | None = typer.Option(None, "--text"),
    text_file: Path | None = typer.Option(None, "--text-file"),
    after_object_id: str | None = typer.Option(None, "--after-object-id"),
    before_object_id: str | None = typer.Option(None, "--before-object-id"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Agrega una transcripción u objeto faltante sin alterar la extracción de origen."""
    value = _resolve_text_input(text, text_file)
    if value is None:
        raise typer.BadParameter("Debe indicarse --text o --text-file")
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            obj = add_editable_object(
                session,
                decisions=decisions,
                source_key=source_key,
                page=page,
                object_type=object_type,
                text=value,
                created_by=created_by,
                after_object_id=after_object_id,
                before_object_id=before_object_id,
                note=note,
            )
    finally:
        engine.dispose()
    typer.echo(
        f"OK: objeto {obj.id} agregado en página {obj.page_number}, "
        f"orden {obj.current_order_index}, revisión 1"
    )


@app.command("delete-editable-object")
def delete_editable_object_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    object_id: str = typer.Option(..., "--object-id"),
    base_revision: int = typer.Option(..., "--base-revision", min=1),
    deleted_by: str = typer.Option("local_user", "--deleted-by"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Marca un objeto como eliminado; no borra su historial."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            obj = set_editable_object_lifecycle(
                session,
                object_id=object_id,
                expected_revision=base_revision,
                lifecycle_status="deleted",
                changed_by=deleted_by,
                note=note,
            )
    finally:
        engine.dispose()
    typer.echo(f"OK: {obj.id} eliminado lógicamente en revisión {obj.revision_number}")


@app.command("restore-editable-object")
def restore_editable_object_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    object_id: str = typer.Option(..., "--object-id"),
    base_revision: int = typer.Option(..., "--base-revision", min=1),
    restored_by: str = typer.Option("local_user", "--restored-by"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Restaura un objeto eliminado mediante una nueva revisión."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            obj = set_editable_object_lifecycle(
                session,
                object_id=object_id,
                expected_revision=base_revision,
                lifecycle_status="active",
                changed_by=restored_by,
                note=note,
            )
    finally:
        engine.dispose()
    typer.echo(f"OK: {obj.id} restaurado en revisión {obj.revision_number}")


@app.command("revert-editable-object")
def revert_editable_object_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    object_id: str = typer.Option(..., "--object-id"),
    target_revision: int = typer.Option(..., "--target-revision", min=1),
    base_revision: int = typer.Option(..., "--base-revision", min=1),
    reverted_by: str = typer.Option("local_user", "--reverted-by"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Copia una revisión histórica como una nueva revisión actual."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            obj = revert_editable_object(
                session,
                object_id=object_id,
                target_revision=target_revision,
                expected_revision=base_revision,
                reverted_by=reverted_by,
                note=note,
            )
    finally:
        engine.dispose()
    typer.echo(
        f"OK: {obj.id} restaurado desde revisión {target_revision}; "
        f"revisión actual {obj.revision_number}"
    )


@app.command("object-history")
def object_history_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    object_id: str = typer.Option(..., "--object-id"),
    full_text: bool = typer.Option(False, "--full-text"),
) -> None:
    """Muestra el historial append-only de un objeto editable."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = object_revision_rows(session, object_id=object_id)
    finally:
        engine.dispose()
    for row in rows:
        text = row.text.replace("\n", " ↵ ")
        if not full_text and len(text) > 120:
            text = text[:117] + "..."
        typer.echo(
            f"rev {row.revision_number} | {row.operation} | base {row.base_revision_number or '-'} | "
            f"{row.lifecycle_status} | {row.object_type} | orden {row.order_index} | "
            f"{row.created_by} | {row.created_at.isoformat()} | {text}"
        )
        if row.note:
            typer.echo(f"    {row.note}")
    typer.echo(f"Total: {len(rows)} revisiones")


@app.command("export-editable-jsonl")
def export_editable_jsonl_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str = typer.Option(..., "--source-key"),
    destination: Path | None = typer.Option(None, "--destination"),
) -> None:
    """Exporta estado editable e historial en JSONL sin usarlo como base canónica."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = export_editable_layer(
                session,
                project_root=project_root,
                source_key=source_key,
                destination=destination,
            )
    finally:
        engine.dispose()
    typer.echo(
        f"OK: objetos {summary.object_count}, revisiones {summary.revision_count} | "
        f"salida {summary.output_root}"
    )


@app.command("rebuild-search-index")
def rebuild_search_index_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Reconstruye el índice FTS5 de la capa editable."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = rebuild_search_index(session)
    finally:
        engine.dispose()
    typer.echo(
        f"OK: índice reconstruido | objetos {summary.object_count} | "
        f"generación {summary.indexed_generation} | {summary.indexed_at}"
    )


@app.command("search-index-status")
def search_index_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Muestra si el índice de búsqueda refleja la capa editable actual."""
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            status = search_index_status(session)
    finally:
        engine.dispose()
    state = "actualizado" if status.is_current else "pendiente de reconstrucción"
    typer.echo(
        f"{state} | datos {status.dirty_generation} | índice {status.indexed_generation} | "
        f"fecha {status.indexed_at or '-'}"
    )


@app.command("search-editable")
def search_editable_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    query: str = typer.Argument(..., help="Palabras o frase que se desea buscar"),
    match_mode: str = typer.Option("all", "--mode", help="all, any o phrase"),
    field: list[str] | None = typer.Option(None, "--field", help="Campo repetible"),
    source_key: list[str] | None = typer.Option(None, "--source-key"),
    object_type: list[str] | None = typer.Option(None, "--object-type"),
    review_status: list[str] | None = typer.Option(None, "--review-status"),
    page_status: list[str] | None = typer.Option(None, "--page-status"),
    document_part: list[str] | None = typer.Option(None, "--document-part"),
    tag_kind: list[str] | None = typer.Option(None, "--tag-kind"),
    temporal_start: str | None = typer.Option(None, "--temporal-start", help="Inicio ISO YYYY-MM-DD"),
    temporal_end: str | None = typer.Option(None, "--temporal-end", help="Final ISO YYYY-MM-DD"),
    temporal_include_undated: bool = typer.Option(False, "--temporal-include-undated"),
    include_deleted: bool = typer.Option(False, "--include-deleted"),
    partial_words: bool = typer.Option(
        False, "--partial-words", help="Permite coincidencias dentro de palabras; mínimo 3 caracteres"
    ),
    limit: int = typer.Option(50, "--limit", min=1, max=500),
) -> None:
    """Busca texto y anotaciones en todos los objetos editables."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = search_editable_objects(
                session,
                query=query,
                match_mode=match_mode,
                fields=field or SEARCH_FIELDS,
                source_keys=source_key or (),
                object_types=object_type or (),
                object_review_statuses=review_status or (),
                page_review_statuses=page_status or (),
                lifecycle_statuses=("active", "deleted") if include_deleted else ("active",),
                document_part_keys=document_part or (),
                tag_kinds=tag_kind or (),
                temporal_start=_parse_temporal_cli_date(temporal_start, "--temporal-start"),
                temporal_end=_parse_temporal_cli_date(temporal_end, "--temporal-end"),
                temporal_include_undated=temporal_include_undated,
                partial_words=partial_words,
                limit=limit,
            )
    except (ValueError, RuntimeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    for row in rows:
        snippet = row.snippet.replace("[[HIT]]", "[").replace("[[/HIT]]", "]")
        part = f" | parte {row.document_part_key}" if row.document_part_key else ""
        typer.echo(
            f"{row.source_key} | pág. {row.page_number} | objeto {row.order_index + 1} | "
            f"{row.object_type} | {row.match_scope}{part}"
        )
        typer.echo(f"    {snippet}")
    typer.echo(f"Total: {len(rows)} resultados")


@app.command("exchange-init")
def exchange_init_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    workspace_name: str = typer.Option(..., "--workspace-name", help="Nombre de esta copia local"),
    created_by: str = typer.Option("local_user", "--created-by"),
    initial_checkpoint: str | None = typer.Option(
        "baseline", "--initial-checkpoint", help="Etiqueta inicial; use vacío para no crearla"
    ),
) -> None:
    """Asigna identidad a esta copia y crea un checkpoint de referencia."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            workspace = ensure_exchange_workspace(
                session, workspace_name=workspace_name, changed_by=created_by
            )
            checkpoint = None
            if initial_checkpoint and initial_checkpoint.strip():
                existing = {row.label for row in checkpoint_rows(session)}
                if initial_checkpoint.strip() not in existing:
                    checkpoint = create_exchange_checkpoint(
                        session,
                        label=initial_checkpoint.strip(),
                        created_by=created_by,
                        note="Estado local de referencia al inicializar el intercambio offline",
                    )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"OK: copia {workspace.workspace_name} | id {workspace.id}")
    if checkpoint is not None:
        typer.echo(
            f"Checkpoint: {checkpoint.label} | secuencia {checkpoint.sequence_number} | "
            f"estado {checkpoint.state_sha256}"
        )


@app.command("exchange-status")
def exchange_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Muestra identidad, secuencia y cambios pendientes de exportación."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            status = exchange_status(session)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"Copia: {status.workspace_name} | {status.workspace_id}")
    typer.echo(f"Proyecto: {status.project_id}")
    typer.echo(
        f"Secuencia actual: {status.current_sequence} | checkpoints {status.checkpoint_count} | "
        f"bundles exportados {status.exported_bundle_count}"
    )
    typer.echo(
        f"Último checkpoint: {status.last_checkpoint_label or '-'} "
        f"({status.last_checkpoint_sequence if status.last_checkpoint_sequence is not None else '-'}) | "
        f"eventos posteriores {status.pending_event_count}"
    )


@app.command("exchange-checkpoint")
def exchange_checkpoint_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    label: str = typer.Option(..., "--label"),
    created_by: str = typer.Option("local_user", "--created-by"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Crea un checkpoint verificable del estado editable actual."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            row = create_exchange_checkpoint(
                session, label=label, created_by=created_by, note=note
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: {row.label} | id {row.id} | secuencia {row.sequence_number} | "
        f"estado {row.state_sha256}"
    )


@app.command("exchange-checkpoints")
def exchange_checkpoints_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Lista checkpoints disponibles como base para un bundle."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = checkpoint_rows(session)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    for row in rows:
        typer.echo(
            f"{row.label} | {row.checkpoint_id} | secuencia {row.sequence_number} | "
            f"{row.created_by} | {row.created_at.isoformat()} | {row.state_sha256[:12]}"
        )
        if row.note:
            typer.echo(f"    {row.note}")
    typer.echo(f"Total: {len(rows)} checkpoints")


@app.command("exchange-export-bundle")
def exchange_export_bundle_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    since: str | None = typer.Option(None, "--since", help="ID o etiqueta del checkpoint; por defecto el último"),
    created_by: str = typer.Option("local_user", "--created-by"),
    destination: Path | None = typer.Option(None, "--destination"),
) -> None:
    """Exporta eventos posteriores a un checkpoint en un ZIP verificable."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = export_change_bundle(
                session,
                project_root=project_root.resolve(),
                checkpoint_ref=since,
                created_by=created_by,
                destination=destination,
            )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    if summary.event_count:
        range_text = f"secuencias {summary.base_sequence + 1}-{summary.last_sequence}"
    else:
        range_text = f"sin eventos nuevos; secuencia {summary.last_sequence}"
    typer.echo(
        f"OK: bundle {summary.bundle_id} | eventos {summary.event_count} | {range_text}"
    )
    typer.echo(f"Archivo: {summary.output_path}")
    typer.echo(f"SHA-256: {summary.bundle_sha256}")
    typer.echo(
        f"Nuevo checkpoint: {summary.next_checkpoint_label} | {summary.next_checkpoint_id}"
    )


@app.command("exchange-inspect-bundle")
def exchange_inspect_bundle_command(
    bundle: Path = typer.Argument(..., help="Bundle ZIP que se desea validar"),
) -> None:
    """Valida estructura, contratos y checksums sin modificar ninguna base."""
    try:
        result = inspect_change_bundle(bundle)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    manifest = result.manifest
    typer.echo(f"OK: bundle {manifest.bundle_id} | SHA-256 {result.bundle_sha256}")
    typer.echo(
        f"Proyecto {manifest.project_id} | copia {manifest.source_workspace_name} "
        f"({manifest.source_workspace_id})"
    )
    typer.echo(
        f"Base {manifest.base_checkpoint_label} sec. {manifest.base_sequence} | "
        f"última {manifest.last_sequence} | eventos {result.event_count}"
    )
    typer.echo(
        f"Archive Workbench {manifest.app_version} | DB {manifest.database_revision} | "
        f"creado por {manifest.created_by}"
    )
    for warning in result.warnings:
        typer.echo(f"⚠ {warning}")


@app.command("exchange-fork-copy")
def exchange_fork_copy_command(
    project_root: Path = typer.Argument(..., help="Raíz de la copia duplicada"),
    workspace_name: str = typer.Option(..., "--workspace-name"),
    created_by: str = typer.Option("local_user", "--created-by"),
    checkpoint_label: str = typer.Option("baseline", "--checkpoint-label"),
    confirm_copy: bool = typer.Option(
        False,
        "--confirm-copy",
        help="Confirma que esta carpeta es una copia y no la instancia principal",
    ),
) -> None:
    """Asigna una identidad nueva a una carpeta duplicada del proyecto."""
    if not confirm_copy:
        raise typer.BadParameter(
            "Use --confirm-copy únicamente después de duplicar físicamente el proyecto"
        )
    initialize_project(project_root)
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = fork_exchange_workspace(
                session,
                workspace_name=workspace_name,
                created_by=created_by,
                checkpoint_label=checkpoint_label,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: copia reidentificada | {summary.previous_workspace_name} "
        f"({summary.previous_workspace_id}) -> {summary.workspace_name} "
        f"({summary.workspace_id})"
    )
    typer.echo(
        f"Checkpoint: {summary.checkpoint_label} | {summary.checkpoint_id} | "
        f"estado {summary.state_sha256}"
    )
    typer.echo("El estado editable y el OCR no fueron modificados.")


@app.command("exchange-dry-run")
def exchange_dry_run_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    bundle: Path = typer.Argument(..., help="Bundle ZIP recibido"),
    assessed_by: str = typer.Option("local_user", "--assessed-by"),
    copy_to_incoming: bool = typer.Option(
        True, "--copy/--no-copy", help="Conservar una copia dentro de exchange/incoming"
    ),
) -> None:
    """Clasifica un bundle recibido sin aplicar cambios al estado editable."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = dry_run_change_bundle(
                session,
                project_root=project_root.resolve(),
                bundle_path=bundle,
                assessed_by=assessed_by,
                copy_to_incoming=copy_to_incoming,
            )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    repeated = " | reevaluado" if summary.repeated_assessment else ""
    typer.echo(
        f"OK: dry-run {summary.bundle_id}{repeated} | origen "
        f"{summary.source_workspace_name} ({summary.source_workspace_id})"
    )
    typer.echo(
        f"Base común: {summary.common_checkpoint_label or '-'} | "
        f"{summary.base_match_status} | estado {summary.overall_status}"
    )
    typer.echo(
        "Eventos: "
        f"aplicables {summary.counts.get('apply', 0)} | "
        f"duplicados {summary.counts.get('duplicate', 0)} | "
        f"revisables {summary.counts.get('review', 0)} | "
        f"conflictos {summary.counts.get('conflict', 0)}"
    )
    typer.echo(f"Reporte: {summary.report_markdown_path}")
    typer.echo(f"JSON: {summary.report_json_path}")
    typer.echo("No se aplicó ningún cambio al estado editable.")


@app.command("exchange-incoming")
def exchange_incoming_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Lista bundles recibidos y su última evaluación dry-run."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = incoming_bundle_rows(session)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    for row in rows:
        counts = row.counts
        typer.echo(
            f"{row.bundle_id} | {row.source_workspace_name} | {row.status} | "
            f"base {row.base_match_status} | eventos {row.event_count} | "
            f"A {counts.get('apply', 0)} D {counts.get('duplicate', 0)} "
            f"R {counts.get('review', 0)} C {counts.get('conflict', 0)}"
        )
        if row.report_markdown_path:
            typer.echo(f"    {row.report_markdown_path}")
    typer.echo(f"Total: {len(rows)} bundles recibidos")


@app.command("exchange-conflicts")
def exchange_conflicts_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    bundle: str = typer.Argument(..., help="ID del bundle o ruta al ZIP evaluado"),
) -> None:
    """Muestra base, valor local, valor recibido y resolución de cada conflicto."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = conflict_field_rows(session, bundle)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    if not rows:
        typer.echo("No hay eventos revisables o conflictivos.")
        return
    previous: str | None = None
    for row in rows:
        if row.event_id != previous:
            typer.echo(
                f"Evento {row.event_id} | sec. {row.source_sequence_number} | "
                f"{row.disposition} | {row.entity_type}/{row.entity_id} | {row.operation}"
            )
            previous = row.event_id
        typer.echo(f"    campo {row.field_name}")
        typer.echo(f"      base:     {row.base_value!r}")
        typer.echo(f"      local:    {row.local_value!r}")
        typer.echo(f"      recibido: {row.incoming_value!r}")
        if row.choice:
            typer.echo(
                f"      decisión: {row.choice} -> {row.resolved_value!r} "
                f"({row.resolved_by or '-'})"
            )
    typer.echo(f"Total: {len(rows)} campos")


@app.command("exchange-resolve-field")
def exchange_resolve_field_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    bundle: str = typer.Argument(..., help="ID del bundle o ruta al ZIP evaluado"),
    event_id: str = typer.Option(..., "--event-id"),
    field_name: str = typer.Option(..., "--field"),
    choice: str = typer.Option(..., "--choice", help="local, incoming o custom"),
    value_text: str | None = typer.Option(None, "--value-text"),
    value_json: str | None = typer.Option(None, "--value-json"),
    value_file: Path | None = typer.Option(None, "--value-file"),
    resolved_by: str = typer.Option("local_user", "--resolved-by"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Resuelve explícitamente un campo conflictivo o revisable."""
    provided = [value_text is not None, value_json is not None, value_file is not None]
    if sum(provided) > 1:
        raise typer.BadParameter("Use solo uno de --value-text, --value-json o --value-file")
    custom_value = None
    if choice.strip().lower() == "custom":
        if not any(provided):
            raise typer.BadParameter("La elección custom requiere un valor")
        try:
            if value_text is not None:
                custom_value = value_text
            elif value_json is not None:
                custom_value = json.loads(value_json)
            else:
                assert value_file is not None
                if not value_file.is_file():
                    raise typer.BadParameter(f"No existe el archivo: {value_file}")
                custom_value = json.loads(value_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"JSON inválido: {exc}") from exc
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            row = save_conflict_resolution(
                session,
                bundle_ref=bundle,
                event_id=event_id,
                field_name=field_name,
                choice=choice,
                custom_value=custom_value,
                resolved_by=resolved_by,
                note=note,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: evento {row.incoming_event_id} | campo {row.field_name} | "
        f"{row.choice} -> {row.resolved_value_json!r}"
    )


@app.command("exchange-resolve-event")
def exchange_resolve_event_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    bundle: str = typer.Argument(..., help="ID del bundle o ruta al ZIP evaluado"),
    event_id: str = typer.Option(..., "--event-id"),
    choice: str = typer.Option(..., "--choice", help="local o incoming"),
    resolved_by: str = typer.Option("local_user", "--resolved-by"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Resuelve todos los campos pendientes de un evento con una misma elección."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            row = resolve_conflict_fields_bulk(
                session,
                bundle_ref=bundle,
                event_id=event_id,
                choice=choice,
                resolved_by=resolved_by,
                note=note,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: evento {event_id} | elección {row.choice} | "
        f"campos resueltos {row.resolved_field_count} | "
        f"coincidencias automáticas {row.auto_matched_field_count}"
    )


@app.command("exchange-resolve-all")
def exchange_resolve_all_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    bundle: str = typer.Argument(..., help="ID del bundle o ruta al ZIP evaluado"),
    choice: str = typer.Option(..., "--choice", help="local o incoming"),
    resolved_by: str = typer.Option("local_user", "--resolved-by"),
    note: str | None = typer.Option(None, "--note"),
    confirm_all: bool = typer.Option(False, "--confirm-all"),
) -> None:
    """Resuelve todos los campos pendientes del bundle con una misma elección."""
    if not confirm_all:
        raise typer.BadParameter("Use --confirm-all para resolver todo el bundle")
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            row = resolve_conflict_fields_bulk(
                session,
                bundle_ref=bundle,
                choice=choice,
                resolved_by=resolved_by,
                note=note,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: bundle {row.bundle_id} | elección {row.choice} | "
        f"eventos {row.event_count} | campos resueltos {row.resolved_field_count} | "
        f"coincidencias automáticas {row.auto_matched_field_count}"
    )


@app.command("exchange-skip-event")
def exchange_skip_event_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    bundle: str = typer.Argument(..., help="ID del bundle o ruta al ZIP evaluado"),
    event_id: str = typer.Option(..., "--event-id"),
    resolved_by: str = typer.Option("local_user", "--resolved-by"),
    note: str | None = typer.Option(None, "--note"),
    confirm_skip: bool = typer.Option(False, "--confirm-skip"),
) -> None:
    """Descarta explícitamente un evento recibido conservando el estado local."""
    if not confirm_skip:
        raise typer.BadParameter("Use --confirm-skip para descartar el evento recibido")
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            row = skip_conflicted_event(
                session,
                bundle_ref=bundle,
                event_id=event_id,
                resolved_by=resolved_by,
                note=note,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"OK: evento {row.incoming_event_id} descartado; se conserva la versión local")


@app.command("exchange-resolution-status")
def exchange_resolution_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    bundle: str = typer.Argument(..., help="ID del bundle o ruta al ZIP evaluado"),
) -> None:
    """Resume el avance de la resolución humana de un bundle."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            row = resolution_status(session, bundle)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"{row.bundle_id} | {row.overall_status} | eventos {row.event_count} | "
        f"campos {row.resolved_field_count}/{row.field_count} | "
        f"coincidencias automáticas {row.auto_matched_field_count} | "
        f"eventos descartados {row.skipped_event_count} | "
        f"pendientes {row.unresolved_field_count}"
    )


@app.command("exchange-finalize-resolutions")
def exchange_finalize_resolutions_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    bundle: str = typer.Argument(..., help="ID del bundle o ruta al ZIP evaluado"),
    finalized_by: str = typer.Option("local_user", "--finalized-by"),
    confirm_resolutions: bool = typer.Option(False, "--confirm-resolutions"),
) -> None:
    """Cierra las decisiones y habilita la aplicación transaccional del bundle."""
    if not confirm_resolutions:
        raise typer.BadParameter(
            "Use --confirm-resolutions después de revisar todas las decisiones"
        )
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            row = finalize_bundle_resolutions(
                session,
                bundle_ref=bundle,
                finalized_by=finalized_by,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    prefix = "OK: ya estaba finalizado" if row.already_finalized else "OK: finalizado"
    typer.echo(
        f"{prefix} bundle {row.bundle_id} | {row.overall_status} | "
        f"campos resueltos {row.resolved_field_count}/{row.field_count} | "
        f"coincidencias automáticas {row.auto_matched_field_count} | "
        f"eventos descartados {row.skipped_event_count}"
    )


def _parse_temporal_cli_date(value: str | None, option_name: str) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise typer.BadParameter(
            f"{option_name} debe usar formato ISO YYYY-MM-DD"
        ) from exc


def _single_project_id(session) -> str:
    projects = session.scalars(select(Project).order_by(Project.created_at, Project.id)).all()
    if not projects:
        raise ValueError("El proyecto no está registrado en la base")
    if len(projects) > 1:
        raise ValueError("La base contiene más de un proyecto; use la interfaz para seleccionarlo")
    return str(projects[0].id)


@app.command("entity-list")
@app.command("authority-list")
def authority_list_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    query: str = typer.Option("", "--query", "-q"),
    entity_type: str | None = typer.Option(None, "--type"),
    temporal_start: str | None = typer.Option(None, "--temporal-start"),
    temporal_end: str | None = typer.Option(None, "--temporal-end"),
    temporal_include_undated: bool = typer.Option(False, "--temporal-include-undated"),
    include_inactive: bool = typer.Option(False, "--include-inactive"),
) -> None:
    """Lista entidades canónicas, alias y cantidad de menciones."""
    if entity_type is not None and entity_type not in AUTHORITY_TYPES:
        raise typer.BadParameter("Tipo inválido: " + entity_type)
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = authority_rows(
                session,
                project_id=_single_project_id(session),
                query=query,
                entity_types=(entity_type,) if entity_type else (),
                lifecycle_statuses=("active", "inactive") if include_inactive else ("active",),
                temporal_start=_parse_temporal_cli_date(temporal_start, "--temporal-start"),
                temporal_end=_parse_temporal_cli_date(temporal_end, "--temporal-end"),
                include_undated=temporal_include_undated,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    for row in rows:
        aliases = ", ".join(alias.alias for alias in row.aliases) or "-"
        typer.echo(
            f"{row.authority_id} | {row.entity_type} | {row.preferred_name} | "
            f"{row.review_status} | rev. {row.revision} | menciones {row.mention_count}"
        )
        typer.echo(f"    alias: {aliases}")
        if row.temporal_expression:
            typer.echo(f"    período: {row.temporal_expression}")
    typer.echo(f"Total: {len(rows)} entidades")


@app.command("entity-create")
@app.command("authority-create")
def authority_create_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    preferred_name: str = typer.Argument(..., help="Nombre canónico preferido"),
    entity_type: str = typer.Option("person", "--type"),
    description: str | None = typer.Option(None, "--description"),
    temporal_expression: str | None = typer.Option(None, "--temporal"),
    temporal_note: str | None = typer.Option(None, "--temporal-note"),
    created_by: str = typer.Option("local_user", "--created-by"),
) -> None:
    """Crea una entidad canónica versionada."""
    if entity_type not in AUTHORITY_TYPES:
        raise typer.BadParameter("Tipo inválido: " + entity_type)
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            row = create_authority(
                session,
                project_id=_single_project_id(session),
                entity_type=entity_type,
                preferred_name=preferred_name,
                description=description,
                temporal_expression=temporal_expression,
                temporal_note=temporal_note,
                created_by=created_by,
            )
            authority_id = row.id
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"OK: entidad {authority_id} | {entity_type} | {preferred_name.strip()}")


@app.command("entity-add-alias")
@app.command("authority-add-alias")
def authority_add_alias_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    authority_id: str = typer.Argument(...),
    alias: str = typer.Argument(...),
    alias_type: str = typer.Option("variant", "--type"),
    created_by: str = typer.Option("local_user", "--created-by"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Agrega un alias y crea una nueva revisión de la entidad."""
    if alias_type not in ALIAS_TYPES:
        raise typer.BadParameter("Tipo de alias inválido: " + alias_type)
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            row = add_authority_alias(
                session,
                authority_id=authority_id,
                alias=alias,
                alias_type=alias_type,
                created_by=created_by,
                note=note,
            )
            alias_id = row.id
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"OK: alias {alias_id} | {alias.strip()} | entidad {authority_id}")


@app.command("mention-scan-text-object")
@app.command("mention-scan-object")
def mention_scan_object_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    object_id: str = typer.Argument(..., help="UUID del objeto textual editable, no de la entidad"),
    created_by: str = typer.Option("local_user", "--created-by"),
) -> None:
    """Busca entidades conocidas dentro de un objeto textual editable."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = suggest_dictionary_mentions(
                session, object_id=object_id, created_by=created_by
            )
            rows = mention_rows(session, object_id=object_id, statuses=("pending",))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: sugerencias +{summary.created} | ya presentes {summary.already_present} | "
        f"ambiguas {summary.ambiguous} | candidatos {summary.candidates_scanned}"
    )
    for row in rows:
        typer.echo(
            f"{row.mention_id} | {row.mention_text!r} | "
            f"{row.authority_name or 'sin vincular'} | {row.status}"
        )


@app.command("mention-scan-all")
def mention_scan_all_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: list[str] | None = typer.Option(
        None, "--source-key", help="Limita el escaneo a uno o más documentos"
    ),
    created_by: str = typer.Option("local_user", "--created-by"),
) -> None:
    """Busca nombres y alias de entidades en todos los objetos textuales activos."""
    upgrade_database(project_root)
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = suggest_dictionary_mentions_all(
                session,
                project_id=decisions.project_id,
                source_keys=source_key or (),
                created_by=created_by,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: objetos recorridos {summary.objects_scanned} | sugerencias +{summary.created} | "
        f"ya presentes {summary.already_present} | ambiguas {summary.ambiguous} | "
        f"nombres/alias disponibles {summary.candidates_scanned}"
    )


@app.command("mention-find-entity")
def mention_find_entity_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    entity_id: str = typer.Argument(..., help="UUID de la entidad"),
    source_key: list[str] | None = typer.Option(
        None, "--source-key", help="Limita la búsqueda a uno o más documentos"
    ),
    include_existing: bool = typer.Option(
        False, "--include-existing", help="Muestra también menciones ya incorporadas"
    ),
) -> None:
    """Previsualiza coincidencias del nombre preferido y los alias sin modificar la base."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = authority_mention_candidates(
                session,
                authority_id=entity_id,
                source_keys=source_key or (),
                include_existing=include_existing,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    for row in rows:
        match = "nombre preferido" if row.match_kind == "preferred" else f"alias {row.matched_surface!r}"
        if row.already_included:
            existing = f" | ya incorporada {row.existing_status}"
        elif row.can_link_existing:
            existing = " | mención existente sin autoridad: se vinculará al incorporar"
        elif row.has_authority_conflict:
            existing = (
                " | conflicto: ya vinculada a "
                f"{row.existing_authority_name or 'otra autoridad'}"
            )
        else:
            existing = ""
        typer.echo(
            f"{row.candidate_key} | {row.document_title or '[sin título]'} | "
            f"pág. {row.page_number} | {row.mention_text!r} | {match}{existing}"
        )
        typer.echo(f"    …{row.context_before}{row.mention_text}{row.context_after}…")
    typer.echo(f"Total: {len(rows)} coincidencias")


@app.command("mention-include-entity")
def mention_include_entity_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    entity_id: str = typer.Argument(..., help="UUID de la entidad"),
    source_key: list[str] | None = typer.Option(
        None, "--source-key", help="Limita la búsqueda a uno o más documentos"
    ),
    status: str = typer.Option("pending", "--status", help="pending o accepted"),
    created_by: str = typer.Option("local_user", "--created-by"),
    confirm_all: bool = typer.Option(
        False, "--confirm-all", help="Confirma la incorporación de todas las coincidencias nuevas"
    ),
) -> None:
    """Incorpora en lote todas las coincidencias nuevas de una entidad."""
    if not confirm_all:
        raise typer.BadParameter("Use --confirm-all después de revisar mention-find-entity")
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = authority_mention_candidates(
                session,
                authority_id=entity_id,
                source_keys=source_key or (),
                include_existing=False,
            )
            summary = include_authority_mention_candidates(
                session,
                authority_id=entity_id,
                candidate_keys=[row.candidate_key for row in rows],
                source_keys=source_key or (),
                status=status,
                created_by=created_by,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: solicitadas {summary.requested} | creadas {summary.created} | "
        f"vinculadas {summary.linked_existing} | ya presentes {summary.already_present}"
    )


@app.command("entity-relation-list")
def entity_relation_list_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    entity_id: str | None = typer.Option(None, "--entity-id", help="Limita a una entidad"),
    temporal_start: str | None = typer.Option(None, "--temporal-start"),
    temporal_end: str | None = typer.Option(None, "--temporal-end"),
    temporal_include_undated: bool = typer.Option(False, "--temporal-include-undated"),
    include_inactive: bool = typer.Option(False, "--include-inactive"),
) -> None:
    """Lista relaciones explícitas entre entidades, unidades y partes documentales."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = entity_relation_rows(
                session,
                project_id=_single_project_id(session),
                authority_id=entity_id,
                include_inactive=include_inactive,
                temporal_start=_parse_temporal_cli_date(temporal_start, "--temporal-start"),
                temporal_end=_parse_temporal_cli_date(temporal_end, "--temporal-end"),
                include_undated=temporal_include_undated,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    for row in rows:
        typer.echo(
            f"{row.relation_id} | {row.source_name} --{row.relation_label}--> "
            f"{row.target_label} | {row.review_status} | rev. {row.revision}"
        )
        if row.temporal_expression:
            typer.echo(f"    vigencia: {row.temporal_expression}")
    typer.echo(f"Total: {len(rows)} relaciones")


@app.command("entity-relation-create")
def entity_relation_create_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_entity_id: str = typer.Argument(..., help="UUID de la entidad de origen"),
    relation_label: str = typer.Argument(..., help="Ej.: integró, dependió de, aparece en"),
    target_id: str = typer.Argument(..., help="UUID del destino"),
    target_kind: str = typer.Option("entity", "--target-kind"),
    evidence_note: str | None = typer.Option(None, "--evidence"),
    temporal_expression: str | None = typer.Option(None, "--temporal"),
    temporal_note: str | None = typer.Option(None, "--temporal-note"),
    review_status: str = typer.Option("unreviewed", "--review-status"),
    created_by: str = typer.Option("local_user", "--created-by"),
) -> None:
    """Crea una relación analítica explícita y versionada."""
    if target_kind not in RELATION_TARGET_KINDS:
        raise typer.BadParameter("Tipo de destino inválido: " + target_kind)
    if review_status not in RELATION_REVIEW_STATUSES:
        raise typer.BadParameter("Estado de revisión inválido: " + review_status)
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            row = create_entity_relation(
                session,
                project_id=_single_project_id(session),
                source_authority_id=source_entity_id,
                relation_label=relation_label,
                target_kind=target_kind,
                target_id=target_id,
                evidence_note=evidence_note,
                temporal_expression=temporal_expression,
                temporal_note=temporal_note,
                review_status=review_status,
                created_by=created_by,
            )
            relation_id = row.id
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"OK: relación {relation_id} | {relation_label.strip()}")


@app.command("graph-check")
def graph_check_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    include_info: bool = typer.Option(False, "--include-info"),
) -> None:
    """Controla duplicados, relaciones sin evidencia y menciones desactualizadas."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            issues = graph_consistency_issues(
                session, project_id=_single_project_id(session)
            )
    finally:
        engine.dispose()
    visible = [row for row in issues if include_info or row.severity != "info"]
    for row in visible:
        target = row.relation_id or row.mention_id or row.entity_id or "-"
        typer.echo(f"{row.severity.upper()} | {row.code} | {target} | {row.message}")
    errors = sum(row.severity == "error" for row in visible)
    warnings = sum(row.severity == "warning" for row in visible)
    infos = sum(row.severity == "info" for row in visible)
    typer.echo(
        f"Total: {len(visible)} incidencias | errores {errors} | "
        f"advertencias {warnings} | información {infos}"
    )


@app.command("graph-export")
def graph_export_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    output_dir: Path = typer.Option(Path("exports/graph"), "--out", help="Carpeta de salida"),
    include_mentions: bool = typer.Option(True, "--mentions/--no-mentions"),
    include_shared: bool = typer.Option(True, "--shared-entities/--no-shared-entities"),
    include_inactive: bool = typer.Option(False, "--include-inactive"),
    include_pending_mentions: bool = typer.Option(False, "--include-pending-mentions"),
    temporal_start: str | None = typer.Option(None, "--temporal-start"),
    temporal_end: str | None = typer.Option(None, "--temporal-end"),
    temporal_include_undated: bool = typer.Option(False, "--temporal-include-undated"),
    min_shared_entities: int = typer.Option(1, "--min-shared", min=1),
    max_nodes: int = typer.Option(1000, "--max-nodes", min=2),
) -> None:
    """Exporta el grafo derivado a JSON, CSV y GraphML."""
    project_root = project_root.expanduser().resolve()
    upgrade_database(project_root)
    edge_types = ["explicit"]
    if include_mentions:
        edge_types.append("mention")
    if include_shared:
        edge_types.append("shared_entity")
    target = output_dir.expanduser()
    if not target.is_absolute():
        target = project_root / target
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            project_id = _single_project_id(session)
            view = build_graph(
                session,
                project_id=project_id,
                edge_types=tuple(edge_types),
                include_inactive=include_inactive,
                include_pending_mentions=include_pending_mentions,
                temporal_start=_parse_temporal_cli_date(temporal_start, "--temporal-start"),
                temporal_end=_parse_temporal_cli_date(temporal_end, "--temporal-end"),
                temporal_include_undated=temporal_include_undated,
                min_shared_entities=min_shared_entities,
                max_nodes=max_nodes,
            )
            issues = graph_consistency_issues(session, project_id=project_id)
            paths = export_graph(view, output_dir=target, issues=issues)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: {len(view.nodes)} nodos | {len(view.edges)} aristas | "
        f"{len(issues)} controles"
    )
    if view.truncated:
        typer.echo(
            f"ADVERTENCIA: la exportación fue limitada desde {view.total_nodes_before_limit} nodos."
        )
    for path in paths:
        typer.echo(str(path))


@app.command("export-profile-list")
def export_profile_list_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Lista los perfiles reproducibles de exportación."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            project_id = _single_project_id(session)
            rows = export_profile_rows(session, project_id=project_id)
    finally:
        engine.dispose()
    for row in rows:
        typer.echo(
            f"{row.id} | {row.name} | {row.aggregation_level} | "
            f"{row.text_policy} | {row.output_format} | rev. {row.revision}"
        )
    typer.echo(f"Total: {len(rows)} perfiles")


@app.command("export-profile-save")
def export_profile_save_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    name: str = typer.Argument(..., help="Nombre único del perfil"),
    profile_id: str | None = typer.Option(None, "--profile-id", help="UUID para actualizar"),
    aggregation: str = typer.Option("document", "--aggregation"),
    text_policy: str = typer.Option("corrected_fallback_original", "--text-policy"),
    output_format: str = typer.Option("jsonl", "--format"),
    object_type: list[str] | None = typer.Option(None, "--object-type"),
    object_review_status: list[str] | None = typer.Option(None, "--object-review-status"),
    page_review_status: list[str] | None = typer.Option(None, "--page-review-status"),
    temporal_start: str | None = typer.Option(None, "--temporal-start"),
    temporal_end: str | None = typer.Option(None, "--temporal-end"),
    temporal_include_undated: bool = typer.Option(False, "--temporal-include-undated"),
    page_markers: bool = typer.Option(False, "--page-markers/--no-page-markers"),
    description: str | None = typer.Option(None, "--description"),
    changed_by: str = typer.Option("local_user", "--changed-by"),
) -> None:
    """Crea o actualiza un perfil de exportación."""
    if aggregation not in AGGREGATION_LEVELS:
        raise typer.BadParameter("Agrupación inválida: " + aggregation)
    if text_policy not in TEXT_POLICIES:
        raise typer.BadParameter("Política de texto inválida: " + text_policy)
    if output_format not in OUTPUT_FORMATS:
        raise typer.BadParameter("Formato inválido: " + output_format)
    invalid = set(object_review_status or []) | set(page_review_status or [])
    invalid -= set(EXPORT_REVIEW_STATUSES)
    if invalid:
        raise typer.BadParameter("Estados de revisión inválidos: " + ", ".join(sorted(invalid)))
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            profile = save_export_profile(
                session,
                project_id=_single_project_id(session),
                profile_id=profile_id,
                values=ExportProfileValues(
                    name=name,
                    description=description,
                    aggregation_level=aggregation,
                    text_policy=text_policy,
                    output_format=output_format,
                    include_object_types=tuple(object_type or []),
                    include_review_statuses=tuple(object_review_status or []),
                    include_page_review_statuses=tuple(page_review_status or []),
                    temporal_start=_parse_temporal_cli_date(temporal_start, "--temporal-start"),
                    temporal_end=_parse_temporal_cli_date(temporal_end, "--temporal-end"),
                    temporal_include_undated=temporal_include_undated,
                    include_page_markers=page_markers,
                ),
                changed_by=changed_by,
            )
            result_id = profile.id
            revision = profile.revision
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"OK: perfil {result_id} | {name.strip()} | rev. {revision}")


@app.command("corpus-export-preview")
def corpus_export_preview_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    profile_ref: str = typer.Argument(..., help="UUID o nombre del perfil"),
    limit: int = typer.Option(5, "--limit", min=0, max=100),
) -> None:
    """Muestra el tamaño y los primeros registros de una exportación sin escribir archivos."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            project_id = _single_project_id(session)
            profile = resolve_export_profile(session, project_id=project_id, profile_ref=profile_ref)
            result = preview_export(session, project_id=project_id, profile=profile, limit=limit)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"Registros: {result.total_records} | caracteres: {result.total_characters}")
    for row in result.records:
        typer.echo(f"{row.codigo} | {row.titulo} | {row.object_count} objetos | {len(row.texto)} caracteres")


@app.command("corpus-export")
def corpus_export_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    profile_ref: str = typer.Argument(..., help="UUID o nombre del perfil"),
    output: Path = typer.Option(..., "--out", help="Ruta relativa a project_data"),
    output_format: str | None = typer.Option(None, "--format"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    created_by: str = typer.Option("local_user", "--created-by"),
) -> None:
    """Materializa una exportación y registra perfil, hash de estado y checksum."""
    if output_format is not None and output_format not in OUTPUT_FORMATS:
        raise typer.BadParameter("Formato inválido: " + output_format)
    project_root = project_root.expanduser().resolve()
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            project_id = _single_project_id(session)
            profile = resolve_export_profile(session, project_id=project_id, profile_ref=profile_ref)
            result = run_export(
                session,
                project_root=project_root,
                project_id=project_id,
                profile=profile,
                output_relative_path=output.as_posix(),
                output_format=output_format,
                overwrite=overwrite,
                created_by=created_by,
            )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: {result.output_path} | registros {result.row_count} | "
        f"caracteres {result.character_count}"
    )
    typer.echo(f"SHA-256 archivo: {result.output_sha256}")
    typer.echo(f"SHA-256 estado: {result.corpus_state_sha256}")


@app.command("corpus-export-history")
def corpus_export_history_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Lista exportaciones materializadas y sus hashes reproducibles."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = export_run_rows(session, project_id=_single_project_id(session))
    finally:
        engine.dispose()
    for row in rows:
        typer.echo(
            f"{row.run_id} | {row.profile_name} | {row.output_format} | "
            f"{row.row_count} registros | {row.output_relative_path}"
        )
        typer.echo(f"    archivo {row.output_sha256} | estado {row.corpus_state_sha256}")
    typer.echo(f"Total: {len(rows)} exportaciones")


@app.command("semantic-profile-list")
def semantic_profile_list_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Lista perfiles de búsqueda semántica y el estado de sus índices."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            project_id = _single_project_id(session)
            profiles = semantic_profile_rows(session, project_id=project_id)
            rows = [
                (
                    profile,
                    semantic_index_status(
                        session,
                        project_root=project_root.resolve(),
                        project_id=project_id,
                        profile=profile,
                    ),
                )
                for profile in profiles
            ]
    finally:
        engine.dispose()
    for profile, status in rows:
        state = "actual" if status.is_current else "pendiente"
        typer.echo(
            f"{profile.id} | {profile.name} | {profile.aggregation_level} | {state} | "
            f"vectores {status.vector_count} | rev. {profile.revision}"
        )
        typer.echo(f"    modelo {profile.model_name}@{profile.model_revision or 'latest'}")
        typer.echo(f"    {status.reason}")
    typer.echo(f"Total: {len(rows)} perfiles")


@app.command("semantic-profile-save")
def semantic_profile_save_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    name: str = typer.Argument(..., help="Nombre del perfil"),
    profile_ref: str | None = typer.Option(None, "--profile", help="ID o nombre a actualizar"),
    model: str = typer.Option(DEFAULT_MODEL_NAME, "--model"),
    model_revision: str | None = typer.Option(DEFAULT_MODEL_REVISION, "--model-revision"),
    aggregation: str = typer.Option("object", "--aggregation"),
    chunk_size: int = typer.Option(1800, "--chunk-size"),
    chunk_overlap: int = typer.Option(200, "--chunk-overlap"),
    object_type: list[str] | None = typer.Option(None, "--object-type"),
    object_status: list[str] | None = typer.Option(None, "--object-status"),
    page_status: list[str] | None = typer.Option(None, "--page-status"),
    query_prefix: str = typer.Option("query: ", "--query-prefix"),
    document_prefix: str = typer.Option("passage: ", "--document-prefix"),
    changed_by: str = typer.Option("local_user", "--changed-by"),
) -> None:
    """Crea o actualiza un perfil semántico reproducible."""
    if aggregation not in SEMANTIC_AGGREGATION_LEVELS:
        raise typer.BadParameter(
            f"--aggregation debe ser: {', '.join(SEMANTIC_AGGREGATION_LEVELS)}"
        )
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            project_id = _single_project_id(session)
            profile_id = None
            if profile_ref:
                profile_id = resolve_semantic_profile(
                    session, project_id=project_id, profile_ref=profile_ref
                ).id
            profile = save_semantic_profile(
                session,
                project_id=project_id,
                profile_id=profile_id,
                values=SemanticProfileValues(
                    name=name,
                    model_name=model,
                    model_revision=model_revision,
                    aggregation_level=aggregation,
                    include_object_types=tuple(object_type or ()),
                    include_review_statuses=tuple(object_status or ()),
                    include_page_review_statuses=tuple(page_status or ()),
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    query_prefix=query_prefix,
                    document_prefix=document_prefix,
                ),
                changed_by=changed_by,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"OK: {profile.id} | {profile.name} | revisión {profile.revision}")
    typer.echo(f"Modelo: {profile.model_name}@{profile.model_revision or 'latest'}")


@app.command("semantic-profile-default")
def semantic_profile_default_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    changed_by: str = typer.Option("local_user", "--changed-by"),
) -> None:
    """Crea el perfil inicial multilingüe si todavía no existe."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            profile = ensure_default_semantic_profile(
                session, project_id=_single_project_id(session), changed_by=changed_by
            )
    finally:
        engine.dispose()
    typer.echo(f"OK: {profile.id} | {profile.name}")


@app.command("semantic-index-status")
def semantic_index_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    profile_ref: str = typer.Argument(..., help="ID o nombre del perfil"),
) -> None:
    """Comprueba si el índice coincide con el perfil y el corpus actuales."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            project_id = _single_project_id(session)
            profile = resolve_semantic_profile(
                session, project_id=project_id, profile_ref=profile_ref
            )
            status = semantic_index_status(
                session,
                project_root=project_root.resolve(),
                project_id=project_id,
                profile=profile,
            )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"{profile.name} | {'actualizado' if status.is_current else 'pendiente'} | "
        f"vectores {status.vector_count} | dimensiones {status.dimensions or '-'}"
    )
    typer.echo(status.reason)
    if status.latest_run_id:
        typer.echo(f"Run: {status.latest_run_id} | {status.indexed_at}")


@app.command("semantic-index-build")
def semantic_index_build_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    profile_ref: str = typer.Argument(..., help="ID o nombre del perfil"),
    device: str = typer.Option("auto", "--device", help="auto, cpu o cuda"),
    batch_size: int = typer.Option(32, "--batch-size", min=1, max=2048),
    created_by: str = typer.Option("local_user", "--created-by"),
) -> None:
    """Descarga/carga el modelo y construye el índice semántico local."""
    if device not in {"auto", "cpu", "cuda"}:
        raise typer.BadParameter("--device debe ser auto, cpu o cuda")
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            project_id = _single_project_id(session)
            profile = resolve_semantic_profile(
                session, project_id=project_id, profile_ref=profile_ref
            )
            summary = build_semantic_index(
                session,
                project_root=project_root.resolve(),
                project_id=project_id,
                profile=profile,
                created_by=created_by,
                device=device,
                batch_size=batch_size,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: índice {summary.run_id} | fragmentos {summary.vector_count} | "
        f"dimensiones {summary.dimensions}"
    )
    typer.echo(f"Vectores: {summary.vectors_path}")
    typer.echo(f"Metadatos: {summary.metadata_path}")
    typer.echo(f"Estado: {summary.corpus_state_sha256}")


@app.command("semantic-search")
def semantic_search_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    profile_ref: str = typer.Argument(..., help="ID o nombre del perfil"),
    query: str = typer.Argument(..., help="Consulta en lenguaje natural"),
    top_k: int = typer.Option(20, "--top-k", min=1, max=500),
    minimum_score: float = typer.Option(0.0, "--minimum-score", min=-1.0, max=1.0),
    temporal_start: str | None = typer.Option(None, "--temporal-start"),
    temporal_end: str | None = typer.Option(None, "--temporal-end"),
    temporal_include_undated: bool = typer.Option(False, "--temporal-include-undated"),
    device: str = typer.Option("auto", "--device"),
) -> None:
    """Busca fragmentos próximos en el espacio vectorial del perfil."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            project_id = _single_project_id(session)
            profile = resolve_semantic_profile(
                session, project_id=project_id, profile_ref=profile_ref
            )
            rows = semantic_search(
                session,
                project_root=project_root.resolve(),
                project_id=project_id,
                profile=profile,
                query=query,
                top_k=top_k,
                minimum_score=minimum_score,
                temporal_start=_parse_temporal_cli_date(temporal_start, "--temporal-start"),
                temporal_end=_parse_temporal_cli_date(temporal_end, "--temporal-end"),
                temporal_include_undated=temporal_include_undated,
                device=device,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    for index, row in enumerate(rows, start=1):
        pages = str(row.page_start) if row.page_start == row.page_end else f"{row.page_start}-{row.page_end}"
        typer.echo(f"{index}. {row.score:.4f} | {row.title} | páginas {pages} | {row.source_key or '-'}")
        typer.echo(f"    {' '.join(row.excerpt.split())}")
    typer.echo(f"Total: {len(rows)} resultados")


@app.command("processing-status")
def processing_status_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Muestra el estado coordinado de incorporación y revisión de cada documento."""
    upgrade_database(project_root)
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = processing_inventory_rows(
                session,
                project_root=project_root,
                project_id=decisions.project_id,
            )
    finally:
        engine.dispose()
    for row in rows:
        total = row.page_count if row.page_count is not None else "?"
        typer.echo(
            f"{row.source_key} | {row.status} | páginas {total} | "
            f"extraídas {row.extracted_pages} | seleccionadas {row.selected_pages} | "
            f"editables {row.editable_pages} | aprobadas {row.approved_pages} | "
            f"{row.title}"
        )
    typer.echo(f"Total: {len(rows)} documentos")


@app.command("processing-jobs")
def processing_jobs_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    limit: int = typer.Option(50, "--limit", min=1, max=500),
    show_items: bool = typer.Option(False, "--items"),
) -> None:
    """Lista trabajos persistentes iniciados desde la vista Procesamiento."""
    upgrade_database(project_root)
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = processing_job_rows(
                session, project_id=decisions.project_id, limit=limit
            )
            item_map = {
                row.job_id: processing_job_item_rows(session, job_id=row.job_id)
                for row in rows
            } if show_items else {}
    finally:
        engine.dispose()
    for row in rows:
        typer.echo(
            f"{row.job_id} | {row.operation} | {row.status} | "
            f"ok {row.completed_items} | advertencias {row.warning_items} | "
            f"fallidos {row.failed_items} | {row.created_at.isoformat()} | {row.created_by}"
        )
        for item in item_map.get(row.job_id, []):
            pages = ",".join(map(str, item.pages)) or "-"
            typer.echo(
                f"  {item.source_key} | {item.status} | páginas {pages} | "
                f"{item.message or '-'}"
            )
    typer.echo(f"Total: {len(rows)} trabajos")


def _parse_due_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter("La fecha debe usar formato YYYY-MM-DD") from exc
    return datetime.combine(parsed, time(23, 59), tzinfo=timezone.utc)


@app.command("work-assignment-create")
def work_assignment_create_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    source_key: str = typer.Argument(..., help="Clave del documento"),
    assignee: str = typer.Argument(..., help="Persona responsable"),
    assignment_kind: str = typer.Option("primary_review", "--kind"),
    page_start: int | None = typer.Option(None, "--page-start", min=1),
    page_end: int | None = typer.Option(None, "--page-end", min=1),
    priority: str = typer.Option("normal", "--priority"),
    due: str | None = typer.Option(None, "--due", help="Fecha límite YYYY-MM-DD"),
    note: str | None = typer.Option(None, "--note"),
    created_by: str = typer.Option("local_user", "--created-by"),
) -> None:
    """Crea una asignación de procesamiento o revisión primaria."""
    if assignment_kind not in {"processing", "primary_review"}:
        raise typer.BadParameter("--kind debe ser processing o primary_review")
    if priority not in ASSIGNMENT_PRIORITIES:
        raise typer.BadParameter(f"Prioridad inválida: {priority}")
    upgrade_database(project_root)
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            registration = session.scalar(
                select(SourceRegistration).where(
                    SourceRegistration.project_id == decisions.project_id,
                    SourceRegistration.source_key == source_key,
                )
            )
            if registration is None:
                raise typer.BadParameter(f"source_key no registrado: {source_key}")
            row = create_work_assignment(
                session,
                project_id=decisions.project_id,
                source_type=registration.source_type,
                source_key=registration.source_key,
                assignment_kind=assignment_kind,
                assignee=assignee,
                created_by=created_by,
                page_start=page_start,
                page_end=page_end,
                priority=priority,
                due_at=_parse_due_date(due),
                note=note,
            )
            assignment_id = row.id
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"OK: asignación {assignment_id}")


@app.command("work-cross-review-create")
def work_cross_review_create_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    primary_assignment_id: str = typer.Argument(..., help="ID de la revisión primaria"),
    assignee: str = typer.Argument(..., help="Responsable de la revisión cruzada"),
    priority: str | None = typer.Option(None, "--priority"),
    due: str | None = typer.Option(None, "--due", help="Fecha límite YYYY-MM-DD"),
    note: str | None = typer.Option(None, "--note"),
    created_by: str = typer.Option("local_user", "--created-by"),
) -> None:
    """Crea una revisión cruzada sobre una revisión primaria enviada."""
    if priority is not None and priority not in ASSIGNMENT_PRIORITIES:
        raise typer.BadParameter(f"Prioridad inválida: {priority}")
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            row = create_cross_review_assignment(
                session,
                primary_assignment_id=primary_assignment_id,
                assignee=assignee,
                created_by=created_by,
                priority=priority,
                due_at=_parse_due_date(due),
                note=note,
            )
            assignment_id = row.id
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"OK: revisión cruzada {assignment_id}")


@app.command("work-assignment-update")
def work_assignment_update_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    assignment_id: str = typer.Argument(...),
    assignee: str | None = typer.Option(None, "--assignee"),
    status: str | None = typer.Option(None, "--status"),
    priority: str | None = typer.Option(None, "--priority"),
    outcome: str | None = typer.Option(None, "--outcome"),
    assignment_note: str | None = typer.Option(None, "--note"),
    change_note: str | None = typer.Option(None, "--change-note"),
    changed_by: str = typer.Option("local_user", "--changed-by"),
) -> None:
    """Actualiza responsable, estado, prioridad o resultado de una asignación."""
    if status is not None and status not in ASSIGNMENT_STATUSES:
        raise typer.BadParameter(f"Estado inválido: {status}")
    if priority is not None and priority not in ASSIGNMENT_PRIORITIES:
        raise typer.BadParameter(f"Prioridad inválida: {priority}")
    if outcome is not None and outcome not in CROSS_REVIEW_OUTCOMES:
        raise typer.BadParameter(f"Resultado inválido: {outcome}")
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            current = session.get(WorkAssignment, assignment_id)
            if current is None:
                raise typer.BadParameter(f"Asignación inexistente: {assignment_id}")
            row = update_work_assignment(
                session,
                assignment_id=assignment_id,
                expected_revision=current.revision,
                changed_by=changed_by,
                assignee=assignee,
                status=status,
                priority=priority,
                outcome=outcome if outcome is not None else current.outcome,
                assignment_note=(
                    assignment_note if assignment_note is not None else current.note
                ),
                change_note=change_note,
            )
            revision = row.revision
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(f"OK: asignación {assignment_id} revisión {revision}")


@app.command("work-assignments")
def work_assignments_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    assignee: str | None = typer.Option(None, "--assignee"),
    status: str | None = typer.Option(None, "--status"),
    assignment_kind: str | None = typer.Option(None, "--kind"),
    include_cancelled: bool = typer.Option(False, "--include-cancelled"),
) -> None:
    """Lista asignaciones de trabajo del equipo."""
    upgrade_database(project_root)
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = work_assignment_rows(
                session,
                project_id=decisions.project_id,
                assignees=[assignee] if assignee else None,
                statuses=[status] if status else None,
                assignment_kinds=[assignment_kind] if assignment_kind else None,
                include_cancelled=include_cancelled,
            )
    finally:
        engine.dispose()
    for row in rows:
        pages = (
            "documento"
            if row.page_start is None
            else str(row.page_start)
            if row.page_start == row.page_end
            else f"{row.page_start}-{row.page_end}"
        )
        typer.echo(
            f"{row.assignment_id} | {row.assignment_kind} | {row.status} | "
            f"{row.priority} | {row.assignee} | {row.source_key} | páginas {pages} | "
            f"{row.title}"
        )
    typer.echo(f"Total: {len(rows)} asignaciones")


@app.command("work-summary")
def work_summary_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Resume la carga de trabajo por responsable."""
    upgrade_database(project_root)
    decisions = load_decisions(project_root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = workload_summary_rows(session, project_id=decisions.project_id)
    finally:
        engine.dispose()
    for row in rows:
        typer.echo(
            f"{row.assignee} | total {row.total} | planificadas {row.planned} | "
            f"en curso {row.in_progress} | enviadas {row.submitted} | "
            f"bloqueadas {row.blocked} | completadas {row.completed} | "
            f"vencidas {row.overdue}"
        )
    typer.echo(f"Total: {len(rows)} responsables")



@app.command("review-app")
def review_app_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8501, "--port", min=1, max=65535),
    open_browser: bool = typer.Option(
        True, "--open-browser/--no-browser", help="Abrir la interfaz en el navegador"
    ),
) -> None:
    """Inicia la primera interfaz local de revisión versionada."""
    if importlib.util.find_spec("streamlit") is None:
        raise typer.BadParameter(
            "Streamlit no está instalado. Ejecutá: "
            'pip install -e ".[dev,extraction,streamlit]"'
        )
    project_root = project_root.expanduser().resolve()
    decisions_path = project_root / "config" / "decisions.yaml"
    if not decisions_path.is_file():
        raise typer.BadParameter(
            f"No se encontró la configuración del proyecto: {decisions_path}"
        )
    upgrade_database(project_root)
    script = Path(__file__).with_name("review_app.py")
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(script),
        "--server.address",
        host,
        "--server.port",
        str(port),
        "--server.headless",
        "false" if open_browser else "true",
        "--",
        "--project-root",
        str(project_root),
    ]
    typer.echo(f"Interfaz: http://{host}:{port}")
    typer.echo("Para detenerla, presioná Ctrl+C.")
    try:
        completed = subprocess.run(command, check=False)
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None
    raise typer.Exit(code=completed.returncode)


@app.command("exchange-apply-bundle")
def exchange_apply_bundle_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    bundle: str = typer.Argument(..., help="ID del bundle o ruta al ZIP ya evaluado"),
    applied_by: str = typer.Option("local_user", "--applied-by"),
    confirm_apply: bool = typer.Option(
        False,
        "--confirm-apply",
        help="Confirma la aplicación transaccional del bundle",
    ),
) -> None:
    """Aplica un bundle ready_to_apply con backup previo y checkpoint posterior."""
    if not confirm_apply:
        raise typer.BadParameter(
            "Use --confirm-apply después de revisar el reporte dry-run"
        )
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            summary = apply_change_bundle(
                session,
                project_root=project_root.resolve(),
                bundle_ref=bundle,
                applied_by=applied_by,
            )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    typer.echo(
        f"OK: bundle {summary.bundle_id} aplicado | eventos {summary.applied_event_count} | "
        f"duplicados omitidos {summary.duplicate_event_count} | "
        f"conservados localmente {summary.kept_local_event_count}"
    )
    typer.echo(
        f"Secuencia local: {summary.local_sequence_start} -> {summary.local_sequence_end}"
    )
    typer.echo(f"Backup: {summary.backup_path}")
    typer.echo(f"SHA-256 backup: {summary.backup_sha256}")
    typer.echo(
        f"Checkpoint: {summary.checkpoint_label} | {summary.checkpoint_id}"
    )
    typer.echo(f"Reporte: {summary.report_markdown_path}")


@app.command("exchange-applications")
def exchange_applications_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Lista bundles aplicados, backups y checkpoints posteriores."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = bundle_application_rows(session)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        engine.dispose()
    for row in rows:
        typer.echo(
            f"{row.bundle_id} | {row.status} | aplicados {row.applied_event_count} | "
            f"duplicados {row.duplicate_event_count} | "
            f"conservados localmente {row.kept_local_event_count} | "
            f"checkpoint {row.checkpoint_label or '-'}"
        )
        typer.echo(
            f"    backup {row.backup_relative_path} | {row.applied_by} | "
            f"{row.applied_at.isoformat()}"
        )
    typer.echo(f"Total: {len(rows)} aplicaciones")


@app.command("project-readiness")
def project_readiness_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Resume el estado operativo y las próximas acciones del proyecto."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            report = operational_readiness(session, project_root=project_root.resolve())
    finally:
        engine.dispose()
    for item in report.items:
        typer.echo(f"{item.status.upper()} | {item.label} | {item.summary}")
        if item.detail:
            typer.echo(f"    {item.detail}")
    typer.echo(
        f"Estado: {report.overall_status} | listos {report.ready_count} | "
        f"atención {report.attention_count} | pendientes {report.pending_count} | "
        f"DB {report.database_revision or '-'}"
    )
    if report.attention_count:
        raise typer.Exit(code=2)


@app.command("project-backup-test")
def project_backup_test_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    backup: Path = typer.Argument(..., help="ZIP de backup a probar"),
    tested_by: str = typer.Option("local_user", "--tested-by"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    """Prueba en una carpeta temporal que el backup pueda migrarse y abrirse."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            result = run_project_backup_recovery_test(
                session,
                project_root=project_root.resolve(),
                backup_path=backup.resolve(),
                tested_by=tested_by,
                note=note,
            )
    finally:
        engine.dispose()
    typer.echo(
        f"{result.status.upper()}: {result.backup_relative_path} | "
        f"{result.source_database_revision or '-'} -> "
        f"{result.upgraded_database_revision or '-'}"
    )
    for key, value in result.details.items():
        typer.echo(f"    {key}: {value}")
    if result.status != "completed":
        raise typer.Exit(code=2)


@app.command("project-recovery-history")
def project_recovery_history_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    limit: int = typer.Option(20, "--limit", min=1, max=500),
) -> None:
    """Lista las pruebas de recuperación registradas."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = recovery_check_rows(session, limit=limit)
    finally:
        engine.dispose()
    for row in rows:
        typer.echo(
            f"{row.status} | {row.backup_relative_path} | "
            f"{row.source_database_revision or '-'} -> "
            f"{row.upgraded_database_revision or '-'} | "
            f"{row.tested_by} | {row.tested_at.isoformat()}"
        )
    typer.echo(f"Total: {len(rows)} pruebas")


@app.command("project-check")
def project_check_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Ejecuta controles globales de SQLite, archivos, menciones, grafo y exportaciones."""
    upgrade_database(project_root)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            report = check_project_health(session, project_root=project_root.resolve())
    finally:
        engine.dispose()
    for issue in report.issues:
        typer.echo(f"{issue.severity.upper()} | {issue.code} | {issue.message}")
        if issue.detail:
            typer.echo(f"    {issue.detail}")
    typer.echo(
        f"Total: errores {report.error_count} | advertencias {report.warning_count} | "
        f"información {report.info_count} | DB {report.database_revision or '-'}"
    )
    if report.error_count:
        raise typer.Exit(code=2)


@app.command("project-backup-create")
def project_backup_create_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    created_by: str = typer.Option("local_user", "--created-by"),
    note: str | None = typer.Option(None, "--note"),
    out: Path | None = typer.Option(None, "--out", help="ZIP de salida opcional"),
) -> None:
    """Crea un backup verificable de SQLite y config, sin copiar PDF/TIFF."""
    upgrade_database(project_root)
    try:
        info = create_project_backup(
            project_root=project_root.resolve(),
            created_by=created_by,
            note=note,
            output_path=out,
        )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"OK: {info.path}")
    typer.echo(f"SHA-256 backup: {info.backup_sha256}")
    typer.echo(f"SHA-256 DB: {info.database_sha256}")
    typer.echo(f"Revisión: {info.database_revision or '-'} | config {info.config_file_count}")


@app.command("project-backup-list")
def project_backup_list_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
) -> None:
    """Lista backups verificables guardados dentro del proyecto."""
    rows = list_project_backups(project_root.resolve())
    for row in rows:
        typer.echo(
            f"{row.path} | {row.created_at} | DB {row.database_revision or '-'} | "
            f"{row.created_by} | {row.backup_sha256}"
        )
    typer.echo(f"Total: {len(rows)} backups")


@app.command("project-backup-inspect")
def project_backup_inspect_command(
    backup: Path = typer.Argument(..., help="ZIP de backup"),
) -> None:
    """Verifica estructura, checksums y quick_check de un backup."""
    try:
        info = inspect_project_backup(backup)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"OK: {info.path}")
    typer.echo(f"Proyecto: {info.project_name or info.project_id or '-'}")
    typer.echo(f"Revisión DB: {info.database_revision or '-'}")
    typer.echo(f"SHA-256 backup: {info.backup_sha256}")
    typer.echo(f"SHA-256 DB: {info.database_sha256}")


@app.command("project-restore-backup")
def project_restore_backup_command(
    project_root: Path = typer.Argument(..., help="Raíz del proyecto operativo"),
    backup: Path = typer.Argument(..., help="ZIP de backup a restaurar"),
    restored_by: str = typer.Option("local_user", "--restored-by"),
    no_config: bool = typer.Option(False, "--no-config", help="No restaura config/"),
    confirm_restore: bool = typer.Option(
        False, "--confirm-restore", help="Confirma el reemplazo de la base activa"
    ),
) -> None:
    """Restaura un backup y crea antes una copia automática del estado actual."""
    if not confirm_restore:
        raise typer.BadParameter(
            "Detené Streamlit y usá --confirm-restore después de inspeccionar el backup"
        )
    try:
        summary = restore_project_backup(
            project_root=project_root.resolve(),
            backup_path=backup,
            restored_by=restored_by,
            restore_config=not no_config,
        )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"OK: restaurado {summary.restored_backup}")
    typer.echo(f"Revisión DB restaurada: {summary.database_revision or '-'}")
    typer.echo(f"Backup de seguridad: {summary.safety_backup}")
    typer.echo(f"SHA-256 seguridad: {summary.safety_backup_sha256}")
    typer.echo("Ejecutá archive-workbench db-upgrade antes de volver a abrir la app.")


if __name__ == "__main__":
    app()
