# Conflictos textuales de rebase y aislamiento de vistas en Archive Workbench 0.42.0

## 1. Problemas resueltos

La versión 0.41.0 permitía relocalizar o rechazar menciones ambiguas, pero seguía bloqueando cualquier corrección humana que se superpusiera con un cambio diferente de la nueva candidata OCR. Además, una navegación desde `Procesamiento → Selección canónica` hacia `Revisión` podía dejar visible e interactiva una copia oscurecida de la vista anterior, incluso después de cambiar a otras secciones.

La versión 0.42.0 resuelve ambos problemas sin eliminar las restricciones conservadoras del rebase.

## 2. Resolución asistida de conflictos textuales

El rebase continúa comparando tres estados:

```text
extracción anterior
edición humana vigente
nueva candidata OCR
```

Cuando la edición humana y la candidata modifican de manera diferente el mismo tramo, la vista previa crea un conflicto textual estructurado. Cada conflicto conserva:

- un identificador estable;
- el fragmento de la extracción anterior;
- la corrección humana;
- el fragmento de la candidata;
- el contexto del cambio;
- el motivo del bloqueo.

La persona usuaria debe elegir explícitamente una de estas acciones:

1. conservar la lectura de la candidata;
2. reaplicar la corrección humana;
3. escribir el texto resultante exacto para ese tramo.

Ninguna opción se aplica por defecto. El texto manual reemplaza solamente el tramo conflictivo mostrado, no el objeto completo.

## 3. Revalidación y seguridad

Cada resolución conserva una copia del fragmento humano y del fragmento candidato que estaban visibles al tomar la decisión. Si alguno cambia antes de aplicar el rebase, la resolución queda inválida y debe revisarse nuevamente.

Después de cada decisión, Archive Workbench reconstruye la vista previa completa. Las menciones se vuelven a calcular sobre el texto resultante, porque una decisión textual puede cambiar sus offsets o sus destinos posibles.

El botón de aplicación permanece deshabilitado mientras exista:

- un conflicto textual sin resolución confirmada;
- una mención sin destino válido;
- una acción estructural previa de división, unión, reordenamiento o deshacer/rehacer;
- un conflicto de parte documental, estado de revisión o etiqueta.

La operación final sigue siendo transaccional y append-only. La revisión de página registra la cantidad de decisiones textuales manuales y sus métodos (`manual_keep_candidate`, `manual_apply_human` o `manual_custom_text`).

## 4. Aislamiento atómico de la vista principal

La superposición visual no provenía de la base de datos ni del rebase. Streamlit estaba reconciliando árboles de componentes complejos pertenecientes a dos vistas distintas. Una pestaña persistente de Procesamiento podía quedar montada debajo de Revisión o Catálogo y continuar recibiendo clics.

La corrección se aplica en la raíz de la aplicación:

- todas las navegaciones entre vistas pasan por `request_app_view`;
- cada vista completa se renderiza dentro de un único `st.empty` estable;
- el contenido interno usa una identidad distinta por modo mediante `isolated_view`;
- al cambiar de vista, Streamlit desmonta el árbol anterior completo antes de montar el nuevo.

La regla cubre Inicio, Catálogo, Procesamiento, Trabajo, Revisión, búsquedas, Entidades, Grafo, Exportar, Intercambio y Administración. No es un parche específico del botón “Abrir esta página en Revisión”.

## 5. Límites que permanecen

Esta versión no agrega un modo forzado para acciones estructurales previas ni decide automáticamente entre metadatos incompatibles. Esos casos continúan bloqueados porque pueden alterar la estructura documental o trasladar anotaciones a un destino incorrecto.

Tampoco modifica autoridades canónicas ni relaciones. Las decisiones textuales afectan únicamente al texto que servirá como nueva base editable y, después, a la relocalización revisable de sus menciones.

## 6. Persistencia y migraciones

No hay migración nueva. La revisión de base continúa en:

```text
0032_page_quality_assessments
```
