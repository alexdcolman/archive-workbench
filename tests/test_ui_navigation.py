import ast
from pathlib import Path
from types import SimpleNamespace

from archive_workbench.processing_app import (
    _extraction_run_ui_label,
    _processing_document_labels,
    _processing_row_identity,
    _remember_multi_widget_state,
    _remember_single_widget_state,
    _restore_multi_widget_state,
    _restore_single_widget_state,
)

from archive_workbench.ui_navigation import (
    isolated_view,
    request_app_view,
    request_tab,
    rerun_app,
    rerun_view,
    tracked_tabs,
)
from archive_workbench.ui_help import SECTION_HELP, TAB_HELP, TASK_HELP


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


def test_catalog_document_inputs_follow_the_public_format_contract() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "catalog_app.py"
    ).read_text(encoding="utf-8")

    assert "_SUPPORTED_DOCUMENT_SUFFIXES = PROCESSABLE_DOCUMENT_SUFFIXES" in source
    assert 'type=["pdf", "tif", "tiff", "png", "jpg", "jpeg", "webp"]' in source
    assert 'type=["pdf", "tif", "tiff", "png", "jpg", "jpeg", "bmp", "webp"]' not in source
    assert "PDF, TIFF, PNG, JPEG o WebP" in source



def test_catalog_relation_caption_distinguishes_custody_hierarchy_and_location() -> None:
    from archive_workbench.catalog_app import _catalog_parent_relation_caption

    custody = SimpleNamespace(resolved_semantic_kind="custody_context")
    record_set = SimpleNamespace(resolved_semantic_kind="record_set")
    container = SimpleNamespace(resolved_semantic_kind="container")
    record = SimpleNamespace(resolved_semantic_kind="record")

    custody_caption = _catalog_parent_relation_caption(
        parent_level=custody,
        parent_path="Archivo / APM Chubut",
        child_level=record_set,
    )
    hierarchy_caption = _catalog_parent_relation_caption(
        parent_level=record_set,
        parent_path="Fondo / Serie A",
        child_level=record,
    )
    location_caption = _catalog_parent_relation_caption(
        parent_level=record_set,
        parent_path="Fondo / Serie A",
        child_level=container,
    )
    undecided_caption = _catalog_parent_relation_caption(
        parent_level=record_set,
        parent_path="Fondo / Serie A",
    )

    assert custody_caption.startswith("Contexto de custodia:")
    assert hierarchy_caption.startswith("Jerarquía documental:")
    assert location_caption.startswith("Ubicación física:")
    assert "puede expresar jerarquía documental o ubicación física" in undecided_caption

def test_tracked_tabs_are_passive_by_default() -> None:
    st = _FakeStreamlit()

    tabs = tracked_tabs(st, ["Uno", "Dos"], key="demo_tabs")

    assert tabs == ("Uno", "Dos")
    assert st.calls == [
        {
            "labels": ["Uno", "Dos"],
            "default": "Uno",
            "key": "demo_tabs",
            "on_change": "ignore",
        }
    ]


def test_passive_tracked_tabs_keep_visual_state_in_browser_without_python_trigger() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "ui_navigation.py").read_text(encoding="utf-8")
    start = source.index("def _tab_state_keeper_renderer")
    end = source.index("def tracked_tabs", start)
    keeper = source[start:end]

    assert "sessionStorage" in keeper
    assert "archive-workbench-tab:" in keeper
    assert '[role=\"tab\"]' in keeper
    assert "aria-selected" in keeper
    assert "tab.click()" in keeper
    assert "setStateValue" not in keeper
    assert "setTriggerValue" not in keeper


def test_context_help_uses_discoverable_info_icons_without_question_badges() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "ui_navigation.py").read_text(encoding="utf-8")

    assert "data-aw-info-icon" in source
    assert "aw-info-icon" in source
    assert "role', 'tooltip" in source
    assert "aria-describedby" in source
    assert "aria-description" in source
    assert "mouseenter" in source
    assert "focus" in source
    assert "setStateValue" not in source[source.index("def _context_help_renderer"):source.index("def request_tab")]
    assert "setTriggerValue" not in source[source.index("def _context_help_renderer"):source.index("def request_tab")]
    assert 'badge("?"' not in source
    assert "contextual_help" not in source
    assert "var(--st-secondary-background-color, Canvas)" in source
    assert "var(--st-text-color, CanvasText)" in source
    assert "var(--secondary-background-color)" not in source
    assert "pointerFocusIsRecent" in source
    assert "matches(':focus-visible')" in source
    assert "event.key === 'Escape'" in source


def test_tracked_tabs_can_switch_without_forcing_rerun() -> None:
    st = _FakeStreamlit()

    tabs = tracked_tabs(
        st,
        ["Descripción", "Productores y gestión"],
        key="catalog_detail_tabs",
        rerun_on_change=False,
    )

    assert tabs == ("Descripción", "Productores y gestión")
    assert st.calls == [
        {
            "labels": ["Descripción", "Productores y gestión"],
            "default": "Descripción",
            "key": "catalog_detail_tabs",
            "on_change": "ignore",
        }
    ]
    assert "catalog_detail_tabs" not in st.session_state




def test_passive_tracked_tabs_honor_programmatic_navigation_without_tab_rerun() -> None:
    st = _FakeStreamlit()
    request_tab(st, key="processing_tabs", label="Elegir texto")

    tracked_tabs(
        st,
        ["Estado", "Preparar / extraer", "Elegir texto"],
        key="processing_tabs",
        rerun_on_change=False,
    )

    assert st.session_state["processing_tabs__remembered"] == "Elegir texto"
    assert st.session_state["processing_tabs"] == "Elegir texto"
    assert "processing_tabs__pending" not in st.session_state
    assert st.calls[-1]["default"] == "Elegir texto"
    assert st.calls[-1]["on_change"] == "ignore"


def test_extraction_run_label_makes_the_actual_engine_visible() -> None:
    assert _extraction_run_ui_label(SimpleNamespace(engine="surya_cli", profile_key="surya")) == "Surya"
    assert _extraction_run_ui_label(SimpleNamespace(engine="docling_cli", profile_key="fallback")) == "Docling"
    assert _extraction_run_ui_label(SimpleNamespace(engine="tesseract_tsv", profile_key="ocr")) == "Tesseract"


def test_processing_document_labels_keep_homonymous_documents_distinct() -> None:
    rows = [
        SimpleNamespace(
            digital_object_id="doc-1",
            source_type="catalog",
            source_key="catalog_a",
            title="Informe",
            original_filename="informe.pdf",
            archival_path="Fondo A > Serie 1 > Informe",
            status="prepared",
        ),
        SimpleNamespace(
            digital_object_id="doc-2",
            source_type="catalog",
            source_key="catalog_b",
            title="Informe",
            original_filename="informe.pdf",
            archival_path="Fondo B > Serie 2 > Informe",
            status="prepared",
        ),
    ]

    labels = _processing_document_labels(rows, include_status=True)

    assert _processing_row_identity(rows[0]) == "doc-1"
    assert _processing_row_identity(rows[1]) == "doc-2"
    assert labels["doc-1"] != labels["doc-2"]
    assert "Fondo A > Serie 1 > Informe" in labels["doc-1"]
    assert "Fondo B > Serie 2 > Informe" in labels["doc-2"]
    assert labels["doc-1"].endswith("Imágenes listas para extraer texto")


def test_processing_document_labels_use_readable_ordinals_for_exact_visible_duplicates() -> None:
    rows = [
        SimpleNamespace(
            digital_object_id="internal-doc-9",
            source_type="catalog",
            source_key="catalog_secret_a",
            title="Informe",
            original_filename="informe.pdf",
            archival_path="Fondo A > Informe",
            status="prepared",
        ),
        SimpleNamespace(
            digital_object_id="internal-doc-2",
            source_type="catalog",
            source_key="catalog_secret_b",
            title="Informe",
            original_filename="informe.pdf",
            archival_path="Fondo A > Informe",
            status="prepared",
        ),
    ]

    labels = _processing_document_labels(rows)

    assert set(labels) == {"internal-doc-9", "internal-doc-2"}
    assert set(labels.values()) == {
        "Informe · informe.pdf · Fondo A > Informe · documento 1",
        "Informe · informe.pdf · Fondo A > Informe · documento 2",
    }
    visible = " ".join(labels.values())
    assert "internal-doc" not in visible
    assert "catalog_secret" not in visible


def test_processing_tabs_and_document_selectors_follow_streamlit_invariant() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "processing_app.py"
    ).read_text(encoding="utf-8")
    render = source.split("def render_processing_view(", 1)[1]
    tab_block = render.split("with inventory_tab:", 1)[0]
    execute = render.split("with execute_tab:", 1)[1].split("with regional_tab:", 1)[0]

    assert "rerun_on_change=False" in tab_block
    assert 'key="processing_document_ids"' in execute
    assert "eligible_by_id = {_processing_row_identity(row): row for row in eligible_rows}" in execute
    assert 'key="processing_source_keys"' not in execute


def test_processing_forms_do_not_disable_submit_from_widgets_inside_same_form() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "processing_app.py"
    ).read_text(encoding="utf-8")
    block = source.split('f"processing_keep_edits_commit_', 1)[1].split('if manual_path == "rebase":', 1)[0]

    assert "disabled=not keep_confirmed" not in block
    assert "if keep_submitted and not keep_confirmed" in block
    assert "Marcá la confirmación dentro del formulario" in block


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

    assert "review_object_tabs" not in st.session_state
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


def test_streamlit_minimum_supports_stateful_tabs_and_components_v2() -> None:
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


def test_review_app_renders_active_mode_directly_and_mounts_scroll_keeper() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    assert "def render_active_view() -> None:" in source
    assert "with isolated_view(st, mode=app_mode):" not in source
    assert "fragmented_view(st, render_active_view, mode=app_mode)" not in source
    navigation = (Path(__file__).parents[1] / "src" / "archive_workbench" / "ui_navigation.py").read_text(encoding="utf-8")
    assert "def fragmented_view(" not in navigation
    assert "st.fragment(" not in navigation
    assert "mount_view_scroll_keeper(st, view_key=app_mode)" in source
    assert "render_active_view()" in source
    assert source.index('if app_mode == "home":') < source.rindex("render_active_view()")


def test_review_exposes_complete_object_attributes() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    assert '"Datos adicionales"' in source
    assert "st.json(selected.attributes, expanded=True)" in source
    assert "información adicional asociada" in TAB_HELP["review_object_tabs"]["Datos adicionales"]



