# Pendientes y mejoras — Archive Workbench

Documento consolidado a partir de la prueba piloto de la versión 0.33.0.

**Estado verificado:** 2026-08-02 · **versión:** 0.49.2. La lista operativa breve y vigente está en `PENDIENTES_ACTIVOS.md`. Este documento conserva también el historial de elementos resueltos, validados y decisiones fuera de alcance.

## Prioridad alta

1. **Revisión de corridas no canónicas — resuelto en 0.34.0**
   - Previsualizar texto, imagen y bounding boxes.
   - Inspeccionar una candidata en Procesamiento sin convertirla antes en canónica.
   - Comparar candidata y selección vigente.
   - Adoptar una nueva extracción de forma segura.
   - Diferenciar selección canónica de aprobación de calidad.

2. **Historial integrado de página — resuelto en 0.34.0**
   - Línea temporal única de ediciones, eliminaciones, agregados, divisiones, fusiones, reordenamientos y cambios de estado.
   - Mostrar estado anterior y posterior.
   - Integrar historial por objeto, estado de página, deshacer/rehacer y selección canónica.
   - Evitar una nueva funcionalidad aislada y dispersa.
   - Registrar también el estado OCR inicial.

3. **Gestión completa de relaciones — resuelto y validado en 0.46.0**
   - Confirmación explícita antes de crear.
   - No crear accidentalmente al pulsar `Enter`.
   - Permitir editar, eliminar, cambiar destino, tipo, evidencia y estado.
   - Mantener auditoría de todos los cambios.

4. **Control de calidad antes del análisis automático — cobertura parcial validada en 0.46.0**
   - Permitir excluir páginas `unreviewed`, `needs_review`, `rejected` o `stale`.
   - Exportación, búsqueda literal, búsqueda semántica y sugerencias transversales de entidades ya respetan el filtro y fueron validadas en 0.46.0.
   - Las sugerencias usan por defecto páginas `approved` y permiten ampliar el conjunto de estados de forma explícita.
   - Continúa pendiente verificar o extender la misma política a resúmenes, estadísticas y cualquier análisis automático nuevo.

5. **Evaluación automática de calidad de imagen — primer bloque en 0.35.0; presentación explicable en 0.36.0**
   - Inclinación, deformación, contraste, desenfoque y ruido.
   - Fragmentación, solapamiento de bboxes y objetos de uno o pocos caracteres.
   - Sugerir preprocesamiento conservador antes del OCR.

## OCR, layout y clasificación

6. **Preprocesamiento y OCR — flujo conservador en 0.36.0; procedencia visible en 0.36.1; Surya integrado en 0.37.0–0.37.1, preferido con fallback en 0.38.0, diagnóstico CPU corregido en 0.38.1 y primer control estructural en 0.39.0**
   - Autocontraste, Otsu y reducción de ruido mediana ya pueden versionarse como derivados OCR; deskew, dewarp, orientación y eliminación controlada de líneas continúan pendientes.
   - OCR regional para portadas e ilustraciones.
   - Comparar Tesseract con Surya u otro backend. **La evaluación empírica inicial sobre seis páginas reales favoreció claramente a Surya; desde 0.38.0 es el backend preferido con fallback Docling/Tesseract. Falta un benchmark con verdad terreno y CER/WER.**
   - Verificar uso real de CUDA y mantener ruta CPU. **La RTX 3090 ejecutó vLLM con picos de 100% de GPU y ~22,9 GB de VRAM. La ruta estable usa VLM en GPU y auxiliares Torch en CPU; Docling/Tesseract permanece como fallback.**
   - No usar restauración generativa que invente trazos.

7. **Fragmentación y orden**
   - Evitar extracción línea por línea cuando corresponde un párrafo.
   - Resolver yuxtaposiciones y orden incorrecto de bboxes.
   - Distinguir columnas reales de bullets o marcas marginales.
   - Evitar duplicaciones parciales.

8. **Tipos de objeto y ruido**
   - Mejorar detección de portadas, encabezados, pies y números de página.
   - Representar casilleros de formularios con estado `marcado`, `no marcado` o `indeterminado`. **0.39.0 detecta símbolos y marcas como candidatos revisables; falta la confirmación canónica y los casilleros vacíos sin objeto OCR.**
   - Detectar ordinales legales dudosos (`4º`, `5º`, etc.) como alertas revisables, sin corregirlos silenciosamente. **Primer bloque resuelto en 0.39.0 mediante secuencias conservadoras y detalle visible.**
   - Separar texto mecanografiado, manuscrito, firma, sello, ilustración y elementos preimpresos.
   - Filtrar líneas, marcos, manchas y caracteres aislados sin eliminar texto legítimo.

