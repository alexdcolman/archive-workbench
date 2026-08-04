from pathlib import Path


ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"
HISTORICAL_TECH = DOCS / "historico" / "decisiones_tecnicas"
HISTORICAL_UPDATES = DOCS / "historico" / "actualizaciones"
OPERATIVE = DOCS / "operativos"


def test_docs_root_is_clean_and_operational_documents_are_unique() -> None:
    assert sorted(path.name for path in DOCS.iterdir() if path.is_file()) == [
        "HISTORIAL_DE_CAMBIOS.md"
    ]
    assert sorted(path.name for path in OPERATIVE.glob("*.md")) == [
        "ACTUALIZACION_ACTUAL.md",
        "ESTRATEGIA_DE_PRUEBAS.md",
        "GUIA_PRUEBA_PILOTO.md",
        "IMPLEMENTACIONES_REALIZADAS.md",
        "PENDIENTES_ACTIVOS.md",
    ]
    assert len(list(DOCS.rglob("PENDIENTES_ACTIVOS.md"))) == 1
    assert len(list(DOCS.rglob("IMPLEMENTACIONES_REALIZADAS.md"))) == 1
    assert not list(OPERATIVE.glob("*0.*.md"))


def test_assistant_continuity_documents_exist_and_define_read_order() -> None:
    assistant = ROOT / ".assistant"
    gitignore_entries = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert ".assistant/" in gitignore_entries
    if not assistant.is_dir():
        return

    required = {
        "00_LEER_PRIMERO.md",
        "01_INTERACCION_Y_GUIADO.md",
        "02_POLITICA_DOCUMENTAL.md",
        "03_POLITICA_DE_PRUEBAS.md",
        "04_CONTINUIDAD_DEL_PROYECTO.md",
        "05_CRITERIOS_INTERFAZ.md",
        "05_FORMULARIOS_STREAMLIT.md",
        "06_RELEVO_NUEVA_CONVERSACION.md",
        "07_SEGURIDAD_ARCHIVOS_Y_REPOSITORIO.md",
    }
    documents = sorted(path.name for path in assistant.glob("*.md"))
    assert required.issubset(documents)

    first = (assistant / "00_LEER_PRIMERO.md").read_text(encoding="utf-8")
    for name in documents:
        assert f".assistant/{name}" in first
    assert "Orden obligatorio de lectura" in first
    assert "docs/operativos/PENDIENTES_ACTIVOS.md" in first
    assert "No volver a presentar como pendiente" in first


def test_active_pending_ledger_has_index_and_recovers_all_major_lines() -> None:
    text = (OPERATIVE / "PENDIENTES_ACTIVOS.md").read_text(encoding="utf-8")
    assert "## Índice" in text
    for item in (
        "DISC-02 — Importación de diccionarios",
        "CAT-02 — Entidades productoras y gestoras",
        "GRAPH-02 — Estructura archivística, documentos y partes",
        "AV-01 — Registro audiovisual local y transcripción",
        "AV-02 — Plugin opcional de descarga desde YouTube",
        "AI-01 — Herramientas CLI opcionales con LLM",
        "AI-02 — Sistema RAG trazable",
        "OPS-01 — Imagen Docker",
        "INT-01 — Integración opcional con Google Drive",
    ):
        assert item in text
    assert "SEM-01 — Calibración reproducible de búsqueda semántica" not in text
    assert "GRAPH-01 — Grafo sin colisiones" not in text
    assert "QA-01 — Control estático y tipado" in text
    assert "OCR-02" not in text
    assert "post-release" in text.lower()
    assert "BUG-01 — Duplicación visual al archivar un perfil" not in text
    assert "UX-01 — Simplificación de la interfaz" not in text
    assert "DATA-01 — Reparación asistida" not in text
    assert "DATA-02 — Control de calidad antes de todo análisis automático" not in text
    assert "CAT-01 — Plantillas distribuibles de catálogo" not in text
    assert "EX-01 — Recuperación asistida de linaje" not in text
    assert "DISC-01 — Descubrimiento abierto" not in text
    assert "DISC-01D" not in text


