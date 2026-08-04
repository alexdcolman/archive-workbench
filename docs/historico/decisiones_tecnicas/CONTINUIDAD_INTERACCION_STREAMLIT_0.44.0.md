# Continuidad de interacción en Archive Workbench 0.44.0

## Problema observado

Archive Workbench ya conservaba la vista y la pestaña activas, pero una interacción local todavía podía reconstruir toda la aplicación. En un rebase, marcar la confirmación final cerraba el panel y desplazaba la página al inicio. En Revisión, seleccionar un objeto podía volver a ejecutar también la barra lateral, el encabezado y todo el resto de la vista.

No era una pérdida de datos: era una consecuencia del modelo normal de ejecución de Streamlit, donde los widgets fuera de un formulario provocan un rerun. Sin una frontera explícita, ese rerun alcanza al script completo.

## Política de 0.44.0

La aplicación distingue desde ahora dos tipos de actualización:

1. **Interacción local:** vuelve a ejecutar solamente la vista activa.
2. **Navegación entre vistas:** vuelve a ejecutar la aplicación completa para desmontar el modo anterior y montar el nuevo.

La distinción queda centralizada en `ui_navigation.py`:

- `fragmented_view`: monta el renderer activo como fragmento;
- `rerun_view`: solicita un rerun limitado al fragmento;
- `rerun_app`: reserva el rerun completo para cambios entre Inicio, Catálogo, Procesamiento, Revisión y las demás vistas;
- `isolated_view`: continúa garantizando que una vista anterior no quede superpuesta ni interactiva.

Ningún módulo de interfaz llama directamente a `st.rerun`. Una prueba de arquitectura impide que esa dispersión vuelva a introducirse.

## Confirmaciones transaccionales

Las confirmaciones peligrosas o finales se agrupan en formularios. Marcar una casilla ya no envía inmediatamente su valor al backend ni redibuja la página: la interacción se entrega en conjunto al presionar el botón de envío.

La política se aplica inicialmente a:

- aplicación final del rebase;
- conservación íntegra de una edición al cambiar la candidata;
- eliminación de una asociación archivística;
- resolución masiva de conflictos de intercambio;
- aplicación de un bundle con backup.

Además, el panel de rebase permanece desplegado mientras la candidata necesita resolución manual. Las selecciones internas recalculan únicamente ese fragmento y no reconstruyen el resto de la aplicación.

## Garantías y límites

Streamlit sigue siendo una aplicación reactiva: ciertos cambios deben recalcular datos y redibujar el fragmento que los contiene. La garantía de Archive Workbench no consiste en eliminar todos los reruns, sino en impedir que una interacción local reconstruya innecesariamente la aplicación completa, cambie de vista, pierda la pestaña activa o cierre una confirmación antes de enviarla.

Las operaciones que cambian de vista continúan usando un rerun completo de manera deliberada. Las operaciones que escriben en la base recalculan la vista activa para mostrar el estado persistido.

## Validación

La versión agrega pruebas que verifican:

- que la vista activa se renderice dentro de un fragmento;
- que los reruns locales y globales tengan ámbitos explícitos;
- que ningún archivo `*_app.py` invoque directamente `st.rerun`;
- que las confirmaciones de rebase estén dentro de formularios;
- que el panel de rebase permanezca abierto durante sus recalculaciones.

No se modifica el esquema de base de datos. La revisión continúa en `0032_page_quality_assessments`.

## Proyección manual de objetos anotados

La misma versión completa el caso pendiente en que un objeto editable con menciones, comentarios, etiquetas, parte documental, estado de revisión o reclasificación humana no puede asociarse con suficiente confianza a un bloque de la nueva candidata.

La vista previa calcula para cada destino sugerido:

- similitud textual;
- solapamiento posicional respecto de la proyección global;
- puntuación combinada y orden del bloque.

Si el texto del objeto anotado cambió demasiado o dos destinos resultan prácticamente equivalentes, Archive Workbench no traslada sus anotaciones por aproximación silenciosa. Presenta el objeto anterior y los bloques candidatos para que se elija explícitamente el destino. La decisión se revalida contra los identificadores actuales de la candidata y se registra como `manual_object_projection`.

Después de resolver la proyección se recalculan las menciones y los posibles conflictos de metadatos. Si la candidata cambió, la resolución queda invalidada y debe revisarse otra vez. No existe una opción de descartar silenciosamente el objeto anotado.