9. **Duplicados y versiones**
   - Detectar fojas duplicadas, copias o versiones más legibles.
   - Vincularlas sin sustituir el original.

## Grafo, alertas y visualización

10. **Grafo sin colisiones**
    - Garantizar que etiquetas de nodos y aristas nunca se superpongan.
    - Separar aristas paralelas y detectar colisiones.
    - Usar tooltips, curvatura y desplazamiento automático.

11. **Alertas reparables**
    - Identificar referencias huérfanas de migraciones anteriores.
    - Diferenciar alertas activas e históricas.
    - Incorporar limpieza o reparación con auditoría.

## Búsqueda y análisis

12. **Calibración semántica**
    - Ajustar el puntaje mínimo por perfil y modelo.
    - Evaluar consultas positivas, negativas y ambiguas.
    - Medir falsos positivos y falsos negativos.
    - Caso registrado en 0.46.0: una consulta sobre «dos anotaciones trasladadas a un destino común» recuperó un segundo bloque no pertinente con similitud `0.830`; no cambiar el umbral global sin un conjunto de evaluación.

13. **Descubrimiento automático abierto de actores, espacios, tiempos y acontecimientos — pendiente**
    - No confundir esta funcionalidad con la búsqueda actual por diccionario, que solo rastrea nombres preferidos y alias de entidades ya registradas.
    - Recorrer el corpus autorizado y proponer candidatos nuevos de: personas, organizaciones y actores colectivos; lugares y espacios; expresiones temporales y períodos; acontecimientos, acciones o procesos documentados.
    - Conservar para cada candidato el fragmento exacto, objeto y página de origen, offsets, tipo sugerido, confianza, método/modelo y versión.
    - Permitir revisar, aceptar, rechazar, modificar, agrupar y deduplicar candidatos. Una aceptación podrá vincular con una autoridad existente o iniciar la creación explícita de un nuevo registro; nunca deberá crear autoridades canónicas automáticamente.
    - No forzar actores, espacios, tiempos y acontecimientos dentro de una única tabla de «entidades»: cada clase deberá conservar su semántica y sus relaciones propias.
    - Respetar filtros de calidad de página, revisiones textuales y trazabilidad transrevisionaria.
    - Es técnicamente viable como una capa de sugerencias revisables, combinando reglas, modelos NER/event extraction o LLM locales; requiere antes definir contratos, persistencia y evaluación para cada clase de candidato.

## UX y arquitectura

14. **Evitar crecimiento fragmentario y acciones implícitas — continuidad validada en 0.47.0; entradas manuales resueltas en 0.48.0; confirmaciones circulares corregidas en 0.49.1**
    - Integrar nuevas funciones en flujos existentes.
    - Reducir pestañas y controles aislados.
    - Mantener una jerarquía clara entre extracción, revisión, calidad, entidades, grafo y exportación.
    - No duplicar estados, historiales ni acciones en lugares distintos.
    - Toda operación de escritura o confirmación usa botones explícitos y formularios con `enter_to_submit=False`.
    - 0.48.0 incorpora también texto manual, fragmentos de menciones y JSON de atributos del rebase a formularios propios, y oculta globalmente las instrucciones de teclado engañosas de Streamlit.
    - 0.49.1 corrige el bloqueo circular de casillas de confirmación dentro de formularios: el botón ya no depende del valor que el propio formulario todavía no envió; la confirmación se valida al pulsarlo.


## Exportación

15. **Administración de perfiles de exportación — resuelta y validada en 0.49.1**
    - Permite archivar, restaurar y eliminar perfiles con confirmación explícita.
    - Las exportaciones históricas materializadas y sus hashes se conservaron después de eliminar el perfil.
    - Queda pendiente únicamente la desincronización visual descrita en el punto 25: después de una acción de ciclo de vida puede coexistir transitoriamente el formulario anterior con “Crear un perfil nuevo”.

16. **Confirmación visible de exportación — resuelta y validada en 0.49.1**
    - La notificación de éxito persiste entre reruns hasta cerrarla explícitamente.
    - Incluye ruta, formato, registros, caracteres, tamaño y SHA-256.
    - Ofrece descarga directa del archivo materializado.
    - La validación manual confirmó la creación del archivo, el hash coincidente, la persistencia de la confirmación y la conservación del historial.


## Intercambio offline

17. **Separar ascendencia de eventos y hash de estado — resuelto y validado en 0.48.0**
    - Los bundles aplicados crean checkpoints de ascendencia y registran secuencias remotas incorporadas.
    - Un segundo bundle incremental reconoce la base común aunque el receptor haya agregado cambios locales y su hash final sea distinto.
    - La prueba manual confirmó dos aplicaciones sucesivas, una divergencia local intermedia y la coexistencia de los tres cambios sin conflictos espurios.