def test_implemented_ledger_separates_closed_work_from_active_pending() -> None:
    text = (OPERATIVE / "IMPLEMENTACIONES_REALIZADAS.md").read_text(encoding="utf-8")
    assert "Migración 0027" in text
    assert "Resuelta y validada en 0.49.1" in text
    assert "tres rebases sucesivos" in text
    assert "Administración de perfiles" in text or "archivar, restaurar y eliminar perfiles" in text
    assert "Organización documental" in text
    assert "Implementada en 0.50.0" in text
    assert "Ciclo de vida visual de perfiles de exportación" in text
    assert "Resuelto y validado manualmente" in text
    assert "Orientación y lenguaje claro — fase 1, 0.51.0" in text
    assert "Recorrido guiado y lenguaje claro — fase 2, 0.52.0" in text
    assert "Búsquedas comprensibles — fase 3, 0.53.0" in text
    assert "Catálogo y procesamiento más legibles — fase 4, 0.54.0" in text
    assert "Revisión, entidades y relaciones más legibles — fase 5, 0.55.0" in text
    assert "Legibilidad final de datos, trabajo y exportación — fase 6, 0.56.0" in text
    assert "UX-01 queda cerrado" in text
    assert "Reparación auditable de menciones" in text
    assert "repair_relocation" in text
    assert "Resolución de menciones sin entidad — fase 2, 0.58.0" in text
    assert "Resolución de menciones duplicadas — fase 3, 0.59.0" in text
    assert "Resolución manual de ubicaciones — fase 4, 0.60.0" in text
    assert "Reconciliación entre fila e historial — fase 5, 0.61.0" in text
    assert "Conjuntos coincidentes y reubicaciones agrupadas — fase 6, 0.62.0" in text
    assert "Validada manualmente en 0.62.1" in text
    assert "DATA-01 queda cerrado" in text
    assert "Política común de alcance automático — fase 1, 0.63.0" in text
    assert "Política común, obligatoria y auditable — fase 2, 0.64.0" in text
    assert "implementación funcional de `DATA-02` quedó completa" in text
    assert "Validada manualmente en 0.64.1" in text
    assert "DATA-02` queda cerrado" in text
    assert "0034_automatic_analysis_authorizations" in text
    assert "EX-01 queda cerrado en 0.68.1" in text
    assert "project_data" in text and "pruebas OCR" in text
    assert "DISC-01D — evaluación reproducible" in text
    assert "DISC-01` queda cerrado" in text
    assert "Calibración reproducible de búsqueda semántica — SEM-01, 0.74.0" in text
    assert "Grafo sin colisiones — GRAPH-01, 0.74.0" in text
    assert "Validada en 0.74.0" in text
    assert "Validado manualmente en 0.74.0" in text
    assert "Decisión de alcance sobre duplicados y copias — OCR-02, 0.74.0" in text
    assert "CAT-01 — exportación, simulación e importación XLSX — 0.75.0" in text
    assert "Corrección 0.75.1" in text
    assert "Plantillas distribuibles CAT-01 | Implementadas en 0.75.0 y validadas en 0.75.1" in text
    assert "Validada manualmente en 0.75.1" in text
    assert "155 filas trazables" in text


def test_streamlit_form_policy_prevents_circular_disabled_buttons() -> None:
    assistant = ROOT / ".assistant"
    if not assistant.is_dir():
        return
    text = (assistant / "05_FORMULARIOS_STREAMLIT.md").read_text(encoding="utf-8")
    tests_policy = (assistant / "03_POLITICA_DE_PRUEBAS.md").read_text(encoding="utf-8")
    first = (assistant / "00_LEER_PRIMERO.md").read_text(encoding="utf-8")

    assert "no provocan un nuevo render" in text
    assert "nunca se debe calcular el estado `disabled`" in text
    assert "validar todas las precondiciones después del envío" in text
    assert "ausencia de paneles duplicados" in text
    assert ".assistant/05_FORMULARIOS_STREAMLIT.md" in tests_policy
    assert ".assistant/05_FORMULARIOS_STREAMLIT.md" in first
    implemented = (
        ROOT / "docs" / "operativos" / "IMPLEMENTACIONES_REALIZADAS.md"
    ).read_text(encoding="utf-8")
    pending = (
        ROOT / "docs" / "operativos" / "PENDIENTES_ACTIVOS.md"
    ).read_text(encoding="utf-8")
    interaction = (assistant / "01_INTERACCION_Y_GUIADO.md").read_text(encoding="utf-8")
    assert "Regla permanente de interfaz" in first
    assert "Principio permanente para toda modificación" in implemented
    assert "UX-02" in pending and "complejidad acumulada" in pending
    assert "UX-03" not in pending
    assert "UX-03" in implemented and "recorridos separados" in implemented
    assert "un solo bloque ejecutable" in tests_policy
    assert "un único bloque de comandos" in interaction



