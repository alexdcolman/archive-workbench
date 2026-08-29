# Actualización actual - Archive Workbench 0.89.0 RC81

## Estado de partida

RC81 continúa `OPS-01` desde el estado material cerrado de RC80. RC80 ya fue publicada y validada en Linux: imagen CPU pública multi-arquitectura `linux/amd64` + `linux/arm64`, imagen NVIDIA GPU pública `linux/amd64`, descarga anónima desde GHCR, persistencia por reinicio y actualización, Surya CPU/GPU, transcripción audiovisual `faster-whisper large-v3` CUDA y diagnóstico GPU administrado. Esos bloques no se reabren sin evidencia nueva.

La primera validación material de RC80 en Windows confirmó que la imagen CPU se descarga y la aplicación puede arrancar, pero detectó cinco bloqueantes de experiencia: codificación del selector PowerShell, conflicto de puerto 8501, falso negativo de readiness, OAuth de Google Drive dependiente de un JSON por instalación y latencia de interfaz. La validación Windows GPU y los proyectos grandes quedaron deliberadamente pausados.

## Alcance de RC81

RC81 corrige sólo esos cinco bloques. No cambia SQLite, no agrega migración y continúa `0047_authority_relation_profiles`. No ejecutar `db-upgrade`.

### 1. Selector Windows con codificación inequívoca

`docker/select-project-windows.ps1` conserva su texto y se distribuye como UTF-8 con BOM. El helper nuevo `docker/windows-runtime.ps1`, que también contiene texto no ASCII, usa la misma codificación. El gate focal comprueba los bytes BOM de ambos archivos para evitar una regresión bajo Windows PowerShell 5.1.

### 2. Puerto local ocupado sin detener procesos ajenos

Compose publica el puerto interno 8501 mediante `127.0.0.1:${AW_HOST_PORT:-8501}:8501`. Los launchers Windows llaman a `docker/windows-runtime.ps1` antes de iniciar el servicio. El helper intenta reservar 8501; si ya está ocupado, informa el conflicto, no ejecuta `docker kill` ni `docker stop` sobre procesos ajenos y elige el primer puerto libre entre 8502 y 8510. El puerto elegido se pasa a Compose mediante `AW_HOST_PORT` y se usa también para la URL pública local de OAuth.

El `docker compose down` previo continúa limitado al proyecto Compose `archive-workbench`; no constituye autorización para detener contenedores de otros proyectos.

### 3. Readiness Windows alineado con el bind real

El falso negativo de RC80 se localizó en una incoherencia concreta: Compose publicaba exclusivamente `127.0.0.1:8501`, mientras el launcher sondeaba `http://localhost:8501/_stcore/health`. La comprobación material que devolvió HTTP 200 había usado explícitamente `127.0.0.1`.

RC81 usa el mismo endpoint IPv4 que publica Compose: `http://127.0.0.1:<puerto>/_stcore/health`. El helper exige HTTP 200 y cuerpo `ok`, y además distingue un contenedor que termina antes de estar listo de un servicio que todavía está iniciando. El navegador se abre sobre la misma dirección y puerto. La corrección debe validarse materialmente en Windows porque el diagnóstico procede de esa plataforma.

### 4. Google Drive administrado sin JSON por integrante

El transporte conserva exclusivamente `https://www.googleapis.com/auth/drive.file` y PKCE. En distribución administrada, Archive Workbench deja de pedir a cada integrante una ruta a `google_drive_client_secret.json`. El identificador del cliente OAuth de escritorio se incorpora una sola vez al construir las imágenes mediante `ARCHIVE_WORKBENCH_GOOGLE_OAUTH_CLIENT_ID`; el workflow toma ese valor de la variable de repositorio homónima.

`Conectar Google Drive` abre la autorización en el navegador anfitrión. El retorno OAuth usa la misma URL loopback que ya publica Archive Workbench, incluida la alternativa de puerto seleccionada por Windows. El token de cada persona se persiste en `ArchiveWorkbenchData/Settings/google_drive_token.json`; el estado PKCE pendiente y el resultado transitorio del selector también viven bajo `ArchiveWorkbenchData/Settings`. Esos archivos pertenecen a la copia local y no se comparten entre integrantes.

La instalación nativa de desarrollo conserva compatibilidad con el JSON de cliente OAuth existente. La distribución administrada no lo solicita.

El flujo de selección de ZIP también usa el OnePicker de escritorio actual con `trigger_onepick=true`, siempre bajo `drive.file`. Después de volver desde Google, la selección queda disponible localmente para confirmar desde la pestaña de intercambio.

