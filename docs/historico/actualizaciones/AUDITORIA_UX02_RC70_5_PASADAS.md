# Auditoría UX-02 de complejidad acumulada - Archive Workbench 0.89.0 RC70

**Fecha:** 2026-08-25  
**Base auditada:** RC69, después de la validación manual de `DISC-03` con `local_rules_v5`  
**Alcance:** revisión transversal estática y semántica de la interfaz vigente; no sustituye la validación manual final de UX-02 sobre `pilot_data`.

## Fuente normativa

La auditoría se contrastó con `.assistant/00_CHECKLIST_CAMBIOS.md`, `.assistant/05_CRITERIOS_INTERFAZ.md`, `.assistant/05_FORMULARIOS_STREAMLIT.md`, la sección **Interfaz y formularios** de `docs/operativos/IMPLEMENTACIONES_REALIZADAS.md` y el invariante canónico de interacción Streamlit en `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md`.

Se revisaron `home_app.py`, `catalog_app.py`, `audiovisual_app.py`, `processing_app.py`, `review_app.py`, `work_app.py`, `semantic_app.py`, `authority_app.py`, `discovery_app.py`, `graph_app.py`, `export_app.py` y `admin_app.py`, además de los componentes auxiliares de revisión, regiones, grafo y audiovisual.

## Pasada 1 - títulos, navegación y propósito

No se detectaron nuevas secciones principales sin ayuda contextual ni una reaparición de navegación por capas simultáneas en las superficies ya depuradas por UX-04 y PILOT-01. Los remanentes concretos se concentraban en **Revisar documentos > Casilleros y campos**, donde varias tareas distintas se mostraban a la vez dentro de una única pestaña.

RC70 sustituye esa acumulación por un selector compacto que muestra una sola tarea por vez: revisar detecciones, agregar manualmente, revisar confirmados, administrar grupos o consultar historial. La página continúa visible en la columna izquierda mientras se trabaja con cualquiera de esas tareas; no se agrega una segunda imagen ni otra navegación paralela.

## Pasada 2 - rótulos, botones y selectores

Hallazgos corregidos:

- `Casilleros y campos` presentaba simultáneamente tres controles de apertura, la edición de confirmados y el historial. RC70 usa una sola elección de tarea y mantiene todos los formularios existentes dentro del recorrido elegido.
- `Procesar documentos` conservaba dos rótulos genéricos `Más opciones`. El identificador de una lectura regional pasa a **Cambiar el identificador de esta lectura** y la extracción general expone directamente **Crear una nueva versión aunque ya exista una equivalente**.
- `Leer una zona` vuelve a mostrar de forma explícita el orden operativo de seis pasos sin agregar decisiones nuevas.

## Pasada 3 - ayudas, avisos, errores y confirmaciones

`Casilleros y campos` incorpora ayuda contextual por tarea mediante el mismo mecanismo usado por otros selectores compactos. La explicación visible se limita a aclarar qué representan los casilleros y grupos y que una detección automática sigue siendo una propuesta hasta confirmación humana.

No se encontraron nuevas alertas permanentes, confirmaciones duplicadas o mensajes técnicos dominando el recorrido principal en las demás vistas auditadas.

## Pasada 4 - estados, resultados e historiales

La pestaña de casilleros reemplaza tres métricas visualmente pesadas por un resumen compacto de casilleros confirmados, grupos y propuestas pendientes. El historial de casilleros y grupos deja de competir con las tareas de edición y se renderiza sólo cuando se lo selecciona.

En **Orden y estructura**, la propuesta conserva la referencia visual sobre la página y la acción explícita de confirmación. La tabla completa del orden propuesto, que puede crecer con cada bloque de texto, pasa a **Ver detalle del orden propuesto**, cerrado por defecto.

## Pasada 5 - opciones técnicas o avanzadas

Las opciones técnicas de OCR regional continúan cerradas por defecto. El identificador técnico de la lectura regional sólo aparece después de solicitar **Cambiar el identificador de esta lectura**. En la extracción general se elimina el contenedor genérico `Más opciones`: la única decisión que contenía queda nombrada directamente.

Los demás detalles técnicos encontrados en la auditoría continúan dentro de expanders informativos o paneles ya validados; no se detectó una razón material para reabrir Entidades, grafo, exportación, intercambio o administración.

## Resultado y límite

RC70 implementa la primera depuración transversal de `UX-02` sobre los remanentes documentados y sobre dos rótulos genéricos encontrados durante la auditoría. No cambia contratos de dominio, persistencia, OCR, extracción, revisión ni historial. No hay migración.

`UX-02` permanece **PARCIAL** hasta una recorrida manual representativa sobre `pilot_data`, concentrada en **Casilleros y campos**, **Orden y estructura** y **Leer una zona**, más una pasada libre por las demás secciones para confirmar que no existe otra acumulación visual material que la auditoría estática no pueda detectar.
