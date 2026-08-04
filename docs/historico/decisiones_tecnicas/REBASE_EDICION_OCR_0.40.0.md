# Rebase seguro de edición sobre una nueva extracción OCR — 0.40.0

## 1. Problema

Una extracción nueva puede ser mucho mejor que la que originó la capa editable, pero la página ya puede contener correcciones humanas, menciones de entidades, comentarios, etiquetas, estados de revisión y asignaciones a partes documentales. Reemplazar los objetos editables por los bloques nuevos destruiría o desanclaría ese trabajo; conservar para siempre la base anterior impediría aprovechar la mejora de OCR y layout.

La versión 0.40.0 incorpora un rebase conservador de tres estados:

```text
extracción anterior ──► edición humana
         │
         └────────────► nueva candidata OCR
```

El resultado toma la candidata como nueva estructura y vuelve a aplicar únicamente los cambios humanos que pueden trasladarse sin ambigüedad.

## 2. Procedimiento

El flujo se integra en:

```text
Procesamiento → Selección canónica
→ elegir documento, página y candidata
→ Rebasar la edición sobre esta candidata
```

Antes de escribir en la base, Archive Workbench prepara una vista previa que informa:

- cantidad de bloques editables anteriores y bloques candidatos;
- cambios humanos detectados respecto de la extracción anterior;
- menciones, comentarios, etiquetas y partes documentales que se trasladarán;
- texto resultante por bloque;
- diferencias entre la candidata pura y el resultado con correcciones humanas;
- conflictos que impiden una aplicación automática.

La acción **Aplicar rebase y adoptar la candidata** solo se habilita cuando la vista previa no contiene conflictos y la persona confirma expresamente la operación.

## 3. Qué preserva

Cuando el rebase es aplicable:

- la candidata pasa a ser la selección canónica y la base editable;
- se crean objetos editables con el orden, geometría y tipos de la candidata;
- se reaplican las correcciones humanas compatibles;
- las menciones se relocalizan por texto y posición y conservan su autoridad;
- los comentarios y etiquetas se trasladan al bloque nuevo correspondiente;
- las asignaciones a partes documentales y estados de revisión se conservan cuando su destino es inequívoco;
- las relaciones entre autoridades no se alteran, porque no dependen del identificador del bloque OCR;
- los objetos anteriores no se borran: pasan a estado retirado y conservan todas sus revisiones;
- la página registra una revisión `rebase` con el origen anterior, el nuevo y el resumen de traslados.

La operación se ejecuta dentro de una única transacción. Si aparece un error, no queda una selección, una edición o una mención aplicada a medias.

## 4. Conflictos conservadores

El rebase automático se bloquea cuando:

- una corrección humana y la candidata modificaron el mismo tramo de maneras incompatibles;
- una mención ya no puede encontrarse exactamente en el texto resultante;
- dos fragmentos que convergen en un mismo bloque tienen partes documentales o estados de revisión incompatibles;
- una etiqueta quedaría duplicada;
- la página contiene acciones estructurales de división, unión, reordenamiento o deshacer/rehacer;
- falta alguna de las tres bases necesarias: extracción anterior, edición activa o candidata completa.

En esos casos no se modifica nada. La opción histórica **Conservar edición y vincular esta candidata** sigue disponible, pero no sustituye el rebase: conserva el texto existente sin importar la estructura nueva.

## 5. Navegación persistente

La misma versión corrige la raíz del retorno involuntario a la primera pestaña. Una apertura programática de una pestaña ahora se guarda como estado activo antes de crear el widget y continúa vigente en reruns posteriores. Por eso evaluar calidad y luego cambiar de documento debe mantener:

```text
Procesamiento → Selección canónica
```

La regla vive en el helper compartido `tracked_tabs` y se aplica a todas las secciones de la aplicación que usan pestañas.

## 6. Límites actuales

0.40.0 no resuelve automáticamente páginas con edición estructural compleja. Tampoco aplica una corrección cuando la candidata y la persona modificaron el mismo pasaje de maneras distintas. Esos casos requieren una futura interfaz de resolución manual de conflictos, con elección de fragmentos y relocalización asistida de anotaciones.

No hay migración nueva. El rebase usa las tablas de selección, objetos editables, revisiones y menciones ya existentes; la revisión de esquema continúa en `0032_page_quality_assessments`.
