# Actualización y prueba — Archive Workbench 0.73.0

Esta versión cierra `DISC-01D` y el bloque `DISC-01`: agrega evaluación reproducible por familia, comparación de informes y un adaptador opcional para spaCy. No cambia el esquema de la base ni agrega controles a la pantalla principal.

## 1. Actualizar sin mover ni eliminar archivos locales

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q \
  ~/Downloads/archive_workbench_v0.73.0.zip \
  -d "$TMP_DIR"

cp -a "$TMP_DIR"/. .

python -m pip install \
  --no-build-isolation \
  --no-deps \
  -e .

python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.73.0`. La copia no se mueve ni se elimina: `project_data`, `.dev`, `.assistant` y los demás archivos locales existentes permanecen en su lugar.

## 2. Base de datos

**No hay migración.** La revisión requerida continúa en `0040_discovery_grouping_continuity`. No ejecutar `db-upgrade` para esta actualización.

## 3. Pruebas relevantes y colección completa

```bash
pytest -q \
  tests/test_discovery_evaluation.py \
  tests/test_open_discovery.py \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

No hace falta repetir `DISC-01A`, `DISC-01B`, `DISC-01C` ni la validación manual de `UX-03`.

## 4. Validación breve de DISC-01D

Esta prueba no abre ni modifica ninguna base. Usa el corpus sintético incluido y escribe tres informes en `~/Downloads`.

```bash
cd ~/projects/archive_app
source .venv/bin/activate

archive-workbench discovery-providers

archive-workbench discovery-evaluate \
  config/discovery_evaluation_corpus.jsonl \
  --provider local_deterministic \
  --provider-version local_rules_v1 \
  --minimum-confidence 0.0 \
  --output ~/Downloads/aw_disc01d_local_000.json

archive-workbench discovery-evaluate \
  config/discovery_evaluation_corpus.jsonl \
  --provider local_deterministic \
  --provider-version local_rules_v1 \
  --minimum-confidence 0.95 \
  --output ~/Downloads/aw_disc01d_local_095.json

archive-workbench discovery-evaluation-compare \
  ~/Downloads/aw_disc01d_local_000.json \
  ~/Downloads/aw_disc01d_local_095.json \
  --output ~/Downloads/aw_disc01d_comparacion.json
```

Resultado esperado:

- `local_deterministic` aparece disponible;
- `spacy_ner` aparece disponible o no disponible según el entorno, sin impedir la prueba;
- con umbral `0.0`: precisión `1.000000`, recuperación `0.857143` y F1 `0.923077`;
- con umbral `0.95`: precisión `1.000000`, recuperación `0.142857` y F1 `0.250000`;
- la comparación se crea porque ambos informes conservan la misma huella del corpus;
- el informe por familia deja visible que las reglas locales no cubren `other`.

El corpus incluido es un control de contrato y offsets, no un benchmark representativo. Ningún proveedor queda declarado como empíricamente superior o recomendado por defecto.
