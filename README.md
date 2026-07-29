# Archive Workbench 0.33.1

Aplicación local para registrar, describir, procesar, revisar, coordinar, anotar, buscar, exportar e intercambiar cambios de documentación archivística digitalizada.

## Novedades 0.33.1

Versión de estabilización posterior a la prueba piloto funcional de 0.33.0.

- Corrige la migración `0027_temporal_authorities_relations` para conservar menciones y relaciones vinculadas a autoridades preexistentes.
- Impide aceptar o modificar menciones sin autoridad canónica y evita duplicados activos sobre el mismo fragmento textual.
- La búsqueda transversal reutiliza y vincula menciones huérfanas existentes en vez de crear una segunda mención sobre los mismos offsets.
- Hace explícita la creación y edición de relaciones: `Enter` no guarda, el destino puede cambiarse y la baja lógica conserva historial.
- Ordena los backups por la fecha real del manifiesto, evitando avisos falsos de recuperación pendiente.
- Reconoce la ascendencia de bundles ya aplicados aunque la copia receptora haya conservado resoluciones locales diferentes.
- Normaliza cadenas internas de eventos, fechas equivalentes y actualizaciones vacías durante el `dry-run`.
- Rechaza la exportación de bundles estructuralmente incompletos que incluyan objetos OCR inicializados después del checkpoint sin una base común con sus páginas y selecciones.
- `exchange-fork-copy` recrea los directorios operativos requeridos.
- El índice semántico se invalida solo cuando cambia el corpus textual comprendido por su perfil; cambios exclusivos de entidades o alias ya no fuerzan una reconstrucción.
- No agrega una migración nueva: la revisión vigente continúa siendo `0028_operational_readiness`.
- 171 tests automatizados.

## Actualización

```bash
pip install -e ".[dev,extraction,streamlit]"
pytest
archive-workbench db-upgrade project_data
archive-workbench db-upgrade project_data_receiver
```

Para usar embeddings:

```bash
pip install -e ".[semantic]"
```

También puede instalarse todo en una sola operación:

```bash
pip install -e ".[dev,extraction,streamlit,semantic]"
```

## Interfaz

```bash
archive-workbench review-app project_data
```

La barra lateral ofrece:

- **Inicio**: estado operativo, recorrido guiado, alertas y accesos directos.
- **Catálogo**: jerarquía archivística, descripción, unidades hijas, objetos digitales, archivos e historial.
- **Procesamiento**: inventario, preparación, extracción por lote, reintentos, selección canónica e inicialización editable.
- **Trabajo**: asignaciones, carga por responsable, vencimientos y revisión cruzada.
- **Revisión**: imagen, cajas OCR, texto editable, anotaciones y menciones.
- **Búsqueda literal**: consulta transversal FTS5 por palabras, frases y fragmentos.
- **Búsqueda semántica**: recuperación por afinidad de sentido mediante un índice local opcional.
- **Entidades**: fichas canónicas, alias, búsqueda transversal de menciones, relaciones e historial.
- **Grafo**: exploración derivada de relaciones, menciones y entidades compartidas.
- **Exportar**: perfiles, vista previa y salidas CSV/JSONL reproducibles.
- **Intercambio**: bundles, dry-run, conflictos y aplicación con backup.
- **Administración**: validaciones globales, backups, pruebas de recuperación y restauración controlada.

## Flujo de incorporación

```text
Catálogo
→ Procesamiento: preparar
→ Procesamiento: extraer
→ Procesamiento: seleccionar páginas canónicas
→ Procesamiento: inicializar capa editable
→ Trabajo: asignar revisión primaria
→ Revisión
→ Trabajo: enviar y asignar revisión cruzada
```

La extracción produce candidatos versionados. La selección de páginas es siempre humana. Si una página ya fue inicializada y luego cambia su selección OCR, la capa editable existente se marca como desactualizada y no se sobrescribe.

## Primer índice semántico

```bash
archive-workbench semantic-profile-default project_data --changed-by alex
archive-workbench semantic-profile-list project_data
archive-workbench semantic-index-build \
  project_data \
  "Multilingüe E5 — objetos" \
  --device auto \
  --created-by alex
archive-workbench semantic-search \
  project_data \
  "Multilingüe E5 — objetos" \
  "vigilancia de organizaciones políticas y culturales"
```

La primera construcción puede descargar el modelo. Los índices se guardan bajo `project_data/semantic/indexes/` y no forman parte de la fuente canónica ni de los bundles offline. Su calidad analítica todavía debe evaluarse con un corpus más amplio y consultas de control definidas por el equipo.

## Licencia y cita

Archive Workbench es software libre distribuido bajo la **GNU Affero General
Public License v3.0 o posterior (`AGPL-3.0-or-later`)**. Puede utilizarse,
estudiarse, modificarse y redistribuirse conforme a los términos de esa
licencia. Las versiones modificadas que se distribuyan o se ofrezcan como
servicio a través de una red deben mantener la misma licencia, publicar su
código fuente correspondiente y conservar los avisos de autoría y licencia.

El desarrollo fue realizado por **Alex Colman** en el marco del
**Grupo de Investigación en Archivos de la Represión (GIAR)**.

Cuando Archive Workbench sea utilizado en una investigación, publicación,
informe, actividad docente o desarrollo derivado, solicitamos citar:

> Colman, Alex, y Grupo de Investigación en Archivos de la Represión
> (GIAR). 2026. *Archive Workbench* (versión 0.33.1) [software].
> https://github.com/alexdcolman/archive-workbench

El archivo [`CITATION.cff`](CITATION.cff) contiene los metadatos de cita
legibles por GitHub, gestores bibliográficos y servicios de archivado
científico.