def test_local_and_cross_view_reruns_have_explicit_scopes() -> None:
    st = _FakeStreamlit()

    rerun_view(st)
    rerun_app(st)

    assert st.calls.count({"rerun": "app"}) == 2


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
    assert 'key=f"processing_manual_path_{current_row.digital_object_id}_{page}_{run_id}"' in source
    assert '"keep": "Mantener la edición actual"' in source
    assert '"rebase": "Trasladar la edición a la extracción comparada"' in source
    assert 'st.expander("Trasladar la edición existente a esta extracción"' not in source
    assert "st.form_submit_button(\n                                        \"Aplicar el traslado y usar la extracción nueva" in source


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
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "catalog_app.py").read_text(encoding="utf-8")
    block = source.split('with st.form("catalog_template_apply_form"', 1)[1].split("level_defs = sorted", 1)[0]
    assert 'disabled=confirmation.strip() != "IMPORTAR"' not in block
    assert 'if submitted and confirmation.strip() != "IMPORTAR":' in block
    assert "Para guardar en el catálogo los cambios de la planilla, escribí exactamente IMPORTAR." in block
    assert "Guardar en el catálogo los cambios de esta planilla" in block




def test_authority_dictionary_confirmation_is_checked_after_submit() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "authority_app.py").read_text(encoding="utf-8")
    block = source.split('with st.form("authority_dictionary_apply"', 1)[1].split("def render_authorities_view", 1)[0]
    assert 'disabled=confirmation.strip() != "IMPORTAR"' not in block
    assert 'if confirmation.strip() != "IMPORTAR":' in block
    assert "Guardar en el proyecto los datos de este diccionario" in block
    assert "El diccionario tiene errores y no puede aplicarse." in block



def test_rebase_manual_inputs_require_explicit_form_submission() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "processing_app.py").read_text(encoding="utf-8")
    for label in (
        "Texto resultante exacto para este tramo",
        "Fragmento exacto dentro del texto",
        "Valor técnico exacto que querés conservar (JSON)",
        "Confirmar texto manual",
        "Confirmar este fragmento como nueva ubicación",
        "Confirmar este valor técnico",
    ):
        assert label in source
    assert source.count("enter_to_submit=False") >= 3



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
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "processing_app.py").read_text(encoding="utf-8")
    assert "rebase_preview.attribute_conflicts" in source
    assert "manual_attribute_selection" in source
    assert "manual_attribute_json" in source
    assert "Valor técnico exacto que querés conservar (JSON)" in source




def test_exchange_review_groups_multiple_events_and_explains_unmatched_lineage() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    assert "by_event: dict[str, list] = {}" in source
    assert "No se pudo comprobar un punto de partida compartido" in source
    assert "Intentar reconstruir el historial compartido" in source
    assert 'key=f"exchange_lineage_panel_{selected_bundle}"' not in source
    assert 'lineage_panel_key = f"exchange_lineage_panel_{selected_bundle}"' in source
    assert 'with st.expander("Buscar evidencia del historial compartido' not in source
    assert '"Diferencia que querés revisar"' in source


def test_sidebar_uses_task_oriented_sections_and_context_help() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    assert '"Sección"' in source
    assert '"Procesar documentos"' in source
    assert '"Revisar documentos"' in source
    assert '"Entidades y menciones"' in source
    assert '"Exportar corpus"' in source
    assert 'st.title("Archive Workbench")' in source
    assert "_VIEW_DESCRIPTIONS" not in source



def test_exchange_ui_uses_plain_spanish_for_main_workflow() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    view = source[source.index("def _render_exchange_view"):source.index("def main()", source.index("def _render_exchange_view"))]
    for phrase in (
        'section_heading(st, "Intercambiar cambios")',
        'key="exchange_main_task"',
        "Enviar cambios",
        "Recibir cambios",
        "Preparar una copia para trabajar en equipo",
        "Resolver un problema entre copias",
        "Crear paquete de cambios",
        "Descargar paquete",
        "Crear copia para compartir",
        "Abrir otro ZIP recibido",
        "Incorporar cambios al proyecto",
        "Archivar paquete",
    ):
        assert phrase in view
    assert "No hace falta " in view
    assert "indicar quién lo va a recibir" in view
    assert "ZIP puede enviarse a varias personas" in view
    assert "Punto de partida del paquete" not in view
    assert "Ejecutar dry-run" not in view
    assert "Aplicar bundle" not in view
    assert '"more": "Más opciones"' not in view
    assert "Opción secundaria" not in view
    assert "Google Drive se usa sólo para trasladar ZIP" not in source



def test_exchange_ui_creates_incremental_package_inside_project() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    view = source[
        source.index("def _render_exchange_view") : source.index(
            "def main()", source.index("def _render_exchange_view")
        )
    ]
    assert "checkpoint_rows(session)" in view
    assert "selected_checkpoint = checkpoints[-1]" in view
    assert "export_change_bundle(" in view
    assert "checkpoint_ref=selected_checkpoint.checkpoint_id" in view
    assert 'st.session_state["exchange_last_created_bundle"]' in view
    assert "create_team_copy_package(" in view
    assert 'st.session_state["exchange_last_team_copy"]' in view
    assert "_render_created_artifact_drive_action(" in view
    assert "Qué querés incluir en la copia" in source
    assert "Tamaño estimado" in source



def test_google_drive_transport_is_integrated_into_normal_exchange_tasks() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    upload = source[
        source.index("def _render_created_artifact_drive_action") : source.index(
            "def _render_google_drive_receive",
            source.index("def _render_created_artifact_drive_action"),
        )
    ]
    receive = source[
        source.index("def _render_google_drive_receive") : source.index(
            "def _render_receive_zip_source",
            source.index("def _render_google_drive_receive"),
        )
    ]
    receive_source = source[
        source.index("def _render_receive_zip_source") : source.index(
            "def _render_exchange_advanced_tools",
            source.index("def _render_receive_zip_source"),
        )
    ]
    assert "upload_archive_workbench_zip_to_drive(" in upload
    assert "download_archive_workbench_zip_from_drive(" in receive
    assert "pick_drive_exchange_bundle(" in receive
    assert '"local": "Desde este equipo"' in receive_source
    assert '"drive": "Desde Google Drive"' in receive_source
    assert "inspect_drive_artifact(temp_path)" in receive_source
    assert "_render_google_drive_transport" not in source



def test_exchange_advanced_zip_paths_offer_file_selectors() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    for label in (
        "Elegir ZIP con el trabajo editable completo",
        "Elegir ZIP de propuesta recibido",
        "Elegir ZIP de propuesta original",
        "Elegir ZIP de acuerdo completado",
    ):
        assert label in source
    assert source.count("st.file_uploader(") >= 5


def test_receive_file_selector_distinguishes_team_copy_from_change_bundle() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    helper = source[
        source.index("def _render_receive_zip_source") : source.index(
            "def _render_exchange_advanced_tools",
            source.index("def _render_receive_zip_source"),
        )
    ]
    view = source[
        source.index('if exchange_task == "receive":') : source.index(
            "if not incoming:", source.index('if exchange_task == "receive":')
        )
    ]
    assert "_render_receive_zip_source(" in view
    assert "st.file_uploader(" in helper
    assert '"Desde este equipo"' in helper
    assert '"Desde Google Drive"' in helper
    assert "inspect_drive_artifact(temp_path)" in helper
    assert 'inspection.kind == "team_copy"' in helper
    assert "No se incorpora sobre el proyecto que está abierto ahora" in helper
    assert "_simulate_exchange_bundle_path(" in helper


def test_received_team_copy_is_reidentified_automatically_on_first_open() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    assert "activate_received_team_copy(" in source
    assert "Esta copia recibida ya tiene una identidad propia" in source



def test_exchange_stale_entries_are_explained_archivable_and_cleanable() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    assert "Detalles de la vista previa desactualizada" in source
    assert "Incluir paquetes archivados" in source
    assert "Archivar paquete" in source
    assert "Nota sobre por qué archivás este paquete (opcional)" in source
    assert "Restaurar paquete" in source
    assert "Eliminar definitivamente esta entrada" in source
    assert "purge_incoming_bundle" in source
    assert "Confirmo que quiero archivar este paquete de intercambio" not in source


def test_export_success_is_persistent_and_profiles_have_lifecycle_controls() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "export_app.py").read_text(encoding="utf-8")
    for phrase in (
        'st.session_state["export_last_run"]', "Exportación creada correctamente", "Descargar esta exportación",
        "Detalles técnicos de esta exportación", "Cerrar confirmación", "Archivadas",
        "Archivar esta configuración de exportación", "Restaurar esta configuración de exportación",
        "Eliminar definitivamente esta configuración de exportación",
    ):
        assert phrase in source



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
        'section_heading(st, "Exportar corpus")', source.index("def render_export_view")
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
    assert st.session_state["export_notice"] == "Configuración de exportación archivada: Perfil de prueba"
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
    export_app._queue_profile_lifecycle_action(st, action="archive", profile_id="profile-1", confirm_key="confirm-profile-1")
    assert export_app._EXPORT_PENDING_LIFECYCLE_KEY not in st.session_state
    assert st.session_state[export_app._EXPORT_LIFECYCLE_ERROR_KEY] == "Marcá la confirmación antes de archivar esta configuración de exportación."



def test_guided_navigation_keeps_every_section_and_adds_contextual_steps() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    assert "_WORKFLOW_STEPS = (" in source
    for mode in ('"catalog"','"processing"','"work"','"review"','"search"','"semantic"','"authorities"','"graph"','"export"','"exchange"','"admin"'):
        assert mode in source
    assert "Guía de esta sección" in source
    assert "← Ir a la sección anterior del recorrido" not in source
    assert "Ir a la sección siguiente del recorrido →" not in source
    assert "Objetivo de esta sección" in source



