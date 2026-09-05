# Actualización actual - Archive Workbench 0.89.0 RC84

## Estado de partida

RC83 quedó publicada correctamente como imagen CPU multi-arquitectura `linux/amd64` + `linux/arm64` e imagen NVIDIA GPU `linux/amd64`. La validación material Windows CPU cerró los cuatro bloques específicos de RC83: las pestañas cambian con un solo clic y sin lag apreciable, una copia completa recibida puede adoptarse dentro de un proyecto vacío sin salir de la aplicación, un proyecto con trabajo rechaza ese reemplazo automático y remite al paquete incremental, y **Cerrar Archive Workbench** termina la instancia propia y libera el puerto.

La misma recorrida detectó una única regresión menor de navegación externa. Tanto **Conectar Google Drive** como **Elegir ZIP en Google Drive** abren Google en una pestaña auxiliar. La autorización y la selección se completan correctamente, pero al volver desde Google esa pestaña inicia una sesión Streamlit independiente y, después de procesar el callback, continuaba hasta el inicio general, mostrando **Crear un proyecto nuevo / Abrir uno existente**. Ese launcher no pertenece al flujo de OAuth ni del selector y resulta confuso.

## Alcance de RC84

RC84 corrige exclusivamente la terminación del callback web de Google Drive en la distribución administrada. No cambia OAuth, permisos, PKCE, almacenamiento de tokens, Google Picker, descarga/subida, intercambio, SQLite ni rendimiento. RC84 no cambia el esquema SQLite, no agrega migración y continúa `0047_authority_relation_profiles`. No ejecutar `db-upgrade` por esta candidata.

### Callback auxiliar de Google Drive como flujo terminal

`_handle_google_drive_oauth_callback()` se ejecuta antes de resolver proyecto, preferencias o vistas. Cuando detecta un retorno de Google, completa la autorización o la selección, persiste el resultado en `ArchiveWorkbenchData/Settings`, limpia los parámetros sensibles de la URL y conserva en la sesión auxiliar un resultado terminal. `main()` detiene allí el render mediante `st.stop()`.

La pestaña auxiliar muestra únicamente el resultado de Google Drive y la indicación de volver a la pestaña de Archive Workbench que ya estaba abierta. No muestra el launcher, no crea una segunda navegación de proyecto y no intenta trasladar `session_state` entre pestañas. La pestaña original continúa siendo la sesión de trabajo; los tokens y la selección de Picker se comparten mediante la persistencia local ya existente.

Este comportamiento se incorpora al invariante Streamlit como caso de **sesión auxiliar terminal**: cuando un proveedor externo vuelve a una pestaña nueva que sólo existe para completar un callback, esa sesión no debe continuar hacia el árbol normal de la aplicación.

## Estado validado de RC83

La suite completa de RC83 fue ejecutada exclusivamente por Alex y quedó 100 % verde con 731 pruebas recopiladas. Sólo aparecieron las 40 `DeprecationWarning` ya conocidas de SQLite/SQLAlchemy bajo Python 3.12: 10 en `tests/test_database.py` y 30 en `tests/test_exchange.py`.

La validación material Windows CPU de RC83 quedó verde para:

1. pestañas con un solo clic y respuesta prácticamente inmediata;
2. adopción de copia completa en proyecto vacío dentro de la misma aplicación;
3. rechazo seguro de copia completa sobre proyecto con trabajo;
4. cierre explícito de la instancia administrada y liberación del puerto.

No repetir esos cuatro bloques por RC84 salvo regresión concreta.

## Tags de la candidata

- CPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc84-cpu`;
- NVIDIA GPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc84-gpu`.

## Pruebas automatizadas de RC84

Los gates automatizados locales quedaron cerrados el 4 de septiembre de 2026:

- gate focal y transversal sobre Google Drive/OAuth/Picker, navegación, distribución Docker, empaquetado y documentación: verde;
- `pytest --collect-only -q`: 733 pruebas recopiladas sin errores;
- suite completa ejecutada exclusivamente por Alex en su equipo local: 100 % verde;
- sólo se registraron 40 `DeprecationWarning` ya conocidas de SQLite/SQLAlchemy bajo Python 3.12: 10 en `tests/test_database.py` y 30 en `tests/test_exchange.py`.

La suite completa no debe repetirse por esta actualización documental ni por rutina. Sólo corresponde una nueva corrida si aparece un cambio material posterior de código.
## Validación manual inmediata

Después de publicar las imágenes RC84, validar en Windows CPU sólo el callback auxiliar:

1. usar **Elegir ZIP en Google Drive** desde un proyecto abierto;
2. completar la selección en Google;
3. comprobar que la pestaña auxiliar vuelve a Archive Workbench mostrando únicamente el resultado y la indicación de regresar a la pestaña original, sin **Crear un proyecto nuevo / Abrir uno existente**;
4. volver a la pestaña original y usar la selección normalmente.

Si la cuenta no estuviera conectada en una instalación limpia, **Conectar Google Drive** debe seguir el mismo patrón terminal. No eliminar tokens locales sólo para repetir esa variante.

No repetir rendimiento, OAuth funcional, inicialización SQLite, audiovisual sin originales, adopción de copia completa, pestañas ni cierre del contenedor. Después de este gate acotado, `OPS-01` continúa con Windows GPU y macOS.

## Persistencia y datos locales

`ArchiveWorkbenchData/` continúa siendo el espacio persistente de la distribución administrada. `pilot_data` no se recrea ni se modifica destructivamente. `pilot_data_2` no forma parte de staging, commits ni paquetes. RC84 no cambia esquema ni revisión de base.

## Estado de OPS-01

`OPS-01` queda **cerrado para el pre-release con alcance de validación explícito**. RC84 está publicada y la ruta Windows CPU quedó materialmente verde, incluido el callback auxiliar de Google Drive. Las validaciones materiales Linux ya cubren CPU y NVIDIA GPU. La construcción publicada también cubre CPU `linux/amd64` y `linux/arm64` y GPU NVIDIA `linux/amd64`.

No se dispone de una máquina Windows con GPU NVIDIA ni de una máquina macOS para realizar las dos comprobaciones materiales restantes. Esas ausencias se registran como limitaciones de validación por hardware no disponible, no como fallos conocidos ni como bloqueantes del pre-release. Si más adelante se dispone de esos equipos, corresponde ejecutar únicamente sus recorridos de arranque administrado.

`WEB-01` deja de estar pausado y vuelve a ser el bloque activo de la secuencia principal: corresponde reescribir el sitio y el README para lectores sin conocimiento previo.