def test_interface_policy_requires_persistent_interactive_panels() -> None:
    assistant = ROOT / ".assistant"
    if not assistant.is_dir():
        return
    text = (assistant / "05_CRITERIOS_INTERFAZ.md").read_text(encoding="utf-8")
    first = (assistant / "00_LEER_PRIMERO.md").read_text(encoding="utf-8")
    tests_policy = (assistant / "03_POLITICA_DE_PRUEBAS.md").read_text(encoding="utf-8")

    assert "Paneles interactivos y reruns" in text
    assert "debe conservar su estado de apertura" in text
    assert "no colocar un flujo interactivo dentro de un `st.expander`" in text
    assert "cerrado por defecto" in text
    assert "05_CRITERIOS_INTERFAZ.md" in first
    assert "persistencia del panel durante reruns" in tests_policy


def test_history_map_is_concise_and_references_historical_detail() -> None:
    text = (DOCS / "HISTORIAL_DE_CAMBIOS.md").read_text(encoding="utf-8")
    assert "## Documentación vigente" in text
    assert "### 0.75.1" in text
    assert "`CAT-01` queda cerrado" in text
    assert "### 0.75.0" in text
    assert "### 0.74.0" in text
    assert "### 0.73.0" in text
    assert "### 0.72.0" in text
    assert "### 0.71.2" in text
    assert "### 0.71.1" in text
    assert "### 0.70.2" in text
    assert "### 0.70.1" in text
    assert "### 0.70.0" in text
    assert "### 0.69.0" in text
    assert "### 0.68.1" in text
    assert "### 0.68.0" in text
    assert "### 0.67.0" in text
    assert "### 0.66.0" in text
    assert "### 0.65.0" in text
    assert "### 0.64.2" in text
    assert "### 0.64.1" in text
    assert "### 0.64.0" in text
    assert "### 0.63.0" in text
    assert "### 0.62.1" in text
    assert "### 0.62.0" in text
    assert "### 0.61.0" in text
    assert "### 0.60.0" in text
    assert "### 0.59.0" in text
    assert "### 0.58.0" in text
    assert "### 0.57.0" in text
    assert "### 0.56.0" in text
    assert "### 0.55.0" in text
    assert "### 0.54.0" in text
    assert "### 0.53.0" in text
    assert "### 0.52.0" in text
    assert "### 0.51.0" in text
    assert "### 0.50.3" in text
    assert "### 0.50.1" in text
    assert "### 0.50.0" in text
    assert "historico/actualizaciones" in text
    assert "historico/decisiones_tecnicas" in text
    assert "CHANGELOG.md" in text
    assert text.index("### 0.75.1") < text.index("### 0.75.0")
    assert text.index("### 0.75.0") < text.index("### 0.74.0")
    assert text.index("### 0.74.0") < text.index("### 0.73.0")
    assert text.index("### 0.73.0") < text.index("### 0.72.0")
    assert text.index("### 0.72.0") < text.index("### 0.71.2")
    assert len(text.splitlines()) < 250


def test_current_architecture_is_separate_from_historical_design() -> None:
    current = (DOCS / "referencia" / "ARQUITECTURA_Y_MODELO_ACTUAL.md").read_text(
        encoding="utf-8"
    )
    historical_path = (
        DOCS
        / "historico"
        / "diseno"
        / "DISENO_Y_PLAN_DE_IMPLEMENTACION_HASTA_0.49.2.md"
    )
    historical = historical_path.read_text(encoding="utf-8")
    assert "Originales inmutables" in current
    assert "plantillas XLSX de catálogo" in current
    assert "una sola transacción" in current
    assert "Resolver contenido de un paquete sin base común no crea linaje" in current
    positions = [historical.index(f"# {number}.") for number in range(17, 51)]
    assert positions == sorted(positions)
    assert "# 50. Estado operativo de pendientes y estrategia de pruebas en 0.49.2" in historical


def test_surya_evaluation_is_preserved_in_historical_technical_docs() -> None:
    text = (HISTORICAL_TECH / "EVALUACION_SURYA_OCR_0.38.0.md").read_text(
        encoding="utf-8"
    )
    assert "## 4. Evaluación cualitativa por página" in text
    assert "Surya fue claramente superior" in text
    assert "surya-server-status" in text
    assert "surya-server-stop" in text


