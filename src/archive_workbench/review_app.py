from __future__ import annotations

from archive_workbench.ui_dates import DATE_INPUT_MIN, DATE_INPUT_MAX
from archive_workbench.ui_help import TAB_HELP, TASK_HELP
import argparse
from collections import Counter
import hashlib
import html
import json
import sys
from pathlib import Path

from typing import Callable

from archive_workbench.local_picker import choose_local_directory
from archive_workbench.runtime_environment import managed_workspace, workspace_display_path
from archive_workbench.ui_navigation import (
    mount_choice_help,
    mount_heading_help,
    mount_view_scroll_keeper,
    rerun_app,
    rerun_view,
    request_app_view,
    section_heading,
    tracked_tabs,
)

from archive_workbench.db import (
    DatabaseRevisionError,
    create_sqlite_engine,
    database_path,
    require_current_database,
    session_scope,
)
from archive_workbench.catalog_app import render_catalog_view
from archive_workbench.audiovisual_app import render_audiovisual_view
from archive_workbench.authority_app import render_authorities_view
from archive_workbench.decisions import load_decisions
from archive_workbench.authorities import (
    AUTHORITY_TYPES,
    LINKED_MENTION_STATUSES,
    MENTION_STATUSES,
    authority_rows,
    create_mention,
    mention_rows,
    suggest_dictionary_mentions,
    update_mention,
)
from archive_workbench.editing import (
    export_editable_layer,
    merge_editable_object,
    move_editable_object,
    object_revision_rows,
    revert_editable_object,
    set_editable_object_lifecycle,
    split_editable_object,
    update_editable_object,
)
from archive_workbench.layout_structure import (
    apply_layout_proposal,
    archive_duplicate_candidate,
    archive_layout_column,
    assign_object_to_column,
    create_layout_column_for_object,
    layout_proposal,
    layout_structure,
    layout_structure_history,
    merge_fragment_candidate,
    rename_layout_column,
    render_layout_overlay,
)
from archive_workbench.form_structure import (
    archive_control,
    archive_group,
    ensure_group,
    form_candidates,
    form_structure,
    form_structure_history,
    register_control,
    rename_group,
    update_control,
)
from archive_workbench.page_actions import (
    execute_page_action,
    page_action_availability,
    redo_page_action,
    undo_page_action,
)
from archive_workbench.candidate_review import page_history_rows
from archive_workbench.review import (
    ReviewObjectRow,
    render_review_overlay,
    review_document_rows,
    review_page_view,
)
from archive_workbench.review_annotations import (
    REVIEW_STATUSES,
    TAG_KINDS,
    add_object_comment,
    add_object_tag,
    object_comment_rows,
    remove_object_tag,
    set_object_review_status,
    set_page_review_status,
)
from archive_workbench.review_parts import (
    assign_editable_object_part,
    assign_page_objects_to_part,
)
from archive_workbench.review_canvas import clickable_review_canvas
from archive_workbench.audiovisual import search_transcript_segments, format_timestamp
from archive_workbench.search import (
    MATCH_MODES,
    SEARCH_FIELDS,
    concordance_occurrences,
    rebuild_search_index,
    search_editable_objects,
    search_index_status,
)
from archive_workbench.graph_app import render_graph_view
from archive_workbench.export_app import render_export_view
from archive_workbench.admin_app import render_admin_view
from archive_workbench.semantic_app import (
    queue_similar_semantic_search,
    render_semantic_search_view,
)
from archive_workbench.processing_app import render_processing_view
from archive_workbench.work_app import render_work_view
from archive_workbench.home_app import render_home_view
from archive_workbench.project_setup import create_ready_project, discover_projects, suggested_project_id
from archive_workbench.user_preferences import (
    PALETTES,
    UserPreferences,
    load_user_preferences,
    save_user_preferences,
)
from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage
from archive_workbench.lineage_recovery import (
    lineage_recovery_rows,
    recover_unmatched_bundle_lineage,
)
from archive_workbench.common_base import (
    accept_common_base_proposal,
    common_base_agreement_rows,
    create_common_base_proposal,
    finalize_common_base_agreement,
)
from archive_workbench.state_adoption import (
    apply_state_adoption,
    create_state_adoption_package,
    preview_state_adoption,
    state_adoption_rows,
)
from archive_workbench.exchange import (
    apply_change_bundle,
    compare_change_bundle_manifest,
    bundle_application_rows,
    conflict_field_rows,
    dry_run_change_bundle,
    exchange_status,
    checkpoint_rows,
    export_change_bundle,
    finalize_bundle_resolutions,
    incoming_bundle_diagnostics,
    incoming_bundle_rows,
    inspect_change_bundle,
    purge_incoming_bundle,
    resolution_status,
    resolve_conflict_fields_bulk,
    save_conflict_resolution,
    set_incoming_bundle_archived,
)
from archive_workbench.team_copy import (
    TEAM_COPY_GROUP_LABELS,
    TEAM_COPY_PRESETS,
    activate_received_team_copy,
    create_team_copy_package,
    plan_team_copy,
)
from archive_workbench.google_drive_transport import (
    authorize_google_drive,
    complete_google_drive_authorization,
    connection_status as google_drive_connection_status,
    default_client_secret_path as google_drive_default_client_secret_path,
    default_token_path as google_drive_default_token_path,
    download_archive_workbench_zip_from_drive,
    get_drive_file_metadata,
    inspect_drive_artifact,
    load_picker_result as google_drive_load_picker_result,
    pick_drive_exchange_bundle,
    prepare_google_drive_authorization,
    upload_archive_workbench_zip_to_drive,
)

_STATUS_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}
_LIFECYCLE_LABELS = {
    "active": "Activo",
    "deleted": "Eliminado",
}
_ACTION_LABELS = {
    "edit": "edición",
    "lifecycle": "cambio de estado",
    "reorder": "reordenamiento",
    "merge": "combinación",
    "split": "división",
    "add": "agregó un bloque de texto",
    "revert": "restauración de revisión",
    "assign_part": "asignación de parte interna",
    "form_structure": "estructura de formulario",
    "layout": "estructura de columnas y orden",
    "delete": "marcó un bloque de texto como eliminado",
    "regional_ocr_replace": "reemplazo de texto desde una zona",
}
_TAG_KIND_LABELS = {
    "thematic": "Temática",
    "conceptual": "Conceptual",
    "workflow": "Flujo de trabajo",
    "unclassified": "Sin clasificar",
}

_AUTHORITY_TYPE_LABELS = {
    "person": "Persona",
    "organization": "Organismo / institución",
    "place": "Lugar",
    "event": "Acontecimiento",
    "work": "Obra / publicación",
    "other": "Otra entidad",
}
_MENTION_STATUS_LABELS = {
    "pending": "Pendiente",
    "accepted": "Aceptada",
    "rejected": "Rechazada",
    "modified": "Modificada",
}

_VIEW_LABELS = {
    "home": "Inicio",
    "catalog": "Catálogo",
    "audiovisual": "Audio y video",
    "processing": "Procesar documentos",
    "work": "Organizar trabajo",
    "review": "Revisar documentos",
    "search": "Búsqueda textual",
    "semantic": "Búsqueda semántica",
    "authorities": "Entidades y menciones",
    "graph": "Explorar relaciones",
    "export": "Exportar corpus",
    "exchange": "Intercambiar cambios",
    "admin": "Administrar y recuperar",
}

_WORKFLOW_STEPS = (
    "catalog",
    "audiovisual",
    "processing",
    "work",
    "review",
    "search",
    "semantic",
    "authorities",
    "graph",
    "export",
    "exchange",
    "admin",
)

_VIEW_PHASES = {
    "catalog": "1. Preparar el corpus",
    "audiovisual": "1. Preparar el corpus",
    "processing": "1. Preparar el corpus",
    "work": "2. Organizar y revisar",
    "review": "2. Organizar y revisar",
    "search": "3. Explorar y describir",
    "semantic": "3. Explorar y describir",
    "authorities": "3. Explorar y describir",
    "graph": "3. Explorar y describir",
    "export": "4. Preparar resultados",
    "exchange": "5. Compartir y preservar",
    "admin": "5. Compartir y preservar",
}

_VIEW_GUIDANCE = {
    "catalog": (
        "Organizar el catálogo, describir sus unidades y asociar los archivos digitales que vas a trabajar.",
        "Antes de empezar, conviene saber qué materiales querés incorporar y, si ya lo conocés, cómo se organizan en el archivo de origen. Podés comenzar con información parcial y completarla después.",
        "Cuando los archivos estén vinculados, podés pasar a Procesar documentos o Audio y video.",
    ),
    "audiovisual": (
        "Incorporar audio o video al proyecto y trabajar con sus transcripciones.",
        "Podés agregar material desde esta computadora o desde una plataforma web y vincularlo con una unidad del catálogo.",
        "Después podés transcribir y revisar el material, buscar la transcripción, registrar entidades o exportar los segmentos revisados.",
    ),
    "processing": (
        "Preparar las imágenes de las páginas, extraer su texto y elegir qué extracción completa querés revisar.",
        "Necesitás un documento registrado en Catálogo y una copia local disponible.",
        "Después de extraer el texto, podés enviar las páginas elegidas a Revisar documentos para corregirlas.",
    ),
    "work": (
        "Distribuir tareas de procesamiento o revisión entre integrantes del equipo y registrar el avance de cada asignación.",
        "Necesitás documentos registrados o páginas listas para revisar.",
        "Después podés abrir cada tarea en Revisar documentos.",
    ),
    "review": (
        "Comparar la imagen de cada página con el texto extraído, corregirlo y registrar decisiones sobre orden, estructura, casilleros, etiquetas, comentarios y menciones.",
        "Necesitás al menos una página enviada a Revisar documentos desde Procesar documentos.",
        "Después podés buscar los textos revisados y registrar menciones de entidades o relaciones analíticas.",
    ),
    "search": (
        "Encontrar palabras, frases y fragmentos exactos en los textos revisados y transcripciones que estén disponibles para búsqueda.",
        "Necesitás páginas ya enviadas a Revisar documentos o transcripciones registradas.",
        "Podés abrir cada resultado de búsqueda en la página documental o en el segmento audiovisual donde aparece.",
    ),
    "semantic": (
        "Encontrar fragmentos relacionados por significado aunque no usen las mismas palabras.",
        "Necesitás el componente de búsqueda semántica y un índice construido para el contenido elegido.",
        "Revisá siempre los resultados en contexto antes de usarlos como evidencia.",
    ),
    "authorities": (
        "Registrar entidades reutilizables y vincular con ellas las menciones encontradas en los documentos.",
        "Podés empezar desde una entidad conocida o desde una mención observada durante la revisión.",
        "Después podés explorar relaciones o volver a los documentos vinculados.",
    ),
    "graph": (
        "Visualizar relaciones registradas y conexiones derivadas entre entidades y documentos.",
        "Necesitás entidades, menciones o relaciones registradas.",
        "Si detectás un error, corregilo en Entidades y menciones o en el catálogo correspondiente.",
    ),
    "export": (
        "Elegir qué textos revisados y datos descriptivos incluir y crear archivos reproducibles para análisis o intercambio externo.",
        "Definí qué estados de revisión y qué tipos de texto o datos descriptivos querés incluir en la exportación.",
        "Revisá la vista previa antes de crear el archivo final.",
    ),
    "exchange": (
        "Compartir cambios entre copias del mismo proyecto sin compartir una base de datos abierta.",
        "Antes de incorporar cambios, Archive Workbench debe poder reconocer un estado previo compartido entre las dos copias o pedirte que resuelvas las diferencias de forma explícita.",
        "Antes de aplicar cambios recibidos, Archive Workbench muestra qué se modificaría y crea una copia de seguridad cuando corresponde.",
    ),
    "admin": (
        "Comprobar la integridad del proyecto y administrar copias de seguridad y recuperación.",
        "Conviene crear una copia de seguridad antes de cambios importantes o actualizaciones.",
        "Volvé a Inicio para revisar el estado general y los próximos pasos.",
    ),
}

_EXCHANGE_STATUS_LABELS = {
    "empty": "Vacío",
    "needs_review": "Requiere decisiones",
    "ready_to_apply": "Listo para aplicar",
    "ready_to_apply_resolved": "Listo para aplicar",
    "ready_to_finalize": "Decisiones completas",
    "resolving": "En resolución",
    "pending": "Pendiente",
    "stale": "Simulación desactualizada",
    "applied": "Aplicado",
    "assessed": "Evaluado",
}

_EXCHANGE_BASE_LABELS = {
    "matched": "Estado previo compartido verificado",
    "unmatched": "Sin estado previo compartido verificado",
}

_EXCHANGE_OPERATION_LABELS = {
    "create": "crear",
    "update": "actualizar",
    "delete": "retirar",
    "restore": "restaurar",
}


def _render_section_guidance(st, app_mode: str) -> None:
    """Muestra orientación contextual sin ocultar controles ni cambiar el flujo de dominio."""

    guidance = _VIEW_GUIDANCE.get(app_mode)
    if guidance is None:
        return
    objective, prerequisite, next_step = guidance
    step_number = _WORKFLOW_STEPS.index(app_mode) + 1
    with st.container(border=True):
        st.caption(
            f"Paso {step_number} de {len(_WORKFLOW_STEPS)} · "
            f"{_VIEW_PHASES[app_mode]}"
        )
        st.write(f"**Objetivo de esta sección:** {objective}")
        with st.expander("Antes de empezar y qué sigue"):
            st.write(f"**Conviene tener:** {prerequisite}")
            st.write(f"**Paso habitual siguiente:** {next_step}")


def _request_workflow_step(st, app_mode: str) -> None:
    request_app_view(st, mode=app_mode)
    rerun_app(st)