**Gate externo pendiente:** el relevo no contiene un `client_id` OAuth real y no debe inventarse. Antes de publicar RC81 debe existir una variable de repositorio `ARCHIVE_WORKBENCH_GOOGLE_OAUTH_CLIENT_ID` con el cliente de escritorio registrado para Archive Workbench. Sin ese valor, los gates de código pueden quedar verdes pero la validación material de `Conectar Google Drive` debe permanecer pendiente.

### 5. Rendimiento de interfaz sin violar el invariante Streamlit

El perfil estático confirmó que `tracked_tabs` era pasivo en `Organizar trabajo` y `Procesar documentos`; el cambio visual de pestaña no viajaba a Python. El costo propio estaba en dos capas frontend: el conservador de pestañas y la ayuda contextual instalaban `MutationObserver` sobre `document.body` y volvían a recorrer clases del DOM ante mutaciones en vistas densas.

RC81 mantiene `st.tabs(..., on_change="ignore")` y `sessionStorage`, pero elimina los observers globales. La búsqueda del scope usa la clase `st-key-*` concreta y los observers quedan limitados al `tablist` o al widget correspondiente. Los títulos se anotan en el montaje del componente sin mantener un observer global. No se introducen `setStateValue`, `setTriggerValue` ni reruns para navegación visual.

En Audio y video, `Opciones avanzadas para crear otra transcripción` deja de ser un `st.toggle` que provocaba un rerun completo. Pasa a `st.popover(..., on_change="ignore")`: abrir y cerrar es una interacción frontend pasiva; los widgets internos mantienen el comportamiento normal cuando la persona realmente modifica parámetros o inicia una transcripción.

## Tags de la candidata

- CPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc81-cpu`;
- NVIDIA GPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc81-gpu`.

La publicación de estos tags todavía no está validada materialmente. RC80 sigue siendo la pareja publicada y validada mientras RC81 no complete sus gates.

## Pruebas automatizadas de RC81

Los gates automatizados locales quedaron cerrados el 29 de agosto de 2026:

- gate focal sobre Google Drive, distribución Docker, navegación, Audio y video, empaquetado y documentación: verde, `exit_code=0`;
- construcción del wheel: `python -m build --wheel` no pudo iniciarse porque la `.venv` local no contiene el módulo `build`; el mismo backend configurado por el proyecto construyó correctamente `archive_workbench-0.89.0-py3-none-any.whl` mediante `pip wheel --no-deps --no-build-isolation`, con `exit_code=0`;
- `pytest --collect-only -q`: 722 pruebas recopiladas sin errores;
- suite completa ejecutada exclusivamente por Alex en su equipo local: alcanzó 100 % con `exit_code=0`. Sólo se registraron 40 `DeprecationWarning` de SQLite/SQLAlchemy bajo Python 3.12.

La suite completa no debe repetirse por esta actualización documental ni por rutina. Sólo corresponde una nueva corrida si aparece un cambio material posterior que la justifique.


## Validación manual inmediata

La primera validación material de RC81 debe hacerse en Windows CPU y en este orden:

1. abrir el selector de proyecto y confirmar tildes/caracteres no ASCII;
2. ocupar 8501 con una aplicación o contenedor ajeno y confirmar mensaje comprensible, ausencia de detención ajena y apertura por puerto alternativo;
3. repetir con 8501 libre y confirmar que el launcher reconoce `/_stcore/health` y abre la aplicación sin falso negativo;
4. pulsar `Conectar Google Drive`, autorizar una cuenta propia y comprobar que el token persiste localmente bajo `ArchiveWorkbenchData/Settings` tras reiniciar;
5. medir la respuesta al abrir `Opciones avanzadas para crear otra transcripción`;
6. medir cambios entre pestañas de `Organizar trabajo`;
7. medir cambios entre pestañas de `Procesar documentos`.

No repetir en esta pasada Surya Linux, transcripción CUDA Linux, persistencia Linux ni publicación RC80 ya cerradas. Windows GPU y macOS se retoman sólo después de que este gate Windows CPU quede verde.

## Persistencia y datos locales

`ArchiveWorkbenchData/` continúa siendo el espacio persistente de la distribución administrada. `pilot_data` no se recrea ni se modifica destructivamente. `pilot_data_2` no forma parte de staging, commits ni paquetes. RC81 no cambia el modelo de proyecto ni la revisión de base.

## Estado de OPS-01

`OPS-01` permanece **parcial, en curso**. RC80 está publicada y materialmente verde en Linux. RC81 queda como próxima candidata para resolver los bloqueantes Windows antes de continuar Windows GPU y macOS. `WEB-01` permanece parcial y queda pausado hasta estabilizar la distribución multiplataforma. No se incorporan capturas hasta realizar esa reescritura para lectores sin conocimiento previo.
