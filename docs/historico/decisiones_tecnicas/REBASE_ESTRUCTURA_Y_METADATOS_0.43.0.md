# Rebase de estructura activa y resolución de metadatos en Archive Workbench 0.43.0

## 1. Problema observado

Una página podía tener una candidata OCR claramente superior y, al mismo tiempo, una historia de trabajo humano con divisiones, uniones, reordenamientos, deshacer o rehacer. Hasta 0.42.0, la mera existencia de cualquiera de esas acciones bloqueaba el rebase, aunque el estado editable activo fuera coherente y ya representara la decisión final de la persona usuaria.

Ese bloqueo protegía los datos, pero confundía dos cosas diferentes:

- el historial de cómo se llegó al estado actual;
- una incompatibilidad real entre ese estado actual y la nueva candidata.

También quedaban sin resolución asistida los casos en que varios objetos anteriores convergían en un mismo bloque candidato con partes documentales, estados de revisión o tipos de objeto distintos.

## 2. Nueva regla estructural

La fuente de verdad para el rebase es ahora el **snapshot editable activo actual**. Las acciones históricas se conservan íntegramente, pero no bloquean por sí solas.

El procedimiento no reproduce mecánicamente cada división, unión o movimiento sobre la candidata. En cambio:

1. toma los objetos activos después de todos los deshacer y rehacer vigentes;
2. construye el texto humano actual en su orden efectivo;
3. realiza el rebase textual de tres vías;
4. proyecta objetos, menciones y anotaciones sobre la estructura de la candidata;
5. bloquea únicamente cuando esa proyección produce una ambigüedad concreta.

Así, una división que luego fue deshecha no se reaplica. Una unión o un reordenamiento que permanece activo se refleja en el estado textual utilizado por el rebase. La historia completa continúa disponible en `editable_page_actions`, revisiones de objetos y revisiones de página.

## 3. Metadatos incompatibles

Cuando varios objetos editables convergen en un mismo bloque candidato, Archive Workbench resuelve automáticamente los metadatos que son inequívocos y presenta una decisión explícita para los que no lo son.

### Parte documental

Si todos los objetos asignados coinciden en una misma parte, se conserva. Si convergen partes distintas, se ofrecen estas opciones:

- conservar una de las partes existentes;
- dejar el bloque sin asignación.

No se fusionan ni se modifican las partes documentales.

### Estado de revisión

Un único estado humano distinto de `unreviewed` se conserva. Si convergen estados diferentes, se puede elegir uno de ellos o volver el bloque a `unreviewed`.

### Tipo de objeto

La clasificación de la candidata se conserva cuando no hubo una reclasificación humana. Si una clasificación humana explícita difiere de la candidata, se muestran ambas y la persona usuaria elige cuál debe quedar.

Las decisiones se revalidan contra las opciones visibles. Si el estado editable o la candidata cambian, la resolución deja de ser válida y debe revisarse nuevamente.

## 4. Comentarios, menciones y etiquetas

Las menciones conservan su flujo independiente de relocalización por texto y offsets. Los comentarios de todos los objetos convergentes se trasladan al bloque resultante.

Las etiquetas idénticas se deduplican de manera conservadora. Una copia se traslada al nuevo bloque; las copias redundantes no se borran, sino que permanecen vinculadas a los objetos históricos retirados. Esto evita violar la unicidad del nuevo bloque sin destruir el registro anterior.

## 5. Qué continúa bloqueado

La versión no agrega un modo forzado. El rebase continúa detenido cuando existe una incompatibilidad real que no puede expresarse con las decisiones anteriores, por ejemplo:

- correcciones textuales todavía no resueltas;
- menciones sin destino válido;
- un objeto anotado que no pueda proyectarse sobre ningún bloque candidato;
- dos correcciones resueltas que se superpongan sobre el mismo tramo;
- cambios concurrentes ocurridos después de preparar la vista previa.

En cualquiera de esos casos no se modifica la selección canónica ni la capa editable.

## 6. Auditoría

La revisión `rebase` registra ahora:

- cantidad de acciones estructurales históricas absorbidas desde el snapshot activo;
- cantidad y método de resoluciones de metadatos;
- etiquetas trasladadas y etiquetas deduplicadas;
- decisiones textuales y de menciones ya existentes;
- objetos anteriores y nuevos.

La operación sigue siendo transaccional y los objetos anteriores quedan retirados, no eliminados.

## 7. Uso

El flujo permanece en:

```text
Procesamiento
→ Selección canónica
→ Rebasar la edición sobre esta candidata
```

Si la página tiene acciones estructurales previas, la interfaz informa cuántas encontró y aclara que utilizará el estado activo. Si aparecen metadatos incompatibles, muestra una tarjeta por bloque y por tipo de metadato. El botón de aplicación solo se habilita cuando no queda ninguna decisión pendiente.

## 8. Migraciones

No hay migración nueva. La revisión de base continúa en:

```text
0032_page_quality_assessments
```
