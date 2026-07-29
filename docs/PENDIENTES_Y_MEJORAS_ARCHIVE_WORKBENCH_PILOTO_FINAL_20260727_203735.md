# Pendientes y mejoras — Archive Workbench

Documento consolidado a partir de la prueba piloto de la versión 0.33.0.

## Prioridad alta

1. **Revisión de corridas no canónicas**
   - Previsualizar texto, imagen y bounding boxes.
   - Abrir una candidata en Revisión sin convertirla antes en canónica.
   - Comparar candidata y selección vigente.
   - Adoptar una nueva extracción de forma segura.
   - Diferenciar selección canónica de aprobación de calidad.

2. **Historial integrado de página**
   - Línea temporal única de ediciones, eliminaciones, agregados, divisiones, fusiones, reordenamientos y cambios de estado.
   - Mostrar estado anterior y posterior.
   - Integrar historial por objeto, estado de página, deshacer/rehacer y selección canónica.
   - Evitar una nueva funcionalidad aislada y dispersa.
   - Registrar también el estado OCR inicial.

3. **Gestión completa de relaciones**
   - Confirmación explícita antes de crear.
   - No crear accidentalmente al pulsar `Enter`.
   - Permitir editar, eliminar, cambiar destino, tipo, evidencia y estado.
   - Mantener auditoría de todos los cambios.

4. **Control de calidad antes del análisis automático**
   - Permitir excluir páginas `unreviewed`, `needs_review`, `rejected` o `stale`.
   - Aplicar el filtro a entidades, relaciones, embeddings, resúmenes, estadísticas y exportaciones.
   - Usar por defecto solo páginas `accepted` o `approved`.

5. **Evaluación automática de calidad de imagen**
   - Inclinación, deformación, contraste, desenfoque y ruido.
   - Fragmentación, solapamiento de bboxes y objetos de uno o pocos caracteres.
   - Sugerir preprocesamiento conservador antes del OCR.

## OCR, layout y clasificación

6. **Preprocesamiento y OCR**
   - Deskew, dewarp, orientación, autocontraste, binarización, reducción de ruido y eliminación controlada de líneas.
   - OCR regional para portadas e ilustraciones.
   - Comparar Tesseract con Surya u otro backend.
   - Verificar uso real de CUDA y mantener ruta CPU.
   - No usar restauración generativa que invente trazos.

7. **Fragmentación y orden**
   - Evitar extracción línea por línea cuando corresponde un párrafo.
   - Resolver yuxtaposiciones y orden incorrecto de bboxes.
   - Distinguir columnas reales de bullets o marcas marginales.
   - Evitar duplicaciones parciales.

8. **Tipos de objeto y ruido**
   - Mejorar detección de portadas, encabezados, pies y números de página.
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

13. **Entidades automáticas como sugerencias**
    - Detectar candidatos sin escribir entidades canónicas automáticamente.
    - Revisar, aceptar, rechazar o modificar sugerencias.
    - Respetar filtros de calidad de página.

## UX y arquitectura

14. **Evitar crecimiento fragmentario**
    - Integrar nuevas funciones en flujos existentes.
    - Reducir pestañas y controles aislados.
    - Mantener una jerarquía clara entre extracción, revisión, calidad, entidades, grafo y exportación.
    - No duplicar estados, historiales ni acciones en lugares distintos.


## Exportación

15. **Administración de perfiles de exportación**
    - Permitir eliminar o archivar perfiles.
    - Exigir confirmación antes de eliminar.
    - No borrar exportaciones históricas ya materializadas.
    - Mostrar qué exportaciones dependen del perfil.

16. **Confirmación visible de exportación**
    - Mostrar notificación inequívoca de éxito.
    - Incluir ruta, formato, registros y caracteres.
    - Ofrecer acceso directo al archivo o carpeta.
    - Mostrar errores de escritura con el mismo nivel de visibilidad.


## Intercambio offline

17. **Separar ascendencia de eventos y hash de estado**
    - Registrar qué bundles y secuencias remotas fueron incorporados.
    - Reconocer una base común aunque el estado final haya divergido por resolución local.
    - Usar el hash como prueba del estado, no como única prueba de parentesco.
    - Comparar cambios posteriores desde la secuencia remota conocida.
    - Clasificar como conflicto solo campos realmente superpuestos.
    - Evitar que una divergencia histórica convierta miles de eventos posteriores en `review`.

