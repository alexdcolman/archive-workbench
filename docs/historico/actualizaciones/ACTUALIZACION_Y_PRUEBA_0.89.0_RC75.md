# Actualización actual - Archive Workbench 0.89.0 RC75

## Alcance de RC75

RC75 continúa `OPS-01` después del primer build CPU material verde.

En el equipo de Alex, RC74 construyó correctamente la imagen CPU `amd64`. La imagen resultante informó Archive Workbench `0.89.0`, `llama-server` 0.1.2-dev build 10524 y PyTorch `2.13.0+cpu` con `cuda=None`. La corrección de `LD_LIBRARY_PATH` de RC74 queda así validada para el preflight CPU. Todavía falta la extracción Surya material y la persistencia entre reinicios.

Antes de continuar con OCR se detectó un problema de experiencia de uso: la distribución administrada obligaba a copiar un proyecto existente dentro de `ArchiveWorkbenchData/Projects`. Eso no representa el recorrido esperado para una persona sin conocimientos técnicos.

RC75 mueve la elección de un proyecto existente al sistema anfitrión:

- Windows usa un selector gráfico de carpetas abierto por PowerShell;
- macOS usa el selector de carpetas del sistema mediante AppleScript;
- Linux usa `zenity` o `kdialog` cuando están disponibles y conserva una alternativa de terminal sólo como último recurso;
- la carpeta elegida debe ser la raíz de un proyecto de Archive Workbench y se valida por `config/decisions.yaml` antes de iniciar el contenedor;
- Docker monta únicamente esa carpeta en `/selected-project` y el entrypoint abre directamente ese proyecto;
- si la persona elige **Abrir el inicio de Archive Workbench**, se conserva el launcher administrado para crear proyectos nuevos o abrir los guardados dentro de `ArchiveWorkbenchData/Projects`.

El montaje del proyecto elegido es independiente de `ArchiveWorkbenchData`, que sigue almacenando proyectos creados por el modo administrado, carpetas de importación, preferencias y cachés. La instalación nativa Linux no cambia.

Los lanzadores no fuerzan una descarga si el tag solicitado ya existe localmente. Esto permite validar RC75 con una imagen construida en el equipo antes de publicarla en GHCR y evita descargas repetidas de un mismo tag inmutable.

## Nube y proyectos activos

Google Drive, OneDrive, Dropbox e iCloud no se presentan como ubicación de una base SQLite abierta. El selector advierte que, para trasladar un proyecto, primero debe descargarse o copiarse una copia completa a una carpeta local y abrir esa carpeta local. Los mecanismos de intercambio por Drive ya existentes continúan como transporte controlado y no se convierten en una SQLite compartida.

## Tags de esta candidata

- CPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc75-cpu`;
- NVIDIA GPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc75-gpu`.

## Persistencia y base

No cambia SQLite ni el modelo de proyecto. Continúa `0047_authority_relation_profiles` y no hay migración. **No ejecutar `db-upgrade`.**

`WEB-01` permanece parcial y queda pausado hasta terminar la distribución multiplataforma. La reescritura integral del sitio continúa pendiente bajo la regla para lectores sin conocimiento previo. No se incorporan capturas hasta realizar esa reescritura.

## Próxima validación material

La próxima prueba debe usar el recorrido que tendrá una persona usuaria, no una copia manual dentro de `ArchiveWorkbenchData`:

1. construir localmente `0.89.0-rc75-cpu` reutilizando el caché de RC74;
2. ejecutar el lanzador CPU de Linux;
3. elegir una copia descartable de un proyecto existente mediante el selector gráfico del anfitrión;
4. comprobar que Archive Workbench abre directamente ese proyecto y que Docker montó únicamente la carpeta elegida;
5. ejecutar una extracción Surya real en CPU;
6. detener y volver a iniciar para comprobar persistencia;
7. recién después construir y validar la imagen NVIDIA GPU.

No usar `pilot_data` como proyecto escribible para esta prueba. Si se necesita su contenido, usar una copia descartable.

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. El gate focal de RC75 es:

```bash
pytest -q tests/test_container_distribution.py tests/test_documentation.py tests/test_packaging.py
pytest --collect-only -q
```

## Actualización desde RC74

Usar `scripts/apply_candidate_update.py` incluido en el paquete. No ejecutar `db-upgrade`.
