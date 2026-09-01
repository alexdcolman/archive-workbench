# Actualización actual - Archive Workbench 0.89.0 RC82

## Estado de partida

RC81 fue publicada correctamente como imagen CPU multi-arquitectura `linux/amd64` + `linux/arm64` e imagen NVIDIA GPU `linux/amd64`. El workflow de publicación terminó en verde para ambos jobs. RC81 ya había corregido el selector Windows a UTF-8 con BOM y alineado puerto/readiness sobre `127.0.0.1`; RC82 conserva esos cierres. Las validaciones Linux ya cerradas incluyen Surya CPU/GPU y transcripción audiovisual CUDA; RC82 no reabre esos runtimes. La validación Windows CPU confirmó que la reducción de observers globales eliminó prácticamente el lag al cambiar de pestaña, pero con un proyecto real de 138 documentos todavía se observan aproximadamente 2-3 segundos al cambiar de sección y alrededor de 7 segundos al entrar en `Organizar trabajo` y `Procesar documentos`.

La misma validación abrió cuatro defectos concretos: Google Drive falla en el canje OAuth con `HTTP 400` / `client secret is missing`; un proyecto creado desde el inicio general puede tener la base migrada pero no una fila `Project` hasta visitar Catálogo, lo que rompe `Administrar y recuperar` e `Intercambiar cambios`; una copia deliberadamente preparada sin originales audiovisuales puede propagar `FileNotFoundError`; y los servicios Docker iniciados con `up -d` permanecen activos después de cerrar navegador/ventana, lo que necesita una solución de ciclo de vida comprensible para personas no técnicas.

## Alcance de RC82

RC82 corrige los tres defectos funcionales reproducidos y la causa principal de latencia en las secciones con inventario documental. El ciclo de vida amigable del contenedor queda registrado como pendiente de `OPS-01` para una decisión específica posterior. RC82 no cambia el esquema SQLite, no agrega migración y continúa `0047_authority_relation_profiles`. No ejecutar `db-upgrade` por esta candidata.

### 1. Google Drive con cliente OAuth de escritorio completo

La distribución administrada conserva `https://www.googleapis.com/auth/drive.file`, PKCE y tokens locales bajo `ArchiveWorkbenchData/Settings`. Además del `client_id`, las imágenes incorporan el `client_secret` correspondiente al cliente OAuth de escritorio mediante `ARCHIVE_WORKBENCH_GOOGLE_OAUTH_CLIENT_SECRET`. El workflow lee ese valor desde un GitHub Actions secret homónimo; no se distribuye un JSON por integrante y cada persona autoriza únicamente su propia cuenta.

Antes de publicar RC82 deben existir:

- variable de repositorio `ARCHIVE_WORKBENCH_GOOGLE_OAUTH_CLIENT_ID`;
- secret de repositorio `ARCHIVE_WORKBENCH_GOOGLE_OAUTH_CLIENT_SECRET`.

### 2. Creación de proyectos y Alembic sin estado parcial

`create_ready_project()` ya no termina después de crear archivos y migrar la base: registra inmediatamente el `Project` definido por `decisions.yaml` dentro de la misma preparación. Así, `Administrar y recuperar` e `Intercambiar cambios` no dependen de que la persona visite primero Catálogo.

`upgrade_database()` serializa las ejecuciones de Alembic dentro del proceso para impedir migraciones simultáneas desde sesiones o reruns de Streamlit. El log material de RC81 mostró una migración 0037 interrumpida con `no such table: main.exchange_state_adoptions` y un segundo intento que terminó en `KeyError: 'script'`, patrón compatible con reentrada concurrente de los proxies globales de Alembic. RC82 evita esa concurrencia sin agregar migraciones implícitas.

Al abrir un proyecto, `main()` también verifica que la revisión SQLite sea la requerida antes de renderizar vistas. Una base incompleta se detiene con un mensaje controlado en vez de propagarse como errores posteriores de SQLAlchemy.

### 3. Copias de proyecto sin originales audiovisuales

