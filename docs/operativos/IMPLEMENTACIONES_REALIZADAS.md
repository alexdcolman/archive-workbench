## RC79 - transcripción audiovisual GPU validada y métrica VRAM en Docker

La imagen GPU RC77 completó una transcripción real de `RememorArte Horacio BAU` con `faster-whisper 1.2.1`, `large-v3`, `device=cuda`, `float16`, VAD activado y `beam_size=5`. La corrida produjo 64 segmentos, quedó `completed` y mostró un proceso CUDA real. La primera ejecución incluyó la descarga de `Systran/faster-whisper-large-v3` al caché persistente administrado, por lo que su tiempo total incluye preparación del modelo y no se usa como benchmark puro. Al finalizar se liberó la memoria del modelo; quedó únicamente el contexto CUDA liviano del proceso Streamlit.

La corrida reveló que `_runtime_metrics.peak_gpu_memory_mib` quedaba en `null` dentro de Docker. El monitor usaba `os.getpid()` del espacio de nombres del contenedor, mientras `nvidia-smi --query-compute-apps` devuelve el PID del anfitrión. RC79 conserva la coincidencia directa para ejecución nativa y agrega un fallback acotado para runtime administrado: sólo atribuye memoria cuando existe un único proceso de cómputo cuyo ejecutable coincide con el Python actual; ante ambigüedad devuelve `None`. No cambia el backend audiovisual, la interfaz, SQLite ni la revisión `0047_authority_relation_profiles`.

El gate focal reveló además dos tests de AV-03 ya desactualizados en RC78: seguían buscando rótulos anteriores a la reorganización de la interfaz aunque las capacidades de evaluación y comparación permanecían presentes. RC79 actualiza únicamente esos literales de prueba a los nombres vigentes; no cambia la interfaz ni el comportamiento audiovisual.

## RC78 - diagnóstico administrado GPU y validación material Linux/NVIDIA

La validación material de RC77 cerró las extracciones Surya de distribución en CPU y GPU sobre una copia descartable. En la imagen GPU, Docker y Torch detectaron la RTX 3090, `llama-server` CUDA se inició dentro del contenedor, Surya 0.22.1 completó una página y el proceso se retiró al finalizar, devolviendo la VRAM al nivel basal. La salida quedó registrada como `surya_cli` completada. La prueba también confirmó que la identificación visible del motor conserva el resultado esperado.

El único defecto observado fue diagnóstico: `extraction-doctor` seguía evaluando la ruta GPU como si Surya debiera lanzar un contenedor vLLM anidado. RC78 reconoce el contrato de la distribución administrada: cuando `ARCHIVE_WORKBENCH_SURYA_BACKEND=llamacpp` y la variante es `gpu`, exige el `llama-server` incluido y acceso NVIDIA directo dentro del contenedor, sin requerir Docker anidado. El runtime de extracción no cambia. Sin migración; continúa `0047_authority_relation_profiles`.

## RC77 - guardas de inferencia para Surya/llama.cpp administrado

La primera corrida Surya real de RC76 confirmó que el preflight, `LLAMA_CPP_BINARY`, `LD_LIBRARY_PATH`, el cache y el arranque de llama.cpp ya funcionan dentro de la imagen CPU. El fallo restante ocurrió durante la inferencia: Surya 0.22.1 permite 12288 tokens para OCR full-page y aplica 600 segundos por petición; la salida observada siguió generando más de 8000 tokens hasta que la tarea externa agotó 2100 segundos y activó el fallback Docling.

RC77 limita únicamente el modo administrado `ARCHIVE_WORKBENCH_SURYA_BACKEND=llamacpp`: el timeout de petición toma por defecto `document_timeout_seconds` y el OCR full-page usa 8192 tokens como techo. Los valores definidos explícitamente en el entorno tienen prioridad. `raw/surya.log` registra ambos parámetros. Las instalaciones nativas y otros backends no cambian. La validación material de una extracción CPU sigue abierta; no hay migración y continúa `0047_authority_relation_profiles`.

## RC76 - runtime Surya administrado y continuidad visual de pestañas

La primera extracción real intentada con RC75 mostró que el fallback Docling podía activarse antes de iniciar Surya. RC76 alinea el diagnóstico con el runtime real de las imágenes: el probe usa `LLAMA_CPP_BINARY=/opt/llama/llama-server` y, cuando `ARCHIVE_WORKBENCH_SURYA_BACKEND=llamacpp`, el subproceso conserva `LD_LIBRARY_PATH` para poder cargar las bibliotecas copiadas a `/opt/llama`. El contrato nativo anterior de `surya_clean_library_path` permanece sin cambios fuera del modo administrado.

La interfaz de **Elegir texto** hace visible el motor de cada corrida, de modo que una salida Docling no pueda confundirse con una salida Surya. En paralelo, `tracked_tabs()` conserva la pestaña visual activa en `sessionStorage` con un componente v2 pasivo, sin estado ni trigger hacia Python; las aperturas programáticas mediante `request_tab()` siguen teniendo prioridad después de una acción semántica. No hay migración y continúa `0047_authority_relation_profiles`.

## RC75 - apertura de proyectos locales desde los lanzadores multiplataforma

Después del primer preflight CPU material verde de RC74, RC75 elimina la obligación de copiar un proyecto existente a `ArchiveWorkbenchData/Projects`. Los lanzadores CPU/GPU de Windows y Linux, y el lanzador CPU de macOS, permiten elegir la carpeta principal de un proyecto mediante el selector gráfico del sistema anfitrión. Compose monta únicamente esa carpeta como `/selected-project` y el entrypoint abre directamente ese proyecto. Elegir el inicio general conserva el launcher administrado y la creación de proyectos dentro de `ArchiveWorkbenchData/Projects`.

Los selectores validan `config/decisions.yaml` antes de iniciar Docker y advierten que una carpeta sincronizada en vivo por Google Drive, OneDrive, Dropbox o iCloud no debe usarse como SQLite activa. Los lanzadores reutilizan un tag local ya disponible antes de intentar descargarlo, lo que permite una validación material previa a GHCR. No cambia el modelo de datos ni la instalación nativa. Continúa `0047_authority_relation_profiles` y no hay migración.

## RC74 - corrección del cargador de bibliotecas de llama.cpp en contenedores

El primer build material CPU de RC73 falló antes de instalar Archive Workbench porque `/opt/llama/llama-server` no encontraba `libllama-server-impl.so`. RC74 conserva el contenido completo del stage upstream y agrega su carpeta a la ruta del cargador dinámico: `/opt/llama` en CPU y `/opt/llama:/usr/local/cuda/lib64` en GPU. Ambos Dockerfiles comprueban además que `libllama-server-impl.so` exista antes de ejecutar `llama-server --version`. Los tags pasan a `0.89.0-rc74-cpu` y `0.89.0-rc74-gpu`. La validación material continúa abierta hasta repetir el build CPU. Sin migración; continúa `0047_authority_relation_profiles`.

## RC73 - imágenes separadas CPU y NVIDIA GPU para OPS-01

RC73 reemplaza el único runtime administrado de RC72 por dos imágenes explícitas. La imagen CPU se publica como manifest multi-arquitectura para `linux/amd64` y `linux/arm64`, incorpora `llama-server` CPU y fuerza PyTorch CPU dentro del entorno aislado de Surya. La imagen GPU usa `nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04`, incorpora `llama-server` CUDA 12, instala PyTorch CUDA 12.8 para Surya y mantiene cuBLAS/cuDNN disponibles para tareas compatibles. El modo administrado fuerza ese backend incluido y evita que Surya intente iniciar Docker dentro del contenedor; las instalaciones nativas conservan el contrato histórico.

`compose.yaml` separa `app-cpu` y `app-gpu`; los dos montan la misma `ArchiveWorkbenchData` y declaran la variante al runtime. Los lanzadores normales usan CPU; Windows y Linux agregan lanzadores GPU con una comprobación previa de `nvidia-smi`. macOS queda en CPU porque Docker Desktop no expone una GPU NVIDIA local. El workflow de GHCR publica CPU para amd64/arm64 y GPU para amd64. Se elimina la construcción local automática: una persona usuaria sólo descarga imágenes ya publicadas.

La implementación queda parcial hasta ejecutar los builds reales y probarlos en hosts limpios. No hay migración y continúa `0047_authority_relation_profiles`.

## RC72 - primera distribución CPU multiplataforma de OPS-01

La revisión editorial de RC71 pausa `WEB-01` y prioriza una forma de ejecución que no dependa de Linux ni de conocimientos de terminal. RC72 agrega una distribución administrada basada en contenedor para Windows, macOS y Linux. `compose.yaml` monta una única carpeta persistente `ArchiveWorkbenchData/`; los proyectos viven en `Projects`, los documentos para incorporación por lote en `Imports/Documents`, los medios audiovisuales en `Imports/AudioVideo` y las preferencias/cachés descargables en `Settings`. Ninguno de esos datos entra en la imagen.

El launcher detecta el espacio administrado mediante variables de entorno y crea/abre proyectos sólo dentro de la carpeta visible del anfitrión. La incorporación por lote y audiovisual puede leer las carpetas de importación sin recurrir a `zenity`, que sólo permanece para instalaciones nativas Linux. Se agregan lanzadores de inicio/detención para Windows, macOS y Linux, `Dockerfile`, `compose.yaml`, workflow de publicación a GHCR y una primera guía de inicio. La imagen CPU instala el runtime principal y mantiene Surya en un entorno Python separado para conservar el contrato existente de extracción.

Esta implementación queda **parcial** hasta construir/publicar la imagen en infraestructura con Docker y validarla en máquinas limpias de los tres sistemas operativos. El perfil GPU/NVIDIA permanece pendiente. No hay migración y continúa `0047_authority_relation_profiles`.


## RC71 - cierre de UX-02 e inicio de WEB-01

La recorrida manual posterior a RC70 cierra `UX-02`. RC71 construye la primera documentación pública multipágina de Archive Workbench bajo `docs/`, reorganiza el README y agrega diagramas técnicos accesibles. `WEB-01` permanece parcial únicamente por la producción e incorporación de capturas reales, su revisión editorial y la comprobación final sobre GitHub Pages. No hay migración ni cambios en la lógica de la aplicación.

## RC70 - cierre de DISC-03 e inicio de UX-02

La validación manual de RC69 confirmó una mejora material de `Buscar nuevas entidades` con `local_rules_v5` y permite cerrar `DISC-03`. Las versiones v1-v5 y las corridas históricas permanecen reproducibles; el descubrimiento sigue produciendo referencias para revisar y no crea automáticamente entidades o relaciones. No se reabre este bloque sin una regresión concreta.

RC70 inicia `UX-02` con una auditoría transversal de cinco pasadas sobre la interfaz acumulada. **Casilleros y campos** reemplaza cinco superficies simultáneas por un selector compacto de tarea, conservando la página visible en la columna izquierda. **Orden y estructura** mantiene la propuesta visual pero relega la tabla extensa del orden a un detalle informativo cerrado. **Leer una zona** vuelve a exponer sus seis pasos y elimina dos rótulos genéricos `Más opciones`, sin cambiar extracción, persistencia ni revisión. La auditoría queda preservada en `docs/historico/actualizaciones/AUDITORIA_UX02_RC70_5_PASADAS.md`. `UX-02` permanece parcial hasta una recorrida manual representativa sobre `pilot_data`. Sin migración.

## RC69 - aplicación efectiva de reglas vigentes en DISC-03

RC69 corrige una brecha entre la implementación y el recorrido real: una configuración persistida conservaba `provider_version`, de modo que podía seguir ejecutando v3 aunque la aplicación ya incluyera v4. La interfaz ahora identifica configuraciones y corridas históricas, exige actualización explícita antes de una nueva búsqueda local y conserva las corridas anteriores sin recalcularlas. `local_rules_v5` endurece `Obra / publicación` eliminando propagación contextual amplia y mantiene los límites nominales completos de v4. La vista muestra 500 referencias por defecto, con 100/250/1000/Todas como alternativas. `DISC-03` sigue parcial hasta validación de una corrida nueva v5. Sin migración.

## RC68 - precisión y visibilidad de candidatos de DISC-03

La revisión humana de RC67 reveló que `local_rules_v3` todavía producía demasiadas obras por citas entrecomilladas, recortaba nombres e instituciones en límites lingüísticamente incompletos y la interfaz sólo consultaba 500 candidatos aunque la corrida contuviera más. RC68 conserva v1/v2/v3 y agrega `local_rules_v4` para perfiles nuevos.

v4 exige evidencia positiva para **Obra / publicación**, completa partículas e iniciales necesarias en actores e instituciones y corta antes de separadores de procedencia. La vista de revisión deja de usar el límite fijo de 500, informa total de corrida, coincidencias por filtro y estados, y permite mostrar `Todas`, `100`, `250`, `500` o `1000`. `config/discovery_evaluation_corpus_disc03_rc68.jsonl` protege los casos reportados sin incluir datos reales del piloto. `DISC-03` continúa parcial hasta validación manual de una corrida v4. No hay migración ni escrituras canónicas automáticas.

## RC67 - segunda fase de DISC-03 sobre exportaciones reales

RC67 audita `local_rules_v2` de sólo lectura sobre dos exportaciones reales ya producidas durante el piloto: 138 documentos y 78 segmentos audiovisuales. Los archivos reales no ingresan al repositorio ni al paquete. A partir de los errores observados incorpora `local_rules_v3`, preservando v1/v2 para reproducibilidad y para continuidad histórica de candidatos.

La nueva versión refina títulos entrecomillados, contexto temporal de días y `mañana`, secuencias abreviadas de años, personas/lugares testimoniales y acciones/acontecimientos contextualizados. `config/discovery_evaluation_corpus_disc03_real_patterns.jsonl` agrega 41 regresiones sintéticas que generalizan esos patrones. Sobre el benchmark RC66 de 46 controles, v3 resuelve los seis holdouts de las familias locales; sobre el corpus nuevo resuelve las 33 anotaciones esperadas. Ambos son corpus de regresión, no estimaciones de rendimiento sobre documentos futuros. `DISC-03` sigue parcial hasta una revisión humana acotada de candidatos v3 reales. No hay migración ni escrituras canónicas automáticas.

## RC66 - cierre pre-release de PILOT-01 y primera fase de DISC-03

La validación manual de RC65 cerró `PILOT-01A`: Catálogo mostró correctamente el repositorio como contexto de custodia, `rememorARTE` como colección construida y audiovisual separó publicación de plataforma y copia incorporada. Con ese cierre, `PILOT-01` queda completado para pre-release; `PILOT-01N` permanece explícitamente post-release.

RC66 inicia `DISC-03` con versionado conservador del proveedor local. `local_rules_v1` permanece disponible sin cambios; `local_rules_v2` pasa a ser la versión local vigente para perfiles nuevos. La continuidad por redetección conserva la versión de origen. El corpus DISC-03 incorpora 46 controles heterogéneos y holdouts: F1 micro pasa de `0.675676` en v1 a `0.911765` en v2 sobre las seis familias locales. La separación entre sugerencias y registros canónicos no cambia. `DISC-03` queda parcial hasta una auditoría sobre corpus real. No hay migración.

## PILOT-01 — grafo y primera exportación del corpus — validados en RC49

La validación manual cerró `PILOT-01Z`: pantalla completa, leyenda y economía simétrica de rótulos estructurales quedaron verdes. La utilidad analítica profunda del grafo queda para investigaciones concretas. En Exportar corpus se validó sobre el proyecto persistente un JSONL de 138 documentos y el paquete texto + imágenes; ambos se materializaron correctamente y el JSONL real permitió auditar la autosuficiencia del contrato externo.

## RC49 - economía simétrica de rótulos estructurales del grafo

La validación manual de RC48 confirmó apertura correcta del grafo, pantalla completa, leyenda y comportamiento local sin reruns. RC49 no reabre esos puntos: amplía únicamente la regla de economía visual para que las relaciones estructurales inversas de pertenencia (`es parte de`, `parte de`, `forma parte de`) se traten igual que `contiene`/`contiene parte`. La ocultación sólo se aplica a vínculos estructurales `hierarchy`, `document` o `part`; las relaciones analíticas conservan siempre sus rótulos aunque usen palabras parecidas. `PILOT-01Z` queda pendiente sólo de una comprobación visual rápida de esta simetría. Sin migración; continúa `0047_authority_relation_profiles`.

## RC48 - corrección de montaje Bidi del refinamiento visual del grafo

La validación manual de RC46 cerró `PILOT-01Y`: el recorrido textual/semántico compacto, su cierre local sin perder documento/página/bloque y la búsqueda semántica desde cualquier bloque seleccionado quedaron aprobados. Las pasadas manuales previas también permiten cerrar `PILOT-01U`, `PILOT-01V` y `PILOT-01W`: los paneles complejos usan superficies inline de ancho completo, el descarte audiovisual queda subordinado y reversible, y `Explorar relaciones` acepta autoridades `Familia` sin error.

