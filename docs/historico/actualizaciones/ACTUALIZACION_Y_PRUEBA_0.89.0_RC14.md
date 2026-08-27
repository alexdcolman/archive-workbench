# Actualización actual - Archive Workbench 0.89.0 RC14

**Estado actualizado:** 2026-08-16  
**Bloque:** `PILOT-01` - corrección del mecanismo de actualización de candidatas cuando una versión reubica archivos documentales.

## Estado de partida

El último estado publicado sigue siendo `v0.88.2`. `0.89.0 RC14` es una candidata no publicada. No agrega migración y la revisión de base continúa en `0046_audiovisual_timeline_annotations`.

Se conserva `/home/alex/projects/archive_app/pilot_data`. No recrear el proyecto, no reincorporar los 138 originales, no repetir audiovisual, preparación ni extracciones ya validadas. RC14 no cambia la lógica funcional de RC13: corrige exclusivamente la actualización local y la regresión documental detectada al instalar RC13 sobre RC12.

## Base funcional que RC14 conserva de RC13

La validación manual pendiente sigue siendo la de RC13: `Procesar documentos` expresa la secuencia **preparar imágenes para extraer texto -> extraer texto de las imágenes preparadas -> elegir el texto para revisar**. En la integración de OCR de zona, `Elegir texto para revisar` permite reemplazar un bloque existente o **agregar un bloque nuevo** con procedencia regional y selección visual mediante cajas sobre la página. RC14 no modifica esas funciones.

## Qué falló en RC13

El ZIP de RC13 ya contenía solamente los seis documentos canónicos de `docs/operativos/` y las auditorías RC11/RC12 estaban correctamente archivadas en `docs/historico/actualizaciones/`. Sin embargo, la guía de instalación seguía usando una copia por superposición (`cp -a`). Esa operación actualiza y agrega archivos, pero no retira archivos que existían en una candidata anterior y dejaron de existir en la nueva ruta.

Por eso, al instalar RC13 sobre RC12, podían permanecer físicamente en `docs/operativos/` las copias obsoletas:

- `AUDITORIA_INTERFAZ_RC11_5_PASADAS.txt`;
- `AUDITORIA_INTERFAZ_RC12_5_PASADAS.txt`.

El mismo problema podía dejar en la raíz relevos RC10-RC12 ya archivados. El test `test_operational_docs_contain_only_canonical_active_documents` detectó correctamente esa instalación incompleta.

## Corrección RC14

RC14 incorpora `scripts/apply_candidate_update.py` y `scripts/candidate_update_manifest.json`.

El actualizador:

1. hace una comprobación previa antes de modificar el repositorio;
2. copia la candidata sobre el repositorio sin borrar archivos locales ajenos al paquete;
3. reconcilia únicamente cinco rutas antiguas conocidas que fueron reubicadas por RC13;
4. sólo retira una copia obsoleta si su SHA-256 coincide exactamente con la copia histórica incluida en el paquete;
5. verifica antes que la copia histórica de destino exista y tenga el mismo SHA-256;
6. si una copia local fue modificada y ya no coincide, se detiene antes de copiar nada y no la toca.

No se usa limpieza global, globos, `git clean`, `rm -rf` ni sincronización destructiva. La actualización conserva `pilot_data`, `.git`, archivos ignorados, bases, logs y cualquier otro contenido local que no figure en la lista explícita de reubicaciones.

La política permanente queda actualizada: cuando una candidata mueve o elimina rutas distribuidas en una versión anterior, una mera copia por superposición no es una instalación válida. El paquete debe declarar las rutas concretas y reconciliarlas de forma verificable y no destructiva para contenido desconocido.

## Base de datos

**No hay migración. No ejecutar `db-upgrade`.**

## Actualización local

RC14 se instala con el actualizador incluido en el ZIP, no con `cp -a` directo:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC14.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py"   --source "$TMP_DIR"   --target ~/projects/archive_app

python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

La versión de código sigue mostrando `0.89.0`; `RC14` identifica la candidata no publicada.

## Prueba focalizada

```bash
pytest -q   tests/test_documentation.py   tests/test_packaging.py && pytest --collect-only -q
```

## Validación manual

Si el gate queda verde, no repetir ninguna prueba funcional cerrada. Volver al mismo `pilot_data` y continuar la validación manual de RC13 desde `Procesar documentos` y `Revisar documentos`.
