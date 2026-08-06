import ast
from pathlib import Path

from archive_workbench.ui_navigation import (
    fragmented_view,
    isolated_view,
    request_app_view,
    request_tab,
    rerun_app,
    rerun_view,
    tracked_tabs,
)


class _FakeSlot:
    def __init__(self, calls: list[dict]) -> None:
        self.calls = calls

    def __enter__(self):
        self.calls.append({"container_enter": True})
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.calls.append({"container_exit": True})
        return False

    def container(self, **kwargs):
        self.calls.append({"container": kwargs})
        return self


class _FakeStreamlit:
    def __init__(self) -> None:
        self.session_state: dict[str, str] = {}
        self.calls: list[dict] = []

    def tabs(self, labels, **kwargs):
        self.calls.append({"labels": list(labels), **kwargs})
        return tuple(labels)

    def empty(self):
        self.calls.append({"empty": True})
        return _FakeSlot(self.calls)

    def container(self, **kwargs):
        self.calls.append({"container": kwargs})
        return _FakeSlot(self.calls)

    def fragment(self, render):
        self.calls.append({"fragment": render.__name__})

        def wrapped(*args, **kwargs):
            self.calls.append({"fragment_call": render.__name__})
            return render(*args, **kwargs)

        return wrapped

    def rerun(self, *, scope="app"):
        self.calls.append({"rerun": scope})


def test_tracked_tabs_use_native_state_and_rerun() -> None:
    st = _FakeStreamlit()

    tabs = tracked_tabs(st, ["Uno", "Dos"], key="demo_tabs")

    assert tabs == ("Uno", "Dos")
    assert st.calls == [
        {
            "labels": ["Uno", "Dos"],
            "default": "Uno",
            "key": "demo_tabs",
            "on_change": "rerun",
        }
    ]


def test_pending_tab_is_applied_before_widget_creation() -> None:
    st = _FakeStreamlit()
    st.session_state["demo_tabs"] = "Uno"
    request_tab(st, key="demo_tabs", label="Dos")

    tracked_tabs(st, ["Uno", "Dos"], key="demo_tabs")

    assert st.session_state["demo_tabs"] == "Dos"
    assert st.calls[0]["default"] == "Dos"


def test_programmatic_tab_survives_the_following_widget_rerun() -> None:
    st = _FakeStreamlit()
    request_tab(st, key="processing_tabs", label="Selección canónica")

    tracked_tabs(
        st,
        ["Inventario", "Ejecutar", "Selección canónica", "Historial"],
        key="processing_tabs",
    )
    tracked_tabs(
        st,
        ["Inventario", "Ejecutar", "Selección canónica", "Historial"],
        key="processing_tabs",
    )

    assert st.session_state["processing_tabs"] == "Selección canónica"
    assert st.calls[-1]["default"] == "Selección canónica"


def test_tab_survives_rerun_triggered_before_widget_is_rendered() -> None:
    st = _FakeStreamlit()
    st.session_state["review_object_tabs"] = "Formulario"

    tracked_tabs(
        st,
        ["Editar texto", "Orden y estructura", "Formulario"],
        key="review_object_tabs",
    )

    # Streamlit elimina el estado de un widget que no llegó a renderizarse en un
    # ciclo interrumpido por una acción anterior, como deshacer o exportar.
    del st.session_state["review_object_tabs"]

    tracked_tabs(
        st,
        ["Editar texto", "Orden y estructura", "Formulario"],
        key="review_object_tabs",
    )

    assert st.session_state["review_object_tabs"] == "Formulario"
    assert st.session_state["review_object_tabs__remembered"] == "Formulario"
    assert st.calls[-1]["default"] == "Formulario"


def test_all_application_tabs_use_shared_persistent_navigation() -> None:
    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    offenders = []
    for path in package.glob("*.py"):
        if path.name == "ui_navigation.py":
            continue
        if "st.tabs(" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)

    assert offenders == []


def test_streamlit_minimum_supports_stateful_tabs_and_fragments() -> None:
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"streamlit>=1.55,<2"' in pyproject


def test_top_level_views_use_identified_containers_without_st_empty() -> None:
    st = _FakeStreamlit()

    processing = isolated_view(st, mode="processing")
    review = isolated_view(st, mode="review")

    assert isinstance(processing, _FakeSlot)
    assert isinstance(review, _FakeSlot)
    assert {
        call["container"]["key"]
        for call in st.calls
        if "container" in call
    } == {
        "archive_workbench_view_processing",
        "archive_workbench_view_review",
    }
    assert {"empty": True} not in st.calls


