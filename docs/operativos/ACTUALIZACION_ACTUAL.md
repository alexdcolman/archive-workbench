# Actualización y uso — Archive Workbench 0.79.0

Archive Workbench 0.79.0 implementa y cierra `OCR-01B`: casilleros y grupos de formulario revisables sobre la capa editable. Los detectores continúan produciendo candidatos no canónicos; una persona confirma el estado, el rótulo y, cuando corresponde, la agrupación. También puede registrar un casillero visible que no haya sido representado por OCR, siempre anclado a un objeto editable y con evidencia.

La migración aditiva `0043_form_structure_review` agrega `form_structure_json` a `editable_pages` y `editable_page_revisions`. Conserva objetos y revisiones anteriores y permite transportar snapshots coherentes mediante intercambio y adopción de estado.

La versión también corrige la navegación persistente: **Deshacer**, **Rehacer**, **Exportar estado editable** y las demás acciones con rerun conservan la pestaña activa en lugar de volver a **Editar texto**. La simplificación integral de la subsección **Formulario** y una referencia visual persistente de la página quedan registradas para `UX-02`.

## Actualización

Antes de migrar una base de trabajo debe existir un backup SQLite verificado. La actualización del código desde el ZIP no reemplaza `.git`, `.venv`, `project_data`, bases de validación ni temporales.

```bash
cd ~/projects/archive_app
source .venv/bin/activate
python -m pip install --no-build-isolation -e .
archive-workbench db-upgrade "$HOME/projects/archive_app/project_data"
archive-workbench db-status "$HOME/projects/archive_app/project_data"
```

La revisión esperada es `0043_form_structure_review`.

## Uso de formularios revisables

En **Revisar documentos → Formulario** se puede:

- confirmar candidatos como `Marcado`, `No marcado` o `Indeterminado`;
- crear o reutilizar grupos estables por página;
- registrar manualmente un casillero visible sin representación OCR;
- corregir rótulos, estados y agrupaciones;
- archivar grupos sin eliminar sus controles;
- revisar historial y usar deshacer/rehacer;
- exportar la estructura mediante `form_structures.jsonl`.

Los candidatos automáticos no se vuelven canónicos sin confirmación humana. Ninguna operación modifica la imagen ni el texto OCR de origen.

## Validación cerrada

La base descartable confirmó tres candidatos, dos grupos —uno activo y uno archivado—, cuatro casilleros activos, historial append-only, deshacer/rehacer, exportación correcta, integridad SQLite, conservación del original por SHA-256 y ausencia de acceso a `project_data`. La validación posterior confirmó además que las acciones con rerun conservan la pestaña activa.

No se repiten pruebas manuales de bloques ya cerrados: `UX-03`, `DISC-01A/B/C/D`, `SEM-01`, `GRAPH-01`, `OCR-02`, `CAT-01`, `DISC-02`, `CAT-02`, `GRAPH-02`, `OCR-01A` y `OCR-01B`.
