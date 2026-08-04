# Resolución asistida de conflictos de rebase en Archive Workbench 0.41.0

## 1. Problema resuelto

El rebase conservador de 0.40.0 bloqueaba correctamente la operación cuando una mención no podía trasladarse sin ambigüedad, pero no ofrecía todavía una forma de resolver el conflicto dentro del mismo flujo. Los casos observados fueron:

- una mención que seguía presente en la candidata, pero en otro bloque o con una grafía levemente distinta;
- dos menciones activas que terminarían ancladas al mismo fragmento después de reagrupar muchos bloques antiguos en pocos bloques Surya.

La versión 0.41.0 agrega una resolución manual asistida. No fuerza decisiones ni modifica entidades canónicas por inferencia.

## 2. Principio de seguridad

La resolución actúa sobre la **mención textual**, no sobre la autoridad canónica. El registro de autoridad, sus alias y sus relaciones permanecen intactos.

Para cada conflicto se permite únicamente:

1. relocalizar la mención en una sugerencia de la nueva base;
2. elegir un bloque y un fragmento exacto manualmente;
3. rechazar explícitamente una mención duplicada o inválida.

Rechazar una mención no elimina la autoridad. La mención y su historial permanecen en la base con estado `rejected`, vinculados al objeto anterior retirado.

## 3. Coincidencias automáticas mejoradas

Antes de declarar que una mención desapareció, el rebase busca en todos los bloques candidatos, no solo en el bloque predicho por el alineamiento estructural.

Una coincidencia única exacta o normalizada puede trasladarse automáticamente. Si hay varias posibilidades o solo coincidencias aproximadas, se presentan como sugerencias y la aplicación permanece bloqueada hasta una decisión humana.

## 4. Flujo de resolución

En **Procesamiento → Selección canónica → Rebasar la edición sobre esta candidata**, cada conflicto muestra:

- texto de la mención;
- autoridad vinculada, si existe;
- estado de la mención;
- contexto de la edición anterior;
- motivo del bloqueo;
- destinos sugeridos, con bloque, método, texto y contexto.

La opción **Elegir otro fragmento manualmente** exige seleccionar un bloque y copiar un fragmento que exista exactamente en el texto resultante. Si aparece más de una vez, se elige la aparición concreta por offsets.

La opción **Rechazar esta mención o duplicado** requiere una confirmación separada. No se aplica por el simple cambio de un selector.

## 5. Duplicados

Cuando dos menciones activas convergen en el mismo objeto y los mismos offsets, ninguna se elimina automáticamente. Se puede:

- conservar una y rechazar la otra;
- relocalizar una de ellas a otra aparición;
- cancelar el rebase y corregir previamente las menciones o las autoridades.

Si dos autoridades diferentes fueron vinculadas al mismo fragmento por error, la fusión o revisión de autoridades debe resolverse en el módulo de Entidades. El rebase no fusiona autoridades.

## 6. Aplicación y auditoría

Después de resolver todos los conflictos se recalcula la vista previa completa. El botón de aplicación solo se habilita si no quedan conflictos textuales, estructurales ni de menciones.

La operación sigue siendo transaccional. Registra:

- `rebase_relocate` para relocalizaciones automáticas;
- `rebase_relocate_manual` para destinos confirmados por una persona;
- `rebase_reject_conflict` para menciones rechazadas durante la resolución;
- conteos de relocalizaciones, rechazos y decisiones manuales en la revisión de página.

Si la página cambia después de preparar la vista previa, la operación se cancela y exige recalcularla.

## 7. Límites

Esta versión resuelve conflictos de anclaje de menciones. Continúan bloqueados, sin modo forzado:

- cambios humanos y OCR incompatibles sobre el mismo tramo;
- acciones estructurales previas de división, unión, reordenamiento, deshacer o rehacer;
- partes documentales o estados de revisión contradictorios;
- etiquetas que quedarían duplicadas por una convergencia estructural.

No hay migración nueva. La revisión de base continúa en `0032_page_quality_assessments`.