def test_structural_ocr_control_document_is_preserved_and_conservative() -> None:
    text = (HISTORICAL_TECH / "CONTROL_ESTRUCTURAL_OCR_0.39.0.md").read_text(
        encoding="utf-8"
    )
    assert "page_quality_v2" in text
    assert "no corrige el texto" in text
    assert "Artículo 49" in text
    assert "casillero vacío" in text
    assert "CER/WER" in text


def test_editable_rebase_document_is_preserved_and_conservative() -> None:
    text = (HISTORICAL_TECH / "REBASE_EDICION_OCR_0.40.0.md").read_text(
        encoding="utf-8"
    )
    assert "rebase conservador de tres estados" in text
    assert "vista previa" in text
    assert "no se modifica nada" in text
    assert "menciones" in text
    assert "tracked_tabs" in text
    assert "0032_page_quality_assessments" in text


def test_rebase_conflict_resolution_document_is_preserved() -> None:
    text = (HISTORICAL_TECH / "RESOLUCION_CONFLICTOS_REBASE_0.41.0.md").read_text(
        encoding="utf-8"
    )
    assert "resolución manual asistida" in text
    assert "autoridad canónica" in text
    assert "rebase_relocate_manual" in text
    assert "rebase_reject_conflict" in text
    assert "no fusiona autoridades" in text


def test_text_rebase_and_view_isolation_document_is_preserved() -> None:
    text = (
        HISTORICAL_TECH / "REBASE_CONFLICTOS_TEXTUALES_Y_NAVEGACION_0.42.0.md"
    ).read_text(encoding="utf-8")
    assert "corrección humana" in text
    assert "conservar la lectura de la candidata" in text
    assert "escribir el texto resultante exacto" in text
    assert "request_app_view" in text
    assert "isolated_view" in text


def test_structural_metadata_rebase_document_is_preserved() -> None:
    text = (HISTORICAL_TECH / "REBASE_ESTRUCTURA_Y_METADATOS_0.43.0.md").read_text(
        encoding="utf-8"
    )
    assert "snapshot editable activo actual" in text
    assert "Parte documental" in text
    assert "Estado de revisión" in text
    assert "Tipo de objeto" in text
    assert "no se borran" in text


def test_interaction_continuity_document_is_preserved() -> None:
    text = (HISTORICAL_TECH / "CONTINUIDAD_INTERACCION_STREAMLIT_0.44.0.md").read_text(
        encoding="utf-8"
    )
    assert "fragmented_view" in text
    assert "rerun_view" in text
    assert "rerun_app" in text
    assert "manual_object_projection" in text
    assert "no consiste en eliminar todos los reruns" in text


def test_specialized_attribute_rebase_document_and_demo_are_preserved() -> None:
    text = (HISTORICAL_TECH / "REBASE_ATRIBUTOS_Y_PRUEBA_GUIADA_0.45.0.md").read_text(
        encoding="utf-8"
    )
    assert "bloqueo circular" in text
    assert "manual_attribute_selection" in text
    assert "manual_attribute_json" in text
    assert "create_rebase_validation_project.py" in text


def test_historical_update_guides_046_to_0630_are_preserved() -> None:
    expected = [
        "ACTUALIZACION_Y_PRUEBA_0.46.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.47.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.48.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.49.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.49.1.md",
        "ACTUALIZACION_Y_PRUEBA_0.49.2.md",
        "ACTUALIZACION_Y_PRUEBA_0.50.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.50.1.md",
        "ACTUALIZACION_Y_PRUEBA_0.50.2.md",
        "ACTUALIZACION_Y_PRUEBA_0.50.3.md",
        "ACTUALIZACION_Y_PRUEBA_0.51.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.52.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.53.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.54.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.55.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.56.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.57.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.58.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.59.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.60.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.61.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.62.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.62.1.md",
        "ACTUALIZACION_Y_PRUEBA_0.63.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.64.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.64.1.md",
        "ACTUALIZACION_Y_PRUEBA_0.64.2.md",
        "ACTUALIZACION_Y_PRUEBA_0.65.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.66.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.67.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.68.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.68.1.md",
        "ACTUALIZACION_Y_PRUEBA_0.69.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.69.1.md",
        "ACTUALIZACION_Y_PRUEBA_0.69.2.md",
        "ACTUALIZACION_Y_PRUEBA_0.70.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.70.1.md",
        "ACTUALIZACION_Y_PRUEBA_0.70.2.md",
        "ACTUALIZACION_Y_PRUEBA_0.71.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.71.1.md",
        "ACTUALIZACION_Y_PRUEBA_0.72.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.73.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.74.0.md",
        "ACTUALIZACION_Y_PRUEBA_0.75.0.md",
    ]
    assert sorted(path.name for path in HISTORICAL_UPDATES.glob("*.md")) == expected
    text_047 = (HISTORICAL_UPDATES / expected[1]).read_text(encoding="utf-8")
    text_049 = (HISTORICAL_UPDATES / expected[3]).read_text(encoding="utf-8")
    assert "A → B → A → B" in text_047
    assert "0033_export_exchange_lifecycle" in text_049