def test_fragmented_view_runs_the_active_renderer_inside_its_own_container() -> None:
    st = _FakeStreamlit()
    seen: list[str] = []

    def render(value: str) -> None:
        seen.append(value)

    fragmented_view(st, render, "ok", mode="processing")

    assert seen == ["ok"]
    assert {"fragment": "render_fragment"} in st.calls
    assert {"fragment_call": "render_fragment"} in st.calls
    assert {"container": {"key": "archive_workbench_view_processing"}} in st.calls
    assert {"container_enter": True} in st.calls
    assert {"container_exit": True} in st.calls


def test_review_app_renders_every_mode_inside_self_contained_fragment() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    assert "def render_active_view() -> None:" in source
    assert "with isolated_view(st, mode=app_mode):" not in source
    assert "fragmented_view(st, render_active_view, mode=app_mode)" in source
    assert source.index('if app_mode == "home":') < source.index(
        "fragmented_view(st, render_active_view, mode=app_mode)"
    )


def test_review_exposes_complete_object_attributes() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    assert '"Atributos"' in source
    assert "st.json(selected.attributes, expanded=True)" in source
    assert "Atributos vigentes del objeto" in source


def test_local_and_cross_view_reruns_have_explicit_scopes() -> None:
    st = _FakeStreamlit()

    rerun_view(st)
    rerun_app(st)

    assert {"rerun": "fragment"} in st.calls
    assert {"rerun": "app"} in st.calls


def test_no_view_calls_streamlit_rerun_directly() -> None:
    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    offenders = []
    for path in package.glob("*_app.py"):
        if "st.rerun(" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)

    assert offenders == []


def test_processing_confirmation_controls_are_batched_in_forms() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "processing_app.py"
    ).read_text(encoding="utf-8")

    assert "processing_rebase_commit_" in source
    assert "processing_keep_edits_commit_" in source
    assert 'st.expander("Rebasar la edición sobre esta candidata", expanded=True)' in source
    assert "st.form_submit_button(\n                                        \"Aplicar rebase" in source


def test_every_streamlit_form_requires_an_explicit_button() -> None:
    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    offenders: list[str] = []
    form_count = 0
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "form"
            ):
                continue
            form_count += 1
            keyword = next(
                (item for item in node.keywords if item.arg == "enter_to_submit"),
                None,
            )
            if not (
                keyword is not None
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
            ):
                offenders.append(f"{path.name}:{node.lineno}")

    assert form_count >= 40
    assert offenders == []



def test_form_confirmation_does_not_circularly_disable_submit_button() -> None:
    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    offenders: list[str] = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "form_submit_button"
            ):
                continue
            disabled = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "disabled"),
                None,
            )
            if disabled is None:
                continue
            confirmation_names = {
                child.id
                for child in ast.walk(disabled)
                if isinstance(child, ast.Name) and child.id.startswith("confirm_")
            }
            if confirmation_names:
                offenders.append(
                    f"{path.name}:{node.lineno}:{','.join(sorted(confirmation_names))}"
                )

    assert offenders == []

def test_catalog_template_confirmation_is_checked_after_submit() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "archive_workbench"
        / "catalog_app.py"
    ).read_text(encoding="utf-8")
    block = source.split('with st.form("catalog_template_apply_form"', 1)[1].split(
        "level_defs = sorted", 1
    )[0]

    assert 'disabled=confirmation.strip() != "IMPORTAR"' not in block
    assert 'if submitted and confirmation.strip() != "IMPORTAR":' in block
    assert "Para aplicar la plantilla, escribí exactamente IMPORTAR." in block



def test_authority_dictionary_confirmation_is_checked_after_submit() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "authority_app.py"
    ).read_text(encoding="utf-8")
    block = source.split('with st.form("authority_dictionary_apply"', 1)[1].split(
        "def render_authorities_view", 1
    )[0]

    assert 'disabled=confirmation.strip() != "IMPORTAR"' not in block
    assert 'if confirmation.strip() != "IMPORTAR":' in block
    assert 'st.form_submit_button(\n            "Aplicar diccionario"' in block
    assert "El diccionario tiene errores y no puede aplicarse." in block