def test_administration_uses_clear_spanish_and_hides_restore_command_by_default() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "admin_app.py"
    ).read_text(encoding="utf-8")

    assert 'section_heading(st, "Administrar y recuperar")' in source
    for label in ("Integridad", "Copias de seguridad", "Probar recuperación", "Restaurar", "Autorizaciones de análisis"):
        assert label in source
    assert "Crear copia de seguridad" in source
    assert "Copias de seguridad disponibles" in source
    assert "Copia de seguridad a probar" in source
    assert "Copia de seguridad a restaurar" in source
    assert 'st.expander("Ver comando técnico de restauración")' in source
    assert 'st.form_submit_button("Crear backup"' not in source
    assert 'st.subheader("Autorizaciones registradas para análisis automáticos")' not in source
    assert 'cols = st.columns(3)' in source
    assert 'Versión de la base de datos del proyecto' not in source
    assert 'st.expander("Detalles técnicos de la comprobación", expanded=False)' in source
    assert 'Revisión de la base de datos del proyecto' in source
    assert '"Abrir Productores y responsables"' in source
    assert '"Abrir Búsqueda textual"' in source
    assert '"Abrir Búsqueda semántica"' in source
    assert '"Abrir Historial de exportaciones"' in source
    assert '"Descartar este aviso"' in source
    assert '"Ver avisos descartados (' in source
    assert '"Buscar autorizaciones"' in source
    assert '"Tipo de análisis"' in source
    assert '"Responsable"' in source
    assert '"Origen de la autorización"' in source
    assert '"Alcance de páginas"' in source
    assert '"Cantidad a mostrar"' in source




def test_integrity_navigation_can_open_catalog_roles_without_losing_target_unit() -> None:
    root = Path(__file__).parents[1]
    admin_source = (root / "src/archive_workbench/admin_app.py").read_text(encoding="utf-8")
    catalog_source = (root / "src/archive_workbench/catalog_app.py").read_text(encoding="utf-8")
    assert 'st.session_state["catalog_pending_unit_id"] = issue.archival_unit_id' in admin_source
    assert 'st.session_state["catalog_pending_detail_tab"] = "Productores y responsables"' in admin_source
    assert 'pending_detail_tab = st.session_state.pop("catalog_pending_detail_tab", None)' in catalog_source
    assert '"Productores y responsables"' in catalog_source


def test_export_formats_include_plain_language_explanations() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "export_app.py"
    ).read_text(encoding="utf-8")

    assert '"jsonl": "JSONL · un registro por línea"' in source
    assert '"csv": "CSV · tabla"' in source
    assert source.count("_OUTPUT_FORMAT_LABELS.get") >= 2


def test_literal_search_keeps_basic_decisions_visible_and_preserves_all_filters() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    view = source[source.index("def _render_search_view"):source.index("def _format_exchange_value", source.index("def _render_search_view"))]
    for label in (
        'section_heading(st, "Búsqueda textual")', "Qué querés encontrar", "Cómo combinar las palabras",
        'literal_filters_open = st.toggle(', '"Más filtros"',
        'key="search_rebuild_open"',
        'st.expander("Detalles técnicos del índice", expanded=False)',
        "Qué partes de los registros querés buscar", "Documentos en los que querés buscar",
        "Tipos de bloques de texto", "Estado de revisión de los bloques de texto", "Estado de la página",
        "Categorías de etiqueta presentes", "Incluir bloques de texto eliminados",
        "Incluir partes de palabras", "Máximo de resultados",
        'label_visibility="collapsed"',
    ):
        assert label in view
    assert 'st.expander("Filtros opcionales"' not in view
    assert 'st.expander("Actualizar la búsqueda textual' not in view
    assert 'st.popover("Más filtros")' not in view
    assert "aw-search-filter-width-marker" not in view


def test_catalog_and_processing_use_progressive_task_oriented_hierarchy() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    catalog = (root / "catalog_app.py").read_text(encoding="utf-8")
    processing = (root / "processing_app.py").read_text(encoding="utf-8")
    for label in ("Estado del catálogo", "Unidades del catálogo", "Planilla del catálogo", "Crear una unidad", "Incorporar archivos"):
        assert label in catalog
    assert 'key="catalog_main_task"' in catalog
    assert 'placeholder="Buscar por título, código, descripción o archivo"' in catalog
    assert "Filtros del catálogo" not in catalog
    assert "Resumen de la unidad seleccionada" not in catalog
    for label in (
        '"Estado"',
        '"Preparar / extraer"',
        '"Leer una zona"',
        '"Elegir texto"',
        '"Corregir o agregar"',
        '"Enviar a revisión"',
        '"Historial"',
    ):
        assert label in processing
    assert '"Paso"' in processing
    assert 'key="processing_operation"' in processing
    assert '"Cambiar el identificador de esta lectura"' in processing
    assert '"Crear una nueva versión aunque ya exista una equivalente"' in processing
    assert 'st.toggle(\n                "Más opciones"' not in processing
    assert "Estado de los documentos" not in processing
    assert "Historial de procesamiento" not in processing


def test_semantic_search_separates_plain_language_from_technical_configuration() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "semantic_app.py").read_text(encoding="utf-8")
    assert 'section_heading(st, "Búsqueda semántica")' in source
    assert "Nombre de esta configuración de búsqueda" in source
    assert "Buscar por significado" in source
    assert "Configurar el índice de búsqueda" in source
    assert "Datos técnicos del índice de búsqueda por significado" in source
    assert '"Más opciones de búsqueda semántica"' in source
    assert '"Umbral mínimo de similitud coseno"' in source
    assert 'st.popover("Opciones de búsqueda")' not in source
    assert "Contenido del índice" in source
    assert "Opciones técnicas para construir el índice" in source
    assert "Opciones para acotar esta búsqueda" not in source
    assert "Textos que se incluirán en la búsqueda por significado" not in source
    assert "La similitud coseno ordena los resultados" in source


def test_semantic_search_supports_distribution_traversal_closure_and_similar_passages() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    semantic = (root / "semantic_app.py").read_text(encoding="utf-8")
    review = (root / "review_app.py").read_text(encoding="utf-8")

    for label in (
        'st.expander("Distribución de los resultados", expanded=False)',
        'similitud coseno **{row.score:.3f}**',
        '"Buscar pasajes similares a este resultado"',
        'st.session_state["semantic_search_params"]',
        '"semantic_pending_execute"',
        '"origin": "semantic"',
    ):
        assert label in semantic

    for label in (
        '"Búsqueda semántica" if is_semantic else "Búsqueda textual"',
        'help=f"Cerrar el recorrido de resultados de {search_name}"',
        '"← Resultado anterior"',
        '"Resultado siguiente →"',
        '"Buscar pasajes similares a este resultado"',
        'queue_similar_semantic_search(',
    ):
        assert label in review


def test_review_search_navigation_is_compact_fragment_local_and_supports_selected_block_similarity() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    close_start = source.index("def _close_search_result_navigation")
    close_end = source.index("def _render_search_result_navigation", close_start)
    close_block = source[close_start:close_end]
    assert 'st.session_state["review_search_navigation"] = None' in close_block
    assert "rerun_view(" not in close_block
    assert "rerun_app(" not in close_block

    navigation_start = source.index("def _render_search_result_navigation")
    navigation_end = source.index("def _render_search_distribution", navigation_start)
    navigation_block = source[navigation_start:navigation_end]
    assert '"✕"' in navigation_block
    assert 'type="primary"' in navigation_block
    assert "on_click=_close_search_result_navigation" in navigation_block

    fragment_start = source.index("def _render_review_object_fragment")
    fragment_end = source.index("\n        _render_review_object_fragment()", fragment_start)
    fragment_block = source[fragment_start:fragment_end]
    help_index = fragment_block.index("Seleccioná un marco en la imagen")
    navigation_index = fragment_block.index("_render_search_result_navigation(st)")
    assert navigation_index > help_index
    assert '"Buscar fragmentos similares a este bloque"' in fragment_block
    assert "object_id=selected.object_id" in fragment_block


def test_review_uses_progressive_task_oriented_hierarchy() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    view = source[source.index('section_heading(st, "Revisar documentos")'):]
    for phrase in (
        "Opciones de visualización",
        "Herramientas de edición de las páginas", "Estado de revisión de la página",
        "Deshacer o rehacer cambios", "Revisar texto y estructura de la página",
        "Datos del bloque de texto seleccionado", "Editar texto", "Orden y estructura",
        "Casilleros y campos", "Estado y anotaciones", "Menciones de entidades",
        "Datos adicionales", "Historial general",
    ):
        assert phrase in view
    assert "Cómo funciona la revisión" not in view
    assert "Resumen del documento" not in view
    assert "document_summary" in view
    assert 'key=f"review_undo_panel_{source_key}_{page}"' in view


def test_review_tabs_switch_without_forcing_full_app_rerun() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    marker = 'key="review_object_tabs"'
    window = source[source.index(marker): source.index(marker) + 180]
    assert "rerun_on_change=False" in window


def test_rc26_processing_keeps_archival_path_visible_and_compacts_regional_context() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "processing_app.py").read_text(encoding="utf-8")
    default_row = source[source.index('item = {'): source.index('if detailed_inventory:')]
    assert '"Ruta archivística": row.archival_path' in default_row
    assert 'context_cols = st.columns([2.2, 0.7, 1.4])' in source
    assert 'text_cols = st.columns([1.1, 1.4])' in source
    assert 'help="Lectura parcial guardada para esa página.' in source


def test_all_navigation_surfaces_have_context_help_contracts() -> None:
    package = Path(__file__).parents[1] / "src" / "archive_workbench"

    expected_sections = {
        "Abrir o crear un proyecto",
        "Inicio",
        "Catálogo",
        "Audio y video",
        "Procesar documentos",
        "Organizar trabajo",
        "Revisar documentos",
        "Búsqueda textual",
        "Búsqueda semántica",
        "Entidades y menciones",
        "Explorar relaciones",
        "Exportar corpus",
        "Intercambiar cambios",
        "Administrar y recuperar",
    }
    assert expected_sections <= set(SECTION_HELP)
    assert all(SECTION_HELP[label].strip() for label in expected_sections)

    expected_tab_sets = {
        "launcher_tabs",
        "catalog_detail_tabs",
        "audiovisual_tabs",
        "processing_tabs",
        "work_tabs",
        "review_object_tabs",
        "semantic_tabs",
        "authority_tabs",
        "open_discovery_grouping_tasks",
        "open_discovery_review_modes",
        "graph_tabs",
        "export_tabs",
        "admin_tabs",
    }
    assert expected_tab_sets <= set(TAB_HELP)
    assert all(TAB_HELP[key] and all(text.strip() for text in TAB_HELP[key].values()) for key in expected_tab_sets)

    expected_task_sets = {
        "catalog_main_task",
        "audiovisual_import_method",
        "review_search_surface",
        "authority_main_task",
        "open_discovery_task",
        "export_surface",
        "exchange_main_task",
        "exchange_adoption_step",
        "exchange_common_base_step",
        "review_structure_task",
        "review_form_task",
    }
    assert expected_task_sets <= set(TASK_HELP)

    for name in (
        "processing_app.py",
        "audiovisual_app.py",
        "review_app.py",
        "authority_app.py",
        "catalog_app.py",
        "discovery_app.py",
        "export_app.py",
        "graph_app.py",
        "semantic_app.py",
        "work_app.py",
        "admin_app.py",
    ):
        source = (package / name).read_text(encoding="utf-8")
        assert "contextual_help(" not in source, name