def test_mention_repair_decision_is_preserved_and_conservative() -> None:
    text = (
        HISTORICAL_TECH / "REPARACION_ASISTIDA_MENCIONES_0.57.0.md"
    ).read_text(encoding="utf-8")
    assert "safe_relocation" in text
    assert "snapshot_divergence" in text
    assert "repair_relocation" in text
    assert "no se presentan como trabajo activo" in text
    assert "nunca reescrituras silenciosas" in text


def test_missing_authority_repair_decision_is_preserved_and_auditable() -> None:
    text = (
        HISTORICAL_TECH / "REPARACION_ENTIDAD_FALTANTE_0.58.0.md"
    ).read_text(encoding="utf-8")
    assert "entidad activa" in text
    assert "mismo proyecto" in text
    assert "no reescriben snapshots anteriores" in text
    assert "límites de palabra" in text


def test_duplicate_repair_decision_is_preserved_and_auditable() -> None:
    text = (
        HISTORICAL_TECH / "REPARACION_DUPLICADOS_MENCIONES_0.59.0.md"
    ).read_text(encoding="utf-8")
    assert "exactamente una contraparte activa" in text
    assert "no se elimina físicamente" in text
    assert "transacción completa" in text
    assert "create_duplicate_mention_validation_project.py" in text


def test_manual_location_repair_decision_is_preserved_and_auditable() -> None:
    text = (
        HISTORICAL_TECH / "REPARACION_UBICACIONES_MANUALES_0.60.0.md"
    ).read_text(encoding="utf-8")
    assert "fragmento literal" in text
    assert "No se permite marcar como ausente" in text
    assert "create_unresolved_mention_validation_project.py" in text


def test_snapshot_divergence_reconciliation_decision_is_preserved() -> None:
    text = (
        HISTORICAL_TECH / "RECONCILIACION_DIVERGENCIAS_MENCIONES_0.61.0.md"
    ).read_text(encoding="utf-8")
    assert "campo por campo" in text
    assert "ningún valor observado desaparezca" in text
    assert "create_snapshot_divergence_validation_project.py" in text



def test_grouped_mention_repair_decision_is_preserved_and_atomic() -> None:
    text = (
        HISTORICAL_TECH / "REPARACION_CONJUNTOS_MENCIONES_0.62.0.md"
    ).read_text(encoding="utf-8")
    assert "duplicate_group" in text
    assert "transaccional" in text
    assert "no permite resolver pares aislados" in text
    assert "create_grouped_mention_validation_project.py" in text

def test_automatic_analysis_quality_decision_is_preserved_and_auditable() -> None:
    text = (
        HISTORICAL_TECH / "POLITICA_AUDITABLE_ANALISIS_AUTOMATICOS_0.64.0.md"
    ).read_text(encoding="utf-8")
    assert "approved" in text
    assert "fundamento no vacío" in text
    assert "automatic_analysis_authorizations" in text
    assert "append-only" in text
    assert "analysis-quality-audit" in text
    assert "st.form" in text


def test_current_update_guide_is_stable_named_and_validates_cat01() -> None:
    text = (OPERATIVE / "ACTUALIZACION_ACTUAL.md").read_text(encoding="utf-8")
    assert "Archive Workbench 0.75.1" in text
    assert "0040_discovery_grouping_continuity" in text
    assert "No hay migración" in text
    assert "project_data" in text
    assert "no mueve ni elimina" in text.lower()
    assert "create_catalog_template_validation_project.py" in text
    assert "catalog-template-validate" in text
    assert "Proyecto de validación CAT-01" in text
    assert "## 6. Resultado de la validación" in text
    assert "reimportación idéntica con 155 unidades sin cambios" in text
    assert "project_data` no fue leído ni modificado" in text
    assert "LISTAS" in text and "oculta" in text
    assert "Aplicar plantilla" in text
    assert "155 unidades sin cambios" in text
    assert "pytest --collect-only -q" in text
    assert "DISC-01D" in text and "No repetir" in text