def test_rebase_manual_inputs_require_explicit_form_submission() -> None:
    source_path = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "processing_app.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    input_labels: set[str] = set()
    submit_labels: set[str] = set()
    manual_form_count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            call = item.context_expr
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "form"
            ):
                continue
            if not call.args:
                continue
            key_expr = call.args[0]
            if not (
                isinstance(key_expr, ast.JoinedStr)
                and any(
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and "_manual_form" in value.value
                    for value in key_expr.values
                )
            ):
                continue
            manual_form_count += 1
            keyword = next(
                (keyword for keyword in call.keywords if keyword.arg == "enter_to_submit"),
                None,
            )
            assert (
                keyword is not None
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
            )
            for child in ast.walk(node):
                if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                    continue
                if child.func.attr in {"text_input", "text_area", "number_input"}:
                    if child.args and isinstance(child.args[0], ast.Constant):
                        input_labels.add(str(child.args[0].value))
                if child.func.attr == "form_submit_button":
                    if child.args and isinstance(child.args[0], ast.Constant):
                        submit_labels.add(str(child.args[0].value))

    assert manual_form_count >= 3
    assert {
        "Texto resultante exacto para este tramo",
        "Fragmento exacto dentro del bloque",
        "Valor JSON exacto",
    } <= input_labels
    assert {
        "Confirmar texto manual",
        "Confirmar fragmento manual",
        "Confirmar valor JSON",
    } <= submit_labels


def test_global_input_policy_hides_streamlit_keyboard_instructions() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    assert '[data-testid="InputInstructions"]' in source
    assert "display: none !important" in source
    assert "_render_global_input_policy(st)" in source

def test_request_app_view_records_mode_and_review_target() -> None:
    st = _FakeStreamlit()

    request_app_view(
        st,
        mode="review",
        source_key="doc",
        page=3,
        object_id="obj-1",
    )

    assert st.session_state["review_pending_app_mode"] == "review"
    assert st.session_state["review_pending_navigation"] == {
        "source_key": "doc",
        "page": 3,
        "object_id": "obj-1",
    }


def test_cross_view_navigation_is_centralized() -> None:
    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    offenders = []
    for path in package.glob("*.py"):
        if path.name in {"ui_navigation.py", "review_app.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        if "review_pending_navigation" in source or "review_pending_app_mode" in source:
            offenders.append(path.name)

    assert offenders == []


def test_rebase_submit_is_not_disabled_by_checkbox_state_inside_form() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "processing_app.py"
    ).read_text(encoding="utf-8")

    form_start = source.index("processing_rebase_commit_")
    form_end = source.index("if rebase_submitted", form_start)
    form_source = source[form_start:form_end]
    assert "disabled=not rebase_preview.can_apply" in form_source
    assert "not rebase_confirmed" not in form_source
    assert "if rebase_submitted and not rebase_confirmed" in source


def test_processing_ui_exposes_specialized_attribute_resolution() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "processing_app.py"
    ).read_text(encoding="utf-8")

    assert "rebase_preview.attribute_conflicts" in source
    assert "manual_attribute_selection" in source
    assert "manual_attribute_json" in source
    assert "Valor JSON exacto" in source


def test_exchange_review_groups_multiple_events_and_explains_unmatched_lineage() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    assert "by_event: dict[str, list] = {}" in source
    assert source.index("by_event: dict[str, list] = {}") < source.index(
        "by_event.setdefault(row.event_id, []).append(row)"
    )
    assert "No se encontró un punto de control que demuestre una base común" in source
    assert "Aceptar todos los valores recibidos» no está disponible" in source
    assert 'disabled=first.operation == "create"' in source


def test_sidebar_uses_task_oriented_sections_and_context_help() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    assert '"Sección"' in source
    assert '"Procesar documentos"' in source
    assert '"Revisar documentos"' in source
    assert '"Entidades y menciones"' in source
    assert '"Preparar corpus"' in source
    assert "st.caption(_VIEW_DESCRIPTIONS[app_mode])" in source


def test_exchange_ui_uses_plain_spanish_for_main_workflow() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    start = source.index("def _render_exchange_view")
    end = source.index("def main()", start)
    view = source[start:end]

    assert 'st.header("Intercambio entre copias")' in view
    assert '"Paquete de intercambio"' in view
    assert '"Simular evaluación"' in view
    assert '"Aplicar paquete"' in view
    assert '"Archivar paquete"' in view
    assert '"punto de control' in view
    assert '"Ejecutar dry-run"' not in view
    assert '"Aplicar bundle"' not in view
    assert '"Archivar bundle"' not in view


