from pathlib import Path


ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"
HISTORICAL_TECH = DOCS / "historico" / "decisiones_tecnicas"
HISTORICAL_UPDATES = DOCS / "historico" / "actualizaciones"
OPERATIVE = DOCS / "operativos"
REFERENCE = DOCS / "referencia"


def test_docs_root_is_clean_and_operational_documents_are_unique() -> None:
    root_files = {path.name for path in DOCS.iterdir() if path.is_file()}
    assert "HISTORIAL_DE_CAMBIOS.md" in root_files
    assert "index.html" in root_files
    assert ".nojekyll" in root_files
    assert not {name for name in root_files if name.endswith(".md") and name != "HISTORIAL_DE_CAMBIOS.md"}
    assert sorted(path.name for path in OPERATIVE.glob("*.md")) == [
        "ACTUALIZACION_ACTUAL.md",
        "ESTRATEGIA_DE_PRUEBAS.md",
        "GUIA_PRUEBA_PILOTO.md",
        "HOJA_DE_RUTA_PRE_RELEASE.md",
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



def test_change_checklist_is_mandatory_and_points_to_canonical_sources() -> None:
    assistant = ROOT / ".assistant"
    first = (assistant / "00_LEER_PRIMERO.md").read_text(encoding="utf-8")
    checklist_path = assistant / "00_CHECKLIST_CAMBIOS.md"
    assert checklist_path.is_file()
    checklist = checklist_path.read_text(encoding="utf-8")
    assert "Antes de modificar código, pruebas, configuración, documentación, empaquetado o instrucciones de una candidata" in first
    assert ".assistant/00_CHECKLIST_CAMBIOS.md" in first
    for name in (
        "01_INTERACCION_Y_GUIADO.md",
        "02_POLITICA_DOCUMENTAL.md",
        "03_POLITICA_DE_PRUEBAS.md",
        "04_CONTINUIDAD_DEL_PROYECTO.md",
        "05_CRITERIOS_INTERFAZ.md",
        "05_FORMULARIOS_STREAMLIT.md",
        "07_SEGURIDAD_ARCHIVOS_Y_REPOSITORIO.md",
        "POLITICA_SITIO_PUBLICO.md",
        "LINEAMIENTOS_DE_DISENO_Y_ESCRITURA.md",
    ):
        assert name in checklist
    assert "ARQUITECTURA_Y_MODELO_ACTUAL.md#streamlit-interaction-invariant" in checklist
    assert "única fuente de verdad" in checklist
    assert "no redefine políticas" in checklist.lower()


def test_active_pending_ledger_has_index_and_recovers_all_major_lines() -> None:
    text = (OPERATIVE / "PENDIENTES_ACTIVOS.md").read_text(encoding="utf-8")
    implemented = (OPERATIVE / "IMPLEMENTACIONES_REALIZADAS.md").read_text(encoding="utf-8")
    assert "## Índice" in text
    for item in (
        "AI-01 — Pipeline CLI opcional de análisis con LLM",
        "AI-02 — Sistema RAG trazable",
        "OPS-01 — Distribución multiplataforma e imagen Docker",
        "WEB-01 — Sitio público y documentación de release",
        "GIAR-01 — Base de conocimiento y sitio",
    ):
        assert item in text
    assert "AV-01 — Registro local de audio y video y transcripción" not in text
    assert "AV-01 — audio/video local, segmentos y corrección — 0.84.0" in implemented
    assert "AV-02 — incorporación autorizada desde plataformas — 0.85.0" in implemented
    assert "AV-03 — evaluación, revisión sincronizada y calidad de reconocimiento — 0.86.0" in implemented
    assert "INT-01 — Google Drive como transporte controlado — 0.87.0" in implemented
    assert "EXP-01 — paquete visual con contexto estructurado — 0.88.0" in implemented
    assert "EXP-01 — Exportación trazable de imágenes y recortes" not in text
    assert "INT-01 — Integración opcional con Google Drive" not in text
    assert "AV-03 — Evaluación y optimización de transcripción de video real" not in text
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
    assert "DISC-02 — Importación de diccionarios" not in text
    assert "EX-01 — Recuperación asistida de linaje" not in text
    assert "DISC-01 — Descubrimiento abierto" not in text
    assert "DISC-01D" not in text
    assert "CAT-02 — Entidades productoras y gestoras" not in text
    assert "GRAPH-02 — Estructura archivística, documentos y partes" not in text


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
    assert "Validada manualmente en 0.75.1" in text
    assert "CAT-01` queda cerrado" in text
    assert "155 filas trazables" in text
    assert "DISC-02 — esquema, simulación e importación transaccional — 0.76.0" in text
    assert "Diccionarios de autoridades DISC-02 | Implementados y validados en 0.76.0" in text
    assert "Validado manualmente en 0.76.0" in text
    assert "DISC-02` queda cerrado" in text
    assert "authority-dictionary-validate" in text
    assert "CAT-02 + GRAPH-02 — implementación conjunta — 0.77.0" in text
    assert "Productores y gestores CAT-02 | Implementados y validados en 0.77.0" in text
    assert "Capas archivísticas GRAPH-02 | Implementadas y validadas en 0.77.0" in text
    assert "0041_catalog_authority_roles_graph_layers" in text
    assert "`CAT-02` y `GRAPH-02` quedan cerrados" in text
    assert "OCR-01A — orientación, deskew y líneas controladas — 0.78.0" in text
    assert "0042_preprocessing_geometry_trace" in text
    assert "Validada manualmente en 0.78.0" in text
    assert "`OCR-01A` queda cerrada" in text
    assert "OCR-01B — formularios y casilleros revisables — 0.79.0" in text
    assert "0043_form_structure_review" in text
    assert "copia durable de la pestaña activa" in text
    assert "Validada manualmente en 0.79.0" in text
    assert "`OCR-01B` queda cerrada" in text
    assert "OCR-01F — Tesseract, Docling y Surya — 0.83.0" in text
    assert "Tesseract 5.3.4" in text
    assert "Docling 2.114.0" in text
    assert "Surya 0.22.1" in text
    assert "`OCR-01F` y el bloque completo `OCR-01` quedan cerrados" in text


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
    assert "UX-02 |" not in pending
    assert "RC71 - cierre de UX-02" in implemented
    assert "Casilleros y campos" in implemented
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
    assert "### 0.80.0" in text
    assert "0044_layout_structure_review" in text
    assert "### 0.83.0" in text
    assert "### 0.79.0" in text
    assert "0043_form_structure_review" in text
    assert "### 0.77.0" in text
    assert "0041_catalog_authority_roles_graph_layers" in text
    assert "### 0.76.0" in text
    assert "`DISC-02` queda cerrado" in text
    assert "### 0.75.1" in text
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
    assert text.index("### 0.83.0") < text.index("### 0.82.0")
    assert text.index("### 0.79.0") < text.index("### 0.77.0")
    assert text.index("### 0.77.0") < text.index("### 0.76.0")
    assert text.index("### 0.76.0") < text.index("### 0.75.1")
    assert text.index("### 0.75.1") < text.index("### 0.75.0")
    assert text.index("### 0.75.0") < text.index("### 0.74.0")
    assert text.index("### 0.74.0") < text.index("### 0.73.0")
    assert text.index("### 0.73.0") < text.index("### 0.72.0")
    assert text.index("### 0.72.0") < text.index("### 0.71.2")
    assert len(text.splitlines()) < 380


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
    assert "máscara diagnóstica" in current
    assert "Una confianza insuficiente produce una omisión explicable" in current
    assert "plantillas XLSX de catálogo" in current
    assert "roles controlados" in current
    assert "objetos digitales y partes documentales" in current
    assert "pertenencia archivística nunca se presenta como relación analítica" in current
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
        "ACTUALIZACION_Y_PRUEBA_0.75.1.md",
        "ACTUALIZACION_Y_PRUEBA_0.88.2.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC10.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC12.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC14.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC15.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC20.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC22.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC23.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC25.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC27.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC30.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC38.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC39.md",
        "ACTUALIZACION_Y_PRUEBA_0.89.0_RC40.md",
    ]
    observed = {path.name for path in HISTORICAL_UPDATES.glob("*.md")}
    assert set(expected).issubset(observed)
    assert "ACTUALIZACION_Y_PRUEBA_0.89.0_RC53.md" in observed
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


