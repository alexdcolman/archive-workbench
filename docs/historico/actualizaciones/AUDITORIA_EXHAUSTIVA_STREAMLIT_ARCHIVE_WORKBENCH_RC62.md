# Auditoría exhaustiva de comportamiento Streamlit - Archive Workbench 0.89.0 RC62

**Fecha:** 2026-08-24  
**Base auditada:** `archive_workbench_v0.89.0_RC62.zip`  
**Revisión de base:** `0047_authority_relation_profiles`  
**Alcance:** toda la interfaz Streamlit y sus componentes interactivos propios.  
**Estado:** auditoría, sin modificaciones de código.

## 1. Fuente normativa usada

Se contrastó RC62 contra:

- `.assistant/00_LEER_PRIMERO.md`;
- `.assistant/00_CHECKLIST_CAMBIOS.md`;
- `.assistant/05_CRITERIOS_INTERFAZ.md`;
- `.assistant/05_FORMULARIOS_STREAMLIT.md`;
- `.assistant/01_INTERACCION_Y_GUIADO.md`;
- `.assistant/03_POLITICA_DE_PRUEBAS.md`;
- `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md#streamlit-interaction-invariant`.

Los criterios reactivos relevantes son, resumidos sin sustituir la documentación:

1. no envolver vistas enteras en `st.fragment`; sólo regiones autocontenidas;
2. mantener zoom, scroll y gestos visuales en el navegador, sin triggers a Python;
3. enviar a Python sólo acciones semánticas discretas;
4. hacer coincidir el alcance del rerun con el alcance de la acción;
5. conservar scroll mediante el mecanismo pasivo canónico;
6. aplicar estados pendientes antes de construir widgets y no corregir estado con reruns anidados;
7. probar interacciones nuevas y conservación de contexto;
8. cambiar de pestaña es navegación visual y no debe provocar un rerun completo;
9. los `st.expander` son sólo para información, historial o detalle técnico sin flujo reactivo;
10. toda escritura requiere botón explícito y no puede ejecutarse con Enter/Ctrl+Enter;
11. un `st.form_submit_button` no puede quedar deshabilitado a partir de un widget del mismo `st.form`;
12. no se asigna a `st.session_state[key]` después de instanciar en ese mismo rerun un widget con la misma key.

## 2. Método

Se revisaron los 18 módulos que contienen la UI Streamlit o sus componentes propios:

`admin_app.py`, `audiovisual_app.py`, `audiovisual_review_component.py`, `authority_app.py`, `catalog_app.py`, `catalog_tree.py`, `discovery_app.py`, `export_app.py`, `graph_app.py`, `graph_canvas.py`, `home_app.py`, `processing_app.py`, `region_canvas.py`, `review_app.py`, `review_canvas.py`, `semantic_app.py`, `ui_navigation.py`, `work_app.py`.

Se hizo además búsqueda estructural de:

- todas las llamadas a `tracked_tabs` y `st.tabs`;
- los 86 `st.expander` de las vistas;
- los 79 `st.form`;
- todos los `form_submit_button(..., disabled=...)`;
- las 15 entradas de fecha, incluidas las creadas desde columnas;
- asignaciones a `st.session_state` posteriores a widgets con la misma key;
- `st.fragment`;
- `rerun_view`, `rerun_app` y `st.rerun`;
- `setTriggerValue` / `setStateValue` en componentes v2;
- manejadores de teclado con Enter;
- callbacks `on_change` y `on_click`.

Como control de las protecciones existentes se ejecutó únicamente el gate focal `tests/test_ui_navigation.py`: sus 109 pruebas pasan. No se ejecutó la suite completa.

## 3. Resultado global

**RC62 no cumple todavía por completo las políticas Streamlit vigentes.**

La arquitectura canónica sí está correctamente aplicada en varias zonas importantes, pero quedan cinco clases de incumplimiento confirmado. Dos son sistémicas: las pestañas con rerun y los expanders interactivos. Las otras tres son defectos puntuales pero de alta prioridad porque contradicen reglas explícitas del proyecto.

## 4. Hallazgos confirmados

### H1 - Pestañas que fuerzan rerun completo - ALTA, sistémica

`tracked_tabs()` todavía tiene `rerun_on_change=True` como valor predeterminado y, en ese modo, crea `st.tabs(..., on_change="rerun")`. Esto contradice directamente el punto 8 del invariante: cambiar de pestaña sin cambiar el objeto de trabajo es navegación visual y no debe solicitar rerun completo.

