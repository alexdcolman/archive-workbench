# Actualización actual - Archive Workbench 0.89.0 RC59

## Alcance de RC59

La validación manual posterior a RC58 cerró `PILOT-01AD`: **Procesar documentos** dejó de mostrar los parpadeos observados al cambiar de pestaña y los documentos distintos con el mismo nombre visible permanecen independientes al seleccionar o quitar uno. La prueba de Surya en lote cerró además `PILOT-01I`: `VLLM::EngineCore` se mantuvo activo entre documentos y desapareció al finalizar el lote completo, liberando la VRAM automáticamente. No repetir esas pruebas salvo regresión concreta.

RC59 cierra `PILOT-01L` y fija un único contrato público de formatos documentales procesables: **PDF, TIFF, PNG, JPEG y WebP**. BMP queda deliberadamente excluido.

- `inspection.detect_media_type()` deja de clasificar `.bmp` como `MediaType.IMAGE`;
- la lista usada por Catálogo proviene del mismo contrato compartido que Inspección;
- los textos de incorporación enumeran PDF, TIFF, PNG, JPEG y WebP en lugar de hablar genéricamente de “imágenes compatibles”;
- Preparar páginas rechaza un BMP aunque un registro histórico o externo lo presente como `MediaType.IMAGE`;
- las regresiones nuevas comprueban inspección y preparación de PNG, JPG, JPEG y WebP y el rechazo explícito de BMP; las pruebas ya existentes de PDF y TIFF siguen cubriendo esos formatos.

No se modifica `pilot_data`, el esquema de base, OCR, selección canónica ni el ciclo de vida de Surya.

## Actualización desde RC58

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC59.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC58 y RC59. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir OCR, la prueba individual o en lote de Surya, ni los recorridos ya cerrados del piloto. Para RC59 corresponde ejecutar únicamente los tests de inspección/formatos, preparación raster afectada, navegación textual relacionada, documentación/empaquetado y, al final, `pytest --collect-only -q`. La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC59

No hace falta conseguir ni incorporar un BMP para cerrar esta candidata: la exclusión fue una decisión explícita del contrato y está protegida por regresiones automáticas.

1. Abrir **Catálogo** y llegar a la incorporación de un archivo. Comprobar únicamente que el texto visible identifica los formatos admitidos como **PDF, TIFF, PNG, JPEG y WebP**.
2. No incorporar archivos nuevos ni repetir preparación/OCR.
3. Si el texto queda claro y no aparece BMP como formato soportado, `PILOT-01L` permanece cerrado.

Después de RC59, los subsidiarios pre-release todavía abiertos dentro de `PILOT-01` son principalmente `PILOT-01E` (auditoría transversal de identidad/redacción) y `PILOT-01A` (modelo descriptivo de colecciones, repositorios y agrupaciones audiovisuales). `PILOT-01N` es post-release y no bloquea.