def test_current_update_guide_describes_0890_rc84_google_drive_callback_candidate() -> None:
    text = (OPERATIVE / "ACTUALIZACION_ACTUAL.md").read_text(encoding="utf-8")
    pending = (OPERATIVE / "PENDIENTES_ACTIVOS.md").read_text(encoding="utf-8")
    implemented = (OPERATIVE / "IMPLEMENTACIONES_REALIZADAS.md").read_text(encoding="utf-8")
    continuity = (Path(__file__).parents[1] / ".assistant" / "06_RELEVO_NUEVA_CONVERSACION.md").read_text(encoding="utf-8")
    guidelines = (Path(__file__).parents[1] / ".assistant" / "LINEAMIENTOS_DE_DISENO_Y_ESCRITURA.md").read_text(encoding="utf-8")
    architecture = (REFERENCE / "ARQUITECTURA_Y_MODELO_ACTUAL.md").read_text(encoding="utf-8")
    historical_rc76 = HISTORICAL_UPDATES / "ACTUALIZACION_Y_PRUEBA_0.89.0_RC76.md"

    assert "Archive Workbench 0.89.0 RC84" in text
    assert "0.89.0-rc84-cpu" in text
    assert "0.89.0-rc84-gpu" in text
    assert "| WEB-01 | Alta | Parcial pre-release, pausado |" in pending
    assert "| OPS-01 | Alta | Parcial, en curso |" in pending
    assert "## RC80 - PyTorch CPU explícito en runtime principal multi-arquitectura" in implemented
    assert "## RC79 - transcripción audiovisual GPU validada y métrica VRAM en Docker" in implemented
    assert "peak_gpu_memory_mib" in implemented
    assert "nvidia-smi" in implemented
    assert "llama-server" in implemented
    assert "## RC78 - diagnóstico administrado GPU y validación material Linux/NVIDIA" in implemented
    assert "## RC77 - guardas de inferencia para Surya/llama.cpp administrado" in implemented
    assert "no cambia el esquema SQLite" in text
    assert "0.89.0 RC84" in continuity
    assert "2.5 Regla obligatoria para lectores sin conocimiento previo" in guidelines
    assert "Cada sustantivo que pueda tener más de un referente" in guidelines
    assert "Distribución administrada y espacio de trabajo multiplataforma - RC72/RC84" in architecture
    assert "ARCHIVE_WORKBENCH_SELECTED_PROJECT_ROOT" in architecture
    assert "0047_authority_relation_profiles" in text
    assert "OPS-01-TABS" not in pending
    assert "OPS-01-COPY" not in pending
    assert "OPS-01-STOP" not in pending
    assert "OPS-01-CALLBACK" in pending
    assert "sesión auxiliar terminal" in text
    assert "Google Drive" in text
    assert "st.stop()" in text
    assert historical_rc76.is_file()