def test_exchange_stale_entries_are_explained_archivable_and_cleanable() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    assert "Cambios locales posteriores a la simulación" in source
    assert "Secuencia evaluada:" in source
    assert "Mostrar paquetes archivados" in source
    assert "Archivar paquete" in source
    assert "Restaurar entrada" in source
    assert "Eliminar entrada" in source
    assert "purge_incoming_bundle" in source


def test_export_success_is_persistent_and_profiles_have_lifecycle_controls() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "export_app.py"
    ).read_text(encoding="utf-8")

    assert 'st.session_state["export_last_run"]' in source
    assert "Exportación creada correctamente" in source
    assert "Descargar archivo" in source
    assert "Cerrar confirmación" in source
    assert "Mostrar perfiles archivados" in source
    assert "Archivar perfil" in source
    assert "Restaurar perfil" in source
    assert "Eliminar perfil definitivamente" in source
    assert "Exportaciones históricas vinculadas a este perfil" in source
    assert "Ver exportaciones vinculadas" in source


def test_export_profile_lifecycle_rebuilds_selector_inside_current_fragment(monkeypatch) -> None:
    from archive_workbench import export_app

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, object] = {}

    st = FakeStreamlit()
    reruns: list[object] = []
    monkeypatch.setattr(export_app, "rerun_view", lambda received: reruns.append(received))

    export_app._request_profile_view_rebuild(st, selected_id="profile-1")
    assert st.session_state["export_profile_selected_id"] == "profile-1"
    assert st.session_state["export_profile_selector_epoch"] == 1
    assert reruns == [st]

    export_app._request_profile_view_rebuild(st, selected_id=None)
    assert st.session_state["export_profile_selected_id"] is None
    assert st.session_state["export_profile_selector_epoch"] == 2
    assert reruns == [st, st]


def test_export_profile_selector_is_remounted_after_lifecycle_actions() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "export_app.py"
    ).read_text(encoding="utf-8")

    assert 'key=f"export_profile_selector_{selector_epoch}"' in source
    # Guardar sigue solicitando un rerun explícito; archivar, restaurar y eliminar
    # se encolan desde callbacks y se procesan antes de reconstruir la vista.
    assert source.count("_request_profile_view_rebuild(st, selected_id=") == 1
    assert source.count("on_click=_queue_profile_lifecycle_action") == 3
    assert "_process_pending_profile_lifecycle(" in source
    assert source.index("_process_pending_profile_lifecycle(", source.index("def render_export_view")) < source.index(
        'st.header("Exportar corpus")', source.index("def render_export_view")
    )
    assert "rerun_view(st)" in source
    assert "rerun_app(st)" not in source
    assert 'key="export_profile_selection"' not in source


def test_export_profile_archive_is_applied_before_render_without_nested_rerun(monkeypatch) -> None:
    from archive_workbench import export_app

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, object] = {}
            self.errors: list[str] = []

        def error(self, message: object) -> None:
            self.errors.append(str(message))

    st = FakeStreamlit()
    confirm_key = "confirm-profile-1"
    st.session_state[confirm_key] = True

    export_app._queue_profile_lifecycle_action(
        st,
        action="archive",
        profile_id="profile-1",
        confirm_key=confirm_key,
    )
    assert st.session_state[export_app._EXPORT_PENDING_LIFECYCLE_KEY] == {
        "action": "archive",
        "profile_id": "profile-1",
    }

    calls: list[tuple[object, str, str, bool, str]] = []

    def fake_set_archived(
        db_path,
        *,
        project_id: str,
        profile_id: str,
        archived: bool,
        actor: str,
    ) -> str:
        calls.append((db_path, project_id, profile_id, archived, actor))
        return "Perfil de prueba"

    monkeypatch.setattr(export_app, "_set_profile_archived_action", fake_set_archived)
    monkeypatch.setattr(
        export_app,
        "rerun_view",
        lambda received: (_ for _ in ()).throw(AssertionError("no debe solicitar rerun")),
    )

    export_app._process_pending_profile_lifecycle(
        st,
        db_path="db.sqlite3",
        project_id="project-1",
        actor="alex",
    )

    assert calls == [("db.sqlite3", "project-1", "profile-1", True, "alex")]
    assert st.session_state["export_notice"] == "Perfil archivado: Perfil de prueba"
    assert st.session_state[export_app._EXPORT_SELECTION_KEY] is None
    assert st.session_state[export_app._EXPORT_SELECTOR_EPOCH_KEY] == 1
    assert export_app._EXPORT_PENDING_LIFECYCLE_KEY not in st.session_state
    assert st.errors == []


