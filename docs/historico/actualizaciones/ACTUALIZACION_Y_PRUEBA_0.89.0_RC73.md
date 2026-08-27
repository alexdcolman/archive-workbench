# Actualización actual - Archive Workbench 0.89.0 RC73

## Alcance de RC73

RC73 continúa `OPS-01` y separa la distribución administrada en dos imágenes publicables:

- **CPU**: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc73-cpu`;
- **NVIDIA GPU**: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc73-gpu`.

La imagen CPU es la opción estándar y se prepara para `linux/amd64` y `linux/arm64`, de modo que Docker Desktop pueda seleccionar la arquitectura correspondiente en Windows, macOS Intel, macOS Apple Silicon y equipos Linux compatibles. La imagen GPU se prepara para `linux/amd64` y contiene CUDA 12.8 y cuDNN. Está destinada a Windows con Docker Desktop + WSL2 + NVIDIA y a Linux con Docker Engine + NVIDIA Container Toolkit. Docker Desktop no ofrece acceso local a GPU NVIDIA en macOS; allí corresponde la imagen CPU.

Los lanzadores normales de Windows, macOS y Linux usan la imagen CPU. RC73 agrega lanzadores GPU separados para Windows y Linux. El usuario final no construye imágenes: cada lanzador descarga la imagen publicada, inicia el servicio y abre la interfaz. Si la imagen todavía no está publicada, el lanzador informa el problema y se detiene; se elimina el fallback de construcción local de RC72.

La carpeta persistente sigue siendo `ArchiveWorkbenchData/`:

- `Projects`: proyectos de Archive Workbench;
- `Imports/Documents`: documentos que se quieren incorporar;
- `Imports/AudioVideo`: audios y videos que se quieren incorporar;
- `Settings`: preferencias y cachés descargables de modelos.

CPU y GPU montan la misma carpeta. Cambiar de imagen no duplica ni reemplaza los proyectos.

## Diferencia entre las dos imágenes

Las dos imágenes incluyen el servidor de inferencia que necesita Surya, sin depender de Docker anidado. La imagen CPU incorpora `llama-server` CPU y PyTorch CPU dentro del entorno aislado de Surya. La imagen GPU incorpora `llama-server` compilado con CUDA 12 y parte de `nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04`; además instala PyTorch CUDA 12.8 en el entorno aislado de Surya. El perfil archivístico preferido conserva los modelos auxiliares Torch de Surya en CPU, mientras el modelo visual principal puede usar el `llama-server` correspondiente a la imagen. El runtime principal de la imagen GPU dispone de cuBLAS/cuDNN para las tareas compatibles, incluida la transcripción con faster-whisper/CTranslate2.

En el modo administrado se fuerza el backend Surya incluido en la imagen (`llamacpp`) incluso si un proyecto antiguo conserva `device: cuda` en su perfil. Esto evita que el proceso dentro del contenedor intente iniciar un segundo contenedor vLLM. Las instalaciones nativas fuera de la distribución administrada conservan la selección histórica de backend.

La distribución informa a la aplicación si el runtime es CPU o GPU. En Audio y video, la imagen CPU ofrece sólo `Procesador (CPU)` para el reconocimiento de voz; la imagen GPU ofrece primero `Placa NVIDIA (CUDA)` y mantiene CPU como alternativa. Una instalación nativa conserva el selector anterior.

## Estado material de las imágenes

Este entorno de construcción no dispone del comando Docker. Por eso RC73 puede validar Dockerfiles, Compose, scripts, workflow y contratos de la aplicación, pero **no puede afirmar todavía que las dos imágenes se construyeron ni que la GPU ejecutó CUDA**.

`.github/workflows/publish-container.yml` queda preparado para publicar ambas imágenes en GHCR:

- CPU: `linux/amd64,linux/arm64`;
- GPU: `linux/amd64`.

El cierre material de esta fase requiere ejecutar ese workflow desde una revisión que contenga RC73, comprobar que ambos builds terminan verdes y luego validar el doble clic en máquinas limpias compatibles.

## Sitio público

`WEB-01` permanece parcial y queda pausado. No se modifica el sitio en RC73. La futura reescritura conserva las reglas de lectores sin conocimiento previo registradas en `.assistant/LINEAMIENTOS_DE_DISENO_Y_ESCRITURA.md`. No se incorporan capturas hasta realizar esa reescritura.

## Actualización desde RC72 en el equipo de desarrollo

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC73.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC72 y RC73. No ejecutar `db-upgrade`.**

## Uso previsto para una persona no técnica

### Windows

- Uso estándar: doble clic en `Start Archive Workbench - Windows.bat`.
- Equipo con NVIDIA compatible: doble clic en `Start Archive Workbench - GPU - Windows.bat`.
- La opción GPU comprueba primero que Docker puede ejecutar `nvidia-smi` dentro de un contenedor. Si no puede, no inicia una falsa sesión GPU y recomienda usar la imagen CPU.

### macOS

- Doble clic en `Start Archive Workbench - macOS.command`.
- Se usa siempre la imagen CPU. El mismo tag CPU ofrece `linux/amd64` y `linux/arm64` para cubrir Mac Intel y Apple Silicon mediante Docker Desktop.

### Linux

- Uso estándar: `Start Archive Workbench - Linux.sh`, con Docker Desktop o Docker Engine + Compose.
- GPU NVIDIA: `Start Archive Workbench - GPU - Linux.sh`, con Docker Engine configurado con NVIDIA Container Toolkit. Docker Desktop para Linux no se documenta como vía GPU.

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. Para RC73 corresponde:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && \
pytest -q \
  tests/test_runtime_environment.py \
  tests/test_container_distribution.py \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

## Validación manual pendiente para OPS-01

Después de publicar las imágenes:

1. Windows sin GPU: comprobar descarga, apertura, creación de proyecto, reinicio y persistencia con la imagen CPU.
2. Windows NVIDIA + WSL2: repetir con el lanzador GPU y confirmar desde una tarea real que CUDA está disponible.
3. macOS Intel o Apple Silicon disponible: comprobar la imagen CPU correspondiente y persistencia.
4. Linux CPU: comprobar el lanzador estándar.
5. Linux NVIDIA: comprobar el lanzador GPU sobre Docker Engine + NVIDIA Container Toolkit.

No corresponde repetir el piloto funcional completo. Estas pruebas evalúan instalación, selección CPU/GPU, acceso al hardware y persistencia de `ArchiveWorkbenchData`.