def test_pilot_01o_is_closed_and_not_active_after_rc20_validation() -> None:
    pending = (OPERATIVE / "PENDIENTES_ACTIVOS.md").read_text(encoding="utf-8")
    implemented = (OPERATIVE / "IMPLEMENTACIONES_REALIZADAS.md").read_text(encoding="utf-8")
    assert "| PILOT-01O |" not in pending
    assert "### PILOT-01O" not in pending
    assert "cierra `PILOT-01O`" in implemented
    assert "Trabajar con varias referencias" in implemented
    assert "Referencias descartadas" in implemented
    assert "Relaciones" in implemented


def test_interaction_policy_requires_explicit_checklist_confirmation_for_code_changes() -> None:
    text = (ROOT / ".assistant" / "01_INTERACCION_Y_GUIADO.md").read_text(encoding="utf-8")
    assert "todo mensaje que presente una modificación de código" in text.lower()
    assert "confirmar explícitamente" in text.lower()
    assert "00_CHECKLIST_CAMBIOS.md" in text


def test_authority_dictionary_format_is_versioned_and_conservative() -> None:
    text = (
        DOCS / "referencia" / "IMPORTACION_DICCIONARIOS_DISC_02.md"
    ).read_text(encoding="utf-8")
    for item in (
        "Versión del esquema",
        "authority_dictionary.schema.json",
        "diccionario_autoridades_ejemplo.json",
        "use_existing",
        "create_new",
        "allow_ambiguous",
        "create_parallel",
        "evidencia",
        "una sola transacción",
    ):
        assert item in text
    assert "una coincidencia ordinaria nunca se sobrescribe por inferencia" in text
    assert "update_existing" in text
    assert "Para crear una relación nueva" in text
    assert "evidence` debe contener al menos uno" in text
    assert "clasificadas explícitamente como `analytical`" in text
    assert "provenance_note" in text


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
    assert "pytest --collect-only" in text
    assert "No eliminar pruebas por ser lentas" in text
    assert "fast" in text and "integration" in text and "slow" in text
    assert "no atribuir a la suite completa" in text