Hay 14 usos de `tracked_tabs` en RC62. Cuatro ya son pasivos (`rerun_on_change=False`): Procesar documentos, Audio y video, detalle de Catálogo y pestañas del bloque activo en Revisar documentos. **Diez todavía fuerzan rerun**:

1. `export_app.py:660` - `export_audiovisual_tabs`;
2. `export_app.py:926` - `export_tabs`;
3. `review_app.py:495` - `launcher_tabs`;
4. `work_app.py:138` - `work_tabs`;
5. `admin_app.py:241` - `admin_tabs`;
6. `semantic_app.py:251` - `semantic_tabs`;
7. `graph_app.py:702` - `graph_tabs`;
8. `discovery_app.py:448` - `open_discovery_grouping_tasks`;
9. `discovery_app.py:837` - `open_discovery_review_modes_<run>`;
10. `authority_app.py:324` - `authority_tabs`.

Además, `tests/test_ui_navigation.py::test_tracked_tabs_use_native_state_and_rerun` todavía exige explícitamente `on_change="rerun"`. Es una protección obsoleta que contradice la fuente normativa actual. Otras pruebas más nuevas ya exigen el modo pasivo en Procesar documentos, Audio y video, Catálogo y Revisar documentos.

**Consecuencia probable:** reconstrucción completa, parpadeos, trabajo innecesario y mayor riesgo de que otros widgets reinterpreten estado al cambiar sólo de pestaña.

### H2 - Flujos reactivos dentro de `st.expander` - ALTA, sistémica

La política reserva `st.expander` a información, historial o detalles técnicos sin flujo reactivo. RC62 contiene 86 expanders. **Veintidós contienen controles interactivos directamente y uno contiene indirectamente un editor interactivo: 23 incumplimientos confirmados.**

#### Administración

- `admin_app.py:338` - tarjeta de backup: botón para volver a comprobar la copia.

#### Entidades y menciones

- `authority_app.py:890` - tarjeta de relación: edición, estado, formularios y botones.

#### Catálogo

- `catalog_app.py:572` - asignar la misma unidad a varios archivos;
- `catalog_app.py:610` - corregir excepciones de una subcarpeta;
- `catalog_app.py:955` - revisar estructura permitida; llama al editor interactivo `_render_catalog_structure_editor()`;
- `catalog_app.py:1108` - agregar unidad hija;
- `catalog_app.py:1752` - tarjeta de archivo: acciones, edición, navegación y desvinculación;
- `catalog_app.py:2091` - vincular un archivo digital ya registrado.

#### Exportar corpus

- `export_app.py:447` - filtro temporal de entidades y relaciones;
- `export_app.py:483` - configuración de separadores de páginas/bloques.

#### Explorar relaciones

- `graph_app.py:542` - Configurar mapa: formulario completo de filtros.

El expander `graph_app.py:1220`, "Ver texto vigente completo", **no se cuenta como incumplimiento**: su `text_area` está `disabled=True` y es sólo información.

#### Revisar documentos / Búsqueda textual

- `review_app.py:1588` - revisar posible casillero detectado;
- `review_app.py:1688` - agregar casillero no detectado;
- `review_app.py:1895` - administrar grupos de casilleros;
- `review_app.py:2413` - Más filtros de Búsqueda textual;
- `review_app.py:5010` - opciones de visualización;
- `review_app.py:5022` - herramientas de edición de páginas;
- `review_app.py:5056` - estado de revisión de la página;
- `review_app.py:5848` - restaurar revisión anterior.

El expander `review_app.py:5219`, "Datos del bloque de texto seleccionado", **no se cuenta**: el helper que contiene es informativo.

#### Búsqueda semántica

- `semantic_app.py:517` - opciones técnicas para construir índice;
- `semantic_app.py:581` - opciones técnicas para construir índice, variante según backend/capacidad.

#### Organizar trabajo

- `work_app.py:306` - tarjeta de asignación: formulario de edición y navegación.

**Consecuencia:** al interactuar, Streamlit rerunea y el expander no tiene un contrato persistente de apertura. Esto puede cerrar el lugar exacto donde se estaba trabajando, ocultar mensajes o hacer que la persona pierda contexto. El patrón ya fue eliminado en Procesar documentos y Audio y video, pero aún persiste en estas superficies.

### H3 - Formulario circular en Catálogo - ALTA, puntual

`catalog_app.py:1869-1879` contiene:

