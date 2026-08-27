# Actualización actual - Archive Workbench 0.89.0 RC65

## Alcance de RC65

La validación manual de RC64 dejó verdes las superficies reparadas y cierra `PILOT-01AE`. RC65 retoma el siguiente bloque sustantivo del piloto, `PILOT-01A`, sin reabrir recorridos funcionales ya validados.

RC65 revisa el modelo descriptivo de Catálogo y audiovisual con base en RiC-CM/RiC-O y en las prácticas de descripción de imágenes en movimiento de FIAF:

- los niveles configurables de Catálogo distinguen contexto de custodia, conjunto documental, recurso documental y contenedor o unidad física;
- Fondo, Colección, Serie y Legajo/File pueden conservar una clasificación más precisa como tipos de conjunto documental;
- `Archivo > Colección` sigue siendo compatible con el proyecto piloto, pero la relación se presenta como **contexto de custodia**, no como afirmación de que el repositorio sea un nivel interno de la Colección;
- los proyectos anteriores que no tienen las nuevas claves semánticas en `decisions.yaml` siguen funcionando por inferencia de los niveles estándar, sin reescribir su configuración;
- la procedencia de un audiovisual incorporado desde una plataforma separa **Publicación en la plataforma**, **Agrupación en la plataforma** cuando existe y **Copia incorporada al proyecto**;
- una playlist u otra agrupación externa no se convierte automáticamente en Colección, Serie ni unidad archivística;
- los registros históricos conservan sus campos anteriores y, para YouTube, pueden recuperar el identificador de playlist si la URL original guardada contiene `list=`.

El diseño usa RiC y FIAF como referencias conceptuales; Archive Workbench no afirma una implementación completa o certificada de esos estándares.

No se modifica `pilot_data`, no se reimporta ningún audiovisual y no hay migración de base. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC64

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC65.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC64 y RC65. No ejecutar `db-upgrade`.**

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. Para RC65 el gate se limita al contrato de decisiones, compatibilidad de proyectos, Catálogo, procedencia de plataformas, navegación/documentación y empaquetado, terminando en recopilación completa sin ejecución:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && \
pytest -q \
  tests/test_decisions.py \
  tests/test_project_setup.py \
  tests/test_platform_import.py \
  tests/test_catalog_management.py \
  tests/test_ui_navigation.py::test_catalog_relation_caption_distinguishes_custody_hierarchy_and_location \
  tests/test_ui_navigation.py::test_catalog_unit_navigation_exposes_hierarchy_and_preserves_ancestors \
  tests/test_ui_navigation.py::test_catalog_allows_level_change_collection_enablement_and_safe_deletion \
  tests/test_ui_navigation.py::test_all_navigation_surfaces_have_context_help_contracts \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

## Validación manual específica de RC65

Usar el mismo `/home/alex/projects/archive_app/pilot_data`. No crear unidades nuevas, no mover unidades, no reimportar el audiovisual y no repetir transcripciones, OCR, búsquedas, exportaciones, intercambio, backup o recuperación.

1. Abrir **Catálogo > Unidades del catálogo** y seleccionar el nodo que funciona como `Archivo`. Debe identificarse como **Repositorio o contexto de custodia**.
2. Seleccionar la Colección usada para `rememorARTE, honrar la vida`. Debe identificarse como **Conjunto documental · Colección construida**. El árbol puede seguir mostrándola bajo Archivo porque esa posición se interpreta como contexto de custodia.
3. Abrir **Ubicación y tipo** de esa Colección. La ubicación actual debe explicarse como **Contexto de custodia** y aclarar que no convierte al repositorio en un nivel interno del Fondo o la Colección. No guardar cambios.
4. Abrir **Audio y video > Transcribir y revisar** y seleccionar `RememorArte Horacio BAU`, ya incorporado en el piloto. En **Datos técnicos e historial de este audio o video**, la procedencia debe distinguir **Publicación en la plataforma** de **Copia incorporada al proyecto**.
5. Si la URL histórica guardada conservaba un parámetro `list=`, también debe aparecer **Agrupación en la plataforma**. Si la URL original no contenía ese contexto y la incorporación es anterior a RC65, su ausencia no es un error y no hace falta reimportar nada.

Si estos puntos quedan claros y el recorrido no introduce una regresión, `PILOT-01A` puede cerrarse. `PILOT-01N` permanece post-release y no bloquea el cierre pre-release del piloto.