La validación funcional del grafo quedó verde para foco, filtros, jerarquía, temporalidad y navegación. RC47 agregó `Pantalla completa`, `Leyenda` y menor ruido de rótulos estructurales, pero la validación real detectó que el componente intentaba usar `classList` sobre la raíz de montaje Bidi. RC48 conserva esas mejoras y las aplica sobre un `HTMLElement` propio `.awg-root`; `parentElement` queda limitado a montaje/estado local. `PILOT-01Z` sigue abierto sólo hasta validar estas mejoras. Sin migración; continúa `0047_authority_relation_profiles`.

## RC46 - ajustes finales del recorrido semántico en Revisar documentos

La validación manual de RC45 confirmó distribución, puntuaciones, umbral, navegación anterior/siguiente, retorno conservando parámetros y búsqueda de pasajes similares. RC46 no reabre esas capacidades: compacta el recorrido y lo coloca debajo del visor dentro del fragmento local de revisión; cerrar la navegación deja de provocar un rerun global y sólo elimina el contexto de recorrido; y cualquier bloque seleccionado puede iniciar una nueva búsqueda semántica por similitud a partir de su texto revisado, excluyendo de la respuesta los fragmentos indexados que contengan el mismo objeto. `PILOT-01Y` permanece abierto sólo hasta la validación manual de estos tres ajustes. Sin migración; continúa `0047_authority_relation_profiles`.

## RC45 - cierre de Búsqueda textual y exploración de Búsqueda semántica

La validación manual de RC44 cerró `PILOT-01X`: `Concordancias`, `Distribución de los resultados`, recorrido anterior/siguiente y retorno conservando consulta/filtros quedaron aprobados y no deben repetirse salvo regresión. RC45 mantiene esas capacidades y agrega a `Revisar documentos` una acción explícita para cerrar el recorrido de resultados. En Búsqueda semántica agrega distribución plegada, similitud coseno visible, umbral mínimo dentro de opciones secundarias, conservación de consulta/filtros al volver, recorrido anterior/siguiente/cierre dentro de Revisión y búsqueda de pasajes similares a partir del texto completo de un resultado, excluyendo el pasaje semilla. `PILOT-01Y` queda pendiente de validación manual. No hay migración nueva; continúa `0047_authority_relation_profiles`.

# Implementaciones realizadas — Archive Workbench

**Estado actualizado:** 2026-08-26 · **versión de trabajo:** 0.89.0 RC77

## RC65 - cierre de PILOT-01AE y modelo descriptivo de PILOT-01A

La validación manual de RC64 dejó verdes las superficies reparadas y cierra `PILOT-01AE`. No se repiten los recorridos funcionales ya aprobados.

RC65 implementa la parte técnica de `PILOT-01A` sin migración. `ArchivalLevelDefinition` admite semántica explícita para contexto de custodia, conjuntos documentales, recursos y contenedores, con tipos de conjunto para Fondo, Colección, Serie, File/Legajo y otras agrupaciones. Los proyectos anteriores siguen cargando mediante inferencia compatible. Catálogo muestra `Archivo` como contexto de custodia cuando corresponde y distingue esa relación de la jerarquía documental y de la ubicación física; una unidad contenedora se presenta como ubicación física aunque su nivel superior sea un conjunto documental.

La procedencia de plataforma conserva ahora tres capas aditivas: publicación remota, agrupación externa y copia local incorporada. Una playlist no se importa como medio ni se convierte automáticamente en Colección o Serie. Los registros anteriores mantienen sus campos y pueden recuperar un `list=` de una URL histórica de YouTube sin modificar la base. `PILOT-01A` queda parcial sólo hasta la validación focal sobre `rememorARTE` y el audiovisual real ya incorporado.

## RC64 - reparación de regresiones de la candidata Streamlit RC63

La primera validación manual de RC63 se interrumpió por tracebacks en **Explorar relaciones**, **Exportar corpus** y **Revisar documentos**. La auditoría de reparación detectó además el mismo patrón en **Búsqueda textual** y **Búsqueda semántica**: variables necesarias para el recorrido principal se inicializaban sólo dentro de paneles opcionales y cuatro toggles destinados a abrir contenido reactivo habían quedado dentro del mismo `st.form`.

RC64 conserva el alcance de `PILOT-01AE` y repara esas regresiones: el grafo usa un estado aplicado durable para filtros y canvas; Revisión usa la página seleccionada y conserva sus opciones de visualización; los filtros textuales y las opciones técnicas semánticas se controlan fuera de los formularios; Exportar corpus conserva período/separadores con los paneles cerrados y agrega el import faltante de `Path`. Se agrega un guardrail estructural limitado al patrón realmente prohibido, sin convertir todos los toggles dentro de formularios en una prohibición nueva. `PILOT-01AE` continúa abierto hasta la validación manual de RC64.

## RC63 - reparación transversal del comportamiento Streamlit

Después de cerrar `PILOT-01E` por validación manual de RC62, una auditoría exhaustiva de toda la app detectó cinco residuos históricos contra el invariante Streamlit. El informe se conserva en `docs/historico/actualizaciones/AUDITORIA_EXHAUSTIVA_STREAMLIT_ARCHIVE_WORKBENCH_RC62.md`. RC63 intentó implementar la reparación transversal: pestañas pasivas por defecto, 23 flujos reactivos retirados de `st.expander`, validación post-submit de la confirmación de desvinculación en Catálogo, eliminación de la escritura audiovisual por Enter y aplicación pendiente de la selección de perfil en Descubrimiento.

La candidata no cambió contratos de dominio ni esquema y agregó guardrails globales, pero la primera validación manual encontró regresiones antes del cierre. RC63 queda supersedida por RC64 y no debe considerarse una candidata validada.

## Cierre de PILOT-01E - identidad y redacción explícita - validado en RC62

La recorrida manual de RC62 aprobó la arquitectura **Audio y video**, la separación entre incorporación y transcripción/revisión y la aclaración de formatos locales. Con esa validación queda satisfecho el criterio de cierre de `PILOT-01E`: identidad obligatoria, referentes explícitos, jerarquía técnica subordinada y recorrido comprensible sin guía externa. No reabrir este bloque salvo una regresión concreta.

## RC62 - formatos visibles en la incorporación audiovisual local

RC62 completa la reorganización de **Audio y video** con una aclaración visible, sólo en **Desde esta computadora**, de los formatos admitidos para incorporación local. La lista no se mantiene a mano: se genera a partir de `AUDIO_EXTENSIONS` y `VIDEO_EXTENSIONS`, que también gobiernan el selector y la detección de tipo audiovisual. Audio admite AAC, AIF, AIFF, ALAC, FLAC, M4A, MP3, OGG, OPUS, WAV y WMA; video admite AVI, M2TS, M4V, MKV, MOV, MP4, MPEG, MPG, MTS, TS, WEBM y WMV.

No cambia registro, reproducción, transcripción ni persistencia. La validación manual posterior de RC62 aprobó esta aclaración y cerró `PILOT-01E`.

## RC61 - arquitectura unificada de Audio y video

La recorrida manual de RC60 detectó que la sección audiovisual todavía mezclaba incorporación y trabajo de transcripción, y que los dos métodos de incorporación estaban separados entre Catálogo (archivo local) y un panel propio de plataforma. RC61 reorganiza la interfaz como **Audio y video** con dos tareas principales: **Incorporar audio o video** y **Transcribir y revisar**.

La primera tarea presenta **Desde esta computadora** y **Desde una plataforma web** como métodos alternativos, no como funciones paralelas. La selección local usa el selector gráfico del sistema y permite múltiples archivos. El registro no duplica lógica: llama a `register_external_file()`, que reutiliza el circuito canónico de Catálogo y crea o reutiliza `DigitalObject`, `FileInstance`, `SourceRegistration` y `AudiovisualMedia`. El método de plataforma mantiene el contrato de `AV-02` y no inicia transcripción automáticamente. Después de incorporar, el material puede abrirse directamente en **Transcribir y revisar**.

Las dos tareas principales usan pestañas sin rerun forzado al cambiar visualmente entre ellas. Los recorridos secundarios de descarte y restauración de versiones pasan de expanders interactivos a controles persistentes. La auditoría semántica en cinco pasadas de la superficie modificada corrigió además el rótulo descriptivo aislado `Fecha` a **Fecha de registro, producción o publicación**. No hay migración y no se reabren las validaciones funcionales de `AV-01`, `AV-02` ni `AV-03`. `PILOT-01E` permanece abierto hasta la validación manual de esta reorganización.

## RC60 - auditoría transversal final de PILOT-01E

La validación manual de RC59 confirmó el contrato público PDF/TIFF/PNG/JPEG/WebP y deja `PILOT-01L` cerrado. RC60 no reabre esa capacidad ni los recorridos funcionales del piloto.

Se completaron las cinco pasadas semánticas previstas por `PILOT-01E` sobre la interfaz vigente. Se corrigieron residuos de referente y jerarquía: abreviaturas `obj.` en Catálogo, deícticos `acá`, `source_key` usado como rótulo de progreso en Procesar documentos, desambiguación visible mediante identificadores técnicos y rutas/SHA-256 mostrados con demasiada jerarquía en Exportar corpus y copias de seguridad. Los datos técnicos siguen disponibles en detalles cerrados y los widgets conservan identidades internas estables.

La auditoría queda preservada en `docs/historico/actualizaciones/AUDITORIA_INTERFAZ_RC60_5_PASADAS.txt`. **No se declara `PILOT-01E` cerrado todavía**: su último criterio requiere una recorrida manual sin guía externa para confirmar que la aplicación se entiende por sí sola. No hay migración; continúa `0047_authority_relation_profiles`.


## RC59 - formatos documentales y cierre de PILOT-01I / PILOT-01AD / PILOT-01L

La validación manual de RC58 cerró `PILOT-01AD`: el cambio entre pestañas de **Procesar documentos** dejó de producir la reconstrucción visual observada y los documentos homónimos permanecen independientes al seleccionar o quitar uno. No se reabre esa validación sin una regresión concreta.

`PILOT-01I` quedó cerrado con evidencia real en GPU. En una extracción individual `VLLM::EngineCore` desapareció al finalizar; en un lote de varios documentos se mantuvo activo entre documentos para reutilizar el servidor y desapareció al terminar el lote completo. En ambos casos la VRAM volvió al nivel basal sin comandos manuales.

`PILOT-01L` queda cerrado con un contrato público deliberadamente acotado: el procesamiento documental admite **PDF, TIFF, PNG, JPEG y WebP**. BMP queda fuera del contrato. Inspección ya no lo clasifica como `MediaType.IMAGE`, Catálogo usa una única lista compartida de extensiones procesables y Preparar páginas rechaza BMP incluso si un registro antiguo lo hubiera persistido como imagen. Los mensajes visibles enumeran el mismo conjunto. Las regresiones cubren inspección y preparación real de PNG/JPEG/WebP; PDF y TIFF conservan sus pruebas de extremo a extremo ya existentes.

No hay migración; continúa `0047_authority_relation_profiles`.

## Validaciones manuales posteriores a RC57

`PILOT-01AC` quedó cerrado: Integridad, navegación hacia la superficie de resolución, descarte reversible de avisos y filtros de Autorizaciones de análisis fueron validados sobre `pilot_data`. A continuación se creó una copia de seguridad real y la prueba no destructiva de recuperación terminó correctamente, con el proyecto activo intacto.

`PILOT-01P` también quedó cerrado mediante el recorrido real de exportar fichas de entidades/relaciones, modificar datos, simular e importar el archivo. La importación reconoció las identidades existentes en lugar de duplicarlas.

En `PILOT-01I` la extracción individual quedó validada primero; el cierre completo se registra en RC59 después de la prueba real en lote.

## RC58 - estabilidad de Procesar documentos e identidad de homónimos

La auditoría completa de **Procesar documentos** detectó que las siete pestañas todavía solicitaban un rerun global al cambiar de panel y que varios selectores dependían de rótulos documentales no necesariamente únicos. RC58 mantiene la persistencia y los contratos de OCR, pero vuelve pasiva la navegación entre pestañas y conserva la navegación programática posterior a una mutación mediante estado pendiente aplicado antes del render.

Los controles documentales pasan a usar `digital_object_id` como identidad estable. Las representaciones equivalentes del mismo objeto se deduplican y los documentos distintos que comparten título o nombre de archivo se desambiguan sólo cuando hace falta mediante ruta archivística, referencia de origen o identificador. El criterio se aplica a Preparar / extraer, OCR regional, elección de texto para revisar e incorporación masiva a revisión.

La misma auditoría corrigió un formulario que deshabilitaba el botón de envío en función de una casilla contenida dentro del propio `st.form`: la acción queda disponible y la confirmación se valida después del submit. Los expanders de la sección se mantienen informativos. `PILOT-01AD` quedó validado manualmente después de RC58 y se cierra en RC59 junto con el cierre del lote de `PILOT-01I`. Sin migración; continúa `0047_authority_relation_profiles`.







## RC57 - Integridad accionable y autorizaciones filtrables

La validación manual de RC56 cerró `PILOT-01AB`: crear copias, enviar y recibir cambios, transportar ZIP por Google Drive y resolver visualmente el recorrido normal quedaron verdes. RC57 no reabre ese subsistema.

En **Administrar y recuperar > Integridad**, los diagnósticos pasan a ofrecer navegación contextual hacia la superficie donde se resuelven. Las relaciones archivísticas conducen a **Catálogo > Productores y responsables** de la unidad afectada; los índices a sus búsquedas; las exportaciones faltantes al historial de exportación; los archivos al Catálogo y los problemas de base a recuperación. Los códigos internos, IDs, fecha de comprobación y revisión de esquema quedan en detalles técnicos. Los avisos informativos se muestran sólo al solicitarlos.

Los avisos no bloqueantes que pueden representar una situación aceptada admiten descarte reversible. La preferencia se persiste en `config/project_health_dismissals.json`, fuera de SQLite y de los eventos de intercambio, y no elimina el registro que originó el diagnóstico. Los backups la conservan como parte de `config/`. Las copias configurables para trabajo en equipo dejan además de denunciar como faltantes los grupos `originals` o `exports` que su propio manifiesto declara omitidos deliberadamente.

**Autorizaciones de análisis** agrega filtros SQL por tipo, responsable, origen y alcance, además de búsqueda y límite de resultados. No cambia la tabla append-only ni su contrato. Sin migración; continúa `0047_authority_relation_profiles`. `PILOT-01AC` queda abierto sólo hasta validar esta superficie antes de backup/prueba no destructiva de recuperación.

## RC56 - intercambio sin categoría residual y recepción por divulgación progresiva

La revisión visual posterior a RC55 confirmó que el intercambio ya era funcional pero todavía exponía como navegación una distinción técnica: Google Drive vivía bajo **Más opciones** aunque sólo cambia el medio de transporte. RC56 deja el selector principal en **Enviar cambios / Recibir cambios / Preparar una copia para trabajar en equipo**. Drive se integra como destino contextual de un ZIP creado y como fuente alternativa al abrir un ZIP recibido. Las herramientas excepcionales pasan a **Resolver un problema entre copias** y sustituyen temporalmente el recorrido normal mientras están activas.

En **Recibir cambios**, incorporar otro ZIP, archivar, eliminar definitivamente, reconstruir historial y resolver todas las diferencias de la misma manera quedan cerrados hasta que se solicitan. El archivo reversible muestra su nota opcional recién después de pulsar **Archivar paquete**; restaurar es directo; la eliminación definitiva conserva confirmación fuerte. Los conflictos se revisan de uno en uno y los diagnósticos permanecen en detalles informativos. No cambia persistencia, formato de bundle, Drive ni revisión de base. La validación manual posterior dejó esta organización verde y cerró `PILOT-01AB`.

## RC55 - jerarquía visual y feedback ordenado en Intercambiar cambios

La validación funcional de RC54 confirmó el recorrido real completo: una copia de trabajo pudo crear un paquete incremental, subirlo a Google Drive y el proyecto original pudo descargarlo, revisarlo e incorporar sus cambios. La misma prueba detectó una regresión de UX: resultados de operaciones, estado persistente de Drive y comprobaciones técnicas aparecían como avisos destacados en distintas zonas y competían visualmente.

RC55 no cambia contratos ni persistencia. **Más opciones** pasa a ser una tarea alternativa del selector principal y deja de renderizarse simultáneamente con Enviar/Recibir. En Google Drive se muestra un único recorrido activo, **Subir un ZIP** o **Recibir un ZIP**; la conexión activa se presenta como estado compacto; credenciales y reconexión sólo aparecen cuando se solicitan; SHA-256, rutas, IDs y tablas de compatibilidad quedan cerrados por defecto. Después de revisar un ZIP descargado desde Drive, la interfaz vuelve al recorrido principal de **Recibir cambios** y selecciona el paquete evaluado.

La recepción normal prioriza la decisión: muestra primero cuántos cambios están listos o requieren intervención y desplaza conteos completos, base, método e identificadores a **Detalles del paquete y la comparación**. La confirmación posterior a una aplicación omite ceros irrelevantes y comunica primero los cambios efectivamente incorporados. `PILOT-01AB` permanece abierto sólo hasta validar esta reorganización visual. Sin migración; continúa `0047_authority_relation_profiles`.

## RC54 - copias configurables y transporte unificado de ZIP

