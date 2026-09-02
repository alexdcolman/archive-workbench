# Actualización actual - Archive Workbench 0.89.0 RC83

## Estado de partida

RC82 quedó publicada correctamente como imagen CPU multi-arquitectura `linux/amd64` + `linux/arm64` e imagen NVIDIA GPU `linux/amd64`. La validación material Windows CPU quedó verde en todos los bloques afectados por RC82: un proyecto nuevo abre directamente `Administrar y recuperar` e `Intercambiar cambios`, Google Drive completa OAuth y conserva el token local, una copia sin originales audiovisuales mantiene transcripciones y metadatos sin traceback, y el proyecto real de 138 documentos redujo la entrada a `Organizar trabajo` y `Procesar documentos` a aproximadamente un segundo; el resto de los cambios de sección resultó casi inmediato.

Esa validación dejó tres cuestiones de experiencia concretas. Primero, el título de una pestaña necesita dos clics: el primer gesto sólo la focaliza y el segundo cambia realmente de pestaña. Segundo, una copia completa descargada y verificada desde Google Drive obliga a salir de la aplicación y abrir manualmente otra carpeta aunque el proyecto actual esté vacío. Tercero, cerrar el navegador no detiene el servicio Docker iniciado en modo desacoplado.

## Alcance de RC83

RC83 corrige exclusivamente esos tres bloques. RC83 no cambia el esquema SQLite, no agrega migración y continúa `0047_authority_relation_profiles`. No ejecutar `db-upgrade` por esta candidata. Los arreglos funcionales y de rendimiento ya validados en RC82 no se reabren.

### 1. Pestañas con un solo clic y sin rerun global

`tracked_tabs` sigue siendo navegación visual pasiva: no envía estado ni triggers a Python y conserva la selección en `sessionStorage`. RC83 elimina el observer del conservador de pestañas y registra la intención del usuario en `pointerdown` antes de que el tab nativo procese el clic. El comportamiento nativo no se cancela ni se sustituye. El teclado conserva Enter/Espacio. Así se evita que la restauración visual compita con el primer clic sin reintroducir reruns globales.

### 2. Adoptar una copia completa dentro del proyecto vacío

Cuando `Descargar y verificar ZIP` o el selector local reconoce una `team_copy`, la interfaz ya no termina con instrucciones de extracción manual. Si el proyecto abierto está vacío, ofrece **Usar esta copia en este proyecto**. La operación exige confirmación explícita, verifica el paquete, prepara primero una staging temporal, valida la revisión SQLite recibida, reidentifica allí la copia de equipo, crea una copia de seguridad del proyecto vacío y sólo entonces reemplaza de forma atómica configuración, base y contenido transportado. El ZIP de transporte y los backups locales del proyecto receptor se conservan. Al terminar, la misma sesión vuelve a Inicio sobre la misma carpeta mediante un rerun controlado.

Esta operación está deliberadamente restringida a un proyecto sin unidades archivísticas, objetos digitales ni autoridades. Si el proyecto actual ya contiene trabajo, una copia completa no se mezcla automáticamente: para combinar trabajo entre copias corresponde un paquete incremental de cambios, con su comparación, conflictos y aplicación existentes.

### 3. Cierre explícito de la distribución administrada

Cuando Archive Workbench se ejecuta dentro del workspace administrado aparece **Cerrar Archive Workbench** en la barra lateral. La acción requiere un botón explícito y termina únicamente la instancia actual. Como Streamlit es el subproceso del comando principal del contenedor y Compose no usa una política de reinicio, al finalizar ese proceso sale el contenedor propio y se liberan el puerto y los recursos. La acción no llama a Docker ni intenta detener otros contenedores o aplicaciones.

Los launchers conservan `docker compose up -d`, pero explican que el cierre de la ventana del launcher no equivale a detener el servicio y remiten al control dentro de la aplicación.

## Tags de la candidata

- CPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc83-cpu`;
- NVIDIA GPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc83-gpu`.

RC83 debe publicarse sólo después de aplicar la candidata, cerrar gates locales y ejecutar la suite completa exclusivamente en el equipo de Alex por tratarse de cambios materiales de código.

## Pruebas automatizadas de RC83

Los gates automatizados locales quedaron cerrados el 2 de septiembre de 2026:

- compilación sintáctica de `src` y `tests`: verde;
- gate focal y transversal sobre intercambio/copias de equipo, navegación, distribución Docker, empaquetado y documentación: verde;
- `tests/test_ui_navigation.py` completo: verde;
- `pytest --collect-only -q`: 731 pruebas recopiladas sin errores;
- suite completa ejecutada exclusivamente por Alex en su equipo local: 100 % verde;
- sólo se registraron 40 `DeprecationWarning` ya conocidas de SQLite/SQLAlchemy bajo Python 3.12: 10 en `tests/test_database.py` y 30 en `tests/test_exchange.py`;
- `python -m build --wheel` no pudo iniciarse en el entorno aislado del asistente porque no contiene el módulo `build`; el mismo backend construyó correctamente `archive_workbench-0.89.0-py3-none-any.whl` mediante `pip wheel --no-deps --no-build-isolation`, SHA-256 `af150d545506890e23fc326d96b3224aeec9d8ad7204405a521805771d5379a9`.

La suite completa no debe repetirse por esta actualización documental ni por rutina. Sólo corresponde una nueva corrida si aparece un cambio material posterior de código.

## Validación manual inmediata

Después de publicar las imágenes RC83, repetir sólo lo afectado en Windows CPU:

1. comprobar que cada pestaña cambia con un solo clic y que el cambio sigue siendo prácticamente inmediato;
2. crear un proyecto vacío, descargar y verificar una copia completa desde Google Drive y usar **Usar esta copia en este proyecto** sin salir de la aplicación ni extraer carpetas manualmente; confirmar que el contenido recibido queda disponible y que la copia tiene identidad local propia;
3. comprobar que una copia completa se rechaza como reemplazo automático si el proyecto actual ya contiene trabajo y que la interfaz remite a paquetes de cambios para combinar trabajo;
4. pulsar **Cerrar Archive Workbench** y comprobar desde Windows que la instancia se detiene y el puerto queda libre.

No repetir OAuth, inicialización SQLite, copia audiovisual sin originales ni la medición de 138 documentos salvo que aparezca una regresión concreta. Después de este gate, `OPS-01` continúa con Windows GPU y macOS.

## Persistencia y datos locales

`ArchiveWorkbenchData/` continúa siendo el espacio persistente de la distribución administrada. `pilot_data` no se recrea ni se modifica destructivamente. `pilot_data_2` no forma parte de staging, commits ni paquetes. RC83 no cambia el esquema ni la revisión de base.

## Estado de OPS-01

`OPS-01` permanece **parcial, en curso**. RC82 queda publicada y materialmente verde en Windows CPU para sus bloques funcionales y de rendimiento. RC83 es la candidata activa para cerrar las tres regresiones/limitaciones de UX detectadas antes de continuar Windows GPU y macOS. `WEB-01` permanece parcial y queda pausado hasta estabilizar la distribución multiplataforma. No se incorporan capturas hasta realizar esa reescritura para lectores sin conocimiento previo.