def test_export_profile_lifecycle_requires_confirmation_before_queueing() -> None:
    from archive_workbench import export_app

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, object] = {}

    st = FakeStreamlit()
    export_app._queue_profile_lifecycle_action(
        st,
        action="archive",
        profile_id="profile-1",
        confirm_key="confirm-profile-1",
    )

    assert export_app._EXPORT_PENDING_LIFECYCLE_KEY not in st.session_state
    assert (
        st.session_state[export_app._EXPORT_LIFECYCLE_ERROR_KEY]
        == "Marcá la confirmación antes de archivar el perfil."
    )


def test_guided_navigation_keeps_every_section_and_adds_contextual_steps() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    assert "_WORKFLOW_STEPS = (" in source
    for mode in (
        '"catalog"',
        '"processing"',
        '"work"',
        '"review"',
        '"search"',
        '"semantic"',
        '"authorities"',
        '"graph"',
        '"export"',
        '"exchange"',
        '"admin"',
    ):
        assert mode in source
    assert "Mostrar orientación de la sección" in source
    assert "← Sección anterior" in source
    assert "Sección siguiente →" in source
    assert "Objetivo de esta sección" in source
    assert "Antes de empezar y qué sigue" in source


def test_administration_uses_clear_spanish_and_hides_restore_command_by_default() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "admin_app.py"
    ).read_text(encoding="utf-8")

    assert 'st.header("Administrar y recuperar")' in source
    assert "Crear y verificar copias" in source
    assert "Crear copia de seguridad" in source
    assert "Copias de seguridad disponibles" in source
    assert "Copia de seguridad a probar" in source
    assert "Copia de seguridad a restaurar" in source
    assert 'st.expander("Ver comando técnico de restauración")' in source
    assert 'st.form_submit_button("Crear backup"' not in source


def test_export_formats_include_plain_language_explanations() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "export_app.py"
    ).read_text(encoding="utf-8")

    assert '"jsonl": "JSONL · un registro por línea"' in source
    assert '"csv": "CSV · tabla"' in source
    assert source.count("_OUTPUT_FORMAT_LABELS.get") >= 2


def test_literal_search_keeps_basic_decisions_visible_and_preserves_all_filters() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    start = source.index("def _render_search_view")
    end = source.index("def _format_exchange_value", start)
    view = source[start:end]

    assert 'st.header("Buscar texto")' in view
    assert '"Qué querés encontrar"' in view
    assert '"Cómo combinar las palabras"' in view
    assert 'st.expander("Filtros opcionales", expanded=False)' in view
    assert 'st.expander("Mantenimiento del índice de texto", expanded=False)' in view
    assert 'st.expander("Detalles técnicos del índice", expanded=False)' in view
    for label in (
        '"Dónde buscar"',
        '"Documentos"',
        '"Tipos de objeto"',
        '"Estado del objeto"',
        '"Estado de la página"',
        '"Categorías de etiqueta presentes"',
        '"Incluir objetos dados de baja"',
        '"Buscar también dentro de las palabras"',
        '"Máximo de resultados"',
    ):
        assert label in view
    assert view.count('"Buscar también dentro de las palabras"') == 1
    assert view.index('"Buscar también dentro de las palabras"') < view.index(
        'st.expander("Filtros opcionales", expanded=False)'
    )
    assert 'st.header("Búsqueda transversal")' not in view


def test_catalog_and_processing_use_progressive_task_oriented_hierarchy() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    catalog = (root / "catalog_app.py").read_text(encoding="utf-8")
    processing = (root / "processing_app.py").read_text(encoding="utf-8")

    assert 'st.header("Catálogo documental")' in catalog
    assert 'st.expander("Resumen del catálogo"' in catalog
    assert '"Buscar en el catálogo"' in catalog
    assert 'st.expander("Filtros del catálogo", expanded=False)' in catalog
    assert '"Nivel documental"' in catalog
    assert '"Estado de descripción"' in catalog
    assert 'st.expander("Datos de la unidad", expanded=False)' in catalog

    assert 'st.header("Procesar documentos")' in processing
    assert 'st.expander("Resumen de avance", expanded=False)' in processing
    assert '"Qué querés hacer"' in processing
    assert 'st.expander("Opciones avanzadas", expanded=False)' in processing
    assert '"Crear una nueva versión aunque exista una equivalente"' in processing
    assert '"Ejecutar tarea"' in processing
    assert '"Ejecutar operación"' not in processing