RC54 completa la simplificación del intercambio normal sin modificar la persistencia. **Preparar una copia para trabajar en equipo** incorpora perfiles Completa, Para revisión y catalogación y Personalizada; SQLite y configuración permanecen obligatorias, mientras originales, derivados, extracción, transcripciones, índices, exportaciones, evaluación y auxiliares pueden incluirse u omitirse explícitamente. `plan_team_copy()` estima tamaño y cantidad antes de escribir; el manifiesto registra perfil, grupos incluidos y omisiones deliberadas.

La recepción local y Google Drive inspeccionan el tipo de ZIP antes de decidir el recorrido. Drive transporta ahora tanto copias iniciales como paquetes incrementales y utiliza subida reanudable por bloques, además de descarga incremental y materialización atómica. La interfaz ofrece selectores de archivo donde antes se dependía de pegar rutas y mantiene la elección directa de ZIP locales conocidos para evitar recargar archivos grandes a través del navegador. `PILOT-01AB` continúa abierto hasta validación manual. No hay migración nueva; continúa `0047_authority_relation_profiles`.

## RC53 - validación segura de paquetes antes de subirlos a Google Drive

La prueba real de RC52 reveló que el panel opcional de Google Drive elegía el ZIP más reciente de `exchange/outgoing/` sin distinguir entre un paquete incremental y una copia completa para iniciar trabajo en equipo. Además, `inspect_change_bundle()` podía propagar `zipfile.BadZipFile`, que no estaba incluido en las excepciones controladas por la interfaz y terminaba en un traceback de Streamlit.

RC53 convierte `BadZipFile` en un `ValueError` de dominio, filtra la preselección de Drive mediante `inspect_change_bundle()` y explica de forma específica cuando se intenta usar una copia completa de trabajo. La operación se detiene antes de OAuth o de cualquier llamada de red cuando el archivo no es un paquete incremental válido. No cambia persistencia, contratos de intercambio ni revisión de base; continúa `0047_authority_relation_profiles`. `PILOT-01AB` permanece abierto hasta validación manual.

## RC52 - recorrido normal de intercambio sin contrapartes manuales

RC52 conserva los contratos de eventos, dry-run, aplicación, recuperación y acuerdos existentes, pero cambia el recorrido normal de colaboración. **Preparar una copia para trabajar en equipo** registra un checkpoint en la copia emisora y crea un ZIP completo con una instantánea SQLite consistente y los archivos locales del proyecto, excluyendo backups, logs y artefactos previos de intercambio. El mismo ZIP puede entregarse a varias personas. Cada extracción se reidentifica automáticamente una sola vez en su primera apertura y crea un checkpoint con la misma huella de estado, sin modificar el trabajo editable.

**Enviar cambios** usa automáticamente el último checkpoint local y `export_change_bundle()`; ya no pide seleccionar base ni declarar una contraparte. **Recibir cambios** conserva la simulación y aplicación existentes. Los acuerdos bilaterales y la adopción de estado completo siguen disponibles como recuperación avanzada, de modo que la simplificación de interfaz no elimina las garantías históricas. No hay migración nueva; continúa `0047_authority_relation_profiles`. El cierre de `PILOT-01AB` depende de la validación manual de este recorrido real.

## RC51 - creación de paquetes de intercambio y base común explicada por tarea

La validación manual cerró `PILOT-01AA`: tanto el JSONL documental 1.1 como la exportación audiovisual administrada conservaron la trazabilidad esperada, y la pasada posterior de asignación/revisión cruzada quedó verde. En `Intercambiar cambios`, RC51 conserva el modelo bilateral existente pero reemplaza el vocabulario centrado en el protocolo por **Establecer una base común para intercambiar cambios**, explicando que se registra el momento en que dos copias contienen exactamente el mismo trabajo editable. Los pasos visibles pasan a identificar qué copia actúa en cada momento.

La misma sección incorpora **Crear un paquete con mis cambios**. El recorrido elige un checkpoint existente, calcula los cambios posteriores y llama a `export_change_bundle()` sin introducir una ruta paralela de persistencia. El ZIP queda en `exchange/outgoing/`, se registra con su SHA-256, crea el checkpoint posterior previsto por el dominio y sólo después ofrece descarga. Si no hay un punto de partida registrado, la interfaz no fabrica uno silenciosamente: explica que primero debe establecerse la base común. Google Drive enlaza explícitamente con esta creación. No hay migración nueva y continúa `0047_authority_relation_profiles`.

## RC44 - Búsqueda textual como herramienta de exploración

RC44 conserva la búsqueda literal y sus filtros, pero amplía el trabajo posterior con los resultados. `Tarjetas` sigue siendo la vista principal; `Concordancias` usa el campo completo donde se produjo la coincidencia y genera una fila por aparición con contexto a izquierda y derecha. `Distribución de los resultados` permanece cerrada por defecto y resume los bloques mostrados por documento, lugar de coincidencia y parte interna. Al abrir una tarjeta en `Revisar documentos`, la aplicación conserva el conjunto ordenado y ofrece `Resultado anterior`, `Resultado siguiente` y `Volver a los resultados de Búsqueda textual`; los parámetros enviados quedan fuera de los widgets en `review_search_params` para reconstruir el mismo formulario y el mismo conjunto al regresar. `PILOT-01X` quedó validado manualmente en la prueba posterior y pasa a cierre. No hay migración nueva; continúa `0047_authority_relation_profiles`.

## RC43 - jerarquía visual del ciclo de vida de transcripciones

RC43 conserva la lógica reversible de descarte/restauración introducida en RC41, pero corrige su ubicación en la interfaz. Retira `Opciones de esta transcripción`: la escucha, corrección, anotación y evaluación de la versión activa se presentan primero; sólo después aparecen, cerrados por defecto, `Descartar esta versión de la transcripción` y `Transcripciones descartadas (n)`. La regla permanente queda incorporada a `.assistant/05_CRITERIOS_INTERFAZ.md`: las acciones excepcionales o destructivas no se agrupan bajo contenedores genéricos ni compiten con el recorrido normal. `PILOT-01V` sigue pendiente de validación manual. No hay migración nueva; continúa `0047_authority_relation_profiles`.

## RC42 - paneles complejos inline en Búsqueda textual y Explorar relaciones

La validación manual de RC41 confirmó que ampliar el cuerpo de `st.popover` mediante CSS sobre su DOM interno no modificó el ancho real de `Más filtros`, y mostró la misma compresión en `Configurar mapa`. RC42 elimina ese parche CSS y reemplaza ambos popovers complejos por `st.expander` cerrados por defecto y de ancho completo. El contenido, los formularios y los filtros se conservan; cambia únicamente el contenedor visual para usar una superficie estable de Streamlit en lugar de depender de la capa flotante del popover. `PILOT-01U` sigue pendiente de validación manual. No hay migración nueva; continúa `0047_authority_relation_profiles`.

## RC41 - primera pasada de Búsqueda textual y correcciones transversales

La validación manual de RC40 cerró `PILOT-01T`: desde Menciones, el bbox seleccionado cambia el bloque correspondiente dentro del fragmento local y conserva documento/página. El piloto avanza a Búsqueda textual. RC41 implementa tres hallazgos nuevos todavía pendientes de validación manual: amplía el cuerpo de `Más filtros` sin agrandar su botón; agrega descarte/restauración reversible de transcripciones completadas, excluyéndolas de búsqueda/exportación mientras están descartadas; y agrega `Familia` al mapa de etiquetas del grafo para eliminar el `KeyError` introducido al ampliar `AUTHORITY_TYPES` en RC31. No hay migración nueva; continúa `0047_authority_relation_profiles`.

## RC40 - `PILOT-01T`: selección de bloque con rerun local de fragmento

RC39 eliminó el reinicio global al hacer clic en un bbox, pero la validación manual mostró una regresión: el bloque activo del panel dejó de seguir la selección visual. RC40 recupera la sincronización semántica ya validada históricamente y cambia únicamente su alcance reactivo. `clickable_review_canvas(..., commit_on_click=True)` vuelve a comunicar el `object_id`, el callback actualiza el selector antes del rerun y la región imagen + selector + panel se ejecuta como `st.fragment`. Por lo tanto el bloque activo cambia inmediatamente sin reconstruir documento, página ni la navegación general. Zoom y scroll permanecen en el navegador. La validación manual posterior confirmó el comportamiento completo y cerró `PILOT-01T`. No hay migración nueva.

## RC39 - `PILOT-01T`: restauración literal del invariante local del bbox

La validación manual de RC38 confirmó que los intentos RC34-RC38 atacaban el lugar equivocado. El recorrido seguía ejecutando `clickable_review_canvas(..., commit_on_click=True)`, por lo que **cada clic sobre un bbox llamaba `setTriggerValue()` y provocaba un rerun completo**. Eso contradice de forma directa el invariante canónico validado en RC7/RC8, que exige mantener la selección visual provisional dentro del navegador y comunicar a Python sólo una confirmación semántica explícita. RC39 elimina el trigger automático del clic, conserva localmente el marco rojo, el zoom y el desplazamiento, y sincroniza el bloque activo únicamente al pulsar `Usar el texto seleccionado`. Se retiran además las capas de navegación generacional introducidas por los intentos fallidos y se restaura el guardia simple y estable de documento/página. `PILOT-01T` permanece abierto hasta validación manual real. No hay migración nueva.

## RC38 - identidad generacional para navegación programática en Revisar documentos

RC38 fue el quinto intento insuficiente de `PILOT-01T`. Su diagnóstico de identidad generacional quedó descartado por la validación manual de RC39: el rerun seguía originándose en el propio clic del bbox porque `commit_on_click=True` permanecía activo. El destino programático vive en `review_context_source_key` y `review_context_page_number`, mientras cada navegación programática incrementa `review_navigation_generation` y monta los selectores con claves nuevas `review_source_key__<generación>` y `review_page_number__<generación>`. Los reruns por bbox conservan la generación; sólo una nueva navegación programática cambia la identidad de esos widgets. Los accesos desde Menciones vuelven al flujo explícito `request_app_view(...)` + `rerun_app(st)` y `review_canvas.py` permanece sin cambios. RC38 retira además la dependencia errónea de RC37 sobre `persist_state="session"`, que no pertenece al mínimo Streamlit 1.55 soportado. `PILOT-01T` continúa abierto hasta validación manual real. No hay migración nueva.

## RC37 - intento insuficiente con `persist_state`

RC37 fue el cuarto intento insuficiente de `PILOT-01T`: la validación manual real confirmó que documento/página seguían cambiando después de seleccionar un bbox. Además, el diagnóstico posterior corrigió una premisa técnica de esa candidata: `persist_state="session"` no estaba disponible en el mínimo Streamlit 1.55 soportado por Archive Workbench. RC38 retira esa dependencia. `review_canvas.py` no había sido modificado. No hubo migración nueva.

## RC36 - separación estricta entre contexto durable y widgets de revisión

RC36 corrige el diseño insuficiente de RC35 para `PILOT-01T`. Documento y página dejan de usar como fuente de verdad cualquier clave asociada a un widget. El contexto persistente en la sesión vive en `review_context_source_key` y `review_context_page_number`; los selectores usan claves temporales `_review_source_key` y `_review_page_number`, cargadas antes de instanciarse y sincronizadas hacia el contexto mediante callbacks. La navegación desde Menciones también se ejecuta por callback y elimina el rerun explícito posterior. `review_canvas.py` permanece sin cambios. El punto sigue abierto hasta validación manual. No hay migración nueva.

## RC35 - continuidad durable de navegación en Revisar documentos

RC35 corrige la única regresión que permaneció abierta tras la validación manual de RC34. El problema no estaba en el canvas: `review_source_key` y `review_page_number` eran claves de widgets que desaparecen al navegar a `Entidades y menciones`, por lo que Streamlit podía limpiarlas. RC35 conserva documento y página también en claves durables no asociadas a widgets y las restaura antes de montar los selectores. La navegación programática desde una mención y los cambios manuales de documento/página actualizan la misma fuente durable. El canvas conserva su callback previo al rerun y no se agregan reruns compensatorios. `PILOT-01T` sigue abierto sólo hasta validación manual. No hay migración nueva; continúa `0047_authority_relation_profiles`.

## PILOT-01Q/R/S - validaciones manuales cerradas en RC34

La validación manual de RC34 confirmó como correctos el árbol tipo explorador de `Catálogo > Unidades del catálogo` (`PILOT-01Q`), la eliminación confirmada y auditable de vínculos de producción/gestión creados por error (`PILOT-01R`) y los límites explícitos amplios de todos los calendarios (`PILOT-01S`). Estos tres puntos quedan cerrados y no deben repetirse salvo regresión material nueva.

## RC34 - árbol tipo explorador, vínculos erróneos, calendarios y continuidad de revisión

RC34 reemplaza el pseudoárbol de RC33 por un componente jerárquico tipo explorador: abrir/cerrar ramas queda en `sessionStorage` y no produce reruns; sólo la selección de una unidad llega a Python. Agrega eliminación confirmada y auditable de roles `producer`/`manager` creados por error, sin borrar la autoridad ni sus revisiones. Todos los `date_input` declaran límites explícitos para evitar la ventana implícita de +/-10 años. Finalmente, `Revisar documentos` restaura el guardia histórico `review_page_source` de RC20/RC7-RC8 y elimina el `on_change` de RC31 que podía reinterpretar un rerun por bbox como cambio de documento. Los cuatro cambios quedan pendientes de validación manual como `PILOT-01Q/R/S/T`. No hay migración nueva; continúa `0047_authority_relation_profiles`.

## RC33 - plantillas descriptivas bidireccionales y árbol del catálogo

RC33 implementa dos ampliaciones surgidas de la validación manual de `PILOT-01`. Primero, el contrato JSON de autoridades pasa a 1.1 sin romper la lectura de 1.0 y puede exportar las fichas actuales de entidades y relaciones analíticas entre entidades con identificadores estables. Al reimportar una plantilla exportada, la simulación distingue `update` de creación/reutilización y la aplicación transaccional actualiza los campos descriptivos del mismo registro. Se preserva la regla de no borrar alias por ausencia en un archivo externo.

Segundo, `Catálogo > Unidades del catálogo` deja de depender de un selector lineal: la estructura se navega como árbol desplegable, con padres visibles y selección directa. Una búsqueda conserva los antecesores de los resultados para mostrar contexto. La elección de nueva unidad padre al mover una unidad usa el mismo árbol y excluye la propia unidad y sus descendientes de los destinos posibles. No hay migración nueva; continúa `0047_authority_relation_profiles`. Ambos cambios quedan pendientes de validación manual como `PILOT-01P` y `PILOT-01Q`.

## RC32 - corrección focal del intercambio sobre RC31

RC32 no cambia el modelo archivístico ni la interfaz incorporados en RC31. Corrige cuatro regresiones detectadas por el gate local: recompone directorios faltantes durante `exchange-fork-copy` sin debilitar la protección general de `init-project`; hace que la huella de estado de intercambio tolere esquemas históricos anteriores a `0047` sin consultar `profile_json` inexistente; conserva el transporte real de perfiles cuando la columna sí existe; y actualiza la expectativa de campos revisables para incluir `profile_json`. No hay migración nueva.

## PILOT-01 - relación analítica básica - validada manualmente después de RC30

La validación manual posterior a RC30 confirmó la creación, persistencia y lectura de una relación analítica real dentro del recorrido del piloto. Esa prueba básica queda cerrada y no debe repetirse como condición de entrada a RC31. RC31 amplía la superficie con perfiles estructurados, clasificación archivística opcional, temporalidad discontinua y fichas desplegables; sólo esas ampliaciones requieren revalidación focal antes de continuar en **Búsqueda textual**.

## UX-04 - economía visual y arquitectura de información transversal - validado y cerrado en RC29

La validación manual acumulada de RC22-RC29 confirmó como mejora material el rediseño transversal de la interfaz. `Entidades y menciones` funcionó como prototipo y los criterios aprobados se extendieron después al resto de las secciones, con una segunda pasada específica sobre `Procesar documentos` y `Revisar documentos > Orden y estructura`.

Quedan validados como criterios permanentes: shell con `Archive Workbench` en el sidebar y un único título grande de sección; reducción de explicaciones permanentes, paneles, métricas e identificadores técnicos; búsqueda y refinamientos integrados cuando forman una sola tarea; una sola capa de navegación contextual visible; objeto o tarea activa con jerarquía visual; recorridos alternativos mutuamente excluyentes mostrados de uno en uno; y conservación explícita de advertencias materiales aunque se reduzca texto accesorio.

La orientación se resuelve sin volver a densificar la pantalla: toda sección, pestaña y tarea principal conserva una explicación explícita de para qué sirve y cómo funciona, accesible mediante un icono de información visible. RC29 cerró los dos últimos defectos detectados manualmente: el tooltip usa una superficie opaca basada en los tokens vigentes del tema de Streamlit y el foco residual de un clic con mouse no deja la ayuda persistente, mientras el foco visible de teclado sigue siendo accesible y `Escape` la cierra. Las reglas resultantes son canónicas en `.assistant/05_CRITERIOS_INTERFAZ.md` y la checklist obliga a releerlas antes de cualquier modificación futura.