def test_every_tracked_tab_call_supplies_context_help() -> None:
    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    offenders = []
    for path in package.glob("*.py"):
        if path.name == "ui_navigation.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = function.id if isinstance(function, ast.Name) else getattr(function, "attr", None)
            if name != "tracked_tabs":
                continue
            if not any(keyword.arg == "help_by_label" for keyword in node.keywords):
                offenders.append((path.name, node.lineno))
    assert offenders == []


def test_authorities_use_ux04_compact_entity_workspace() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "authority_app.py").read_text(encoding="utf-8")

    for phrase in (
        "_AUTHORITY_TASK_LABELS",
        'placeholder="Buscar nombre, nombre alternativo o historia"',
        'label_visibility="collapsed"',
        '"Tipo"',
        '"Estado de ficha"',
        '"Período"',
        'st.subheader(selected.preferred_name)',
        'with st.popover("Agregar nombre alternativo"',
        '["Ficha", "Menciones", "Relaciones", "Historial"]',
        '"Buscar menciones"',
        '"Roles archivísticos"',
        '"Relaciones analíticas"',
        '"Crear una relación analítica"',
        'st.subheader("Menciones vinculadas")',
        '"Estado de las páginas"',
        'key=f"relation_create_panel_{selected.authority_id}"',
        '_MENTION_STATUS_LABELS.get(mention.status, mention.status)',
    ):
        assert phrase in source

    for removed in (
        'st.header("Entidades y menciones")',
        'st.expander("Qué es una entidad"',
        '"Filtros de entidades"',
        '"Ficha de entidad que querés revisar"',
        '"Resumen de la ficha de entidad seleccionada"',
        '"Elegí qué información de la ficha de entidad seleccionada querés revisar',
        '"Nombres alternativos",',
        '"Archive Workbench busca en los textos revisados el nombre principal',
        '"Completar estos campos no crea la relación.',
        'st.expander("Opciones de búsqueda"',
        '"Alcance de calidad: solo páginas aprobadas."',
        '"Alcance de calidad ampliado:',
        '"Confirmo que esta búsqueda puede incluir páginas',
        '"Por qué esta búsqueda debe incluir páginas',
        "mention.document_title or '[sin título]'",
    ):
        assert removed not in source

    mentions = source[source.index('st.subheader("Menciones vinculadas")'):source.index('with relations_tab:')]
    assert mentions.index('st.subheader("Menciones vinculadas")') < mentions.index('"Buscar menciones"')
    relation_panel = source[source.index('with relations_tab:'):source.index('with history_tab:')]
    assert 'st.toggle(' in relation_panel
    assert 'value=False' in relation_panel



def test_graph_uses_plain_language_and_progressive_details() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "graph_app.py").read_text(encoding="utf-8")
    for phrase in (
        'section_heading(st, "Explorar relaciones")', 'st.toggle(\n        "Configurar mapa",',
        "Menciones de entidades que necesitan una decisión",
        "Otros problemas detectados en las relaciones",
    ):
        assert phrase in source
    for removed in (
        "Qué representa este mapa de relaciones",
        "Cantidad de elementos y relaciones visibles en el mapa",
        "Cómo leer los elementos y las líneas del mapa",
    ):
        assert removed not in source
    assert "relaciones ·" in source
    assert '"family": "Familia"' in source
    assert 'st.popover("Configurar mapa")' not in source


def test_review_object_details_wrap_long_status_values() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    assert "Datos del bloque de texto seleccionado" in source
    assert "Estado de revisión" in source
    assert "st.caption" in source



def test_work_and_export_finish_progressive_plain_language_hierarchy() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    work = (root / "work_app.py").read_text(encoding="utf-8")
    export = (root / "export_app.py").read_text(encoding="utf-8")
    for phrase in ('section_heading(st, "Organizar trabajo")', "Cantidad de tareas por responsable", "Avance de procesamiento y revisión por documento", 'st.popover("Filtrar asignaciones")'):
        assert phrase in work
    assert "Qué se puede organizar en esta sección" not in work
    for phrase in ('section_heading(st, "Exportar corpus")', "Configuración de exportación", "Configurar qué exportar", "Revisar textos que se exportarán", "Crear archivo de exportación", "Historial de exportaciones"):
        assert phrase in export
    assert "Cómo preparar una exportación" not in export
    assert '"Archivadas"' in export


def test_graph_exposes_only_auditable_mention_repairs() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "graph_app.py").read_text(encoding="utf-8")
    assert "Menciones de entidades que necesitan una decisión" in source
    assert "Reubicar menciones seguras" in source
    assert "Fundamento de la decisión" in source
    assert "Marcá la confirmación" in source



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
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    start = source.index('lineage_panel_key = f"exchange_lineage_panel_{selected_bundle}"')
    end = source.index('if selected.status == "stale"', start)
    block = source[start:end]
    assert "Intentar reconstruir el historial compartido" in block
    assert 'with st.form(' in block
    assert "Registrar el historial compartido reconstruido" in block
    assert "recovery_confirmed" in block
    assert 'with st.expander("Buscar evidencia del historial compartido' not in block
    assert "disabled=" not in block


def test_exchange_common_base_forms_are_explicit_and_not_circularly_disabled() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    start = source.index('if exchange_task == "common_base":')
    end = source.index('if exchange_task == "receive":', start)
    block = source[start:end]
    assert "create_common_base_proposal" in block
    assert "accept_common_base_proposal" in block
    assert "finalize_common_base_agreement" in block
    assert "disabled=" not in block
    assert '"1. Iniciar desde esta copia"' in block
    assert '"2. Confirmar en la otra copia"' in block
    assert '"3. Completar en la copia inicial"' in block
    assert "Crear propuesta para la otra copia" in block
    assert "Confirmar coincidencia y devolver acuerdo" in block
    assert "Registrar la base común en esta copia" in block



def test_exchange_state_adoption_forms_are_explicit_and_not_circularly_disabled() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    start = source.index('if exchange_task == "adoption":')
    end = source.index('if exchange_task == "common_base":', start)
    block = source[start:end]
    assert "create_state_adoption_package" in block
    assert "preview_state_adoption" in block
    assert "apply_state_adoption" in block
    assert "disabled=" not in block
    assert "Crear el ZIP con todo el trabajo editable" in block
    assert "Revisar un ZIP completo y reemplazar el trabajo editable de esta copia" in block
    assert "Reemplazar el trabajo editable con el contenido de este ZIP" in block



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


def test_review_layout_panel_exposes_compact_task_selector_and_confirmations() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    for phrase in (
        'structure_task_key = f"review_structure_task_{view.editable_page_id}"',
        '"proposal": "Revisar orden y columnas"',
        '"columns": "Ajustar columnas"',
        '"part": "Asignar parte del documento"',
        '"move": "Mover texto"',
        '"merge": "Combinar textos"',
        '"split": "Dividir texto"',
        '"issues": "Resolver fragmentaciones o duplicados"',
        '"history": "Historial de orden y estructura"',
        "Confirmar columnas y aplicar orden",
        "Crear la columna y asignarle este texto",
        "Combinar secuencia confirmada",
        "Confirmar y archivar duplicado",
    ):
        assert phrase in source
    for obsolete in (
        "1. Revisar la propuesta automática de orden y columnas",
        "2. Ajustar las columnas confirmadas",
        "3. Resolver fragmentaciones y duplicados",
        "4. Historial de Orden y estructura",
    ):
        assert obsolete not in source



def test_ux02_form_structure_uses_one_compact_task_at_a_time() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    source = (root / "review_app.py").read_text(encoding="utf-8")

    for phrase in (
        'form_task_key = f"review_form_task_{view.editable_page_id}"',
        '"candidate": "Revisar casilleros detectados"',
        '"manual": "Agregar un casillero manualmente"',
        '"confirmed": "Revisar casilleros confirmados"',
        '"groups": "Administrar grupos de casilleros"',
        '"history": "Historial de casilleros y grupos"',
        '"Tarea con casilleros y campos"',
        'TASK_HELP["review_form_task"]',
    ):
        assert phrase in source
    for removed in (
        'key=f"form_candidate_panel_{view.editable_page_id}"',
        'key=f"form_manual_control_panel_{view.editable_page_id}"',
        'key=f"form_groups_panel_{view.editable_page_id}"',
        'with st.expander("Historial de estructura de formulario"',
    ):
        assert removed not in source
    assert "páginas que funcionan como formularios" in source


def test_ux02_layout_proposal_hides_long_order_table_in_details() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    proposal_start = source.index('if mode == "proposal":')
    proposal_end = source.index('if mode == "columns":', proposal_start)
    block = source[proposal_start:proposal_end]
    assert 'with st.expander("Ver detalle del orden propuesto", expanded=False):' in block
    assert block.index('render_layout_overlay(') < block.index('Ver detalle del orden propuesto')
    assert block.index('Ver detalle del orden propuesto') < block.index('Confirmar columnas y aplicar orden')


def test_ux02_regional_ocr_keeps_six_visible_steps_and_specific_options() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "processing_app.py"
    ).read_text(encoding="utf-8")
    for phrase in (
        "1. Elegir el documento y la página",
        "2. Marcar una zona en la imagen",
        "3. Describir la zona marcada",
        "4. Agregar la zona a la lista",
        "5. Revisar las zonas marcadas",
        "6. Procesar las zonas marcadas",
        "Cambiar el identificador de esta lectura",
        "Crear una nueva versión aunque ya exista una equivalente",
    ):
        assert phrase in source
    assert '"Más opciones"' not in source
    assert 'key="processing_advanced_open"' not in source


def test_layout_overlay_uses_review_page_field() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    assert "page_number=view.page," in source
    assert "view.page_number" not in source


