# Actualización actual - Archive Workbench 0.89.0 RC10

**Estado actualizado:** 2026-08-15  
**Bloque:** `PILOT-01` - inicio de `Procesar documentos` y reparación de preparación TIFF.

## Estado de partida

La validación audiovisual quedó aprobada en RC9. El proyecto persistente `/home/alex/projects/archive_app/pilot_data` conserva los 138 originales APM incorporados y la corrida audiovisual controlada ya revisada. No recrear el proyecto, no volver a incorporar archivos y no repetir la transcripción.

Se conservan las capacidades de onboarding ya validadas en 0.89.0: `archive-workbench review-app` abre el launcher cuando no recibe proyecto, Catálogo mantiene `Incorporar archivos por lote` y cada sección conserva `Guía de esta sección`. Estas funciones no se revalidan por RC10 porque el cambio actual no las toca.

La primera prueba de `Procesar documentos > Ejecutar > Preparar páginas` usó cinco casos reales. Los tres PDF se prepararon correctamente. `leg_15_a_c_2.tiff` y `leg_15_a_c_6.tiff` fallaron con `VipsForeignSaveWebpFile` / `tiff2vips: out of order read`.

## Cambio RC10

La rama pyvips abre TIFF grandes con `access="sequential"`. Antes de RC10 una misma imagen secuencial se usaba primero para guardar el derivado OCR y después para construir el preview. El primer guardado consume la lectura y el segundo puede pedir nuevamente la línea 0, que libvips rechaza.

RC10 conserva el modo secuencial y reabre la misma página para el preview. OCR y preview usan lecturas independientes; no se fuerza `access="random"` ni se carga el TIFF completo en memoria. Se agrega una regresión que simula una fuente secuencial y exige exactamente dos aperturas independientes para una página TIFF.

RC10 también aplica dos hallazgos de redacción de PILOT-01: la introducción de `Procesar documentos` nombra explícitamente los documentos, las versiones de texto y las páginas; se elimina `Las opciones técnicas aparecen solamente cuando corresponden`, porque la interfaz no necesita explicar su propia lógica de aparición.

No hay migración de base. La revisión sigue en `0046_audiovisual_timeline_annotations`.

## Estado de pendientes subsidiarios de PILOT-01

Tras la validación manual acumulada hasta RC9, `PILOT-01B` (continuidad y reruns), `PILOT-01C` (configuración/trazabilidad audiovisual) y `PILOT-01D` (temas y fechas históricas) se consideran validados y se trasladan a `IMPLEMENTACIONES_REALIZADAS.md`.

Siguen abiertos:

- `PILOT-01A`: modelo descriptivo de repositorios, colecciones, series, audiovisuales y agrupaciones de plataforma.
- `PILOT-01E`: identidad obligatoria y auditoría transversal de redacción explícita; RC10 corrige dos textos concretos de Procesar documentos, pero falta recorrer el resto de la app.
- `PILOT-01G`: inicialización masiva de páginas extraídas por documento y por lote de documentos, registrada durante la revisión manual y pendiente para la próxima candidata.
- `PILOT-01H`: replanteo integral de `OCR regional` para que propósito, pasos, plantillas y resultado se entiendan sin una guía externa.
- `PILOT-01I`: liberación automática de VRAM al finalizar una extracción individual o un lote completo, sin exigir un comando CLI normal de limpieza.
- `PILOT-01J`: replanteo de orientación, lenguaje y orden de tareas en `Revisar documentos`, incluida la comprensión de `Formulario`, síntesis por pestaña y auditoría estricta de referentes.

## Actualización local

Detener Streamlit. Aplicar el ZIP de RC10 sobre `~/projects/archive_app` y reinstalar el entorno editable con los mismos extras ya usados. **No ejecutar `db-upgrade`.**

## Pruebas automatizadas

Ejecutar únicamente los subsistemas afectados más documentación y recopilación completa. La candidata final contiene **134 pruebas focalizadas** en los cinco archivos afectados/trasversales y **568 tests recopilados** en 53 archivos. No repetir la suite completa costosa.

## Validación manual acumulada

La reparación TIFF quedó validada sobre `pilot_data`: `leg_15_a_c_2.tiff` y `leg_15_a_c_6.tiff` completaron la preparación sin `out of order read`. `PILOT-01F` pasa a implementaciones realizadas. No repetir esa preparación ni los tres PDF ya correctos.

`Extraer texto` se ejecutó después sobre los cinco documentos con el perfil principal de Surya. Resultado: 5 documentos completados, 0 advertencias, 0 fallos; `effective_backend=surya_cli`, `automatic_fallback=false` y `selection_policy=never`. La revisión visual ya aprobó las páginas 1 de ambos TIFF y las páginas 1, 2 y 4 de `caso_bolson.pdf`.

La revisión visual de las páginas previstas de `carp_reg.pdf` y `adm_pub_asp_contr.pdf` resultó satisfactoria; se observaron firmas representadas como `[Handwritten signature]` y varias anotaciones manuscritas recuperadas correctamente. Al iniciar la prueba de `OCR regional`, la propia interfaz no permitió comprender sin guía externa el propósito, el vocabulario, las plantillas ni la secuencia de acciones. El hallazgo queda abierto como `PILOT-01H` y debe corregirse en la próxima candidata.

Para continuar la prueba actual, usar sólo los controles reales verificados en RC10 y registrar cualquier nueva dependencia de explicación externa como evidencia del piloto.

## Actualización de validación 2026-08-15

La prueba de `OCR regional` creó correctamente una corrida nueva con 1 página y 1 objeto, sin modificar la selección de página previamente elegida. En `Selección canónica`, la columna `Selección vigente` conservó el texto completo seleccionado antes de la prueba y la columna `Candidata` mostró la corrida regional más reciente, que contiene solamente los objetos generados dentro de la zona definida. El resultado regional recuperó parcialmente el nombre y cargo impresos atravesados por la firma. Esta limitación se registra como posible optimización futura no bloqueante de `PILOT-01H`, sin asumir que caracteres físicamente ocultados puedan recuperarse siempre. La prueba también confirma que RC10 no integra automáticamente la región con la extracción general: ambas corridas se conservan por separado. `PILOT-01H` debe decidir y explicar si la función seguirá ofreciendo una alternativa regional parcial o si debe poder construir, mediante confirmación explícita, una versión integrada que conserve el resto de la página.

La validación continuó en `Revisar documentos`. Las acciones básicas solicitadas en la prueba –comparar imagen y texto, corregir texto, registrar comentario, aplicar etiqueta y dejar un estado de revisión– se realizaron correctamente. No se cierra todavía el recorrido de revisión porque faltan entidades, relaciones, búsqueda, exportación y las demás etapas del extremo a extremo.

Durante esta prueba se registraron nuevos problemas de comprensión: texto redundante en el historial de `Orden y estructura`; propósito poco claro de la pestaña `Formulario` y del bloque `Registrar casillero manual`; orden mejorable de `Datos adicionales` e `Historial general`; falta de una síntesis breve en cada pestaña; y una referencia implícita en `Crea sugerencias pendientes usando solamente el diccionario de autoridades del proyecto`. Estos puntos quedan en `PILOT-01J` y refuerzan `PILOT-01E`. Antes de empaquetar la próxima candidata se exigen cinco pasadas independientes sobre toda la aplicación para buscar referentes implícitos.

**Próximo paso del piloto:** continuar con entidades y menciones sobre el mismo documento ya revisado, y luego registrar una relación explícita antes de pasar a búsquedas.