La validación manual del 2026-08-21 dio por terminado el rodeo. `UX-04` queda **cerrado** y sale de `PENDIENTES_ACTIVOS.md`. `UX-02` permanece reservado para la revisión integral final de remanentes antes de v1.0. El recorrido activo de `PILOT-01` volvió a **Relaciones**; la relación analítica básica quedó validada después de RC30 y RC31 sólo revalida sus ampliaciones antes de continuar en Búsqueda textual.

## GRAPH-03 - capas estructurales desactivadas por defecto - validado manualmente en RC22

RC22 cambió únicamente la selección inicial del grafo: `Jerarquía archivística` (`hierarchy`) y `Documentos en unidades` (`document`) quedan desactivadas por defecto en `Explorar relaciones`, pero siguen disponibles para activación explícita y conservan el mismo contenido y trazabilidad. La validación manual del 2026-08-20 confirmó expresamente que el comportamiento de `Explorar relaciones` quedó correcto. `GRAPH-03` se cierra y sale de `PENDIENTES_ACTIVOS.md`.

## PILOT-01 - Entidades y menciones y cierre de regresiones RC20 - validado manualmente

La validación manual de RC19-RC20 cierra `PILOT-01O` y deja validada la etapa de **Entidades y menciones** del recorrido actual de `PILOT-01`. No debe repetirse salvo regresión material nueva.

- En `Revisar documentos`, varios clics consecutivos sobre bboxes mueven el marco rojo y la selección visual dentro del navegador sin reconstruir la vista; al confirmar `Usar el texto seleccionado`, el selector textual y el panel de revisión quedan sincronizados con ese bloque.
- Los roles archivísticos de **productor** y **responsable de gestión** creados desde Catálogo son visibles desde la ficha de la entidad como información de solo lectura. Catálogo continúa siendo la única interfaz de escritura de esos vínculos.
- La revisión de referencias encontradas se reduce a **Aceptar** o **Descartar**. Aceptar permite corregir antes el texto o la clasificación y luego crea o vincula el registro correspondiente; descartar saca la referencia de pendientes sin borrar el historial.
- `Referencias descartadas` es una pestaña independiente y permite restaurar una referencia mediante una nueva decisión append-only.
- `Trabajar con varias referencias` usa un `st.form`: seleccionar varias referencias y marcar la confirmación no provoca reruns antes del envío. La acción masiva crea una entidad nueva con estado `Sin revisar` **por cada referencia seleccionada**, sin agrupar referencias por tipo; el descarte masivo conserva la misma trazabilidad.
- `Duplicados y cambios de texto` presenta las tareas como `Revisar posibles referencias repetidas` y `Actualizar referencias después de corregir el texto`, con explicaciones orientadas a la tarea.
- La validación manual confirmó también que el resto de los cambios de RC19 funciona correctamente. El afinado de calidad del detector no se mezcla con este cierre y permanece abierto como `DISC-03`, pre-release.

La relación analítica básica quedó validada después de RC30. Tras la revalidación focal de las ampliaciones de RC31, el recorrido continúa en **Búsqueda textual**, búsqueda semántica, grafo y exportación.

## PILOT-01 - cierres manuales de procesamiento, lectura localizada y continuidad Streamlit - RC18

La validación manual acumulada de RC15-RC18 cierra tres pendientes subsidiarios que ya cumplieron sus criterios y salen de `PENDIENTES_ACTIVOS.md`:

