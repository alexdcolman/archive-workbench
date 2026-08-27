# CONTINUIDAD - Archive Workbench 0.89.0 RC11 / PILOT-01

**Fecha:** 2026-08-15  
**Estado:** candidata `0.89.0 RC11`, no publicada. Última publicación real: `v0.88.2`, commit `df118df30e63779d10681618bc2fa9dd173ce7a7`.

## 0. Instrucción principal

Leer primero este archivo completo. Después leer `.assistant/00_LEER_PRIMERO.md` y toda `.assistant/` en el orden obligatorio. Leer los documentos operativos vigentes, `docs/HISTORIAL_DE_CAMBIOS.md` y `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md`. Tratar esa documentación como fuente de verdad y no reconstruir el estado desde memoria conversacional.

PILOT-01 evalúa si una persona puede comprender y realizar las tareas sin una guía externa que compense defectos de la interfaz. Antes de dar instrucciones manuales, verificar la sección exacta de RC11 contra código y, cuando exista, contra una captura de esa misma candidata.

## 1. Estado que no debe repetirse

Proyecto persistente:

```text
/home/alex/projects/archive_app/pilot_data
```

No:

- recrear `pilot_data`;
- reincorporar los 138 originales;
- repetir la prueba audiovisual;
- volver a preparar los cinco documentos de la muestra;
- repetir por rutina la extracción Surya 5/5 ya validada;
- procesar el DOCX auxiliar como original;
- copiar resultados desde `project_data`;
- ejecutar `db-upgrade` por RC11;
- preparar commit/tag/push antes de validar la candidata.

La revisión DB sigue en `0046_audiovisual_timeline_annotations`.

## 2. Validaciones cerradas

- `PILOT-01B`: continuidad frente a reruns y contexto audiovisual.
- `PILOT-01C`: configuración y trazabilidad audiovisual.
- `PILOT-01D`: temas nativos y fechas históricas.
- `PILOT-01F`: preparación TIFF con pyvips.

Los dos TIFF reales `leg_15_a_c_2.tiff` y `leg_15_a_c_6.tiff` prepararon correctamente en RC10. La extracción Surya sobre los cinco documentos terminó 5/5, 0 advertencias y 0 fallos, con `effective_backend=surya_cli`, `automatic_fallback=false` y `selection_policy=never`.

La revisión visual prevista fue satisfactoria. En `carp_reg.pdf`, página 13, se creó además un resultado regional real sobre firma/nombre/cargo que recuperó parcialmente el texto impreso sin cambiar la selección previa. En `Revisar documentos` ya funcionaron comparar imagen/texto, corregir texto, comentario, etiqueta y estado de revisión.

## 3. Pendientes abiertos o parciales

- `PILOT-01A`: modelo descriptivo de repositorios, colecciones y audiovisual.
- `PILOT-01E`: identidad y redacción explícita transversal.
- `PILOT-01G`: preparación masiva para revisión, implementada en RC11 y pendiente de validación manual.
- `PILOT-01H`: replanteo de trabajo por zonas y uso local del OCR regional, implementado en RC11 y pendiente de validación manual.
- `PILOT-01I`: liberación automática de recursos Surya, implementada en RC11 y pendiente de validación manual.
- `PILOT-01J`: orientación/lenguaje/orden de `Revisar documentos`, implementado en RC11 y pendiente de validación manual.

## 4. Decisión RC11 sobre resultados regionales

Un resultado creado sobre una zona es parcial. No debe sustituir una página completa por defecto.

RC11 conserva la extracción general elegida para la página y permite usar un resultado regional como fuente de una corrección localizada: en `Procesar documentos > Elegir texto para revisar`, cuando se compara una corrida regional, la persona elige un objeto textual editable y puede reemplazar **solamente el texto de ese objeto** con el texto de la zona.

La operación:

- no cambia `ExtractionPageSelection`;
- no cambia `EditablePage.source_extraction_run_id`;
- incrementa la revisión del objeto;
- registra `regional_ocr_replace`;
- conserva procedencia hacia corrida, objeto y zona regional y el texto previo.

