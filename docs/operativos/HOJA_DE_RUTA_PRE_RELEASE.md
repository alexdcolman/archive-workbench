# Hoja de ruta pre-release y líneas paralelas — Archive Workbench

**Estado preparado:** 2026-08-27
**Versión de referencia:** 0.89.0 RC81

Esta hoja ordena el trabajo restante hasta v1.0. El detalle y el estado de cada bloque se mantienen en [`PENDIENTES_ACTIVOS.md`](PENDIENTES_ACTIVOS.md). Las líneas paralelas no bloquean la publicación inicial salvo decisión explícita posterior.

## Secuencia principal hasta v1.0

`OCR-01` quedó implementado, validado y cerrado en 0.83.0. `AV-01` quedó implementado, validado y cerrado en 0.84.0. `AV-02` quedó implementado, validado y cerrado en 0.85.0. `AV-03` quedó implementado, validado y cerrado en 0.86.0. `INT-01` quedó implementado, validado y cerrado en 0.87.0. `EXP-01` quedó implementado, validado y cerrado en 0.88.0.

1. Completar y validar `OPS-01`: validar RC81 primero en Windows CPU sobre selector, puerto/readiness, Google Drive y latencia de interfaz; sólo después continuar Windows GPU y macOS. RC80 ya quedó publicada y materialmente verde en Linux.
2. Retomar `WEB-01` sólo después de estabilizar la instalación pública y reescribir sitio/README bajo la regla de lectores sin conocimiento previo. La publicación final seguirá usando GitHub Pages.
3. Ejecutar `QA-01` junto con `OPS-02`.
4. Cerrar `OPS-03`, congelar contratos públicos y preparar la candidata a v1.0.

## Línea paralela vinculada

`UX-02` quedó cerrado por la recorrida manual posterior a RC70. `PILOT-01` quedó cerrado para pre-release en RC66. `GIAR-01` continúa como línea paralela porque reutiliza materiales, autoridades, unidades archivísticas y resultados de investigación reales. Su base debe vivir en un proyecto separado y persistente de Archive Workbench. La construcción del sitio público del Grupo de Investigación en Archivos de la Represión se realizará cuando el modelo de datos y los contenidos hayan sido revisados; no bloquea por sí sola la v1.0 de Archive Workbench.

El alcance completo se documenta en [`PROYECTO_PARALELO_GIAR.md`](../referencia/PROYECTO_PARALELO_GIAR.md).

## Trabajo posterior al release inicial

`AI-01` diseñará las etapas concretas del pipeline de análisis con LLM, sus contratos, ingeniería de contexto y trazabilidad. En ese momento se revisará el repositorio adicional que provea Alex para decidir qué componentes pueden reutilizarse. `vision_describe` consumirá las imágenes y recortes producidos por `EXP-01`.

`AI-02` agregará recuperación y generación trazables sobre corpus sistematizados, sin convertir respuestas automáticas en fuente de verdad.