def _render_global_input_policy(st) -> None:
    """Oculta instrucciones de teclado que contradicen la política de acciones explícitas."""
    st.markdown(
        """
        <style>
        [data-testid="InputInstructions"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_wrapping_detail(st, label: str, value: object) -> None:
    """Presenta un dato breve sin el recorte con puntos suspensivos de ``st.metric``."""

    with st.container(border=True):
        st.caption(label)
        st.write(f"**{value}**")


def _project_root_from_argv(argv: list[str] | None = None) -> Path | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-root")
    args, _unknown = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    if not args.project_root:
        return None
    return Path(args.project_root).expanduser().resolve()


def _apply_palette(st, palette: str) -> None:
    """No retematiza widgets nativos durante un rerun.

    Las paletas personalizadas se aplican al iniciar Streamlit mediante su sistema
    nativo de temas. Inyectar CSS durante la ejecución deja fuera portales y
    componentes internos, como el calendario, y produce estados visuales incoherentes.
    """

    return None


def _save_preferences_from_values(st, *, actor: str, palette: str) -> bool:
    clean_actor = actor.strip()
    if not clean_actor:
        st.error("Escribí tu nombre antes de guardar las preferencias.")
        return False
    previous = load_user_preferences()
    save_user_preferences(UserPreferences(actor=clean_actor, palette=palette))
    if previous.palette != palette:
        st.success("Preferencias guardadas.")
        st.info(
            "La paleta se aplica con el sistema nativo de temas de Streamlit. "
            "Cerrá y volvé a abrir Archive Workbench para aplicar el cambio a todos los controles."
        )
    else:
        st.success("Preferencias guardadas.")
    return True


def _stage_review_preferences(st, *, actor: str, palette: str) -> None:
    st.session_state["_pending_review_actor"] = actor.strip()
    st.session_state["_pending_review_palette"] = palette


def _apply_staged_review_preferences(st) -> None:
    actor = st.session_state.pop("_pending_review_actor", None)
    palette = st.session_state.pop("_pending_review_palette", None)
    if actor is not None:
        st.session_state["review_actor"] = actor
    if palette is not None:
        st.session_state["review_palette"] = palette


def _render_launcher(st) -> None:
    preferences = load_user_preferences()
    workspace = managed_workspace()
    st.title("Archive Workbench")
    section_heading(st, "Abrir o crear un proyecto", level="subheader")
    if workspace is not None:
        st.caption(
            "Esta instalación guarda los proyectos en `ArchiveWorkbenchData/Projects`. "
            "Los documentos que se incorporan por lote se pueden copiar a "
            "`ArchiveWorkbenchData/Imports/Documents` y los archivos de audio o video a "
            "`ArchiveWorkbenchData/Imports/AudioVideo`."
        )

    actor = st.text_input(
        "Nombre de la persona que va a trabajar",
        value=st.session_state.get("launcher_actor", preferences.actor),
        help="Se usa para registrar quién realizó cada cambio. Podés modificarlo después en Preferencias.",
        key="launcher_actor",
    )
    palette_keys = list(PALETTES)
    default_palette = preferences.palette if preferences.palette in PALETTES else "system"
    palette = st.selectbox(
        "Paleta de colores de la interfaz",
        options=palette_keys,
        index=palette_keys.index(default_palette),
        format_func=lambda value: PALETTES[value],
        key="launcher_palette",
        help=(
            "Sistema respeta el tema general de Streamlit. Las paletas personalizadas "
            "se aplican por completo al volver a abrir Archive Workbench."
        ),
    )
    _apply_palette(st, palette)

    open_tab, create_tab = tracked_tabs(
        st,
        ["Abrir un proyecto existente", "Crear un proyecto nuevo"],
        key="launcher_tabs",
        help_by_label=TAB_HELP["launcher_tabs"],
    )
    with open_tab:
        discovered = []
        seen_projects: set[Path] = set()
        search_roots = (
            (workspace.projects,)
            if workspace is not None
            else (Path.cwd(), Path.home() / "ArchiveWorkbench")
        )
        for search_root in search_roots:
            for candidate in discover_projects(search_root):
                if candidate not in seen_projects:
                    discovered.append(candidate)
                    seen_projects.add(candidate)
        discovered_values = [str(path) for path in discovered]

        if workspace is not None:
            if discovered_values:
                existing_path = st.selectbox(
                    "Proyecto que querés abrir",
                    options=discovered_values,
                    format_func=lambda value: Path(value).name,
                    key="launcher_managed_project",
                )
                st.caption(
                    "La carpeta de este proyecto está dentro de "
                    f"`{workspace_display_path(workspace.projects)}`."
                )
            else:
                existing_path = ""
                st.info(
                    "Todavía no hay proyectos en `ArchiveWorkbenchData/Projects`. "
                    "Podés crear el primero en la pestaña Crear un proyecto nuevo."
                )
        else:
            if discovered_values:
                selected = st.selectbox(
                    "Proyectos encontrados en esta carpeta",
                    options=[""] + discovered_values,
                    format_func=lambda value: "Elegir..." if not value else Path(value).name,
                    key="launcher_discovered_project",
                )
            else:
                selected = ""
                st.caption(
                    "No se encontraron proyectos directamente dentro de la carpeta desde la que abriste Archive Workbench."
                )
            existing_key = "launcher_existing_path"
            pending_existing = st.session_state.pop("_pending_launcher_existing_path", None)
            if pending_existing is not None:
                st.session_state[existing_key] = pending_existing
            elif selected and not st.session_state.get(existing_key):
                st.session_state[existing_key] = selected
            existing_path = st.text_input(
                "Carpeta del proyecto",
                placeholder="/home/usuario/proyectos/mi_proyecto",
                key=existing_key,
            )
            if st.button(
                "Elegir la carpeta del proyecto en la computadora",
                key="launcher_choose_existing_project",
            ):
                selected_existing, selection_error = choose_local_directory(
                    Path(existing_path) if existing_path.strip() else Path.cwd(),
                    title="Elegir carpeta de proyecto",
                )
                if selection_error:
                    st.warning(selection_error)
                elif selected_existing is not None:
                    st.session_state["_pending_launcher_existing_path"] = str(selected_existing)
                    rerun_app(st)

        if st.button(
            "Abrir este proyecto",
            type="primary",
            key="launcher_open_project",
            disabled=not bool(str(existing_path).strip()),
        ):
            clean_actor = actor.strip()
            if not clean_actor:
                st.error("Escribí tu nombre antes de abrir un proyecto.")
            else:
                root = Path(existing_path).expanduser().resolve() if str(existing_path).strip() else None
                if root is None or not root.is_dir():
                    st.error("Elegí una carpeta de proyecto existente.")
                elif not (root / "config" / "decisions.yaml").is_file():
                    st.error("La carpeta elegida no contiene la configuración de un proyecto de Archive Workbench.")
                else:
                    try:
                        require_current_database(root)
                    except DatabaseRevisionError as exc:
                        st.error(str(exc))
                        st.info(
                            "Este proyecto necesita una actualización de su base antes de abrirse. No se actualiza automáticamente porque una migración de un proyecto existente debe protegerse con una copia de seguridad."
                        )
                    else:
                        save_user_preferences(UserPreferences(actor=clean_actor, palette=palette))
                        _stage_review_preferences(st, actor=clean_actor, palette=palette)
                        st.session_state["launcher_project_root"] = str(root)
                        rerun_app(st)

    with create_tab:
        project_name = st.text_input(
            "Nombre del proyecto",
            placeholder="Por ejemplo: Corpus de archivos de la represión",
            key="launcher_new_project_name",
        )
        suggested = suggested_project_id(project_name) if project_name.strip() else ""
        project_id_key = "launcher_new_project_id"
        previous_suggestion = str(
            st.session_state.get("_launcher_previous_project_id_suggestion", "")
        )
        current_project_id = str(st.session_state.get(project_id_key, ""))
        if not current_project_id or current_project_id == previous_suggestion:
            st.session_state[project_id_key] = suggested
        st.session_state["_launcher_previous_project_id_suggestion"] = suggested
        project_id = st.text_input(
            "Identificador interno del proyecto",
            help="Archive Workbench usa este identificador estable para distinguir el proyecto en sus registros. Se propone a partir del nombre y puede modificarse antes de crear el proyecto.",
            key=project_id_key,
        )

        if workspace is not None:
            parent_folder = str(workspace.projects)
            st.caption(
                "El proyecto se guardará dentro de "
                f"`{workspace_display_path(workspace.projects)}`."
            )
        else:
            pending_parent = st.session_state.pop("_pending_launcher_project_parent", None)
            parent_key = "launcher_new_project_parent"
            if pending_parent is not None:
                st.session_state[parent_key] = pending_parent
            st.session_state.setdefault(parent_key, str(Path.cwd().resolve()))
            parent_folder = st.text_input(
                "Carpeta donde se creará el proyecto",
                key=parent_key,
                help="Elegí una carpeta existente. Archive Workbench creará dentro de ella una carpeta nueva para este proyecto.",
            )
            if st.button(
                "Elegir en la computadora la carpeta donde se creará el proyecto",
                key="launcher_choose_project_parent",
            ):
                selected_parent, selection_error = choose_local_directory(
                    Path(parent_folder) if parent_folder.strip() else Path.cwd(),
                    title="Elegir carpeta donde crear el proyecto",
                )
                if selection_error:
                    st.warning(selection_error)
                elif selected_parent is not None:
                    st.session_state["_pending_launcher_project_parent"] = str(selected_parent)
                    rerun_app(st)

        folder_key = "launcher_new_project_folder_name"
        suggested_folder = project_id or "nuevo_proyecto"
        previous_folder_suggestion = str(
            st.session_state.get("_launcher_previous_folder_suggestion", "")
        )
        current_folder = str(st.session_state.get(folder_key, ""))
        if not current_folder or current_folder == previous_folder_suggestion:
            st.session_state[folder_key] = suggested_folder
        st.session_state["_launcher_previous_folder_suggestion"] = suggested_folder
        folder_name = st.text_input(
            "Nombre de la carpeta del proyecto",
            key=folder_key,
            help="La carpeta debe ser nueva. Podés cambiar este nombre antes de crear el proyecto.",
        )
        root_preview = (
            Path(parent_folder).expanduser() / folder_name.strip()
            if parent_folder.strip() and folder_name.strip()
            else None
        )
        if root_preview is not None:
            st.caption(f"El proyecto se creará en: {workspace_display_path(root_preview)}")
        st.caption(
            "Archive Workbench creará las carpetas necesarias, copiará una configuración inicial y preparará la base local. No hace falta editar archivos YAML ni ejecutar una migración por terminal."
        )
        if st.button("Crear este proyecto", type="primary", key="launcher_create_project"):
            clean_actor = actor.strip()
            if not clean_actor:
                st.error("Escribí tu nombre antes de crear un proyecto.")
            elif not project_name.strip():
                st.error("Escribí un nombre para el proyecto.")
            elif not project_id.strip():
                st.error("El identificador interno del proyecto no puede quedar vacío.")
            elif not parent_folder.strip():
                st.error("Elegí la carpeta donde querés crear el proyecto.")
            elif not folder_name.strip():
                st.error("Escribí un nombre para la carpeta del proyecto.")
            else:
                parent = Path(parent_folder).expanduser().resolve()
                if not parent.is_dir():
                    st.error("La carpeta elegida no existe. Elegí una carpeta existente.")
                else:
                    root = (parent / folder_name.strip()).resolve()
                    if root.exists():
                        st.error(
                            "La carpeta del proyecto ya existe. Elegí otro nombre para evitar mezclar o reemplazar un proyecto anterior."
                        )
                    else:
                        try:
                            create_ready_project(
                                root,
                                project_name=project_name,
                                project_id=project_id,
                            )
                        except (ValueError, OSError, RuntimeError, FileExistsError) as exc:
                            st.error(str(exc))
                        else:
                            save_user_preferences(UserPreferences(actor=clean_actor, palette=palette))
                            _stage_review_preferences(st, actor=clean_actor, palette=palette)
                            st.session_state["launcher_project_root"] = str(root)
                            st.success("Proyecto creado. Abriendo la interfaz...")
                            rerun_app(st)

def _render_preferences(st, *, current_actor: str, current_palette: str) -> tuple[str, str]:
    actor_key = "review_actor"
    palette_key = "review_palette"
    st.session_state.setdefault(actor_key, current_actor)
    st.session_state.setdefault(palette_key, current_palette)
    with st.popover("Preferencias", use_container_width=True):
        actor = st.text_input("Nombre de la persona que está trabajando", key=actor_key)
        palette = st.selectbox(
            "Paleta de colores de la interfaz",
            options=list(PALETTES),
            format_func=lambda value: PALETTES[value],
            key=palette_key,
            help=(
                "Sistema respeta el tema general de Streamlit. Las otras paletas se aplican "
                "de forma nativa al volver a abrir Archive Workbench."
            ),
        )
        if st.button("Guardar estas preferencias", key="review_save_preferences"):
            _save_preferences_from_values(st, actor=actor, palette=palette)
    return str(st.session_state.get(actor_key, "")).strip(), str(
        st.session_state.get(palette_key, "system")
    )

def _require_reviewer_name(st, *, reviewer: str, palette: str) -> None:
    """Impide entrar en las vistas del proyecto sin una identidad explícita."""

    if reviewer.strip():
        return

    st.error("Antes de continuar, escribí tu nombre. Se usará para registrar los cambios.")
    required_actor = st.text_input(
        "Tu nombre para continuar",
        key="required_review_actor",
        placeholder="Nombre de la persona que está trabajando",
    )
    if st.button(
        "Guardar nombre y continuar",
        key="required_review_actor_save",
        use_container_width=True,
        type="primary",
    ):
        clean_actor = required_actor.strip()
        if not clean_actor:
            st.error("Escribí tu nombre para continuar.")
        else:
            save_user_preferences(UserPreferences(actor=clean_actor, palette=palette))
            _stage_review_preferences(st, actor=clean_actor, palette=palette)
            rerun_app(st)
    st.stop()


def _snippet(text: str, limit: int = 72) -> str:
    compact = " ".join(text.split())
    if not compact:
        return "[sin texto]"
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _object_label(item: ReviewObjectRow, labels: dict[str, str]) -> str:
    state = " · eliminado" if item.lifecycle_status == "deleted" else ""
    review = _STATUS_LABELS.get(item.review_status, item.review_status)
    annotations = []
    if item.tags:
        annotations.append(
            ", ".join(
                f"{_TAG_KIND_LABELS.get(tag.tag_kind, tag.tag_kind)}: #{tag.tag}"
                for tag in item.tags[:3]
            )
        )
    if item.comment_count:
        annotations.append(f"{item.comment_count} com.")
    if item.document_part_key:
        annotations.append("parte " + item.document_part_key)
    suffix = " · " + " · ".join(annotations) if annotations else ""
    return (
        f"{item.order_index + 1}. {labels.get(item.object_type, item.object_type)}"
        f" · rev {item.revision_number} · {review}{state}{suffix} · {_snippet(item.text)}"
    )


def _pending_selection_key(selection_key: str) -> str:
    return selection_key + "__pending"


def _run_action(
    st,
    action: Callable[[], str | None],
    *,
    selection_key: str | None = None,
    fallback_selection: str | None = None,
) -> None:
    try:
        selected = action()
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
    else:
        selection = selected or fallback_selection
        if selection_key and selection:
            # No se modifica la clave del widget ya instanciado. La selección se
            # aplica al comienzo del siguiente rerun, antes de crear el selectbox.
            st.session_state[_pending_selection_key(selection_key)] = selection
        rerun_view(st)


def _database_action(db_path: Path, callback: Callable) -> str | None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            result = callback(session)
            if isinstance(result, str):
                return result
            object_id = getattr(result, "id", None)
            return str(object_id) if object_id else None
    finally:
        engine.dispose()




_LAYOUT_HISTORY_LABELS = {
    "apply_layout_proposal": "Confirmó columnas y aplicó el orden",
    "create_layout_column": "Creó una columna manual",
    "create_and_assign_layout_column": "Creó una columna manual y asignó el bloque de texto seleccionado",
    "assign_layout_column": "Asignó el bloque de texto seleccionado a una columna",
    "rename_layout_column": "Renombró una columna",
    "archive_layout_column": "Archivó una columna",
    "merge_layout_fragment": "Combinó una fragmentación",
    "archive_layout_duplicate": "Archivó un duplicado",
}


def _layout_history_label(row) -> str:
    if row.operation == "undo":
        return "Deshizo la última acción"
    if row.operation == "redo":
        return "Rehizo la última acción"
    action = str((row.details or {}).get("action") or "")
    return _LAYOUT_HISTORY_LABELS.get(action, action or "Actualizó la estructura")


def _render_layout_structure_panel(
    st,
    *,
    db_path: Path,
    view,
    selected: ReviewObjectRow,
    objects_by_id: dict[str, ReviewObjectRow],
    reviewer: str,
    object_state_key: str,
    mode: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            proposal = layout_proposal(session, editable_page_id=view.editable_page_id)
            structure = layout_structure(session, editable_page_id=view.editable_page_id)
            history = layout_structure_history(
                session, editable_page_id=view.editable_page_id
            )
    finally:
        engine.dispose()

    active_columns = sorted(
        (item for item in structure.columns if item.lifecycle_status == "active"),
        key=lambda item: (item.order_index, item.column_id),
    )

    if mode == "proposal":
        summary_parts = [
            f"{len(proposal.columns)} columna(s) propuesta(s)",
            f"{proposal.changed_positions} cambio(s) de orden",
        ]
        if proposal.unassigned_object_ids:
            summary_parts.append(
                f"{len(proposal.unassigned_object_ids)} texto(s) sin posición reconocida"
            )
        if proposal.fragment_candidates:
            summary_parts.append(
                f"{len(proposal.fragment_candidates)} posible(s) fragmentación(es)"
            )
        if proposal.duplicate_candidates:
            summary_parts.append(
                f"{len(proposal.duplicate_candidates)} posible(s) duplicado(s)"
            )
        st.caption(" · ".join(summary_parts))

        if view.preview_path is not None and proposal.columns:
            overlay = render_layout_overlay(
                view.preview_path,
                view.objects,
                proposal=proposal,
                page_number=view.page,
            )
            st.image(overlay, use_container_width=True)

        column_by_object = {
            object_id: column.label
            for column in proposal.columns
            for object_id in column.object_ids
        }
        proposed_rows = []
        for position, object_id in enumerate(proposal.proposed_order, start=1):
            item = objects_by_id.get(object_id)
            proposed_rows.append(
                {
                    "Propuesto": position,
                    "Actual": (item.order_index + 1) if item is not None else None,
                    "Columna": column_by_object.get(
                        object_id, "Sin posición reconocida"
                    ),
                    "Tipo": item.object_type if item is not None else "",
                    "Texto": _snippet(item.text, 90) if item is not None else object_id,
                }
            )
        if proposed_rows:
            with st.expander("Ver detalle del orden propuesto", expanded=False):
                st.dataframe(proposed_rows, hide_index=True, use_container_width=True)

        with st.form(f"apply_layout_{view.editable_page_id}", enter_to_submit=False):
            layout_note = st.text_input(
                "Evidencia o nota de revisión (opcional)",
                key=f"layout_apply_note_{view.editable_page_id}",
            )
            apply_layout = st.form_submit_button(
                "Confirmar columnas y aplicar orden",
                type="primary",
                disabled=not proposal.proposed_order,
            )
        if apply_layout:
            def apply_callback(session):
                return execute_page_action(
                    session,
                    editable_page_id=view.editable_page_id,
                    action_type="layout",
                    changed_by=reviewer,
                    selected_object_id=selected.object_id,
                    note=layout_note or None,
                    action=lambda: apply_layout_proposal(
                        session,
                        editable_page_id=view.editable_page_id,
                        changed_by=reviewer,
                        note=layout_note or None,
                    ),
                )

            _run_action(
                st,
                lambda: _database_action(db_path, apply_callback),
                selection_key=object_state_key,
                fallback_selection=selected.object_id,
            )

        with st.expander("Detalles técnicos", expanded=False):
            st.caption(
                f"Algoritmo `{proposal.algorithm}` · confianza calculada {proposal.confidence:.1%} · "
                f"identificador técnico `{proposal.fingerprint[:12]}…`"
            )
        return

    if mode == "columns":
        active_column_map = {item.column_id: item for item in active_columns}
        current_column_id = next(
            (
                column.column_id
                for column in active_columns
                if selected.object_id in column.object_ids
            ),
            None,
        )
        current_column_label = (
            active_column_map[current_column_id].label
            if current_column_id is not None
            else "Sin columna"
        )
        st.caption(f"Columna del texto seleccionado: **{current_column_label}**")

        if active_columns:
            st.dataframe(
                [
                    {
                        "Orden": column.order_index + 1,
                        "Columna": column.label,
                        "Textos": len(column.object_ids),
                    }
                    for column in active_columns
                ],
                hide_index=True,
                use_container_width=True,
            )
            with st.expander("Procedencia de las columnas", expanded=False):
                st.dataframe(
                    [
                        {
                            "Columna": column.label,
                            "Origen": column.source,
                            "Evidencia": column.evidence_note or "",
                        }
                        for column in active_columns
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
        else:
            st.info("Todavía no hay columnas confirmadas para esta página.")

        action_options = ["create"]
        if active_columns:
            action_options.extend(["move", "manage"])
        action = st.radio(
            "Acción sobre las columnas",
            options=action_options,
            horizontal=True,
            format_func=lambda value: {
                "create": "Crear una columna para este texto",
                "move": "Mover este texto",
                "manage": "Renombrar o archivar una columna",
            }[value],
            key=f"layout_column_action_{view.editable_page_id}_{selected.object_id}",
        )

        if action == "create":
            with st.form(
                f"create_layout_column_{view.editable_page_id}_{selected.object_id}",
                enter_to_submit=False,
            ):
                create_cols = st.columns([1, 1.3])
                new_column_label = create_cols[0].text_input(
                    "Nombre de la nueva columna",
                    key=f"layout_new_column_{view.editable_page_id}_{selected.object_id}",
                )
                new_column_note = create_cols[1].text_input(
                    "Nota (opcional)",
                    key=f"layout_new_column_note_{view.editable_page_id}_{selected.object_id}",
                )
                create_column = st.form_submit_button(
                    "Crear la columna y asignarle este texto"
                )
            if create_column:
                def create_and_assign_callback(session):
                    return execute_page_action(
                        session,
                        editable_page_id=view.editable_page_id,
                        action_type="layout",
                        changed_by=reviewer,
                        selected_object_id=selected.object_id,
                        note=new_column_note or None,
                        action=lambda: (
                            create_layout_column_for_object(
                                session,
                                editable_page_id=view.editable_page_id,
                                object_id=selected.object_id,
                                label=new_column_label,
                                changed_by=reviewer,
                                note=new_column_note or None,
                            ),
                            selected.object_id,
                        )[1],
                    )

                _run_action(
                    st,
                    lambda: _database_action(db_path, create_and_assign_callback),
                    selection_key=object_state_key,
                    fallback_selection=selected.object_id,
                )
            return

        if action == "move":
            assignment_options = [None, *active_column_map]
            with st.form(
                f"layout_assign_{selected.object_id}_{selected.revision_number}",
                enter_to_submit=False,
            ):
                move_cols = st.columns([1, 1.3])
                target_column_id = move_cols[0].selectbox(
                    "Columna de destino",
                    options=assignment_options,
                    index=assignment_options.index(current_column_id),
                    format_func=lambda value: (
                        "Sin columna"
                        if value is None
                        else active_column_map[value].label
                    ),
                )
                assignment_note = move_cols[1].text_input(
                    "Nota (opcional)"
                )
                assign_column = st.form_submit_button(
                    "Guardar la columna de este texto"
                )
            if assign_column:
                def assign_callback(session):
                    return execute_page_action(
                        session,
                        editable_page_id=view.editable_page_id,
                        action_type="layout",
                        changed_by=reviewer,
                        selected_object_id=selected.object_id,
                        note=assignment_note or None,
                        action=lambda: assign_object_to_column(
                            session,
                            editable_page_id=view.editable_page_id,
                            object_id=selected.object_id,
                            column_id=target_column_id,
                            changed_by=reviewer,
                            note=assignment_note or None,
                        ),
                    )

                _run_action(
                    st,
                    lambda: _database_action(db_path, assign_callback),
                    selection_key=object_state_key,
                    fallback_selection=selected.object_id,
                )
            return

        selected_column_id = st.selectbox(
            "Columna",
            options=list(active_column_map),
            format_func=lambda value: active_column_map[value].label,
            key=f"layout_manage_column_{view.editable_page_id}",
        )
        column = active_column_map[selected_column_id]
        with st.form(
            f"layout_column_{column.column_id}_{column.updated_at.isoformat()}",
            enter_to_submit=False,
        ):
            manage_cols = st.columns([1, 1.3])
            renamed = manage_cols[0].text_input(
                "Nombre de la columna",
                value=column.label,
                key=f"layout_rename_{column.column_id}",
            )
            note = manage_cols[1].text_input(
                "Nota (opcional)",
                value=column.evidence_note or "",
                key=f"layout_column_note_{column.column_id}",
            )
            rename_submit = st.form_submit_button("Guardar nombre")
            archive_submit = st.form_submit_button("Archivar columna")
        if rename_submit:
            _run_action(
                st,
                lambda: _database_action(
                    db_path,
                    lambda session: rename_layout_column(
                        session,
                        editable_page_id=view.editable_page_id,
                        column_id=column.column_id,
                        label=renamed,
                        changed_by=reviewer,
                        note=note or None,
                    ),
                ),
                selection_key=object_state_key,
                fallback_selection=selected.object_id,
            )
        if archive_submit:
            _run_action(
                st,
                lambda: _database_action(
                    db_path,
                    lambda session: archive_layout_column(
                        session,
                        editable_page_id=view.editable_page_id,
                        column_id=column.column_id,
                        changed_by=reviewer,
                        note=note or None,
                    ),
                ),
                selection_key=object_state_key,
                fallback_selection=selected.object_id,
            )
        return

    if mode == "issues":
        if not proposal.fragment_candidates and not proposal.duplicate_candidates:
            st.success("No se detectaron posibles fragmentaciones ni duplicados en esta página.")
            return
        for candidate in proposal.fragment_candidates:
            st.warning(
                f"Posible fragmentación en columna {candidate.column_index + 1}: "
                f"{candidate.text_preview}"
            )
            if st.button(
                "Combinar secuencia confirmada",
                key=f"merge_layout_fragment_{candidate.fingerprint}",
            ):
                def merge_callback(session, fingerprint=candidate.fingerprint):
                    return execute_page_action(
                        session,
                        editable_page_id=view.editable_page_id,
                        action_type="merge",
                        changed_by=reviewer,
                        selected_object_id=candidate.object_ids[0],
                        action=lambda: merge_fragment_candidate(
                            session,
                            editable_page_id=view.editable_page_id,
                            fingerprint=fingerprint,
                            changed_by=reviewer,
                        ),
                    )

                _run_action(
                    st,
                    lambda: _database_action(db_path, merge_callback),
                    selection_key=object_state_key,
                    fallback_selection=candidate.object_ids[0],
                )
        for candidate in proposal.duplicate_candidates:
            st.warning(
                f"Posible duplicado ({candidate.overlap:.0%} de superposición): "
                f"{candidate.text_preview}"
            )
            if st.button(
                "Confirmar y archivar duplicado",
                key=f"archive_layout_duplicate_{candidate.fingerprint}",
            ):
                def duplicate_callback(
                    session,
                    fingerprint=candidate.fingerprint,
                    keep_object_id=candidate.keep_object_id,
                ):
                    execute_page_action(
                        session,
                        editable_page_id=view.editable_page_id,
                        action_type="delete",
                        changed_by=reviewer,
                        selected_object_id=keep_object_id,
                        action=lambda: archive_duplicate_candidate(
                            session,
                            editable_page_id=view.editable_page_id,
                            fingerprint=fingerprint,
                            changed_by=reviewer,
                        ),
                    )
                    return keep_object_id

                _run_action(
                    st,
                    lambda: _database_action(db_path, duplicate_callback),
                    selection_key=object_state_key,
                    fallback_selection=candidate.keep_object_id,
                )
        return

    if mode == "history":
        if history:
            st.dataframe(
                [
                    {
                        "Revisión": row.revision_number,
                        "Acción": _layout_history_label(row),
                        "Columnas activas": row.active_column_count,
                        "Textos asignados": row.assigned_object_count,
                        "Responsable": row.created_by,
                        "Fecha": row.created_at.isoformat(),
                        "Nota": row.note or "",
                    }
                    for row in history
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption("Todavía no hay revisiones de orden o estructura.")
        return

    raise ValueError(f"Modo de orden y estructura no reconocido: {mode}")


def _render_document_part_panel(
    st,
    *,
    db_path: Path,
    view,
    selected: ReviewObjectRow,
    reviewer: str,
    object_state_key: str,
) -> None:
    if not view.parts:
        st.info("Esta página no pertenece a una parte interna registrada.")
        return

    part_map = {item.part_id: item for item in view.parts}
    part_options = [None, *part_map]
    current_part = (
        selected.document_part_id if selected.document_part_id in part_map else None
    )
    scope = st.radio(
        "Alcance",
        options=["text", "page"],
        horizontal=True,
        format_func=lambda value: {
            "text": "Sólo este texto",
            "page": "Toda la página",
        }[value],
        key=f"review_part_scope_{view.editable_page_id}_{selected.object_id}",
    )
    if scope == "text":
        with st.form(
            f"assign_part_{selected.object_id}_{selected.revision_number}",
            enter_to_submit=False,
        ):
            part_cols = st.columns([1, 1.3])
            selected_part_id = part_cols[0].selectbox(
                "Parte del documento",
                options=part_options,
                index=part_options.index(current_part),
                format_func=lambda value: (
                    "Sin asignar"
                    if value is None
                    else f"{part_map[value].title} · {part_map[value].part_type}"
                ),
            )
            part_note = part_cols[1].text_input("Nota (opcional)")
            assign_part_submit = st.form_submit_button(
                "Guardar la parte de este texto"
            )
        if assign_part_submit:
            def assign_part_callback(session):
                return execute_page_action(
                    session,
                    editable_page_id=view.editable_page_id,
                    action_type="assign_part",
                    changed_by=reviewer,
                    selected_object_id=selected.object_id,
                    note=part_note or None,
                    action=lambda: assign_editable_object_part(
                        session,
                        object_id=selected.object_id,
                        part_id=selected_part_id,
                        expected_revision=selected.revision_number,
                        changed_by=reviewer,
                        note=part_note or None,
                    ),
                )

            _run_action(
                st,
                lambda: _database_action(db_path, assign_part_callback),
                selection_key=object_state_key,
                fallback_selection=selected.object_id,
            )
        return

    with st.form(f"assign_page_part_{view.editable_page_id}", enter_to_submit=False):
        page_cols = st.columns([1, 1.3])
        page_part_id = page_cols[0].selectbox(
            "Parte del documento",
            options=part_options,
            format_func=lambda value: (
                "Sin asignar"
                if value is None
                else f"{part_map[value].title} · {part_map[value].part_type}"
            ),
            key=f"page_part_choice_{view.editable_page_id}",
        )
        bulk_note = page_cols[1].text_input(
            "Nota (opcional)",
            key=f"page_part_note_{view.editable_page_id}",
        )
        bulk_part_submit = st.form_submit_button(
            "Asignar esta parte a todos los textos de la página"
        )
    if bulk_part_submit:
        def bulk_part_callback(session):
            return execute_page_action(
                session,
                editable_page_id=view.editable_page_id,
                action_type="assign_part",
                changed_by=reviewer,
                selected_object_id=selected.object_id,
                note=bulk_note or None,
                action=lambda: assign_page_objects_to_part(
                    session,
                    editable_page_id=view.editable_page_id,
                    part_id=page_part_id,
                    changed_by=reviewer,
                    note=bulk_note or None,
                ),
            )

        _run_action(
            st,
            lambda: _database_action(db_path, bulk_part_callback),
            selection_key=object_state_key,
            fallback_selection=selected.object_id,
        )


def _render_move_text_panel(
    st,
    *,
    db_path: Path,
    view,
    selected: ReviewObjectRow,
    reviewer: str,
    object_state_key: str,
) -> None:
    active_orders = [
        item.order_index for item in view.objects if item.lifecycle_status == "active"
    ]
    move_left, move_right = st.columns(2)
    move_up = move_left.button(
        "↑ Mover una posición hacia arriba",
        use_container_width=True,
        disabled=selected.lifecycle_status != "active" or selected.order_index <= 0,
        key=f"move_up_{selected.object_id}_{selected.revision_number}",
    )
    move_down = move_right.button(
        "↓ Mover una posición hacia abajo",
        use_container_width=True,
        disabled=(
            selected.lifecycle_status != "active"
            or not active_orders
            or selected.order_index >= max(active_orders)
        ),
        key=f"move_down_{selected.object_id}_{selected.revision_number}",
    )
    if move_up or move_down:
        direction = "up" if move_up else "down"

        def move_callback(session):
            return execute_page_action(
                session,
                editable_page_id=view.editable_page_id,
                action_type="reorder",
                changed_by=reviewer,
                selected_object_id=selected.object_id,
                action=lambda: move_editable_object(
                    session,
                    object_id=selected.object_id,
                    expected_revision=selected.revision_number,
                    direction=direction,
                    changed_by=reviewer,
                ),
            )

        _run_action(
            st,
            lambda: _database_action(db_path, move_callback),
            selection_key=object_state_key,
            fallback_selection=selected.object_id,
        )


def _render_merge_text_panel(
    st,
    *,
    db_path: Path,
    view,
    selected: ReviewObjectRow,
    reviewer: str,
    object_state_key: str,
) -> None:
    active_orders = [
        item.order_index for item in view.objects if item.lifecycle_status == "active"
    ]
    separator_label = st.selectbox(
        "Separación entre los textos",
        options=["blank_line", "line", "space", "none"],
        format_func=lambda value: {
            "blank_line": "Línea en blanco",
            "line": "Salto de línea",
            "space": "Espacio",
            "none": "Sin separación",
        }[value],
        key=f"merge_separator_{selected.object_id}",
    )
    separators = {"blank_line": "\n\n", "line": "\n", "space": " ", "none": ""}
    merge_previous_col, merge_next_col = st.columns(2)
    merge_previous = merge_previous_col.button(
        "Combinar con el texto anterior",
        use_container_width=True,
        disabled=selected.lifecycle_status != "active" or selected.order_index <= 0,
        key=f"merge_prev_{selected.object_id}_{selected.revision_number}",
    )
    merge_next = merge_next_col.button(
        "Combinar con el texto siguiente",
        use_container_width=True,
        disabled=(
            selected.lifecycle_status != "active"
            or not active_orders
            or selected.order_index >= max(active_orders)
        ),
        key=f"merge_next_{selected.object_id}_{selected.revision_number}",
    )
    if merge_previous or merge_next:
        direction = "previous" if merge_previous else "next"

        def merge_callback(session):
            return execute_page_action(
                session,
                editable_page_id=view.editable_page_id,
                action_type="merge",
                changed_by=reviewer,
                selected_object_id=selected.object_id,
                action=lambda: merge_editable_object(
                    session,
                    object_id=selected.object_id,
                    expected_revision=selected.revision_number,
                    direction=direction,
                    separator=separators[separator_label],
                    changed_by=reviewer,
                ),
            )

        _run_action(
            st,
            lambda: _database_action(db_path, merge_callback),
            selection_key=object_state_key,
            fallback_selection=selected.object_id,
        )


def _render_split_text_panel(
    st,
    *,
    db_path: Path,
    view,
    selected: ReviewObjectRow,
    reviewer: str,
    object_state_key: str,
) -> None:
    split_marker = "[[DIVIDIR]]"
    with st.form(f"split_{selected.object_id}_{selected.revision_number}", enter_to_submit=False):
        split_source = st.text_area(
            f"Texto · insertá {split_marker} en el punto de división",
            value=selected.text,
            height=250,
        )
        split_note = st.text_input("Nota (opcional)")
        split_submit = st.form_submit_button(
            "Dividir este texto en dos",
            disabled=selected.lifecycle_status != "active",
        )
    if split_submit:
        if split_source.count(split_marker) != 1:
            st.error(f"El texto debe contener exactamente una marca {split_marker}.")
        else:
            left_text, right_text = split_source.split(split_marker, 1)

            def split_callback(session):
                return execute_page_action(
                    session,
                    editable_page_id=view.editable_page_id,
                    action_type="split",
                    changed_by=reviewer,
                    selected_object_id=selected.object_id,
                    note=split_note or None,
                    action=lambda: split_editable_object(
                        session,
                        object_id=selected.object_id,
                        expected_revision=selected.revision_number,
                        left_text=left_text,
                        right_text=right_text,
                        changed_by=reviewer,
                        note=split_note or None,
                    ),
                )

            _run_action(
                st,
                lambda: _database_action(db_path, split_callback),
                selection_key=object_state_key,
                fallback_selection=selected.object_id,
            )


def _render_form_structure_tab(
    st,
    *,
    db_path: Path,
    view,
    selected: ReviewObjectRow,
    objects_by_id: dict[str, ReviewObjectRow],
    reviewer: str,
    object_state_key: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            structure = form_structure(session, editable_page_id=view.editable_page_id)
            candidates = form_candidates(session, editable_page_id=view.editable_page_id)
            history = form_structure_history(
                session, editable_page_id=view.editable_page_id
            )
    finally:
        engine.dispose()


    active_groups = [
        item for item in structure.groups if item.lifecycle_status == "active"
    ]
    active_controls = [
        item for item in structure.controls if item.lifecycle_status == "active"
    ]
    group_map = {item.group_id: item for item in active_groups}
    object_options = [
        object_id
        for object_id, item in objects_by_id.items()
        if item.lifecycle_status == "active"
    ]

    pending_count = sum(not item.already_registered for item in candidates)
    st.caption(
        f"{len(active_controls)} casillero(s) confirmado(s) · "
        f"{len(active_groups)} grupo(s) · {pending_count} posible(s) casillero(s) pendiente(s)"
    )
    st.caption(
        "Casilleros y grupos describen la estructura de páginas que funcionan como formularios. "
        "Las detecciones automáticas siguen siendo propuestas hasta que una persona las confirma."
    )

    pending = [item for item in candidates if not item.already_registered]
    form_task_labels = {
        "candidate": "Revisar casilleros detectados",
        "manual": "Agregar un casillero manualmente",
        "confirmed": "Revisar casilleros confirmados",
        "groups": "Administrar grupos de casilleros",
        "history": "Historial de casilleros y grupos",
    }
    form_task_key = f"review_form_task_{view.editable_page_id}"
    default_form_task = (
        "candidate" if pending else "confirmed" if active_controls else "manual"
    )
    if st.session_state.get(form_task_key) not in form_task_labels:
        st.session_state[form_task_key] = default_form_task
    form_task = st.selectbox(
        "Tarea con casilleros y campos",
        options=list(form_task_labels),
        format_func=lambda value: form_task_labels[value],
        key=form_task_key,
    )
    form_task_label = form_task_labels[form_task]
    mount_choice_help(
        st,
        key=form_task_key,
        label=form_task_label,
        help_text=TASK_HELP["review_form_task"][form_task_label],
    )

    if form_task == "candidate":
        with st.container(border=True):
            if not pending:
                st.info("No hay nuevos casilleros detectados para revisar en esta página.")
            else:
                candidate_map = {item.fingerprint: item for item in pending}
                candidate_id = st.selectbox(
                    "Posible casillero",
                    options=list(candidate_map),
                    format_func=lambda value: (
                        f"{candidate_map[value].state} · "
                        f"{candidate_map[value].label or '[sin rótulo]'} · "
                        f"{candidate_map[value].method}"
                    ),
                    key=f"form_candidate_{view.editable_page_id}",
                )
                candidate = candidate_map[candidate_id]
                group_options = [None, *group_map]
                with st.form(
                    f"confirm_form_candidate_{view.editable_page_id}_{candidate_id}",
                    enter_to_submit=False,
                ):
                    state = st.selectbox(
                        "Estado del casillero",
                        options=["marked", "unmarked", "indeterminate"],
                        index=["marked", "unmarked", "indeterminate"].index(
                            candidate.state
                        ),
                        format_func=lambda value: {
                            "marked": "Marcado",
                            "unmarked": "No marcado",
                            "indeterminate": "Indeterminado",
                        }[value],
                    )
                    label = st.text_input(
                        "Rótulo del casillero", value=candidate.label or ""
                    )
                    group_id = st.selectbox(
                        "Grupo de casilleros existente",
                        options=group_options,
                        format_func=lambda value: (
                            "Sin grupo" if value is None else group_map[value].label
                        ),
                    )
                    new_group_label = st.text_input(
                        "Crear o reutilizar grupo por nombre (opcional)"
                    )
                    evidence = st.text_area(
                        "Evidencia o nota de revisión",
                        value=f"Detección {candidate.method}: {candidate.marker or ''}".strip(),
                        height=90,
                    )
                    confirm_submit = st.form_submit_button(
                        "Confirmar este casillero", type="primary"
                    )
                if confirm_submit:
                    def confirm_callback(session):
                        def action():
                            target_group = group_id
                            if new_group_label.strip():
                                target_group = ensure_group(
                                    session,
                                    editable_page_id=view.editable_page_id,
                                    label=new_group_label,
                                    changed_by=reviewer or "local_user",
                                    note=evidence or None,
                                )
                            return register_control(
                                session,
                                editable_page_id=view.editable_page_id,
                                state=state,
                                label=label,
                                changed_by=reviewer or "local_user",
                                marker_object_id=candidate.marker_object_id,
                                label_object_id=candidate.label_object_id,
                                group_id=target_group,
                                source="candidate",
                                candidate_fingerprint=candidate.fingerprint,
                                candidate_method=candidate.method,
                                marker_text=candidate.marker,
                                evidence_note=evidence or None,
                            )
                        execute_page_action(
                            session,
                            editable_page_id=view.editable_page_id,
                            action_type="form_structure",
                            changed_by=reviewer or "local_user",
                            selected_object_id=(
                                candidate.label_object_id or candidate.marker_object_id
                            ),
                            note=evidence or None,
                            action=action,
                        )
                        return candidate.label_object_id or candidate.marker_object_id
                    _run_action(
                        st,
                        lambda: _database_action(db_path, confirm_callback),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

    if form_task == "manual":
        with st.container(border=True):
            st.caption(
                "Usá esta opción cuando la página contiene un casillero real que no aparece entre los casilleros detectados. Elegí qué bloque de texto contiene el rótulo del casillero, qué bloque contiene la marca si la hay y cuál es su estado."
            )
            if not object_options:
                st.info("La página no tiene bloques de texto disponibles para identificar el rótulo o la marca de un casillero.")
            else:
                marker_options = [None, *object_options]
                default_label_index = (
                    object_options.index(selected.object_id)
                    if selected.object_id in object_options
                    else 0
                )
                with st.form(
                    f"manual_form_control_{view.editable_page_id}",
                    enter_to_submit=False,
                ):
                    label_object_id = st.selectbox(
                        "Bloque de texto que contiene el rótulo del casillero",
                        options=object_options,
                        index=default_label_index,
                        format_func=lambda value: _snippet(objects_by_id[value].text),
                    )
                    marker_object_id = st.selectbox(
                        "Bloque de texto que contiene la marca del casillero (opcional)",
                        options=marker_options,
                        format_func=lambda value: (
                            "Sin bloque de texto para la marca"
                            if value is None
                            else _snippet(objects_by_id[value].text)
                        ),
                    )
                    state = st.selectbox(
                        "Estado del casillero",
                        options=["marked", "unmarked", "indeterminate"],
                        format_func=lambda value: {
                            "marked": "Marcado",
                            "unmarked": "No marcado",
                            "indeterminate": "Indeterminado",
                        }[value],
                    )
                    label = st.text_input(
                        "Texto que funcionará como rótulo del casillero",
                        value=objects_by_id[label_object_id].text,
                    )
                    group_id = st.selectbox(
                        "Grupo de casilleros existente",
                        options=[None, *group_map],
                        format_func=lambda value: (
                            "Sin grupo" if value is None else group_map[value].label
                        ),
                    )
                    new_group_label = st.text_input(
                        "Nombre de un grupo de casilleros nuevo o existente (opcional)",
                        key=f"manual_new_group_{view.editable_page_id}",
                    )
                    evidence = st.text_area("Evidencia o nota sobre este casillero", height=90)
                    manual_submit = st.form_submit_button("Registrar este casillero en la estructura de la página")
                if manual_submit:
                    def manual_callback(session):
                        def action():
                            target_group = group_id
                            if new_group_label.strip():
                                target_group = ensure_group(
                                    session,
                                    editable_page_id=view.editable_page_id,
                                    label=new_group_label,
                                    changed_by=reviewer or "local_user",
                                    note=evidence or None,
                                )
                            return register_control(
                                session,
                                editable_page_id=view.editable_page_id,
                                state=state,
                                label=label,
                                changed_by=reviewer or "local_user",
                                marker_object_id=marker_object_id,
                                label_object_id=label_object_id,
                                group_id=target_group,
                                source="manual",
                                evidence_note=evidence or None,
                            )
                        execute_page_action(
                            session,
                            editable_page_id=view.editable_page_id,
                            action_type="form_structure",
                            changed_by=reviewer or "local_user",
                            selected_object_id=label_object_id,
                            note=evidence or None,
                            action=action,
                        )
                        return label_object_id
                    _run_action(
                        st,
                        lambda: _database_action(db_path, manual_callback),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

    if form_task == "confirmed":
        st.write("**Casilleros ya confirmados para esta página**")
        if not active_controls:
            st.caption("Todavía no hay casilleros confirmados.")
        else:
            control_map = {item.control_id: item for item in active_controls}
            control_id = st.selectbox(
                "Casillero que querés editar",
                options=list(control_map),
                format_func=lambda value: (
                    f"{control_map[value].label} · "
                    f"{control_map[value].state} · "
                    f"{group_map[control_map[value].group_id].label if control_map[value].group_id in group_map else 'sin grupo'}"
                ),
                key=f"form_control_{view.editable_page_id}",
            )
            control = control_map[control_id]
            with st.form(
                f"update_form_control_{view.editable_page_id}_{control_id}",
                enter_to_submit=False,
            ):
                state = st.selectbox(
                    "Estado del casillero",
                    options=["marked", "unmarked", "indeterminate"],
                    index=["marked", "unmarked", "indeterminate"].index(control.state),
                    format_func=lambda value: {
                        "marked": "Marcado",
                        "unmarked": "No marcado",
                        "indeterminate": "Indeterminado",
                    }[value],
                )
                label = st.text_input("Rótulo del casillero", value=control.label)
                group_options = [None, *group_map]
                current_group = control.group_id if control.group_id in group_map else None
                group_id = st.selectbox(
                    "Grupo de casilleros",
                    options=group_options,
                    index=group_options.index(current_group),
                    format_func=lambda value: (
                        "Sin grupo" if value is None else group_map[value].label
                    ),
                )
                evidence = st.text_area(
                    "Evidencia o nota sobre este casillero", value=control.evidence_note or "", height=90
                )
                update_submit = st.form_submit_button("Guardar cambios de este casillero")
            if update_submit:
                def update_callback(session):
                    execute_page_action(
                        session,
                        editable_page_id=view.editable_page_id,
                        action_type="form_structure",
                        changed_by=reviewer or "local_user",
                        selected_object_id=(
                            control.label_object_id or control.marker_object_id
                        ),
                        note=evidence or None,
                        action=lambda: update_control(
                            session,
                            editable_page_id=view.editable_page_id,
                            control_id=control_id,
                            changed_by=reviewer or "local_user",
                            state=state,
                            label=label,
                            group_id=group_id,
                            evidence_note=evidence or None,
                        ),
                    )
                    return control.label_object_id or control.marker_object_id
                _run_action(
                    st,
                    lambda: _database_action(db_path, update_callback),
                    selection_key=object_state_key,
                    fallback_selection=selected.object_id,
                )

            with st.form(
                f"archive_form_control_{view.editable_page_id}_{control_id}",
                enter_to_submit=False,
            ):
                archive_note = st.text_input("Motivo de archivo")
                archive_submit = st.form_submit_button("Archivar casillero")
            if archive_submit:
                def archive_callback(session):
                    execute_page_action(
                        session,
                        editable_page_id=view.editable_page_id,
                        action_type="form_structure",
                        changed_by=reviewer or "local_user",
                        selected_object_id=(
                            control.label_object_id or control.marker_object_id
                        ),
                        note=archive_note or None,
                        action=lambda: archive_control(
                            session,
                            editable_page_id=view.editable_page_id,
                            control_id=control_id,
                            changed_by=reviewer or "local_user",
                            note=archive_note or None,
                        ),
                    )
                    return control.label_object_id or control.marker_object_id
                _run_action(
                    st,
                    lambda: _database_action(db_path, archive_callback),
                    selection_key=object_state_key,
                    fallback_selection=selected.object_id,
                )

    if form_task == "groups":
        with st.container(border=True):
            with st.form(
                f"create_form_group_{view.editable_page_id}", enter_to_submit=False
            ):
                new_label = st.text_input("Nombre del nuevo grupo de casilleros")
                new_note = st.text_input("Nota sobre este grupo de casilleros (opcional)")
                create_group_submit = st.form_submit_button("Crear grupo de casilleros")
            if create_group_submit:
                def create_group_callback(session):
                    execute_page_action(
                        session,
                        editable_page_id=view.editable_page_id,
                        action_type="form_structure",
                        changed_by=reviewer or "local_user",
                        selected_object_id=selected.object_id,
                        note=new_note or None,
                        action=lambda: ensure_group(
                            session,
                            editable_page_id=view.editable_page_id,
                            label=new_label,
                            changed_by=reviewer or "local_user",
                            note=new_note or None,
                        ),
                    )
                    return selected.object_id

                _run_action(
                    st,
                    lambda: _database_action(db_path, create_group_callback),
                    selection_key=object_state_key,
                    fallback_selection=selected.object_id,
                )
            if active_groups:
                target_group_id = st.selectbox(
                    "Grupo de casilleros existente",
                    options=list(group_map),
                    format_func=lambda value: group_map[value].label,
                    key=f"manage_form_group_{view.editable_page_id}",
                )
                target_group = group_map[target_group_id]
                with st.form(
                    f"rename_form_group_{view.editable_page_id}_{target_group_id}",
                    enter_to_submit=False,
                ):
                    renamed_label = st.text_input(
                        "Nuevo nombre de este grupo de casilleros", value=target_group.label
                    )
                    group_note = st.text_input(
                        "Nota sobre este registro (opcional)", value=target_group.note or ""
                    )
                    rename_submit = st.form_submit_button("Guardar los cambios de este grupo de casilleros")
                if rename_submit:
                    def rename_group_callback(session):
                        execute_page_action(
                            session,
                            editable_page_id=view.editable_page_id,
                            action_type="form_structure",
                            changed_by=reviewer or "local_user",
                            selected_object_id=selected.object_id,
                            note=group_note or None,
                            action=lambda: rename_group(
                                session,
                                editable_page_id=view.editable_page_id,
                                group_id=target_group_id,
                                label=renamed_label,
                                changed_by=reviewer or "local_user",
                                note=group_note or None,
                            ),
                        )
                        return selected.object_id

                    _run_action(
                        st,
                        lambda: _database_action(db_path, rename_group_callback),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )
                with st.form(
                    f"archive_form_group_{view.editable_page_id}_{target_group_id}",
                    enter_to_submit=False,
                ):
                    archive_group_note = st.text_input("Motivo de archivo del grupo")
                    archive_group_submit = st.form_submit_button("Archivar este grupo de casilleros")
                if archive_group_submit:
                    def archive_group_callback(session):
                        execute_page_action(
                            session,
                            editable_page_id=view.editable_page_id,
                            action_type="form_structure",
                            changed_by=reviewer or "local_user",
                            selected_object_id=selected.object_id,
                            note=archive_group_note or None,
                            action=lambda: archive_group(
                                session,
                                editable_page_id=view.editable_page_id,
                                group_id=target_group_id,
                                changed_by=reviewer or "local_user",
                                note=archive_group_note or None,
                            ),
                        )
                        return selected.object_id

                    _run_action(
                        st,
                        lambda: _database_action(db_path, archive_group_callback),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

    if form_task == "history":
        if not history:
            st.caption("Todavía no hay revisiones de formulario.")
        else:
            for row in reversed(history):
                with st.container(border=True):
                    st.write(
                        f"**Revisión {row.revision_number}** · {row.operation} · "
                        f"{row.created_by}"
                    )
                    st.caption(row.created_at.isoformat(timespec="minutes"))
                    st.write(
                        f"Grupos: {row.group_count} · Casilleros: {row.control_count}"
                    )
                    if row.note:
                        st.write(row.note)
                    if row.details:
                        st.json(row.details, expanded=False)


def _apply_pending_app_mode(st) -> None:
    pending = st.session_state.pop("review_pending_app_mode", None)
    if pending in {"home", "catalog", "audiovisual", "processing", "work", "review", "search", "semantic", "authorities", "graph", "export", "exchange", "admin"}:
        st.session_state["review_app_mode"] = pending


def _apply_pending_navigation(st, document_map: dict[str, object]) -> None:
    """Aplica una navegación explícita antes de montar los controles de revisión."""

    pending = st.session_state.pop("review_pending_navigation", None)
    if not isinstance(pending, dict):
        return
    source_key = pending.get("source_key")
    if source_key not in document_map:
        return
    document = document_map[source_key]
    page_options = list(document.editable_pages)
    if not page_options:
        return
    try:
        page = int(pending.get("page"))
    except (TypeError, ValueError):
        page = page_options[0]
    if page not in page_options:
        page = page_options[0]

    st.session_state["review_app_mode"] = "review"
    st.session_state["review_source_key"] = source_key
    st.session_state["review_page_source"] = source_key
    st.session_state["review_page_number"] = page
    object_id = pending.get("object_id")
    if object_id:
        st.session_state["review_pending_object_id"] = str(object_id)


def _highlight_search_snippet(value: str) -> str:
    escaped = html.escape(value)
    return escaped.replace("[[HIT]]", "<mark>").replace("[[/HIT]]", "</mark>")


def _search_navigation_entries(results) -> list[dict[str, object]]:
    return [
        {
            "source_key": row.source_key,
            "page": row.page_number,
            "object_id": row.object_id,
            "document_title": row.document_title,
            "order_index": row.order_index,
            "match_scope": row.match_scope,
        }
        for row in results
    ]


def _open_search_result(st, *, results, index: int, query: str) -> None:
    entries = _search_navigation_entries(results)
    if not 0 <= index < len(entries):
        return
    st.session_state["review_search_navigation"] = {
        "origin": "textual",
        "query": query,
        "index": index,
        "results": entries,
    }
    target = entries[index]
    request_app_view(
        st,
        mode="review",
        source_key=str(target["source_key"]),
        page=int(target["page"]),
        object_id=str(target["object_id"]),
    )
    rerun_app(st)


def _close_search_result_navigation(st) -> None:
    """Cierra sólo el recorrido de búsqueda, sin tocar el contexto de revisión."""

    st.session_state["review_search_navigation"] = None


def _render_search_result_navigation(st) -> None:
    navigation = st.session_state.get("review_search_navigation")
    if not isinstance(navigation, dict):
        return
    entries = navigation.get("results")
    if not isinstance(entries, list) or not entries:
        return
    try:
        index = int(navigation.get("index", 0))
    except (TypeError, ValueError):
        index = 0
    index = max(0, min(index, len(entries) - 1))
    navigation["index"] = index
    st.session_state["review_search_navigation"] = navigation
    query = str(navigation.get("query") or "").strip()
    origin = str(navigation.get("origin") or "textual")
    is_semantic = origin == "semantic"
    search_name = "Búsqueda semántica" if is_semantic else "Búsqueda textual"
    return_mode = "semantic" if is_semantic else "search"

    with st.container(border=True):
        title_col, close_col = st.columns([8, 1])
        with title_col:
            st.caption(
                f"{search_name}"
                + (f" · consulta «{query}»" if query else "")
            )
        with close_col:
            st.button(
                "✕",
                key="review_search_close_results",
                type="primary",
                help=f"Cerrar el recorrido de resultados de {search_name}",
                on_click=_close_search_result_navigation,
                args=(st,),
            )
        previous_col, position_col, next_col = st.columns([1.2, 0.8, 1.2])
        with previous_col:
            previous_clicked = st.button(
                "← Resultado anterior",
                key="review_search_previous_result",
                disabled=index == 0,
                use_container_width=True,
            )
        with position_col:
            st.caption(f"Resultado {index + 1} de {len(entries)}")
        with next_col:
            next_clicked = st.button(
                "Resultado siguiente →",
                key="review_search_next_result",
                disabled=index >= len(entries) - 1,
                use_container_width=True,
            )
        action_columns = st.columns(2 if is_semantic else 1)
        with action_columns[0]:
            return_clicked = st.button(
                f"Volver a {search_name}",
                key="review_search_return_to_results",
                use_container_width=True,
            )
        similar_clicked = False
        current_target = entries[index]
        if is_semantic and current_target.get("semantic_query_text"):
            with action_columns[1]:
                similar_clicked = st.button(
                    "Buscar pasajes similares a este resultado",
                    key="review_semantic_similar_result",
                    use_container_width=True,
                )

    if return_clicked:
        request_app_view(st, mode=return_mode)
        rerun_app(st)
        return
    if similar_clicked:
        queue_similar_semantic_search(
            st,
            query_text=str(current_target["semantic_query_text"]),
            chunk_id=str(current_target.get("chunk_id") or ""),
            profile_id=str(navigation.get("semantic_profile_id") or "") or None,
        )
        st.session_state["review_search_navigation"] = None
        request_app_view(st, mode="semantic")
        rerun_app(st)
        return
    if previous_clicked or next_clicked:
        next_index = index - 1 if previous_clicked else index + 1
        navigation["index"] = next_index
        st.session_state["review_search_navigation"] = navigation
        target = entries[next_index]
        request_app_view(
            st,
            mode="review",
            source_key=str(target["source_key"]),
            page=int(target["page"]),
            object_id=str(target["object_id"]),
        )
        rerun_app(st)


def _render_search_distribution(st, results) -> None:
    document_counts = Counter(row.document_title for row in results)
    page_count = len({(row.source_key, row.page_number) for row in results})
    scope_counts = Counter(row.match_scope for row in results)
    part_counts = Counter(
        (
            row.document_title,
            row.document_part_title or row.document_part_key,
        )
        for row in results
        if row.document_part_title or row.document_part_key
    )

    with st.expander("Distribución de los resultados", expanded=False):
        st.write(
            f"**{len(results)} bloques mostrados en {len(document_counts)} documentos y {page_count} páginas.**"
        )
        st.write("**Por documento**")
        st.dataframe(
            [
                {"Documento": title, "Bloques mostrados": count}
                for title, count in document_counts.most_common()
            ],
            hide_index=True,
            use_container_width=True,
        )
        st.write("**Por lugar de la coincidencia**")
        st.dataframe(
            [
                {"Lugar de la coincidencia": scope, "Bloques mostrados": count}
                for scope, count in scope_counts.most_common()
            ],
            hide_index=True,
            use_container_width=True,
        )
        if part_counts:
            st.write("**Por parte interna del documento**")
            st.dataframe(
                [
                    {
                        "Documento": document,
                        "Parte interna": part,
                        "Bloques mostrados": count,
                    }
                    for (document, part), count in part_counts.most_common()
                ],
                hide_index=True,
                use_container_width=True,
            )


def _render_search_concordances(st, results) -> None:
    rows: list[dict[str, object]] = []
    for result_number, row in enumerate(results, start=1):
        occurrences = concordance_occurrences(row.match_text)
        for occurrence_number, occurrence in enumerate(occurrences, start=1):
            rows.append(
                {
                    "N.º de resultado": result_number,
                    "Documento": row.document_title,
                    "Página": row.page_number,
                    "Antes": occurrence.left_context,
                    "Coincidencia": occurrence.hit,
                    "Después": occurrence.right_context,
                    "Lugar de la coincidencia": row.match_scope,
                    "N.º de aparición en el bloque": occurrence_number,
                }
            )
    if not rows:
        st.info("No se pudieron construir concordancias para estos resultados.")
        return
    st.caption(
        f"{len(rows)} concordancias en {len(results)} bloques. La columna N.º de resultado corresponde al número de la tarjeta en la vista Tarjetas."
    )
    st.dataframe(rows, hide_index=True, use_container_width=True)


def _render_search_view(st, *, db_path: Path, project_id: str, document_map, type_labels: dict[str, str]) -> None:
    section_heading(st, "Búsqueda textual")
    search_surface = st.radio(
        "Dónde querés buscar",
        options=("documentos", "audiovisual"),
        format_func=lambda value: (
            "Documentos revisados" if value == "documentos" else "Transcripciones de audio y video"
        ),
        horizontal=True,
        key="review_search_surface",
    )
    search_surface_label = (
        "Documentos revisados" if search_surface == "documentos" else "Transcripciones de audio y video"
    )
    mount_choice_help(
        st,
        key="review_search_surface",
        label=search_surface_label,
        help_text=TASK_HELP["review_search_surface"][search_surface_label],
    )
    if search_surface == "audiovisual":
        with st.form("search_audiovisual_form", enter_to_submit=False):
            query_col, limit_col = st.columns([4, 1])
            with query_col:
                av_query = st.text_input(
                    "Qué querés encontrar en las transcripciones",
                    value=st.session_state.get("av_search_query", ""),
                    placeholder="Buscar palabras o una frase en las transcripciones",
                    key="av_search_query_input",
                    label_visibility="collapsed",
                )
            with limit_col:
                av_limit = st.number_input(
                    "Máximo de resultados", min_value=10, max_value=500, value=50, step=10,
                    key="av_search_limit",
                    label_visibility="collapsed",
                    help="Cantidad máxima de coincidencias que se mostrarán.",
                )
            av_submitted = st.form_submit_button("Buscar en las transcripciones", type="primary")
        if av_submitted:
            st.session_state["av_search_query"] = av_query
        query_value = st.session_state.get("av_search_query", "").strip()
        if not query_value:
            st.info("Escribí las palabras o la frase que querés buscar para comenzar.")
            return
        av_engine = create_sqlite_engine(db_path)
        try:
            with session_scope(av_engine) as session:
                av_results = search_transcript_segments(
                    session, project_id=project_id, query=query_value, limit=int(av_limit)
                )
        finally:
            av_engine.dispose()
        st.subheader(f"Coincidencias en transcripciones · {len(av_results)}")
        if not av_results:
            st.warning("No se encontraron coincidencias en las transcripciones.")
            return
        for index, row in enumerate(av_results):
            with st.container(border=True):
                header, action = st.columns([5, 1])
                with header:
                    st.markdown(
                        f"**{row.title}** · {format_timestamp(row.start_time)}–{format_timestamp(row.end_time)}"
                    )
                    st.caption(f"Estado de revisión del fragmento: {_STATUS_LABELS.get(row.review_status, row.review_status)}")
                    st.write(row.text)
                with action:
                    if st.button(
                        "Abrir este fragmento en Audio y video", key=f"open_av_search_{index}_{row.segment_id}", use_container_width=True
                    ):
                        st.session_state["av_pending_media_id"] = row.media_id
                        st.session_state["av_pending_segment_id"] = row.segment_id
                        request_app_view(st, mode="audiovisual")
                        rerun_app(st)
        return
    field_labels = {
        "current_text": "Texto revisado",
        "original_text": "OCR original",
        "comments": "Comentarios",
        "tags": "Etiquetas",
        "entities": "Entidades, menciones y relaciones",
    }
    mode_labels = {
        "all": "Deben aparecer todas las palabras",
        "any": "Puede aparecer cualquiera de las palabras",
        "phrase": "Debe aparecer la frase exacta",
    }
    saved_params = st.session_state.get("review_search_params")
    if not isinstance(saved_params, dict):
        saved_params = {}
    saved_match_mode = str(saved_params.get("match_mode") or "all")
    if saved_match_mode not in MATCH_MODES:
        saved_match_mode = "all"
    saved_fields = [value for value in saved_params.get("fields", SEARCH_FIELDS) if value in SEARCH_FIELDS]
    saved_source_keys = [value for value in saved_params.get("source_keys", ()) if value in document_map]
    saved_object_types = [value for value in saved_params.get("object_types", ()) if value in type_labels]
    saved_object_statuses = [value for value in saved_params.get("object_review_statuses", ()) if value in REVIEW_STATUSES]
    saved_page_statuses = [value for value in saved_params.get("page_review_statuses", ()) if value in REVIEW_STATUSES]
    saved_tag_kinds = [value for value in saved_params.get("tag_kinds", ()) if value in TAG_KINDS]
    saved_part_keys = list(saved_params.get("document_part_keys", ()))
    saved_lifecycle = list(saved_params.get("lifecycle_statuses", ("active",)))
    saved_temporal_start = saved_params.get("temporal_start")
    saved_temporal_end = saved_params.get("temporal_end")
    saved_temporal_filter = saved_temporal_start is not None or saved_temporal_end is not None
    fields = saved_fields
    source_keys = saved_source_keys
    object_types = saved_object_types
    object_statuses = saved_object_statuses
    page_statuses = saved_page_statuses
    include_deleted = "deleted" in saved_lifecycle
    limit = int(saved_params.get("limit", 50))
    part_key = str(saved_part_keys[0]) if saved_part_keys else ""
    tag_kinds = saved_tag_kinds
    temporal_filter = saved_temporal_filter
    temporal_start = saved_temporal_start or "today"
    temporal_end = saved_temporal_end or "today"
    temporal_include_undated = bool(
        saved_params.get("temporal_include_undated", False)
    )
    literal_filters_open = st.toggle(
        "Más filtros",
        value=False,
        key="literal_search_filters_open",
    )

    with st.form("search_corpus_form", enter_to_submit=False):
        query_col, mode_col, partial_col = st.columns([2.4, 1.5, 1.4])
        with query_col:
            query = st.text_input(
                "Qué querés encontrar",
                value=str(saved_params.get("query") or st.session_state.get("review_search_query", "")),
                placeholder="Buscar palabras o una frase en los documentos",
                label_visibility="collapsed",
            )
        with mode_col:
            match_mode = st.selectbox(
                "Cómo combinar las palabras",
                options=list(MATCH_MODES),
                index=list(MATCH_MODES).index(saved_match_mode),
                format_func=lambda value: mode_labels[value],
                label_visibility="collapsed",
            )
        with partial_col:
            partial_words = st.checkbox(
                "Incluir partes de palabras",
                value=bool(saved_params.get("partial_words", False)),
                help=(
                    "Permite que 'marx' encuentre 'marxista' o 'averig' encuentre "
                    "'averiguaciones'. Cada fragmento debe tener al menos 3 caracteres."
                ),
            )
        if literal_filters_open:
            with st.container(border=True):
                left, right = st.columns(2)
                with left:
                    fields = st.multiselect(
                        "Qué partes de los registros querés buscar",
                        options=list(SEARCH_FIELDS),
                        default=saved_fields,
                        format_func=lambda value: field_labels[value],
                    )
                    source_keys = st.multiselect(
                        "Documentos en los que querés buscar",
                        options=list(document_map),
                        default=saved_source_keys,
                        format_func=lambda key: document_map[key].title,
                    )
                    part_key = st.text_input(
                        "Parte interna del documento, si querés limitar la búsqueda",
                        value=str(saved_part_keys[0]) if saved_part_keys else "",
                        placeholder="Opcional",
                    )
                    object_types = st.multiselect(
                        "Tipos de bloques de texto",
                        options=list(type_labels),
                        default=saved_object_types,
                        format_func=lambda value: type_labels.get(value, value),
                    )
                    tag_kinds = st.multiselect(
                        "Categorías de etiqueta presentes",
                        options=list(TAG_KINDS),
                        default=saved_tag_kinds,
                        format_func=lambda value: _TAG_KIND_LABELS[value],
                    )
                with right:
                    object_statuses = st.multiselect(
                        "Estado de revisión de los bloques de texto",
                        options=list(REVIEW_STATUSES),
                        default=saved_object_statuses,
                        format_func=lambda value: _STATUS_LABELS[value],
                    )
                    page_statuses = st.multiselect(
                        "Estado de la página",
                        options=list(REVIEW_STATUSES),
                        default=saved_page_statuses,
                        format_func=lambda value: _STATUS_LABELS[value],
                    )
                    include_deleted = st.checkbox(
                        "Incluir bloques de texto eliminados",
                        value="deleted" in saved_lifecycle,
                    )
                    limit = st.number_input(
                        "Máximo de resultados",
                        min_value=10,
                        max_value=500,
                        value=int(saved_params.get("limit", 50)),
                        step=10,
                    )
                temporal_filter = st.checkbox(
                    "Acotar por fechas de entidades o relaciones vinculadas",
                    value=saved_temporal_filter,
                )
                temporal_columns = st.columns(2)
                temporal_start = temporal_columns[0].date_input(
                    "Buscar vínculos vigentes desde",
                    value=saved_temporal_start or "today",
                    min_value=DATE_INPUT_MIN,
                    max_value=DATE_INPUT_MAX,
                    key="review_search_temporal_start",
                )
                temporal_end = temporal_columns[1].date_input(
                    "Buscar vínculos vigentes hasta",
                    value=saved_temporal_end or "today",
                    min_value=DATE_INPUT_MIN,
                    max_value=DATE_INPUT_MAX,
                    key="review_search_temporal_end",
                )
                temporal_include_undated = st.checkbox(
                    "Incluir vínculos sin fecha",
                    value=bool(saved_params.get("temporal_include_undated", False)),
                )
        submitted = st.form_submit_button("Buscar en los documentos", type="primary")
    if submitted:
        st.session_state["review_search_navigation"] = None
        st.session_state["review_search_query"] = query
        st.session_state["review_search_params"] = {
            "query": query,
            "match_mode": match_mode,
            "fields": fields,
            "source_keys": source_keys,
            "object_types": object_types,
            "object_review_statuses": object_statuses,
            "page_review_statuses": page_statuses,
            "lifecycle_statuses": ["active", "deleted"] if include_deleted else ["active"],
            "document_part_keys": [part_key.strip()] if part_key.strip() else [],
            "tag_kinds": tag_kinds,
            "temporal_start": temporal_start if temporal_filter else None,
            "temporal_end": temporal_end if temporal_filter else None,
            "temporal_include_undated": (
                temporal_include_undated if temporal_filter else False
            ),
            "partial_words": partial_words,
            "limit": int(limit),
        }

    rebuild_open = st.toggle(
        "Actualizar textos de la búsqueda",
        value=False,
        key="search_rebuild_open",
        help="Usalo si una corrección reciente todavía no aparece en la búsqueda textual.",
    )
    rebuild_clicked = False
    if rebuild_open:
        rebuild_clicked = st.button("Actualizar ahora los textos usados por la búsqueda")
    if rebuild_clicked:
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                summary = rebuild_search_index(session)
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
        else:
            st.success(f"Búsqueda textual actualizada con {summary.object_count} bloques de texto")
        finally:
            engine.dispose()

    params = st.session_state.get("review_search_params")
    if not params:
        st.info("Escribí las palabras o la frase que querés buscar para comenzar.")
        return
    try:
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                results = search_editable_objects(session, **params)
                status = search_index_status(session)
        finally:
            engine.dispose()
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return

    st.subheader(f"Coincidencias en documentos · {len(results)}")
    with st.expander("Detalles técnicos del índice", expanded=False):
        indexed = status.indexed_at or "sin fecha"
        st.caption(
            f"Generación indexada: {status.indexed_generation} · última actualización: {indexed}"
        )
    if not results:
        st.warning("No se encontraron coincidencias con los filtros seleccionados.")
        return

    _render_search_distribution(st, results)
    result_view = st.radio(
        "Cómo querés ver los resultados",
        options=("cards", "kwic"),
        format_func=lambda value: {
            "cards": "Tarjetas",
            "kwic": "Concordancias",
        }[value],
        horizontal=True,
        key="review_search_result_view",
    )
    result_view_label = "Tarjetas" if result_view == "cards" else "Concordancias"
    mount_choice_help(
        st,
        key="review_search_result_view",
        label=result_view_label,
        help_text=TASK_HELP["review_search_result_view"][result_view_label],
    )
    if result_view == "kwic":
        _render_search_concordances(st, results)
        return

    for index, row in enumerate(results):
        with st.container(border=True):
            header, action = st.columns([5, 1])
            with header:
                part = f" · parte `{row.document_part_key}`" if row.document_part_key else ""
                st.markdown(
                    f"**Resultado {index + 1}** · **{row.document_title}** · página **{row.page_number}** · "
                    f"bloque de texto **{row.order_index + 1}** · "
                    f"{type_labels.get(row.object_type, row.object_type)}{part}"
                )
                st.caption(
                    f"Bloque {_STATUS_LABELS.get(row.object_review_status, row.object_review_status)} "
                    f"· página {_STATUS_LABELS.get(row.page_review_status, row.page_review_status)} "
                    f"· coincidencia en {row.match_scope}"
                )
            with action:
                if st.button(
                    "Abrir este resultado en Revisar documentos",
                    key=f"open_search_{index}_{row.object_id}",
                    use_container_width=True,
                ):
                    _open_search_result(
                        st,
                        results=results,
                        index=index,
                        query=str(params.get("query") or ""),
                    )
            st.markdown(_highlight_search_snippet(row.snippet), unsafe_allow_html=True)


def _format_exchange_value(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    return repr(value)


def _run_exchange_action(st, *, db_path: Path, callback: Callable) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            message = callback(session)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    st.session_state["exchange_flash"] = str(message or "Operación completada")
    rerun_view(st)


def _exchange_dry_run_message(summary) -> str:
    apply_count = int(summary.counts.get("apply", 0))
    duplicate_count = int(summary.counts.get("duplicate", 0))
    review_count = int(summary.counts.get("review", 0))
    conflict_count = int(summary.counts.get("conflict", 0))
    if conflict_count or review_count:
        parts = []
        if apply_count:
            parts.append(
                f"{apply_count} {'cambio listo' if apply_count == 1 else 'cambios listos'} para incorporar"
            )
        if review_count:
            parts.append(
                f"{review_count} {'cambio requiere' if review_count == 1 else 'cambios requieren'} una decisión"
            )
        if conflict_count:
            parts.append(
                f"{conflict_count} {'conflicto requiere' if conflict_count == 1 else 'conflictos requieren'} revisión"
            )
        return "Paquete revisado: " + "; ".join(parts) + "."
    if apply_count:
        suffix = (
            f" Se reconocieron además {duplicate_count} "
            f"{'cambio ya incorporado' if duplicate_count == 1 else 'cambios ya incorporados'}."
            if duplicate_count
            else ""
        )
        return (
            f"Paquete revisado: {apply_count} "
            f"{'cambio listo' if apply_count == 1 else 'cambios listos'} para incorporar."
            + suffix
        )
    if duplicate_count:
        return (
            f"Paquete revisado: sus {duplicate_count} "
            f"{'cambio ya está incorporado' if duplicate_count == 1 else 'cambios ya están incorporados'} "
            "en esta copia."
        )
    return "Paquete revisado: no contiene cambios nuevos para esta copia."


def _exchange_apply_message(result) -> str:
    applied = int(result.applied_event_count)
    duplicates = int(result.duplicate_event_count)
    kept_local = int(result.kept_local_event_count)
    message = (
        f"{applied} {'cambio incorporado' if applied == 1 else 'cambios incorporados'} al proyecto."
    )
    extras = []
    if duplicates:
        extras.append(
            f"{duplicates} {'cambio ya estaba incorporado' if duplicates == 1 else 'cambios ya estaban incorporados'}"
        )
    if kept_local:
        extras.append(
            f"{kept_local} {'valor local se conservó' if kept_local == 1 else 'valores locales se conservaron'}"
        )
    if extras:
        message += " " + "; ".join(extras) + "."
    return message


def _simulate_exchange_bundle_path(
    st,
    *,
    project_root: Path,
    db_path: Path,
    bundle_path: Path,
    reviewer: str,
) -> None:
    def callback(session):
        summary = dry_run_change_bundle(
            session,
            project_root=project_root,
            bundle_path=bundle_path,
            assessed_by=reviewer or "local_user",
        )
        st.session_state["exchange_selected_bundle"] = summary.bundle_id
        st.session_state["exchange_main_task"] = "receive"
        st.session_state["exchange_receive_add_open"] = False
        return _exchange_dry_run_message(summary)

    _run_exchange_action(st, db_path=db_path, callback=callback)


def _purge_exchange_entry(
    st,
    *,
    project_root: Path,
    db_path: Path,
    bundle_ref: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            plan = purge_incoming_bundle(session, bundle_ref=bundle_ref)
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    root = project_root.resolve()
    removed = 0
    failed = 0
    for value in plan.relative_paths:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            try:
                candidate.unlink()
            except OSError:
                failed += 1
            else:
                removed += 1
    suffix = f"; {failed} archivo(s) no pudieron retirarse" if failed else ""
    st.session_state["exchange_flash"] = (
        f"Entrada {plan.bundle_id[:8]} eliminada; {removed} archivo(s) internos retirados"
        f"{suffix}"
    )
    st.session_state.pop("exchange_selected_bundle", None)
    rerun_view(st)


def _exchange_event_summary(event) -> str:
    fields = event.changed_fields
    label = (
        fields.get("preferred_name")
        or fields.get("name")
        or fields.get("title")
        or fields.get("current_text")
    )
    suffix = f" · {str(label)[:100]}" if label else ""
    operation = _EXCHANGE_OPERATION_LABELS.get(event.operation, event.operation)
    return (
        f"secuencia {event.sequence_number} · {operation} · "
        f"{event.actor} · {event.occurred_at}{suffix}"
    )


def _human_file_size(byte_size: int) -> str:
    value = float(max(byte_size, 0))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{byte_size} B"


def _save_uploaded_zip(project_root: Path, uploaded, *, namespace: str) -> Path:
    safe_name = Path(str(uploaded.name)).name
    if not safe_name.lower().endswith(".zip"):
        safe_name += ".zip"
    destination_dir = project_root / "exchange" / "ui_uploads" / namespace
    destination_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(uploaded.getvalue()).hexdigest()[:16]
    destination = destination_dir / f"{digest}_{safe_name}"
    if not destination.is_file():
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(uploaded.getvalue())
        temporary.replace(destination)
    return destination


def _google_drive_query_param(st, name: str) -> str:
    value = st.query_params.get(name)
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def _handle_google_drive_oauth_callback(st) -> None:
    flash = st.session_state.pop("google_drive_oauth_flash", None)
    if flash:
        st.success(str(flash))

    error = _google_drive_query_param(st, "error")
    code = _google_drive_query_param(st, "code")
    state = _google_drive_query_param(st, "state")
    picked_file_ids = _google_drive_query_param(st, "picked_file_ids")
    if not error and not code and not state:
        return

    if error:
        st.query_params.clear()
        st.error(f"Google Drive no fue autorizado: {error}")
        return
    if not code or not state:
        st.query_params.clear()
        st.error("La respuesta de Google Drive está incompleta. Iniciá la conexión nuevamente.")
        return

    try:
        result = complete_google_drive_authorization(
            code=code,
            state=state,
            picked_file_ids=picked_file_ids,
            token_path=google_drive_default_token_path(),
        )
    except (ValueError, RuntimeError, OSError) as exc:
        st.query_params.clear()
        st.error(str(exc))
        return

    if result.picked_file_ids:
        message = (
            "El ZIP quedó autorizado en Google Drive. Podés volver a la pestaña donde lo elegiste "
            "y usar esa selección."
        )
    else:
        message = "Google Drive quedó conectado en esta computadora."
    st.session_state["google_drive_oauth_flash"] = message
    st.query_params.clear()
    st.success(message)


def _render_google_drive_connection(
    st,
    *,
    key_prefix: str,
) -> tuple[Path | None, Path] | None:
    """Devuelve el cliente/token disponible o muestra el alta OAuth correspondiente."""

    token_path = google_drive_default_token_path()
    client_path = google_drive_default_client_secret_path()
    status = google_drive_connection_status(token_path)
    workspace = managed_workspace()
    if status in {"connected", "expired"}:
        return (None if workspace is not None else client_path), token_path

    if workspace is not None:
        try:
            authorization_url = prepare_google_drive_authorization()
        except (ValueError, RuntimeError, OSError) as exc:
            st.warning(str(exc))
            return None
        st.link_button(
            "Conectar Google Drive",
            authorization_url,
            type="primary",
            use_container_width=True,
        )
        st.caption(
            "Se abrirá Google en una pestaña del navegador. Cada integrante autoriza su propia cuenta; "
            "el token queda guardado sólo en ArchiveWorkbenchData/Settings de esta computadora."
        )
        return None

    panel_key = f"{key_prefix}_connect_open"
    if not st.session_state.get(panel_key, False):
        if st.button("Conectar Google Drive", key=f"{key_prefix}_connect_prompt"):
            st.session_state[panel_key] = True
            rerun_view(st)
        return None

    st.markdown("**Conectar Google Drive**")
    client_path_text = st.text_input(
        "Credenciales OAuth de Google",
        value=str(client_path),
        key=f"{key_prefix}_client_secret_path",
        help=(
            "En una instalación nativa de desarrollo podés indicar el JSON de un cliente OAuth "
            "de escritorio. La distribución administrada no requiere este archivo por persona."
        ),
    )
    client_path = Path(client_path_text).expanduser()
    connect_col, cancel_col = st.columns(2)
    with connect_col:
        connect = st.button(
            "Autorizar Google Drive",
            type="primary",
            key=f"{key_prefix}_authorize",
            use_container_width=True,
        )
    with cancel_col:
        cancel = st.button(
            "Cancelar",
            key=f"{key_prefix}_cancel_connect",
            use_container_width=True,
        )
    if cancel:
        st.session_state[panel_key] = False
        rerun_view(st)
    if connect:
        try:
            with st.spinner("Esperando autorización en el navegador…"):
                authorize_google_drive(client_path, token_path=token_path)
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
        else:
            st.session_state[panel_key] = False
            rerun_view(st)
    return None


def _render_created_artifact_drive_action(st, *, archive_path: Path, key: str) -> None:
    if not archive_path.is_file():
        return
    connection = _render_google_drive_connection(
        st,
        key_prefix=f"{key}_drive",
    )
    if connection is None:
        return
    client_path, token_path = connection
    if st.button("Subir a Google Drive", key=key):
        try:
            with st.spinner("Subiendo el ZIP a Google Drive de forma reanudable…"):
                result = upload_archive_workbench_zip_to_drive(
                    archive_path,
                    client_secret_path=client_path,
                    token_path=token_path,
                )
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
        else:
            st.session_state[f"{key}_result"] = result
    result = st.session_state.get(f"{key}_result")
    if result is not None:
        st.write("**ZIP disponible en Google Drive.**")
        if result.metadata.web_view_link:
            st.link_button(
                "Abrir ZIP en Google Drive",
                result.metadata.web_view_link,
                key=f"{key}_open",
            )
        with st.expander("Detalles de la subida", expanded=False):
            st.write(result.metadata.name)
            st.code(f"SHA-256: {result.local_sha256}", language="text")


def _render_google_drive_receive(
    st,
    *,
    project_root: Path,
    db_path: Path,
    reviewer: str,
) -> None:
    connection = _render_google_drive_connection(
        st,
        key_prefix="exchange_receive_drive",
    )
    if connection is None:
        return
    client_path, token_path = connection

    if managed_workspace() is not None:
        try:
            picker_url = prepare_google_drive_authorization(picker=True)
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
            picker_url = None
        if picker_url:
            st.link_button(
                "Elegir ZIP en Google Drive",
                picker_url,
                use_container_width=True,
            )
            st.caption(
                "Después de elegir el ZIP en Google, volvé a esta pestaña y confirmá la selección."
            )
            if st.button("Usar el ZIP elegido", key="exchange_drive_pick_result_button"):
                picked = google_drive_load_picker_result()
                if not picked:
                    st.warning("Todavía no hay una selección reciente de Google Drive para usar.")
                else:
                    try:
                        file_id = picked[0]
                        metadata = get_drive_file_metadata(
                            file_id,
                            client_secret_path=client_path,
                            token_path=token_path,
                        )
                    except (ValueError, RuntimeError, OSError) as exc:
                        st.error(str(exc))
                    else:
                        st.session_state["exchange_drive_selected_file"] = (file_id, metadata)
                        st.session_state.pop("exchange_drive_downloaded_artifact", None)
    elif st.button("Elegir ZIP en Google Drive", key="exchange_drive_pick_button"):
        try:
            with st.spinner("Elegí el archivo en la pestaña de Google Drive…"):
                file_id, metadata = pick_drive_exchange_bundle(
                    client_path,
                    token_path=token_path,
                )
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
        else:
            st.session_state["exchange_drive_selected_file"] = (file_id, metadata)
            st.session_state.pop("exchange_drive_downloaded_artifact", None)

    selected_file = st.session_state.get("exchange_drive_selected_file")
    if selected_file is None:
        return
    file_id, metadata = selected_file
    st.write(f"**ZIP elegido:** {metadata.name}")
    if metadata.web_view_link:
        st.link_button("Abrir en Google Drive", metadata.web_view_link)
    if st.button(
        "Descargar y verificar ZIP",
        type="primary",
        key="exchange_drive_download_button",
    ):
        try:
            with st.spinner("Descargando y verificando el ZIP…"):
                result = download_archive_workbench_zip_from_drive(
                    file_id,
                    project_root=project_root,
                    client_secret_path=client_path,
                    token_path=token_path,
                )
                comparison = None
                if result.artifact_kind == "exchange_bundle":
                    compare_engine = create_sqlite_engine(db_path)
                    try:
                        with session_scope(compare_engine) as session:
                            comparison = compare_change_bundle_manifest(
                                session,
                                project_root=project_root,
                                bundle_path=result.destination,
                            )
                    finally:
                        compare_engine.dispose()
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            st.error(str(exc))
        else:
            st.session_state["exchange_drive_downloaded_artifact"] = (
                result,
                comparison,
            )

    downloaded = st.session_state.get("exchange_drive_downloaded_artifact")
    if downloaded is None:
        return
    result, comparison = downloaded
    if not result.destination.is_file():
        st.warning("El ZIP descargado ya no está disponible en la ruta local registrada.")
        return

    if result.artifact_kind == "team_copy":
        st.write("**Copia para trabajar en equipo descargada y verificada.**")
        st.caption(
            "Extraé este ZIP en una carpeta nueva y abrí esa carpeta como otro proyecto. "
            "No se incorpora sobre el proyecto que está abierto ahora."
        )
        with st.expander("Detalles del ZIP descargado", expanded=False):
            st.code(str(result.destination))
            st.code(f"SHA-256: {result.local_sha256}", language="text")
        return

    assert comparison is not None
    st.write("**Paquete de cambios descargado y verificado.**")
    if not comparison.project_matches:
        st.error("El paquete pertenece a otro proyecto y no puede revisarse en esta copia.")
        return
    if comparison.source_is_local_workspace:
        st.error("El paquete fue producido por esta misma copia y no puede recibirse como remoto.")
        return
    if not comparison.base_checkpoint_known:
        st.warning(
            "No se pudo comprobar todavía un punto de partida compartido. La revisión puede "
            "requerir resolver diferencias antes de incorporar cambios."
        )
    if not comparison.database_revision_known:
        st.warning(
            "La revisión de base de datos del ZIP no se reconoce como equivalente. "
            "Archive Workbench exigirá revisar sus cambios antes de incorporarlos."
        )
    with st.expander("Detalles de compatibilidad y archivo", expanded=False):
        st.dataframe(
            [
                {
                    "Dato": row.field,
                    "Esta copia": row.local_value,
                    "ZIP recibido": row.incoming_value,
                    "Comprobación": row.status,
                }
                for row in comparison.rows
            ],
            hide_index=True,
            use_container_width=True,
        )
        st.code(str(result.destination))
        st.code(f"SHA-256: {result.local_sha256}", language="text")
    if st.button(
        "Revisar los cambios de este ZIP",
        type="primary",
        key="exchange_drive_dry_run_button",
    ):
        st.session_state["exchange_receive_add_open"] = False
        _simulate_exchange_bundle_path(
            st,
            project_root=project_root,
            db_path=db_path,
            bundle_path=result.destination,
            reviewer=reviewer,
        )


def _render_receive_zip_source(
    st,
    *,
    project_root: Path,
    db_path: Path,
    reviewer: str,
) -> None:
    source_labels = {
        "local": "Desde este equipo",
        "drive": "Desde Google Drive",
    }
    source = st.radio(
        "Dónde está el ZIP recibido",
        options=list(source_labels),
        format_func=lambda value: source_labels[value],
        horizontal=True,
        key="exchange_receive_source",
    )
    mount_choice_help(
        st,
        key="exchange_receive_source",
        label=source_labels[source],
        help_text=TASK_HELP["exchange_receive_source"][source_labels[source]],
    )
    if source == "drive":
        _render_google_drive_receive(
            st,
            project_root=project_root,
            db_path=db_path,
            reviewer=reviewer,
        )
        return

    uploaded = st.file_uploader(
        "Elegir ZIP recibido",
        type=["zip"],
        key="exchange_bundle_upload",
    )
    if uploaded is not None:
        st.caption(f"{uploaded.name} · {_human_file_size(uploaded.size)}")
    if st.button(
        "Identificar y revisar el ZIP recibido",
        type="primary",
        disabled=uploaded is None,
        key="exchange_upload_dry_run",
    ):
        assert uploaded is not None
        try:
            temp_path = _save_uploaded_zip(
                project_root, uploaded, namespace="received"
            )
            inspection = inspect_drive_artifact(temp_path)
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
        else:
            if inspection.kind == "team_copy":
                st.session_state["exchange_received_team_copy"] = str(temp_path)
                st.session_state.pop("exchange_selected_bundle", None)
            else:
                st.session_state.pop("exchange_received_team_copy", None)
                st.session_state["exchange_receive_add_open"] = False
                _simulate_exchange_bundle_path(
                    st,
                    project_root=project_root,
                    db_path=db_path,
                    bundle_path=temp_path,
                    reviewer=reviewer,
                )

    received_team_copy = st.session_state.get("exchange_received_team_copy")
    if received_team_copy:
        received_path = Path(str(received_team_copy))
        if received_path.is_file():
            st.write("**El ZIP recibido es una copia para trabajar en equipo.**")
            st.caption(
                "Extraela en una carpeta nueva y abrí esa carpeta como otro proyecto. "
                "No se incorpora sobre el proyecto que está abierto ahora."
            )
            with st.expander("Detalles del ZIP recibido", expanded=False):
                st.code(str(received_path))
            return
        st.session_state.pop("exchange_received_team_copy", None)


def _render_exchange_advanced_tools(
    st,
    *,
    project_root: Path,
    db_path: Path,
    reviewer: str,
    workspace,
    common_base_agreements,
    state_adoptions,
) -> None:
    advanced_tasks = {
        "adoption": "Reemplazar el trabajo editable completo",
        "common_base": "Reconectar dos copias con el mismo trabajo editable",
    }
    exchange_task = st.radio(
        "Qué necesitás hacer",
        options=list(advanced_tasks),
        format_func=lambda value: advanced_tasks[value],
        key="exchange_advanced_task",
    )
    mount_choice_help(
        st,
        key="exchange_advanced_task",
        label=advanced_tasks[exchange_task],
        help_text=TASK_HELP["exchange_advanced_task"][advanced_tasks[exchange_task]],
    )
    if exchange_task == "adoption":
        st.caption(
            "Usá esta herramienta excepcional cuando dos copias del mismo proyecto ya tienen versiones distintas del trabajo editable y decidieron conservar completa la versión de una de ellas. Primero se muestra una vista previa de lo que se agregaría, quitaría o cambiaría. Si confirmás la adopción, Archive Workbench crea una copia de seguridad antes de reemplazar el trabajo editable."
        )
        adoption_step = st.radio(
            "Qué querés hacer con la versión completa del trabajo editable",
            options=["Crear el ZIP con todo el trabajo editable", "Revisar un ZIP completo y reemplazar el trabajo editable de esta copia"],
            horizontal=True,
            key="exchange_state_adoption_step",
        )
        mount_choice_help(
            st,
            key="exchange_state_adoption_step",
            label=adoption_step,
            help_text=TASK_HELP["exchange_adoption_step"][adoption_step],
        )
        if adoption_step == "Crear el ZIP con todo el trabajo editable":
            with st.form("exchange_state_package_create", enter_to_submit=False):
                target_workspace_id = st.text_input(
                    "Identificador técnico de la otra copia del proyecto",
                    key="exchange_state_package_target_id",
                )
                target_workspace_name = st.text_input(
                    "Nombre reconocible de la otra copia del proyecto",
                    key="exchange_state_package_target_name",
                )
                package_created_by = st.text_input(
                    "Persona responsable de crear este ZIP de estado",
                    value=reviewer or "local_user",
                    key="exchange_state_package_created_by",
                )
                package_reason = st.text_area(
                    "Motivo por el que se envía el trabajo editable completo",
                    key="exchange_state_package_reason",
                )
                package_confirmed = st.checkbox(
                    "Confirmo que el paquete contiene el estado editable completo para la copia indicada",
                    key="exchange_state_package_confirmed",
                )
                package_submitted = st.form_submit_button(
                    "Crear el ZIP con todo el trabajo editable",
                    type="primary",
                )
            if package_submitted:
                if not target_workspace_id.strip():
                    st.error("Indicá el identificador de la copia destinataria.")
                elif not target_workspace_name.strip():
                    st.error("Indicá el nombre de la copia destinataria.")
                elif not package_created_by.strip():
                    st.error("Indicá quién crea el paquete.")
                elif not package_reason.strip():
                    st.error("Escribí el fundamento del paquete.")
                elif not package_confirmed:
                    st.error("Marcá la confirmación antes de crear el paquete.")
                else:
                    _run_exchange_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: (
                            lambda summary: (
                                f"Paquete de estado {summary.adoption_id} creado en "
                                f"{summary.output_path}. No se modificó el corpus."
                            )
                        )(
                            create_state_adoption_package(
                                session,
                                project_root=project_root,
                                target_workspace_id=target_workspace_id,
                                target_workspace_name=target_workspace_name,
                                created_by=package_created_by,
                                creation_reason=package_reason,
                                package_confirmed=package_confirmed,
                            )
                        ),
                    )
        else:
            state_package_upload = st.file_uploader(
                "Elegir ZIP con el trabajo editable completo",
                type=["zip"],
                key="exchange_state_adoption_package_file",
            )
            state_package_path = st.text_input(
                "O escribir o pegar una ruta local",
                key="exchange_state_adoption_package_path",
                help="La ruta local es una alternativa al selector de archivos.",
            )
            if st.button(
                "Ver qué cambiaría sin modificar el proyecto",
                key="exchange_state_adoption_preview_button",
            ):
                if state_package_upload is None and not state_package_path.strip():
                    st.error("Elegí el ZIP o indicá una ruta local.")
                else:
                    selected_state_path = (
                        _save_uploaded_zip(
                            project_root,
                            state_package_upload,
                            namespace="state_adoption",
                        )
                        if state_package_upload is not None
                        else Path(state_package_path).expanduser()
                    )
                    preview_engine = create_sqlite_engine(db_path)
                    try:
                        with session_scope(preview_engine) as session:
                            preview = preview_state_adoption(
                                session,
                                package_path=selected_state_path,
                            )
                        st.session_state["exchange_state_adoption_preview"] = preview
                    except (ValueError, RuntimeError, OSError) as exc:
                        st.error(str(exc))
                    finally:
                        preview_engine.dispose()

            preview = st.session_state.get("exchange_state_adoption_preview")
            if preview is not None:
                st.write(
                    f"**Estado local:** `{preview.local_state_sha256}`  \n"
                    f"**Estado recibido:** `{preview.incoming_state_sha256}`"
                )
                st.write(
                    f"Impacto: agregar **{preview.total_added}**, quitar "
                    f"**{preview.total_removed}**, cambiar **{preview.total_changed}**."
                )
                changed_sections = [
                    row
                    for row in preview.sections
                    if row.added or row.removed or row.changed
                ]
                if changed_sections:
                    st.dataframe(
                        [
                            {
                                "Sección": row.section,
                                "Local": row.local_count,
                                "Recibido": row.incoming_count,
                                "Agregar": row.added,
                                "Quitar": row.removed,
                                "Cambiar": row.changed,
                            }
                            for row in changed_sections
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )
                with st.form("exchange_state_adoption_apply", enter_to_submit=False):
                    adoption_applied_by = st.text_input(
                        "Persona responsable de reemplazar el trabajo editable de esta copia",
                        value=reviewer or "local_user",
                        key="exchange_state_adoption_applied_by",
                    )
                    adoption_reason = st.text_area(
                        "Motivo por el que se reemplazará el trabajo editable de esta copia",
                        key="exchange_state_adoption_reason",
                    )
                    adoption_confirmed = st.checkbox(
                        "Confirmo que quiero crear una copia de seguridad y reemplazar el trabajo editable de esta copia por el contenido del ZIP",
                        key="exchange_state_adoption_confirmed",
                    )
                    adoption_submitted = st.form_submit_button(
                        "Reemplazar el trabajo editable con el contenido de este ZIP",
                        type="primary",
                    )
                if adoption_submitted:
                    if not adoption_applied_by.strip():
                        st.error("Indicá quién es responsable de reemplazar el trabajo editable.")
                    elif not adoption_reason.strip():
                        st.error("Escribí por qué se reemplazará el trabajo editable de esta copia.")
                    elif not adoption_confirmed:
                        st.error("Marcá la confirmación antes de reemplazar el trabajo editable.")
                    else:
                        _run_exchange_action(
                            st,
                            db_path=db_path,
                            callback=lambda session: (
                                lambda summary: (
                                    f"Trabajo editable reemplazado mediante la operación {summary.adoption_id}. Copia de seguridad previa: "
                                    f"{summary.backup_path}. Ahora corresponde comprobar que ambas copias reconozcan el mismo estado de partida antes de volver a intercambiar cambios."
                                )
                            )(
                                apply_state_adoption(
                                    session,
                                    project_root=project_root,
                                    package_path=Path(preview.package_path),
                                    applied_by=adoption_applied_by,
                                    application_reason=adoption_reason,
                                    adoption_confirmed=adoption_confirmed,
                                    source="ui",
                                )
                            ),
                        )

        if state_adoptions:
            st.markdown("**Adopciones registradas en esta copia**")
            for adoption in state_adoptions:
                status = "revertida" if adoption.rolled_back else "activa"
                st.write(
                    f"`{adoption.adoption_id}` · {status} · origen "
                    f"{adoption.source_workspace_name}"
                )
                st.caption(
                    f"{adoption.previous_state_sha256} → {adoption.adopted_state_sha256} · "
                    f"responsable {adoption.applied_by}"
                )
            st.info(
                "Si necesitás deshacer esta adopción completa, la recuperación se realiza con Archive Workbench cerrado usando la copia de seguridad creada antes del reemplazo. El comando técnico se muestra sólo como referencia de recuperación."
            )


    if exchange_task == "common_base":
        st.caption(
            "Usá esta tarea cuando dos copias del mismo proyecto contienen en este momento "
            "exactamente el mismo trabajo editable. Archive Workbench registra ese punto común "
            "para que, desde entonces, cada paquete pueda contener solamente los cambios nuevos "
            "de una copia. En este paso no se envían documentos ni se reemplaza trabajo."
        )
        st.info(
            f"Esta copia se llama {workspace.workspace_name} y su identificador es "
            f"{workspace.workspace_id}. La otra copia muestra sus propios datos en esta misma pantalla."
        )
        common_base_step = st.radio(
            "Qué paso corresponde en esta copia",
            options=[
                "1. Iniciar desde esta copia",
                "2. Confirmar en la otra copia",
                "3. Completar en la copia inicial",
            ],
            horizontal=True,
            key="exchange_common_base_step",
        )
        mount_choice_help(
            st,
            key="exchange_common_base_step",
            label=common_base_step,
            help_text=TASK_HELP["exchange_common_base_step"][common_base_step],
        )
        if common_base_step == "1. Iniciar desde esta copia":
            with st.form("exchange_common_base_proposal", enter_to_submit=False):
                counterpart_id = st.text_input(
                    "Identificador de la copia contraparte",
                    key="exchange_common_base_counterpart_id",
                )
                counterpart_name = st.text_input(
                    "Nombre de la copia contraparte",
                    key="exchange_common_base_counterpart_name",
                )
                proposed_by = st.text_input(
                    "Persona que propone este acuerdo entre copias",
                    value=reviewer or "local_user",
                    key="exchange_common_base_proposed_by",
                )
                proposal_reason = st.text_area(
                    "Fundamento de la propuesta",
                    key="exchange_common_base_proposal_reason",
                )
                proposal_confirmed = st.checkbox(
                    "Confirmo que ambas copias ya contienen el mismo trabajo editable y quiero iniciar el registro de esta base común",
                    key="exchange_common_base_proposal_confirmed",
                )
                proposal_submitted = st.form_submit_button(
                    "Crear propuesta para la otra copia",
                    type="primary",
                )
            if proposal_submitted:
                if not counterpart_id.strip():
                    st.error("Indicá el identificador de la copia contraparte.")
                elif not counterpart_name.strip():
                    st.error("Indicá el nombre de la copia contraparte.")
                elif not proposed_by.strip():
                    st.error("Indicá quién crea la propuesta.")
                elif not proposal_reason.strip():
                    st.error("Escribí el fundamento de la propuesta.")
                elif not proposal_confirmed:
                    st.error("Marcá la confirmación antes de crear la propuesta.")
                else:
                    _run_exchange_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: (
                            lambda summary: (
                                f"Propuesta {summary.agreement_id} creada en "
                                f"{summary.output_path}. Todavía no se activó ningún acuerdo."
                            )
                        )(
                            create_common_base_proposal(
                                session,
                                project_root=project_root,
                                counterpart_workspace_id=counterpart_id,
                                counterpart_workspace_name=counterpart_name,
                                proposed_by=proposed_by,
                                proposal_reason=proposal_reason,
                                proposal_confirmed=proposal_confirmed,
                                source="ui",
                            )
                        ),
                    )
        elif common_base_step == "2. Confirmar en la otra copia":
            with st.form("exchange_common_base_accept", enter_to_submit=False):
                proposal_upload = st.file_uploader(
                    "Elegir ZIP de propuesta recibido",
                    type=["zip"],
                    key="exchange_common_base_accept_proposal_file",
                )
                proposal_path_text = st.text_input(
                    "O escribir o pegar una ruta local",
                    key="exchange_common_base_accept_proposal_path",
                )
                accepted_by = st.text_input(
                    "Persona que acepta este acuerdo entre copias",
                    value=reviewer or "local_user",
                    key="exchange_common_base_accepted_by",
                )
                accept_reason = st.text_area(
                    "Fundamento de la aceptación",
                    key="exchange_common_base_accept_reason",
                )
                accept_confirmed = st.checkbox(
                    "Confirmo que esta es la otra copia indicada y que ambas contienen el mismo trabajo editable",
                    key="exchange_common_base_accept_confirmed",
                )
                accept_submitted = st.form_submit_button(
                    "Confirmar coincidencia y devolver acuerdo",
                    type="primary",
                )
            if accept_submitted:
                if proposal_upload is None and not proposal_path_text.strip():
                    st.error("Elegí el ZIP de propuesta o indicá una ruta local.")
                elif not accepted_by.strip():
                    st.error("Indicá quién acepta la propuesta.")
                elif not accept_reason.strip():
                    st.error("Escribí el fundamento de la aceptación.")
                elif not accept_confirmed:
                    st.error("Marcá la confirmación antes de aceptar el acuerdo.")
                else:
                    selected_proposal_path = (
                        _save_uploaded_zip(
                            project_root, proposal_upload, namespace="common_base_proposal"
                        )
                        if proposal_upload is not None
                        else Path(proposal_path_text).expanduser()
                    )
                    _run_exchange_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: (
                            lambda summary: (
                                f"Acuerdo {summary.agreement_id} registrado en esta copia. "
                                f"Manifiesto completado: {summary.output_path}. La copia "
                                "iniciadora todavía debe finalizarlo."
                            )
                        )(
                            accept_common_base_proposal(
                                session,
                                project_root=project_root,
                                proposal_path=selected_proposal_path,
                                accepted_by=accepted_by,
                                confirmation_reason=accept_reason,
                                agreement_confirmed=accept_confirmed,
                                source="ui",
                            )
                        ),
                    )
        else:
            with st.form("exchange_common_base_finalize", enter_to_submit=False):
                original_proposal_upload = st.file_uploader(
                    "Elegir ZIP de propuesta original",
                    type=["zip"],
                    key="exchange_common_base_finalize_proposal_file",
                )
                original_proposal_path = st.text_input(
                    "O ruta local de la propuesta original",
                    key="exchange_common_base_finalize_proposal_path",
                )
                completed_agreement_upload = st.file_uploader(
                    "Elegir ZIP de acuerdo completado",
                    type=["zip"],
                    key="exchange_common_base_finalize_agreement_file",
                )
                completed_agreement_path = st.text_input(
                    "O ruta local del acuerdo completado",
                    key="exchange_common_base_finalize_agreement_path",
                )
                finalized_by = st.text_input(
                    "Persona que finaliza este acuerdo entre copias",
                    value=reviewer or "local_user",
                    key="exchange_common_base_finalized_by",
                )
                finalize_reason = st.text_area(
                    "Fundamento de la finalización",
                    key="exchange_common_base_finalize_reason",
                )
                finalize_confirmed = st.checkbox(
                    "Confirmo que ambas copias contienen el mismo trabajo editable y quiero registrar este punto como base común para los próximos paquetes",
                    key="exchange_common_base_finalize_confirmed",
                )
                finalize_submitted = st.form_submit_button(
                    "Registrar la base común en esta copia",
                    type="primary",
                )
            if finalize_submitted:
                if original_proposal_upload is None and not original_proposal_path.strip():
                    st.error("Elegí la propuesta original o indicá una ruta local.")
                elif completed_agreement_upload is None and not completed_agreement_path.strip():
                    st.error("Elegí el acuerdo completado o indicá una ruta local.")
                elif not finalized_by.strip():
                    st.error("Indicá quién finaliza el acuerdo.")
                elif not finalize_reason.strip():
                    st.error("Escribí el fundamento de la finalización.")
                elif not finalize_confirmed:
                    st.error("Marcá la confirmación antes de finalizar el acuerdo.")
                else:
                    selected_original_proposal = (
                        _save_uploaded_zip(
                            project_root,
                            original_proposal_upload,
                            namespace="common_base_finalize_proposal",
                        )
                        if original_proposal_upload is not None
                        else Path(original_proposal_path).expanduser()
                    )
                    selected_completed_agreement = (
                        _save_uploaded_zip(
                            project_root,
                            completed_agreement_upload,
                            namespace="common_base_finalize_agreement",
                        )
                        if completed_agreement_upload is not None
                        else Path(completed_agreement_path).expanduser()
                    )
                    _run_exchange_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: (
                            lambda summary: (
                                f"Acuerdo {summary.agreement_id} finalizado. Nuevo estado previo compartido: "
                                f"{summary.checkpoint_label}."
                            )
                        )(
                            finalize_common_base_agreement(
                                session,
                                project_root=project_root,
                                proposal_path=selected_original_proposal,
                                agreement_path=selected_completed_agreement,
                                finalized_by=finalized_by,
                                confirmation_reason=finalize_reason,
                                agreement_confirmed=finalize_confirmed,
                                source="ui",
                            )
                        ),
                    )

        if common_base_agreements:
            st.markdown("**Acuerdos registrados en esta copia**")
            for agreement in common_base_agreements:
                st.write(
                    f"`{agreement.agreement_id}` · rol {agreement.local_role} · "
                    f"punto `{agreement.checkpoint_label}`"
                )
                st.caption(
                    f"Contraparte {agreement.counterpart_workspace_id} · "
                    f"estado {agreement.state_sha256} · "
                    f"responsable {agreement.registered_by}"
                )



def _render_exchange_view(st, *, project_root: Path, db_path: Path, reviewer: str) -> None:
    section_heading(st, "Intercambiar cambios")
    flash = st.session_state.pop("exchange_flash", None)
    if flash:
        st.success(flash)

    if st.session_state.get("exchange_main_task") == "more":
        st.session_state["exchange_main_task"] = "receive"

    recovery_mode = bool(st.session_state.get("exchange_recovery_mode", False))
    exchange_tasks = {
        "send": "Enviar cambios",
        "receive": "Recibir cambios",
        "prepare_copy": "Preparar una copia para trabajar en equipo",
    }
    if recovery_mode:
        exchange_task = "recovery"
    else:
        exchange_task = st.selectbox(
            "Tarea de intercambio",
            options=list(exchange_tasks),
            format_func=lambda value: exchange_tasks[value],
            key="exchange_main_task",
            label_visibility="collapsed",
        )
        exchange_task_label = exchange_tasks[exchange_task]
        mount_choice_help(
            st,
            key="exchange_main_task",
            label=exchange_task_label,
            help_text=TASK_HELP["exchange_main_task"][exchange_task_label],
        )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            workspace = exchange_status(session)
            checkpoints = checkpoint_rows(session)
            incoming_all = incoming_bundle_rows(session, include_archived=True)
            applications = bundle_application_rows(session)
            recoveries = lineage_recovery_rows(session)
            common_base_agreements = common_base_agreement_rows(session)
            state_adoptions = state_adoption_rows(session)
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    incoming = [row for row in incoming_all if row.lifecycle_status != "archived"]

    if recovery_mode:
        if st.button("Volver a Recibir cambios", key="exchange_recovery_back"):
            st.session_state["exchange_recovery_mode"] = False
            st.session_state["exchange_main_task"] = "receive"
            rerun_view(st)
        st.subheader("Resolver un problema entre copias")
        mount_heading_help(
            st,
            label="Resolver un problema entre copias",
            help_text=(
                "Reúne herramientas excepcionales para reconciliar dos copias cuando el "
                "recorrido normal de enviar y recibir cambios no alcanza."
            ),
        )
        _render_exchange_advanced_tools(
            st,
            project_root=project_root,
            db_path=db_path,
            reviewer=reviewer,
            workspace=workspace,
            common_base_agreements=common_base_agreements,
            state_adoptions=state_adoptions,
        )
        return

    if exchange_task == "send" and workspace.pending_event_count:
        st.caption(
            f"{workspace.pending_event_count} "
            f"{'cambio local sin compartir' if workspace.pending_event_count == 1 else 'cambios locales sin compartir'}"
        )
    elif exchange_task == "receive" and incoming:
        st.caption(
            f"{len(incoming)} "
            f"{'paquete recibido disponible' if len(incoming) == 1 else 'paquetes recibidos disponibles'}"
        )

    if exchange_task == "send":
        st.caption(
            "Archive Workbench reúne en un ZIP los cambios nuevos de esta copia. No hace falta "
            "indicar quién lo va a recibir: cualquier otra copia compatible del mismo proyecto "
            "puede revisarlo."
        )
        if not checkpoints:
            st.info(
                "Todavía no existe un punto de partida para intercambiar cambios. Si vas a "
                "empezar a trabajar con otras personas, elegí Preparar una copia para trabajar "
                "en equipo y enviá esa copia inicial a quienes participen."
            )
            return

        selected_checkpoint = checkpoints[-1]
        changes_after_base = max(
            0, workspace.current_sequence - selected_checkpoint.sequence_number
        )
        if changes_after_base == 0:
            st.info("No hay cambios nuevos para enviar desde el último punto compartido.")
        else:
            st.write(
                f"Hay **{changes_after_base}** "
                f"{'cambio nuevo' if changes_after_base == 1 else 'cambios nuevos'} para enviar."
            )
            with st.form("exchange_create_incremental_bundle", enter_to_submit=False):
                bundle_created_by = st.text_input(
                    "Persona responsable de crear el paquete",
                    value=reviewer or "local_user",
                    key="exchange_send_created_by",
                )
                bundle_submitted = st.form_submit_button(
                    "Crear paquete de cambios",
                    type="primary",
                )
            if bundle_submitted:
                if not bundle_created_by.strip():
                    st.error("Indicá quién crea el paquete.")
                else:
                    bundle_engine = create_sqlite_engine(db_path)
                    try:
                        with session_scope(bundle_engine) as session:
                            summary = export_change_bundle(
                                session,
                                project_root=project_root,
                                checkpoint_ref=selected_checkpoint.checkpoint_id,
                                created_by=bundle_created_by,
                            )
                        st.session_state["exchange_last_created_bundle"] = {
                            "bundle_id": summary.bundle_id,
                            "output_path": str(summary.output_path),
                            "bundle_sha256": summary.bundle_sha256,
                            "event_count": summary.event_count,
                            "base_sequence": summary.base_sequence,
                            "last_sequence": summary.last_sequence,
                            "next_checkpoint_label": summary.next_checkpoint_label,
                        }
                    except (ValueError, RuntimeError, OSError) as exc:
                        st.error(str(exc))
                    finally:
                        bundle_engine.dispose()

        created_bundle = st.session_state.get("exchange_last_created_bundle")
        if created_bundle is not None:
            output_path = Path(str(created_bundle["output_path"]))
            event_count = int(created_bundle["event_count"])
            st.success(
                f"Paquete creado: {event_count} "
                f"{'cambio listo' if event_count == 1 else 'cambios listos'} para compartir."
            )
            if output_path.is_file():
                st.download_button(
                    "Descargar paquete",
                    data=output_path.read_bytes(),
                    file_name=output_path.name,
                    mime="application/zip",
                    key=f"exchange_download_created_{created_bundle['bundle_id']}",
                )
                _render_created_artifact_drive_action(
                    st,
                    archive_path=output_path,
                    key=f"exchange_drive_created_bundle_{created_bundle['bundle_id']}",
                )
            else:
                st.warning("El ZIP ya no está disponible en la ruta registrada.")
            with st.expander("Detalles del paquete", expanded=False):
                try:
                    relative_output = output_path.relative_to(project_root.resolve())
                    st.code(relative_output.as_posix())
                except ValueError:
                    st.code(str(output_path))
                st.code(f"SHA-256: {created_bundle['bundle_sha256']}", language="text")
                st.write(
                    f"Punto compartido utilizado: `{selected_checkpoint.label}` · "
                    f"secuencia {selected_checkpoint.sequence_number}."
                )
        return

    if exchange_task == "prepare_copy":
        st.caption(
            "Prepará una copia del proyecto para empezar a trabajar con otras personas. El mismo "
            "ZIP puede enviarse a varias personas: cada una recibirá automáticamente una identidad "
            "propia cuando abra su copia por primera vez."
        )
        profile_labels = {
            "complete": "Completa",
            "review": "Para revisión y catalogación",
            "custom": "Personalizada",
        }
        profile = st.radio(
            "Qué querés incluir en la copia",
            options=list(profile_labels),
            format_func=lambda value: profile_labels[value],
            horizontal=True,
            key="exchange_team_copy_profile",
            help=(
                "Los datos necesarios para mantener el proyecto y su configuración siempre viajan. Podés omitir documentos "
                "originales y otros archivos pesados o regenerables para reducir el tamaño."
            ),
        )
        if profile == "complete":
            included_groups = list(TEAM_COPY_PRESETS["complete"])
        elif profile == "review":
            included_groups = list(TEAM_COPY_PRESETS["review"])
            st.caption(
                "Incluye derivados de consulta, resultados de extracción y transcripciones. "
                "Omite los originales y otros materiales que no son necesarios para revisar o catalogar."
            )
        else:
            default_custom = list(
                st.session_state.get(
                    "exchange_team_copy_custom_groups",
                    TEAM_COPY_PRESETS["review"],
                )
            )
            included_labels = st.multiselect(
                "Contenido adicional de la copia",
                options=list(TEAM_COPY_GROUP_LABELS),
                default=default_custom,
                format_func=lambda key: TEAM_COPY_GROUP_LABELS[key],
                key="exchange_team_copy_custom_groups",
                help=(
                    "Los grupos no seleccionados quedan registrados como omitidos deliberadamente "
                    "en el manifiesto de la copia."
                ),
            )
            included_groups = list(included_labels)

        try:
            plan = plan_team_copy(
                project_root=project_root,
                included_groups=included_groups,
                profile_name=profile,
            )
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
            return
        st.write(
            f"Tamaño estimado: **{_human_file_size(plan.estimated_total_byte_size)}** · "
            f"{plan.selected_file_count + 1} archivos aproximadamente."
        )
        if "originals" in plan.omitted_groups:
            st.caption(
                "Los documentos originales no viajarán. La copia podrá conservar y revisar el "
                "trabajo editable y los materiales incluidos, pero no podrá abrir ni reprocesar "
                "un original que no tenga disponible localmente."
            )
        with st.expander("Ver detalle del tamaño estimado"):
            st.dataframe(
                [
                    {
                        "Contenido": row.label,
                        "Incluido": "Sí" if row.included else "No",
                        "Archivos": row.file_count,
                        "Tamaño": _human_file_size(row.byte_size),
                    }
                    for row in plan.group_summaries
                ],
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                "La base SQLite y la configuración del proyecto son obligatorias y están "
                f"incluidas en el estimado ({_human_file_size(plan.database_estimated_byte_size + plan.core_byte_size)})."
            )

        team_copy_created_by = st.text_input(
            "Persona responsable de preparar la copia",
            value=reviewer or "local_user",
            key="exchange_team_copy_created_by",
        )
        team_copy_submitted = st.button(
            "Crear copia para compartir",
            type="primary",
            key="exchange_prepare_team_copy_button",
        )
        if team_copy_submitted:
            if not team_copy_created_by.strip():
                st.error("Indicá quién prepara la copia.")
            else:
                try:
                    with st.spinner("Preparando la copia del proyecto…"):
                        summary = create_team_copy_package(
                            project_root=project_root,
                            created_by=team_copy_created_by,
                            included_groups=included_groups,
                            content_profile=profile,
                        )
                    st.session_state["exchange_last_team_copy"] = {
                        "package_id": summary.package_id,
                        "output_path": str(summary.output_path),
                        "package_sha256": summary.package_sha256,
                        "byte_size": summary.byte_size,
                        "file_count": summary.file_count,
                        "base_checkpoint_label": summary.base_checkpoint_label,
                        "content_profile": summary.content_profile,
                        "included_groups": summary.included_content_groups,
                        "omitted_groups": summary.omitted_content_groups,
                    }
                except (ValueError, RuntimeError, OSError) as exc:
                    st.error(str(exc))

        prepared = st.session_state.get("exchange_last_team_copy")
        if prepared is not None:
            output_path = Path(str(prepared["output_path"]))
            st.success("Copia preparada y lista para compartir.")
            st.caption(
                f"Tamaño: {_human_file_size(int(prepared['byte_size']))}. "
                "El mismo ZIP puede enviarse a varias personas."
            )
            if output_path.is_file() and prepared["byte_size"] <= 100 * 1024 * 1024:
                st.download_button(
                    "Descargar copia",
                    data=output_path.read_bytes(),
                    file_name=output_path.name,
                    mime="application/zip",
                    key=f"exchange_download_team_copy_{prepared['package_id']}",
                )
            elif output_path.is_file():
                st.caption(
                    "El ZIP quedó guardado localmente. Por su tamaño no se vuelve a cargar en "
                    "el navegador para descargarlo."
                )
            _render_created_artifact_drive_action(
                st,
                archive_path=output_path,
                key=f"exchange_drive_team_copy_{prepared['package_id']}",
            )
            with st.expander("Detalles de la copia", expanded=False):
                try:
                    relative_output = output_path.relative_to(project_root.resolve())
                    st.code(relative_output.as_posix())
                except ValueError:
                    st.code(str(output_path))
                st.code(f"SHA-256: {prepared['package_sha256']}", language="text")
                omitted = tuple(prepared.get("omitted_groups", ()))
                if omitted:
                    st.write(
                        "Contenido omitido deliberadamente: "
                        + ", ".join(TEAM_COPY_GROUP_LABELS[key] for key in omitted)
                        + "."
                    )
                st.write(
                    f"Punto inicial: `{prepared['base_checkpoint_label']}` · "
                    f"{prepared['file_count']} archivos incluidos."
                )
        return

    if exchange_task == "receive":
        add_open_key = "exchange_receive_add_open"
        if not incoming and not st.session_state.get(add_open_key, False):
            st.session_state[add_open_key] = True

        if st.session_state.get(add_open_key, False):
            st.markdown("**Abrir un ZIP recibido**")
            close_col, _ = st.columns([1, 4])
            with close_col:
                if incoming and st.button(
                    "Cerrar incorporación de ZIP",
                    key="exchange_receive_add_close",
                    use_container_width=True,
                ):
                    st.session_state[add_open_key] = False
                    rerun_view(st)
            _render_receive_zip_source(
                st,
                project_root=project_root,
                db_path=db_path,
                reviewer=reviewer,
            )
            if incoming:
                st.divider()
        else:
            if st.button(
                "Abrir otro ZIP recibido",
                key="exchange_receive_add_button",
            ):
                st.session_state[add_open_key] = True
                rerun_view(st)

        archived_available = any(
            row.lifecycle_status == "archived" for row in incoming_all
        )
        show_archived = False
        if archived_available:
            show_archived = st.checkbox(
                "Incluir paquetes archivados",
                value=False,
                key="exchange_show_archived",
            )
        incoming = [
            row
            for row in incoming_all
            if show_archived or row.lifecycle_status != "archived"
        ]

    if not incoming:
        if exchange_task == "receive" and not st.session_state.get(add_open_key, False):
            st.caption("No hay paquetes recibidos pendientes de revisión.")
        if exchange_task == "receive":
            if st.button(
                "Resolver un problema entre copias",
                key="exchange_recovery_entry_empty",
                help=(
                    "Abre herramientas excepcionales para reconciliar copias cuando el "
                    "recorrido normal de enviar y recibir cambios no alcanza."
                ),
            ):
                st.session_state["exchange_recovery_mode"] = True
                rerun_view(st)
        return

    incoming_map = {row.bundle_id: row for row in incoming}
    recovery_map = {row.bundle_id: row for row in recoveries}
    current_selection = st.session_state.get("exchange_selected_bundle")
    if current_selection not in incoming_map:
        st.session_state.pop("exchange_selected_bundle", None)
    selected_bundle = st.selectbox(
        "Paquete de cambios que querés revisar",
        options=list(incoming_map),
        format_func=lambda key: (
            ("[Archivado] " if incoming_map[key].lifecycle_status == "archived" else "")
            + f"{incoming_map[key].source_workspace_name} · "
            + incoming_map[key].assessed_at.strftime("%d/%m %H:%M")
            + " · "
            + _EXCHANGE_STATUS_LABELS.get(
                incoming_map[key].status,
                incoming_map[key].status,
            )
        ),
        key="exchange_selected_bundle",
    )
    selected = incoming_map[selected_bundle]
    selected_recovery = recovery_map.get(selected_bundle)
    counts = selected.counts
    status_label = _EXCHANGE_STATUS_LABELS.get(selected.status, selected.status)
    base_label = _EXCHANGE_BASE_LABELS.get(
        selected.base_match_status,
        selected.base_match_status,
    )
    apply_count = int(counts.get("apply", 0))
    duplicate_count = int(counts.get("duplicate", 0))
    review_count = int(counts.get("review", 0))
    conflict_count = int(counts.get("conflict", 0))
    if conflict_count or review_count:
        parts = []
        if apply_count:
            parts.append(
                f"{apply_count} {'cambio listo' if apply_count == 1 else 'cambios listos'}"
            )
        if review_count:
            parts.append(
                f"{review_count} {'cambio requiere' if review_count == 1 else 'cambios requieren'} una decisión"
            )
        if conflict_count:
            parts.append(
                f"{conflict_count} {'conflicto' if conflict_count == 1 else 'conflictos'}"
            )
        st.warning(" · ".join(parts) + ".")
    elif apply_count:
        st.write(
            f"**{apply_count} {'cambio listo' if apply_count == 1 else 'cambios listos'} "
            "para incorporar.**"
        )
        if duplicate_count:
            st.caption(
                f"{duplicate_count} "
                f"{'cambio ya está incorporado' if duplicate_count == 1 else 'cambios ya están incorporados'}."
            )
    elif duplicate_count:
        st.write("**Este paquete no agrega cambios nuevos a esta copia.**")
    else:
        st.write(f"**{status_label}.**")

    with st.expander("Detalles del paquete y la comparación", expanded=False):
        st.write(
            f"Estado: {status_label} · base: {base_label} · "
            f"eventos: {selected.event_count}."
        )
        st.write(
            f"Aplicables: {apply_count} · duplicados: {duplicate_count} · "
            f"a revisar: {review_count} · conflictos: {conflict_count}."
        )
        st.code(
            f"paquete={selected.bundle_id}\n"
            f"base={selected.base_match_status}\n"
            f"metodo_base={selected.base_match_method}",
            language="text",
        )
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            status = resolution_status(session, selected_bundle)
            conflict_rows = conflict_field_rows(session, selected_bundle)
            diagnostics = (
                incoming_bundle_diagnostics(session, bundle_ref=selected_bundle)
                if selected.status == "stale"
                else None
            )
    except ValueError:
        status = None
        conflict_rows = []
        diagnostics = None
    finally:
        engine.dispose()

    if status is not None and status.unresolved_field_count:
        st.caption(
            f"Quedan {status.unresolved_field_count} "
            f"{'campo por decidir' if status.unresolved_field_count == 1 else 'campos por decidir'}."
        )

    if selected_recovery is not None:
        st.write("**Historial compartido reconstruido.**")
        st.caption(
            "La revisión anterior quedó desactualizada. Volvé a revisar el ZIP antes de aplicar cambios."
        )
        with st.expander("Detalles de la reconstrucción", expanded=False):
            st.write(
                f"Método: `{selected_recovery.recovery_method}` · punto local "
                f"`{selected_recovery.local_checkpoint_label or '-'}` · "
                f"secuencia remota {selected_recovery.remote_sequence}"
            )
            st.write(
                f"Responsable: {selected_recovery.confirmed_by} · "
                f"origen: {selected_recovery.source}"
            )
            st.write(f"Fundamento: {selected_recovery.confirmation_reason}")
            st.code(
                f"caso={selected_recovery.case_id}\n"
                f"decision={selected_recovery.decision_id}\n"
                f"parametros_sha256={selected_recovery.parameters_sha256}",
                language="text",
            )

    if selected.base_match_status == "unmatched":
        st.warning(
            "No se pudo comprobar un punto de partida compartido entre esta copia y el ZIP. "
            "Revisá cada diferencia antes de incorporar cambios."
        )
        lineage_panel_key = f"exchange_lineage_panel_{selected_bundle}"
        if not st.session_state.get(lineage_panel_key, False):
            if st.button(
                "Intentar reconstruir el historial compartido",
                key=f"exchange_lineage_open_{selected_bundle}",
            ):
                st.session_state[lineage_panel_key] = True
                rerun_view(st)
        if st.session_state.get(lineage_panel_key, False):
            close_lineage_col, _ = st.columns([1, 4])
            with close_lineage_col:
                if st.button(
                    "Cerrar reconstrucción del historial",
                    key=f"exchange_lineage_close_{selected_bundle}",
                    use_container_width=True,
                ):
                    st.session_state[lineage_panel_key] = False
                    rerun_view(st)
            st.caption(
                "Archive Workbench examina siempre la base local y el ZIP recibido. Si además conservás ZIP anteriores, copias de seguridad o archivos manifest.json, podés indicar una ruta por línea para comprobar si demuestran un estado previo compartido."
            )
            evidence_text = st.text_area(
                "Archivos adicionales que querés comprobar como evidencia",
                key=f"exchange_lineage_evidence_{selected_bundle}",
                placeholder=(
                    "/ruta/al/paquete_anterior.zip\n"
                    "/ruta/al/project_backup.zip\n"
                    "/ruta/al/manifest.json"
                ),
            )
            if st.button(
                "Comprobar estos archivos sin modificar el proyecto",
                key=f"exchange_lineage_diagnose_{selected_bundle}",
            ):
                evidence_paths = [
                    Path(line.strip()).expanduser()
                    for line in evidence_text.splitlines()
                    if line.strip()
                ]
                diagnostic_engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(diagnostic_engine) as session:
                        lineage_report = diagnose_unmatched_bundle_lineage(
                            session,
                            project_root=project_root,
                            bundle_ref=selected_bundle,
                            evidence_paths=evidence_paths,
                        )
                    st.session_state[
                        f"exchange_lineage_report_{selected_bundle}"
                    ] = lineage_report
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
                finally:
                    diagnostic_engine.dispose()

            lineage_report = st.session_state.get(
                f"exchange_lineage_report_{selected_bundle}"
            )
            if lineage_report is not None:
                labels = {
                    "recoverable": "Recuperable",
                    "ambiguous": "Ambiguo",
                    "insufficient": "Insuficiente",
                }
                label = labels.get(
                    lineage_report.classification, lineage_report.classification
                )
                if lineage_report.classification == "recoverable":
                    st.success(f"Resultado de la reconstrucción del historial: {label}. {lineage_report.summary}")
                elif lineage_report.classification == "ambiguous":
                    st.warning(f"Resultado de la reconstrucción del historial: {label}. {lineage_report.summary}")
                else:
                    st.info(f"Resultado de la reconstrucción del historial: {label}. {lineage_report.summary}")
                st.caption(
                    f"Evidencias: {len(lineage_report.findings)} · "
                    f"cadenas concluyentes: {len(lineage_report.recovery_candidates)} · "
                    f"contradicciones: {lineage_report.contradiction_count}"
                )
                for index, finding in enumerate(lineage_report.findings, start=1):
                    with st.expander(
                        f"{index}. {finding.strength} · {finding.code}",
                        expanded=finding.strength in {"conclusive", "rejected"},
                    ):
                        st.write(finding.explanation)
                        st.code(
                            f"artefacto={finding.artifact_reference}\n"
                            f"sha256={finding.artifact_sha256 or '-'}\n"
                            f"proyecto={finding.project_id or '-'}\n"
                            f"copia={finding.workspace_id or '-'}\n"
                            "secuencia="
                            f"{finding.sequence_number if finding.sequence_number is not None else '-'}\n"
                            f"checkpoint={finding.checkpoint_id or '-'}\n"
                            f"estado={finding.state_sha256 or '-'}",
                            language="text",
                        )
                if lineage_report.recovery_candidates:
                    st.markdown("**Cadenas concluyentes identificadas**")
                    for candidate in lineage_report.recovery_candidates:
                        st.write(
                            f"{candidate.method} · punto "
                            f"`{candidate.local_checkpoint_label or '-'}` · "
                            f"secuencia remota {candidate.remote_sequence}"
                        )
                        if candidate.chain_bundle_ids:
                            st.caption(
                                "Paquetes: " + " → ".join(candidate.chain_bundle_ids)
                            )
                if lineage_report.classification == "recoverable":
                    if selected_recovery is None:
                        candidate = lineage_report.recovery_candidates[0]
                        st.warning(
                            "La recuperación no aplica eventos ni modifica el corpus, pero "
                            "registra una decisión permanente e invalida esta simulación."
                        )
                        with st.form(
                            f"exchange_lineage_recover_{selected_bundle}",
                            enter_to_submit=False,
                        ):
                            recovered_by = st.text_input(
                                "Persona responsable de registrar esta reconstrucción del historial",
                                value=reviewer or "local_user",
                                key=f"exchange_lineage_recovered_by_{selected_bundle}",
                            )
                            recovery_reason = st.text_area(
                                "Motivo de esta decisión",
                                key=f"exchange_lineage_reason_{selected_bundle}",
                            )
                            recovery_confirmed = st.checkbox(
                                "Confirmo esta cadena concluyente y acepto invalidar la simulación anterior",
                                key=f"exchange_lineage_confirm_{selected_bundle}",
                            )
                            recovery_submitted = st.form_submit_button(
                                "Registrar el historial compartido reconstruido",
                                type="primary",
                            )
                        if recovery_submitted:
                            evidence_paths = [
                                Path(line.strip()).expanduser()
                                for line in evidence_text.splitlines()
                                if line.strip()
                            ]
                            if not recovered_by.strip():
                                st.error("Indicá quién confirma la recuperación.")
                            elif not recovery_reason.strip():
                                st.error("Escribí el fundamento de la recuperación.")
                            elif not recovery_confirmed:
                                st.error(
                                    "Marcá la confirmación antes de registrar el historial compartido reconstruido."
                                )
                            else:
                                _run_exchange_action(
                                    st,
                                    db_path=db_path,
                                    callback=lambda session: (
                                        lambda summary: (
                                            "Linaje recuperado mediante "
                                            f"{summary.recovery_method}. La simulación "
                                            "anterior quedó obsoleta; volvé a simular "
                                            "antes de resolver o aplicar."
                                        )
                                    )(
                                        recover_unmatched_bundle_lineage(
                                            session,
                                            project_root=project_root,
                                            bundle_ref=selected_bundle,
                                            evidence_paths=evidence_paths,
                                            recovered_by=recovered_by,
                                            confirmation_reason=recovery_reason,
                                            recovery_confirmed=recovery_confirmed,
                                            source="ui",
                                        )
                                    ),
                                )
                    else:
                        st.caption(
                            "La reconstrucción del historial ya fue registrada. Volvé a revisar qué cambios produciría el ZIP para que Archive Workbench use ese antecedente."
                        )
                else:
                    st.caption(
                        "Esta comprobación no permite modificar el proyecto. Sólo una secuencia de evidencia concluyente y única permite registrar un historial compartido reconstruido."
                    )

    if selected.status == "stale":
        st.warning(
            "La vista previa quedó desactualizada porque esta copia cambió después de revisar el ZIP. "
            "Volvé a revisar el ZIP antes de incorporarlo."
        )
        if diagnostics is not None:
            with st.expander("Detalles de la vista previa desactualizada", expanded=False):
                st.write(
                    "Secuencia evaluada: "
                    f"{diagnostics.assessed_sequence_number if diagnostics.assessed_sequence_number is not None else '-'} · "
                    f"secuencia actual: {diagnostics.current_sequence_number} · "
                    f"hash de estado cambiado: {'sí' if diagnostics.state_changed else 'no'}"
                )
                if diagnostics.local_events_after_assessment:
                    for event in diagnostics.local_events_after_assessment:
                        st.write(_exchange_event_summary(event))
                elif diagnostics.state_changed:
                    st.write(
                        "El contenido editable cambió, pero no hay un cambio de intercambio posterior "
                        "que permita atribuirlo a una sola operación."
                    )

    if selected.lifecycle_status == "archived":
        st.write("**Paquete archivado.**")
        st.caption(
            "No aparece en la lista normal de paquetes recibidos. Podés restaurarlo o, si ya no "
            "lo necesitás, eliminar definitivamente esta entrada."
        )
        if st.button(
            "Restaurar paquete",
            key=f"exchange_restore_{selected_bundle}",
        ):
            _run_exchange_action(
                st,
                db_path=db_path,
                callback=lambda session: (
                    set_incoming_bundle_archived(
                        session,
                        bundle_ref=selected_bundle,
                        archived=False,
                        changed_by=reviewer or "local_user",
                    ),
                    "Paquete restaurado",
                )[1],
            )

        if selected.status != "applied":
            purge_panel_key = f"exchange_purge_panel_{selected_bundle}"
            if not st.session_state.get(purge_panel_key, False):
                if st.button(
                    "Eliminar definitivamente esta entrada",
                    key=f"exchange_purge_open_{selected_bundle}",
                ):
                    st.session_state[purge_panel_key] = True
                    rerun_view(st)
            if st.session_state.get(purge_panel_key, False):
                st.caption(
                    "Esta acción elimina la simulación, sus decisiones, el ZIP recibido y los "
                    "reportes internos. No modifica el corpus ni los eventos locales."
                )
                with st.form(
                    f"exchange_purge_{selected_bundle}",
                    enter_to_submit=False,
                ):
                    confirm_purge = st.checkbox(
                        "Confirmo que quiero eliminar definitivamente esta entrada archivada",
                        key=f"exchange_confirm_purge_{selected_bundle}",
                    )
                    purge_submitted = st.form_submit_button(
                        "Eliminar definitivamente"
                    )
                    purge_cancelled = st.form_submit_button("Cancelar")
                if purge_cancelled:
                    st.session_state[purge_panel_key] = False
                    rerun_view(st)
                if purge_submitted:
                    if not confirm_purge:
                        st.error("Marcá la confirmación antes de eliminar la entrada.")
                    else:
                        _purge_exchange_entry(
                            st,
                            project_root=project_root,
                            db_path=db_path,
                            bundle_ref=selected_bundle,
                        )
        if applications:
            with st.expander("Paquetes aplicados anteriormente"):
                for row in applications:
                    st.write(
                        f"`{row.bundle_id}` · aplicados {row.applied_event_count} · "
                        f"duplicados {row.duplicate_event_count} · "
                        f"conservados localmente {row.kept_local_event_count} · "
                        f"estado registrado `{row.checkpoint_label}`"
                    )
        if st.button(
            "Resolver un problema entre copias",
            key=f"exchange_recovery_entry_archived_{selected_bundle}",
        ):
            st.session_state["exchange_recovery_mode"] = True
            rerun_view(st)
        return

    if conflict_rows:
        st.subheader("Resolver diferencias entre esta copia y el ZIP recibido")
        by_event: dict[str, list] = {}
        for row in conflict_rows:
            by_event.setdefault(row.event_id, []).append(row)

        contains_creations = any(row.operation == "create" for row in conflict_rows)
        bulk_options = ["local"] if contains_creations else ["local", "incoming"]
        bulk_panel_key = f"exchange_bulk_panel_{selected_bundle}"
        if not st.session_state.get(bulk_panel_key, False):
            if st.button(
                "Resolver todas las diferencias de la misma manera",
                key=f"exchange_bulk_open_{selected_bundle}",
            ):
                st.session_state[bulk_panel_key] = True
                rerun_view(st)
        if st.session_state.get(bulk_panel_key, False):
            if contains_creations:
                st.caption(
                    "El ZIP contiene elementos nuevos sin un estado previo compartido verificado. "
                    "Por seguridad, la decisión conjunta sólo puede conservar los valores locales."
                )
            with st.form(
                f"exchange_bulk_commit_{selected_bundle}",
                enter_to_submit=False,
            ):
                bulk_choice = st.radio(
                    "Qué hacer con todas las diferencias",
                    options=bulk_options,
                    format_func=lambda value: {
                        "local": "Conservar todos los valores de esta copia",
                        "incoming": "Aceptar todos los valores recibidos",
                    }[value],
                    horizontal=True,
                    key=f"exchange_bulk_choice_{selected_bundle}",
                )
                confirm_bulk = st.checkbox(
                    "Confirmo que quiero aplicar esta decisión a todas las diferencias pendientes",
                    key=f"exchange_confirm_bulk_{selected_bundle}",
                )
                bulk_submitted = st.form_submit_button(
                    "Aplicar a todas las diferencias",
                )
                bulk_cancelled = st.form_submit_button("Cancelar")
            if bulk_cancelled:
                st.session_state[bulk_panel_key] = False
                rerun_view(st)
            if bulk_submitted:
                if not confirm_bulk:
                    st.error("Marcá la confirmación antes de aplicar la decisión conjunta.")
                else:
                    _run_exchange_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: (
                            lambda result: (
                                f"Resueltos {result.resolved_field_count} campos; "
                                f"{result.auto_matched_field_count} coincidían automáticamente"
                            )
                        )(
                            resolve_conflict_fields_bulk(
                                session,
                                bundle_ref=selected_bundle,
                                choice=bulk_choice,
                                resolved_by=reviewer or "local_user",
                            )
                        ),
                    )

        event_ids = list(by_event)
        selected_event_id = st.selectbox(
            "Diferencia que querés revisar",
            options=event_ids,
            format_func=lambda event_id: (
                f"{_EXCHANGE_OPERATION_LABELS.get(by_event[event_id][0].operation, by_event[event_id][0].operation).capitalize()} · "
                f"{len(by_event[event_id])} "
                f"{'campo' if len(by_event[event_id]) == 1 else 'campos'} · "
                f"{event_id[:8]}"
            ),
            key=f"exchange_conflict_event_{selected_bundle}",
        )
        rows = by_event[selected_event_id]
        first = rows[0]

        event_local, event_incoming = st.columns(2)
        with event_local:
            if st.button(
                "Conservar los valores de esta copia en esta diferencia",
                key=f"exchange_event_local_{selected_bundle}_{selected_event_id}",
                use_container_width=True,
            ):
                _run_exchange_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: (
                        lambda result: f"Diferencia resuelta: {result.resolved_field_count} campos locales"
                    )(
                        resolve_conflict_fields_bulk(
                            session,
                            bundle_ref=selected_bundle,
                            event_id=selected_event_id,
                            choice="local",
                            resolved_by=reviewer or "local_user",
                        )
                    ),
                )
        with event_incoming:
            if st.button(
                "Conservar los valores recibidos en esta diferencia",
                key=f"exchange_event_incoming_{selected_bundle}_{selected_event_id}",
                use_container_width=True,
                disabled=first.operation == "create",
                help=(
                    "Los elementos nuevos sin un estado previo compartido verificado deben revisarse campo por campo"
                    if first.operation == "create"
                    else None
                ),
            ):
                _run_exchange_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: (
                        lambda result: f"Diferencia resuelta: {result.resolved_field_count} campos recibidos"
                    )(
                        resolve_conflict_fields_bulk(
                            session,
                            bundle_ref=selected_bundle,
                            event_id=selected_event_id,
                            choice="incoming",
                            resolved_by=reviewer or "local_user",
                        )
                    ),
                )

        for row in rows:
            st.markdown(f"**Campo `{row.field_name}`**")
            base_col, local_col, incoming_col = st.columns(3)
            base_col.caption("Estado previo compartido")
            base_col.code(_format_exchange_value(row.base_value), language="text")
            local_col.caption("Valor en esta copia")
            local_col.code(_format_exchange_value(row.local_value), language="text")
            incoming_col.caption("Valor recibido")
            incoming_col.code(_format_exchange_value(row.incoming_value), language="text")
            choice_key = f"exchange_choice_{selected_bundle}_{selected_event_id}_{row.field_name}"
            default_choice = (
                row.choice
                if row.choice in {"local", "incoming", "custom"}
                else "local"
            )
            choice = st.radio(
                "Qué valor querés conservar para este campo",
                options=["local", "incoming", "custom"],
                format_func=lambda value: {
                    "local": "Valor de esta copia",
                    "incoming": "Valor recibido",
                    "custom": "Escribir otro valor",
                }[value],
                index=["local", "incoming", "custom"].index(default_choice),
                horizontal=True,
                key=choice_key,
            )
            custom_text = ""
            as_json = False
            if choice == "custom":
                custom_text = st.text_area(
                    "Valor que querés conservar",
                    value=_format_exchange_value(row.resolved_value),
                    key=f"exchange_custom_{selected_bundle}_{selected_event_id}_{row.field_name}",
                )
                as_json = st.checkbox(
                    "Interpretar como JSON",
                    value=isinstance(row.local_value, (dict, list)),
                    key=f"exchange_custom_json_{selected_bundle}_{selected_event_id}_{row.field_name}",
                )
            if st.button(
                "Guardar esta decisión",
                key=f"exchange_save_{selected_bundle}_{selected_event_id}_{row.field_name}",
            ):
                _run_exchange_action(
                    st,
                    db_path=db_path,
                    callback=lambda session, row=row, choice=choice, custom_text=custom_text, as_json=as_json: (
                        lambda saved: f"Decisión guardada para {saved.field_name}"
                    )(
                        save_conflict_resolution(
                            session,
                            bundle_ref=selected_bundle,
                            event_id=row.event_id,
                            field_name=row.field_name,
                            choice=choice,
                            custom_value=(
                                json.loads(custom_text)
                                if choice == "custom" and as_json
                                else custom_text
                                if choice == "custom"
                                else None
                            ),
                            resolved_by=reviewer or "local_user",
                        )
                    ),
                )

    if status is not None:
        if status.overall_status == "ready_to_finalize":
            if st.button(
                "Terminé de resolver las diferencias",
                type="primary",
                key=f"exchange_finalize_{selected_bundle}",
            ):
                _run_exchange_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: (
                        lambda result: (
                            "El paquete ya estaba finalizado"
                            if result.already_finalized
                            else "Diferencias resueltas"
                        )
                    )(
                        finalize_bundle_resolutions(
                            session,
                            bundle_ref=selected_bundle,
                            finalized_by=reviewer or "local_user",
                        )
                    ),
                )

        if selected.status in {"ready_to_apply", "ready_to_apply_resolved"}:
            with st.form(
                f"exchange_apply_commit_{selected_bundle}",
                enter_to_submit=False,
            ):
                confirm_apply = st.checkbox(
                    "Confirmo que quiero incorporar estos cambios y crear antes una copia de seguridad",
                    key=f"exchange_confirm_apply_{selected_bundle}",
                )
                apply_submitted = st.form_submit_button(
                    "Incorporar cambios al proyecto",
                    type="primary",
                    use_container_width=True,
                )
            if apply_submitted:
                if not confirm_apply:
                    st.error("Marcá la confirmación antes de aplicar el paquete.")
                else:
                    _run_exchange_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: (
                            lambda result: _exchange_apply_message(result)
                        )(
                            apply_change_bundle(
                                session,
                                project_root=project_root,
                                bundle_ref=selected_bundle,
                                applied_by=reviewer or "local_user",
                            )
                        ),
                    )

    st.divider()
    archive_panel_key = f"exchange_archive_panel_{selected_bundle}"
    if not st.session_state.get(archive_panel_key, False):
        if st.button(
            "Archivar paquete",
            key=f"exchange_archive_open_{selected_bundle}",
        ):
            st.session_state[archive_panel_key] = True
            rerun_view(st)
    if st.session_state.get(archive_panel_key, False):
        st.markdown("**Archivar paquete**")
        with st.form(
            f"exchange_archive_{selected_bundle}",
            enter_to_submit=False,
        ):
            archive_note = st.text_input(
                "Nota sobre por qué archivás este paquete (opcional)",
                key=f"exchange_archive_note_{selected_bundle}",
            )
            archive_submitted = st.form_submit_button("Archivar")
            archive_cancelled = st.form_submit_button("Cancelar")
        if archive_cancelled:
            st.session_state[archive_panel_key] = False
            rerun_view(st)
        if archive_submitted:
            _run_exchange_action(
                st,
                db_path=db_path,
                callback=lambda session: (
                    set_incoming_bundle_archived(
                        session,
                        bundle_ref=selected_bundle,
                        archived=True,
                        changed_by=reviewer or "local_user",
                        note=archive_note,
                    ),
                    "Paquete archivado",
                )[1],
            )

    if applications:
        with st.expander("Paquetes aplicados anteriormente"):
            for row in applications:
                st.write(
                    f"`{row.bundle_id}` · aplicados {row.applied_event_count} · "
                    f"duplicados {row.duplicate_event_count} · "
                    f"conservados localmente {row.kept_local_event_count} · "
                    f"estado registrado `{row.checkpoint_label}`"
                )

    if st.button(
        "Resolver un problema entre copias",
        key=f"exchange_recovery_entry_{selected_bundle}",
        help=(
            "Abre herramientas excepcionales para reconciliar copias cuando el recorrido "
            "normal de enviar y recibir cambios no alcanza."
        ),
    ):
        st.session_state["exchange_recovery_mode"] = True
        rerun_view(st)

def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Archive Workbench", layout="wide")
    _handle_google_drive_oauth_callback(st)
    _render_global_input_policy(st)
    project_root = _project_root_from_argv()
    if project_root is None:
        selected_root = st.session_state.get("launcher_project_root")
        if selected_root:
            project_root = Path(selected_root).expanduser().resolve()
    if project_root is None:
        _render_launcher(st)
        st.stop()

    decisions_path = project_root / "config" / "decisions.yaml"
    db_path = database_path(project_root)
    if not decisions_path.is_file() or not db_path.is_file():
        st.error(
            "La carpeta elegida no está lista para abrirse como proyecto. Volvé al inicio general para crear un proyecto nuevo o elegí una carpeta que ya tenga su configuración y su base local."
        )
        st.stop()

    try:
        require_current_database(project_root)
    except DatabaseRevisionError as exc:
        st.error(
            "La base local de este proyecto no quedó preparada para esta versión de Archive Workbench. "
            "No se abrirán las secciones para evitar trabajar sobre un estado incompleto."
        )
        with st.expander("Ver detalle técnico"):
            st.code(str(exc))
        st.stop()

    decisions = load_decisions(decisions_path)
    preferences = load_user_preferences()
    try:
        activation = activate_received_team_copy(
            project_root=project_root,
            created_by=preferences.actor or "local_user",
        )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(
            "No se pudo preparar automáticamente esta copia recibida para el trabajo en equipo: "
            f"{exc}"
        )
        st.stop()
    if activation is not None:
        st.success(
            "Esta copia recibida ya tiene una identidad propia y conserva el mismo punto de "
            "partida que las demás copias creadas desde el ZIP original."
        )
        if activation.omitted_content_groups:
            st.info(
                "Esta copia fue preparada deliberadamente sin: "
                + ", ".join(
                    TEAM_COPY_GROUP_LABELS[key]
                    for key in activation.omitted_content_groups
                )
                + ". Esos archivos no se consideran perdidos en la copia de origen."
            )
    _apply_staged_review_preferences(st)
    _apply_palette(st, str(st.session_state.get("review_palette", preferences.palette)))
    type_definitions = [item for item in decisions.object_types if item.editable]
    type_keys = [item.key for item in type_definitions]
    type_labels = {item.key: item.label for item in type_definitions}

    documents = []
    document_map: dict[str, object] = {}
    documents_loaded = False

    def load_review_documents() -> None:
        nonlocal documents, document_map, documents_loaded
        if documents_loaded:
            return
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                documents = review_document_rows(session)
        finally:
            engine.dispose()
        document_map = {item.source_key: item for item in documents}
        documents_loaded = True

    _apply_pending_app_mode(st)
    if isinstance(st.session_state.get("review_pending_navigation"), dict):
        load_review_documents()
        _apply_pending_navigation(st, document_map)
    with st.sidebar:
        st.title("Archive Workbench")
        reviewer, active_palette = _render_preferences(
            st,
            current_actor=preferences.actor,
            current_palette=preferences.palette,
        )
        _apply_palette(st, active_palette)
        if reviewer:
            st.caption(f"Usuario: {reviewer}")
        _require_reviewer_name(st, reviewer=reviewer, palette=active_palette)
        app_mode = st.radio(
            "Sección",
            options=list(_VIEW_LABELS),
            format_func=lambda value: _VIEW_LABELS[value],
            key="review_app_mode",
        )
        if app_mode in _WORKFLOW_STEPS:
            step_index = _WORKFLOW_STEPS.index(app_mode)
            st.caption(
                f"{_VIEW_PHASES[app_mode]} · "
                f"paso {step_index + 1} de {len(_WORKFLOW_STEPS)}"
            )
            with st.popover("Guía de esta sección", use_container_width=True):
                _render_section_guidance(st, app_mode)

    if app_mode in {"review", "search"}:
        load_review_documents()

    def render_active_view() -> None:
        if app_mode == "home":
            render_home_view(
                st,
                project_root=project_root,
                db_path=db_path,
                actor=reviewer,
            )
            return
        if app_mode == "catalog":
            render_catalog_view(
                st,
                project_root=project_root,
                db_path=db_path,
                decisions=decisions,
                actor=reviewer,
            )
            return
        if app_mode == "audiovisual":
            render_audiovisual_view(
                st,
                project_root=project_root,
                db_path=db_path,
                project_id=decisions.project_id,
                actor=reviewer,
            )
            return
        if app_mode == "processing":
            render_processing_view(
                st,
                project_root=project_root,
                db_path=db_path,
                decisions=decisions,
                project_id=decisions.project_id,
                actor=reviewer,
            )
            return
        if app_mode == "work":
            render_work_view(
                st,
                project_root=project_root,
                db_path=db_path,
                project_id=decisions.project_id,
                actor=reviewer,
            )
            return
        if app_mode == "authorities":
            render_authorities_view(
                st,
                db_path=db_path,
                project_id=decisions.project_id,
                actor=reviewer,
            )
            return
        if app_mode == "graph":
            render_graph_view(
                st,
                project_root=project_root,
                db_path=db_path,
                project_id=decisions.project_id,
                actor=reviewer,
            )
            return
        if app_mode == "export":
            render_export_view(
                st,
                project_root=project_root,
                db_path=db_path,
                project_id=decisions.project_id,
                actor=reviewer,
                object_types=type_keys,
                object_type_labels=type_labels,
            )
            return
        if app_mode == "semantic":
            render_semantic_search_view(
                st,
                project_root=project_root,
                db_path=db_path,
                project_id=decisions.project_id,
                actor=reviewer,
                object_types=type_keys,
                object_type_labels=type_labels,
            )
            return
        if app_mode == "search":
            _render_search_view(
                st,
                db_path=db_path,
                project_id=decisions.project_id,
                document_map=document_map,
                type_labels=type_labels,
            )
            return
        if app_mode == "exchange":
            _render_exchange_view(
                st,
                project_root=project_root,
                db_path=db_path,
                reviewer=reviewer,
            )
            return
        if app_mode == "admin":
            render_admin_view(
                st,
                project_root=project_root,
                db_path=db_path,
                actor=reviewer,
            )
            return
        section_heading(st, "Revisar documentos")
        if not documents:
            st.info(
                "Todavía no hay documentos listos para revisar. Primero elegí una extracción en Procesar documentos e inicializá la revisión de sus páginas."
            )
            if st.button("Ir a Procesar documentos", key="review_go_processing_empty"):
                _request_workflow_step(st, "processing")
            return

        with st.sidebar:
            source_key = st.selectbox(
                "Documento que querés revisar",
                options=list(document_map),
                format_func=lambda key: document_map[key].title,
                key="review_source_key",
            )
            document = document_map[source_key]
            state_source = st.session_state.get("review_page_source")
            if state_source != source_key:
                st.session_state["review_page_source"] = source_key
                st.session_state["review_page_number"] = document.editable_pages[0]
            page_options = list(document.editable_pages)
            current_page = st.session_state.get("review_page_number", page_options[0])
            if current_page not in page_options:
                st.session_state["review_page_number"] = page_options[0]
            previous_col, next_col = st.columns(2)
            with previous_col:
                if st.button("← Página anterior", use_container_width=True):
                    index = page_options.index(st.session_state["review_page_number"])
                    if index > 0:
                        st.session_state["review_page_number"] = page_options[index - 1]
                        rerun_view(st)
            with next_col:
                if st.button("Página siguiente →", use_container_width=True):
                    index = page_options.index(st.session_state["review_page_number"])
                    if index < len(page_options) - 1:
                        st.session_state["review_page_number"] = page_options[index + 1]
                        rerun_view(st)
            page = st.selectbox(
                "Página del documento",
                options=page_options,
                key="review_page_number",
            )
            display_options_open = st.toggle(
                "Opciones de visualización",
                value=False,
                key=f"review_display_options_open_{source_key}_{page}",
            )
            show_boxes_key = f"review_show_boxes_{source_key}_{page}"
            include_deleted_key = f"review_include_deleted_{source_key}_{page}"
            show_boxes = bool(
                st.session_state.get(f"{show_boxes_key}__remembered", True)
            )
            include_deleted = bool(
                st.session_state.get(f"{include_deleted_key}__remembered", False)
            )
            if display_options_open:
                with st.container(border=True):
                    if show_boxes_key not in st.session_state:
                        st.session_state[show_boxes_key] = show_boxes
                    if include_deleted_key not in st.session_state:
                        st.session_state[include_deleted_key] = include_deleted
                    show_boxes = st.checkbox(
                        "Mostrar marcos alrededor de los bloques de texto",
                        key=show_boxes_key,
                    )
                    include_deleted = st.checkbox(
                        "Mostrar también bloques de texto eliminados",
                        key=include_deleted_key,
                    )
                    st.session_state[f"{show_boxes_key}__remembered"] = bool(show_boxes)
                    st.session_state[f"{include_deleted_key}__remembered"] = bool(
                        include_deleted
                    )
            document_summary = (
                f"{len(document.editable_pages)}/{document.page_count} páginas disponibles · "
                f"{document.active_objects} textos activos"
            )
            if document.deleted_objects:
                document_summary += f" · {document.deleted_objects} eliminados en historial"
            st.caption(document_summary)
            if document.stale_pages:
                st.warning("Texto desactualizado en páginas: " + ", ".join(map(str, document.stale_pages)))
            page_tools_open = st.toggle(
                "Herramientas de edición de las páginas",
                value=False,
                key=f"review_page_tools_open_{source_key}_{page}",
            )
            if page_tools_open:
                with st.container(border=True):
                    if st.button("Exportar texto y estructura en revisión", use_container_width=True):
                        def export_action() -> str | None:
                            def callback(session):
                                summary = export_editable_layer(
                                    session,
                                    project_root=project_root,
                                    source_key=source_key,
                                )
                                st.session_state["last_export"] = str(summary.output_root)
                            return _database_action(db_path, callback)

                        _run_action(st, export_action)
                    if st.session_state.get("last_export"):
                        st.caption("Última exportación: " + st.session_state["last_export"])

        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                view = review_page_view(
                    session,
                    project_root=project_root,
                    source_key=source_key,
                    page=page,
                    include_deleted=include_deleted,
                )
                availability = page_action_availability(
                    session, editable_page_id=view.editable_page_id
                )
        finally:
            engine.dispose()

        with st.sidebar:
            st.divider()
            page_review_state_open = st.toggle(
                "Estado de revisión de la página",
                value=False,
                key=f"review_page_state_open_{source_key}_{page}",
            )
            if page_review_state_open:
                with st.container(border=True):
                    with st.form(f"page_review_{view.editable_page_id}", enter_to_submit=False):
                        page_status = st.selectbox(
                            "Estado de revisión de esta página",
                            options=list(REVIEW_STATUSES),
                            index=list(REVIEW_STATUSES).index(view.page_review_status),
                            format_func=lambda value: _STATUS_LABELS[value],
                        )
                        page_note = st.text_area("Nota sobre el estado de revisión de esta página (opcional)", value=view.page_review_note or "", height=90)
                        page_review_submit = st.form_submit_button("Guardar el estado de revisión de esta página")
                    if page_review_submit:
                        _run_action(
                            st,
                            lambda: _database_action(
                                db_path,
                                lambda session: set_page_review_status(
                                    session,
                                    editable_page_id=view.editable_page_id,
                                    status=page_status,
                                    changed_by=reviewer or "local_user",
                                    note=page_note,
                                ),
                            ),
                        )

        if view.is_stale:
            st.warning(
                "La extracción elegida para esta página cambió después de preparar la página para revisión. "
                "Las correcciones se conservan, pero no deben mezclarse automáticamente con el nuevo OCR."
            )

        objects_by_id = {item.object_id: item for item in view.objects}
        object_ids = list(objects_by_id)
        object_state_key = f"review_object_{source_key}_{page}_{include_deleted}"
        search_target_object = st.session_state.pop("review_pending_object_id", None)
        if search_target_object in objects_by_id:
            st.session_state[_pending_selection_key(object_state_key)] = search_target_object
        pending_selection = st.session_state.pop(
            _pending_selection_key(object_state_key), None
        )
        if pending_selection in objects_by_id:
            st.session_state[object_state_key] = pending_selection
        selected_id = st.session_state.get(object_state_key)
        if selected_id not in objects_by_id:
            selected_id = object_ids[0] if object_ids else None
            st.session_state[object_state_key] = selected_id

        undo_clicked = False
        redo_clicked = False
        undo_panel_open = st.toggle(
            "Deshacer o rehacer cambios",
            value=False,
            key=f"review_undo_panel_{source_key}_{page}",
        )
        if undo_panel_open:
            undo_col, redo_col = st.columns(2)
            with undo_col:
                undo_clicked = st.button(
                    "↶ Deshacer el último cambio de esta página",
                    disabled=not availability.can_undo,
                    use_container_width=True,
                    help=(
                        "Deshacer " + _ACTION_LABELS.get(availability.undo_label or "", availability.undo_label or "")
                        if availability.can_undo
                        else "No hay acciones nuevas para deshacer"
                    ),
                )
            with redo_col:
                redo_clicked = st.button(
                    "↷ Rehacer el cambio deshecho de esta página",
                    disabled=not availability.can_redo,
                    use_container_width=True,
                    help=(
                        "Rehacer " + _ACTION_LABELS.get(availability.redo_label or "", availability.redo_label or "")
                        if availability.can_redo
                        else "No hay acciones para rehacer"
                    ),
                )
        if undo_clicked:
            _run_action(
                st,
                lambda: _database_action(
                    db_path,
                    lambda session: undo_page_action(
                        session,
                        editable_page_id=view.editable_page_id,
                        changed_by=reviewer or "local_user",
                    ),
                ),
                selection_key=object_state_key,
                fallback_selection=selected_id,
            )
        if redo_clicked:
            _run_action(
                st,
                lambda: _database_action(
                    db_path,
                    lambda session: redo_page_action(
                        session,
                        editable_page_id=view.editable_page_id,
                        changed_by=reviewer or "local_user",
                    ),
                ),
                selection_key=object_state_key,
                fallback_selection=selected_id,
            )

        @st.fragment
        def _render_review_object_fragment() -> None:
            # El bloque activo es estado semántico de esta región. Un clic en bbox
            # rerunea sólo este fragmento; documento y página quedan fuera.
            selected_id = st.session_state.get(object_state_key)
            if selected_id not in objects_by_id:
                selected_id = object_ids[0] if object_ids else None
                st.session_state[object_state_key] = selected_id

            image_column, editor_column = st.columns([1.15, 1], gap="large")
            with image_column:
                st.subheader(f"{view.title} · página {page}/{view.page_count}")
                if view.preview_path is None:
                    st.info("No se encontró el derivado de vista para esta página.")
                elif show_boxes:
                    clicked_id = clickable_review_canvas(
                        view.preview_path,
                        view.objects,
                        page=page,
                        selected_object_id=selected_id,
                        show_deleted=include_deleted,
                        key=f"review_canvas_{source_key}_{page}_{include_deleted}",
                        commit_on_click=True,
                        selection_state_key=object_state_key,
                    )
                    if clicked_id is None and not hasattr(st.components, "v2"):
                        overlay = render_review_overlay(
                            view.preview_path,
                            view.objects,
                            page=page,
                            selected_object_id=selected_id,
                            show_deleted=include_deleted,
                        )
                        st.image(overlay, use_container_width=True)
                        st.info(
                            "La selección directa de bloques de texto sobre la imagen requiere Streamlit 1.51 o posterior. La lista de bloques de la página sigue disponible."
                        )
                else:
                    st.image(str(view.preview_path), use_container_width=True)
                st.caption(
                    "Seleccioná un marco en la imagen para revisar inmediatamente el bloque de texto correspondiente. Usá los botones o Ctrl+rueda para ampliar y arrastrá el fondo para recorrer la imagen."
                )
                _render_search_result_navigation(st)

            with editor_column:
                st.subheader("Revisar texto y estructura de la página")
                if not object_ids:
                    st.info("Esta página no tiene bloques de texto visibles con la configuración actual.")
                else:
                    selected_id = st.selectbox(
                        "Bloque de texto de la página que querés revisar",
                        options=object_ids,
                        format_func=lambda oid: _object_label(objects_by_id[oid], type_labels),
                        key=object_state_key,
                    )
                    selected = objects_by_id[selected_id]
                    with st.expander("Datos del bloque de texto seleccionado", expanded=False):
                        metadata_a, metadata_b = st.columns(2)
                        with metadata_a:
                            _render_wrapping_detail(st, "Orden de lectura", selected.order_index + 1)
                        with metadata_b:
                            _render_wrapping_detail(st, "Revisión", selected.revision_number)
                        metadata_c, metadata_d = st.columns(2)
                        with metadata_c:
                            _render_wrapping_detail(
                                st,
                                "Estado del bloque de texto",
                                _LIFECYCLE_LABELS.get(
                                    selected.lifecycle_status,
                                    selected.lifecycle_status,
                                ),
                            )
                        with metadata_d:
                            _render_wrapping_detail(
                                st,
                                "Estado de revisión del bloque de texto",
                                _STATUS_LABELS[selected.review_status],
                            )
                        if selected.document_part_title:
                            st.caption(
                                f"Parte interna: **{selected.document_part_title}** "
                                f"(`{selected.document_part_key}`)"
                            )
                        else:
                            st.caption("Parte interna: sin asignar")
                        if selected.manually_added:
                            st.caption("Bloque de texto agregado manualmente")
                        else:
                            confidence = selected.attributes.get("source_confidence")
                            if confidence is not None:
                                st.caption(f"Confianza OCR de origen: {float(confidence):.1%}")

                    if selected.text.strip():
                        if st.button(
                            "Buscar fragmentos similares a este bloque",
                            key=f"review_similar_block_{selected.object_id}_{selected.revision_number}",
                            help=(
                                "Usa el texto de este bloque como punto de partida para una nueva "
                                "Búsqueda semántica y excluye este mismo bloque de los resultados."
                            ),
                        ):
                            queue_similar_semantic_search(
                                st,
                                query_text=selected.text,
                                object_id=selected.object_id,
                            )
                            st.session_state["review_search_navigation"] = None
                            request_app_view(st, mode="semantic")
                            rerun_app(st)

                    (
                        edit_tab,
                        structure_tab,
                        form_tab,
                        annotations_tab,
                        entities_tab,
                        attributes_tab,
                        history_tab,
                    ) = tracked_tabs(
                        st,
                        [
                            "Editar texto",
                            "Orden y estructura",
                            "Casilleros y campos",
                            "Estado y anotaciones",
                            "Menciones de entidades",
                            "Datos adicionales",
                            "Historial general",
                        ],
                        key="review_object_tabs",
            help_by_label=TAB_HELP["review_object_tabs"],
                        rerun_on_change=False,
                    )
                    with edit_tab:
                        with st.form(f"edit_{selected.object_id}_{selected.revision_number}", enter_to_submit=False):
                            new_text = st.text_area("Texto corregido", value=selected.text, height=260)
                            type_index = type_keys.index(selected.object_type) if selected.object_type in type_keys else 0
                            new_type = st.selectbox(
                                "Clase de bloque de texto",
                                options=type_keys,
                                index=type_index,
                                format_func=lambda key: type_labels.get(key, key),
                            )
                            note = st.text_input("Nota sobre esta corrección (opcional)")
                            save = st.form_submit_button("Guardar esta corrección como nueva revisión", type="primary")
                        if save:
                            def save_callback(session):
                                return execute_page_action(
                                    session,
                                    editable_page_id=view.editable_page_id,
                                    action_type="edit",
                                    changed_by=reviewer or "local_user",
                                    selected_object_id=selected.object_id,
                                    note=note or None,
                                    action=lambda: update_editable_object(
                                        session,
                                        decisions=decisions,
                                        object_id=selected.object_id,
                                        expected_revision=selected.revision_number,
                                        edited_by=reviewer or "local_user",
                                        text=new_text,
                                        object_type=new_type,
                                        note=note or None,
                                    ),
                                )
                            _run_action(
                                st,
                                lambda: _database_action(db_path, save_callback),
                                selection_key=object_state_key,
                                fallback_selection=selected.object_id,
                            )

                        if selected.original_text is not None:
                            with st.expander("Ver OCR original inmutable"):
                                st.text(selected.original_text)

                        lifecycle_label = (
                            "Restaurar este bloque de texto" if selected.lifecycle_status == "deleted" else "Marcar este bloque de texto como eliminado"
                        )
                        with st.form(f"lifecycle_{selected.object_id}_{selected.revision_number}", enter_to_submit=False):
                            lifecycle_note = st.text_input("Motivo de este cambio en el bloque de texto", key=f"life_note_{selected.object_id}")
                            lifecycle_submit = st.form_submit_button(lifecycle_label)
                        if lifecycle_submit:
                            target_status = "active" if selected.lifecycle_status == "deleted" else "deleted"
                            def lifecycle_callback(session):
                                return execute_page_action(
                                    session,
                                    editable_page_id=view.editable_page_id,
                                    action_type="lifecycle",
                                    changed_by=reviewer or "local_user",
                                    selected_object_id=selected.object_id,
                                    note=lifecycle_note or None,
                                    action=lambda: set_editable_object_lifecycle(
                                        session,
                                        object_id=selected.object_id,
                                        expected_revision=selected.revision_number,
                                        lifecycle_status=target_status,
                                        changed_by=reviewer or "local_user",
                                        note=lifecycle_note or None,
                                    ),
                                )
                            _run_action(
                                st,
                                lambda: _database_action(db_path, lifecycle_callback),
                                selection_key=object_state_key,
                                fallback_selection=selected.object_id,
                            )

                    with structure_tab:
                        structure_task_labels = {
                            "proposal": "Revisar orden y columnas",
                            "columns": "Ajustar columnas",
                            "part": "Asignar parte del documento",
                            "move": "Mover texto",
                            "merge": "Combinar textos",
                            "split": "Dividir texto",
                            "issues": "Resolver fragmentaciones o duplicados",
                            "history": "Historial de orden y estructura",
                        }
                        structure_task_key = f"review_structure_task_{view.editable_page_id}"
                        structure_task = st.selectbox(
                            "Tarea",
                            options=list(structure_task_labels),
                            format_func=lambda value: structure_task_labels[value],
                            key=structure_task_key,
                        )
                        structure_task_label = structure_task_labels[structure_task]
                        mount_choice_help(
                            st,
                            key=structure_task_key,
                            label=structure_task_label,
                            help_text=TASK_HELP["review_structure_task"][structure_task_label],
                        )
                        if structure_task in {"proposal", "columns", "issues", "history"}:
                            _render_layout_structure_panel(
                                st,
                                db_path=db_path,
                                view=view,
                                selected=selected,
                                objects_by_id=objects_by_id,
                                reviewer=reviewer or "local_user",
                                object_state_key=object_state_key,
                                mode=structure_task,
                            )
                        elif structure_task == "part":
                            _render_document_part_panel(
                                st,
                                db_path=db_path,
                                view=view,
                                selected=selected,
                                reviewer=reviewer or "local_user",
                                object_state_key=object_state_key,
                            )
                        elif structure_task == "move":
                            _render_move_text_panel(
                                st,
                                db_path=db_path,
                                view=view,
                                selected=selected,
                                reviewer=reviewer or "local_user",
                                object_state_key=object_state_key,
                            )
                        elif structure_task == "merge":
                            _render_merge_text_panel(
                                st,
                                db_path=db_path,
                                view=view,
                                selected=selected,
                                reviewer=reviewer or "local_user",
                                object_state_key=object_state_key,
                            )
                        else:
                            _render_split_text_panel(
                                st,
                                db_path=db_path,
                                view=view,
                                selected=selected,
                                reviewer=reviewer or "local_user",
                                object_state_key=object_state_key,
                            )

                    with form_tab:
                        _render_form_structure_tab(
                            st,
                            db_path=db_path,
                            view=view,
                            selected=selected,
                            objects_by_id=objects_by_id,
                            reviewer=reviewer or "local_user",
                            object_state_key=object_state_key,
                        )

                    with annotations_tab:
                        with st.form(f"object_review_{selected.object_id}", enter_to_submit=False):
                            object_review_status = st.selectbox(
                                "Estado de revisión del bloque de texto",
                                options=list(REVIEW_STATUSES),
                                index=list(REVIEW_STATUSES).index(selected.review_status),
                                format_func=lambda value: _STATUS_LABELS[value],
                            )
                            object_review_submit = st.form_submit_button("Guardar el estado de revisión de este bloque")
                        if object_review_submit:
                            _run_action(
                                st,
                                lambda: _database_action(
                                    db_path,
                                    lambda session: set_object_review_status(
                                        session,
                                        object_id=selected.object_id,
                                        status=object_review_status,
                                        changed_by=reviewer or "local_user",
                                    ),
                                ),
                                selection_key=object_state_key,
                                fallback_selection=selected.object_id,
                            )

                        st.write("**Etiquetas**")
                        if selected.tags:
                            for tag in selected.tags:
                                tag_col, remove_col = st.columns([5, 1])
                                tag_col.write(
                                    f"**{_TAG_KIND_LABELS.get(tag.tag_kind, tag.tag_kind)}:** "
                                    f"`{tag.tag}`"
                                )
                                if remove_col.button(
                                    "Quitar esta etiqueta", key=f"remove_tag_{selected.object_id}_{tag.tag_id}", help="Quitar esta etiqueta del bloque de texto"
                                ):
                                    _run_action(
                                        st,
                                        lambda tag_id=tag.tag_id: _database_action(
                                            db_path,
                                            lambda session: remove_object_tag(
                                                session,
                                                object_id=selected.object_id,
                                                tag_id=tag_id,
                                            ),
                                        ),
                                        selection_key=object_state_key,
                                        fallback_selection=selected.object_id,
                                    )
                        else:
                            st.caption("El bloque de texto seleccionado no tiene etiquetas.")
                        with st.form(f"add_tag_{selected.object_id}", clear_on_submit=True, enter_to_submit=False):
                            tag_kind = st.selectbox(
                                "Categoría de la etiqueta",
                                options=list(TAG_KINDS),
                                format_func=lambda value: _TAG_KIND_LABELS[value],
                            )
                            new_tag = st.text_input("Texto de la nueva etiqueta")
                            tag_submit = st.form_submit_button("Agregar esta etiqueta al bloque de texto")
                        if tag_submit:
                            def add_tag_callback(session):
                                add_object_tag(
                                    session,
                                    object_id=selected.object_id,
                                    tag=new_tag,
                                    tag_kind=tag_kind,
                                    created_by=reviewer or "local_user",
                                )
                                return selected.object_id
                            _run_action(
                                st,
                                lambda: _database_action(db_path, add_tag_callback),
                                selection_key=object_state_key,
                                fallback_selection=selected.object_id,
                            )

                        st.write("**Comentarios**")
                        # Los comentarios se leen en una sesión separada para mantener la UI simple.
                        comments_engine = create_sqlite_engine(db_path)
                        try:
                            with session_scope(comments_engine) as comments_session:
                                comment_rows = object_comment_rows(
                                    comments_session, object_id=selected.object_id
                                )
                        finally:
                            comments_engine.dispose()
                        if comment_rows:
                            for comment in reversed(comment_rows):
                                st.markdown(
                                    f"**{comment.created_by}** · {comment.created_at.isoformat(timespec='minutes')}"
                                )
                                st.write(comment.body)
                        else:
                            st.caption("El bloque de texto seleccionado no tiene comentarios.")
                        with st.form(f"comment_{selected.object_id}", clear_on_submit=True, enter_to_submit=False):
                            comment_body = st.text_area("Nuevo comentario sobre este bloque de texto", height=100)
                            comment_submit = st.form_submit_button("Agregar este comentario al bloque de texto")
                        if comment_submit:
                            def add_comment_callback(session):
                                add_object_comment(
                                    session,
                                    object_id=selected.object_id,
                                    body=comment_body,
                                    created_by=reviewer or "local_user",
                                )
                                return selected.object_id
                            _run_action(
                                st,
                                lambda: _database_action(db_path, add_comment_callback),
                                selection_key=object_state_key,
                                fallback_selection=selected.object_id,
                            )

                    with attributes_tab:
                        if selected.attributes:
                            st.metric("Datos adicionales de este bloque", len(selected.attributes))
                            st.json(selected.attributes, expanded=True)
                        else:
                            st.info("El bloque de texto seleccionado no tiene datos adicionales vigentes.")

                    with entities_tab:
                        entities_engine = create_sqlite_engine(db_path)
                        try:
                            with session_scope(entities_engine) as entities_session:
                                object_mentions = mention_rows(
                                    entities_session, object_id=selected.object_id
                                )
                                available_authorities = authority_rows(
                                    entities_session,
                                    project_id=decisions.project_id,
                                    lifecycle_statuses=("active",),
                                )
                        finally:
                            entities_engine.dispose()
                        authority_map = {
                            row.authority_id: row for row in available_authorities
                        }
                        authority_options = [None, *authority_map]

                        st.write("**Menciones de entidades vinculadas a este bloque de texto**")
                        if object_mentions:
                            for mention in object_mentions:
                                with st.container(border=True):
                                    mention_header, mention_state = st.columns([4, 2])
                                    mention_header.write(
                                        f"**{mention.mention_text}** · "
                                        f"{mention.authority_name or 'sin entidad vinculada'}"
                                    )
                                    mention_header.caption(
                                        f"offsets {mention.start_offset}:{mention.end_offset} · "
                                        f"origen {mention.source} · revisión textual "
                                        f"{mention.object_revision_number}"
                                    )
                                    if mention.is_stale:
                                        mention_header.warning(
                                            "El texto fue editado después de crear esta mención. "
                                            "Verificá los offsets antes de aceptarla."
                                        )
                                    with mention_state.form(
                                        f"mention_update_{mention.mention_id}_{mention.revision}",
                                        enter_to_submit=False,
                                    ):
                                        status_choice = st.selectbox(
                                            "Estado de la mención",
                                            options=list(MENTION_STATUSES),
                                            index=list(MENTION_STATUSES).index(mention.status),
                                            format_func=lambda value: _MENTION_STATUS_LABELS[value],
                                        )
                                        authority_choice = st.selectbox(
                                            "Entidad vinculada a esta mención",
                                            options=authority_options,
                                            index=(
                                                authority_options.index(mention.authority_id)
                                                if mention.authority_id in authority_options
                                                else 0
                                            ),
                                            format_func=lambda value: (
                                                "Sin vincular"
                                                if value is None
                                                else (
                                                    f"{authority_map[value].preferred_name} · "
                                                    f"{_AUTHORITY_TYPE_LABELS[authority_map[value].entity_type]}"
                                                )
                                            ),
                                        )
                                        mention_note = st.text_input(
                                            "Nota sobre esta mención (opcional)", value=mention.note or ""
                                        )
                                        mention_submit = st.form_submit_button("Guardar cambios de la mención")
                                    if mention_submit:
                                        if (
                                            authority_choice is None
                                            and status_choice in LINKED_MENTION_STATUSES
                                        ):
                                            st.error(
                                                "Una mención aceptada o modificada debe estar "
                                                "vinculada a una entidad."
                                            )
                                        else:
                                            _run_action(
                                                st,
                                                lambda mention=mention, status_choice=status_choice,
                                                authority_choice=authority_choice,
                                                mention_note=mention_note: _database_action(
                                                    db_path,
                                                    lambda session: update_mention(
                                                        session,
                                                        mention_id=mention.mention_id,
                                                        expected_revision=mention.revision,
                                                        status=status_choice,
                                                        authority_id=authority_choice,
                                                        note=mention_note,
                                                        changed_by=reviewer or "local_user",
                                                    ),
                                                ),
                                                selection_key=object_state_key,
                                                fallback_selection=selected.object_id,
                                            )
                        else:
                            st.caption("Sin menciones registradas")

                        scan_col, note_col = st.columns([2, 3])
                        with scan_col:
                            scan_dictionary = st.button(
                                "Buscar posibles menciones de entidades en este bloque",
                                use_container_width=True,
                                key=f"entity_scan_{selected.object_id}_{selected.revision_number}",
                            )
                        with note_col:
                            st.caption(
                                "Busca en este bloque de texto nombres que ya figuran en las fichas de entidades del proyecto y propone posibles menciones para que las revises antes de guardarlas."
                            )
                        if scan_dictionary:
                            result_holder: dict[str, object] = {}

                            def scan_callback(session):
                                summary = suggest_dictionary_mentions(
                                    session,
                                    object_id=selected.object_id,
                                    created_by=reviewer or "local_user",
                                    quality_scope_source="ui",
                                )
                                result_holder["summary"] = summary
                                return selected.object_id

                            _run_action(
                                st,
                                lambda: _database_action(db_path, scan_callback),
                                selection_key=object_state_key,
                                fallback_selection=selected.object_id,
                            )

                        st.divider()
                        st.write("**Agregar una mención manual**")
                        if not available_authorities:
                            st.info(
                                "Primero creá un registro en la vista Entidades. "
                                "También podés registrar una mención sin vincular."
                            )
                        with st.form(
                            f"mention_create_{selected.object_id}_{selected.revision_number}",
                            clear_on_submit=True,
                            enter_to_submit=False,
                        ):
                            manual_text = st.text_input(
                                "Texto exacto de la mención que querés registrar",
                                placeholder="Debe aparecer en el texto corregido actual",
                            )
                            manual_occurrence = st.number_input(
                                "Qué aparición de ese texto querés registrar",
                                min_value=1,
                                value=1,
                                step=1,
                                help="Usá 2, 3, etc. cuando el mismo texto aparece varias veces.",
                            )
                            manual_authority = st.selectbox(
                                "Entidad con la que querés vincular esta mención",
                                options=authority_options,
                                format_func=lambda value: (
                                    "Sin vincular"
                                    if value is None
                                    else (
                                        f"{authority_map[value].preferred_name} · "
                                        f"{_AUTHORITY_TYPE_LABELS[authority_map[value].entity_type]}"
                                    )
                                ),
                            )
                            manual_status = st.selectbox(
                                "Estado de la mención",
                                options=list(MENTION_STATUSES),
                                index=list(MENTION_STATUSES).index("accepted"),
                                format_func=lambda value: _MENTION_STATUS_LABELS[value],
                            )
                            manual_note = st.text_input("Nota sobre este registro (opcional)")
                            manual_submit = st.form_submit_button("Agregar esta mención de entidad")
                        if manual_submit:
                            if manual_authority is None and manual_status in LINKED_MENTION_STATUSES:
                                st.error(
                                    "Una mención aceptada o modificada debe estar vinculada a una ficha de entidad. Usá Pendiente o Rechazada si todavía no querés vincularla."
                                )
                            else:
                                _run_action(
                                    st,
                                    lambda: _database_action(
                                        db_path,
                                        lambda session: create_mention(
                                            session,
                                            object_id=selected.object_id,
                                            mention_text=manual_text,
                                            occurrence=int(manual_occurrence),
                                            authority_id=manual_authority,
                                            status=manual_status,
                                            source="manual",
                                            note=manual_note,
                                            created_by=reviewer or "local_user",
                                        ),
                                    ),
                                    selection_key=object_state_key,
                                    fallback_selection=selected.object_id,
                                )

                    with history_tab:
                        history_engine = create_sqlite_engine(db_path)
                        try:
                            with session_scope(history_engine) as history_session:
                                timeline = page_history_rows(
                                    history_session, source_key=source_key, page=page
                                )
                                history = object_revision_rows(
                                    history_session, object_id=selected.object_id
                                )
                        finally:
                            history_engine.dispose()

                        scope = st.radio(
                            "Qué cambios querés ver en este historial",
                            options=["page", "object"],
                            format_func=lambda value: {
                                "page": "Toda la página",
                                "object": "Sólo el bloque de texto seleccionado",
                            }[value],
                            horizontal=True,
                            key=f"history_scope_{source_key}_{page}_{selected.object_id}",
                        )
                        visible_timeline = (
                            timeline
                            if scope == "page"
                            else [item for item in timeline if item.object_id == selected.object_id]
                        )
                        if not visible_timeline:
                            st.caption("Todavía no hay acontecimientos para este filtro.")
                        for index, item in enumerate(visible_timeline):
                            label = (
                                f"{item.title} · {item.actor} · "
                                f"{item.occurred_at.isoformat(timespec='minutes')}"
                            )
                            with st.expander(label, expanded=index == 0):
                                st.caption(f"{item.category} · {item.operation}")
                                if item.note:
                                    st.write(item.note)
                                simple_details = []
                                if item.details.get("revision") is not None:
                                    simple_details.append(f"revisión {item.details['revision']}")
                                if item.details.get("object"):
                                    simple_details.append(str(item.details["object"]))
                                if item.details.get("object_type"):
                                    simple_details.append(
                                        type_labels.get(
                                            str(item.details["object_type"]),
                                            str(item.details["object_type"]),
                                        )
                                    )
                                if item.details.get("order") is not None:
                                    simple_details.append(f"orden {item.details['order']}")
                                if item.details.get("status"):
                                    simple_details.append(f"estado {item.details['status']}")
                                if item.details.get("review_status"):
                                    simple_details.append(
                                        "revisión "
                                        + _STATUS_LABELS.get(
                                            str(item.details["review_status"]),
                                            str(item.details["review_status"]),
                                        )
                                    )
                                if simple_details:
                                    st.caption(" · ".join(simple_details))

                        previous_revisions = [
                            item.revision_number
                            for item in history
                            if item.revision_number < selected.revision_number
                        ]
                        if previous_revisions:
                            restore_revision_open = st.toggle(
                                "Restaurar una revisión anterior",
                                value=False,
                                key=f"review_restore_revision_open_{selected.object_id}",
                            )
                            if restore_revision_open:
                                with st.container(border=True):
                                    with st.form(
                                        f"revert_{selected.object_id}_{selected.revision_number}",
                                        enter_to_submit=False,
                                    ):
                                        target_revision = st.selectbox(
                                            "Revisión anterior cuyo contenido querés restaurar",
                                            options=previous_revisions,
                                            format_func=lambda number: f"Revisión {number}",
                                        )
                                        revert_note = st.text_input("Nota sobre esta restauración (opcional)")
                                        revert_submit = st.form_submit_button(
                                            "Restaurar ese contenido como una nueva revisión"
                                        )
                                    if revert_submit:
                                        def revert_callback(session):
                                            return execute_page_action(
                                                session,
                                                editable_page_id=view.editable_page_id,
                                                action_type="revert",
                                                changed_by=reviewer or "local_user",
                                                selected_object_id=selected.object_id,
                                                note=revert_note or None,
                                                action=lambda: revert_editable_object(
                                                    session,
                                                    object_id=selected.object_id,
                                                    target_revision=target_revision,
                                                    expected_revision=selected.revision_number,
                                                    reverted_by=reviewer or "local_user",
                                                    note=revert_note or None,
                                                ),
                                            )
                                        _run_action(
                                            st,
                                            lambda: _database_action(db_path, revert_callback),
                                            selection_key=object_state_key,
                                            fallback_selection=selected.object_id,
                                        )


                if not object_ids:
                    st.info(
                        "Esta página todavía no tiene texto para revisar. Para agregar texto y ubicarlo sobre la imagen, "
                        "usá «Procesar documentos > Corregir o agregar»."
                    )

        _render_review_object_fragment()

    mount_view_scroll_keeper(st, view_key=app_mode)
    render_active_view()

if __name__ == "__main__":
    main()