def test_processing_regional_ocr_is_linear_visual_and_never_auto_selects() -> None:
    root = Path(__file__).parents[1]
    source = (root / "src" / "archive_workbench" / "processing_app.py").read_text(encoding="utf-8")
    for label in (
        '"Documento"',
        '"Página"',
        '"Qué contiene"',
        '"Qué hacer"',
        'Zonas marcadas:',
        '"Procesar las zonas marcadas"',
    ):
        assert label in source
    region_canvas = (root / "src" / "archive_workbench" / "region_canvas.py").read_text(encoding="utf-8")
    assert "Dibujar zona" in region_canvas
    assert "Usar zona marcada" in region_canvas
    assert 'selection_policy="never"' in source
    assert '"Corregir o agregar"' in source
    assert '"Opciones del reconocimiento"' in source
    assert "Corregir texto existente" in source
    assert "Agregar texto faltante" in source
    assert "clickable_review_canvas" in source
    assert "review_canvas_with_drawing" in source



def test_ocr01d_assistant_guidance_update_is_idempotent(tmp_path: Path) -> None:
    from scripts.update_assistant_guidance_0810 import update

    assistant = tmp_path / ".assistant"
    assistant.mkdir()
    for name in (
        "00_LEER_PRIMERO.md",
        "01_INTERACCION_Y_GUIADO.md",
        "05_CRITERIOS_INTERFAZ.md",
    ):
        (assistant / name).write_text(f"# {name}\n", encoding="utf-8")

    first = update(tmp_path)
    second = update(tmp_path)

    assert any(item.startswith("Creado:") for item in first)
    assert all(item.startswith("Sin cambios:") for item in second)
    interaction = (assistant / "01_INTERACCION_Y_GUIADO.md").read_text(encoding="utf-8")
    interface = (assistant / "05_CRITERIOS_INTERFAZ.md").read_text(encoding="utf-8")
    first_doc = (assistant / "00_LEER_PRIMERO.md").read_text(encoding="utf-8")
    public_policy = (assistant / "POLITICA_SITIO_PUBLICO.md").read_text(encoding="utf-8")
    design_policy = (assistant / "LINEAMIENTOS_DE_DISENO_Y_ESCRITURA.md").read_text(encoding="utf-8")
    assert "ruta completa dentro de la interfaz" in interaction
    assert "declarar explícitamente si la imagen se muestra" in interaction
    assert "retomar desde la última acción no persistida" in interaction
    assert "recorrido común debe ser lineal" in interface
    assert "nunca inventa una transcripción" in interface
    assert "orden de lectura" in interface
    assert "POLITICA_SITIO_PUBLICO.md" in first_doc
    assert "archivistas, cientistas sociales" in public_policy
    assert "tutorial completo" in public_policy
    assert "GitHub Pages" in public_policy
    assert "instrumento de investigación" in design_policy
    assert "SaaS genérico" in design_policy

def test_processing_single_selection_survives_widget_state_cleanup() -> None:
    st = _FakeStreamlit()

    _remember_single_widget_state(
        st, key="processing_geometry_mode", value="conservative_dewarp"
    )
    _restore_single_widget_state(
        st,
        key="processing_geometry_mode",
        options=["none", "conservative", "conservative_dewarp"],
        default="none",
    )

    assert st.session_state["processing_geometry_mode"] == "conservative_dewarp"


def test_processing_document_selection_survives_diagnostic_rerun() -> None:
    st = _FakeStreamlit()

    _remember_multi_widget_state(
        st, key="processing_source_keys", values=["curved", "flat"]
    )
    _restore_multi_widget_state(
        st, key="processing_source_keys", options=["curved", "flat"]
    )

    assert st.session_state["processing_source_keys"] == ["curved", "flat"]


def test_processing_document_restore_discards_missing_inventory_entries() -> None:
    st = _FakeStreamlit()
    st.session_state["processing_source_keys__remembered"] = ["curved", "missing"]

    _restore_multi_widget_state(
        st, key="processing_source_keys", options=["curved", "flat"]
    )

    assert st.session_state["processing_source_keys"] == ["curved"]


def test_launcher_preferences_and_catalog_batch_flow_are_exposed_in_ui() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    review = (root / "review_app.py").read_text(encoding="utf-8")
    catalog = (root / "catalog_app.py").read_text(encoding="utf-8")
    for phrase in ("Abrir o crear un proyecto", "Abrir un proyecto existente", "Crear un proyecto nuevo", "Tu nombre", "Paleta de colores de la interfaz", "Guía de esta sección"):
        assert phrase in review
    for phrase in ("Incorporar archivos por lote", "Unidad del catálogo", "Asignar la misma unidad del catálogo a varios archivos de una subcarpeta", "Revisar la estructura permitida del catálogo", "Crear una persona u organización", "Continuar en Procesar documentos"):
        assert phrase in catalog



def test_catalog_move_confirmation_is_not_reactively_disabled_inside_form() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "catalog_app.py").read_text(encoding="utf-8")
    block = source.split('with st.form(f"catalog_move_{unit.id}"', 1)[1].split('latest_revision = revisions[0]', 1)[0]
    assert "Mover esta unidad a la ubicación elegida" in block
    assert "disabled=new_parent == current_parent" not in block
    assert "if move_submit and new_parent == current_parent" in block



def test_user_visible_app_copy_does_not_hardcode_project_data() -> None:
    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    for name in (
        "catalog_app.py",
        "export_app.py",
        "graph_app.py",
        "review_app.py",
    ):
        source = (package / name).read_text(encoding="utf-8")
        assert "project_data" not in source, name


def test_batch_unit_suggestion_accepts_filename_abbreviations_without_writing() -> None:
    from types import SimpleNamespace
    from archive_workbench.catalog_app import _batch_unit_suggestion

    rows = [
        SimpleNamespace(
            title="Administración pública: aspectos fundamentales sobre contrainteligencia. Síntesis de conferencias. Ejemplar 0619",
            path="Archivo / SiCH / Caja / Ejemplar 0619",
            depth=3,
        ),
        SimpleNamespace(
            title="Carpeta con reglamentos",
            path="Archivo / SiCH / Caja / Carpeta con reglamentos",
            depth=3,
        ),
    ]
    assert _batch_unit_suggestion(Path("adm_pub_asp_contr.pdf"), rows).endswith(
        "Ejemplar 0619"
    )
    assert _batch_unit_suggestion(Path("carp_reg.pdf"), rows).endswith(
        "Carpeta con reglamentos"
    )


def test_onboarding_rc3_uses_folder_picker_full_palette_and_safe_preferences() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    source = (root / "review_app.py").read_text(encoding="utf-8")
    picker = (root / "local_picker.py").read_text(encoding="utf-8")

    assert '"Carpeta donde se creará el proyecto"' in source
    assert '"Carpeta del proyecto"' in source
    assert "Elegir la carpeta del proyecto en la computadora" in source
    assert "Elegir en la computadora la carpeta donde se creará el proyecto" in source
    assert 'st.session_state.setdefault(parent_key, str(Path.cwd().resolve()))' in source
    assert '"Nombre de la carpeta del proyecto"' in source
    assert '"--file-selection"' in picker
    assert '"--directory"' in picker

    palette_block = source.split("def _apply_palette", 1)[1].split(
        "def _save_preferences_from_values", 1
    )[0]
    assert "<style>" not in palette_block
    assert "sistema" in palette_block and "temas" in palette_block
    preferences = (root / "user_preferences.py").read_text(encoding="utf-8")
    assert "STREAMLIT_THEME_PRESETS" in preferences
    assert "streamlit_theme_cli_args" in preferences

    save_block = source.split("def _save_preferences_from_values", 1)[1].split(
        "def _stage_review_preferences", 1
    )[0]
    assert 'st.session_state["review_actor"] =' not in save_block
    assert 'st.session_state["review_palette"] =' not in save_block

    launcher_block = source.split("def _render_launcher", 1)[1].split(
        "def _render_preferences", 1
    )[0]
    assert launcher_block.count("_stage_review_preferences(") == 2
    assert 'save_user_preferences(UserPreferences(actor=clean_actor, palette=palette))' in launcher_block


def test_pilot_rc3_home_catalog_and_batch_regressions_are_explicit() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    home = (root / "home_app.py").read_text(encoding="utf-8")
    operational = (root / "operational.py").read_text(encoding="utf-8")
    catalog = (root / "catalog_app.py").read_text(encoding="utf-8")
    graph = (root / "graph_app.py").read_text(encoding="utf-8")
    assert 'metric("Versión de la base"' not in home
    assert "La búsqueda textual todavía no está preparada para este proyecto." in operational
    assert "La búsqueda textual necesita actualizarse porque el contenido cambió" in operational
    assert "Unidades del catálogo" in catalog
    assert "Corregir archivos que no siguen la asignación de su subcarpeta" in catalog
    assert "Aplicar cambios a estas filas" in catalog
    assert "choose_local_directory" in catalog and "choose_local_directory" in graph




def test_catalog_allows_level_change_collection_enablement_and_safe_deletion() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "catalog_app.py").read_text(encoding="utf-8")
    assert '"Habilitar Colección en este proyecto"' in source
    assert '"Tipo de unidad"' in source
    assert '"Cambiar tipo de unidad"' in source
    assert '"Eliminar esta unidad del catálogo"' in source
    assert '"Escribí ELIMINAR para confirmar"' in source
    assert "archival_unit_delete_blockers" in source



def test_global_scroll_persistence_uses_frameless_component_and_stmain() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "ui_navigation.py"
    ).read_text(encoding="utf-8")
    assert "def _view_scroll_keeper_renderer" in source
    assert "st.components.v2.component" in source
    assert "archive-workbench-scroll:" in source
    assert "sessionStorage" in source
    assert 'section[data-testid="stMain"]' in source
    assert "scrollTop" in source
    assert "ResizeObserver" in source
    # Un componente v2 no acepta width=0. La conservación de scroll no necesita
    # fijar dimensiones porque no renderiza contenido visible.
    assert "width=0" not in source
    assert "height=0" not in source
    assert "window.scrollY" not in source
    assert "window.scrollTo" not in source
    assert "mount_view_scroll_keeper(st, view_key=app_mode)" in (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")


def test_custom_palettes_use_streamlit_native_theme_at_launch() -> None:
    preferences = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "user_preferences.py"
    ).read_text(encoding="utf-8")
    cli = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "cli.py"
    ).read_text(encoding="utf-8")
    review = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    assert "STREAMLIT_THEME_PRESETS" in preferences
    for option in (
        '"primaryColor"',
        '"backgroundColor"',
        '"secondaryBackgroundColor"',
        '"textColor"',
        '"borderColor"',
    ):
        assert option in preferences
    assert "streamlit_theme_cli_args(preferences.palette)" in cli
    palette_function = review.split("def _apply_palette", 1)[1].split(
        "def _save_preferences_from_values", 1
    )[0]
    assert "<style>" not in palette_function
    assert "sistema nativo de temas" in review