- **`PILOT-01H` - lectura localizada / OCR regional para uso sin guía.** El recorrido quedó separado de la elección de extracciones completas y permite corregir texto existente o agregar texto faltante con ubicación gráfica explícita y procedencia conservada. La prueba manual confirmó que el recorrido se comprende y funciona. La posible mejora sobre texto parcialmente cubierto por firmas queda separada como `PILOT-01N`, post-release, para no mantener abierto un flujo funcional ya validado.
- **`PILOT-01K` - secuencia de preparación, extracción y envío a revisión.** La interfaz distingue `1. Preparar imágenes para extraer texto` de `2. Extraer texto de las imágenes preparadas`, impide iniciar extracción sobre documentos sin preparación vigente y separa el envío de páginas a `Revisar documentos`. La prueba manual confirmó tanto el recorrido como el envío masivo por un documento y por varios documentos.
- **`PILOT-01M` - continuidad transversal de interacción Streamlit.** Tras descartar RC16 y volver en RC17 al patrón RC7/RC8, la validación manual de RC18 confirmó que seleccionar varias cajas y dibujar/repetir rectángulos no reconstruye la vista, y que las confirmaciones conservan documento, página, contexto y posición. La única fuente de verdad de esta arquitectura sigue siendo el [invariante canónico de interacción Streamlit](../referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md#streamlit-interaction-invariant).

Estos cierres no deben reabrirse sin evidencia material nueva.

## Gobernanza de cambios - checklist obligatoria - RC18

RC18 incorpora `.assistant/00_CHECKLIST_CAMBIOS.md` como protocolo transversal para cualquier modificación del proyecto. La obligación de completarla queda establecida en `.assistant/00_LEER_PRIMERO.md`. La checklist no replica las políticas: obliga a consultar sus documentos canónicos y enlaza de manera explícita el invariante Streamlit, la política documental, la política de pruebas, los criterios de interfaz, la seguridad de archivos y las reglas de continuidad antes de modificar y antes de entregar una candidata.

## PILOT-01 - interacción Streamlit y única fuente de alta de texto - RC17

RC17 parte de **RC15** y descarta por completo RC16. La regresión de RC16 confirmó que envolver regiones operativas con nuevos fragmentos no es una estrategia válida de continuidad para Archive Workbench. La solución vuelve al patrón validado en RC7/RC8 y queda desarrollada una sola vez en el [invariante canónico de interacción Streamlit](../referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md#streamlit-interaction-invariant).

Los componentes visuales de procesamiento mantienen en el navegador la selección provisional de cajas, el zoom, el desplazamiento interno y los rectángulos dibujados. Esas acciones pueden repetirse sin comunicar nada a Python. El backend recibe únicamente confirmaciones discretas como `Usar el texto seleccionado` o `Usar esta ubicación`; el componente pasivo de continuidad vertical vuelve a la implementación estabilizada en RC8 y no emite estado ni triggers. La abstracción `fragmented_view` se elimina del código para impedir que vuelva a convertirse en una solución general de reruns.

La validación manual previa a RC17 cerró además `PILOT-01G`: el envío de muchas páginas de un documento y de varios documentos a `Revisar documentos` funcionó con identidad por objeto digital, sin repetir el `StreamlitDuplicateElementKey`. También cerró `PILOT-01J`: las pestañas de `Revisar documentos`, su orientación y su orden se entendieron y funcionaron en la prueba real.

`Agregar un bloque de texto` deja de existir en `Revisar documentos`. La única interfaz para incorporar texto faltante queda en `Procesar documentos > Corregir o agregar`, donde la ubicación debe definirse sobre la imagen. Una página sin objetos en `Revisar documentos` remite explícitamente a esa tarea en vez de ofrecer una segunda vía de alta.


## PILOT-01 - separación de tareas de procesamiento, continuidad y lote multdocumento - RC15

RC15 implementa las correcciones surgidas de la validación manual de RC14 sin declarar cerrados los pendientes de usabilidad. `Procesar documentos` separa la elección de extracciones completas, la incorporación de texto recuperado al volver a leer una parte concreta de una página y el envío de muchas páginas a `Revisar documentos`; las lecturas parciales ya no se mezclan con las extracciones completas elegibles para toda la página. La incorporación parcial permite corregir texto existente mediante selección visual o agregar texto faltante después de dibujar explícitamente su ubicación sobre la página; la geometría original de la lectura parcial queda preservada como procedencia.

La operación masiva sobre varios documentos deja de construir claves de widgets con `source_key`: deduplica por objeto digital y usa `digital_object_id` para la identidad de controles y operaciones, corrigiendo el `StreamlitDuplicateElementKey` reproducido en `pilot_data`. La misma identidad se propaga a comparación, selección, adopción y traslado de edición para no depender de que `source_key` sea globalmente único.

La estrategia de continuidad introducida en RC15 mediante ancla lógica no se considera arquitectura vigente: la validación manual mostró que los clics visuales seguían provocando reruns y saltos. RC17 la reemplaza por el patrón RC7/RC8 documentado en la fuente canónica de arquitectura.

El historial de trabajos antiguos traduce la causa persistida de extracción sin preparación a un mensaje comprensible, sin repetir la tarea de 138 documentos. La interfaz de preparación declara el soporte de PDF, TIFF, PNG, JPEG y WebP. RC59 cierra `PILOT-01L`: BMP queda explícitamente fuera del contrato de procesamiento documental. Estas implementaciones permanecen sujetas a validación manual sobre el mismo `pilot_data`; `Revisar documentos` todavía no se revalidó en esta ronda.

Antes del empaquetado se repitieron las cinco pasadas semánticas de interfaz exigidas por `.assistant`, incluyendo vistas distintas de procesamiento. Se retiraron restos de `texto inicial` y orientaciones antiguas en Inicio/Revisar documentos, se corrigió una frase truncada en `Orden y estructura` y se hicieron explícitos referentes de estados/resultados cuando podían quedar implícitos. Los 152 tests focalizados relevantes quedaron verdes y la recopilación completa registra 583 tests en 53 archivos.

## Actualización de candidatas con reubicaciones verificadas - RC14

La instalación de RC13 sobre RC12 reveló que `cp -a` por superposición no retira rutas distribuidas por una candidata anterior. El ZIP de RC13 ya ubicaba correctamente las auditorías RC11/RC12 en `docs/historico/actualizaciones/`, pero las copias antiguas podían permanecer en `docs/operativos/` y hacer fallar la política documental. RC14 incorpora un actualizador con manifiesto explícito de cinco reubicaciones conocidas. Antes de copiar comprueba que cualquier ruta antigua presente tenga exactamente la huella de la copia histórica distribuida; después de copiar verifica el destino canónico y recién entonces retira la duplicación antigua. Si el contenido local difiere, aborta antes de modificar el repositorio. La regresión simula una instalación sobre un árbol con residuos RC12 y comprueba además que contenido local ajeno al paquete se conserve.

Este documento registra capacidades ya implementadas y, cuando corresponde, validadas. No deben volver a aparecer en `PENDIENTES_ACTIVOS.md` salvo evidencia de regresión o ampliación explícita del alcance.

## PILOT-01 - RC12 - reescritura transversal de interfaz y auditoría semántica

RC12 corrige la metodología insuficiente de la auditoría de RC11. La revisión anterior evitaba varios rótulos genéricos, pero todavía podía aprobar frases cuyo referente sólo se deducía por contexto. RC12 aplica la prueba de lectura aislada a títulos, controles, ayudas, estados, resultados, historiales y bloques técnicos de todas las vistas operativas y de los componentes auxiliares que renderizan interfaz. Se reescriben, entre otros, Inicio, Catálogo, Procesar documentos, Revisar documentos, búsqueda textual y semántica, entidades y menciones, relaciones, exportación, intercambio, administración, audiovisual y organización de trabajo. Los casos detectados manualmente `una parte del trabajo`, `qué significa cada columna` y el botón genérico `Abrir` quedan reemplazados por frases que nombran explícitamente la etapa, el dato del catálogo y la sección de destino. La implementación queda sujeta a validación manual de `PILOT-01E` y `PILOT-01J`; esta entrada registra el cambio realizado, no declara cerrada la usabilidad.

## PILOT-01 - preparación robusta de TIFF grandes con pyvips - validado en RC10

`PILOT-01F` queda cerrado por validación manual sobre el `pilot_data` persistente. Después de instalar RC10 se reintentaron únicamente `leg_15_a_c_2.tiff` y `leg_15_a_c_6.tiff`; ambos completaron `Preparar páginas` sin reproducir `tiff2vips: out of order read`, conservaron los originales y generaron los derivados esperados. La extracción posterior sobre la muestra completa de cinco documentos terminó 5/5, con 0 advertencias y 0 fallos, usando efectivamente `surya_cli`, sin fallback automático y sin selección automática de páginas. Esto confirma en los TIFF reales el invariante de reabrir una lectura secuencial independiente para cada salida.

## PILOT-01 - onboarding, catálogo e incorporación inicial - 0.89.0

**Corrección RC4.** La preparación de la prueba audiovisual mostró tres carencias de Catálogo: no se podía corregir el tipo de una unidad ya creada, no existía una acción segura para eliminar una unidad y los proyectos no ofrecían Colección como nivel estándar. RC4 agrega Colección bajo Archivo, permite habilitarla explícitamente en proyectos anteriores, permite cambiar el tipo de una unidad sólo cuando la ubicación, los hijos y los campos siguen siendo compatibles, y permite eliminar únicamente unidades sin dependencias mediante confirmación explícita. Las plantillas XLSX antiguas siguen siendo válidas cuando omiten un nivel agregado posteriormente al proyecto.

**Corrección RC3.** Después de incorporar 138 originales reales, la prueba detectó cinco regresiones de interfaz y una necesidad de escalabilidad: Inicio exponía `generación 0/5` y la revisión de base; las paletas tenían poco contraste y controles oscuros; `Unidades del catálogo` quedaba fuera de las pestañas principales; las pestañas internas provocaban un rerun inmediato con salto de scroll; algunos campos de carpetas seguían sin selector; y corregir excepciones a una regla de carpeta exigía recorrer manualmente la tabla completa. RC3 corrige esos puntos sin tocar persistencia documental ni procesamiento.

**Corrección RC2.** La primera prueba de RC1 detectó que crear un proyecto exigía escribir la ruta de destino sin selector, que las paletas sólo afectaban el acento visual y que `Guardar preferencias` podía lanzar `StreamlitAPIException` al reescribir `review_actor` después de instanciar el widget. RC2 usa un selector de carpeta del sistema con alternativa manual, separa carpeta contenedora y nombre de la carpeta nueva, aplica temas completos y persiste nombre/paleta sin modificar claves de widgets ya instanciados.

La primera prueba manual desde un proyecto vacío mostró que el recorrido de inicio dependía de `init-project`, edición manual de `decisions.yaml` y `db-upgrade`; además, Catálogo mezclaba expanders reactivos, copy técnico, rutas hardcodeadas, carga individual poco escalable y un bug en el movimiento de unidades. 0.89.0 introduce un launcher gráfico, preferencias locales, navegación y guía revisadas, planillas con ejemplos, configuración gráfica de la jerarquía, creación de productores/gestores desde la unidad, selección de archivos existentes, rangos de páginas sugeridos, estados en español y un flujo de incorporación por lote. La validación manual de esta fase de `PILOT-01` quedó completada sobre el proyecto persistente; el mismo `pilot_data` continúa ahora en procesamiento y OCR sin reiniciar las fases ya aprobadas.

## PILOT-01 - continuidad de interfaz, audiovisual y temas - validado en RC9

Las subtareas `PILOT-01B`, `PILOT-01C` y `PILOT-01D` quedan cerradas después de la validación manual acumulada de RC7-RC9. La continuidad frente a reruns conserva el segmento activo y el punto del reproductor al guardar una transcripción; salir y volver a la vista audiovisual ya no dejó los estados incoherentes reproducidos durante RC6. La configuración de transcripción expone y registra `large-v3`, dispositivo, `compute_type`, idioma, vocabulario esperado, `beam_size` y VAD; la corrida controlada con los hotwords históricos volvió a 78 segmentos y reprodujo casi por completo la salida histórica. La asignación de hablante distingue alcance puntual y continuidad hasta la próxima marca; menciones y métricas quedaron reorganizadas y RAM/GPU usan la misma jerarquía visual.

Las paletas personalizadas dejaron de intentar retematizar widgets mediante CSS inyectado y pasan por el sistema nativo de temas de Streamlit al iniciar la aplicación; `Sistema` conserva el comportamiento nativo y las fechas descriptivas permiten un rango histórico explícito. La validación posterior no reprodujo los defectos visuales que habían motivado `PILOT-01D`. Estas capacidades no deben volver a `PENDIENTES_ACTIVOS.md` salvo regresión concreta.


## PILOT-01 — padres existentes omitidos en plantillas de catálogo — 0.88.2

Durante la ampliación del catálogo APM Chubut, una plantilla válida de 16 filas falló en aplicación porque dos actualizaciones dependían por `parent_local_id` de unidades existentes marcadas `omitir`. La aplicación excluía esas filas del mapa jerárquico aunque la validación las aceptaba. 0.88.2 conserva como referencias de jerarquía todas las filas con `unit_id`, incluso si se omiten, sin modificarlas. La corrección no cambia persistencia ni interfaz. **Validación manual cerrada:** la misma plantilla real se reintentó sobre `pilot_data` y terminó con 7 unidades creadas, 3 actualizadas, 6 omitidas y 0 errores; el catálogo quedó en `archival_units: 16` y `digital_objects: 0`.

## PILOT-01 — corrección de primera importación en proyecto nuevo — 0.88.1

Durante el inicio real de `PILOT-01`, una plantilla APM Chubut con 9 filas fue validada correctamente sobre `pilot_data`, pero la aplicación falló en la primera unidad con `FOREIGN KEY constraint failed` porque la base recién inicializada tenía `projects: 0`. La transacción se revirtió por completo. 0.88.1 hace que `apply_catalog_template()` garantice la fila del proyecto sólo después de una validación válida y dentro de la transacción de aplicación. La simulación permanece no destructiva. Se agregó una regresión específica para una base nueva sin fila `Project`. **Validación manual cerrada:** después de instalar 0.88.1 se reintentó la misma plantilla; la simulación volvió a informar 9 creaciones y 0 errores, y la aplicación creó las 9 unidades con `projects: 1`, `archival_units: 9` y `digital_objects: 0`. `PILOT-01` continúa abierto con el catálogo APM Chubut ya iniciado desde cero.


## Índice de capacidades implementadas

| Área | Estado actual |
|---|---|
| Catálogo, originales y estructura archivística | Implementado |
| Extracciones versionadas y selección canónica | Implementado y validado |
| Revisión, historial y rebase | Implementado y validado |
| Calidad de página y derivados OCR | OCR-01A–F implementadas, validadas y cerradas |
| Búsqueda literal y semántica | Implementado; calibración reproducible cerrada en 0.74.0 |
| Autoridades, menciones y relaciones | Núcleo implementado y validado |
| Exportaciones reproducibles | CSV/JSONL y texto+imágenes ZIP implementados, validados; EXP-01 cerrado en 0.88.0 |
| Backups y restauración | Implementado y validado |
| Intercambio offline | Implementado y validado; EX-01 cerrado en 0.68.1 |
| Transporte opcional por Google Drive INT-01 | Implementado, validado y cerrado en 0.87.0 |
| Política de formularios explícitos | Implementada y validada |
| Simplificación general de interfaz y léxico | Implementada y validada en 0.56.0 |
| Reparación auditable de menciones históricas | Implementada y validada en 0.62.1 |
| Política auditable de análisis automáticos | Implementada y validada en 0.64.1 |
| Organización documental | Implementada en 0.50.0 |
| Descubrimiento abierto DISC-01A–D | Implementado y validado en 0.73.0 |
| Reformulación UX-03 de Entidades y descubrimiento | Implementada y validada en 0.72.0 |
| Calibración semántica SEM-01 | Implementada y validada en 0.74.0 |
| Grafo sin colisiones GRAPH-01 | Implementado y validado en 0.74.0 |
| Duplicados OCR-02 | Cerrado por decisión de alcance en 0.74.0 |
| Plantillas distribuibles CAT-01 | Implementadas y validadas en 0.75.1 |
| Diccionarios de autoridades DISC-02 | Implementados y validados en 0.76.0 |
| Productores y gestores CAT-02 | Implementados y validados en 0.77.0 |
| Capas archivísticas GRAPH-02 | Implementadas y validadas en 0.77.0 |
| Registro audiovisual y transcripción segmentada AV-01 | Implementado, validado y cerrado en 0.84.0 |
| Incorporación autorizada desde plataformas AV-02 | Implementada, validada y cerrada en 0.85.0 |
| Evaluación y revisión audiovisual AV-03 | Implementada, validada y cerrada en 0.86.0 |

## Exportación de texto e imágenes

### EXP-01 — paquete visual con contexto estructurado — 0.88.0

**Exportar corpus > Crear archivo** agrega la opción visible **Exportar texto e imágenes (ZIP)** sin crear un segundo sistema de exportación. El perfil continúa definiendo el contenido textual principal; la ejecución puede materializar además la imagen exacta de cada página vinculada a `EditablePage.source_extraction_page_id`, recortes regionales registrados y figuras recortadas desde la geometría editable vigente. Cada recurso conserva documento, página, extracción de origen, revisión, geometría cuando corresponde, tamaño y SHA-256.

El ZIP incluye `manifest.json` y contexto textual estructurado en `context/objects.jsonl`, `context/pages.jsonl` y `context/documents.jsonl`. Los objetos que no pertenecen al perfil principal pueden viajar únicamente como contexto y quedan marcados como tales, preservando identidad y orden. Esto permite que una etapa futura `vision_describe` decida cuánto contexto consumir sin volver a consultar SQLite ni acceder de forma opaca a los originales. Si falta un recurso requerido o una huella no coincide, la exportación falla en vez de producir un paquete aparentemente válido.

La interfaz mantiene una sola elección principal de salida. **Elegir qué imágenes incluir** permanece cerrado por defecto y, al activarse, permite decidir páginas completas, recortes regionales y figuras. La exportación no ejecuta modelos ni transforma resultados automáticos en datos revisados. No hay migración: continúa `0046_audiovisual_timeline_annotations`.

**Validada manualmente en 0.88.0.** El proyecto descartable produjo 1 registro principal, 1 página, 1 recorte regional, 1 figura y 2 objetos textuales de contexto. El verificador confirmó `quick_check: ok`, cero violaciones FK, SHA-256 del original y de la página fuente idénticos (`25d1d8b6b483ec915e547648708be185e6f9a193ef88615aff71b3a8f663f41c`), huellas internas válidas, separación correcta del objeto contextual y ausencia de modificaciones en las imágenes fuente. `project_data` permaneció en `0046` y fuera del recorrido. `EXP-01` queda cerrado.

## Transporte opcional por Google Drive

### INT-01 — Google Drive como transporte controlado — 0.87.0

Archive Workbench agrega Google Drive como capa opcional de transporte sobre los paquetes ZIP del intercambio existente. La aplicación usa OAuth de escritorio con PKCE y solicita únicamente `drive.file`; Google Picker permite elegir un archivo concreto. La subida valida primero el bundle local y conserva como propiedades remotas su SHA-256, `bundle_id` y `project_id`. La descarga se escribe de forma atómica en `exchange/drive_downloads/`, vuelve a validar el ZIP y compara el manifiesto con el proyecto, la identidad de la copia, la revisión de base, la base común y las secuencias locales antes de habilitar el dry-run existente.

Drive no se convierte en fuente de verdad ni en base compartida: cada copia conserva su SQLite local, esta función no sube ni descarga `project_data` u otra SQLite y una descarga jamás aplica cambios automáticamente. Las credenciales y tokens OAuth permanecen fuera del proyecto y del repositorio bajo la configuración local del usuario. `INT-01` no agrega migraciones; la revisión sigue siendo `0046_audiovisual_timeline_annotations`.

**Validada manualmente en 0.87.0.** RC1 reveló que el generador descartable omitía `config/decisions.yaml`; RC2 corrigió esa preparación sin cambiar el transporte. La prueba real de RC2 confirmó conexión OAuth, subida, selección mediante Google Picker, descarga y SHA-256 idéntico (`9386824cb404cbba46b57152040ac1c0bbf74086d4729b7cda682c0957997beb`). El verificador registró `quick_check: ok`, cero violaciones FK, ninguna descarga inválida, otra identidad de copia, base común `matched` por `exact_checkpoint` y dry-run `empty` con A 0 / D 0 / R 0 / C 0. `project_data` quedó fuera del recorrido y sin cambios. `INT-01` queda cerrado.

## Registro audiovisual y transcripción segmentada

### AV-01 — audio/video local, segmentos y corrección — 0.84.0

Archive Workbench reutiliza `DigitalObject`, `FileInstance` y `SourceRegistration` para la identidad del original audiovisual y agrega una capa temporal propia mediante `AudiovisualMedia`, derivados trazables, corridas de transcripción, segmentos, revisiones append-only y menciones vinculadas a autoridades existentes. La migración aditiva `0045_audiovisual_transcription` no transforma las tablas OCR ni representa segundos como páginas.

FFprobe registra formato, códecs, canales, frecuencia, resolución y duración; FFmpeg genera solamente derivados técnicos cuando son necesarios. La vista **Transcribir audio y video** integra reproducción, **Velocidad de reproducción**, **Ir al inicio del segmento**, corrección revisada persistente y paneles secundarios cerrados por defecto. El backend es intercambiable y el recorrido local inicial usa `faster-whisper`, con CPU `int8` funcional.

Los segmentos participan en búsqueda literal, navegación directa desde resultados, exportación CSV/JSONL y menciones de entidades. El intercambio adopta contrato audiovisual 1.1 únicamente cuando existe contenido AV, preservando la huella histórica de proyectos sin audio/video. El inventario OCR excluye explícitamente medios audiovisuales.

**Validada manualmente en 0.84.0.** La prueba real confirmó audio y video, velocidades variables, salto temporal al segmento, corrección persistente, una mención `Memoria`, búsqueda con apertura directa, exportación y una corrida `faster-whisper` `tiny` completada en CPU sobre video. RC1 reveló dos regresiones de UI —salto temporal inefectivo y navegación audiovisual descartada desde búsqueda— que RC2 corrigió y revalidó. El diagnóstico final informó `quick_check: ok`, cero violaciones FK, originales intactos, cinco segmentos exportables y dos segmentos producidos por la corrida CPU. `AV-01` queda cerrado.

El gate de cierre con la suite completa detectó además que la huella de intercambio intentaba leer tablas AV aun al ejercitar bases históricas anteriores a `0045`. La implementación final comprueba la presencia del esquema audiovisual antes de incorporarlo al estado, conservando el comportamiento histórico durante migraciones; también se actualizaron únicamente los fixtures y verificadores antiguos que habían quedado fijados a versiones o revisiones anteriores.

### AV-02 — incorporación autorizada desde plataformas — 0.85.0

Archive Workbench incorpora una extensión opcional `platform` basada en `yt-dlp` para descargar audio o video autorizado desde plataformas compatibles y registrarlo inmediatamente mediante el circuito local de `AV-01`. No agrega tablas ni migración: conserva la revisión `0045_audiovisual_transcription` y utiliza `SourceRegistration.source_payload_json` para almacenar URL solicitada y canónica, plataforma e identificador, canal/uploader, fecha de publicación, formatos seleccionados, versión de `yt-dlp`, ruta local, SHA-256, tamaño, fecha de descarga y condiciones de acceso/autorización.

La vista **Transcribir audio y video** agrega el panel cerrado **Incorporar desde plataforma**, con URL, unidad archivística, incorporación como video o solo audio, condiciones de acceso/autorización y confirmación explícita. El material incorporado queda disponible para reproducción y para el circuito de transcripción de `AV-01`, pero la descarga no inicia una transcripción automáticamente. La exportación de segmentos conserva también la procedencia remota.

**Validada manualmente en 0.85.0.** La prueba real incorporó desde YouTube el video `RememorArte Horacio BAU` (`CwWKigBOfjQ`) del canal `Centro Cultural por la Memoria Trelew` (`UCsZG_7l0cYIEtJNhajrFPYg`). El archivo quedó registrado como MP4 de 436.221 s, 1280×720, H.264 + Opus, con SHA-256 `f187eaa71718ed2b016ec3af01e58102d19537d758fdc5c21df46f00378ec7ba`; el verificador confirmó `quick_check: ok`, cero violaciones FK, procedencia y condiciones de acceso persistentes y `transcription_run_count: 0`. RC1 expuso además que un campo obligatorio vacío podía mostrar un `ValidationError` técnico de Pydantic; RC2 reemplazó esos fallos por mensajes comprensibles para personas no técnicas y la revalidación manual fue satisfactoria. `AV-02` queda cerrado.

### AV-03 — evaluación, revisión sincronizada y calidad de reconocimiento — 0.86.0

Archive Workbench evaluó el circuito audiovisual sobre el video real autorizado `RememorArte Horacio BAU`. La línea de base `faster-whisper small` + CPU `int8` completó 436.221 s de medio en 202.21 s (`RTF 0.464`) y produjo 89 segmentos. Cinco segmentos deterministas fueron corregidos una sola vez por una persona y dieron CER 0.100 / WER 0.163 sobre la salida automática original. La prueba mostró además que editar 89 segmentos como unidades independientes era demasiado costoso para una revisión normal.

RC2–RC4 reemplazaron esa interacción por una transcripción continua editable sin perder los tiempos subyacentes. RC5 agregó `0046_audiovisual_timeline_annotations`, con hablantes y anotaciones temporales estructurados, vinculables opcionalmente a autoridades e independientes de cada corrida. RC6 incorporó la revisión sincronizada junto al reproductor: avance del segmento vigente, seek al pulsar texto y creación de hablantes/anotaciones desde el tiempo actual. La validación manual confirmó que este recorrido es usable.

RC7 ejecutó una segunda corrida completa con el perfil `faster-whisper large-v3` + CUDA `float16` y `beam_size=5`: 914.92 s (`RTF 2.097`) y 5394 MiB de VRAM máxima observada. La comparación final conserva `original_text` como hipótesis y `corrected_text` sólo como referencia revisada. Como `large-v3` usa otra segmentación y estas corridas no guardan timestamps por palabra, 0.86.0 no fabrica CER/WER mediante recortes guiados por la referencia: muestra el contexto automático temporalmente solapado y las dos transcripciones completas. La revisión cualitativa de ambas salidas concluyó que el perfil probado `large-v3` + CUDA ofrece mayor calidad global —mejor recuperación de frases, nombres y relaciones semánticas— que `small` + CPU, aunque con mayor coste de ejecución y errores residuales que mantienen necesaria la revisión manual. La línea de base CPU se conserva como recorrido portable y no se cambia el default general a partir de un único material.

**Validada manualmente en 0.86.0.** RC12 confirmó el evaluador corregido, la visualización completa de ambas salidas y el recorrido de `Transcribir audio y video → Evaluar transcripción → Comparar reconocimiento` sin crash después de limpiar el estado problemático del perfil de Firefox. `AV-03` queda cerrado.

## Benchmark OCR con verdad terreno

### OCR-01F — Tesseract, Docling y Surya — 0.83.0

Se agregó una comparación reproducible contra transcripciones de referencia por página. El benchmark usa los mismos derivados OCR vigentes, ejecuta los perfiles existentes de Tesseract, Docling y Surya sin fallback entre motores, calcula CER/WER mediante distancia de Levenshtein y registra tiempo, versiones, perfiles, texto y salida cruda. La verdad terreno se conserva por archivo y SHA-256, y cada corrida guarda una copia exacta de la referencia usada.

No escribe selecciones canónicas ni inicializa la capa editable. La validación real ejecutó Tesseract 5.3.4, Docling 2.114.0 y Surya 0.22.1 sobre la misma página y la misma verdad terreno. Los tres obtuvieron CER 0.0000 y WER 0.0000 en el caso controlado; los tiempos registrados fueron 0.27 s para Tesseract, 23.07 s para Docling y 209.84 s para Surya. Se conservaron el texto comparado, las salidas crudas, versiones, perfiles, métricas, tiempos, la copia de la verdad terreno y su SHA-256. El TIFF original permaneció intacto y la selección canónica vacía. `OCR-01F` y el bloque completo `OCR-01` quedan cerrados en 0.83.0.

## Preprocesamiento geométrico para OCR

### OCR-01E — Dewarp conservador — 0.82.0

El nuevo modo `conservative_dewarp` extiende la preparación geométrica con una estimación de curvatura vertical suave. Divide la página en franjas, compara perfiles de tinta, ajusta una curva cuadrática y aplica una malla reproducible únicamente al derivado OCR. La decisión exige soporte suficiente, desplazamiento acotado, ajuste estable y confianza superior al umbral.

Cada página conserva `dewarp_detected`, `dewarp_applied`, confianza, desplazamiento máximo, franjas con soporte, calidad de ajuste, coeficientes y motivo. Se genera un activo `dewarp_diagnostic` separado de la máscara de líneas. La previsualización y el original permanecen intactos. No requiere migración.

**Estado:** implementada, validada y cerrada en 0.82.0. La validación específica de navegación confirmó que documentos y opciones permanecen seleccionados al abrir y recorrer el diagnóstico geométrico.

### OCR-01D — OCR regional visual y zonas documentales — 0.81.0

La extracción regional versionada ya disponible por CLI se integra en **Procesar documentos > OCR regional** mediante un recorrido lineal de seis pasos. La persona elige documento y página, ve la página preparada, carga una plantilla o dibuja zonas, las describe con una clasificación controlada y decide si cada una se procesa por OCR o queda como región manual. Las opciones técnicas de Tesseract permanecen bajo un panel avanzado.

Cada corrida conserva cajas normalizadas, orden, modo, tipo de objeto, clasificación semántica, recortes, resultados crudos, `regions.jsonl` y manifiesto. Se ejecuta con `selection_policy=never`: no cambia la selección canónica ni la capa editable. Una región manual conserva imagen y geometría para revisión posterior y no inventa una transcripción. No agrega migraciones; continúa sobre `0044_layout_structure_review`.

**Validada manualmente en 0.81.0.** La prueba confirmó una corrida terminada con seis zonas, tres regiones OCR y tres manuales, seis recortes, al menos un objeto por zona, clasificación semántica correcta, selección canónica vacía, contrato regional 1.1 e integridad del PDF original. `OCR-01D` queda cerrada.

### OCR-01C — columnas y orden de lectura revisables — 0.80.0

La capa editable calcula una propuesta no canónica de columnas a partir de geometrías normalizadas, muestra el orden sugerido sobre la página y conserva sin cambios el orden vigente hasta una confirmación explícita. La confirmación crea columnas estables, aplica el orden mediante revisiones de objeto y permite reasignación manual, creación, renombrado y archivo de columnas.

El mismo diagnóstico señala secuencias posiblemente fragmentadas y objetos posiblemente duplicados. Ninguna candidata se corrige sola: combinar o archivar exige una decisión explícita y participa en historial, deshacer/rehacer e intercambio. La migración `0044_layout_structure_review` agrega `layout_structure_json` a páginas y revisiones; la exportación incorpora `layout_structures.jsonl` y manifiesto 1.4.

**Validada manualmente en 0.80.0.** La base controlada confirmó tres columnas activas —`Columna 1`, `Columna 2` y `Margen derecho`—, cinco objetos editables activos, cero fragmentaciones o duplicaciones pendientes, orden vigente coincidente con la propuesta, historial específico con confirmación, renombrado, combinación, archivo, deshacer y rehacer, y exportación `layout_structures.jsonl` con manifiesto 1.4. El PDF conservó su SHA-256 y los siete objetos OCR de origen permanecieron intactos. Durante la validación se corrigieron la ausencia de imagen cuando no había preview, un acceso inválido a `ReviewPageView.page_number`, la ambigüedad entre **Historial general** y el historial específico de layout, y el guiado de las acciones nuevas. `OCR-01C` queda cerrada; la revisión integral de densidad y comprensión de **Orden y estructura** permanece registrada en `UX-02`.


### OCR-01B — formularios y casilleros revisables — 0.79.0

Los indicadores automáticos de casilleros siguen siendo candidatos no canónicos. La capa editable permite confirmarlos de forma explícita, asignar los estados controlados `marked`, `unmarked` o `indeterminate`, corregir rótulos, vincular la marca y el texto a objetos editables y registrar evidencia. Un casillero visible que no fue representado por OCR puede darse de alta manualmente sin inventar un objeto extraído ni modificar la imagen.

Los controles pueden agruparse mediante identificadores persistentes dentro de cada página. Crear, renombrar o archivar un grupo y confirmar, corregir o archivar un control conserva snapshots append-only en las revisiones de página. Archivar un grupo no elimina sus controles: los desvincula y conserva tanto la agrupación histórica como las confirmaciones. Las acciones participan en deshacer/rehacer, intercambio offline y adopción de estado. La exportación editable incorpora `form_structures.jsonl` y el manifiesto 1.3.

La migración aditiva `0043_form_structure_review` agrega `form_structure_json` a `editable_pages` y `editable_page_revisions`. La estructura se valida como una unidad coherente, con IDs únicos y referencias de grupo válidas; las páginas anteriores reciben objetos vacíos. `create_form_structure_validation_project.py` genera una ficha controlada con candidatos marcados y no marcados, un vínculo por proximidad y un casillero visible para alta manual.

**Validada manualmente en 0.79.0.** Se confirmaron grupos, controles, historial, deshacer/rehacer, exportación, SHA-256 del original y ausencia de acceso a `project_data`. Durante la prueba se detectó que acciones renderizadas antes del bloque de pestañas podían hacer volver la interfaz a **Editar texto**; la RC2 agregó una copia durable de la pestaña activa y la validación posterior confirmó que deshacer, rehacer, exportar y las demás acciones conservan la subsección activa. `OCR-01B` queda cerrada; `OCR-01` continúa parcial por los alcances restantes. La simplificación integral de **Formulario** y una referencia visual persistente de la página quedan programadas en `UX-02`.

### OCR-01A — orientación, deskew y líneas controladas — 0.78.0

La preparación de páginas incorpora un modo geométrico conservador que detecta orientaciones de `0°`, `90°`, `180°` y `270°`, aplica deskew dentro de un rango acotado y elimina únicamente líneas o marcos largos que superan los controles de longitud, espesor e intersección con texto. Una confianza insuficiente no modifica la página: la omisión queda registrada como advertencia y transformación no aplicada.

El original y la previsualización permanecen intactos. El tratamiento produce un derivado OCR separado, una máscara diagnóstica de los píxeles eliminados y metadatos estructurados por página con orientación, confianzas, rotación, ángulo de deskew, líneas detectadas, líneas eliminadas y transformaciones aplicadas u omitidas. La interfaz compara en paralelo la previsualización sin cambios, el derivado OCR y la máscara.

La migración aditiva `0042_preprocessing_geometry_trace` agrega `analysis_json` y `transformations_json` a `derivative_assets`. No reconstruye la tabla ni altera derivados anteriores; los registros existentes reciben objetos vacíos. El script `create_preprocessing_geometry_validation_project.py` crea fuera del repositorio cinco casos controlados: orientación a 90°, inclinación de 3°, marco y líneas largas, línea que cruza texto y página de baja confianza.

**Validada manualmente en 0.78.0.** Se confirmaron la rotación controlada de `90°`, el deskew de `-3°`, la eliminación exclusiva de cuatro líneas de marco, la conservación de una línea que cruza texto, la omisión por baja confianza y la presencia de candidato, confianza, umbral y motivo en cada transformación. Los cinco originales conservaron sus SHA-256, ninguna extracción fue adoptada automáticamente como canónica y `project_data` no fue leído ni modificado durante la prueba. `OCR-01A` queda cerrada; `OCR-01` continúa parcial por los alcances restantes.

## Productores, gestores y estructura documental en el grafo

### CAT-02 + GRAPH-02 — implementación conjunta — 0.77.0

Las entidades productoras y gestoras se registran como relaciones controladas `producer` y `manager` entre una autoridad canónica existente y una unidad archivística. Cada vínculo conserva período, evidencia, procedencia, revisión manual, ciclo de vida e historial append-only. Las etiquetas visibles `produjo` y `gestionó` se generan desde el tipo controlado y no se admiten como nombres libres canónicos. Una misma autoridad puede ocupar roles distintos en unidades o períodos diferentes; un cambio de gestión crea otro vínculo y no reescribe el anterior.

La migración `0041_catalog_authority_roles_graph_layers` agrega `relation_kind` y `provenance_note` de manera aditiva. Las relaciones anteriores quedan clasificadas como `analytical`. Los triggers de SQLite impiden roles sin unidad archivística, evidencia, procedencia o etiqueta canónica, y el intercambio offline conserva todos los campos nuevos.

El grafo distingue nodos de autoridad, unidad archivística, objeto digital y parte documental. Sus capas separan jerarquía, pertenencia de documentos, partes internas, menciones, relaciones analíticas, productores, gestores y la capa derivada de entidades compartidas ya existente. La vista permite filtrar niveles, elegir cualquiera de los cuatro tipos de nodo como foco, limitar profundidad y cantidad de nodos, y mostrar la procedencia explicable de cada arista. Las aristas dirigidas terminan en una flecha visible, mientras que la capa simétrica de entidades compartidas permanece sin flecha. La distancia queda siempre disponible y solo se aplica cuando hay un foco. Las relaciones entre objeto digital y unidad siguen la dirección del contrato catalográfico y usan etiquetas legibles en español. JSON, CSV y GraphML conservan el tipo de vínculo, la explicación y la procedencia; las fechas se serializan en ISO.

La validación automatizada creó una base descartable fuera del repositorio en revisión `0041_catalog_authority_roles_graph_layers`, produjo las siete capas requeridas, los cuatro tipos de nodo y cero errores de consistencia. **Validado manualmente en 0.77.0.** Se confirmaron los roles y períodos históricos, el historial append-only, las siete capas, el foco y la distancia, las flechas dirigidas, la pertenencia documental `objeto digital → unidad archivística` y las exportaciones JSON, CSV y GraphML. El JSON final registró nueve nodos, doce aristas, cero inconsistencias y ningún truncamiento. `CAT-02` y `GRAPH-02` quedan cerrados.

## Plantillas distribuibles de catálogo

### CAT-01 — exportación, simulación e importación XLSX — 0.75.0

**Corrección 0.75.1.** El formulario ya no deshabilita el botón según un campo escrito dentro del mismo `st.form`: el botón se envía habilitado y luego comprueba la confirmación exacta `IMPORTAR`. La hoja `LISTAS` continúa oculta porque funciona como soporte de los desplegables y no requiere edición ordinaria. El proyecto descartable usa ahora la identidad neutral `Proyecto de validación CAT-01`.

Se incorporó un formato XLSX versionado con cuatro hojas: `INSTRUCCIONES` documenta el contrato y cada campo; `ESTRUCTURA` declara niveles y padres permitidos; `CATALOGO` contiene las unidades y sus valores descriptivos; y `LISTAS` alimenta controles de valores válidos. La plantilla puede exportarse vacía o con el catálogo vigente desde la interfaz y mediante `catalog-template-export`.

La estructura transportada puede restringir los padres admitidos por el proyecto, pero nunca ampliarlos. La simulación mediante `catalog-template-validate` comprueba el esquema, IDs locales y persistentes, padres inexistentes, ciclos, niveles desconocidos, transiciones jerárquicas, campos aplicables, tipos, estados y confirmaciones de completitud. Los errores conservan hoja, fila, columna y código.

La aplicación requiere `--apply --confirm IMPORTAR` en la CLI o la misma confirmación explícita en la interfaz. Primero valida el libro completo y después crea, actualiza, mueve u omite unidades dentro de una sola transacción. Las escrituras usan las operaciones canónicas del catálogo, conservan historial de revisiones y no generan una actualización nueva cuando una exportación se reimporta sin cambios. La URL y la nota de procedencia de cada fila quedan incorporadas a la revisión y, cuando corresponde, a la procedencia del campo descriptivo.

Se incluye `examples/plantilla_catalogo_dippba.xlsx`, generada desde `config/catalog_templates/dippba_public_seed.json`. Contiene 155 filas trazables obtenidas de información pública de la Comisión Provincial por la Memoria. Las elipsis y los agrupamientos sin nivel rotulado se señalan expresamente como parciales o provisionales; la plantilla no inventa denominaciones ausentes ni debe tratarse como descripción archivística definitiva.

**Validada manualmente en 0.75.1.** Se confirmó el rechazo de un documento directamente bajo un fondo, la importación de las 155 filas DIPPBA, la jerarquía completa, la exportación del catálogo y la reimportación idéntica sin revisiones nuevas. `CAT-01` queda cerrado. No hay migración: continúa `0040_discovery_grouping_continuity`.

## Diccionarios distribuibles de autoridades

### DISC-02 — esquema, simulación e importación transaccional — 0.76.0

Se incorporó un formato JSON `1.0` con esquema y ejemplo versionados. Cada diccionario registra identidad, fuente y proyecto de destino; describe autoridades, alias, temporalidad, características y relaciones; y conserva una huella SHA-256 reproducible en el informe de simulación.

La detección de duplicados compara nombres preferidos y alias normalizados. El modo `auto` crea registros nuevos solo cuando no hay coincidencias y reutiliza únicamente una coincidencia exacta de nombre y tipo. Los casos ambiguos exigen `use_existing`, `create_new` o `skip`. Una autoridad existente nunca es sobrescrita: puede recibir alias nuevos, mientras las diferencias de descripción, características o temporalidad se muestran como advertencias.

Las relaciones pueden dirigirse a otra autoridad, una unidad archivística o una parte documental. Cada una requiere evidencia en el propio JSON. Las relaciones idénticas se omiten en reimportaciones; una relación paralela con evidencia o temporalidad distinta exige `create_parallel` o `skip`.

La CLI ofrece `authority-dictionary-schema`, `authority-dictionary-validate` y `authority-dictionary-import`; la interfaz agrega **Importar diccionario** dentro de **Entidades y menciones**. La aplicación requiere la confirmación `IMPORTAR` y ejecuta autoridades, alias y relaciones dentro de una sola transacción. La guía canónica está en `docs/referencia/IMPORTACION_DICCIONARIOS_DISC_02.md`.

**Validado manualmente en 0.76.0.** Se confirmó que una coincidencia nominal ambigua exige resolución explícita, que una relación sin evidencia es rechazada y que el diccionario controlado crea dos autoridades, reutiliza una ficha sin sobrescribirla, agrega dos alias y crea dos relaciones. La reimportación idéntica produjo cero autoridades, cero alias y cero relaciones nuevas y omitió las dos relaciones duplicadas. `project_data` no fue leído ni modificado. `DISC-02` queda cerrado. No hay migración: continúa `0040_discovery_grouping_continuity`.

## Descubrimiento abierto

### Primera ejecución con menciones existentes — 0.69.1

Se reemplazó el acceso inválido a `EntityMention.lifecycle_status` por el contrato real de `EntityMention.status`. Solo las menciones no rechazadas y con offsets completos bloquean un tramo ya registrado. El panel se movió al final de la vista y queda colapsado por defecto. La corrección quedó incluida en la validación final de `DISC-01A`.

### DISC-01A — detección reproducible validada — 0.69.2

La validación manual de la corrida existente quedó cerrada con 17 objetos aprobados recorridos, 13 candidatos totales y siete candidatos controlados correctos. Se comprobaron las seis familias previstas, offsets, revisión textual, ausencia de escrituras canónicas durante la detección, revisión `0038_open_discovery`, integridad `ok` y claves foráneas vacías. La cantidad mayor de objetos y candidatos corresponde a otros documentos aprobados presentes en la copia y no es una anomalía.

### Verificación de descubrimiento sobre corpus no vacío — 0.69.2

La validación de `DISC-01A` identifica el objeto controlado por su ID y comprueba sus siete candidatos sin asumir que la corrida excluye otros documentos aprobados. El total de candidatos y objetos puede ser mayor.

### DISC-01B — revisión persistente implementada — 0.70.0

La migración `0039_discovery_decisions` agrega `discovery_decisions` y `discovery_context_records`. Cada candidato puede aceptar, rechazar, modificar o aplazar mediante una decisión append-only. Actores, espacios, acontecimientos y obras pueden vincularse a una autoridad existente o iniciar explícitamente una autoridad `unreviewed`; tiempos, acontecimientos y acciones o procesos conservan datos propios. Las decisiones obsoletas se bloquean por revisión textual, toda escritura conserva responsable y origen, y ninguna aceptación crea relaciones automáticamente.

### DISC-01B — revisión persistente validada — 0.70.2

La validación manual confirmó ocho decisiones controladas y una decisión adicional append-only sobre `manifestación`, cuatro registros propios, dos menciones controladas y ninguna relación creada automáticamente. Los conteos finales conservados son siete autoridades, doce menciones, tres relaciones, nueve decisiones y cuatro registros propios. Los paneles interactivos permanecieron abiertos al cambiar decisiones y destinos.

### DISC-01C — agrupamiento y continuidad implementados — 0.71.0

La migración `0040_discovery_grouping_continuity` agrega grupos, pertenencias, acciones append-only y vínculos de continuidad entre candidatos. El agrupamiento automático propone coincidencias exactas o normalizadas entre corridas; el agrupamiento manual permite reunir y separar candidatos sin fusionar sus filas ni borrar procedencias. Una separación conserva la pertenencia histórica con estado retirado y no es revertida por una reconstrucción automática posterior.

Cuando una revisión textual vuelve obsoleto un candidato, la continuidad crea una corrida y un candidato nuevos mediante proyección exacta única o nueva detección local. El candidato anterior continúa visible, el nuevo snapshot conserva offsets y revisión vigentes y las pertenencias activas de grupo se trasladan como procedencia, nunca como decisión explícita. La interfaz ubica la función en un panel secundario cerrado por defecto y usa paneles persistentes para que los reruns no interrumpan el recorrido. La validación manual quedó cerrada en 0.72.0.

### Selección segura después de crear un grupo manual — 0.71.1

La creación del grupo se confirma y persiste antes del rerun. La interfaz ya no intenta modificar la clave de un `selectbox` después de instanciarlo: guarda una selección pendiente en una clave separada, ejecuta el rerun y aplica esa selección antes de crear el widget. Esto evita `StreamlitAPIException`, conserva abierto el recorrido y no duplica el grupo ya escrito.

### Validación de continuidad desde snapshots equivalentes — 0.71.2

La continuidad de `Cuaderno del Delta` puede iniciarse desde cualquiera de los dos candidatos obsoletos controlados que representan el mismo texto, objeto y revisión y ya pertenecen al mismo grupo. El validador dejó de exigir arbitrariamente el identificador `work_original` y comprueba en cambio que el origen sea uno de los snapshots controlados equivalentes, que esté obsoleto, que el destino sea vigente y que ambos permanezcan en el grupo. La regresión de extremo a extremo usa ahora el candidato duplicado, que fue el seleccionado durante la prueba manual.

### DISC-01C — agrupamiento y continuidad validados — 0.72.0

El validador final confirmó cuatro grupos —tres automáticos y uno manual—, nueve pertenencias conservadas, catorce acciones append-only y una continuidad desde un snapshot equivalente. También conservó exactamente siete autoridades, doce menciones, tres relaciones, nueve decisiones y cuatro registros propios. La revisión es `0040_discovery_grouping_continuity`, la integridad es correcta y no hay claves foráneas inválidas. La prueba no debe repetirse.

### DISC-01D — evaluación reproducible y proveedor opcional — 0.73.0

Se agregó un corpus JSONL inicial con cobertura explícita de las siete familias, texto exacto, offsets, subtipo y procedencia. El evaluador calcula precisión, recuperación y F1 micro, macro y por familia; conserva predicciones, falsos positivos, falsos negativos, discrepancias de familia o subtipo, parámetros y huellas SHA-256. Los informes del mismo corpus pueden compararse por proveedor, versión y configuración.

El proveedor `local_deterministic@local_rules_v1` continúa disponible sin declararse empíricamente superior. El adaptador opcional `spacy_ner` usa el mismo contrato auditable y exige fijar `modelo@versión`; la dependencia y el modelo se cargan únicamente al ejecutar ese perfil. El corpus inicial es un control sintético de contrato, no un benchmark representativo: muestra seis aciertos de siete y documenta que la familia `other` no es cubierta por las reglas locales. `DISC-01` queda cerrado sin migración nueva.

### UX-03 — recorridos separados para entidades y descubrimiento — 0.72.0

La vista **Entidades y menciones** separa ahora tres tareas principales persistentes: revisar entidades, crear una entidad y abrir Descubrimiento abierto. La creación dejó de competir visualmente con la búsqueda y el descubrimiento ya no aparece como un panel agregado al final de una ficha.

Dentro de Descubrimiento abierto se distinguen **Revisar candidatos**, **Nueva corrida** y **Agrupamiento y continuidad**. La revisión cotidiana queda primero; la configuración de perfiles y la ejecución se aíslan en su propia tarea; agrupamiento y continuidad se dividen en recorridos persistentes. Los historiales, resúmenes y datos técnicos permanecen cerrados por defecto. Se conservaron autoridades, menciones, relaciones, perfiles, corridas, decisiones, grupos, continuidades y contratos de datos sin migración nueva.

La validación manual confirmó los recorridos separados, la conservación de la pestaña activa y el cierre inicial de resúmenes, historiales, filtros y detalles técnicos.

## Correcciones validadas

### Ciclo de vida visual de perfiles de exportación — 0.50.3

**Resuelto y validado manualmente.** Archivar, restaurar y eliminar perfiles reconstruye un único selector, un único bloque de pestañas y un único formulario. La secuencia previa al render evita duplicaciones visuales sin modificar archivos ni historial.

## Núcleo documental

### Catálogo y originales

- Catálogo archivístico jerárquico y campos configurables.
- Registro de objetos digitales y ubicaciones locales.
- Originales inmutables y verificación de presencia, tamaño y checksum.
- Partes internas y asociación de páginas con documentos.
- Migraciones explícitas mediante `db-upgrade`.

### Procesamiento y extracción

- Preparación reproducible de derivados para OCR.
- Corridas versionadas por página y perfil.
- Tesseract, Docling y Surya como backends revisables.
- Runtime Surya aislado y servidor persistente con fallback.
- Comparación de corridas no canónicas mediante texto, imagen y cajas.
- Selección canónica independiente de la evaluación de calidad.
- Diagnóstico de brillo, contraste, desenfoque probable, ruido, fragmentación, objetos mínimos y solapamientos.
- Control conservador de ordinales y candidatos de casilleros sin corrección silenciosa.

La evaluación empírica inicial de Surya y las decisiones técnicas se conservan en `docs/historico/decisiones_tecnicas/`.

### Decisión de alcance sobre duplicados y copias — OCR-02, 0.74.0

- Los archivos binariamente idénticos ya se reconocen por SHA-256 dentro de cada proyecto: `DigitalObject` conserva unicidad por `project_id + sha256` y una nueva ubicación se registra como otra instancia del mismo objeto digital.
- Dos copias, ejemplares o digitalizaciones catalográficamente distintas pueden contener el mismo texto y seguir siendo documentos diferentes por procedencia, soporte o contexto.
- Cada objeto documental distinto conserva su propio OCR y sus derivados; Archive Workbench no sustituye automáticamente una representación por otra ni elige una copia “más legible” para reemplazar la fuente.
- La identificación intelectual de duplicados documentales corresponde al proceso de catalogación. No se implementa una deduplicación OCR adicional que pueda mezclar procedencias.

`OCR-02` queda cerrado como decisión de alcance, sin migración ni cambios de datos.

## Revisión e historial

### Editor y auditoría

- Edición de texto y tipo de objeto.
- Alta, baja lógica, restauración, división, unión y reordenamiento.
- Comentarios, etiquetas, partes documentales y estados de revisión.
- Deshacer y rehacer transaccional.
- Historial integrado de página y por objeto, incluido el estado OCR inicial.

### Rebase de edición sobre otra extracción

Implementado entre 0.40.0 y 0.48.0:

- rebase conservador de tres estados;
- relocalización de comentarios, etiquetas y menciones;
- resolución manual de conflictos de menciones;
- resolución de conflictos textuales;
- conservación del snapshot estructural activo;
- decisiones de parte documental, estado y tipo;
- proyección manual de objetos ambiguos;
- resolución de atributos especializados;
- ciclos `A → B → A → B` sin violar unicidad histórica;
- conservación de procedencia e historial;
- entradas manuales con botón explícito y sin envío por `Enter` o `Ctrl+Enter`.

La validación manual confirmó tres rebases sucesivos, conservación de atributos, dos comentarios, dos etiquetas y ausencia del remanente visual oscuro.

## Búsqueda, autoridades y grafo

### Búsqueda

- Índice literal FTS5 y búsqueda por trigramas.
- Búsqueda semántica opcional con perfiles e índices reconstruibles.
- Navegación desde resultados hacia documento, página y objeto.
- Filtros por estado de página en búsqueda literal y semántica.

### Calibración reproducible de búsqueda semántica — SEM-01, 0.74.0

- `semantic-evaluate` ejecuta consultas verificadas contra un perfil y un índice vigentes sin modificar la base, el corpus ni los vectores.
- El corpus JSONL distingue consultas `positive`, `negative` y `ambiguous`, fija el tipo de fragmento y permite evaluar por `chunk_id`, `record_id`, `source_key` u `object_id`.
- Cada informe conserva corpus, perfil, modelo, revisión, corrida de índice, parámetros, resultados ordenados, falsos positivos, falsos negativos y métricas por umbral y tipo de consulta.
- El umbral recomendado maximiza F1 dentro del conjunto evaluado y queda acompañado por una advertencia explícita: no es universal y solo vale para ese corpus, perfil, modelo, revisión de índice y grilla de umbrales.
- `semantic-evaluation-compare` compara informes del mismo corpus y tipo de fragmento sin declarar un modelo superior fuera de esa evidencia.
- `config/semantic_evaluation_corpus.example.jsonl` documenta los tres tipos de consulta y exige reemplazar las claves de ejemplo por referencias verificadas del proyecto.

No hay migración: los informes son archivos JSON reproducibles y la ejecución solo lee el índice y la base existentes.

**Validada en 0.74.0.** El proyecto descartable conservó la revisión `0040_discovery_grouping_continuity`, recomendó el umbral controlado `0.7` con F1 `0.8`, produjo un informe alternativo comparable y confirmó que `project_data` no fue leído ni modificado. El resultado valida el contrato y la comparación reproducible; no fija un umbral universal.

### Autoridades y menciones

- Autoridades con nombre preferido, alias, tipo, estados y temporalidad.
- Rastreo transversal de nombres y alias ya registrados.
- Incorporación de menciones con offsets y revisión textual.
- Invariante que impide menciones aceptadas o modificadas sin autoridad.
- Historial append-only de creación, desvinculación y revinculación.
- Deduplicación transrevisionaria y conflicto cuando un fragmento ya está vinculado a otra autoridad.
- Diagnósticos para menciones huérfanas, antiguas y duplicadas.

El descubrimiento de elementos desconocidos es una función separada y quedó cerrado como `DISC-01` en 0.73.0.

### Relaciones

**Resuelto y validado en 0.46.0:** creación con confirmación explícita, edición de tipo, evidencia, temporalidad y estado, cambio de destino, baja lógica y conservación de todas las revisiones. La baja lógica se refleja correctamente en el grafo.

### Grafo

- Relaciones explícitas, entidades compartidas y capas derivadas.
- Filtros de entidades o relaciones inactivas.
- Advertencias de consistencia y procedencia de aristas.

### Grafo sin colisiones — GRAPH-01, 0.74.0

- Las aristas paralelas, incluidas las de sentido inverso, reciben carriles deterministas y separados.
- El canvas usa rutas cuadráticas o bucles propios en lugar de líneas superpuestas, y recalcula la geometría al arrastrar nodos.
- Las etiquetas de aristas se desplazan automáticamente cuando colisionan con nodos u otras etiquetas.
- Las etiquetas de nodos se envuelven en dos líneas y eligen automáticamente el lado menos ocupado.
- Los tooltips de nodos y aristas muestran tipo, contexto, explicación del origen, evidencia, estado, período y fuente cuando esos datos existen.
- El layout aplica una separación mínima determinista entre centros de nodos y conserva el mismo resultado ante la misma vista.
- La identidad del componente incorpora todos los filtros visibles para que el estado corresponda exactamente a la vista solicitada.

Los filtros y la explicación detallada ya existentes se conservan; no se agrega un panel nuevo a la pantalla principal.

**Validado manualmente en 0.74.0.** Se comprobaron tres relaciones curvas separadas entre los nodos controlados, incluida una relación en sentido inverso; los tooltips conservaron tipo, dirección, procedencia y evidencia; al arrastrar nodos se recalcularon curvas y etiquetas; y los filtros coincidieron con el resumen, la tabla y el canvas.


## Reparación auditable de menciones

### Reubicación segura sobre el texto vigente — fase 1, 0.57.0

- Las menciones activas se separan de las menciones rechazadas, que permanecen como evidencia histórica.
- Cada alerta se clasifica como reubicación segura, ubicación no resuelta, colisión con otra mención, vínculo faltante o divergencia de snapshot.
- La reubicación automática solo se habilita cuando existe una proyección única, no hay otra mención activa en el mismo fragmento y la fila coincide con su último snapshot.
- La operación exige confirmación explícita, actor y nota; actualiza offsets y revisión textual, incrementa la revisión de la mención y agrega un snapshot `repair_relocation`.
- Los snapshots anteriores no se modifican y la revisión rechazada o ambigua nunca se repara automáticamente.
- `scripts/create_mention_repair_validation_project.py` genera una copia descartable para validar el recorrido sin alterar proyectos reales.

### Resolución de menciones sin entidad — fase 2, 0.58.0

- Una mención histórica con estado `accepted` o `modified` y sin entidad vinculada puede asociarse a una entidad activa existente del mismo proyecto.
- Como alternativa, puede volver a estado `pending` para exigir una revisión manual posterior.
- Las dos rutas requieren confirmación explícita, actor y nota.
- La vinculación agrega una revisión `repair_link_authority`; el retorno a pendiente agrega `repair_return_pending`.
- Las revisiones y snapshots anteriores permanecen intactos.
- Si la fila vigente diverge de su último snapshot, ninguna de las dos decisiones se habilita.
- `scripts/create_missing_authority_validation_project.py` crea dos casos descartables, con frases completas, para validar ambas rutas sin alterar proyectos reales.

**Validada manualmente en 0.58.0.** Las dos rutas produjeron `repair_link_authority` y `repair_return_pending`, eliminaron las alertas activas correspondientes y conservaron integridad y claves foráneas válidas.

### Resolución de menciones duplicadas — fase 3, 0.59.0

- La comparación se habilita cuando una mención histórica converge con exactamente una mención activa sobre el fragmento vigente.
- La persona revisora puede conservar la mención vigente y retirar la histórica, o conservar la histórica, retirar la vigente y reubicar la elegida.
- La mención retirada agrega `repair_duplicate_rejected`; la histórica conservada y reubicada agrega `repair_duplicate_relocated`.
- No se fusionan entidades, notas ni snapshots, y ninguna mención se elimina físicamente.
- Las dos filas deben coincidir con sus últimos snapshots y con las revisiones mostradas por el formulario.
- Los conjuntos con más de una contraparte se mantienen bloqueados para evitar decisiones parciales.
- `scripts/create_duplicate_mention_validation_project.py` crea dos pares descartables para validar ambas rutas sin alterar proyectos reales.

**Validada manualmente en 0.59.0.** Las dos decisiones conservaron la mención elegida, retiraron la contraparte mediante revisiones nuevas y dejaron la base íntegra y sin claves foráneas inválidas.

### Resolución manual de ubicaciones — fase 4, 0.60.0

- Los casos `unresolved_relocation` permiten indicar un fragmento literal del texto vigente y elegir una aparición concreta.
- La reubicación manual verifica revisión textual, revisión de mención, contenido exacto, offsets y ausencia de otra mención activa antes de registrar `repair_manual_relocation`.
- Cuando el fragmento histórico ya no aparece, puede retirarse la mención mediante `repair_mark_absent`; no se borra el registro ni se alteran revisiones anteriores.
- No se permite declarar ausencia cuando el fragmento todavía aparece en el texto vigente.
- Las dos decisiones exigen confirmación explícita, actor y fundamento, y generan eventos de intercambio `update`.
- `scripts/create_unresolved_mention_validation_project.py` crea una aparición ambigua y un fragmento ausente dentro de una copia descartable.

**Validada manualmente en 0.60.0.** La prueba confirmó la reubicación en la segunda aparición, el retiro del fragmento ausente, las operaciones `repair_manual_relocation` y `repair_mark_absent`, cero alertas restantes, integridad `ok` y ausencia de claves foráneas inválidas.

### Reconciliación entre fila e historial — fase 5, 0.61.0

- Los casos `snapshot_divergence` comparan en pantalla cada campo distinto entre la fila vigente y el último snapshot registrado.
- La persona revisora puede conservar la fila vigente mediante `repair_adopt_current_row` o restaurar el último estado registrado.
- Antes de restaurar, `repair_capture_divergent_row` incorpora la fila divergente al historial para que ningún valor observado desaparezca.
- La restauración agrega después `repair_restore_snapshot`; no reescribe ni elimina snapshots anteriores.
- El formulario queda obsoleto si cambia la fila, la revisión de la mención o el contenido del último snapshot.
- Se validan objeto, entidad, estado, procedencia, offsets y pertenencia al proyecto antes de restaurar.
- `scripts/create_snapshot_divergence_validation_project.py` crea dos casos descartables para validar ambas decisiones.

**Validada manualmente en 0.61.0.** Las dos rutas produjeron `repair_adopt_current_row`, `repair_capture_divergent_row` y `repair_restore_snapshot`, conservaron la fila divergente antes de restaurar el historial y dejaron cero alertas, integridad `ok` y claves foráneas válidas.

### Conjuntos coincidentes y reubicaciones agrupadas — fase 6, 0.62.0

- Los conjuntos de tres o más menciones sobre la misma ubicación se presentan una sola vez como `duplicate_group`.
- La interfaz muestra todas las menciones y exige elegir una única ganadora; no permite decisiones binarias parciales.
- Las perdedoras agregan `repair_group_duplicate_rejected`; la ganadora agrega `repair_group_duplicate_relocated` si era histórica o `repair_group_duplicate_kept` si ya estaba vigente.
- Las reubicaciones seguras del mismo objeto pueden aplicarse juntas mediante `repair_group_relocation`.
- Antes de escribir, ambas operaciones vuelven a verificar revisiones, snapshots, revisión textual, offsets y composición exacta del conjunto; cualquier cambio cancela la transacción completa.
- `scripts/create_grouped_mention_validation_project.py` crea un conjunto de tres menciones y tres reubicaciones seguras agrupables en una copia descartable.

**Validada manualmente en 0.62.1.** La prueba confirmó las tres reubicaciones seguras agrupadas, la elección de una única mención ganadora, el rechazo auditable de las otras dos, cero alertas restantes, integridad `ok` y ausencia de claves foráneas inválidas. DATA-01 queda cerrado: todas las reparaciones conservan snapshots y agregan revisiones nuevas sin reescritura silenciosa.

## Calidad y análisis

- Estados de calidad de página y evaluación de corridas.
- Exportación, búsqueda literal, búsqueda semántica y sugerencias por diccionario respetan filtros de calidad.
- Índices se marcan como pendientes de reconstrucción cuando cambia el corpus.

### Política común de alcance automático — fase 1, 0.63.0

- `analysis_quality.py` concentra estados válidos, alcance predeterminado y mensajes de calidad.
- El alcance seguro para análisis automático es únicamente `approved`.
- Los perfiles nuevos de exportación y búsqueda semántica comienzan con páginas aprobadas.
- Un perfil ampliado debe confirmarse explícitamente al guardar; el botón permanece disponible y la validación ocurre al enviar para evitar bloqueos circulares de `st.form`.
- La búsqueda automática de menciones muestra el alcance, advierte cuando se amplía y exige confirmación antes de comenzar.
- Los estados seleccionados permanecen registrados en perfiles y snapshots reproducibles.

La obligatoriedad programática, la auditoría persistente y el contrato para análisis futuros se completan en la fase 2 de 0.64.0.

### Política común, obligatoria y auditable — fase 2, 0.64.0

- El alcance seguro deja de ser solamente una convención de interfaz: `ExportProfileValues` y `SemanticProfileValues` usan `approved` como valor programático predeterminado.
- Ya no existe la ruta de compatibilidad que permitía un alcance ampliado sin autorización; otros estados o todos exigen confirmación explícita y un fundamento no vacío.
- Cada guardado de perfil de exportación, perfil semántico o búsqueda automática de menciones agrega una fila append-only en `automatic_analysis_authorizations`.
- La previsualización y ejecución de exportaciones y las operaciones semánticas verifican una autorización que coincida con la huella de los parámetros funcionales actuales; una autorización vieja no habilita silenciosamente una configuración modificada.
- Los perfiles existentes antes de la migración deben guardarse nuevamente para registrar su primer alcance autorizado; no se fabrican consentimientos retrospectivos.
- La autorización registra política, tipo de análisis, estados de página, responsable, fundamento, origen, destino y hash canónico de parámetros.
- La migración `0034_automatic_analysis_authorizations` crea el registro sin modificar perfiles, índices, menciones ni autorizaciones históricas inexistentes.
- La interfaz incorpora **Administrar y recuperar → Auditoría de análisis** y la terminal agrega `analysis-quality-audit`.
- El registro común declara contratos para exportación, índice semántico, sugerencias, resúmenes, estadísticas, descubrimiento abierto, importaciones asistidas, herramientas LLM, RAG e integraciones. Una implementación futura debe usar un tipo registrado o falla de manera explícita.
- `.assistant/06_RELEVO_NUEVA_CONVERSACION.md` prepara la continuidad sin reconstruir decisiones desde conversaciones antiguas.

La implementación funcional de `DATA-02` quedó completa en 0.64.0 y la corrección del botón se incorporó en 0.64.1.

**Validada manualmente en 0.64.1.** La interfaz registró las autorizaciones ampliadas de exportación, índice semántico y sugerencias de menciones con origen `ui`, responsable `alex`, estados `reviewed,approved`, fundamentos y huellas SHA-256. `analysis-quality-audit` mostró los tres tipos esperados; la comprobación directa devolvió tres autorizaciones ampliadas, revisión `0034_automatic_analysis_authorizations`, integridad `ok` y ninguna clave foránea inválida. `DATA-02` queda cerrado y retirado de los pendientes activos.

## Exportación

**Implementado y validado en 0.49.1:**

- perfiles con agrupación, texto, formatos y filtros;
- vista previa con registros y caracteres;
- CSV y JSONL reproducibles;
- historial con ruta, tamaño, estado y SHA-256;
- prevención de sobrescritura implícita;
- confirmación persistente y descarga directa;
- archivar, restaurar y eliminar perfiles sin borrar archivos ni historial.

## Backups y recuperación

**Resuelto y validado en 0.48.0:**

- creación y listado cronológico por fecha real del manifiesto;
- verificación de estructura, checksums y SQLite;
- prueba de recuperación no destructiva;
- restauración real con backup automático previo;
- indicación explícita de `db-upgrade` posterior;
- integridad y claves foráneas verificadas;
- recuperación del estado esperado sin conservar cambios posteriores al backup.

## Intercambio offline

- copias reidentificadas y puntos de control;
- exportación incremental de paquetes;
- inspección, simulación y reportes;
- reconocimiento de ascendencia aunque existan cambios locales posteriores;
- aplicación transaccional con backup;
- registro de dos paquetes aplicados y coexistencia de cambios remotos y locales;
- bloqueo de simulaciones obsoletas antes de crear backups;
- archivo, restauración y limpieza de entradas no aplicadas;
- presentación segura de paquetes sin base común, con tres eventos y 21 campos;
- aceptación masiva recibida deshabilitada para creaciones sin base verificable.

### Diagnóstico de evidencia de linaje — EX-01A, 0.65.0

**Implementado y validado manualmente.**

- trabaja únicamente sobre paquetes activos cuya simulación quedó `unmatched`;
- lee la SQLite vigente y el paquete recibido sin crear casos, decisiones, puntos de control ni reportes persistentes;
- inspecciona solamente paquetes, manifiestos y backups adicionales indicados explícitamente;
- reconoce punto exacto, aplicación anterior, backup íntegro de la misma copia y cadenas continuas de paquetes;
- clasifica como recuperable, ambiguo o insuficiente y explica cada evidencia concluyente, de apoyo o rechazada;
- rechaza checksums inválidos, proyecto diferente, copia de origen incompatible, ciclos y bifurcaciones;
- expone `exchange-lineage-diagnose` y un panel de solo lectura en Intercambiar cambios.

La validación manual confirmó por terminal e interfaz que el caso sin evidencia quedaba insuficiente, que un manifiesto aislado seguía siendo solo apoyo y que la cadena íntegra producía un único candidato `verified_bundle_chain`. La comprobación directa confirmó ausencia de tablas o filas de escritura de `EX-01`, revisión `0034_automatic_analysis_authorizations`, integridad `ok` y claves foráneas válidas.

### Recuperación append-only de linaje — EX-01B, 0.66.0

**Implementada y validada manualmente.**

- agrega la migración `0035_exchange_lineage_recovery` con casos, evidencias y decisiones append-only separadas de los eventos de contenido;
- persiste el método con el que cada simulación reconoce su base mediante `base_match_method`;
- solo permite recuperar un paquete `unmatched` cuando el diagnóstico produce una cadena concluyente, única y sin contradicciones;
- exige responsable, fundamento, confirmación explícita y conserva un SHA-256 de los parámetros funcionales;
- registra todas las evidencias examinadas y marca cuáles sustentan la decisión;
- impide una segunda recuperación sobre el mismo paquete;
- vuelve obsoleta la simulación anterior y obliga a repetirla;
- permite que la nueva simulación reconozca la base mediante `recovered_lineage`;
- no modifica páginas, objetos, autoridades, menciones, relaciones ni eventos de contenido;
- expone `exchange-lineage-recover`, `exchange-lineage-recoveries` y un formulario Streamlit con `enter_to_submit=False` y validaciones posteriores al envío.

La validación manual confirmó una única recuperación `verified_bundle_chain` sobre `baseline_ex01a`, con responsable y fundamento persistidos. La simulación anterior quedó obsoleta y la reevaluación reconoció la base mediante `recovered_lineage`, produjo el conflicto esperado y no aplicó ningún cambio al estado editable.

### Acuerdo bilateral de base común con estado idéntico — EX-01C, 0.67.0

**Implementada y validada manualmente.**

- agrega la migración `0036_exchange_common_base_agreements` con un registro append-only local del mismo acuerdo bilateral en cada copia;
- divide el recorrido en propuesta, aceptación por la contraparte y finalización por la copia iniciadora;
- transporta propuesta y acuerdo en ZIP verificables con manifiestos JSON 1.0 y checksums SHA-256;
- exige proyecto común, identidades de copia distintas y el mismo SHA-256 del estado editable;
- bloquea la aceptación si la contraparte, el proyecto o el estado no coinciden y bloquea la finalización si la iniciadora cambió desde la propuesta;
- registra en ambos lados el mismo `agreement_id`, la misma huella del manifiesto y puntos de control locales con la etiqueta `common_base_<id>`;
- vuelve obsoletas las simulaciones anteriores y permite reconocer paquetes posteriores mediante `common_base_agreement`;
- no modifica páginas, objetos, autoridades, menciones, relaciones ni texto editable;
- expone los comandos `exchange-common-base-propose`, `exchange-common-base-accept`, `exchange-common-base-finalize` y `exchange-common-base-agreements`;
- incorpora formularios Streamlit con `enter_to_submit=False`, botones siempre habilitados y validación posterior al envío;
- incorpora `create_common_base_validation_projects.py` para crear dos copias descartables con identidades distintas y estado idéntico.

La validación manual confirmó que ambas copias registraron el mismo identificador de acuerdo, manifiesto, SHA-256 editable y punto `common_base_…`, con roles `initiator` y `counterpart`. Un paquete posterior sin eventos fue reconocido mediante `common_base_agreement`, quedó `empty` y no modificó el estado editable.

### Adopción explícita de estado divergente — EX-01D, 0.68.0

**Implementada y validada manualmente.**

- agrega la migración `0037_exchange_state_adoptions` con adopciones y rollbacks append-only;
- crea un ZIP verificable del estado editable completo, dirigido a una contraparte concreta y vinculado a la base documental compartida;
- presenta una vista previa de solo lectura con altas, bajas y cambios por sección;
- exige responsable, fundamento y confirmación explícita tanto para crear el paquete como para adoptarlo;
- crea un backup verificable antes de escribir y reemplaza transaccionalmente el estado editable;
- verifica SHA-256 final, integridad SQLite y claves foráneas antes de confirmar la operación;
- invalida simulaciones anteriores y no activa por sí sola una base común;
- permite restaurar el backup previo mediante un rollback explícito, que crea además un backup de seguridad del estado posterior;
- bloquea el rollback si el estado cambió desde la adopción, si ya fue revertida o si un acuerdo bilateral ya utiliza ese estado;
- expone `exchange-state-package-create`, `exchange-state-adoption-preview`, `exchange-state-adopt`, `exchange-state-adoptions` y `exchange-state-adoption-rollback`;
- incorpora el panel **Reconciliar estados divergentes** y `create_state_adoption_validation_projects.py`.

La validación manual confirmó la vista previa sin escritura, la primera adopción con backup, la igualdad de hashes, el rollback, una segunda adopción definitiva, el acuerdo bilateral posterior y el reconocimiento de un paquete final mediante `common_base_agreement`. Ambas bases conservaron revisión `0037_exchange_state_adoptions`, integridad `ok` y claves foráneas válidas. `project_data` fue respaldada y migrada a la misma revisión; la aplicación abrió y las pruebas OCR continuaron visibles.

**EX-01 queda cerrado en 0.68.1.** El diagnóstico, la recuperación, el acuerdo bilateral y la adopción reversible quedaron validados sin convertir resoluciones de contenido en parentesco implícito.

## Integridad y migraciones

### Migración 0027

**Resuelta y validada en 0.49.1.** La regresión parte de `0026_team_workflow` y conserva:

- UUID de autoridades;
- alias;
- snapshots append-only;
- una mención aceptada vinculada;
- una relación entre autoridades;
- claves foráneas hasta `0033_export_exchange_lifecycle`.

También pasaron las rutas desde 0031 y 0032 y el archivo completo `tests/test_database.py`. No debe reabrirse como bloqueante sin una regresión concreta.

### Integridad posterior

Las bases descartables de rebase, intercambio receptor y paquete sin base común devolvieron:

```text
integrity_check: ok
foreign_key_check: []
```

## Interfaz y formularios

### Principio permanente para toda modificación — 0.70.1–0.70.2

Toda nueva versión debe releer y aplicar esta sección y `.assistant/05_CRITERIOS_INTERFAZ.md` antes de agregar o modificar capacidades. La interfaz no debe volver a complejizarse por acumulación: el recorrido principal permanece visible y breve; configuraciones, historiales, parámetros y datos técnicos se muestran mediante divulgación progresiva; los paneles secundarios nuevos quedan cerrados por defecto; y no se duplican controles ni explicaciones.

Los paneles que contienen controles reactivos deben conservar su apertura durante los reruns de Streamlit. Los `st.expander` quedan reservados para contenido informativo, historiales o detalles técnicos; un flujo interactivo usa un estado persistente con clave estable o un recorrido explícito por pasos. Cambiar una decisión, un destino o un filtro no debe cerrar el panel activo ni hacer perder el contexto.

Esta obligación rige desde el diseño de cada cambio y se verifica en sus pruebas de navegación. `UX-02` realizará una revisión integral al final de los bloques funcionales activos y antes de la candidata a v1.0, sin postergar la corrección de regresiones concretas.

En 0.88.0, **Exportar corpus > Crear archivo** conserva una sola elección principal de salida. **Exportar texto e imágenes (ZIP)** usa lenguaje orientado a la tarea; las variantes de páginas, recortes y figuras sólo aparecen al activar **Elegir qué imágenes incluir**, mediante un control persistente y cerrado por defecto. El contexto textual adicional no agrega controles técnicos a la pantalla.

### Orientación y lenguaje claro — fase 1, 0.51.0

- La barra lateral presenta secciones como tareas y explica brevemente para qué sirve cada una.
- Inicio muestra el recorrido recomendado con los mismos nombres visibles.
- Intercambio usa “paquete de intercambio”, “simulación”, “punto de control” y “copia de seguridad” en las acciones principales.
- Los estados técnicos permanecen disponibles en un desplegable separado, sin dominar la pantalla principal.

Esta fue la primera de seis fases; la revisión general quedó completada y validada en 0.56.0.

### Recorrido guiado y lenguaje claro — fase 2, 0.52.0

- El circuito completo se organiza en cinco etapas y once pasos, sin retirar ninguna sección.
- La barra lateral permite ir a la sección anterior o siguiente.
- La orientación contextual es opcional y explica objetivo, requisitos y paso habitual siguiente.
- Administración usa “copia de seguridad” en todo el recorrido principal y oculta el comando técnico de restauración hasta abrir su desplegable.
- Exportar explica `JSONL` como un registro por línea y `CSV` como tabla.

Esta fue la segunda de seis fases; la revisión general quedó completada y validada en 0.56.0.

### Búsquedas comprensibles — fase 3, 0.53.0

- Buscar texto muestra primero la consulta y la forma de combinar palabras.
- Todos los filtros anteriores se conservan dentro de `Filtros opcionales`.
- La reconstrucción y la generación del índice literal quedan en desplegables técnicos.
- Buscar por significado separa consulta, opciones, estado técnico, contenido incluido y configuración del índice.
- CPU y CUDA se presentan como procesador y placa NVIDIA, sin cambiar los valores internos.

Esta fue la tercera de seis fases; la revisión general quedó completada y validada en 0.56.0.

### Catálogo y procesamiento más legibles — fase 4, 0.54.0

- Buscar dentro de las palabras pasa a ser una opción principal junto con la combinación de términos.
- Catálogo deja visible la búsqueda general y agrupa resumen, filtros y datos internos de la unidad.
- Procesamiento presenta las acciones como tareas, agrupa el resumen de avance y relega la repetición forzada a opciones avanzadas.
- Se conservan todos los campos, filtros, operaciones, perfiles, candidatos e historiales existentes.

**Implementada y validada manualmente en 0.54.0.**

### Revisión, entidades y relaciones más legibles — fase 5, 0.55.0

- Revisión conserva documento, página y objeto como recorrido principal, y agrupa visualización, resumen, exportación, estado de página, deshacer/rehacer y datos del objeto.
- Las tareas del objeto se nombran como editar texto, ordenar y estructurar, anotar, revisar datos adicionales y gestionar menciones.
- Entidades deja visible la búsqueda general y separa filtros, resumen, explicación conceptual y opciones de búsqueda de menciones.
- El grafo se presenta como mapa de relaciones, usa “elementos” y “vínculos” en la interfaz principal y mantiene identificadores y pesos dentro de detalles técnicos.
- No cambia la persistencia, la lógica de revisión, las relaciones ni la construcción del grafo.

**Implementada y validada manualmente en 0.55.0.** La revisión final de densidad, legibilidad y recorridos de trabajo se completó en 0.56.0.

### Legibilidad final de datos, trabajo y exportación — fase 6, 0.56.0

- Los datos del objeto seleccionado usan tarjetas de texto que permiten envolver valores largos; “Sin revisar” y los demás estados ya no quedan recortados con puntos suspensivos.
- Los estados de ciclo de vida del objeto se presentan como “Activo” y “Eliminado”.
- Organización del trabajo separa el resumen principal de la carga por responsable, el avance documental y los filtros de asignaciones.
- Exportar organiza el recorrido como configurar perfil, revisar contenido y crear archivo; identificadores y huellas verificables quedan disponibles en detalles técnicos.
- No cambia estados, asignaciones, perfiles, archivos ni reglas de exportación.

**Implementada y validada manualmente en 0.56.0.** No se detectaron recortes ni pérdida de controles; `UX-01` queda cerrado con sus seis fases validadas.

- Navegación persistente por vista y pestaña.
- Fragmentos autocontenidos y separación entre rerun local y navegación completa.
- Ausencia validada del remanente visual oscuro después del rebase.
- Formularios con `enter_to_submit=False`.
- Botones que validan sus propias casillas al enviar, sin bloqueo circular.
- Mensajes `Press Enter…` y `Press Ctrl+Enter…` ocultos.
- Pruebas AST para impedir regresiones de formularios y confirmaciones.

**UX-01 queda cerrado:** el recorrido completo mantiene todas las funciones y presenta navegación, orientación, léxico y detalles técnicos con jerarquía progresiva. Las mejoras futuras de pantallas concretas se registrarán como tareas nuevas y acotadas, no como reapertura de este bloque general.

## Organización documental

**Implementada en 0.50.0:**

- una única lista de pendientes activos;
- un único registro de implementaciones realizadas;
- guía de actualización vigente con nombre estable;
- documentación histórica separada por tipo;
- arquitectura actual separada del diseño histórico;
- carpeta oculta `.assistant/` con instrucciones de continuidad;
- pruebas que impiden volver a ensuciar la raíz de `docs/` o duplicar documentos operativos.
