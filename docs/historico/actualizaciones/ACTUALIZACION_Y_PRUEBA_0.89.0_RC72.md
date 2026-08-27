# Actualización actual - Archive Workbench 0.89.0 RC72

## Alcance de RC72

La revisión editorial de RC71 pausa `WEB-01` y cambia la prioridad inmediata: antes de terminar el sitio público, Archive Workbench debe poder iniciarse de forma sencilla en Windows, macOS y Linux sin exigir una instalación Python manual ni conocimientos de terminal.

RC72 implementa la primera capa de `OPS-01` mediante una distribución CPU basada en Docker. El ZIP incluye un lanzador de inicio y otro de detención para cada sistema operativo. La aplicación y sus dependencias se ejecutan dentro del contenedor; los proyectos, los archivos que se preparan para importar y las preferencias quedan fuera del contenedor, en una carpeta visible llamada `ArchiveWorkbenchData`.

La carpeta tiene cuatro ubicaciones principales:

- `ArchiveWorkbenchData/Projects`: proyectos creados o abiertos desde esta distribución;
- `ArchiveWorkbenchData/Imports/Documents`: documentos que se quieren incorporar por lote a un proyecto;
- `ArchiveWorkbenchData/Imports/AudioVideo`: archivos locales de audio o video que se quieren incorporar;
- `ArchiveWorkbenchData/Settings`: preferencias y cachés descargables de modelos.

En este modo, la interfaz no intenta abrir el selector gráfico de carpetas Linux desde dentro del contenedor. El launcher enumera proyectos de `Projects`; Catálogo y Audio y video leen las carpetas de importación. Una instalación nativa sin las variables del contenedor conserva el comportamiento anterior.

RC72 también agrega `Dockerfile`, `compose.yaml`, un workflow para publicar la imagen CPU en GitHub Container Registry y reglas para impedir que `ArchiveWorkbenchData` ingrese a Git o a la imagen Docker.

**Limitación de esta candidata:** este entorno no dispone de Docker. Por eso el código, la configuración y los lanzadores pueden validarse estáticamente y mediante tests, pero la imagen todavía debe construirse/publicarse y el primer inicio debe probarse en máquinas limpias de Windows, macOS y Linux. El perfil GPU/NVIDIA queda para la segunda parte de `OPS-01`.

No se modifica SQLite ni `pilot_data`. Continúa `0047_authority_relation_profiles`. No hay migración.

## Sitio público

`WEB-01` permanece parcial y queda pausado. La revisión futura no continuará corrigiendo frases aisladas de RC71. Todo el sitio y el README se revisarán frase por frase bajo la sección **2.5 Regla obligatoria para lectores sin conocimiento previo** de `.assistant/LINEAMIENTOS_DE_DISENO_Y_ESCRITURA.md`. No se incorporan capturas hasta realizar esa reescritura.

## Actualización desde RC71 en el equipo de desarrollo actual

Esta candidata puede seguir aplicándose sobre el repositorio existente de desarrollo con el mecanismo habitual:

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC72.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC71 y RC72. No ejecutar `db-upgrade`.**

## Uso previsto de la distribución multiplataforma

La entrega contiene `FIRST_START.txt` y estos lanzadores:

- Windows: `Start Archive Workbench - Windows.bat`;
- macOS: `Start Archive Workbench - macOS.command`;
- Linux: `Start Archive Workbench - Linux.sh`.

El uso final previsto es: instalar Docker Desktop o Docker Engine una sola vez, descomprimir la distribución y ejecutar el lanzador correspondiente. El lanzador prepara `ArchiveWorkbenchData`, obtiene la imagen publicada cuando esté disponible, inicia la aplicación y abre `http://localhost:8501`.

Mientras la imagen RC72 no esté publicada, los lanzadores intentan construirla localmente a partir del `Dockerfile`. Ese fallback sirve para validación técnica, pero **no constituye todavía la experiencia final para personas sin conocimientos técnicos**. El cierre de esta etapa exige una imagen pública previamente construida.

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. Para RC72 el gate se limita a la nueva capa de runtime administrado, distribución de contenedor, navegación afectada, documentación y empaquetado, y termina con recopilación completa sin ejecución:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && \
pytest -q \
  tests/test_runtime_environment.py \
  tests/test_container_distribution.py \
  tests/test_ui_navigation.py::test_managed_distribution_uses_host_visible_workspace_instead_of_native_pickers \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

## Validación manual pendiente para OPS-01

No corresponde repetir pruebas funcionales del piloto. La validación nueva debe hacerse sobre instalaciones limpias y se divide por sistema operativo.

### Windows

1. Instalar Docker Desktop con WSL2 y abrirlo.
2. Descomprimir el ZIP de RC72 en una carpeta normal del usuario.
3. Hacer doble clic en `Start Archive Workbench - Windows.bat`.
4. Confirmar que el navegador abre `http://localhost:8501`.
5. Crear un proyecto y confirmar que aparece dentro de `ArchiveWorkbenchData/Projects`.
6. Copiar un documento a `ArchiveWorkbenchData/Imports/Documents` y comprobar que Catálogo puede preparar su incorporación por lote.

### macOS

1. Instalar y abrir Docker Desktop.
2. Descomprimir RC72.
3. Abrir `Start Archive Workbench - macOS.command`.
4. Confirmar apertura en el navegador y creación del proyecto dentro de `ArchiveWorkbenchData/Projects`.
5. Probar una incorporación desde una de las carpetas `Imports`.

### Linux

1. Usar Docker Engine con Compose o Docker Desktop.
2. Descomprimir RC72 y ejecutar `Start Archive Workbench - Linux.sh`.
3. Confirmar apertura en el navegador, creación del proyecto y permisos de escritura en `ArchiveWorkbenchData`.

En los tres sistemas, detener y volver a iniciar la aplicación debe conservar el proyecto sin copiarlo dentro del contenedor. Una actualización posterior deberá probar además que reemplazar la versión del programa conserva completa la carpeta `ArchiveWorkbenchData`.
