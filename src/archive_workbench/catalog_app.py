from __future__ import annotations

from archive_workbench.ui_help import TAB_HELP, TASK_HELP
from collections import Counter, defaultdict
from pathlib import Path
import tempfile

from typing import Callable

from archive_workbench.authorities import authority_rows, create_authority
from archive_workbench.local_picker import choose_local_directory
from archive_workbench.runtime_environment import managed_workspace, workspace_display_path
from archive_workbench.catalog_tree import catalog_tree_select
from archive_workbench.ui_navigation import mount_choice_help, rerun_app, rerun_view, request_app_view, section_heading, tracked_tabs

from archive_workbench.catalog import ensure_project, scan_file_instances
from archive_workbench.catalog_management import (
    REGISTRATION_STATUSES,
    RELATION_TYPES,
    archival_field_rows,
    archival_revision_rows,
    archival_unit_delete_blockers,
    catalog_summary,
    catalog_unit_rows,
    change_archival_unit_level,
    create_archival_unit,
    delete_archival_unit,
    digital_object_choices,
    link_existing_digital_object,
    move_archival_unit,
    remove_file_instance,
    register_external_file,
    register_local_file,
    register_uploaded_file,
    undo_last_archival_move,
    unlink_digital_object_from_unit,
    search_catalog_units,
    unit_digital_objects,
    update_archival_unit,
)
from archive_workbench.catalog_templates import (
    apply_catalog_template,
    export_catalog_template_bytes,
    validate_catalog_template,
)
from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.db.models import ArchivalUnit
from archive_workbench.inspection import PROCESSABLE_DOCUMENT_SUFFIXES, inspect_input
from archive_workbench.project_setup import add_standard_collection_level, update_archival_parent_keys
from archive_workbench.relations import (
    ARCHIVAL_ROLE_KINDS,
    RELATION_KIND_LABELS,
    RELATION_EDITABLE_LIFECYCLE_STATUSES,
    RELATION_REVIEW_STATUSES,
    create_entity_relation,
    delete_entity_relation,
    entity_relation_revision_rows,
    entity_relation_rows,
    update_entity_relation,
)
from archive_workbench.temporal import format_temporal_range

_STATUS_LABELS = {
    "incomplete": "Incompleto",
    "provisional": "Provisional",
    "complete": "Completo",
}
_FIELD_STATE_LABELS = {
    "provided": "Informado",
    "no_information": "Sin información",
    "not_applicable": "No corresponde",
    "pending": "Pendiente",
}
_RELATION_LABELS = {
    "represents": "Representa",
    "contains": "Contiene",
    "is_part_of": "Es parte de",
    "alternate_representation": "Representación alternativa",
}
_RELATION_HELP = {
    "represents": (
        "Este archivo digital corresponde a la unidad completa que seleccionaste. Por ejemplo, un PDF "
        "que contiene todas las páginas de un documento o un legajo completo."
    ),
    "contains": (
        "Este archivo digital contiene la unidad seleccionada y también otras unidades. Por ejemplo, un "
        "PDF que reúne varios documentos. Podés indicar qué páginas corresponden a esta unidad."
    ),
    "is_part_of": (
        "Este archivo digital es solo una parte de la unidad seleccionada. Usá esta relación cuando una "
        "unidad completa está distribuida entre varios archivos."
    ),
    "alternate_representation": (
        "Este archivo digital es otra representación de un contenido ya registrado, por ejemplo una nueva "
        "digitalización, una copia corregida o el mismo contenido en otro formato."
    ),
}
_PRESENCE_LABELS = {
    "present": "Disponible",
    "missing": "Ausente",
    "modified": "Modificado",
    "unverified": "Sin verificar",
}
_OPERATION_LABELS = {
    "baseline": "Estado inicial",
    "create": "Creación",
    "update": "Actualización descriptiva",
    "move": "Movimiento en la jerarquía",
    "change_level": "Cambio de tipo de unidad",
    "undo_move": "Reversión de movimiento",
}

_ROLE_STATUS_LABELS = {
    "active": "Activo",
    "inactive": "Inactivo / histórico",
}
_ROLE_REVIEW_LABELS = {
    "unreviewed": "Sin revisar",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}

_SEMANTIC_KIND_LABELS = {
    "custody_context": "Repositorio o contexto de custodia",
    "record_set": "Conjunto documental",
    "record": "Recurso documental",
    "container": "Contenedor o unidad física",
    "other": "Nivel configurable del catálogo",
}
_RECORD_SET_TYPE_LABELS = {
    "fonds": "Fondo",
    "collection": "Colección construida",
    "series": "Serie",
    "file": "Expediente o legajo",
    "other": "Otra agrupación documental",
}


def _level_semantic_label(level) -> str:
    kind = level.resolved_semantic_kind
    base = _SEMANTIC_KIND_LABELS.get(kind, _SEMANTIC_KIND_LABELS["other"])
    record_set_type = level.resolved_record_set_type
    if kind == "record_set" and record_set_type is not None:
        return f"{base} · {_RECORD_SET_TYPE_LABELS.get(record_set_type, record_set_type)}"
    return base


def _catalog_parent_relation_caption(*, parent_level, parent_path: str, child_level=None) -> str:
    parent_kind = parent_level.resolved_semantic_kind
    child_kind = child_level.resolved_semantic_kind if child_level is not None else None
    if parent_kind == "custody_context":
        return (
            f"Contexto de custodia: {parent_path}. Esta relación indica dónde se conserva o gestiona "
            "la unidad; no convierte al repositorio en un nivel interno del fondo o la colección."
        )
    if child_kind == "container" or parent_kind == "container":
        return f"Ubicación física: la unidad se ubica en el contexto de {parent_path}."
    if parent_kind == "record_set" and child_kind in {"record_set", "record"}:
        return f"Jerarquía documental: la unidad forma parte de {parent_path}."
    if parent_kind == "record_set" and child_kind is None:
        return (
            f"Nivel superior: {parent_path}. Según el tipo de unidad que agregues, esta relación puede "
            "expresar jerarquía documental o ubicación física."
        )
    return f"Nivel superior del catálogo: {parent_path}."
_PROCESSING_STATUS_LABELS = {
    "not_started": "No iniciado",
    "queued": "En cola",
    "running": "En ejecución",
    "completed": "Completado",
    "completed_with_warnings": "Completado con advertencias",
    "failed": "Fallido",
    "stale": "Desactualizado",
}


def _directory_input_with_picker(
    st,
    *,
    label: str,
    key: str,
    initial_value: str,
    picker_initial: Path,
    picker_title: str,
    help_text: str,
    relative_to: Path | None = None,
) -> str:
    pending_key = f"{key}__pending"
    pending = st.session_state.pop(pending_key, None)
    if pending is not None:
        st.session_state[key] = pending
    st.session_state.setdefault(key, initial_value)
    value = st.text_input(label, key=key, help=help_text)
    if managed_workspace() is None:
        if st.button("Elegir esta carpeta en la computadora", key=f"{key}__choose"):
            selected, error = choose_local_directory(picker_initial, title=picker_title)
            if error:
                st.warning(error)
            elif selected is not None:
                selected_value = str(selected)
                if relative_to is not None:
                    try:
                        selected_value = selected.resolve().relative_to(relative_to.resolve()).as_posix()
                    except ValueError:
                        st.error("Elegí una carpeta ubicada dentro de la carpeta del proyecto.")
                        return value
                    if selected_value == ".":
                        selected_value = ""
                st.session_state[pending_key] = selected_value
                rerun_view(st)
    return value
_SUPPORTED_DOCUMENT_SUFFIXES = PROCESSABLE_DOCUMENT_SUFFIXES