def test_semantic_search_separates_plain_language_from_technical_configuration() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "semantic_app.py"
    ).read_text(encoding="utf-8")

    assert 'st.header("Buscar por significado")' in source
    assert '"Perfil de búsqueda"' in source
    assert '["Buscar", "Preparar búsqueda"]' in source
    assert 'st.expander("Estado técnico del índice", expanded=False)' in source
    assert 'st.expander("Opciones de búsqueda", expanded=False)' in source
    assert 'st.expander("Contenido incluido", expanded=True)' in source
    assert 'st.expander("Configuración técnica del índice", expanded=False)' in source
    assert '"cpu": "Procesador (CPU)"' in source
    assert '"cuda": "Placa NVIDIA (CUDA)"' in source
    assert '"Similitud mínima"' in source
    assert '"Construir o reconstruir índice"' in source
    assert '"Configurar e indexar"' not in source


def test_review_uses_progressive_task_oriented_hierarchy() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    start = source.index('st.header("Revisar documentos")')
    view = source[start:]

    assert 'st.expander("Cómo funciona la revisión", expanded=False)' in view
    assert 'st.expander("Opciones de visualización", expanded=False)' in view
    assert 'st.expander("Resumen del documento", expanded=False)' in view
    assert 'st.expander("Herramientas de la capa editable", expanded=False)' in view
    assert 'st.expander("Estado de revisión de la página", expanded=False)' in view
    assert 'st.expander("Deshacer o rehacer cambios", expanded=False)' in view
    assert 'st.subheader("Revisar objetos de la página")' in view
    assert 'st.expander("Datos del objeto seleccionado", expanded=False)' in view
    for label in (
        '"Editar texto"',
        '"Orden y estructura"',
        '"Anotaciones"',
        '"Datos adicionales"',
        '"Menciones"',
        '"Historial"',
        '"Agregar objeto"',
    ):
        assert label in view


def test_authorities_separate_search_filters_summary_and_tasks() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "authority_app.py"
    ).read_text(encoding="utf-8")

    assert 'st.header("Entidades y menciones")' in source
    assert 'st.expander("Qué es una entidad", expanded=False)' in source
    assert '"Revisar entidades"' in source
    assert '"Crear entidad"' in source
    assert '"Importar diccionario"' in source
    assert '"Descubrimiento abierto"' in source
    assert 'key="authority_main_tasks"' in source
    assert 'default="Revisar entidades"' in source
    assert 'with entities_tab:' in source
    assert 'with create_tab:' in source
    assert 'with dictionary_tab:' in source
    assert 'with discovery_tab:' in source
    assert '_render_open_discovery_panel' not in source
    assert '"Buscar nombre, nombre alternativo o descripción"' in source
    assert 'st.expander("Filtros de entidades", expanded=False)' in source
    assert '"Tipos de entidad"' in source
    assert '"Incluir entidades dadas de baja"' in source
    assert 'st.expander("Resumen de la entidad", expanded=False)' in source
    assert source.count('summary_cols[0].metric("Tipo", _TYPE_LABELS[selected.entity_type])') == 1
    assert '"Nombres alternativos"' in source
    assert '"Menciones en documentos"' in source
    assert 'st.subheader("Encontrar nuevas menciones en el corpus")' in source
    assert 'st.expander("Opciones de búsqueda", expanded=False)' in source
    assert 'st.subheader("Menciones ya vinculadas")' in source


def test_graph_uses_plain_language_and_progressive_details() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "graph_app.py"
    ).read_text(encoding="utf-8")

    assert 'st.header("Mapa de relaciones")' in source
    assert 'st.expander("Cómo se construye este mapa", expanded=False)' in source
    assert 'st.expander("Filtros del mapa", expanded=False)' in source
    assert '"Tipos de vínculo"' in source
    assert 'st.expander("Resumen del mapa", expanded=False)' in source
    assert '["Explorar", "Revisar alertas", "Exportar datos"]' in source
    assert 'st.expander("Cómo leer los elementos y vínculos", expanded=False)' in source
    assert source.count('st.expander("Detalles técnicos", expanded=False)') >= 2
    assert '"Seleccioná un elemento o un vínculo' in source
    assert 'st.header("Grafo documental")' not in source