def test_ex01_lineage_recovery_plan_is_complete_and_conservative() -> None:
    text = (
        DOCS / "referencia" / "RECUPERACION_LINAJE_EX_01.md"
    ).read_text(encoding="utf-8")
    for item in (
        "## 2. Objetivo",
        "## 3. Contratos actuales que se conservan",
        "## 4. Invariantes de seguridad",
        "## 8. Fases de implementación",
        "## 9. Criterios de no regresión",
        "## 10. Pruebas mínimas",
        "## 11. Fuera de alcance por ahora",
        "EX-01A",
        "EX-01B",
        "EX-01C",
        "EX-01D",
    ):
        assert item in text
    assert "Resolver el contenido de un paquete no crea linaje" in text
    assert "Sin inferencia por similitud" in text
    assert "diagnóstico" in text and "sin escribir" in text
    assert "backup" in text and "rollback" in text
    assert "IMPLEMENTADA Y VALIDADA EN 0.65.0" in text
    assert "IMPLEMENTADA Y VALIDADA EN 0.66.0" in text
    assert "0037_exchange_state_adoptions" in text
    assert "recovered_lineage" in text
    assert "create_lineage_diagnostic_validation_projects.py" in text
    assert "IMPLEMENTADA Y VALIDADA EN 0.67.0" in text
    assert "common_base_agreement" in text
    assert "create_common_base_validation_projects.py" in text
    assert "IMPLEMENTADA Y VALIDADA EN 0.68.0" in text
    assert "exchange-state-adoption-rollback" in text
    assert "create_state_adoption_validation_projects.py" in text


def test_testing_strategy_is_explicit_and_does_not_discard_slow_tests() -> None:
    text = (OPERATIVE / "ESTRATEGIA_DE_PRUEBAS.md").read_text(encoding="utf-8")
    assert "pytest --collect-only -q" in text
    assert "No eliminar pruebas por ser lentas" in text
    assert "fast" in text and "integration" in text and "slow" in text
    assert "no atribuir a la suite completa" in text


def test_pilot_guide_delegates_future_work_to_single_pending_ledger() -> None:
    text = (OPERATIVE / "GUIA_PRUEBA_PILOTO.md").read_text(encoding="utf-8")
    assert "PENDIENTES_ACTIVOS.md" in text
    assert "Esta guía se limita al piloto" in text
    assert "# Fase 7 — Candidata a v1.0" in text
    assert "## Capacidades previstas después del núcleo" not in text


def test_readme_points_only_to_current_documentation_map() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert "**Versión actual:** 0.75.1" in text
    assert "La versión 0.75.1 incorpora pruebas automatizadas" in text
    assert "(versión 0.75.1)" in text
    assert 'version: "0.75.1"' in citation
    assert "docs/HISTORIAL_DE_CAMBIOS.md" in text
    assert "docs/operativos/PENDIENTES_ACTIVOS.md" in text
    assert "docs/operativos/IMPLEMENTACIONES_REALIZADAS.md" in text
    assert "docs/DISENO_Y_PLAN_DE_IMPLEMENTACION.md" not in text


def test_open_discovery_plan_separates_suggestions_from_canonical_records() -> None:
    text = (DOCS / "referencia" / "DESCUBRIMIENTO_ABIERTO_DISC_01.md").read_text(
        encoding="utf-8"
    )
    assert "DISC-01A" in text
    assert "DISC-01B" in text
    assert "DISC-01C" in text
    assert "DISC-01D" in text
    assert "únicamente páginas `approved`" in text
    assert "nunca canoniza" in text or "nunca debe" in text
    assert "no se convierte en una tabla canónica universal" in text
    assert "no crear autoridades, menciones ni relaciones" in text
    assert "implementada y validada" in text
    assert "17" in text and "13" in text
    assert "0040_discovery_grouping_continuity" in text
    assert "discovery_context_records" in text
    assert "autoridad nueva con estado `unreviewed`" in text
    assert "local_deterministic@local_rules_v1" in text
    assert "spacy_ner" in text
    assert "config/discovery_evaluation_corpus.jsonl" in text
    assert "Criterio de cierre cumplido" in text