18. **Gestión de bundles obsoletos — resuelta y validada en 0.49.1**
    - Bloquea la aplicación de un dry-run caduco antes de crear backup o modificar datos.
    - Explica la secuencia y el evento local posterior que lo volvió obsoleto.
    - Archivar, restaurar y limpiar una entrada no aplicada fue validado sin modificar el corpus ni crear backups innecesarios; las aplicaciones anteriores conservaron su auditoría.


19. **Resolución segura de bundles sin base reconocida — resuelta y validada en 0.49.1**
    - Corrige el `NameError`, agrupa todos los campos por evento y presenta una explicación global de la ascendencia no reconocida.
    - La prueba manual mostró tres eventos y 21 campos; la aceptación masiva de valores recibidos no está disponible para creaciones sin base verificable.
    - `Finalizar resoluciones` y `Aplicar bundle` permanecen bloqueados mientras haya decisiones pendientes.
    - **Pendiente separado:** recuperación asistida de linaje y creación de una nueva base común verificada, descrita en el punto 26.


20. **Orden cronológico correcto de backups — resuelto y validado en 0.48.0**
    - Los backups se ordenan por `created_at` real y el más reciente queda seleccionado por defecto.
    - La prueba de recuperación registra el archivo y hash exactos sin modificar el proyecto activo.
    - La restauración real crea un backup automático previo, conserva integridad y claves foráneas y restaura el estado esperado.


## Corrección de precisión: relaciones — resuelta y validada en 0.46.0

La interfaz impide la creación accidental con `Enter`, exige confirmación explícita, permite editar tipo, evidencia, temporalidad, destino y estados, y representa la eliminación como baja lógica auditable. La prueba manual confirmó creación, edición, cambio de destino, baja lógica y conservación de todas las revisiones.

## Integridad de menciones

21. **Impedir menciones aceptadas sin autoridad — invariante resuelta y validada en 0.47.0**
    - La UI y la capa de dominio rechazan `accepted` o `modified` con `authority_id = NULL`.
    - La prueba manual confirmó que una mención puede pasar a `pending` sin autoridad y volver a `accepted` únicamente al vincularla.
    - Continúan pendientes una acción abreviada rotulada “Vincular y aceptar” y la reparación asistida de menciones huérfanas históricas.


22. **Deduplicación y vinculación de menciones por posición — identidad transrevisionaria resuelta en 0.47.0**
    - Detectar existentes por objeto, revisión y offsets, no solo por `authority_id`.
    - Vincular una mención huérfana existente en lugar de crear otra.
    - Mostrar conflicto si los mismos offsets están vinculados a otra autoridad.
    - Impedir menciones activas duplicadas sobre el mismo fragmento, incluso cuando una edición desplaza los offsets y cambia la revisión textual.
    - 0.47.0 agrega proyección conservadora y diagnóstico `graph_duplicate_mention`.
    - Continúa pendiente la fusión y limpieza asistida de duplicados históricos ya existentes.


23. **Auditar toda modificación de vínculos de menciones — núcleo de UI y dominio validado en 0.47.0**
    - Toda alteración de `authority_id` desde la interfaz crea una revisión append-only; la prueba manual confirmó la secuencia `create → unlink → relink` sin registrar intentos inválidos.
    - Las migraciones y el intercambio deben conservar los vínculos canónicos.
    - La regresión de migración quedó cubierta en 0.49.1. Continúan pendientes la comparación periódica entre la fila vigente y el último snapshot, la reparación de divergencias no auditadas y pruebas específicas de intercambio.


24. **Migración 0027 sin pérdida de claves foráneas — resuelta y validada en 0.49.1**
    - Agrega las columnas temporales sin recrear `authority_records`.
    - La regresión parte de `0026_team_workflow` con dos autoridades, alias, revisiones append-only, una mención `accepted` vinculada y una relación entre autoridades.
    - Después de migrar hasta `0033_export_exchange_lifecycle`, conserva exactamente los UUID, vínculos, estados y cantidades de filas; `PRAGMA foreign_key_check` devuelve vacío.
    - También pasaron las rutas complementarias desde 0031 y 0032 y el archivo completo `tests/test_database.py`.
    - La reparación retrospectiva de bases piloto descartables continúa fuera de alcance, según la decisión documentada debajo; no es un bloqueante activo.


25. **Sincronización visual de perfiles de exportación tras archivar, restaurar o eliminar — pendiente**
    - Después de una acción de ciclo de vida, el selector puede indicar un perfil mientras el formulario muestra “Crear un perfil nuevo”, o pueden coexistir dos árboles hasta cambiar manualmente la selección.
    - Las operaciones, los archivos y el historial permanecen correctos; falta forzar un rerun completo o limpiar el estado de selección para renderizar un único formulario coherente.