18. **Gestión de bundles obsoletos**
    - Permitir archivar o limpiar entradas `stale`.
    - Explicar por qué un bundle quedó obsoleto.
    - Conservar auditoría sin saturar la vista operativa.


19. **Resolución segura de bundles sin base reconocida**
    - No presentar miles de eventos homogéneos como decisiones manuales independientes.
    - Detectar el caso global de ascendencia no reconocida.
    - Impedir acciones masivas incompatibles con creaciones conflictivas.
    - Explicar claramente qué operaciones pueden o no aceptarse.
    - Ofrecer recuperación de linaje o creación de una nueva base común verificada.


20. **Orden cronológico correcto de backups**
    - Ordenar por `created_at` del manifiesto o fecha real, no por nombre.
    - Mostrar qué backup se considera el más reciente.
    - Vincular claramente cada prueba de recuperación con su archivo y hash.
    - Evitar falsos avisos de backup no probado.


## Corrección de precisión: relaciones

La interfaz actual ya permite editar el tipo, la evidencia, la temporalidad, el estado de revisión y el ciclo de vida. Los pendientes específicos son:

- impedir la creación accidental con `Enter`;
- agregar confirmación inequívoca;
- permitir cambiar el destino;
- presentar una acción explícita de eliminar o archivar;
- explicar que `inactiva` es una baja lógica;
- conservar el historial de la baja o modificación.

## Integridad de menciones

21. **Impedir menciones aceptadas sin autoridad**
    - No permitir `accepted` o `modified` con `authority_id = NULL`.
    - Validar tanto en UI como en la capa de dominio.
    - Ofrecer “Vincular y aceptar” como acción única.
    - Detectar y reparar menciones huérfanas existentes.


22. **Deduplicación y vinculación de menciones por posición**
    - Detectar existentes por objeto, revisión y offsets, no solo por `authority_id`.
    - Vincular una mención huérfana existente en lugar de crear otra.
    - Mostrar conflicto si los mismos offsets están vinculados a otra autoridad.
    - Impedir menciones activas duplicadas sobre el mismo fragmento.
    - Incorporar fusión y limpieza de duplicados históricos.


23. **Auditar toda modificación de vínculos de menciones**
    - Toda alteración de `authority_id` debe crear una revisión.
    - Las migraciones y el intercambio deben conservar los vínculos canónicos.
    - Comparar periódicamente la fila actual con el último snapshot.
    - Alertar y reparar divergencias no auditadas.
    - Añadir pruebas de regresión para creación, aceptación, migración, intercambio y reapertura.


24. **Corregir la migración 0027 — bloqueante**
    - No recrear `authority_records` mediante batch con claves foráneas activas.
    - Agregar las columnas temporales con `ALTER TABLE ADD COLUMN` cuando sea posible.
    - Añadir una prueba de regresión con autoridades, menciones y relaciones preexistentes.
    - Verificar que una migración conserve exactamente todos los UUID y vínculos.
    - Crear una migración de reparación para bases ya afectadas.
    - Recuperar menciones desde revisiones/eventos y relaciones desde eventos o backups.
    - Ejecutar `foreign_key_check` y controles semánticos antes y después de migrar.


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

1. Migración 0027 sin pérdida de claves foráneas.
2. Pruebas de regresión de migraciones con autoridades, menciones y relaciones.
3. Integridad de menciones: autoridad obligatoria para estados aceptados.
4. Deduplicación por objeto, revisión y offsets.
5. Seguimiento de ascendencia independiente del hash de estado.

## Alta prioridad

6. Gestión completa y segura de relaciones.
7. Historial integrado y auditable.
8. Comparación y adopción segura de extracciones candidatas.
9. Orden cronológico correcto de backups.
10. Limpieza y explicación de alertas históricas.

## Mejora funcional

11. Control de calidad automático de página.
12. Preprocesamiento OCR conservador.
13. Evaluación de Surya y CUDA.
14. Mejoras de layout, columnas, ruido y clasificación.
15. Grafo sin colisiones de texto.
16. Calibración de búsqueda semántica.
17. Administración de perfiles y notificaciones de exportación.
18. Identificación automática de entidades como sugerencias revisables.
