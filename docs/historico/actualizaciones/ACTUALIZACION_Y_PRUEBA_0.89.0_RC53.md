# Actualización actual - Archive Workbench 0.89.0 RC53

## Alcance de RC53

La validación manual de RC52 detectó una regresión acotada en **Intercambiar cambios > Más opciones > Google Drive (opcional)**. Al intentar subir un archivo que no podía abrirse como paquete incremental ZIP, `zipfile.BadZipFile` escapaba de la capa de validación y Streamlit mostraba un traceback completo.

RC53 corrige ese fallo sin cambiar el modelo de intercambio ni la persistencia:

- `inspect_change_bundle()` transforma un ZIP inválido en un error de dominio comprensible en vez de propagar `BadZipFile`.
- Google Drive preselecciona únicamente archivos de `exchange/outgoing/` que superan la inspección de un **paquete incremental de cambios**.
- Una copia completa creada en **Preparar una copia para trabajar en equipo** se distingue explícitamente de un paquete incremental. Ese ZIP contiene el proyecto completo y no se sube desde el panel de Google Drive de intercambio.
- Si se indica manualmente un archivo inválido, la pantalla muestra el motivo y no intenta conectarse a Drive.

El recorrido principal de RC52 se conserva: **Preparar una copia para trabajar en equipo → Enviar cambios → Recibir cambios**. `PILOT-01AB` permanece abierto hasta completar la validación real del intercambio.

## Actualización desde RC52

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC53.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC52 y RC53. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir los recorridos ya validados. Para RC53 alcanza con:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && pytest -q   tests/test_google_drive_transport.py::test_upload_non_zip_fails_before_network_with_plain_error   tests/test_google_drive_transport.py::test_upload_team_copy_zip_explains_that_drive_accepts_incremental_packages   tests/test_google_drive_transport.py::test_upload_valid_bundle_sets_archive_workbench_properties   tests/test_google_drive_transport.py::test_download_valid_bundle_is_atomic_and_verified   tests/test_exchange.py::test_bundle_export_and_inspection_are_verifiable   tests/test_ui_navigation.py::test_google_drive_upload_only_autoselects_valid_incremental_packages   tests/test_ui_navigation.py::test_exchange_ui_uses_plain_spanish_for_main_workflow   tests/test_ui_navigation.py::test_exchange_ui_creates_incremental_package_inside_project   tests/test_ui_navigation.py::test_every_streamlit_form_requires_an_explicit_button   tests/test_ui_navigation.py::test_form_confirmation_does_not_circularly_disable_submit_button   tests/test_documentation.py::test_current_update_guide_describes_0890_rc53_drive_validation   tests/test_packaging.py::test_candidate_update_reconciles_only_known_relocations && pytest --collect-only -q
```

La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC53

Usar el mismo `pilot_data`; no recrear el proyecto ni repetir etapas anteriores.

1. Abrir **Intercambiar cambios > Más opciones > Google Drive (opcional)**.
2. Comprobar que **Ruta del paquete de intercambio** se complete automáticamente sólo con un ZIP creado desde **Enviar cambios**, cuando exista uno válido en `exchange/outgoing/`.
3. Intentar subir ese paquete incremental. La pantalla no debe mostrar traceback; si Drive u OAuth devuelve un problema, debe aparecer como mensaje dentro de la interfaz.
4. Si se prueba manualmente una ruta que no sea un ZIP válido, la pantalla debe indicar que el archivo no es un ZIP válido de Archive Workbench y no debe romper la vista.
5. Si se indica la ruta de una copia completa creada en **Preparar una copia para trabajar en equipo**, la pantalla debe explicar que ese archivo no es un paquete incremental de cambios y que este panel de Drive no lo sube.

No aplicar ningún paquete recibido durante esta comprobación salvo que la continuación del piloto lo requiera explícitamente.