def test_project_views_require_an_explicit_user_name_before_navigation() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    assert "def _require_reviewer_name" in source
    assert 'st.error("Antes de continuar, escribí tu nombre.' in source
    assert '"Guardar nombre y continuar"' in source
    assert 'st.stop()' in source.split("def _require_reviewer_name", 1)[1].split("def _snippet", 1)[0]
    main_block = source.split("with st.sidebar:", 1)[1].split("app_mode = st.radio(", 1)[0]
    assert "_require_reviewer_name" in main_block


def _rc12_visible_ui_paths() -> list[Path]:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    paths = list(root.glob("*_app.py"))
    paths.extend(
        root / name
        for name in (
            "region_canvas.py",
            "review_canvas.py",
            "audiovisual_review_component.py",
            "graph_canvas.py",
            "local_picker.py",
        )
        if (root / name).exists()
    )
    return sorted(set(paths))


def test_rc12_visible_controls_do_not_use_generic_bare_referents() -> None:
    import ast

    forbidden = {
        "Abrir", "Guardar", "Aplicar", "Confirmar", "Crear", "Eliminar",
        "Mostrar", "Usar", "Actualizar", "Agregar", "Quitar", "Reintentar",
        "Seleccionar", "Cambiar", "Registrar", "Editar", "Cerrar", "Estado",
        "Resultado", "Selección", "Calidad", "Versión", "Candidato",
        "Candidatos", "Sugerencias",
    }
    visible_calls = {
        "button", "form_submit_button", "download_button", "selectbox", "radio",
        "text_input", "text_area", "checkbox", "multiselect", "number_input",
        "file_uploader", "toggle",
    }
    violations: list[str] = []
    for path in _rc12_visible_ui_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in visible_calls or not node.args:
                continue
            value = node.args[0]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                if value.value.strip() in forbidden:
                    violations.append(f"{path.name}:{node.lineno}: {value.value}")
    assert not violations, "Rótulos con referente implícito:\n" + "\n".join(violations)


def test_rc12_removes_flagged_pilot01_interface_phrases() -> None:
    visible_source = "\n".join(path.read_text(encoding="utf-8") for path in _rc12_visible_ui_paths())
    for phrase in (
        "Cada tarjeta resume una parte del trabajo",
        "qué significa cada columna",
        "El botón Abrir te lleva a la sección correspondiente",
        "Definí zonas sobre una página visible y creá una extracción candidata",
        "La corrida no cambia la selección canónica ni la capa editable",
        "Zonas que formarán la candidata",
        "Crear la extracción candidata",
        "Los candidatos son alertas visuales",
        "Registrar casillero manual",
        "Crea sugerencias pendientes usando solamente el diccionario de autoridades del proyecto",
        "No es la pestaña «Historial general»",
        "El servidor vLLM quedará activo para reutilizarse en las próximas corridas",
        "archive-workbench surya-server-stop",
    ):
        assert phrase not in visible_source


def test_rc12_rewrites_the_two_user_reported_implicit_referents() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    home = (root / "home_app.py").read_text(encoding="utf-8")
    catalog = (root / "catalog_app.py").read_text(encoding="utf-8")

    assert 'f"Abrir {item.label}"' in home
    assert 'st.subheader("Estado del proyecto")' in home
    assert "Cada tarjeta resume una etapa del trabajo con el corpus" not in home
    assert 'key="catalog_main_task"' in catalog
    assert 'placeholder="Buscar por título, código, descripción o archivo"' in catalog


def test_rc12_audit_document_is_historical_and_covers_helper_components() -> None:
    audit = (
        Path(__file__).parents[1]
        / "docs"
        / "historico"
        / "actualizaciones"
        / "AUDITORIA_INTERFAZ_RC12_5_PASADAS.txt"
    ).read_text(encoding="utf-8")
    for token in (
        "region_canvas.py",
        "review_canvas.py",
        "audiovisual_review_component.py",
        "graph_canvas.py",
        "local_picker.py",
        "lectura semántica",
        "referente",
        "cinco pasadas",
    ):
        assert token in audit


def test_review_tabs_and_processing_tasks_are_exposed_clearly() -> None:
    root = Path(__file__).parents[1]
    review = (root / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    processing = (root / "src" / "archive_workbench" / "processing_app.py").read_text(encoding="utf-8")

    assert review.index('"Datos adicionales"') < review.index('"Historial general"')
    assert "páginas que funcionan como formularios" in TAB_HELP["review_object_tabs"]["Casilleros y campos"]
    assert "vincular una parte del bloque de texto" in TAB_HELP["review_object_tabs"]["Menciones de entidades"]
    assert "nombres detectados automáticamente" in TAB_HELP["review_object_tabs"]["Menciones de entidades"]
    assert '"Elegir texto"' in processing
    assert '"Leer una zona"' in processing
    assert '"Corregir o agregar"' in processing
    assert '"Enviar a revisión"' in processing
    assert "Corregir texto existente" in processing
    assert "Agregar texto faltante" in processing


def test_rc13_processing_exposes_ordered_steps_and_removes_duplicate_preparation_label() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    processing = (root / "processing_app.py").read_text(encoding="utf-8")
    assert '"1. Preparar imágenes para extraer texto"' in processing
    assert '"2. Extraer texto de las imágenes preparadas"' in processing
    assert 'operation_options = ["prepare", "extract"]' in processing
    assert "row.preprocessing_ready" in processing
    assert '"Preparar páginas para revisión"' not in processing
    assert '"Preparar páginas"' not in processing
    assert "clickable_review_canvas" in processing
    assert "Agregar texto faltante" in processing




def test_rc15_processing_separates_full_page_partial_text_and_bulk_review_tasks() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    processing = (root / "processing_app.py").read_text(encoding="utf-8")
    canvas = (root / "review_canvas.py").read_text(encoding="utf-8")
    navigation = (root / "ui_navigation.py").read_text(encoding="utf-8")

    for phrase in (
        "Elegir texto",
        "Corregir o agregar",
        "Enviar a revisión",
        "Lectura de zona",
        "Dibujar dónde irá el texto nuevo",
        "No se pudo extraer texto porque el documento todavía no tenía imágenes preparadas.",
    ):
        assert phrase in processing or phrase in canvas
    for forbidden in ("texto inicial", "resultado de una zona", "texto obtenido de una zona"):
        assert forbidden not in processing.lower()
    assert "processing_bulk_multi_run_{row.digital_object_id}" in processing
    assert "processing_bulk_multi_run_{multi_source}" not in processing
    assert "review_canvas_with_drawing" in processing
    assert "archive-workbench-scroll:" in navigation
    assert "archive-workbench-scroll-anchor:" not in navigation
    assert "setTriggerValue" not in navigation

def test_rc40_review_bbox_selection_updates_object_inside_local_fragment() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    review_canvas = (root / "review_canvas.py").read_text(encoding="utf-8")
    review_app = (root / "review_app.py").read_text(encoding="utf-8")

    assert "@st.fragment" in review_app
    assert "_render_review_object_fragment" in review_app
    assert "commit_on_click=True" in review_app
    assert "selection_state_key=object_state_key" in review_app
    assert "on_selection_commit_change=on_selection_commit_change" in review_canvas
    assert "if (Boolean(data.commit_selection_on_click))" in review_canvas
    assert "setTriggerValue('selection_commit', state.selected)" in review_canvas
    fragment = review_app[review_app.index("@st.fragment"):review_app.index("_render_review_object_fragment()", review_app.index("@st.fragment")) + len("_render_review_object_fragment()")]
    assert 'key="review_source_key"' not in fragment
    assert 'key="review_page_number"' not in fragment

def test_rc17_review_has_no_second_manual_add_text_path() -> None:
    review = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    assert '"Agregar un bloque de texto"' not in review
    assert "Agregar este bloque de texto" not in review
    assert "Procesar documentos > Corregir o agregar" in review


def test_rc13_removes_reported_generic_negative_disclaimer() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    visible = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*_app.py"))
    assert "Organizar estas tareas no cambia por sí solo" not in visible


def test_rc15_bulk_document_identity_is_stable_when_source_keys_repeat() -> None:
    from types import SimpleNamespace
    from archive_workbench.processing_app import _processing_row_identity, _unique_processing_rows

    rows = [
        SimpleNamespace(digital_object_id="doc-1", source_type="discovery", source_key="same"),
        SimpleNamespace(digital_object_id="doc-1", source_type="catalog", source_key="same"),
        SimpleNamespace(digital_object_id="doc-2", source_type="catalog", source_key="same"),
    ]
    unique = _unique_processing_rows(rows)
    assert [row.digital_object_id for row in unique] == ["doc-1", "doc-2"]
    assert unique[0].source_type == "catalog"
    assert len({_processing_row_identity(row) for row in unique}) == 2


def test_rc20_discovery_review_is_accept_or_discard_with_stable_bulk_and_discarded_tabs() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "discovery_app.py").read_text(encoding="utf-8")
    assert 'options=("accept", "reject")' in source
    assert "Corregir el texto o el tipo antes de aceptar esta referencia" in source
    assert "Aplazar" not in source
    assert "Corregir esta referencia encontrada" not in source
    assert '"Revisar una por una"' in source
    assert '"Trabajar con varias referencias"' in source
    assert '"Referencias descartadas"' in source
    assert "open_discovery_bulk_form_" in source
    assert "st.form_submit_button" in source
    assert "Crear una entidad Sin revisar por cada referencia seleccionada" in source
    assert "Descartar las referencias seleccionadas" in source
    assert "Restaurar esta referencia para revisarla" in source
    assert 'with st.expander(f"Referencias descartadas' not in source
    bulk_form = source[source.index('with st.form(\n                f"open_discovery_bulk_form_'):source.index('if bulk_create_submit or bulk_reject_submit:')]
    assert "st.multiselect(" in bulk_form
    assert "st.checkbox(" in bulk_form
    assert bulk_form.count("st.form_submit_button(") == 2
    assert "Crear una entidad Sin revisar por cada referencia seleccionada" in bulk_form
    assert "Descartar las referencias seleccionadas" in bulk_form
    assert "disabled=" not in bulk_form
    assert "Buscar referencias que podrían corresponder al mismo referente" in source
    assert "Actualizar referencias después de corregir el texto" in source
    assert 'limit=None' in source
    assert '"Cuántas referencias mostrar"' in source
    assert 'options=("100", "250", "500", "1000", "Todas")' in source
    assert "index=2" in source
    assert 'f"Mostrando {len(active_candidates):,} de {len(active_candidates_all):,} referencias pendientes"' in source
    assert 'f"Mostrando {len(rejected_candidates):,} de {len(rejected_candidates_all):,} referencias descartadas"' in source
    assert '"Obra / publicación"' in source
    assert "Actualizar esta configuración a {current_label}" in source
    assert "reglas históricas" in source
    assert "Las búsquedas históricas siguen disponibles" in source
    assert "_discovery_rules_label(run_map[value].provider_key, run_map[value].provider_version)" in source