def _run_catalog_action(st, *, db_path: Path, callback: Callable, unit_id: str | None = None) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            result = callback(session)
    except (ValueError, RuntimeError, OSError, FileNotFoundError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    message = result
    target_unit_id = unit_id
    if isinstance(result, tuple) and len(result) == 2:
        message, target_unit_id = result
    if target_unit_id:
        st.session_state["catalog_pending_unit_id"] = str(target_unit_id)
    if message:
        st.session_state["catalog_flash"] = str(message)
    rerun_view(st)


def _unit_label(row, level_labels: dict[str, str]) -> str:
    indent = "　" * row.depth
    status = _STATUS_LABELS.get(row.registration_status, row.registration_status)
    files = (
        f" · {row.digital_object_count} "
        f"{'contenido digital' if row.digital_object_count == 1 else 'contenidos digitales'}"
        if row.digital_object_count
        else ""
    )
    return f"{indent}{level_labels.get(row.level_key, row.level_key)} · {row.title} · {status}{files}"


def _catalog_tree_include_ids(rows, matching_ids: set[str]) -> set[str]:
    by_id = {row.id: row for row in rows}
    include = set(matching_ids)
    for unit_id in tuple(matching_ids):
        current = by_id.get(unit_id)
        seen: set[str] = set()
        while current is not None and current.parent_id and current.parent_id not in seen:
            seen.add(current.parent_id)
            include.add(current.parent_id)
            current = by_id.get(current.parent_id)
    return include


def _catalog_descendant_ids(rows, unit_id: str) -> set[str]:
    children: dict[str | None, list[str]] = defaultdict(list)
    for row in rows:
        children[row.parent_id].append(row.id)
    result: set[str] = set()
    pending = list(children.get(unit_id, []))
    while pending:
        current = pending.pop()
        if current in result:
            continue
        result.add(current)
        pending.extend(children.get(current, []))
    return result


def _field_payload(existing_by_key: dict[str, list], field_def, values: str, state: str) -> dict:
    notes = [row.source_note for row in existing_by_key.get(field_def.key, []) if row.source_note]
    return {
        "state": state,
        "values": [line.strip() for line in values.splitlines() if line.strip()],
        "source_note": notes[0] if notes else None,
    }


def _existing_field_payload(existing_by_key: dict[str, list], field_def) -> dict | None:
    rows = existing_by_key.get(field_def.key, [])
    if not rows:
        return None
    notes = [row.source_note for row in rows if row.source_note]
    return {
        "state": rows[0].value_state,
        "values": [str(row.value) for row in rows if row.value is not None],
        "source_note": notes[0] if notes else None,
    }


def _inspect_uploaded_file(name: str, content: bytes):
    suffix = Path(name).suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as handle:
        handle.write(content)
        handle.flush()
        return inspect_input(Path(handle.name))


def _project_corpus_files(project_root: Path) -> list[Path]:
    corpus = project_root / "corpus"
    if not corpus.is_dir():
        return []
    return [
        path
        for path in sorted(corpus.rglob("*"))
        if path.is_file() and path.suffix.lower() in _SUPPORTED_DOCUMENT_SUFFIXES
    ]


def _external_folder_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return [
        path
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.suffix.lower() in _SUPPORTED_DOCUMENT_SUFFIXES
    ]


def _default_page_range(path: Path) -> tuple[int, int]:
    inspection = inspect_input(path)
    count = int(inspection.page_count or 1)
    return 1, max(1, count)


def _relation_help_text(relation_type: str) -> str:
    return _RELATION_HELP.get(relation_type, "Elegí cómo se relaciona este archivo con la unidad seleccionada.")


def _render_catalog_structure_editor(st, *, decisions, project_root: Path) -> None:
    st.write("**Configurar relaciones permitidas entre niveles**")
    st.write(
        "El árbol del catálogo combina contexto de custodia, jerarquía documental y ubicación física. "
        "Podés ajustar qué nivel superior admite cada tipo sin editar archivos de configuración manualmente."
    )
    levels = sorted(
        [item for item in decisions.archival_levels if item.enabled],
        key=lambda item: item.display_order,
    )
    labels = {item.key: item.label for item in levels}
    updates: dict[str, list[str]] = {}
    for index, level in enumerate(levels):
        eligible = [item.key for item in levels[:index]]
        selected = [value for value in level.parent_keys if value in eligible]
        updates[level.key] = st.multiselect(
            f"Nivel superior permitido para {level.label}",
            options=eligible,
            default=selected,
            format_func=lambda value: labels[value],
            key=f"catalog_structure_parents_{level.key}",
            help=(
                f"{_level_semantic_label(level)}. Dejalo vacío si este nivel puede aparecer en la raíz del catálogo. "
                "Sólo se ofrecen niveles anteriores para evitar ciclos."
            ),
        )
    if st.button("Guardar estructura del catálogo", type="primary", key="catalog_structure_save"):
        try:
            update_archival_parent_keys(project_root / "config" / "decisions.yaml", updates)
        except (OSError, ValueError) as exc:
            st.error(str(exc))
        else:
            st.session_state["catalog_flash"] = (
                "Estructura actualizada. Archive Workbench volvió a cargar las reglas del catálogo."
            )
            rerun_app(st)


def _batch_unit_suggestion(path: Path, unit_rows) -> str:
    from archive_workbench.identity import slugify

    file_tokens = [token for token in slugify(path.stem).split("_") if len(token) >= 3]
    if len(file_tokens) <= 1:
        file_tokens = [token for token in slugify(path.stem).replace("_", "-").split("-") if len(token) >= 3]
    if not file_tokens:
        return ""

    def token_matches(left: str, right: str) -> bool:
        return left == right or left.startswith(right) or right.startswith(left)

    best_path = ""
    best_score = 0
    best_depth = -1
    ambiguous = False
    for row in unit_rows:
        unit_slug = slugify(row.title).replace("_", "-")
        unit_tokens = [token for token in unit_slug.split("-") if len(token) >= 3]
        score = sum(
            1
            for file_token in file_tokens
            if any(token_matches(file_token, unit_token) for unit_token in unit_tokens)
        )
        depth = int(getattr(row, "depth", 0))
        if score > best_score or (score == best_score and score > 0 and depth > best_depth):
            best_score = score
            best_path = row.path
            best_depth = depth
            ambiguous = False
        elif score == best_score and score > 0 and depth == best_depth and row.path != best_path:
            ambiguous = True
    return best_path if best_score >= 2 and not ambiguous else ""


def _render_batch_import(st, *, project_root: Path, db_path: Path, decisions, actor: str, all_rows) -> None:
    st.subheader("Incorporar archivos por lote")
    st.write(
        "Podés revisar muchos archivos antes de registrarlos. Para cada archivo elegís la unidad "
        "del catálogo, el tipo de relación y el rango de páginas. Archive Workbench procesa cada "
        "archivo por separado, de modo que un error no obliga a repetir los que ya terminaron."
    )
    if not all_rows:
        st.info("Primero creá o importá al menos una unidad del catálogo.")
        return

    workspace = managed_workspace()
    mode = st.radio(
        "Dónde están los archivos",
        options=["project", "external"],
        format_func=lambda value: (
            "Ya están dentro de corpus/ en este proyecto"
            if value == "project"
            else (
                "Están en ArchiveWorkbenchData/Imports/Documents"
                if workspace is not None
                else "Están en otra carpeta de esta computadora y quiero copiarlos al proyecto"
            )
        ),
        horizontal=True,
        key="catalog_batch_mode",
    )
    source_root: Path | None = None
    destination_dir = "corpus/importados"
    source_description = ""
    if mode == "project":
        source_root = project_root / "corpus"
        source_description = str(source_root)
        st.caption(
            "Archive Workbench revisará los archivos PDF, TIFF, PNG, JPEG y WebP que ya estén guardados dentro de "
            "corpus/ y sus subcarpetas."
        )
    else:
        if workspace is not None:
            external_path = str(workspace.document_imports)
            st.caption(
                "Copiá los documentos que querés incorporar por lote a "
                "`ArchiveWorkbenchData/Imports/Documents`. Archive Workbench lee esa carpeta y "
                "sus subcarpetas sin modificar los archivos que están allí."
            )
        else:
            external_key = "catalog_batch_external_folder"
            external_current = str(st.session_state.get(external_key, project_root.parent))
            external_path = _directory_input_with_picker(
                st,
                label="Carpeta de la computadora que contiene los archivos",
                key=external_key,
                initial_value=str(project_root.parent),
                picker_initial=Path(external_current),
                picker_title="Elegir carpeta que contiene los archivos",
                help_text=(
                    "Elegí la carpeta que contiene los archivos. Archive Workbench la lee para preparar "
                    "el lote."
                ),
            )
        destination_key = "catalog_batch_destination"
        destination_current = str(
            st.session_state.get(destination_key, "corpus/importados")
        )
        destination_dir = _directory_input_with_picker(
            st,
            label="Carpeta del proyecto donde se copiarán los archivos",
            key=destination_key,
            initial_value="corpus/importados",
            picker_initial=project_root / destination_current,
            picker_title="Elegir carpeta de destino dentro del proyecto",
            help_text=(
                "Los archivos seleccionados se copiarán dentro de esta subcarpeta del proyecto y se conservarán "
                "sus subcarpetas de origen."
            ),
            relative_to=project_root,
        )
        if external_path.strip():
            source_root = Path(external_path).expanduser().resolve()
            source_description = workspace_display_path(source_root) if workspace is not None else str(source_root)

    scan_signature = (mode, source_description, destination_dir)
    if st.button(
        "Preparar una lista de los archivos de esta carpeta",
        type="primary",
        key="catalog_batch_scan",
    ):
        if source_root is None or not source_root.is_dir():
            st.error("Elegí una carpeta existente antes de revisar el lote.")
        else:
            source_files = (
                _project_corpus_files(project_root)
                if mode == "project"
                else _external_folder_files(source_root)
            )
            if not source_files:
                st.warning("No se encontraron archivos PDF, TIFF, PNG, JPEG o WebP en esa carpeta.")
            else:
                existing_hashes: set[str] = set()
                scan_engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(scan_engine) as session:
                        existing_hashes = {
                            row.sha256
                            for row in digital_object_choices(session, decisions.project_id)
                        }
                finally:
                    scan_engine.dispose()

                rows = []
                for path in source_files:
                    relative_display = path.relative_to(source_root).as_posix()
                    try:
                        inspection = inspect_input(path)
                        page_start = 1
                        page_end = max(1, int(inspection.page_count or 1))
                        media_type = str(inspection.media_type)
                        size_label = f"{inspection.byte_size / (1024 * 1024):.1f} MiB"
                        digest = inspection.sha256
                        problem = ""
                    except (OSError, ValueError, RuntimeError) as exc:
                        page_start, page_end = 1, 1
                        media_type = "-"
                        size_label = "-"
                        digest = ""
                        problem = str(exc)
                    rows.append(
                        {
                            "Importar": not bool(problem),
                            "Archivo": relative_display,
                            "Formato": media_type,
                            "Páginas": page_end,
                            "Tamaño": size_label,
                            "Unidad del catálogo": _batch_unit_suggestion(path, all_rows),
                            "Relación": _RELATION_LABELS["represents"],
                            "Página inicial": page_start,
                            "Página final": page_end,
                            "Coincidencia de contenido": "",
                            "Problema detectado": problem,
                            "__source": str(path),
                            "__sha256": digest,
                        }
                    )
                hash_counts = Counter(
                    row["__sha256"] for row in rows if row["__sha256"]
                )
                for row in rows:
                    digest = row["__sha256"]
                    notices = []
                    if digest and digest in existing_hashes:
                        notices.append("Ya registrado en este proyecto")
                    if digest and hash_counts[digest] > 1:
                        notices.append("Mismo contenido repetido en este lote")
                    row["Coincidencia de contenido"] = "; ".join(notices)
                st.session_state["catalog_batch_rows"] = rows
                st.session_state["catalog_batch_scan_signature"] = scan_signature
                st.session_state["catalog_batch_editor_version"] = (
                    int(st.session_state.get("catalog_batch_editor_version", 0)) + 1
                )
                rerun_view(st)

    stored_rows = st.session_state.get("catalog_batch_rows")
    stored_signature = st.session_state.get("catalog_batch_scan_signature")
    if not stored_rows:
        st.info(
            "Pulsá «Preparar una lista de los archivos de esta carpeta» para revisar qué archivos se incorporarían antes de guardar cambios en el proyecto."
        )
        return
    if stored_signature != scan_signature:
        st.warning(
            "Cambiaste la carpeta de origen o la carpeta de destino después de preparar la lista. Volvé a preparar la lista antes de incorporar archivos."
        )
        return

    import pandas as pd

    frame = pd.DataFrame(stored_rows)
    source_lookup = {str(row["Archivo"]): str(row["__source"]) for row in stored_rows}
    sha_lookup = {str(row["Archivo"]): str(row.get("__sha256") or "") for row in stored_rows}
    unit_options = [row.path for row in all_rows]
    unit_by_path = {row.path: row for row in all_rows}
    relation_labels = [_RELATION_LABELS[value] for value in RELATION_TYPES]
    relation_by_label = {label: key for key, label in _RELATION_LABELS.items()}
    editor_version = int(st.session_state.get("catalog_batch_editor_version", 0))

    edited = st.data_editor(
        frame.drop(columns=["__source", "__sha256"]),
        hide_index=True,
        use_container_width=True,
        key=f"catalog_batch_editor_{editor_version}",
        disabled=[
            "Archivo",
            "Formato",
            "Páginas",
            "Tamaño",
            "Coincidencia de contenido",
            "Problema detectado",
        ],
        column_config={
            "Importar": st.column_config.CheckboxColumn("Importar"),
            "Unidad del catálogo": st.column_config.SelectboxColumn(
                "Unidad del catálogo", options=[""] + unit_options, required=False
            ),
            "Relación": st.column_config.SelectboxColumn(
                "Relación", options=relation_labels, required=True
            ),
            "Página inicial": st.column_config.NumberColumn(
                "Página inicial", min_value=1, step=1
            ),
            "Página final": st.column_config.NumberColumn(
                "Página final", min_value=1, step=1
            ),
        },
    )

    folders = sorted(
        {
            str(Path(value).parent)
            for value in edited["Archivo"]
            if str(Path(value).parent) != "."
        }
    )
    folder_rule_open = st.toggle(
        "Asignar la misma unidad del catálogo a varios archivos de una subcarpeta",
        value=False,
        key="catalog_batch_folder_rule_open",
    )
    if folder_rule_open:
        with st.container(border=True):
            st.write(
                "Usalo cuando varios archivos de una subcarpeta pertenecen a la misma unidad. La regla "
                "sólo modifica la tabla de revisión; podés corregir cualquier fila antes de incorporar."
            )
            if folders:
                folder = st.selectbox(
                    "Subcarpeta cuyos archivos querés asignar juntos", options=folders, key="catalog_batch_rule_folder"
                )
                folder_unit = st.selectbox(
                    "Unidad del catálogo para esa carpeta",
                    options=[""] + unit_options,
                    format_func=lambda value: "Elegir..." if not value else value,
                    key="catalog_batch_rule_unit",
                )
                folder_relation = st.selectbox(
                    "Cómo se vinculan esos archivos con la unidad elegida",
                    options=relation_labels,
                    key="catalog_batch_rule_relation",
                )
                if st.button("Aplicar esta asignación a los archivos de la subcarpeta", key="catalog_batch_apply_folder_rule"):
                    updated = edited.copy()
                    mask = updated["Archivo"].map(
                        lambda value: str(Path(str(value)).parent) == folder
                    )
                    updated.loc[mask, "Unidad del catálogo"] = folder_unit
                    updated.loc[mask, "Relación"] = folder_relation
                    new_rows = []
                    for record in updated.to_dict(orient="records"):
                        record["__source"] = source_lookup[str(record["Archivo"])]
                        record["__sha256"] = sha_lookup[str(record["Archivo"])]
                        new_rows.append(record)
                    st.session_state["catalog_batch_rows"] = new_rows
                    st.session_state["catalog_batch_editor_version"] = editor_version + 1
                    rerun_view(st)
            else:
                st.caption("Este lote no contiene subcarpetas.")

    exceptions_panel_open = st.toggle(
        "Corregir archivos que no siguen la asignación de su subcarpeta",
        value=False,
        key="catalog_batch_exceptions_open",
    )
    if exceptions_panel_open:
        with st.container(border=True):
            if st.session_state.pop("catalog_batch_exception_files__clear", False):
                st.session_state["catalog_batch_exception_files"] = []
            st.write(
                "Si una regla de carpeta asignó casi todos los archivos correctamente, elegí en este selector sólo "
                "los archivos que necesitan otra unidad o relación. Podés buscar por nombre dentro del selector."
            )
            exception_files = st.multiselect(
                "Archivos que son una excepción",
                options=[str(value) for value in edited["Archivo"]],
                key="catalog_batch_exception_files",
            )
            exception_unit = st.selectbox(
                "Unidad del catálogo para estas excepciones",
                options=[""] + unit_options,
                format_func=lambda value: "Elegir..." if not value else value,
                key="catalog_batch_exception_unit",
            )
            exception_relation = st.selectbox(
                "Cómo se vinculan estos archivos con la unidad elegida",
                options=relation_labels,
                key="catalog_batch_exception_relation",
            )
            if st.button(
                "Aplicar cambios a estas filas",
                key="catalog_batch_apply_exceptions",
            ):
                if not exception_files:
                    st.warning("Elegí al menos un archivo para aplicar una excepción.")
                elif not exception_unit:
                    st.warning("Elegí la unidad del catálogo para las excepciones.")
                else:
                    updated = edited.copy()
                    mask = updated["Archivo"].isin(exception_files)
                    updated.loc[mask, "Unidad del catálogo"] = exception_unit
                    updated.loc[mask, "Relación"] = exception_relation
                    new_rows = []
                    for record in updated.to_dict(orient="records"):
                        record["__source"] = source_lookup[str(record["Archivo"])]
                        record["__sha256"] = sha_lookup[str(record["Archivo"])]
                        new_rows.append(record)
                    st.session_state["catalog_batch_rows"] = new_rows
                    st.session_state["catalog_batch_editor_version"] = editor_version + 1
                    st.session_state["catalog_batch_exception_files__clear"] = True
                    rerun_view(st)

    selected_mask = edited["Importar"] == True
    selected_count = int(selected_mask.sum())
    missing_units = int(
        (selected_mask & (edited["Unidad del catálogo"].fillna("") == "")).sum()
    )
    errors = int(
        (selected_mask & (edited["Problema detectado"].fillna("") != "")).sum()
    )
    invalid_ranges = int(
        (selected_mask & (edited["Página final"] < edited["Página inicial"])).sum()
    )
    summary_cols = st.columns(4)
    summary_cols[0].metric("Archivos seleccionados para incorporar", selected_count)
    summary_cols[1].metric("Archivos sin unidad del catálogo asignada", missing_units)
    summary_cols[2].metric("Archivos con problemas de lectura", errors)
    summary_cols[3].metric("Archivos con rangos de páginas inválidos", invalid_ranges)
    relation_counts = Counter(str(value) for value in edited.loc[selected_mask, "Relación"])
    if selected_count:
        relation_summary = " · ".join(
            f"{label}: {relation_counts.get(label, 0)}" for label in relation_labels
        )
        st.caption(f"Formas de vinculación elegidas para los archivos: {relation_summary}")
    st.caption(
        "Las asociaciones sugeridas por nombre son sólo un punto de partida. Archive Workbench nunca "
        "crea ni modifica la estructura archivística a partir de nombres de archivos o carpetas sin "
        "que la revises y confirmes."
    )

    if st.button(
        "Incorporar archivos seleccionados",
        type="primary",
        key="catalog_batch_commit",
    ):
        if not actor.strip():
            st.error("Definí tu nombre en Preferencias antes de registrar archivos.")
            return
        if selected_count == 0:
            st.error("Seleccioná al menos un archivo para incorporar.")
            return
        if missing_units:
            st.error("Asigná una unidad del catálogo a todos los archivos seleccionados.")
            return
        if errors:
            st.error("Desmarcá o corregí los archivos que muestran un problema antes de continuar.")
            return
        if invalid_ranges:
            st.error("Corregí los rangos donde la página final es anterior a la inicial.")
            return

        results = []
        failures = []
        for _, row in edited[selected_mask].iterrows():
            source_path = Path(source_lookup[str(row["Archivo"])])
            unit_path = str(row["Unidad del catálogo"])
            unit = unit_by_path[unit_path]
            relation_type = relation_by_label[str(row["Relación"])]
            page_start = int(row["Página inicial"])
            page_end = int(row["Página final"])
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    if mode == "project":
                        relative_path = source_path.relative_to(project_root).as_posix()
                        result = register_local_file(
                            session,
                            project_root=project_root,
                            project_id=decisions.project_id,
                            archival_unit_id=unit.id,
                            relative_path=relative_path,
                            relation_type=relation_type,
                            page_start=page_start,
                            page_end=page_end,
                            registered_by=actor,
                        )
                        results.append((source_path.name, result.source_key))
                    else:
                        relative_parent = Path(str(row["Archivo"])).parent
                        file_destination_dir = Path(destination_dir)
                        if str(relative_parent) != ".":
                            file_destination_dir = file_destination_dir / relative_parent
                        result = register_external_file(
                            session,
                            project_root=project_root,
                            project_id=decisions.project_id,
                            archival_unit_id=unit.id,
                            source_path=source_path,
                            destination_dir=file_destination_dir.as_posix(),
                            relation_type=relation_type,
                            page_start=page_start,
                            page_end=page_end,
                            registered_by=actor,
                        )
                        results.append((source_path.name, result.registration.source_key))
            except (OSError, ValueError, RuntimeError, FileNotFoundError) as exc:
                failures.append((source_path.name, str(exc)))
            finally:
                engine.dispose()

        if results:
            st.success(f"Se incorporaron {len(results)} archivos correctamente.")
        if failures:
            st.error(
                f"{len(failures)} archivos no pudieron incorporarse. Los que terminaron correctamente "
                "se conservaron y no hace falta repetirlos."
            )
            st.dataframe(
                [{"Archivo": name, "Problema": message} for name, message in failures],
                hide_index=True,
                use_container_width=True,
            )
        if not failures:
            st.session_state.pop("catalog_batch_rows", None)
            st.session_state.pop("catalog_batch_scan_signature", None)
            st.session_state["catalog_flash"] = (
                f"Lote completado: {len(results)} archivos incorporados."
            )
            rerun_view(st)


def render_catalog_view(st, *, project_root: Path, db_path: Path, decisions, actor: str) -> None:
    section_heading(st, "Catálogo")
    flash = st.session_state.pop("catalog_flash", None)
    if flash:
        st.success(flash)

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            ensure_project(session, decisions)
            summary = catalog_summary(session, decisions.project_id)
            all_rows = catalog_unit_rows(session, decisions.project_id)
    finally:
        engine.dispose()

    level_defs = sorted(
        [item for item in decisions.archival_levels if item.enabled],
        key=lambda item: item.display_order,
    )
    level_labels = {item.key: item.label for item in level_defs}
    level_map = {item.key: item for item in level_defs}
    root_levels = [item.key for item in level_defs if not item.parent_keys]

    catalog_tasks = {
        "summary": "Estado del catálogo",
        "units": "Unidades del catálogo",
        "template": "Planilla del catálogo",
        "create": "Crear una unidad",
        "batch": "Incorporar archivos",
    }
    catalog_task = st.selectbox(
        "Tarea del catálogo",
        options=list(catalog_tasks),
        format_func=lambda value: catalog_tasks[value],
        key="catalog_main_task",
        label_visibility="collapsed",
    )
    catalog_task_label = catalog_tasks[catalog_task]
    mount_choice_help(
        st,
        key="catalog_main_task",
        label=catalog_task_label,
        help_text=TASK_HELP["catalog_main_task"][catalog_task_label],
    )

    if catalog_task == "summary":
        metrics = st.columns(6)
        metrics[0].metric("Unidades del catálogo", summary.units)
        metrics[1].metric("Unidades con descripción incompleta", summary.incomplete_units)
        metrics[2].metric("Documentos digitales registrados", summary.digital_objects)
        metrics[3].metric("Copias de archivo registradas", summary.file_instances)
        metrics[4].metric("Copias de archivo disponibles", summary.present_files)
        metrics[5].metric("Copias de archivo ausentes", summary.missing_files)

    if catalog_task == "template":
        include_catalog = st.checkbox(
            "Incluir las unidades actuales del catálogo en la planilla descargada",
            value=bool(all_rows),
            key="catalog_template_include_current",
        )
        export_engine = create_sqlite_engine(db_path)
        try:
            with session_scope(export_engine) as session:
                template_bytes = export_catalog_template_bytes(
                    session,
                    decisions=decisions,
                    project_id=decisions.project_id,
                    include_catalog=include_catalog,
                    template_name=(
                        "Catálogo actual de Archive Workbench"
                        if include_catalog
                        else "Plantilla vacía de catálogo"
                    ),
                )
        finally:
            export_engine.dispose()
        st.download_button(
            "Descargar planilla XLSX del catálogo",
            data=template_bytes,
            file_name=(
                "catalogo_exportado.xlsx" if include_catalog else "plantilla_catalogo_vacia.xlsx"
            ),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="catalog_template_download",
        )

        uploaded_template = st.file_uploader(
            "Seleccionar una planilla XLSX con unidades del catálogo para revisar antes de guardar cambios",
            type=["xlsx"],
            key="catalog_template_upload",
        )
        if uploaded_template is not None:
            template_content = uploaded_template.getvalue()
            validation_engine = create_sqlite_engine(db_path)
            try:
                with session_scope(validation_engine) as session:
                    report = validate_catalog_template(
                        session,
                        decisions=decisions,
                        project_id=decisions.project_id,
                        source=template_content,
                    )
            finally:
                validation_engine.dispose()

            report_metrics = st.columns(5)
            report_metrics[0].metric("Filas de unidades en la planilla", len(report.rows))
            report_metrics[1].metric("Unidades del catálogo a crear", report.create_count)
            report_metrics[2].metric("Unidades del catálogo a actualizar", report.update_count)
            report_metrics[3].metric("Errores de la planilla", report.error_count)
            report_metrics[4].metric("Advertencias de la planilla", report.warning_count)
            if report.issues:
                st.dataframe(
                    [
                        {
                            "Importancia": "Error" if item.severity == "error" else "Advertencia",
                            "Hoja": item.sheet,
                            "Fila": item.row,
                            "Columna": item.column,
                            "Qué hay que revisar": item.message,
                        }
                        for item in report.issues
                    ],
                    width="stretch",
                    hide_index=True,
                )
            preview_rows = [
                {
                    "Acción": row.action or ("actualizar" if row.unit_id else "crear"),
                    "Identificador dentro de la planilla": row.local_id,
                    "Unidad que la contiene": row.parent_local_id or row.parent_unit_id or "Raíz",
                    "Nivel": level_labels.get(row.level_key, row.level_key),
                    "Título de la unidad del catálogo": row.title,
                }
                for row in report.rows[:100]
            ]
            if preview_rows:
                st.write("**Unidades del catálogo que resultarían de esta planilla**")
                st.dataframe(preview_rows, width="stretch", hide_index=True)
            if report.valid:
                st.success(
                    "La planilla está lista para importar. Si confirmás, Archive Workbench aplicará "
                    "todos los cambios juntos. Si ocurre un error durante la importación, no se guardará "
                    "ningún cambio. El historial conservará qué unidades fueron creadas o modificadas."
                )
                with st.form("catalog_template_apply_form", enter_to_submit=False):
                    confirmation = st.text_input(
                        "Escribí IMPORTAR para confirmar",
                        key="catalog_template_apply_confirmation",
                    )
                    submitted = st.form_submit_button(
                        "Guardar en el catálogo los cambios de esta planilla",
                        type="primary",
                    )
                if submitted and confirmation.strip() != "IMPORTAR":
                    st.error("Para guardar en el catálogo los cambios de la planilla, escribí exactamente IMPORTAR.")
                elif submitted:
                    def import_callback(session):
                        result = apply_catalog_template(
                            session,
                            decisions=decisions,
                            project_id=decisions.project_id,
                            source=template_content,
                            changed_by=actor or "local_user",
                            note=f"Importación de {uploaded_template.name}",
                        )
                        return (
                            "Cambios de la planilla guardados en el catálogo: "
                            f"{result.created} creadas, {result.updated} actualizadas, "
                            f"{result.moved} movidas, {result.unchanged} sin cambios y "
                            f"{result.skipped} omitidas."
                        )

                    _run_catalog_action(st, db_path=db_path, callback=import_callback)
            else:
                st.warning(
                    "La planilla todavía no puede importarse. Revisá los errores de la tabla anterior. "
                    "Si alguno indica que una unidad no puede estar dentro de otra, podés ajustar esa "
                    "regla desde Configurar estructura del catálogo sin editar archivos de configuración."
                )
                structure_review_open = st.toggle(
                    "Revisar la estructura permitida del catálogo",
                    value=True,
                    key="catalog_structure_review_open",
                )
                if structure_review_open:
                    with st.container(border=True):
                        _render_catalog_structure_editor(
                            st, decisions=decisions, project_root=project_root
                        )

    if catalog_task == "create":
        if "coleccion" not in level_map:
            st.info(
                "Este proyecto fue creado antes de que Colección estuviera disponible. Una Colección es "
                "un conjunto documental construido, distinto de un Fondo. En el árbol puede vincularse a "
                "Archivo como contexto de custodia y puede reunir Documentos."
            )
            if st.button("Habilitar Colección en este proyecto", key="catalog_enable_collection"):
                try:
                    changed = add_standard_collection_level(project_root / "config" / "decisions.yaml")
                except (OSError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    st.session_state["catalog_flash"] = (
                        "Colección quedó disponible como nivel del catálogo."
                        if changed
                        else "Colección ya estaba disponible en este proyecto."
                    )
                    rerun_app(st)
        if not root_levels:
            st.info("La configuración no habilita niveles en la raíz del catálogo.")
        else:
            with st.form("catalog_create_root_unit", enter_to_submit=False):
                level_key = st.selectbox(
                    "Tipo de unidad que querés crear en la raíz del catálogo",
                    options=root_levels,
                    format_func=lambda key: level_labels[key],
                )
                title = st.text_input("Título de la unidad del catálogo")
                reference_code = st.text_input("Código de referencia de la unidad (opcional)")
                note = st.text_input("Nota sobre la creación de esta unidad (opcional)", placeholder="Opcional")
                submit_create = st.form_submit_button("Crear esta unidad en la raíz del catálogo", type="primary")
            if submit_create:
                def callback(session):
                    unit = create_archival_unit(
                        session,
                        decisions=decisions,
                        project_id=decisions.project_id,
                        parent_id=None,
                        level_key=level_key,
                        title=title,
                        reference_code=reference_code,
                        created_by=actor or "local_user",
                        note=note,
                    )
                    return f"Unidad creada: {unit.title}", unit.id

                _run_catalog_action(st, db_path=db_path, callback=callback)

    if catalog_task == "batch":
        _render_batch_import(
            st,
            project_root=project_root,
            db_path=db_path,
            decisions=decisions,
            actor=actor,
            all_rows=all_rows,
        )

    if catalog_task == "units":
        search_cols = st.columns([2.4, 1, 1])
        with search_cols[0]:
            query = st.text_input(
                "Buscar una unidad del catálogo por título o código",
                placeholder="Buscar por título, código, descripción o archivo",
                key="catalog_query",
                label_visibility="collapsed",
            )
        with search_cols[1]:
            level_filter = st.selectbox(
                "Tipo de unidad del catálogo",
                options=[""] + [item.key for item in level_defs],
                format_func=lambda value: "Todos los tipos" if not value else level_labels[value],
                key="catalog_level_filter",
                label_visibility="collapsed",
            )
        with search_cols[2]:
            status_filter = st.selectbox(
                "Estado de la descripción de la unidad",
                options=[""] + list(REGISTRATION_STATUSES),
                format_func=lambda value: "Todos los estados" if not value else _STATUS_LABELS[value],
                key="catalog_status_filter",
                label_visibility="collapsed",
            )

        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                visible_rows = search_catalog_units(
                    session,
                    project_id=decisions.project_id,
                    query=query,
                    level_key=level_filter or None,
                    registration_status=status_filter or None,
                )
        finally:
            engine.dispose()

        if not visible_rows:
            st.info("No hay unidades que coincidan con los filtros.")
            return

        by_id = {row.id: row for row in all_rows}
        visible_by_id = {row.id: row for row in visible_rows}
        pending = st.session_state.pop("catalog_pending_unit_id", None)
        if pending in visible_by_id:
            st.session_state["catalog_selected_unit"] = pending
        selected_id = st.session_state.get("catalog_selected_unit")
        if selected_id not in visible_by_id:
            selected_id = visible_rows[0].id
            st.session_state["catalog_selected_unit"] = selected_id

        tree_col, detail_col = st.columns([0.95, 2.05], gap="large")
        with tree_col:
            st.write("**Catálogo y contexto de custodia**")
            st.caption(
                "Abrí las ramas y seleccioná la unidad directamente en el árbol. El nivel superior puede "
                "representar custodia, jerarquía documental o ubicación física según su tipo."
            )
            matching_ids = set(visible_by_id)
            filters_active = bool(query.strip() or level_filter or status_filter)
            include_ids = (
                _catalog_tree_include_ids(all_rows, matching_ids)
                if filters_active
                else {row.id for row in all_rows}
            )
            tree_selected = catalog_tree_select(
                st,
                rows=all_rows,
                level_labels=level_labels,
                selected_id=selected_id,
                key="catalog_unit_tree",
                selection_state_key="catalog_selected_unit",
                selectable_ids=matching_ids if filters_active else None,
                include_ids=include_ids,
                force_open_ids=matching_ids if filters_active else {selected_id},
            )
            if tree_selected is not None and tree_selected != selected_id:
                selected_id = tree_selected
                st.session_state["catalog_selected_unit"] = selected_id
            selected_row = by_id[selected_id]
            selected_level = level_map[selected_row.level_key]
            st.caption(f"Seleccionada: {selected_row.path}")
            st.caption(_level_semantic_label(selected_level))
            if selected_row.reference_code:
                st.caption(f"Código: {selected_row.reference_code}")
            child_levels = [
                item.key for item in level_defs if selected_row.level_key in item.parent_keys
            ]
            if child_levels:
                add_child_open = st.toggle(
                    f"Agregar una unidad bajo {selected_row.title}",
                    value=False,
                    key=f"catalog_add_child_open_{selected_row.id}",
                )
                if add_child_open:
                    with st.container(border=True):
                        st.caption(
                            _catalog_parent_relation_caption(
                                parent_level=selected_level,
                                parent_path=selected_row.path,
                            )
                        )
                        with st.form(f"catalog_create_child_{selected_row.id}", clear_on_submit=True, enter_to_submit=False):
                            child_level = st.selectbox(
                                "Tipo de unidad que querés agregar",
                                options=child_levels,
                                format_func=lambda key: level_labels[key],
                            )
                            child_title = st.text_input("Título de la nueva unidad del catálogo")
                            child_reference = st.text_input("Código de referencia de la unidad (opcional)")
                            child_note = st.text_input("Nota sobre la creación de esta unidad (opcional)", placeholder="Opcional")
                            child_submit = st.form_submit_button("Crear esta unidad en el catálogo", type="primary")
                        if child_submit:
                            def create_child_callback(session):
                                child = create_archival_unit(
                                    session,
                                    decisions=decisions,
                                    project_id=decisions.project_id,
                                    parent_id=selected_row.id,
                                    level_key=child_level,
                                    title=child_title,
                                    reference_code=child_reference,
                                    created_by=actor or "local_user",
                                    note=child_note,
                                )
                                return f"Unidad creada: {child.title}", child.id

                            _run_catalog_action(st, db_path=db_path, callback=create_child_callback)
            else:
                st.caption("Este nivel no admite unidades hijas según la configuración del proyecto.")

        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                unit = session.get(ArchivalUnit, selected_id)
                assert unit is not None
                fields = archival_field_rows(session, selected_id)
                digital_objects = unit_digital_objects(session, selected_id)
                revisions = archival_revision_rows(session, selected_id)
                object_choices = digital_object_choices(session, decisions.project_id)
                archival_roles = entity_relation_rows(
                    session,
                    project_id=decisions.project_id,
                    archival_unit_id=selected_id,
                    relation_kinds=ARCHIVAL_ROLE_KINDS,
                    include_inactive=True,
                )
                role_histories = {
                    row.relation_id: entity_relation_revision_rows(session, row.relation_id)
                    for row in archival_roles
                }
                role_authorities = authority_rows(
                    session,
                    project_id=decisions.project_id,
                    lifecycle_statuses=("active", "inactive"),
                )
        finally:
            engine.dispose()

        existing_by_key: dict[str, list] = defaultdict(list)
        for row in fields:
            existing_by_key[row.field_key].append(row)

        with detail_col:
            st.markdown(f"### {unit.title}")
            st.caption(
                f"{level_labels.get(unit.level_key, unit.level_key)} · "
                f"{by_id[unit.id].path} · {selected_row.child_count} unidades hijas · "
                f"{selected_row.digital_object_count} contenidos digitales"
            )
            # Estas pestañas se resuelven en el navegador sin forzar una nueva ejecución.
            # Cambiar entre ellas no debe desplazar la vista al inicio de Catálogo.
            detail_tab_labels = [
                "Descripción de la unidad",
                "Productores y responsables",
                "Archivos vinculados",
                "Ubicación y tipo",
                "Historial de la unidad",
            ]
            pending_detail_tab = st.session_state.pop("catalog_pending_detail_tab", None)
            if pending_detail_tab in detail_tab_labels:
                st.session_state["catalog_detail_tabs"] = pending_detail_tab
            description_tab, roles_tab, files_tab, structure_tab, history_tab = tracked_tabs(
                st,
                detail_tab_labels,
                key="catalog_detail_tabs",
                default=(
                    pending_detail_tab
                    if pending_detail_tab in detail_tab_labels
                    else "Descripción de la unidad"
                ),
                help_by_label=TAB_HELP["catalog_detail_tabs"],
                rerun_on_change=False,
            )

            with description_tab:
                st.caption(
                    "Revisá o corregí los datos necesarios para describir esta unidad. Los datos complementarios "
                    "son opcionales y se agregan solamente cuando aportan información útil."
                )
                applicable_fields = [
                    item
                    for item in decisions.descriptive_fields
                    if item.enabled
                    and item.key != "reference_code"
                    and ("all" in item.applies_to_levels or unit.level_key in item.applies_to_levels)
                ]
                required_fields = [item for item in applicable_fields if item.required]
                optional_fields = [item for item in applicable_fields if not item.required]
                definition_by_key = {item.key: item for item in applicable_fields}

                title = st.text_input(
                    "Título de la unidad del catálogo", value=unit.title, key=f"catalog_title_{unit.id}"
                )
                reference_code = st.text_input(
                    "Código de referencia de la unidad (opcional)",
                    value=unit.reference_code or "",
                    key=f"catalog_reference_{unit.id}",
                )
                registration_status = st.selectbox(
                    "Vigencia de esta unidad en el catálogo",
                    options=list(REGISTRATION_STATUSES),
                    index=list(REGISTRATION_STATUSES).index(unit.registration_status),
                    format_func=lambda value: _STATUS_LABELS[value],
                    key=f"catalog_registration_status_{unit.id}",
                    help=(
                        "Incompleto: faltan datos importantes. Provisional: la descripción puede usarse, "
                        "pero todavía requiere revisión. Completo: la descripción fue revisada y puede "
                        "confirmarse manualmente."
                    ),
                )
                completion_confirmed = st.checkbox(
                    "Descripción completada y confirmada manualmente",
                    value=bool(unit.completion_confirmed and registration_status == "complete"),
                    disabled=registration_status != "complete",
                    key=f"catalog_completion_confirmed_{unit.id}",
                )
                if registration_status != "complete":
                    st.caption(
                        "Esta confirmación sólo se habilita cuando el Estado del registro es Completo."
                    )

                required_widgets: dict[str, tuple[str, str]] = {}
                if required_fields:
                    st.divider()
                    st.markdown("#### Datos descriptivos requeridos")
                    for definition in required_fields:
                        rows = existing_by_key.get(definition.key, [])
                        current_state = rows[0].value_state if rows else "pending"
                        values = "\n".join(str(row.value) for row in rows if row.value is not None)
                        st.markdown(f"**{definition.label}**")
                        state_col, value_col = st.columns([1, 2.5])
                        with state_col:
                            state = st.selectbox(
                                "Estado de revisión de este campo descriptivo",
                                options=list(decisions.catalog.field_value_states),
                                index=list(decisions.catalog.field_value_states).index(current_state),
                                format_func=lambda value: _FIELD_STATE_LABELS.get(value, value),
                                key=f"catalog_required_state_{unit.id}_{definition.key}",
                            )
                        with value_col:
                            value = st.text_area(
                                "Valor" + (" · uno por línea" if definition.repeatable else ""),
                                value=values,
                                height=72 if definition.repeatable else 68,
                                key=f"catalog_required_value_{unit.id}_{definition.key}",
                            )
                        required_widgets[definition.key] = (state, value)

                st.divider()
                st.markdown("#### Datos descriptivos registrados")
                registered_any = False
                for definition in applicable_fields:
                    rows = existing_by_key.get(definition.key, [])
                    if not rows:
                        continue
                    current_state = rows[0].value_state
                    values = [str(row.value) for row in rows if row.value is not None]
                    if current_state == "pending" and not values:
                        continue
                    registered_any = True
                    with st.container(border=True):
                        st.markdown(f"**{definition.label}**")
                        if values:
                            st.caption(" · ".join(values))
                        else:
                            st.caption(_FIELD_STATE_LABELS.get(current_state, current_state))
                if not registered_any:
                    st.caption("Todavía no hay datos descriptivos complementarios registrados.")

                st.caption(
                    "No es necesario completar todos los datos descriptivos opcionales. Elegí uno solamente "
                    "cuando corresponda revisarlo o agregarlo a esta unidad."
                )
                optional_field_key = st.selectbox(
                    "Dato descriptivo opcional que querés revisar o agregar",
                    options=[""] + [item.key for item in optional_fields],
                    format_func=lambda value: (
                        "Elegir un dato…" if not value else definition_by_key[value].label
                    ),
                    key=f"catalog_optional_field_{unit.id}_{unit.revision}",
                )
                optional_state = None
                optional_value = None
                if optional_field_key:
                    definition = definition_by_key[optional_field_key]
                    rows = existing_by_key.get(optional_field_key, [])
                    current_state = rows[0].value_state if rows else "pending"
                    values = "\n".join(str(row.value) for row in rows if row.value is not None)
                    state_col, value_col = st.columns([1, 2.5])
                    with state_col:
                        optional_state = st.selectbox(
                            "Estado de revisión de este campo descriptivo",
                            options=list(decisions.catalog.field_value_states),
                            index=list(decisions.catalog.field_value_states).index(current_state),
                            format_func=lambda value: _FIELD_STATE_LABELS.get(value, value),
                            key=f"catalog_optional_state_{unit.id}_{optional_field_key}",
                        )
                    with value_col:
                        optional_value = st.text_area(
                            definition.label + (" · uno por línea" if definition.repeatable else ""),
                            value=values,
                            height=80,
                            key=f"catalog_optional_value_{unit.id}_{optional_field_key}",
                        )

                note = st.text_input(
                    "Nota sobre estos cambios en la descripción (opcional)",
                    placeholder="Opcional",
                    key=f"catalog_description_note_{unit.id}",
                )
                save_description = st.button(
                    "Guardar los cambios en la descripción de esta unidad",
                    type="primary",
                    key=f"catalog_description_save_{unit.id}",
                )
                if save_description:
                    payload: dict[str, dict] = {}
                    for definition in applicable_fields:
                        existing_payload = _existing_field_payload(existing_by_key, definition)
                        if existing_payload is not None:
                            payload[definition.key] = existing_payload
                    for definition in required_fields:
                        state, value = required_widgets[definition.key]
                        payload[definition.key] = _field_payload(
                            existing_by_key, definition, value, state
                        )
                    if optional_field_key and optional_state is not None and optional_value is not None:
                        definition = definition_by_key[optional_field_key]
                        payload[optional_field_key] = _field_payload(
                            existing_by_key, definition, optional_value, optional_state
                        )
                    _run_catalog_action(
                        st,
                        db_path=db_path,
                        unit_id=unit.id,
                        callback=lambda session: (
                            update_archival_unit(
                                session,
                                decisions=decisions,
                                unit_id=unit.id,
                                changed_by=actor or "local_user",
                                title=title,
                                reference_code=reference_code,
                                registration_status=registration_status,
                                completion_confirmed=(
                                    completion_confirmed if registration_status == "complete" else False
                                ),
                                field_values=payload,
                                note=note,
                            ),
                            "Descripción actualizada",
                        )[1],
                    )

            with roles_tab:
                authority_map = {row.authority_id: row for row in role_authorities}
                authority_options = [row.authority_id for row in role_authorities]

                st.markdown("#### Productores y responsables registrados")
                st.caption(
                    "Estos vínculos describen quién produjo, gestionó o tuvo responsabilidad sobre la unidad "
                    "y tienen prioridad visual sobre las acciones para crear información nueva."
                )
                if not archival_roles:
                    st.info("Esta unidad todavía no tiene productores ni responsables de gestión registrados.")
                for role in archival_roles:
                    temporal_label = format_temporal_range(
                        role.temporal_expression,
                        role.temporal_start,
                        role.temporal_end,
                        role.temporal_approximate,
                    )
                    with st.container(border=True):
                        st.markdown(
                            f"**{RELATION_KIND_LABELS.get(role.relation_kind, role.relation_kind)}** · "
                            f"**{role.source_name}**"
                        )
                        st.caption(f"Período: {temporal_label or 'Sin registrar'}")
                        st.caption(
                            f"Estado: {_ROLE_STATUS_LABELS.get(role.lifecycle_status, role.lifecycle_status)} · "
                            f"Revisión: {_ROLE_REVIEW_LABELS.get(role.review_status, role.review_status)}"
                        )
                        st.caption(f"Evidencia: {role.evidence_note or 'Sin registrar'}")
                        st.caption(f"Fuente: {role.provenance_note or 'Sin registrar'}")

                        edit_key = f"catalog_role_edit_open_{role.relation_id}"
                        delete_key = f"catalog_role_delete_open_{role.relation_id}"
                        edit_open = bool(st.session_state.get(edit_key, False))
                        delete_open = bool(st.session_state.get(delete_key, False))
                        role_action_cols = st.columns(2)
                        with role_action_cols[0]:
                            if not edit_open and st.button(
                                "Modificar este vínculo",
                                key=f"catalog_role_edit_button_{role.relation_id}_{role.revision}",
                                use_container_width=True,
                            ):
                                st.session_state[edit_key] = True
                                st.session_state[delete_key] = False
                                edit_open = True
                                delete_open = False
                            elif edit_open and st.button(
                                "Cerrar edición",
                                key=f"catalog_role_edit_close_{role.relation_id}_{role.revision}",
                                use_container_width=True,
                            ):
                                st.session_state[edit_key] = False
                                edit_open = False
                        with role_action_cols[1]:
                            if not delete_open and st.button(
                                "Eliminar vínculo",
                                key=f"catalog_role_delete_button_{role.relation_id}_{role.revision}",
                                use_container_width=True,
                            ):
                                st.session_state[delete_key] = True
                                st.session_state[edit_key] = False
                                delete_open = True
                                edit_open = False
                            elif delete_open and st.button(
                                "Cancelar eliminación",
                                key=f"catalog_role_delete_cancel_{role.relation_id}_{role.revision}",
                                use_container_width=True,
                            ):
                                st.session_state[delete_key] = False
                                delete_open = False

                        if delete_open:
                            st.warning(
                                "Eliminar sirve para corregir un vínculo registrado por error. "
                                "No equivale a marcarlo Inactivo: la entidad vinculada no se borra y el historial técnico del vínculo se conserva."
                            )
                            with st.form(
                                f"catalog_role_delete_{role.relation_id}",
                                enter_to_submit=False,
                            ):
                                delete_confirm = st.checkbox(
                                    "Confirmo que este vínculo fue registrado por error y debe retirarse del catálogo"
                                )
                                delete_note = st.text_input(
                                    "Motivo de la eliminación (opcional)",
                                    placeholder="Opcional",
                                )
                                delete_submit = st.form_submit_button("Eliminar este vínculo")
                            if delete_submit:
                                if not delete_confirm:
                                    st.error("Confirmá explícitamente la eliminación antes de continuar.")
                                else:
                                    def delete_role_callback(session, current=role):
                                        delete_entity_relation(
                                            session,
                                            relation_id=current.relation_id,
                                            expected_revision=current.revision,
                                            changed_by=actor or "local_user",
                                            note=delete_note,
                                        )
                                        return "Vínculo eliminado; la entidad relacionada y el historial se conservaron"

                                    _run_catalog_action(
                                        st,
                                        db_path=db_path,
                                        unit_id=unit.id,
                                        callback=delete_role_callback,
                                    )

                        if edit_open:
                            edit_authority_options = list(authority_options)
                            if role.source_authority_id not in edit_authority_options:
                                edit_authority_options.insert(0, role.source_authority_id)
                            with st.form(f"catalog_role_edit_{role.relation_id}", enter_to_submit=False):
                                edit_cols = st.columns(2)
                                with edit_cols[0]:
                                    edit_role_kind = st.selectbox(
                                        "Función de esta persona u organización respecto de la unidad",
                                        options=list(ARCHIVAL_ROLE_KINDS),
                                        index=list(ARCHIVAL_ROLE_KINDS).index(role.relation_kind),
                                        format_func=lambda value: RELATION_KIND_LABELS[value],
                                        key=f"catalog_role_edit_kind_{role.relation_id}",
                                    )
                                    edit_role_authority = st.selectbox(
                                        "Persona u organización que querés vincular",
                                        options=edit_authority_options,
                                        index=edit_authority_options.index(role.source_authority_id),
                                        format_func=lambda value: (
                                            authority_map[value].preferred_name
                                            if value in authority_map
                                            else role.source_name
                                        ),
                                        key=f"catalog_role_edit_authority_{role.relation_id}",
                                    )
                                    edit_role_period = st.text_input(
                                        "Período en que tuvo esta función (opcional)",
                                        value=role.temporal_expression or "",
                                        placeholder="Ej.: 1946 - 2015; desde 2024",
                                        key=f"catalog_role_edit_period_{role.relation_id}",
                                    )
                                    edit_role_review = st.selectbox(
                                        "Estado de revisión de este vínculo",
                                        options=list(RELATION_REVIEW_STATUSES),
                                        index=list(RELATION_REVIEW_STATUSES).index(role.review_status),
                                        format_func=lambda value: _ROLE_REVIEW_LABELS[value],
                                        key=f"catalog_role_edit_review_{role.relation_id}",
                                    )
                                    edit_role_lifecycle = st.selectbox(
                                        "Vigencia de este vínculo en el catálogo",
                                        options=list(RELATION_EDITABLE_LIFECYCLE_STATUSES),
                                        index=list(RELATION_EDITABLE_LIFECYCLE_STATUSES).index(role.lifecycle_status),
                                        format_func=lambda value: _ROLE_STATUS_LABELS[value],
                                        key=f"catalog_role_edit_lifecycle_{role.relation_id}",
                                    )
                                with edit_cols[1]:
                                    edit_role_evidence = st.text_area(
                                        "Evidencia documental de este vínculo (opcional)",
                                        value=role.evidence_note or "",
                                        key=f"catalog_role_edit_evidence_{role.relation_id}",
                                    )
                                    edit_role_provenance = st.text_area(
                                        "Fuente de la información sobre este vínculo (opcional)",
                                        value=role.provenance_note or "",
                                        key=f"catalog_role_edit_provenance_{role.relation_id}",
                                    )
                                edit_role_note = st.text_input(
                                    "Nota sobre estos cambios en el vínculo (opcional)",
                                    placeholder="Opcional",
                                    key=f"catalog_role_edit_note_{role.relation_id}",
                                )
                                edit_role_submit = st.form_submit_button(
                                    "Guardar los cambios en este vínculo"
                                )
                            if edit_role_submit:
                                def update_role_callback(session, current=role):
                                    update_entity_relation(
                                        session,
                                        relation_id=current.relation_id,
                                        expected_revision=current.revision,
                                        changed_by=actor or "local_user",
                                        source_authority_id=edit_role_authority,
                                        relation_kind=edit_role_kind,
                                        evidence_note=edit_role_evidence,
                                        provenance_note=edit_role_provenance,
                                        temporal_expression=edit_role_period,
                                        review_status=edit_role_review,
                                        lifecycle_status=edit_role_lifecycle,
                                        note=edit_role_note,
                                    )
                                    return "Vínculo actualizado; el estado anterior quedó conservado en el historial"

                                _run_catalog_action(
                                    st,
                                    db_path=db_path,
                                    unit_id=unit.id,
                                    callback=update_role_callback,
                                )

                        history_rows = role_histories.get(role.relation_id, [])
                        with st.expander("Historial del vínculo", expanded=False):
                            for revision in history_rows:
                                st.markdown(
                                    f"**Revisión {revision.revision_number} · {revision.operation}** · "
                                    f"{revision.changed_by} · {revision.changed_at.isoformat()}"
                                )
                                if revision.note:
                                    st.caption(revision.note)
                                st.json(revision.snapshot, expanded=False)

                st.divider()
                st.markdown("#### Agregar información sobre producción o gestión")
                st.caption(
                    "Elegí una acción solamente cuando necesites crear o agregar información. Los formularios "
                    "no se muestran mientras no selecciones una acción."
                )
                role_action = st.selectbox(
                    "Acción",
                    options=["", "add_role", "create_authority"],
                    format_func=lambda value: {
                        "": "Elegir una acción…",
                        "add_role": "Agregar productor o responsable de gestión",
                        "create_authority": "Crear una persona u organización para poder vincularla",
                    }[value],
                    key=f"catalog_role_action_{unit.id}_{unit.revision}",
                )

                if role_action == "create_authority":
                    with st.form(
                        f"catalog_inline_authority_{unit.id}",
                        clear_on_submit=True,
                        enter_to_submit=False,
                    ):
                        new_authority_type = st.selectbox(
                            "Tipo de persona u organización",
                            options=["person", "organization"],
                            format_func=lambda value: "Persona" if value == "person" else "Organización",
                            key=f"catalog_inline_authority_type_{unit.id}",
                        )
                        new_authority_name = st.text_input(
                            "Forma autorizada del nombre", key=f"catalog_inline_authority_name_{unit.id}"
                        )
                        new_authority_description = st.text_area(
                            "Historia / nota biográfica (opcional)",
                            placeholder="Agregá sólo la información necesaria para identificarla.",
                            key=f"catalog_inline_authority_description_{unit.id}",
                        )
                        create_authority_submit = st.form_submit_button(
                            "Crear esta persona u organización", type="primary"
                        )
                    if create_authority_submit:
                        def inline_authority_callback(session):
                            authority = create_authority(
                                session,
                                project_id=decisions.project_id,
                                entity_type=new_authority_type,
                                preferred_name=new_authority_name,
                                description=new_authority_description,
                                created_by=actor or "local_user",
                            )
                            return f"Registro creado: {authority.preferred_name}"

                        _run_catalog_action(
                            st,
                            db_path=db_path,
                            unit_id=unit.id,
                            callback=inline_authority_callback,
                        )

                if role_action == "add_role":
                    if not authority_options:
                        st.info(
                            "Primero creá una persona u organización para poder vincularla con esta unidad."
                        )
                    else:
                        with st.form(
                            f"catalog_role_create_{unit.id}",
                            clear_on_submit=True,
                            enter_to_submit=False,
                        ):
                            create_cols = st.columns(2)
                            with create_cols[0]:
                                new_role_kind = st.selectbox(
                                    "Función de esta persona u organización respecto de la unidad",
                                    options=list(ARCHIVAL_ROLE_KINDS),
                                    format_func=lambda value: RELATION_KIND_LABELS[value],
                                    key=f"catalog_role_kind_{unit.id}",
                                )
                                new_role_authority = st.selectbox(
                                    "Persona u organización que querés vincular",
                                    options=authority_options,
                                    format_func=lambda value: authority_map[value].preferred_name,
                                    key=f"catalog_role_authority_{unit.id}",
                                )
                                new_role_period = st.text_input(
                                    "Período en que tuvo esta función (opcional)",
                                    placeholder="Ej.: 1946 - 2015; desde 2024",
                                    key=f"catalog_role_period_{unit.id}",
                                )
                            with create_cols[1]:
                                new_role_evidence = st.text_area(
                                    "Evidencia documental de este vínculo (opcional)",
                                    help="Documento, pasaje o fundamento que sostiene la asignación del rol.",
                                    key=f"catalog_role_evidence_{unit.id}",
                                )
                                new_role_provenance = st.text_area(
                                    "Fuente de la información sobre este vínculo (opcional)",
                                    help="Origen de la información: instrumento descriptivo, expediente, entrevista u otra fuente.",
                                    key=f"catalog_role_provenance_{unit.id}",
                                )
                            new_role_note = st.text_input(
                                "Nota sobre este vínculo (opcional)",
                                placeholder="Opcional",
                                key=f"catalog_role_note_{unit.id}",
                            )
                            create_role_submit = st.form_submit_button(
                                "Vincular esta persona u organización con la unidad", type="primary"
                            )
                        if create_role_submit:
                            def create_role_callback(session):
                                relation = create_entity_relation(
                                    session,
                                    project_id=decisions.project_id,
                                    source_authority_id=new_role_authority,
                                    relation_kind=new_role_kind,
                                    relation_label="",
                                    target_kind="archival_unit",
                                    target_id=unit.id,
                                    evidence_note=new_role_evidence,
                                    provenance_note=new_role_provenance,
                                    temporal_expression=new_role_period,
                                    created_by=actor or "local_user",
                                    note=new_role_note,
                                )
                                return f"{RELATION_KIND_LABELS[relation.relation_kind]} registrada"

                            _run_catalog_action(
                                st,
                                db_path=db_path,
                                unit_id=unit.id,
                                callback=create_role_callback,
                            )

            with files_tab:
                st.caption("Consultá qué archivos digitales están vinculados con esta unidad del catálogo, comprobá que sigan disponibles y agregá o quitá vínculos cuando corresponda.")
                scan_col, info_col = st.columns([1, 3])
                with scan_col:
                    if st.button("Comprobar si los archivos vinculados siguen disponibles e intactos", use_container_width=True):
                        _run_catalog_action(
                            st,
                            db_path=db_path,
                            unit_id=unit.id,
                            callback=lambda session: (
                                lambda result: (
                                    f"Archivos verificados: {result.checked}; disponibles {result.present}; "
                                    f"ausentes {result.missing}; modificados {result.modified}"
                                )
                            )(scan_file_instances(session, project_root)),
                        )
                with info_col:
                    st.caption(
                        "La comprobación revisa si cada archivo vinculado sigue disponible y si su contenido coincide con el registrado. Si un archivo cambió, Archive Workbench lo informa pero no reemplaza automáticamente su registro."
                    )

                if not digital_objects:
                    st.info("Esta unidad todavía no tiene archivos o contenidos digitales asociados.")
                for item in digital_objects:
                    digital_object_panel_key = f"catalog_digital_object_panel_{item.link_id}"
                    st.session_state.setdefault(
                        digital_object_panel_key, len(digital_objects) == 1
                    )
                    digital_object_panel_open = st.toggle(
                        f"{item.original_filename} · {item.media_type} · {item.page_count or '?'} pág.",
                        key=digital_object_panel_key,
                    )
                    if digital_object_panel_open:
                        with st.container(border=True):
                            st.write(
                                f"**Relación con la unidad:** {_RELATION_LABELS.get(item.relation_type, item.relation_type)} · "
                                f"**tamaño:** {item.byte_size:,} bytes"
                            )
                            with st.expander("Detalles técnicos del archivo", expanded=False):
                                st.write(f"Huella SHA-256: `{item.sha256}`")
                                if item.source_key:
                                    st.write(f"Identificador interno de procesamiento: `{item.source_key}`")
                            pcols = st.columns(4)
                            pcols[0].metric(
                                "Preparación de páginas",
                                _PROCESSING_STATUS_LABELS.get(
                                    item.preprocessing_status, item.preprocessing_status
                                ),
                            )
                            pcols[1].metric(
                                "Extracción de texto",
                                _PROCESSING_STATUS_LABELS.get(
                                    item.extraction_status, item.extraction_status
                                ),
                            )
                            pcols[2].metric("Páginas con texto elegido", item.selected_pages)
                            pcols[3].metric(
                                "Páginas revisadas",
                                f"{item.reviewed_pages}/{item.editable_pages}",
                            )
                            if item.page_start or item.page_end:
                                st.caption(f"Páginas vinculadas: {item.page_start or '?'}–{item.page_end or '?'}")
                            if not item.files:
                                st.warning("Este documento digital no tiene un archivo local disponible en el proyecto.")
                            for local in item.files:
                                file_left, file_action = st.columns([5, 2])
                                file_left.write(
                                    f"`{local.relative_path}` · "
                                    f"**{_PRESENCE_LABELS.get(local.presence, local.presence)}**"
                                )
                                with file_action.popover("Retirar este archivo local del proyecto"):
                                    st.caption(
                                        "Retirar este archivo local no elimina el documento digital registrado ni su vínculo con la unidad del catálogo. Si elegís borrar también el archivo físico, otras unidades que reutilicen ese mismo archivo pueden quedar sin copia disponible."
                                    )
                                    delete_physical = st.checkbox(
                                        "Borrar también este archivo original de la computadora",
                                        key=f"catalog_delete_physical_{local.id}",
                                    )
                                    confirmation = st.text_input(
                                        "Escribí ELIMINAR para confirmar" if delete_physical else "Escribí RETIRAR para confirmar",
                                        key=f"catalog_remove_file_confirm_{local.id}",
                                    )
                                    expected = "ELIMINAR" if delete_physical else "RETIRAR"
                                    if st.button(
                                        "Retirar este archivo local",
                                        disabled=confirmation.strip() != expected,
                                        key=f"catalog_remove_file_{local.id}",
                                    ):
                                        def remove_file_callback(session, file_id=local.id, physical=delete_physical):
                                            result = remove_file_instance(
                                                session,
                                                project_root=project_root,
                                                file_instance_id=file_id,
                                                delete_physical=physical,
                                                removed_by=actor or "local_user",
                                            )
                                            action = "Archivo físico eliminado y copia local retirada" if result.physical_deleted else "Copia local retirada del catálogo"
                                            return f"{action}: {result.relative_path}"

                                        _run_catalog_action(
                                            st, db_path=db_path, unit_id=unit.id, callback=remove_file_callback
                                        )

                            st.divider()
                            st.write("**Qué hacer después**")
                            if not item.files:
                                st.info(
                                    "Este registro todavía no tiene una copia local disponible. Asociá o incorporá "
                                    "un archivo antes de iniciar el procesamiento."
                                )
                            elif item.editable_pages > 0:
                                st.success(
                                    f"El documento ya tiene {item.editable_pages} páginas disponibles para revisión."
                                )
                                if item.source_key and st.button(
                                    "Abrir este documento en Revisar documentos",
                                    key=f"catalog_open_review_{item.link_id}",
                                ):
                                    request_app_view(
                                        st, mode="review", source_key=item.source_key, page=1
                                    )
                                    rerun_app(st)
                            else:
                                current_step = (
                                    "preparar las páginas"
                                    if item.preprocessing_status == "not_started"
                                    else "continuar con la extracción y selección del texto"
                                )
                                st.info(
                                    f"El próximo paso es {current_step}. Podés hacerlo en Procesar documentos; "
                                    "Archive Workbench abrirá esa sección con este archivo identificado para que "
                                    "continúes desde la interfaz."
                                )
                                if st.button(
                                    "Continuar en Procesar documentos",
                                    key=f"catalog_open_processing_{item.link_id}",
                                ):
                                    request_app_view(
                                        st, mode="processing", source_key=item.source_key
                                    )
                                    rerun_app(st)

                            with st.popover("Quitar asociación con esta unidad"):
                                st.warning(
                                    f"Se quitará el vínculo entre {item.original_filename} y {unit.title}. "
                                    "El archivo y el registro del documento digital se conservarán."
                                )
                                with st.form(
                                    f"catalog_unlink_commit_{item.link_id}",
                                    enter_to_submit=False,
                                ):
                                    unlink_confirm = st.checkbox(
                                        "Confirmo que quiero quitar solamente esta asociación",
                                        key=f"catalog_unlink_confirm_{item.link_id}",
                                    )
                                    unlink_submitted = st.form_submit_button(
                                        "Quitar este vínculo entre el documento y la unidad"
                                    )
                                if unlink_submitted and not unlink_confirm:
                                    st.warning("Marcá la confirmación antes de quitar esta asociación.")
                                elif unlink_submitted:
                                    def unlink_callback(session, link_id=item.link_id):
                                        result = unlink_digital_object_from_unit(
                                            session, link_id=link_id, removed_by=actor or "local_user"
                                        )
                                        return (
                                            f"Asociación quitada: {result.original_filename}. "
                                            f"Vínculos restantes: {result.remaining_links}"
                                        )

                                    _run_catalog_action(
                                        st, db_path=db_path, unit_id=unit.id, callback=unlink_callback
                                    )

                file_input_tasks = {
                    "copy": "Copiar un archivo al proyecto",
                    "attach": "Asociar un archivo de corpus/",
                }
                file_input_task = st.selectbox(
                    "Forma de incorporar un archivo",
                    options=list(file_input_tasks),
                    format_func=lambda value: file_input_tasks[value],
                    key=f"catalog_file_input_task_{unit.id}",
                    label_visibility="collapsed",
                )

                if file_input_task == "copy":
                    st.caption(
                        "Elegí un archivo PDF, TIFF, PNG, JPEG o WebP desde esta computadora. Archive Workbench guardará una "
                        "copia dentro de la carpeta corpus/ del proyecto y conservará el archivo de origen sin cambios."
                    )
                    uploaded_file = st.file_uploader(
                        "Archivo que querés incorporar",
                        type=["pdf", "tif", "tiff", "png", "jpg", "jpeg", "webp"],
                        key=f"catalog_upload_file_input_{unit.id}",
                    )
                    upload_inspection = None
                    upload_name = ""
                    upload_content = b""
                    if uploaded_file is not None:
                        upload_name = uploaded_file.name
                        upload_content = uploaded_file.getvalue()
                        try:
                            upload_inspection = _inspect_uploaded_file(upload_name, upload_content)
                        except (OSError, ValueError, RuntimeError) as exc:
                            st.error(f"No se pudo revisar el archivo seleccionado: {exc}")
                        else:
                            st.caption(
                                f"Archivo detectado: {upload_inspection.media_type} · "
                                f"{int(upload_inspection.page_count or 1)} páginas."
                            )
                    upload_destination_key = f"catalog_upload_destination_{unit.id}"
                    upload_destination_current = str(
                        st.session_state.get(upload_destination_key, "corpus/importados")
                    )
                    destination_dir = _directory_input_with_picker(
                        st,
                        label="Carpeta del proyecto donde se copiarán los archivos",
                        key=upload_destination_key,
                        initial_value="corpus/importados",
                        picker_initial=project_root / upload_destination_current,
                        picker_title="Elegir carpeta de destino dentro del proyecto",
                        help_text=(
                            "La ruta se guarda dentro de la carpeta del proyecto. Podés organizar los archivos "
                            "en subcarpetas para localizar los archivos que querés incorporar."
                        ),
                        relative_to=project_root,
                    )
                    upload_relation = st.selectbox(
                        "Relación con esta unidad del catálogo",
                        options=list(RELATION_TYPES),
                        format_func=lambda value: _RELATION_LABELS[value],
                        key=f"catalog_upload_relation_{unit.id}",
                    )
                    st.caption(_relation_help_text(upload_relation))
                    default_start = 1
                    default_end = int(upload_inspection.page_count or 1) if upload_inspection else 1
                    upload_pages = st.columns(2)
                    upload_key_suffix = abs(hash((unit.id, upload_name)))
                    with upload_pages[0]:
                        upload_page_start = st.number_input(
                            "Página inicial",
                            min_value=1,
                            value=default_start,
                            key=f"catalog_upload_start_{upload_key_suffix}",
                        )
                    with upload_pages[1]:
                        upload_page_end = st.number_input(
                            "Página final",
                            min_value=1,
                            value=max(default_start, default_end),
                            key=f"catalog_upload_end_{upload_key_suffix}",
                        )
                    if st.button(
                        "Copiar, registrar y asociar",
                        type="primary",
                        key=f"catalog_upload_submit_{unit.id}",
                    ):
                        if uploaded_file is None or upload_inspection is None:
                            st.error("Seleccioná un archivo válido antes de continuar.")
                        elif int(upload_page_end) < int(upload_page_start):
                            st.error("La página final no puede ser anterior a la página inicial.")
                        else:
                            def upload_callback(session):
                                result = register_uploaded_file(
                                    session,
                                    project_root=project_root,
                                    project_id=decisions.project_id,
                                    archival_unit_id=unit.id,
                                    original_filename=upload_name,
                                    content=upload_content,
                                    destination_dir=destination_dir,
                                    relation_type=upload_relation,
                                    page_start=int(upload_page_start),
                                    page_end=int(upload_page_end),
                                    registered_by=actor or "local_user",
                                )
                                action = (
                                    "El archivo ya estaba disponible y se reutilizó"
                                    if result.reused_existing_path
                                    else "Archivo copiado, registrado y asociado"
                                )
                                return f"{action}: {result.relative_path}"

                            _run_catalog_action(
                                st, db_path=db_path, unit_id=unit.id, callback=upload_callback
                            )

                if file_input_task == "attach":
                    st.caption(
                        "Usá esta opción cuando el archivo ya está guardado dentro de corpus/ en la carpeta "
                        "del proyecto. Podés elegirlo de la lista sin escribir rutas manualmente."
                    )
                    project_files = _project_corpus_files(project_root)
                    if not project_files:
                        st.info(
                            "La carpeta corpus/ todavía no contiene archivos PDF, TIFF, PNG, JPEG o WebP."
                        )
                    else:
                        selected_path = st.selectbox(
                            "Archivo dentro de corpus/",
                            options=project_files,
                            format_func=lambda value: value.relative_to(project_root).as_posix(),
                            key=f"catalog_attach_path_{unit.id}",
                        )
                        relation_type = st.selectbox(
                            "Relación con esta unidad del catálogo",
                            options=list(RELATION_TYPES),
                            format_func=lambda value: _RELATION_LABELS[value],
                            key=f"catalog_attach_relation_{unit.id}",
                        )
                        st.caption(_relation_help_text(relation_type))
                        try:
                            attach_start, attach_end = _default_page_range(selected_path)
                        except (OSError, ValueError, RuntimeError) as exc:
                            st.error(f"No se pudo revisar el archivo seleccionado: {exc}")
                            attach_start, attach_end = 1, 1
                        path_key = abs(hash((unit.id, str(selected_path))))
                        page_cols = st.columns(2)
                        with page_cols[0]:
                            page_start = st.number_input(
                                "Página inicial",
                                min_value=1,
                                value=attach_start,
                                key=f"catalog_attach_start_{path_key}",
                            )
                        with page_cols[1]:
                            page_end = st.number_input(
                                "Página final",
                                min_value=1,
                                value=attach_end,
                                key=f"catalog_attach_end_{path_key}",
                            )
                        if st.button(
                            "Registrar este archivo y vincularlo con la unidad",
                            type="primary",
                            key=f"catalog_attach_submit_{unit.id}",
                        ):
                            if int(page_end) < int(page_start):
                                st.error("La página final no puede ser anterior a la página inicial.")
                            else:
                                relative_path = selected_path.relative_to(project_root).as_posix()
                                _run_catalog_action(
                                    st,
                                    db_path=db_path,
                                    unit_id=unit.id,
                                    callback=lambda session: (
                                        lambda result: (
                                            "Archivo asociado; se reutilizó un contenido ya registrado"
                                            if result.duplicate_content
                                            else "Archivo registrado y asociado"
                                        )
                                    )(
                                        register_local_file(
                                            session,
                                            project_root=project_root,
                                            project_id=decisions.project_id,
                                            archival_unit_id=unit.id,
                                            relative_path=relative_path,
                                            relation_type=relation_type,
                                            page_start=int(page_start),
                                            page_end=int(page_end),
                                            registered_by=actor or "local_user",
                                        )
                                    ),
                                )

                linked_ids = {row.id for row in digital_objects}
                available = [row for row in object_choices if row.id not in linked_ids]
                if available:
                    link_existing_open = st.toggle(
                        "Vincular con esta unidad un archivo digital ya registrado",
                        value=False,
                        key=f"catalog_link_existing_panel_{unit.id}",
                    )
                    if link_existing_open:
                        with st.container(border=True):
                            selected_object_id = st.selectbox(
                                "Documento digital ya registrado que querés vincular",
                                options=[row.id for row in available],
                                format_func=lambda value: next(
                                    f"{row.original_filename} · {row.media_type} · {row.sha256[:10]}…"
                                    for row in available
                                    if row.id == value
                                ),
                                key=f"catalog_existing_digital_{unit.id}",
                            )
                            existing_relation = st.selectbox(
                                "Relación de este documento digital con la unidad",
                                options=list(RELATION_TYPES),
                                format_func=lambda value: _RELATION_LABELS[value],
                                key=f"catalog_existing_relation_{unit.id}",
                            )
                            st.caption(_RELATION_HELP[existing_relation])
                            if st.button("Vincular este archivo digital con la unidad", key=f"catalog_link_existing_{unit.id}"):
                                _run_catalog_action(
                                    st,
                                    db_path=db_path,
                                    unit_id=unit.id,
                                    callback=lambda session: (
                                        link_existing_digital_object(
                                            session,
                                            project_id=decisions.project_id,
                                            archival_unit_id=unit.id,
                                            digital_object_id=selected_object_id,
                                            relation_type=existing_relation,
                                            registered_by=actor or "local_user",
                                        ),
                                        "Contenido digital vinculado",
                                    )[1],
                                )

            with structure_tab:
                st.caption("Revisá el tipo de unidad y su relación con el nivel superior; los cambios crean una nueva revisión y conservan el historial anterior.")
                st.write("**Tipo de unidad**")
                st.caption(
                    "Podés corregir el tipo de esta unidad sin crear otra. Antes de guardar, Archive "
                    "Workbench comprueba que su ubicación, sus unidades hijas y sus datos descriptivos "
                    "sigan siendo compatibles con el nuevo tipo."
                )
                level_keys = [item.key for item in level_defs]
                new_level_key = st.selectbox(
                    "Tipo de unidad",
                    options=level_keys,
                    index=level_keys.index(unit.level_key),
                    format_func=lambda value: level_labels[value],
                    key=f"catalog_change_level_{unit.id}",
                )
                level_note = st.text_input(
                    "Motivo del cambio de tipo",
                    placeholder="Opcional",
                    key=f"catalog_change_level_note_{unit.id}",
                )
                if st.button(
                    "Cambiar tipo de unidad",
                    key=f"catalog_change_level_submit_{unit.id}",
                ):
                    if new_level_key == unit.level_key:
                        st.error("Elegí un tipo diferente antes de guardar el cambio.")
                    else:
                        _run_catalog_action(
                            st,
                            db_path=db_path,
                            unit_id=unit.id,
                            callback=lambda session: (
                                change_archival_unit_level(
                                    session,
                                    decisions=decisions,
                                    unit_id=unit.id,
                                    new_level_key=new_level_key,
                                    changed_by=actor or "local_user",
                                    note=level_note,
                                ),
                                "Tipo de unidad actualizado",
                            )[1],
                        )

                st.divider()
                st.write("**Ubicación y relación dentro del catálogo**")
                current_parent = unit.parent_id
                descendants = _catalog_descendant_ids(all_rows, unit.id)
                blocked_parent_ids = descendants | {unit.id}
                possible_parents = [
                    row
                    for row in all_rows
                    if row.id not in blocked_parent_ids
                    and row.level_key in level_map[unit.level_key].parent_keys
                ]
                root_allowed = not level_map[unit.level_key].parent_keys
                valid_parent_ids = {row.id for row in possible_parents}
                st.write(f"**Ubicación actual:** {by_id[unit.id].path}")
                if current_parent is not None and current_parent in by_id:
                    parent_row = by_id[current_parent]
                    parent_level = level_map[parent_row.level_key]
                    st.caption(
                        _catalog_parent_relation_caption(
                            parent_level=parent_level,
                            parent_path=parent_row.path,
                            child_level=level_map[unit.level_key],
                        )
                    )
                else:
                    st.caption("Esta unidad está en la raíz del catálogo.")
                st.caption(
                    "Abrí el árbol y elegí directamente el nivel superior. Al mover la unidad, también se "
                    "desplaza toda su rama; la interfaz conserva el significado de custodia, jerarquía o ubicación física."
                )
                if possible_parents or root_allowed:
                    target_key = f"catalog_move_target_{unit.id}"
                    if target_key not in st.session_state:
                        st.session_state[target_key] = current_parent
                    current_target = st.session_state.get(target_key)
                    if current_target is not None and current_target not in valid_parent_ids:
                        current_target = current_parent if current_parent in valid_parent_ids else None
                        st.session_state[target_key] = current_target
                    include_ids = {row.id for row in all_rows if row.id not in blocked_parent_ids}
                    selected_parent = catalog_tree_select(
                        st,
                        rows=all_rows,
                        level_labels=level_labels,
                        selected_id=current_target,
                        key=f"catalog_move_tree_{unit.id}",
                        selection_state_key=target_key,
                        selectable_ids=valid_parent_ids,
                        include_ids=include_ids,
                        force_open_ids={current_target} if current_target else set(),
                        allow_root=root_allowed,
                    )
                    if selected_parent != current_target:
                        current_target = selected_parent
                        st.session_state[target_key] = current_target
                    new_parent = current_target
                    chosen_label = (
                        "Raíz del catálogo"
                        if new_parent is None
                        else by_id[new_parent].path
                    )
                    st.caption(f"Nueva ubicación seleccionada: {chosen_label}")
                    with st.form(f"catalog_move_{unit.id}", enter_to_submit=False):
                        move_note = st.text_input(
                            "Motivo para mover esta unidad (opcional)", placeholder="Opcional"
                        )
                        move_submit = st.form_submit_button(
                            "Mover esta unidad a la ubicación elegida"
                        )
                    if move_submit and new_parent == current_parent:
                        st.error("Elegí una ubicación diferente antes de confirmar el movimiento.")
                    elif move_submit:
                        _run_catalog_action(
                            st,
                            db_path=db_path,
                            unit_id=unit.id,
                            callback=lambda session: (
                                move_archival_unit(
                                    session,
                                    decisions=decisions,
                                    unit_id=unit.id,
                                    new_parent_id=new_parent,
                                    changed_by=actor or "local_user",
                                    note=move_note,
                                ),
                                "Unidad movida",
                            )[1],
                        )
                    latest_revision = revisions[0] if revisions else None
                    if latest_revision and latest_revision.operation in {"move", "undo_move"}:
                        st.caption(
                            "El último cambio de esta unidad fue un movimiento. Deshacer crea una nueva revisión; no borra el historial."
                        )
                        if st.button("Deshacer el último movimiento de esta unidad", key=f"catalog_undo_move_{unit.id}_{unit.revision}"):
                            _run_catalog_action(
                                st,
                                db_path=db_path,
                                unit_id=unit.id,
                                callback=lambda session: (
                                    undo_last_archival_move(
                                        session,
                                        decisions=decisions,
                                        unit_id=unit.id,
                                        changed_by=actor or "local_user",
                                    ),
                                    "Movimiento deshecho",
                                )[1],
                            )
                else:
                    st.info("No hay ubicaciones alternativas válidas para este nivel.")
                st.caption(
                    "Archive Workbench impide ciclos y movimientos hacia niveles que la estructura del "
                    "catálogo no permite."
                )

                st.divider()
                st.write("**Eliminar unidad**")
                blocker_engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(blocker_engine) as session:
                        delete_blockers = archival_unit_delete_blockers(session, unit.id)
                finally:
                    blocker_engine.dispose()
                if delete_blockers:
                    st.info(
                        "Esta unidad no puede eliminarse todavía porque "
                        + "; ".join(delete_blockers)
                        + ". Quitá o reasigná esos vínculos antes de eliminarla."
                    )
                else:
                    st.warning(
                        "Eliminar esta unidad borra su descripción y su historial propio del catálogo. "
                        "Esta opción sólo se habilita cuando la unidad no contiene unidades hijas, "
                        "archivos, registros de procedencia ni relaciones con personas u organizaciones."
                    )
                    delete_confirmation = st.text_input(
                        "Escribí ELIMINAR para confirmar",
                        key=f"catalog_delete_confirmation_{unit.id}",
                    )
                    if st.button(
                        "Eliminar esta unidad del catálogo",
                        type="primary",
                        disabled=delete_confirmation.strip() != "ELIMINAR",
                        key=f"catalog_delete_unit_{unit.id}",
                    ):
                        _run_catalog_action(
                            st,
                            db_path=db_path,
                            callback=lambda session: (
                                f"Unidad eliminada: {delete_archival_unit(session, unit_id=unit.id, deleted_by=actor or 'local_user')}",
                                None,
                            ),
                        )

            with history_tab:
                st.caption("Consultá las revisiones registradas para la descripción y la ubicación de la unidad seleccionada.")
                if not revisions:
                    st.info("La unidad todavía no tiene revisiones registradas desde esta etapa.")
                for revision in revisions:
                    with st.expander(
                        f"Rev. {revision.revision_number} · "
                        f"{_OPERATION_LABELS.get(revision.operation, revision.operation)} · "
                        f"{revision.changed_by}",
                        expanded=False,
                    ):
                        st.caption(revision.changed_at.isoformat())
                        if revision.note:
                            st.write(revision.note)
                        snapshot = revision.snapshot
                        st.json(
                            {
                                "parent_id": snapshot.get("parent_id"),
                                "level_key": snapshot.get("level_key"),
                                "reference_code": snapshot.get("reference_code"),
                                "title": snapshot.get("title"),
                                "registration_status": snapshot.get("registration_status"),
                                "completion_confirmed": snapshot.get("completion_confirmed"),
                                "fields": snapshot.get("fields", []),
                            },
                            expanded=False,
                        )
