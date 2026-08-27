# Actualización actual - Archive Workbench 0.89.0 RC39

**Estado:** candidata no publicada de `PILOT-01` sobre RC38  
**Última publicación:** `v0.88.2`  
**Revisión de base:** `0047_authority_relation_profiles`  
**Migración nueva respecto de RC38:** no.

## Alcance de RC39

RC39 corrige exclusivamente `PILOT-01T` después de que la validación manual real demostrara que RC34-RC38 no habían eliminado el salto de contexto al trabajar desde una mención.

El diagnóstico definitivo está en el propio contrato del componente. `Revisar documentos` llamaba:

```python
clickable_review_canvas(..., commit_on_click=True, ...)
```

Con esa opción, cada clic sobre un bbox ejecutaba `setTriggerValue('selection_commit', ...)`. En un componente v2 eso comunica estado a Python y provoca un rerun. Por lo tanto, todos los intentos anteriores estaban intentando conservar documento/página **después de un rerun que la política canónica dice que no debe existir para una selección visual provisional**.

RC39 vuelve literalmente al invariante RC7/RC8:

- hacer clic en un bbox modifica sólo el estado local del componente: marco rojo, resumen del texto seleccionado, zoom y desplazamiento;
- ese clic no llama `setTriggerValue()` y no reconstruye Streamlit;
- el botón ya existente `Usar el texto seleccionado` es la acción semántica explícita que comunica la selección a Python;
- `on_selection_commit_change` sincroniza el bloque activo antes del rerun que esa confirmación sí necesita;
- documento y página vuelven al guardia simple `review_source_key` / `review_page_source` / `review_page_number`; se retiran las generaciones y copias de estado introducidas por RC34-RC38;
- los accesos desde Menciones conservan `request_app_view(...)` + `rerun_app(st)` únicamente para la navegación explícita hacia `Revisar documentos`.

No se modifica la base de datos ni el modelo de dominio.

## Actualización desde RC38

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC39.zip -d "$TMP_DIR"

python "$TMP_DIR/scripts/apply_candidate_update.py" \
  --source "$TMP_DIR" \
  --target ~/projects/archive_app

python -m pip install --no-build-isolation \
  -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"

python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status /home/alex/projects/archive_app/pilot_data
```

Esperado: versión `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC38 y RC39.** No ejecutar `db-upgrade` si `pilot_data` ya está en `0047_authority_relation_profiles`.

## Pruebas automáticas

Por indicación explícita de Alex, **no se ejecutaron ni se solicitan pruebas automáticas para RC39**. No correr `pytest`, `collect-only` ni la suite completa por este bloque.

## Validación manual específica de RC39

Abrir normalmente `archive-workbench review-app /home/alex/projects/archive_app/pilot_data` y recorrer `Entidades y menciones > Menciones > Buscar menciones > Abrir este fragmento en Revisar documentos`.

En la página abierta, hacer clic en varios bboxes. Cada clic debe mover inmediatamente el marco rojo y el resumen local del texto seleccionado **sin reconstruir la aplicación y sin cambiar documento ni página**. Cuando se quiera cargar uno de esos bloques en el panel de revisión, pulsar `Usar el texto seleccionado`; sólo esa confirmación debe actualizar el bloque activo en Python.

No repetir ninguna otra validación ya cerrada. `PILOT-01T` permanece abierto hasta esta comprobación real. Si queda verde, continuar desde **Búsqueda textual**.