def test_rc19_authority_relations_show_catalog_roles_read_only() -> None:
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "authority_app.py").read_text(encoding="utf-8")
    assert 'relation_kinds=("analytical", "producer", "manager")' in source
    assert '"Roles archivísticos"' in source
    assert "Se registran y modifican desde Catálogo" in source
    assert "en Entidades y menciones son de solo lectura" in source
    assert "acá son de solo lectura" not in source
    assert "Crear una relación analítica" in source



def test_rc60_final_pilot01e_audit_keeps_technical_identifiers_secondary() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    catalog = (root / "catalog_app.py").read_text(encoding="utf-8")
    processing = (root / "processing_app.py").read_text(encoding="utf-8")
    export = (root / "export_app.py").read_text(encoding="utf-8")
    admin = (root / "admin_app.py").read_text(encoding="utf-8")

    assert " obj." not in catalog
    assert "contenidos digitales" in catalog
    assert "desde acá" not in catalog
    assert "elegí acá" not in catalog

    execute_batch = processing.split("def _execute_batch(", 1)[1].split("def _open_review", 1)[0]
    assert "Procesando **{source_key}**" not in execute_batch
    assert "source_labels" in execute_batch
    label_helper = processing.split("def _processing_document_labels", 1)[1].split("def _bbox_geometry", 1)[0]
    assert "referencia {row.source_key}" not in label_helper
    assert "documento {row_id}" not in label_helper

    result_block = export.split("def _render_export_result", 1)[1].split("def _render_profile_editor", 1)[0]
    assert "Detalles técnicos de esta exportación" in result_block
    assert "Descargar esta exportación" in result_block
    assert 'st.caption(f"SHA-256:' not in result_block

    assert "Copia de seguridad creada correctamente." in admin
    assert "Detalles técnicos de la copia de seguridad" in admin
    assert "La copia de seguridad está íntegra y puede usarse para una recuperación." in admin


def test_catalog_unit_navigation_exposes_hierarchy_and_preserves_ancestors() -> None:
    from types import SimpleNamespace
    from archive_workbench.catalog_app import (
        _catalog_descendant_ids,
        _catalog_tree_include_ids,
    )

    rows = [
        SimpleNamespace(id="root", parent_id=None),
        SimpleNamespace(id="series", parent_id="root"),
        SimpleNamespace(id="file", parent_id="series"),
        SimpleNamespace(id="other", parent_id="root"),
    ]
    assert _catalog_tree_include_ids(rows, {"file"}) == {"root", "series", "file"}
    assert _catalog_descendant_ids(rows, "root") == {"series", "file", "other"}
    assert _catalog_descendant_ids(rows, "series") == {"file"}

    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "catalog_app.py"
    ).read_text(encoding="utf-8")
    assert "Catálogo y contexto de custodia" in source
    assert "Abrí las ramas y seleccioná la unidad directamente en el árbol" in source
    assert "Repositorio o contexto de custodia" in source
    assert "Conjunto documental" in source
    assert "no convierte al repositorio en un nivel interno del fondo o la colección" in source
    assert '"Mover esta unidad dentro de"' not in source
    assert "catalog_tree_select(" in source


def test_rc34_catalog_uses_browser_local_explorer_tree_and_not_button_stack() -> None:
    tree = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "catalog_tree.py"
    ).read_text(encoding="utf-8")
    catalog = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "catalog_app.py"
    ).read_text(encoding="utf-8")
    assert "archive_workbench_catalog_tree" in tree
    assert "sessionStorage" in tree
    assert "aw-tree" in tree
    assert "aw-toggle" in tree
    assert "setTriggerValue('selection_commit'" in tree
    # Abrir/cerrar ramas es estado local del navegador y no comunica triggers.
    toggle_block = tree[tree.index("toggle.onclick"):tree.index("label.onclick")]
    assert "setTriggerValue" not in toggle_block
    assert "catalog_tree_select(" in catalog
    assert "_render_catalog_tree_selector" not in catalog
    assert 'type="primary" if row.id == selected_id' not in catalog


def test_rc34_all_streamlit_date_inputs_have_explicit_bounds() -> None:
    import ast

    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    calls = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "date_input":
                continue
            keywords = {item.arg for item in node.keywords if item.arg}
            calls.append((path.name, node.lineno, keywords))
    assert calls
    missing = [f"{name}:{line}" for name, line, keys in calls if not {"min_value", "max_value"} <= keys]
    assert missing == []


def test_rc40_review_navigation_has_local_fragment_and_no_failed_generation_strategy() -> None:
    root = Path(__file__).parents[1]
    review_source = (root / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    canvas_source = (root / "src" / "archive_workbench" / "review_canvas.py").read_text(encoding="utf-8")
    authority_source = (root / "src" / "archive_workbench" / "authority_app.py").read_text(encoding="utf-8")

    assert 'review_navigation_generation' not in review_source
    assert 'review_context_source_key' not in review_source
    assert 'review_context_page_number' not in review_source
    assert 'key="review_source_key"' in review_source
    assert 'key="review_page_number"' in review_source
    assert 'review_page_source' in review_source
    assert 'commit_on_click=True' in review_source
    assert '@st.fragment' in review_source
    assert 'if commit_on_click and selection_state_key:' in canvas_source

    candidate_start = authority_source.index('"Abrir este fragmento en Revisar documentos"')
    candidate_block = authority_source[candidate_start:candidate_start + 850]
    assert 'request_app_view(' in candidate_block
    assert 'rerun_app(st)' in candidate_block

def test_rc34_catalog_roles_offer_explicit_confirmed_deletion() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "catalog_app.py"
    ).read_text(encoding="utf-8")
    assert '"Eliminar vínculo"' in source
    assert "Confirmo que este vínculo fue registrado por error" in source
    assert "delete_entity_relation(" in source
    assert "No equivale a marcarlo Inactivo" in source


def test_literal_search_supports_kwic_distribution_and_result_traversal() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")

    for label in (
        'st.expander("Distribución de los resultados", expanded=False)',
        'key="review_search_result_view"',
        '"Tarjetas"',
        '"Concordancias"',
        '"← Resultado anterior"',
        '"Resultado siguiente →"',
        'f"Volver a {search_name}"',
        '"Búsqueda textual"',
        'st.session_state["review_search_navigation"]',
        "saved_params = st.session_state.get(\"review_search_params\")",
    ):
        assert label in source

    help_source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "ui_help.py"
    ).read_text(encoding="utf-8")
    assert '"review_search_result_view"' in help_source
    assert "Alinea cada aparición encontrada" in help_source


def test_audiovisual_export_uses_configure_preview_create_history_flow() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "export_app.py"
    ).read_text(encoding="utf-8")
    start = source.index("def _render_audiovisual_export_view")
    end = source.index("def render_export_view", start)
    view = source[start:end]
    for phrase in (
        "Configurar qué exportar",
        "Revisar textos que se exportarán",
        "Crear archivo de exportación",
        "Historial de exportaciones",
        "Audios y videos cuyas transcripciones querés exportar",
        "Qué versiones de las transcripciones querés incluir",
        "Qué versión del texto de cada segmento querés exportar",
        "Estado de revisión de los segmentos que querés incluir",
        "Nombre o ruta del archivo dentro del proyecto",
        "Crear archivo con las transcripciones seleccionadas",
        "run_audiovisual_export",
    ):
        assert phrase in view
    assert "Descargar las transcripciones de audio y video" not in view




def test_exchange_view_keeps_reactive_controls_out_of_expanders() -> None:
    import ast

    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_render_exchange_view"
    )
    reactive = {
        "button",
        "checkbox",
        "file_uploader",
        "form",
        "form_submit_button",
        "multiselect",
        "number_input",
        "radio",
        "selectbox",
        "text_area",
        "text_input",
        "toggle",
    }
    violations: list[tuple[int, str]] = []
    for node in ast.walk(target):
        if not isinstance(node, ast.With):
            continue
        is_expander = any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "expander"
            for item in node.items
        )
        if not is_expander:
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in reactive
            ):
                violations.append((child.lineno, child.func.attr))
    assert not violations, f"Controles reactivos dentro de expanders de intercambio: {violations}"


def test_exchange_ui_rc56_integrates_transport_and_uses_progressive_disclosure() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py"
    ).read_text(encoding="utf-8")
    exchange = source[
        source.index("def _render_exchange_view") : source.index(
            "def main()", source.index("def _render_exchange_view")
        )
    ]
    receive_source = source[
        source.index("def _render_receive_zip_source") : source.index(
            "def _render_exchange_advanced_tools",
            source.index("def _render_receive_zip_source"),
        )
    ]

    assert '"more": "Más opciones"' not in exchange
    assert "Opción secundaria" not in exchange
    assert 'key="exchange_receive_source"' in receive_source
    assert '"local": "Desde este equipo"' in receive_source
    assert '"drive": "Desde Google Drive"' in receive_source
    assert "Google Drive se usa sólo para trasladar ZIP" not in source
    assert "Abrir otro ZIP recibido" in exchange
    assert 'archive_panel_key = f"exchange_archive_panel_{selected_bundle}"' in exchange
    assert "Nota sobre por qué archivás este paquete (opcional)" in exchange
    assert "Confirmo que quiero archivar este paquete de intercambio" not in exchange
    assert 'with st.expander("Buscar evidencia del historial compartido' not in exchange
    assert '"Diferencia que querés revisar"' in exchange
    assert 'with st.expander(\n                f"Evento' not in exchange
    assert 'st.expander("Detalles del paquete y la comparación", expanded=False)' in exchange
    assert "Paquete aplicado:" not in exchange
    assert "_exchange_apply_message(result)" in exchange
    archive_button = exchange.index('"Archivar paquete"')
    archive_note = exchange.index('"Nota sobre por qué archivás este paquete (opcional)"')
    assert archive_button < archive_note
    assert 'st.session_state[archive_panel_key] = True' in exchange[archive_button:archive_note]
    assert '"Resolver un problema entre copias"' in exchange
    assert '"Reconectar dos copias con el mismo trabajo editable"' in source
    assert 'st.session_state["exchange_recovery_mode"] = True' in exchange
    assert '"Volver a Recibir cambios"' in exchange




