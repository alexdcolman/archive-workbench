# Actualización actual - Archive Workbench 0.89.0 RC38

**Estado:** candidata no publicada de `PILOT-01` sobre RC37  
**Última publicación:** `v0.88.2`  
**Revisión de base:** `0047_authority_relation_profiles`  
**Migración nueva respecto de RC37:** no.

## Alcance de RC38

RC38 vuelve exclusivamente sobre `PILOT-01T`, porque la validación manual real confirmó que RC37 seguía cambiando documento o página después de abrir una coincidencia desde `Entidades y menciones` y seleccionar un bbox.

El diagnóstico de raíz mostró que RC34-RC37 mantuvieron, de distintas maneras, una identidad reutilizable para los selectores de documento y página después de una navegación programática. Esa reutilización deja abierta la posibilidad de que un rerun posterior reciba desde el navegador estado correspondiente a la instancia anterior del widget y vuelva a imponerlo.

RC38 cambia el contrato de navegación:

- el destino programático se valida y se conserva en `review_context_source_key` y `review_context_page_number`, que no son claves de widgets;
- cada navegación programática incrementa `review_navigation_generation`;
- los selectores se crean con claves generacionales `review_source_key__<generación>` y `review_page_number__<generación>`;
- los reruns ordinarios de esa misma vista, incluido el producido por seleccionar un bbox, conservan la generación y por lo tanto la misma identidad;
- una nueva navegación programática crea una identidad distinta, por lo que el estado de una instancia anterior no puede volver a competir con el nuevo destino;
- los cambios manuales de documento y página actualizan el contexto durable;
- los botones desde Menciones vuelven al flujo explícito histórico `request_app_view(...)` + `rerun_app(st)`;
- `review_canvas.py` no se modifica y el callback del bbox sigue afectando únicamente la selección del bloque.

RC37 se apoyó además en una premisa incorrecta: `persist_state="session"` no forma parte del mínimo Streamlit 1.55 soportado por el proyecto. RC38 elimina por completo esa dependencia y mantiene compatibilidad con `streamlit>=1.55,<2`.

## Actualización desde RC37

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC38.zip -d "$TMP_DIR"

python "$TMP_DIR/scripts/apply_candidate_update.py" \
  --source "$TMP_DIR" \
  --target ~/projects/archive_app

python -m pip install --no-build-isolation \
  -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"

python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status /home/alex/projects/archive_app/pilot_data
```

Esperado: versión `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC37 y RC38.** Si `pilot_data` ya está en `0047_authority_relation_profiles`, no ejecutar `db-upgrade`.

## Pruebas automáticas

Por indicación explícita de la validación de `PILOT-01T`, **no se ejecutaron ni se solicitan pruebas automáticas para RC38**. No correr `pytest`, `collect-only` ni la suite completa por este bloque.

La única comprobación pendiente es el comportamiento real de la interfaz.

## Validación manual específica de RC38

1. Abrir normalmente `archive-workbench review-app /home/alex/projects/archive_app/pilot_data`.
2. Entrar en `Entidades y menciones > Menciones > Buscar menciones`.
3. Abrir un resultado mediante `Abrir este fragmento en Revisar documentos`.
4. Seleccionar varios bboxes de esa misma página.
5. Confirmar que sólo cambia el bloque seleccionado y que documento y página permanecen exactamente en el destino abierto.

No repetir otras validaciones ya cerradas. `PILOT-01T` sólo se cierra si este recorrido real queda estable. Si queda verde, continuar desde **Búsqueda textual**.