26. **Recuperación asistida de linaje y creación de base común verificada — pendiente**
    - Para bundles `unmatched`, recuperar parentesco solamente desde checkpoints, bundles, manifiestos o backups verificables.
    - Si no puede recuperarse, permitir establecer una nueva base común mediante una operación independiente, explícita y auditable que identifique copias, estado adoptado, responsable y evidencia.
    - Resolver campos o aceptar contenido recibido no debe crear parentesco automáticamente.

27. **Clasificación formal de la suite de pruebas — pendiente de ingeniería**
    - Conservar todas las pruebas actuales, pero marcarlas como rápidas, integración y lentas.
    - En cada versión ejecutar el subsistema afectado, las transversales pertinentes y una recopilación completa; reservar la suite monolítica para la validación final local.
    - No eliminar pruebas sin demostrar redundancia exacta o retiro deliberado del comportamiento cubierto.


## Decisión de alcance: datos piloto descartables

La reparación retrospectiva de bases afectadas queda fuera de alcance.

El pendiente bloqueante se reduce a:

- corregir el código de migración para instalaciones nuevas y actualizaciones futuras;
- agregar pruebas de regresión que garanticen la conservación de menciones y relaciones;
- permitir limpiar y regenerar las capas derivadas del proyecto piloto;
- conservar catálogo, originales, procesamiento y extracción.

La indicación anterior de crear una migración de reparación para esta base queda anulada.


---

# Prioridad de implementación posterior al piloto

## Bloqueantes

No quedan bloqueantes activos en la ruta soportada de actualización. La migración 0027 y sus regresiones quedaron resueltas y validadas en 0.49.1. Las reparaciones históricas de menciones y duplicados continúan como alta prioridad, pero no bloquean bases nuevas ni actualizaciones verificadas.

## Alta prioridad

6. Gestión completa y segura de relaciones. **Resuelto y validado en 0.46.0.**
7. Historial integrado y auditable. **Resuelto en 0.34.0.**
8. Comparación y adopción segura de extracciones candidatas. **Resuelto en 0.34.0; 0.40.0 agrega rebase transaccional, 0.41.0 resuelve conflictos de menciones, 0.42.0 incorpora resolución asistida de conflictos textuales, 0.43.0 absorbe el estado estructural activo y resuelve partes documentales, estados de revisión y tipos incompatibles, 0.44.0 permite decidir manualmente proyecciones estructurales débiles o ambiguas, 0.45.0 resuelve atributos especializados y 0.47.0 permite ciclos `A → B → A → B` conservando procedencia e historial.**
9. Orden cronológico correcto de backups. **Resuelto y validado en 0.48.0.**
10. Limpieza y explicación de alertas históricas.

## Mejora funcional

11. Control de calidad automático de página. **Primer bloque en 0.35.0; indicadores explicables en 0.36.0.**
12. Preprocesamiento OCR conservador. **Primer flujo reproducible resuelto en 0.36.0.**
13. Evaluación de Surya y CUDA. **Prueba real completada y documentada en 0.38.0; Surya queda preferido con servidor persistente y fallback automático; 0.38.1 alinea el dispositivo auxiliar y 0.39.0 agrega alertas estructurales. Pendientes: CER/WER y lotes mayores.**
14. Mejoras de layout, columnas, ruido y clasificación. **0.39.0 incorpora el primer control revisable de ordinales y casilleros; faltan confirmación canónica, grupos de formulario y resaltado específico.**
15. Grafo sin colisiones de texto.
16. Calibración de búsqueda semántica.
17. Administración de perfiles y notificaciones de exportación. **Resueltas y validadas en 0.49.1; queda pendiente la sincronización visual posterior a acciones de ciclo de vida.**
18. Descubrimiento automático abierto de actores, espacios, tiempos y acontecimientos como sugerencias revisables. **Pendiente; no equivale al rastreo por diccionario de autoridades existentes. El filtro de calidad ya disponible deberá reutilizarse.**
19. Continuidad de interacción de la interfaz. **Base resuelta en 0.44.0; 0.45.0 corrige la habilitación circular de botones, 0.46.0 vuelve autocontenido el árbol de cada fragmento, 0.47.0 valida que no reaparezca la vista anterior oscurecida y amplía la verificación AST a formularios anidados, y 0.48.0 hace explícitas las tres entradas manuales del rebase y elimina las instrucciones `Press Enter…`. Queda pendiente la desincronización visual de perfiles de exportación del punto 25.**
20. Recuperación asistida de linaje o creación de base común verificada para bundles `unmatched`. **Pendiente; resolver contenido no debe crear parentesco.**
21. Clasificación formal de tests rápidos, integración y lentos. **Pendiente de ingeniería; no implica eliminar cobertura.**