def test_review_object_details_wrap_long_status_values() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    start = source.index('st.expander("Datos del objeto seleccionado", expanded=False)')
    view = source[start : start + 1800]

    assert "_render_wrapping_detail" in source
    assert 'st.columns(2)' in view
    assert '"Revisión humana"' in view
    assert '_STATUS_LABELS[selected.review_status]' in view
    assert 'metadata_d.metric("Revisión humana"' not in source
    assert '"active": "Activo"' in source
    assert '"deleted": "Eliminado"' in source


def test_work_and_export_finish_progressive_plain_language_hierarchy() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    work = (root / "work_app.py").read_text(encoding="utf-8")
    export = (root / "export_app.py").read_text(encoding="utf-8")

    assert 'st.header("Organizar trabajo")' in work
    assert 'st.expander("Cómo se organiza el trabajo", expanded=False)' in work
    assert '["Resumen", "Asignar y administrar", "Mi trabajo", "Revisión cruzada"]' in work
    assert 'st.expander("Carga por responsable", expanded=False)' in work
    assert 'st.expander("Avance de los documentos", expanded=False)' in work
    assert 'st.expander("Filtros de asignaciones", expanded=False)' in work
    assert '"Tipo de tarea"' in work
    assert 'cols[3].metric("Revisiones cruzadas pendientes"' not in work

    assert 'st.expander("Cómo preparar una exportación", expanded=False)' in export
    assert '"Perfil de exportación"' in export
    assert '["Configurar perfil", "Revisar contenido", "Crear archivo", "Historial"]' in export
    assert '"Nombre o ruta del archivo dentro del proyecto"' in export
    assert 'st.expander("Detalles técnicos del registro", expanded=False)' in export
    assert 'st.expander("Detalles técnicos de la exportación", expanded=False)' in export
    assert '"Ruta de salida relativa a project_data"' not in export


def test_graph_exposes_only_auditable_mention_repairs() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "graph_app.py"
    ).read_text(encoding="utf-8")

    assert 'st.subheader("Menciones que requieren revisión")' in source
    assert '"Reubicables con seguridad"' in source
    assert '"Requieren decisión humana"' in source
    assert '"Reubicar mención"' in source
    assert '"Confirmo que deseo reubicar esta mención y registrar una nueva revisión"' in source
    assert 'st.markdown("**Resolver entidad faltante**")' in source
    assert '"Vincular a una entidad existente"' in source
    assert '"Devolver la mención a pendiente"' in source
    assert '"Confirmo que deseo vincular esta mención y registrar "' in source
    assert '"Confirmo que deseo devolver esta mención a pendiente "' in source
    assert 'st.markdown("**Resolver la duplicación**")' in source
    assert 'st.markdown("**Resolver el conjunto completo**")' in source
    assert '"Mención que se conservará"' in source
    assert '"Registrar decisión conjunta"' in source
    assert 'st.markdown("### Acciones agrupadas verificables")' in source
    assert '"Reubicar menciones seguras"' in source
    assert '"Conservar la mención ya ubicada en el texto vigente"' in source
    assert '"Conservar la mención histórica y reubicarla"' in source
    assert '"Registrar decisión sobre el duplicado"' in source
    assert 'st.markdown("**Resolver la ubicación manualmente**")' in source
    assert '"Fragmento exacto en el texto vigente"' in source
    assert '"Aparición que corresponde a la mención"' in source
    assert '"Registrar que el fragmento ya no está presente"' in source
    assert '"Reubicar mención manualmente"' in source
    assert '"Retirar mención ausente"' in source
    assert 'st.markdown("**Reconciliar la divergencia**")' in source
    assert '"Conservar la fila vigente y registrarla en el historial"' in source
    assert '"Restaurar el último estado registrado"' in source
    assert '"Conservar fila vigente"' in source
    assert '"Restaurar estado registrado"' in source
    assert 'st.expander("Detalles técnicos e historial de la alerta", expanded=False)' in source
    authorities = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "authorities.py"
    ).read_text(encoding="utf-8")
    assert 'operation="repair_relocation"' in authorities
    assert 'operation = "repair_link_authority"' in authorities
    assert 'operation = "repair_return_pending"' in authorities
    assert 'operation="repair_duplicate_rejected"' in authorities
    assert 'operation="repair_duplicate_relocated"' in authorities
    assert 'operation="repair_group_duplicate_rejected"' in authorities
    assert 'winner_operation = "repair_group_duplicate_relocated"' in authorities
    assert 'winner_operation = "repair_group_duplicate_kept"' in authorities
    assert 'operation="repair_group_relocation"' in authorities
    assert 'operation="repair_manual_relocation"' in authorities
    assert 'operation="repair_mark_absent"' in authorities
    assert 'operation="repair_adopt_current_row"' in authorities
    assert 'operation="repair_capture_divergent_row"' in authorities
    assert 'operation="repair_restore_snapshot"' in authorities