- checkbox `unlink_confirm` dentro del formulario;
- `form_submit_button(..., disabled=not unlink_confirm)` dentro del mismo formulario.

Esto es exactamente el patrón prohibido por `.assistant/05_FORMULARIOS_STREAMLIT.md`. Un checkbox dentro de `st.form` no rerunea antes del envío, por lo que no puede habilitar reactivamente el botón.

El resto de los `form_submit_button(..., disabled=...)` inspeccionados depende de estado externo o previamente calculado y no presenta esta dependencia circular.

Los **79 formularios** encontrados tienen `enter_to_submit=False`, lo cual sí cumple la política.

### H4 - Escritura audiovisual con Enter - ALTA, puntual

`audiovisual_review_component.py:465-469` captura Enter en el campo de anotación y llama `addNote()`. `addNote()` emite `setTriggerValue('action', {kind: 'annotation', ...})`, que termina registrando una anotación.

La política dice que toda escritura requiere botón explícito y que Enter/Ctrl+Enter no ejecutan escrituras. El botón de agregar nota ya existe, por lo que el manejador de Enter debe eliminarse.

Los Enter detectados en `review_canvas.py` y `graph_canvas.py` sólo realizan selección accesible de un objeto de dominio y no escriben en persistencia, por lo que no constituyen este incumplimiento.

### H5 - Modificación de key de widget después de instanciarlo - ALTA, puntual

`discovery_app.py` crea el selector:

`key="open_discovery_profile_selected"`

y, después de guardar una configuración en el mismo rerun, ejecuta:

`st.session_state["open_discovery_profile_selected"] = saved.id`

antes de `rerun_view(st)`.

Esto contradice la regla vigente: una key usada por un widget ya instanciado no se modifica en el mismo render. Debe encolarse un valor pendiente y aplicarse antes de construir el selector en el rerun siguiente.

Las otras coincidencias estáticas analizadas no son defectos: en Audio y video la asignación ocurre en la rama donde no se renderiza el selector, y en Intercambio ocurre en una rama mutuamente excluyente con el selector normal.

## 5. Aspectos que sí cumplen el invariante

### Fragmentos y alcance local

Sólo hay un `@st.fragment`: `review_app.py:5163`, alrededor de la región autocontenida de imagen, selector de bloque y editor del bloque activo. Documento y página quedan fuera. Es exactamente el patrón canónico definido por RC7/RC8.

### Continuidad vertical

`mount_view_scroll_keeper()` usa estado del navegador y `sessionStorage` sin emitir triggers a Python. Se monta transversalmente en la vista activa. Cumple el invariante.

### Componentes v2

- `catalog_tree.py`: expandir/cerrar ramas es local; sólo la selección de unidad llega a Python.
- `region_canvas.py`: dibujo local; sólo confirmar una caja emite `box_commit`.
- `review_canvas.py`: zoom, desplazamiento y dibujo quedan locales; la selección de bbox es acción semántica discreta.
- `graph_canvas.py`: drag/pan/zoom no emiten triggers; seleccionar nodo/arista sí, como acción semántica.
- `audiovisual_review_component.py`: reproducción y posición permanecen locales; las acciones de hablante/anotación son discretas. La única excepción es H4, porque la anotación puede dispararse con Enter.

### Procesar documentos

Las siete pestañas ya usan modo pasivo, la identidad documental está separada del nombre visible, no hay flujo reactivo dentro de expanders y la corrección del formulario de conservar edición sigue vigente. La auditoría no encontró un incumplimiento nuevo en esta sección.

### Audio y video

Las dos pestañas principales son pasivas y la reorganización RC61 eliminó los expanders interactivos de la superficie. Salvo H4, no se encontró un incumplimiento nuevo.

### Intercambiar cambios

La auditoría AST específica ya existente para esta vista sigue pasando y no se encontraron controles reactivos dentro de expanders del recorrido de intercambio. Los modos excepcionales usan estado persistente y acciones explícitas. No se reabre funcionalmente esta sección.

### Formularios y fechas

- 79 `st.form`: todos con `enter_to_submit=False`.
- 15 `date_input`: todos tienen límites mínimo y máximo explícitos.
- sólo se confirmó una dependencia circular de submit: H3.

### Reruns explícitos

Se revisaron los usos de `rerun_view` y `rerun_app`. La gran mayoría sigue a una escritura, reparación, navegación entre vistas o cambio explícito de objeto de dominio, por lo que un rerun completo puede estar justificado. No se identificó otra familia sistémica de reruns visuales aparte de H1. No se recomienda eliminar reruns mecánicamente.