def test_pilot_guide_delegates_future_work_to_single_pending_ledger() -> None:
    text = (OPERATIVE / "GUIA_PRUEBA_PILOTO.md").read_text(encoding="utf-8")
    assert "PENDIENTES_ACTIVOS.md" in text
    assert "HOJA_DE_RUTA_PRE_RELEASE.md" in text
    assert "PROYECTO_PARALELO_GIAR.md" in text
    assert "Esta guía se limita al piloto" in text
    assert "Archivo de la DIPPBA" in text
    assert "APM-Chubut" in text
    assert "testimonios audiovisuales" in text
    assert "audios y videos autorizados" in text
    assert "velocidades" in text
    assert "no se tratará como una base descartable" in text
    assert "# Fase 7 — Candidata a v1.0" in text
    assert "## Capacidades previstas después del núcleo" not in text


def test_readme_points_only_to_current_documentation_map() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert "**Versión actual:** 0.89.0" in text
    assert 'version: "0.89.0"' in citation
    assert "archive-workbench review-app" in text
    assert "Abrir un proyecto existente" in text
    assert "Crear un proyecto nuevo" in text
    assert "--complete-existing" in text
    assert "Incorporación individual y por lote" in text
    assert "Productores y responsables de gestión" in text
    assert "Exportar texto e imágenes (ZIP)" in text
    assert 'pip install -e ".[platform]"' in text
    assert "FFmpeg/FFprobe" in text
    assert "docs/HISTORIAL_DE_CAMBIOS.md" in text
    assert "docs/operativos/PENDIENTES_ACTIVOS.md" in text
    assert "docs/operativos/IMPLEMENTACIONES_REALIZADAS.md" in text
    assert "docs/DISENO_Y_PLAN_DE_IMPLEMENTACION.md" not in text