def test_local_file_picker_supports_multiple_files_and_deduplicates(monkeypatch, tmp_path: Path) -> None:
    from archive_workbench.local_picker import choose_local_files
    import archive_workbench.local_picker as picker

    first = tmp_path / "uno.wav"
    second = tmp_path / "dos.mp4"
    first.write_bytes(b"a")
    second.write_bytes(b"b")

    monkeypatch.setattr(picker.shutil, "which", lambda _name: "/usr/bin/zenity")
    monkeypatch.setattr(
        picker.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=f"{first}\n{second}\n{first}\n", stderr=""
        ),
    )

    selected, error = choose_local_files(
        tmp_path,
        title="Elegir audio o video",
        extensions=[".wav", ".mp4"],
    )
    assert error is None
    assert selected == [first.resolve(), second.resolve()]


def test_all_streamlit_expanders_are_informational_only() -> None:
    import ast

    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    reactive = {
        "button",
        "checkbox",
        "data_editor",
        "date_input",
        "file_uploader",
        "form",
        "form_submit_button",
        "multiselect",
        "number_input",
        "radio",
        "selectbox",
        "text_area",
        "text_input",
        "toggle",
    }
    violations: list[tuple[str, int, int, str]] = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            is_expander = any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "expander"
                for item in node.items
            )
            if not is_expander:
                continue
            for child in ast.walk(node):
                if not (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr in reactive
                ):
                    continue
                disabled = next(
                    (keyword.value for keyword in child.keywords if keyword.arg == "disabled"),
                    None,
                )
                if isinstance(disabled, ast.Constant) and disabled.value is True:
                    continue
                violations.append(
                    (path.name, node.lineno, child.lineno, child.func.attr)
                )

    assert violations == []


def test_all_tracked_tabs_use_passive_navigation() -> None:
    import ast

    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    helper = (package / "ui_navigation.py").read_text(encoding="utf-8")
    assert "rerun_on_change: bool = False" in helper

    violations: list[tuple[str, int]] = []
    for path in package.glob("*.py"):
        if path.name == "ui_navigation.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = function.id if isinstance(function, ast.Name) else getattr(function, "attr", None)
            if name != "tracked_tabs":
                continue
            keyword = next(
                (item.value for item in node.keywords if item.arg == "rerun_on_change"),
                None,
            )
            if isinstance(keyword, ast.Constant) and keyword.value is True:
                violations.append((path.name, node.lineno))

    assert violations == []


def test_forms_do_not_disable_submit_from_widgets_inside_the_same_form() -> None:
    import ast

    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    widget_calls = {
        "checkbox",
        "date_input",
        "multiselect",
        "number_input",
        "radio",
        "selectbox",
        "text_area",
        "text_input",
        "toggle",
    }
    violations: list[tuple[str, int, str]] = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            is_form = any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "form"
                for item in node.items
            )
            if not is_form:
                continue
            form_widget_names: set[str] = set()
            for child in ast.walk(node):
                if not isinstance(child, (ast.Assign, ast.AnnAssign)):
                    continue
                value = child.value
                if not (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr in widget_calls
                ):
                    continue
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        form_widget_names.add(target.id)
            for child in ast.walk(node):
                if not (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "form_submit_button"
                ):
                    continue
                disabled = next(
                    (keyword.value for keyword in child.keywords if keyword.arg == "disabled"),
                    None,
                )
                if disabled is None:
                    continue
                used_names = {
                    item.id for item in ast.walk(disabled) if isinstance(item, ast.Name)
                }
                for name in sorted(used_names & form_widget_names):
                    violations.append((path.name, child.lineno, name))

    assert violations == []



def test_form_toggles_do_not_control_reactive_content_inside_the_same_form() -> None:
    import ast

    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    violations: list[tuple[str, int, int, str]] = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            is_form = any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "form"
                for item in node.items
            )
            if not is_form:
                continue
            toggle_names: set[str] = set()
            for child in ast.walk(node):
                if not isinstance(child, (ast.Assign, ast.AnnAssign)):
                    continue
                value = child.value
                if not (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "toggle"
                ):
                    continue
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                toggle_names.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )
            for child in ast.walk(node):
                if not isinstance(child, ast.If):
                    continue
                used_names = {
                    item.id for item in ast.walk(child.test) if isinstance(item, ast.Name)
                }
                for name in sorted(used_names & toggle_names):
                    violations.append((path.name, node.lineno, child.lineno, name))

    assert violations == []


def test_rc64_streamlit_panels_keep_required_state_when_closed() -> None:
    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    graph = (package / "graph_app.py").read_text(encoding="utf-8")
    review = (package / "review_app.py").read_text(encoding="utf-8")
    export = (package / "export_app.py").read_text(encoding="utf-8")
    semantic = (package / "semantic_app.py").read_text(encoding="utf-8")

    assert 'st.session_state["graph_applied_filters"] = applied_graph_filters' in graph
    assert 'edge_types=tuple(applied_graph_filters["edge_types"])' in graph
    assert 'edge_types=tuple(edge_types)' not in graph

    assert 'key=f"review_display_options_open_{source_key}_{page}"' in review
    assert 'key=f"review_page_tools_open_{source_key}_{page}"' in review
    assert 'key=f"review_page_state_open_{source_key}_{page}"' in review
    assert 'show_boxes = bool(' in review
    assert 'include_deleted = bool(' in review
    search_view = review[
        review.index("def _render_search_view") : review.index(
            "def _format_exchange_value", review.index("def _render_search_view")
        )
    ]
    assert search_view.index("fields = saved_fields") < search_view.index(
        'with st.form("search_corpus_form"'
    )
    assert search_view.index('literal_filters_open = st.toggle(') < search_view.index(
        'with st.form("search_corpus_form"'
    )

    assert "from pathlib import Path" in export
    assert export.index("temporal_enabled = default_temporal_enabled") < export.index(
        "with st.form(form_key"
    )
    assert export.index("temporal_filter_open = st.toggle(") < export.index(
        "with st.form(form_key"
    )
    assert export.index("separator_options_open = st.toggle(") < export.index(
        "with st.form(form_key"
    )

    assert semantic.index("model_name = values.model_name") < semantic.index(
        'with st.form("semantic_profile_form"'
    )
    assert semantic.index('key="semantic_profile_build_options_open"') < semantic.index(
        'with st.form("semantic_profile_form"'
    )
    assert semantic.index('build_device = str(') < semantic.index(
        'if technical_build_options_open:',
        semantic.index('key="semantic_index_build_options_open"'),
    )

def test_audiovisual_annotation_requires_explicit_button() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "archive_workbench"
        / "audiovisual_review_component.py"
    ).read_text(encoding="utf-8")
    assert "noteButton.onclick = addNote" in source
    assert "noteInput.onkeydown" not in source
    assert "event.key === 'Enter'" not in source[source.index("const addNote"):source.index("return () =>", source.index("const addNote"))]


def test_widget_keys_changed_after_render_use_pending_state() -> None:
    import ast

    package = Path(__file__).parents[1] / "src" / "archive_workbench"
    widget_calls = {
        "checkbox",
        "date_input",
        "multiselect",
        "number_input",
        "radio",
        "selectbox",
        "tabs",
        "text_area",
        "text_input",
        "toggle",
    }
    allowed_mutually_exclusive = {
        ("review_app.py", "_render_exchange_view", "exchange_main_task"),
        ("audiovisual_app.py", "_render_transcription_workspace", "av_media_id"),
    }
    violations: list[tuple[str, str, str, int]] = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]:
            widget_lines: dict[str, list[int]] = {}
            for node in ast.walk(function):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in widget_calls
                ):
                    continue
                key = next((item.value for item in node.keywords if item.arg == "key"), None)
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    widget_lines.setdefault(key.value, []).append(node.lineno)
            for node in ast.walk(function):
                if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "session_state"
                    ):
                        continue
                    key = target.slice
                    if not (
                        isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                        and key.value in widget_lines
                        and any(line < node.lineno for line in widget_lines[key.value])
                    ):
                        continue
                    item = (path.name, function.name, key.value)
                    if item not in allowed_mutually_exclusive:
                        violations.append((*item, node.lineno))

    assert violations == []
    discovery = (package / "discovery_app.py").read_text(encoding="utf-8")
    assert 'open_discovery_profile_selected__pending' in discovery
    assert 'st.session_state["open_discovery_profile_selected"] = saved.id' not in discovery


def test_managed_distribution_uses_host_visible_workspace_instead_of_native_pickers() -> None:
    root = Path(__file__).parents[1]
    review_source = (root / "src" / "archive_workbench" / "review_app.py").read_text(
        encoding="utf-8"
    )
    catalog_source = (root / "src" / "archive_workbench" / "catalog_app.py").read_text(
        encoding="utf-8"
    )
    audiovisual_source = (root / "src" / "archive_workbench" / "audiovisual_app.py").read_text(
        encoding="utf-8"
    )
    graph_source = (root / "src" / "archive_workbench" / "graph_app.py").read_text(
        encoding="utf-8"
    )

    assert "workspace = managed_workspace()" in review_source
    assert "ArchiveWorkbenchData/Projects" in review_source
    assert '"Proyecto que querés abrir"' in review_source
    assert "workspace.projects" in review_source
    assert "launcher_choose_existing_project" in review_source
    assert "if workspace is not None:" in review_source

    assert "ArchiveWorkbenchData/Imports/Documents" in catalog_source
    assert "workspace.document_imports" in catalog_source
    assert "if managed_workspace() is None:" in catalog_source

    assert "ArchiveWorkbenchData/Imports/AudioVideo" in audiovisual_source
    assert "workspace.audiovisual_imports" in audiovisual_source
    assert '"Archivos de audio o video que querés incorporar"' in audiovisual_source
    assert "_managed_audiovisual_import_paths" in audiovisual_source

    assert "if managed_workspace() is None:" in graph_source
    assert "workspace_display_path(target)" in graph_source
