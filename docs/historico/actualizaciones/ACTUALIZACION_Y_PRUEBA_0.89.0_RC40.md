# Actualización actual - Archive Workbench 0.89.0 RC40

## Alcance de RC40

RC40 corrige únicamente la regresión todavía abierta de `PILOT-01T`.

La validación manual de RC39 confirmó dos requisitos simultáneos: seleccionar un bbox no debe reiniciar toda la vista, pero **sí debe cambiar inmediatamente el bloque de texto correspondiente en el panel de `Revisar documentos`**. RC39 cumplía el primero y rompía el segundo.

RC40 recupera la semántica validada históricamente de selección inmediata y cambia el alcance del rerun. La región autocontenida formada por imagen, selector de bloque y panel del bloque activo está aislada mediante `st.fragment`. El clic sobre un bbox comunica el `object_id`; `on_selection_commit_change` actualiza `object_state_key` antes del rerun del fragmento. Documento, página y navegación quedan fuera del fragmento y no se reconstruyen. Zoom y desplazamiento siguen en el navegador mediante `sessionStorage`.

No se modifica `pilot_data` ni el esquema de base. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC39

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC40.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
archive-workbench db-status /home/alex/projects/archive_app/pilot_data
```

**No hay migración nueva entre RC39 y RC40.** No ejecutar `db-upgrade` si `pilot_data` ya está en `0047_authority_relation_profiles`.

## Pruebas automatizadas

Por indicación explícita de Alex, **no se ejecutan ni se solicitan pruebas automatizadas para este bloque**. No correr `pytest`, `collect-only` ni la suite completa.

## Validación manual específica de RC40

Abrir `Entidades y menciones -> Menciones -> Buscar menciones -> Abrir este fragmento en Revisar documentos`. En la página abierta, hacer clic en varios bboxes consecutivos.

Resultado esperado: cada clic cambia inmediatamente `Bloque de texto de la página que querés revisar` y el contenido del panel al bloque correspondiente; documento y página permanecen iguales; no se reconstruye el resto de la aplicación; zoom y desplazamiento de la imagen se conservan.

No repetir ninguna otra validación ya cerrada. `PILOT-01T` permanece abierto hasta esta comprobación real. Si queda verde, continuar desde **Búsqueda textual**.
