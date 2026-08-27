# Actualización actual - Archive Workbench 0.89.0 RC80

## Alcance de RC80

RC80 continúa `OPS-01` después del primer workflow real de publicación de RC79. El job NVIDIA GPU `linux/amd64` terminó correctamente. El job CPU multi-arquitectura falló únicamente en `linux/arm64` durante la instalación del runtime principal. El registro BuildKit muestra que PyTorch 2.13.0 para AArch64 intentó instalar dependencias NVIDIA y `pip check` rechazó `nvidia-cusparselt-cu13 0.8.1` como no compatible con esa plataforma.

La imagen CPU ya forzaba PyTorch CPU en el entorno aislado de Surya, pero no en el entorno principal que instala Docling, búsqueda semántica y los demás extras. RC80 instala `torch` y `torchvision` desde `https://download.pytorch.org/whl/cpu` también en ese entorno principal **antes** de resolver los extras. Las ruedas CPU oficiales existen para Python 3.12 tanto en `linux/amd64` como en `linux/arm64`; las restricciones de Docling y sentence-transformers quedan satisfechas por esa instalación y no se retira ninguna capacidad. La construcción multi-arquitectura del workflow sigue siendo `linux/amd64,linux/arm64`.

El Dockerfile agrega además una aserción de build `torch.version.cuda is None` para el entorno principal de la imagen CPU. La imagen NVIDIA GPU no cambia funcionalmente; se republica con tag RC80 para mantener una pareja coherente de artefactos.

La validación material de RC79 ya dejó verdes persistencia por reinicio y por actualización, Surya CPU/GPU, `faster-whisper large-v3` con CUDA y el diagnóstico GPU administrado. RC80 no modifica esos backends ni la interfaz.

## Tags de esta candidata

- CPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc80-cpu`;
- NVIDIA GPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc80-gpu`.

## Persistencia y base

No cambia SQLite ni el modelo de proyecto. Continúa `0047_authority_relation_profiles` y no hay migración. **No ejecutar `db-upgrade`.**

`WEB-01` permanece parcial y queda pausado hasta terminar la distribución multiplataforma; RC79 no modifica el sitio público. No se incorporan capturas hasta realizar esa reescritura para lectores sin conocimiento previo.

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. Para RC80 el gate se limita a distribución, documentación, empaquetado y recopilación completa sin ejecución:

```bash
pytest -q \
  tests/test_container_distribution.py \
  tests/test_documentation.py \
  tests/test_packaging.py \
&& pytest --collect-only -q
```

El gate material que no puede sustituirse con pruebas unitarias es repetir el workflow `Publish Archive Workbench container images` y comprobar que ambos jobs publiquen los tags RC80.

## Validación manual específica

No repetir OCR Surya, transcripción audiovisual, persistencia por reinicio ni persistencia por actualización en Linux: esos recorridos ya quedaron materialmente verdes y RC80 no modifica sus runtimes de ejecución. Después de que el workflow publique ambas imágenes RC80, comprobar una descarga limpia de los dos tags y continuar con las pruebas Windows/macOS pendientes de `OPS-01`.