## 5. Otros cambios RC11

### Procesar documentos

- `OCR regional` pasa a **Trabajar una zona**.
- `Selección canónica` pasa a **Elegir texto para revisar**.
- Se reescriben los seis pasos del trabajo por zonas.
- Las plantillas se presentan como opción para reutilizar posiciones de zonas y pueden ignorarse si no existen.
- Se agrega **Preparar muchas páginas para revisión** por un documento o varios.
- Las páginas ya inicializadas se omiten; los resultados regionales no pueden preparar una página completa.
- `Extraer texto` usa vocabulario orientado a la tarea y relega perfil/motor/dispositivo a **Detalles técnicos del método**.

### Recursos Surya

- perfiles distribuidos: `surya_keep_server: false`;
- tarea individual: no mantiene servidor;
- lote: lo mantiene entre documentos;
- al terminar, la tarea llama `stop_surya_servers()` desde `finally`;
- la interfaz no exige `archive-workbench surya-server-stop` como paso normal.

### Revisar documentos

- `Formulario` explica casilleros, opciones marcadas y grupos;
- `Registrar casillero manual` pasa a **Agregar un casillero que no fue detectado**;
- cada pestaña operativa agrega una síntesis breve;
- `Datos adicionales` queda penúltima y `Historial general` última;
- se explicitan referentes en sugerencias, estados y acciones;
- se elimina la frase redundante del historial de orden/estructura.

## 6. Auditoría de interfaz

Antes del empaquetado se hicieron cinco pasadas independientes sobre 1.537 cadenas literales visibles de 12 vistas `*_app.py`: títulos/síntesis; rótulos/botones; ayudas/avisos; estados/resultados/historiales; bloques técnicos/avanzados. Resultado de controles automatizables: 0 botones con verbos genéricos sin objeto, 0 métricas de estado/resultado sin referente dentro del conjunto controlado, 0 reapariciones de las frases concretas señaladas en PILOT-01 y 0 coincidencias de los términos PILOT-01 controlados en el recorrido normal. El informe está en `docs/operativos/AUDITORIA_INTERFAZ_RC11_5_PASADAS.txt`.

## 7. Pruebas de construcción

Pasaron 201 pruebas focalizadas distribuidas en:

- `test_candidate_review.py`
- `test_processing.py`
- `test_surya_extraction.py`
- `test_region_extraction.py`
- `test_regional_workflow.py`
- `test_form_structure.py`
- `test_ui_navigation.py`
- `test_review.py`
- `test_documentation.py`
- `test_packaging.py`
- `test_discovery_grouping.py`
- `test_open_discovery.py`

`pytest --collect-only -q` recopiló 573 tests en 53 archivos. No se repitió la suite completa local costosa.

## 8. Próximo paso después de instalar RC11

Esperar primero las salidas de instalación y pruebas que Alex envíe. Si cierran, volver al mismo `pilot_data` y revalidar sólo los cambios nuevos de `Procesar documentos` y `Revisar documentos`.

La prueba debe comenzar sin explicar de antemano cada control. Observar si la propia interfaz permite entender:

1. para qué sirve **Trabajar una zona**;
2. qué hace un resultado regional y cómo reemplaza sólo un objeto textual en **Elegir texto para revisar**;
3. cómo funciona **Preparar muchas páginas para revisión**;
4. para qué sirve `Formulario` y cómo se organizan las pestañas de `Revisar documentos`.

Cuando algo no se entienda sin ayuda, registrarlo como hallazgo antes de destrabar el recorrido.

La liberación automática de Surya se valida después mediante una extracción mínima y controlada. No repetir el lote completo de cinco documentos sólo para esa comprobación.

## 9. Cierre y publicación

RC11 no se publica todavía. Después de la validación manual, revisar salidas, actualizar documentación, y sólo entonces preparar cierre local con commit/tag. El push sigue siendo un paso separado posterior.