def test_group_duplicate_form_submit_is_not_circularly_disabled() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "graph_app.py"
    ).read_text(encoding="utf-8")

    start = source.index('st.markdown("**Resolver el conjunto completo**")')
    end = source.index('if case.can_resolve_duplicate:', start)
    section = source[start:end]

    assert 'disabled=winner_id is None' not in section
    assert 'if duplicate_group_submit and winner_id is None:' in section
    assert '"Elegí la mención que se conservará antes de registrar la decisión."' in section


def test_exchange_lineage_recovery_uses_explicit_non_circular_form() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    start = source.index('with st.expander("Diagnosticar evidencia de linaje"')
    end = source.index('if selected.status == "stale"', start)
    block = source[start:end]

    assert "diagnose_unmatched_bundle_lineage" in block
    assert "Ejecutar diagnóstico de solo lectura" in block
    assert "recover_unmatched_bundle_lineage" in block
    assert 'enter_to_submit=False' in block
    assert 'st.form_submit_button(\n                                "Recuperar linaje"' in block
    assert "disabled=" not in block
    assert "if recovery_submitted:" in block
    assert 'elif not recovery_reason.strip():' in block
    assert 'elif not recovery_confirmed:' in block
    assert "Establecer base común" not in block


def test_exchange_common_base_forms_are_explicit_and_not_circularly_disabled() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    start = source.index('with st.expander("Establecer una base común entre copias"')
    end = source.index('with st.expander("Recibir y evaluar un paquete ZIP"', start)
    block = source[start:end]

    assert 'options=["Crear propuesta", "Aceptar propuesta", "Finalizar acuerdo"]' in block
    assert 'enter_to_submit=False' in block
    assert '"Crear propuesta de base común"' in block
    assert '"Aceptar y completar acuerdo"' in block
    assert '"Finalizar acuerdo en esta copia"' in block
    assert "create_common_base_proposal" in block
    assert "accept_common_base_proposal" in block
    assert "finalize_common_base_agreement" in block
    assert "disabled=" not in block
    assert "if proposal_submitted:" in block
    assert "if accept_submitted:" in block
    assert "if finalize_submitted:" in block


def test_exchange_state_adoption_forms_are_explicit_and_not_circularly_disabled() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    start = source.index('with st.expander("Reconciliar estados divergentes"')
    end = source.index('with st.expander("Establecer una base común entre copias"', start)
    block = source[start:end]

    assert 'options=["Crear paquete de estado", "Previsualizar y adoptar"]' in block
    assert '"Previsualizar impacto sin escribir"' in block
    assert 'enter_to_submit=False' in block
    assert '"Crear paquete de estado"' in block
    assert '"Adoptar estado recibido"' in block
    assert "create_state_adoption_package" in block
    assert "preview_state_adoption" in block
    assert "apply_state_adoption" in block
    assert "disabled=" not in block
    assert "if package_submitted:" in block
    assert "if adoption_submitted:" in block
    assert 'elif not adoption_confirmed:' in block
    assert "exchange-state-adoption-rollback" in block


def test_manual_discovery_group_defers_selectbox_selection_until_next_rerun() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "archive_workbench"
        / "discovery_app.py"
    ).read_text(encoding="utf-8")

    assert '"open_discovery_group_pending_selection"' in source
    assert '] = group.id' in source
    assert 'st.session_state["open_discovery_group_selected"] = group.id' not in source
    assert 'pending_group_id = st.session_state.pop(' in source
    assert 'if pending_group_id in group_map:' in source
    assert 'st.session_state["open_discovery_group_selected"] = pending_group_id' in source