## 6. Matriz por superficie

| Superficie | Estado frente a política Streamlit | Hallazgos |
|---|---|---|
| Inicio | Cumple | Sin hallazgos reactivos |
| Launcher Abrir/Crear proyecto | No cumple | H1: pestañas con rerun |
| Catálogo | No cumple | H2: 7 expanders interactivos contando editor indirecto; H3: formulario circular |
| Audio y video | Parcial | H4: Enter registra anotación; pestañas/expanders principales cumplen |
| Procesar documentos | Cumple | Sin hallazgos nuevos |
| Revisar documentos | No cumple | H2: 7 expanders interactivos propios de revisión; pestañas del bloque y fragmento cumplen |
| Búsqueda textual | No cumple | H2: `Más filtros` dentro de expander |
| Entidades y menciones | No cumple | H1: pestañas de ficha; H2: relación editable en expander |
| Buscar nuevas entidades | No cumple | H1: dos grupos de pestañas; H5: key modificada después de widget |
| Búsqueda semántica | No cumple | H1: pestañas; H2: dos expanders técnicos interactivos |
| Explorar relaciones | No cumple | H1: pestañas; H2: Configurar mapa en expander |
| Exportar corpus | No cumple | H1: dos grupos de pestañas; H2: dos expanders interactivos |
| Organizar trabajo | No cumple | H1: pestañas; H2: asignación editable en expander |
| Intercambiar cambios | Cumple | Sin hallazgos nuevos |
| Administrar y recuperar | No cumple | H1: pestañas; H2: botón dentro de expander de backup |

Nota: en Revisar documentos hay 8 expanders interactivos detectados dentro de `review_app.py`; uno corresponde a Búsqueda textual, por eso la matriz asigna 7 a Revisar documentos y 1 a Búsqueda textual.

## 7. Cobertura de tests: brecha detectada

`tests/test_ui_navigation.py` tiene 109 pruebas y pasa completo sobre RC62, pero no impide estos incumplimientos.

Brechas concretas:

- existe una prueba global AST para impedir controles reactivos dentro de expanders **sólo en Intercambiar cambios**, no en toda la app;
- existen pruebas pasivas de pestañas en algunas superficies, pero la prueba genérica de `tracked_tabs` todavía exige `on_change="rerun"`;
- hay regresiones focales de formularios, pero no un guard global contra `disabled` dependiente de widgets del mismo `st.form`;
- no hay guard contra escrituras disparadas por Enter en componentes propios;
- no hay guard global suficiente contra asignar a una key después de haber creado el widget correspondiente.

## 8. Orden recomendado de reparación

1. **Corregir `tracked_tabs` de forma sistémica:** hacer pasivo el comportamiento predeterminado, adaptar los 10 usos y retirar la prueba obsoleta que exige rerun. Conservar `request_tab()` para navegación programática posterior a acciones reales.
2. **Retirar los 23 flujos interactivos de `st.expander`:** sustituirlos por `st.toggle` persistente + `st.container(border=True)`, popover cuando sea realmente auxiliar y pequeño, o pasos explícitos. No cambiar contratos de dominio durante esta reparación.
3. **Corregir el formulario de desvinculación de Catálogo:** mantener submit habilitado y validar la confirmación después del envío.
4. **Eliminar Enter como escritura audiovisual:** conservar sólo el botón explícito para registrar la anotación.
5. **Corregir la selección de perfil de Descubrimiento:** usar una key pendiente aplicada antes de renderizar el selector.
6. **Agregar guardrails globales:** expanders interactivos, tabs pasivas, formularios circulares, Enter con escritura y mutación de keys después del widget.

Conviene hacerlo como un único bloque conceptual de conformidad Streamlit, pero con gates por superficie, para no mezclar esta reparación con cambios de dominio o UX no relacionados.

## 9. Conclusión

La app ya tiene correctamente estabilizadas las zonas donde los problemas fueron detectados y reparados durante el piloto, especialmente Procesar documentos, Audio y video, el fragmento localizado de Revisar documentos, el árbol de Catálogo y la continuidad de scroll. Sin embargo, **la política se aplicó históricamente de manera focal y no quedó todavía generalizada a toda la UI**.

Por eso RC62 no debe considerarse globalmente conforme al invariante Streamlit. Los defectos restantes son localizables y reparables sin migración ni cambios de modelo de datos, pero deben corregirse antes de considerar terminada la revisión transversal de interfaz.
