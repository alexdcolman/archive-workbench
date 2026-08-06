# Actualización y uso — Archive Workbench 0.80.0

Archive Workbench 0.80.0 implementa y cierra `OCR-01C`: columnas y orden de lectura revisables sobre la capa editable. La propuesta automática es no canónica hasta que una persona la confirma. La confirmación crea columnas estables y aplica el orden mediante revisiones de objetos; después pueden reasignarse objetos, crear, renombrar o archivar columnas y resolver explícitamente fragmentaciones y duplicaciones.

La migración aditiva `0044_layout_structure_review` agrega `layout_structure_json` a `editable_pages` y `editable_page_revisions`. Conserva textos, geometrías, imágenes, objetos OCR y revisiones anteriores. La estructura participa en deshacer/rehacer, intercambio, adopción de estado y exportación reproducible mediante `layout_structures.jsonl` y manifiesto 1.4.

La versión también:

- muestra una referencia visual cacheada desde el original cuando falta un derivado de previsualización;
- organiza **Orden y estructura** en cuatro bloques numerados;
- conserva visible el objeto seleccionado y su columna vigente;
- permite crear una columna manual y asignar el objeto mediante una sola acción;
- distingue la pestaña **Historial general** del bloque **Historial de Orden y estructura**;
- conserva la pestaña activa después de acciones con rerun;
- incorpora verificadores diagnósticos con valores reales y reglas privadas de guiado idempotentes para `.assistant`.

La simplificación integral de **Formulario** y la revisión de densidad y comprensión de **Orden y estructura** permanecen registradas para `UX-02`.

## Actualización

Antes de migrar una base de trabajo debe existir un backup SQLite verificado. La actualización desde el ZIP no reemplaza `.git`, `.venv`, `project_data`, bases descartables ni temporales.

```bash
cd ~/projects/archive_app
source .venv/bin/activate
python -m pip install --no-build-isolation -e .
archive-workbench db-upgrade "$HOME/projects/archive_app/project_data"
archive-workbench db-status "$HOME/projects/archive_app/project_data"
```

La revisión esperada es `0044_layout_structure_review`.

## Uso de columnas y orden de lectura

En **Revisar documentos → Orden y estructura** se puede:

- revisar una propuesta automática sin modificar el orden editable;
- confirmar columnas y aplicar el orden sugerido;
- crear, renombrar, reasignar o archivar columnas;
- combinar una fragmentación confirmada;
- archivar un duplicado confirmado;
- revisar el historial específico de layout;
- usar deshacer y rehacer;
- exportar la estructura mediante `layout_structures.jsonl`.

La pestaña superior **Historial general** muestra la auditoría completa de la página. El bloque **4. Historial de Orden y estructura** muestra únicamente las acciones del layout. No son la misma vista.

Ninguna propuesta automática modifica la capa editable hasta su confirmación. Las operaciones revisadas no alteran el PDF ni los objetos OCR de origen.

## Validación cerrada

La base descartable confirmó tres columnas activas —`Columna 1`, `Columna 2` y `Margen derecho`—, cinco objetos editables activos, cero fragmentaciones o duplicaciones pendientes y orden vigente coincidente con la propuesta. El historial específico conservó confirmación, creación y asignación de columna, renombrado, combinación, archivo, deshacer y rehacer. La exportación produjo `layout_structures.jsonl` con schema 1.4. El PDF conservó su SHA-256, los siete objetos OCR de origen permanecieron intactos y `project_data` no fue tocada durante la validación.

No se repiten pruebas manuales de bloques ya cerrados: `UX-03`, `DISC-01A/B/C/D`, `SEM-01`, `GRAPH-01`, `OCR-02`, `CAT-01`, `DISC-02`, `CAT-02`, `GRAPH-02`, `OCR-01A`, `OCR-01B` y `OCR-01C`.