Una copia de trabajo puede omitir deliberadamente archivos originales y conservar transcripciones, anotaciones y metadatos. `resolve_playback_path()` ya no trata la falta del original como una excepción fatal: usa un derivado de reproducción si existe y, si no existe, devuelve ausencia de reproducción. La interfaz explica que el original no está disponible y deshabilita las operaciones que requieren ese medio, sin impedir revisar la transcripción guardada.

### 4. Rendimiento con inventarios documentales reales

La validación de RC81 mostró que las pestañas ya responden prácticamente al instante. El costo restante se concentraba al entrar en secciones: `processing_inventory_rows()` hacía varias consultas por cada documento y tanto `Procesar documentos` como `Organizar trabajo` reutilizan ese inventario. Con 138 documentos esto producía un patrón N+1 de cientos de consultas.

RC82 carga en bloque archivos, preparaciones, extracciones, páginas extraídas, selecciones, páginas editables y trabajos activos; el número de consultas queda acotado al proyecto y deja de crecer linealmente por documento. Además, `review_app.main()` deja de cargar `review_document_rows()` para secciones que no lo necesitan: el inventario de revisión se consulta sólo para `Revisar documentos`, `Búsqueda textual` o una navegación pendiente hacia un resultado.

No se cambia el invariante Streamlit: las pestañas siguen siendo navegación visual pasiva y no se reintroducen reruns globales al cambiarlas.

## Tags de la candidata

- CPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc82-cpu`;
- NVIDIA GPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc82-gpu`.

Estos tags no deben publicarse hasta aplicar RC82 al repositorio, cerrar los gates locales y configurar el `client_secret` OAuth real en GitHub.

## Pruebas automatizadas de RC82

Los gates automatizados locales quedaron cerrados el 1 de septiembre de 2026:

- gate focal y transversal sobre creación de proyecto y migraciones, Google Drive, Audio y video, procesamiento, navegación, distribución Docker, empaquetado y documentación: verde;
- `pytest --collect-only -q`: 726 pruebas recopiladas sin errores;
- suite completa ejecutada exclusivamente por Alex en su equipo local: 100 % verde;
- sólo se registraron 40 `DeprecationWarning` ya conocidas de SQLite/SQLAlchemy bajo Python 3.12: 10 en `tests/test_database.py` y 30 en `tests/test_exchange.py`.

La suite completa no debe repetirse por esta actualización documental ni por rutina. Sólo corresponde una nueva corrida si aparece un cambio material posterior de código.

## Validación manual inmediata

Después de publicar las imágenes RC82, repetir sólo los comportamientos materialmente afectados en Windows CPU:

1. crear un proyecto nuevo y abrir directamente `Administrar y recuperar` e `Intercambiar cambios`, sin visitar antes Catálogo;
2. conectar Google Drive y comprobar autorización y persistencia del token tras reiniciar;
3. abrir una copia de proyecto sin originales audiovisuales y confirmar que Audio y video conserva transcripción/metadatos sin traceback;
4. con el proyecto real de 138 documentos, medir el cambio entre secciones y especialmente la entrada en `Organizar trabajo` y `Procesar documentos`;
5. comprobar que el cambio entre pestañas continúa siendo prácticamente inmediato.

No repetir Surya Linux, transcripción CUDA Linux, persistencia Linux ni las publicaciones RC80/RC81 ya cerradas salvo evidencia nueva. Windows GPU y macOS continúan después del gate Windows CPU.

## Persistencia y datos locales

`ArchiveWorkbenchData/` continúa siendo el espacio persistente de la distribución administrada. `pilot_data` no se recrea ni se modifica destructivamente. `pilot_data_2` no forma parte de staging, commits ni paquetes. RC82 no cambia el esquema ni la revisión de base.

## Estado de OPS-01

`OPS-01` permanece **parcial, en curso**. RC81 quedó publicada y sirvió para aislar los defectos Windows descritos arriba. RC82 es la candidata activa. El cierre del ciclo de vida del contenedor para personas no técnicas permanece abierto: cerrar el navegador no detiene por sí solo un servicio iniciado con Docker Compose en modo desacoplado, y la solución final debe ser explícita, segura y no detener procesos ajenos. `WEB-01` permanece parcial y queda pausado hasta estabilizar la distribución multiplataforma. No se incorporan capturas hasta realizar esa reescritura para lectores sin conocimiento previo.