def test_public_site_web01_has_required_pages_metadata_and_local_links() -> None:
    required = {
        "index.html", "instalacion.html", "tutorial.html", "catalogo.html",
        "procesamiento.html", "revision.html", "entidades.html", "busquedas.html",
        "relaciones.html", "audiovisual.html", "exportacion.html", "intercambio.html",
        "resguardo.html", "conceptos.html", "referencia.html", "problemas.html", "404.html",
    }
    assert required.issubset({p.name for p in DOCS.glob("*.html")})
    for path in [DOCS / name for name in required]:
        text = path.read_text(encoding="utf-8")
        assert 'lang="es-AR"' in text
        assert '<meta name="description"' in text
        assert 'href="assets/site.css"' in text
        assert 'class="skip"' in text
        assert '<nav aria-label="Navegación principal">' in text
        assert "placeholder" not in text.lower()
    for html in DOCS.glob("*.html"):
        text = html.read_text(encoding="utf-8")
        for target in __import__("re").findall(r'(?:href|src)="([^"]+)"', text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            resolved = (html.parent / target.split("#", 1)[0]).resolve()
            assert resolved.exists(), f"broken local link in {html.name}: {target}"


def test_public_site_diagrams_are_accessible_and_readme_points_to_site() -> None:
    diagrams = DOCS / "assets" / "diagrams"
    for name in ("flujo-general.svg", "trazabilidad-texto.svg", "arquitectura-local.svg", "intercambio.svg"):
        text = (diagrams / name).read_text(encoding="utf-8")
        assert 'role="img"' in text
        assert "<title" in text and "<desc" in text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/index.html" in readme
    assert "docs/tutorial.html" in readme
    assert "docs/assets/diagrams/flujo-general.svg" in readme
    assert "versión 0.89.0" in readme.lower()


def test_web01_is_paused_until_distribution_and_full_novice_reader_rewrite() -> None:
    pending = (OPERATIVE / "PENDIENTES_ACTIVOS.md").read_text(encoding="utf-8")
    current = (OPERATIVE / "ACTUALIZACION_ACTUAL.md").read_text(encoding="utf-8")
    guidelines = (ROOT / ".assistant" / "LINEAMIENTOS_DE_DISENO_Y_ESCRITURA.md").read_text(encoding="utf-8")
    assert "UX-02 |" not in pending
    assert "WEB-01 | Alta | Parcial pre-release, pausado" in pending
    assert "WEB-01` permanece parcial y queda pausado" in current
    assert "No se incorporan capturas hasta realizar esa reescritura" in current
    assert "lectores sin conocimiento previo" in current
    assert "no usar `candidato` como sustantivo autónomo" in guidelines.lower()


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



def test_pre_release_roadmap_includes_public_site_export_and_parallel_giar() -> None:
    text = (OPERATIVE / "HOJA_DE_RUTA_PRE_RELEASE.md").read_text(encoding="utf-8")
    assert "EXP-01" in text
    assert "WEB-01" in text
    assert "PILOT-01" in text
    assert "GIAR-01" in text
    assert "vision_describe" in text
    assert "GitHub Pages" in text
    assert "`AV-03` quedó implementado, validado y cerrado en 0.86.0" in text
    assert "`OCR-01` quedó implementado, validado y cerrado en 0.83.0" in text
    assert "`AV-01` quedó implementado, validado y cerrado en 0.84.0" in text
    assert "`AV-02` quedó implementado, validado y cerrado en 0.85.0" in text
    assert "`AV-03` quedó implementado, validado y cerrado en 0.86.0" in text
    assert "1. Completar `AV-03`" not in text
    assert "`INT-01` quedó implementado, validado y cerrado en 0.87.0" in text
    assert "0.88.0" in text
    assert "`EXP-01` quedó implementado, validado y cerrado en 0.88.0" in text
    assert "1. Cerrar `DISC-03`" not in text
    assert "1. Completar `UX-02`" not in text
    assert "1. Completar y validar `OPS-01`" in text
    assert "2. Retomar `WEB-01`" in text
    assert "1. Ejecutar `PILOT-01`" not in text
    assert "Validar y cerrar `EXP-01`" not in text
    assert "Validar y cerrar `INT-01`" not in text
    assert "Validar y cerrar `AV-02`" not in text
    assert "Validar y cerrar `AV-01`" not in text
    assert "Validar `OCR-01F`" not in text


def test_giar_parallel_project_is_referential_and_preserves_provenance() -> None:
    path = DOCS / "referencia" / "PROYECTO_PARALELO_GIAR.md"
    text = path.read_text(encoding="utf-8")
    for item in (
        "integrantes e investigadores",
        "publicaciones e informes",
        "DIPPBA Bahía Blanca",
        "páginas personales",
        "Páginas temáticas",
        "Glosario conceptual",
        "Páginas de archivos",
        "GitHub Pages",
        "POLITICA_SITIO_PUBLICO",
    ):
        assert item in text
    assert "proyecto separado y persistente" in text
    assert "ninguna relación analítica se creará sin evidencia" in text


def test_ocr01c_assistant_guidance_update_is_idempotent(tmp_path: Path) -> None:
    import importlib.util

    assistant = tmp_path / ".assistant"
    assistant.mkdir()
    for name in (
        "01_INTERACCION_Y_GUIADO.md",
        "03_POLITICA_DE_PRUEBAS.md",
        "05_CRITERIOS_INTERFAZ.md",
    ):
        (assistant / name).write_text(f"# {name}\n", encoding="utf-8")

    script = ROOT / "scripts" / "update_assistant_guidance_0800.py"
    spec = importlib.util.spec_from_file_location("assistant_guidance_0800", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    first = module.update(tmp_path)
    second = module.update(tmp_path)

    assert len(first) == 3
    assert second == []
    interaction = (assistant / "01_INTERACCION_Y_GUIADO.md").read_text(encoding="utf-8")
    tests_policy = (assistant / "03_POLITICA_DE_PRUEBAS.md").read_text(encoding="utf-8")
    interface = (assistant / "05_CRITERIOS_INTERFAZ.md").read_text(encoding="utf-8")
    assert "Cada control nuevo debe explicarse" in interaction
    assert "No se deben usar `assert` sin mensaje" in tests_policy
    assert "Crear una columna para un objeto" in interface


def test_ocr01_is_closed_and_architecture_remains_conservative() -> None:
    pending = (OPERATIVE / "PENDIENTES_ACTIVOS.md").read_text(encoding="utf-8")
    implemented = (OPERATIVE / "IMPLEMENTACIONES_REALIZADAS.md").read_text(encoding="utf-8")
    architecture = (DOCS / "referencia" / "ARQUITECTURA_Y_MODELO_ACTUAL.md").read_text(encoding="utf-8")
    assert "### OCR-01 —" not in pending
    assert "| OCR-01 |" not in pending
    assert "`OCR-01` quedó cerrado en 0.83.0" in pending
    assert "OCR-01A–F implementadas, validadas y cerradas" in implemented
    assert "OCR-01F — Tesseract, Docling y Surya — 0.83.0" in implemented
    assert "CER 0.0000" in implemented and "WER 0.0000" in implemented
    assert "`OCR-01F` y el bloque completo `OCR-01` quedan cerrados" in implemented
    assert "OCR regional" in architecture
    assert "selección canónica desactivada" in architecture
    assert "Una región manual no inventa" in architecture
    assert "Dewarp conservador de derivados OCR" in architecture
    assert "no reconstruye caracteres" in architecture
    assert "dewarp_diagnostic" in architecture
    assert "Benchmark OCR con verdad terreno" in architecture
    assert "Tesseract, Docling y Surya" in architecture
    assert "CER/WER" in architecture
    assert "AV-01 — audio/video local, segmentos y corrección — 0.84.0" in implemented
    assert "FFprobe" in implemented and "FFmpeg" in implemented
    assert "Velocidad de reproducción" in implemented
    assert "faster-whisper" in implemented and "CPU" in implemented
    assert "video real autorizado" in implemented
    assert "reproducción con velocidades configurables" in architecture
    assert "0045_audiovisual_transcription" in architecture
    assert "0047_authority_relation_profiles" in architecture
    assert "TranscriptSegmentRevision" in architecture
    assert "SegmentEntityMention" in architecture
    assert "AudiovisualTimelineAnnotation" in architecture
    assert "AudiovisualTimelineAnnotationRevision" in architecture
    assert "AV-02 — Plugin opcional de incorporación desde YouTube y otras plataformas — EN VALIDACIÓN" not in pending
    assert "AV-02 — incorporación autorizada desde plataformas — 0.85.0" in implemented
    assert "AV-03 — Evaluación y optimización de transcripción de video real — EN VALIDACIÓN" not in pending
    assert "Evaluación y revisión audiovisual AV-03" in implemented
    assert "AV-03 — evaluación, revisión sincronizada y calidad de reconocimiento — 0.86.0" in implemented
    assert "large-v3" in implemented and "CUDA" in implemented
    assert "Evaluación audiovisual AV-03" in architecture
    assert "_runtime_metrics" in architecture
    assert "AV-01 —" not in pending
    assert "INT-01 — Integración opcional con Google Drive como transporte — EN VALIDACIÓN" not in pending
    assert "| INT-01 |" not in pending
    assert "INT-01 — Google Drive como transporte controlado — 0.87.0" in implemented
    assert "EXP-01 — paquete visual con contexto estructurado — 0.88.0" in implemented
    assert "EXP-01 — Exportación trazable de imágenes y recortes" not in pending
    assert "Desde Google Drive" in (ROOT / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    assert "Transporte opcional por Google Drive — INT-01" in architecture
    assert "drive.file" in architecture
    assert "no sincroniza una SQLite abierta" in architecture


def test_pilot_findings_are_persisted_in_project_documentation() -> None:
    interaction = (ROOT / ".assistant" / "01_INTERACCION_Y_GUIADO.md").read_text(encoding="utf-8")
    policy = (ROOT / ".assistant" / "02_POLITICA_DOCUMENTAL.md").read_text(encoding="utf-8")
    interface = (ROOT / ".assistant" / "05_CRITERIOS_INTERFAZ.md").read_text(encoding="utf-8")
    pending = (OPERATIVE / "PENDIENTES_ACTIVOS.md").read_text(encoding="utf-8")
    implemented = (OPERATIVE / "IMPLEMENTACIONES_REALIZADAS.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "referencia" / "ARQUITECTURA_Y_MODELO_ACTUAL.md").read_text(encoding="utf-8")

    assert "dejar asentado" in interaction.lower()
    assert "memoria del asistente como sustituto" in interaction
    assert 'Qué significa "dejar asentado"' in policy
    assert "todo campo visible que solicite una carpeta debe ofrecer un selector gráfico" in interface
    assert "invariante canónico de interacción Streamlit" in interface
    for task_id in ("PILOT-01A", "PILOT-01B", "PILOT-01C", "PILOT-01D"):
        assert task_id in implemented
    assert "| PILOT-01A |" not in pending
    assert "Modelo de custodia, conjuntos documentales y audiovisual - PILOT-01A / RC65" in architecture
    assert "`Archivo` como contexto de custodia" in architecture
    assert "no como afirmación de que el repositorio sea un nivel interno de la colección" in architecture
    assert "Diferencias entre dos transcripciones" in architecture


def test_streamlit_interaction_architecture_has_one_canonical_source() -> None:
    architecture = (DOCS / "referencia" / "ARQUITECTURA_Y_MODELO_ACTUAL.md").read_text(encoding="utf-8")
    first = (ROOT / ".assistant" / "00_LEER_PRIMERO.md").read_text(encoding="utf-8")
    criteria = (ROOT / ".assistant" / "05_CRITERIOS_INTERFAZ.md").read_text(encoding="utf-8")
    forms = (ROOT / ".assistant" / "05_FORMULARIOS_STREAMLIT.md").read_text(encoding="utf-8")
    pending = (OPERATIVE / "PENDIENTES_ACTIVOS.md").read_text(encoding="utf-8")

    assert '<a id="streamlit-interaction-invariant"></a>' in architecture
    assert "única fuente de verdad vigente" in architecture
    assert "setStateValue()" in architecture and "setTriggerValue()" in architecture
    assert "estado visual fino permanece en el navegador" in architecture
    assert "mount_view_scroll_keeper()" in architecture
    for text in (first, criteria, forms):
        assert "streamlit-interaction-invariant" in text
    assert "| PILOT-01G |" not in pending
    assert "| PILOT-01J |" not in pending
    assert "| PILOT-01M |" not in pending
    assert "PILOT-01M" in (OPERATIVE / "IMPLEMENTACIONES_REALIZADAS.md").read_text(encoding="utf-8")


def test_operational_docs_contain_only_canonical_active_documents() -> None:
    actual = {path.name for path in OPERATIVE.iterdir() if path.is_file()}
    assert actual == {
        "PENDIENTES_ACTIVOS.md",
        "IMPLEMENTACIONES_REALIZADAS.md",
        "ACTUALIZACION_ACTUAL.md",
        "ESTRATEGIA_DE_PRUEBAS.md",
        "GUIA_PRUEBA_PILOTO.md",
        "HOJA_DE_RUTA_PRE_RELEASE.md",
    }
    historical = DOCS / "historico" / "actualizaciones"
    assert (historical / "AUDITORIA_INTERFAZ_RC11_5_PASADAS.txt").is_file()
    assert (historical / "AUDITORIA_INTERFAZ_RC12_5_PASADAS.txt").is_file()
    assert (historical / "ACTUALIZACION_Y_PRUEBA_0.89.0_RC12.md").is_file()
