## 0.89.0 RC72-RC84 - 2026-08-25/09-04
RC72 inició la distribución administrada; RC73 separó CPU/GPU; RC74 corrigió las bibliotecas de `llama-server`; RC75 abrió proyectos locales desde el anfitrión; RC76 alineó el preflight y el entorno real de Surya/llama.cpp y corrigió la continuidad visual de pestañas; RC77 agregó guardas de inferencia y quedó validado materialmente en CPU/GPU; RC78 alinea `extraction-doctor` con el llama.cpp CUDA incluido, sin exigir Docker anidado; RC79 registra la transcripción `large-v3` CUDA material y corrige la medición de VRAM dentro del espacio de nombres PID de Docker; RC80 corrige el primer fallo de publicación CPU ARM64 forzando PyTorch CPU también en el runtime principal; RC81 publica la candidata Windows con BOM, puerto host seguro, readiness IPv4, OAuth Drive administrado y reducción de observers globales; RC82 completa el cliente OAuth de escritorio, registra el proyecto al crearlo, serializa Alembic, tolera copias audiovisuales sin originales y elimina el patrón N+1 del inventario documental; RC83 corrige el doble clic en pestañas sin rerun, permite adoptar una copia completa dentro de un proyecto vacío desde la propia app y agrega cierre explícito de la instancia administrada; RC84 convierte el retorno OAuth/Picker de Google Drive en una sesión auxiliar terminal que no cae en el launcher. Sin migración; continúa `0047_authority_relation_profiles`.
## 0.89.0 RC65-RC71 - 2026-08-24/25
RC65-RC69 cerraron el piloto y `DISC-03`; RC70 cerró la revisión final de complejidad y RC71 inicia `WEB-01` con sitio público multipágina, tutorial, diagramas y README renovado. Sin migración, continúa `0047_authority_relation_profiles`.
## 0.89.0 RC63-RC64 - 2026-08-24
RC63 abrió la reparación transversal de conformidad Streamlit después del cierre manual de `PILOT-01E`; su primera validación expuso tracebacks y estados no inicializados. RC64 supersede esa candidata reparando Grafo, Exportar corpus, Revisar documentos, Búsqueda textual y Búsqueda semántica y agrega un guardrail específico para toggles reactivos dentro de formularios. `PILOT-01AE` sigue abierto hasta validación manual; sin migración, continúa `0047_authority_relation_profiles`.
## 0.89.0 RC62 - 2026-08-24
RC62 agrega la aclaración visible de formatos locales a Audio y video, derivada de `AUDIO_EXTENSIONS`/`VIDEO_EXTENSIONS`; no cambia registro, reproducción, transcripción ni persistencia y continúa `0047_authority_relation_profiles`.
## 0.89.0 RC61 - 2026-08-24
- Reorganiza audiovisual como **Audio y video**: incorporación local/plataforma unificada, transcripción/revisión separada, circuito canónico de Catálogo y navegación sin rerun forzado; sin migración.
## 0.89.0 RC60 - 2026-08-24
- Auditoría final en cinco pasadas de `PILOT-01E`; corrige residuos de referente/jerarquía y mantiene el cierre sujeto a recorrida manual; sin migración.
## 0.89.0 RC45-RC50 - 2026-08-23
- RC45-RC46 completaron Búsqueda semántica; RC47-RC49 cerraron mejoras visuales del grafo; RC50 normaliza exportación audiovisual y hace más autoexplicativo el contrato JSONL/CSV documental.
- Sin migración; continúa `0047_authority_relation_profiles`.
# Historial de cambios y mapa documental
Este es el mapa Markdown interno de la documentación. La raíz de `docs/` contiene además los archivos públicos del sitio de GitHub Pages. Resume la evolución del proyecto y señala dónde encontrar el detalle sin duplicarlo.
## Documentación vigente
- [Pendientes activos](operativos/PENDIENTES_ACTIVOS.md): único inventario de tareas abiertas.
- [Implementaciones realizadas](operativos/IMPLEMENTACIONES_REALIZADAS.md): funciones cerradas y validaciones.
- [Actualización actual](operativos/ACTUALIZACION_ACTUAL.md): instalación y pruebas de la versión vigente.
- [Estrategia de pruebas](operativos/ESTRATEGIA_DE_PRUEBAS.md).
- [Guía de prueba piloto](operativos/GUIA_PRUEBA_PILOTO.md).
- [Hoja de ruta pre-release](operativos/HOJA_DE_RUTA_PRE_RELEASE.md).
- [Arquitectura y modelo actual](referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md).
- [Plan de recuperación de linaje EX-01](referencia/RECUPERACION_LINAJE_EX_01.md).
- [Plan de descubrimiento abierto DISC-01](referencia/DESCUBRIMIENTO_ABIERTO_DISC_01.md) y [formato de importación DISC-02](referencia/IMPORTACION_DICCIONARIOS_DISC_02.md).
- [Proyecto paralelo GIAR](referencia/PROYECTO_PARALELO_GIAR.md).
## Versiones recientes — más reciente primero
## 0.89.0 RC59 - 2026-08-24
- Cierra por validación manual `PILOT-01AD`: estabilidad entre pestañas e identidad independiente de documentos homónimos en Procesar documentos.
- Cierra `PILOT-01I`: Surya reutiliza `VLLM::EngineCore` durante un lote y lo libera automáticamente al finalizar, igual que en la extracción individual ya validada.
- Cierra `PILOT-01L` con contrato público PDF/TIFF/PNG/JPEG/WebP; BMP pasa a `MediaType.OTHER` y queda rechazado para derivados documentales.
- Centraliza la lista de formatos admitidos entre Inspección y Catálogo y agrega regresiones de preparación raster.
- Sin migración; continúa `0047_authority_relation_profiles`.
## 0.89.0 RC58 - 2026-08-24
- Cierra `PILOT-01AC` y `PILOT-01P` por validación manual; backup y prueba no destructiva de recuperación también quedan verdes.
- Registra como validada la liberación automática de VRAM después de una extracción individual con Surya; `PILOT-01I` queda pendiente sólo del lote.
- Corrige `Procesar documentos`: las pestañas no fuerzan un rerun completo al cambiar de panel y los selectores usan identidad estable por objeto digital con rótulos homónimos desambiguados.
- Corrige el formulario de conservación de edición para validar la confirmación después del submit, conforme a la política Streamlit.
- Sin migración; continúa `0047_authority_relation_profiles`.
## 0.89.0 RC57 - 2026-08-24
- Cierra `PILOT-01AB` por validación manual de RC56 y mueve el piloto a Administración antes de backup/recuperación.
- Hace accionables los diagnósticos de Integridad, subordina revisión de base e IDs técnicos y agrega descarte reversible de avisos no bloqueantes.
- Respeta omisiones deliberadas de originales/exportaciones en copias configurables y agrega búsqueda/filtros a Autorizaciones de análisis.
- No agrega migración; continúa `0047_authority_relation_profiles`.

## 0.89.0 RC56 - 2026-08-24
- Elimina `Más opciones` del selector principal de `Intercambiar cambios` e integra Google Drive en Enviar/Recibir/Preparar copia.
- Aplica divulgación progresiva en `Recibir cambios`: abrir otro ZIP, archivar, eliminar, recuperación y resolución masiva aparecen sólo al solicitarlos.
- Presenta una diferencia por vez y mantiene las herramientas de recuperación en un recorrido excepcional explícito.
- No agrega migración; continúa `0047_authority_relation_profiles`.

## 0.89.0 RC55 - 2026-08-24
- Reorganiza `Intercambiar cambios` después de validar funcionalmente el intercambio incremental completo.
- `Más opciones` deja de competir con el recorrido principal y Google Drive muestra sólo Subir o Recibir a la vez.
- Distingue estados persistentes de resultados de acciones y relega hashes, rutas, IDs y comparaciones técnicas a detalles secundarios.
- No agrega migración; continúa `0047_authority_relation_profiles`.

## 0.89.0 RC54 — 2026-08-23
- Hace configurable la copia inicial para trabajo en equipo mediante perfiles Completa, Para revisión y catalogación y Personalizada, con tamaño estimado y omisiones explícitas en el manifiesto.
- Mantiene SQLite y configuración como núcleo obligatorio y permite omitir grupos pesados o regenerables, incluidos los originales.
- Agrega selectores de ZIP en los recorridos de recepción y herramientas avanzadas sin eliminar la elección directa de archivos ya conocidos por el proyecto.
- Google Drive transporta copias iniciales y paquetes incrementales; la subida pasa a sesiones reanudables por bloques y la descarga se escribe de forma incremental y atómica.
- No agrega migración; continúa `0047_authority_relation_profiles`.

## 0.89.0 RC53 — 2026-08-23
- Corrige el traceback `BadZipFile` al subir un archivo inválido desde Google Drive.
- Google Drive preselecciona únicamente paquetes incrementales válidos y distingue las copias completas para iniciar trabajo en equipo.
- No agrega migración; continúa `0047_authority_relation_profiles`.

## 0.89.0 RC52 — 2026-08-23
- Simplifica el intercambio normal a preparar una copia de trabajo, enviar cambios y recibir cambios.
- Un mismo ZIP inicial puede distribuirse a varias personas; cada copia se reidentifica automáticamente al abrirse por primera vez y conserva la misma huella de base.
- Enviar cambios deja de pedir contraparte y checkpoint; los acuerdos bilaterales y la adopción completa quedan como herramientas excepcionales.
- No agrega migración; continúa `0047_authority_relation_profiles`.

## 0.89.0 RC51 - 2026-08-23
RC51 cierra por validación manual la exportación RC50 y la pasada de asignación/revisión cruzada, y corrige dos hallazgos del piloto en `Intercambiar cambios`: explica la base común como punto en que dos copias contienen el mismo trabajo editable y agrega la creación del paquete incremental dentro de la propia interfaz usando el dominio de intercambio existente. Sin migración; continúa `0047_authority_relation_profiles`.
## 0.89.0 RC43 - 2026-08-22
RC43 reorganiza el descarte/restauración audiovisual según la jerarquía UI vigente: elimina `Opciones de esta transcripción`, deja el trabajo normal primero y relega descarte e historial de versiones descartadas a expanders explícitos y cerrados. Sin migración; continúa `0047_authority_relation_profiles`.
## 0.89.0 RC41-RC42 - 2026-08-22
RC41 cerró `PILOT-01T`, agregó descarte/restauración audiovisual y compatibilidad `Familia` en el grafo; RC42 reemplazó los popovers comprimidos de Búsqueda textual y Explorar relaciones por paneles inline de ancho completo. Sin migración; continúa `0047_authority_relation_profiles`.

## 0.89.0 RC31-RC40 - 2026-08-21
RC31 incorporó perfiles descriptivos estructurados, temporalidad discontinua y `0047_authority_relation_profiles`; RC32 estabilizó intercambio y compatibilidad histórica. RC33-RC34 agregaron plantillas bidireccionales, árbol de catálogo, descarte de roles erróneos y calendarios amplios. RC35-RC40 iteraron sobre la regresión Menciones -> Revisar documentos; RC40 recuperó selección bbox/bloque con rerun local de fragmento y quedó validado manualmente. El detalle de cada candidata permanece en `CHANGELOG.md` e implementaciones realizadas.

## 0.89.0 RC27-RC30 - 2026-08-21
RC27-RC29 cerraron la orientación contextual y tooltips de `UX-04`; RC30 registró su validación manual, retiró el rodeo de pendientes y devolvió el piloto a su recorrido funcional. Sin migración; se mantuvo `0046_audiovisual_timeline_annotations` hasta RC31.
## 0.89.0 RC26 - 2026-08-21
RC25 quedó validada manualmente como una mejora material de `Procesar documentos`. RC26 aplica los ajustes finales de `UX-04`: muestra `Ruta archivística` por defecto en Estado, compacta `Corregir o agregar`, incorpora ayuda contextual `?` en recorridos complejos, rediseña `Revisar documentos > Orden y estructura` para mostrar un único flujo por vez y evita el rerun completo al cambiar las pestañas de revisión mediante la modalidad ya existente `tracked_tabs(..., rerun_on_change=False)`. No hay migración y la revisión permanece en `0046_audiovisual_timeline_annotations`. `UX-04` sigue abierto hasta la validación manual focal de RC26.
## 0.89.0 RC25 - 2026-08-21
La validación transversal de RC24 fue favorable en principio salvo `Procesar documentos`, que continuó demasiado cargado en todas sus pestañas. RC25 realiza una segunda pasada focal: acorta la navegación a siete tareas, reduce columnas y métricas permanentes, compacta preparación/extracción, vuelve central la imagen en lectura regional, simplifica comparación y control automático, muestra un solo recorrido cuando las alternativas son mutuamente excluyentes y compacta el historial. Conserva las funciones y las confirmaciones de escrituras materiales. No hay migración y la revisión permanece en `0046_audiovisual_timeline_annotations`. `UX-04` sigue abierto hasta validar manualmente esta sección.
## 0.89.0 RC24 - 2026-08-20
RC23 quedó validada como segunda etapa de `UX-04`. RC24 promueve los criterios aprobados a `.assistant/05_CRITERIOS_INTERFAZ.md` y ejecuta una pasada transversal de economía visual sobre las restantes secciones: elimina introducciones y paneles informativos redundantes, compacta búsqueda y filtros, refuerza la identidad del objeto activo, reduce métricas permanentes y evita capas simultáneas de navegación. Catálogo e Intercambiar cambios usan selectores de tarea para no acumular recorridos; Búsqueda textual y semántica, Grafo, Exportación, Organización, Revisión y Administración reducen superficies secundarias sin eliminar funciones. No hay migración y la revisión permanece en `0046_audiovisual_timeline_annotations`. `UX-04` sigue abierto hasta validación manual transversal.
## 0.89.0 RC23 / RC22 - 2026-08-20
RC22 abre el prototipo de `UX-04` en `Entidades y menciones` y la validación manual confirma una mejora material, incluido el cierre de `GRAPH-03`. RC23 conserva esos patrones y profundiza `Menciones`, `Relaciones` y `Buscar nuevas entidades en los textos`: menciones vinculadas primero, alcance de búsqueda en línea sin confirmaciones duplicadas, creación de relaciones cerrada por defecto, selector compacto de tareas de descubrimiento y trazabilidad técnica secundaria. No hay migración y la revisión permanece en `0046_audiovisual_timeline_annotations`.
## 0.89.0 RC21 - 2026-08-20
RC21 no modifica código funcional: registra la validación manual satisfactoria de RC20, cierra `PILOT-01O`, archiva la guía y el relevo de RC20 y deja el punto de continuidad del piloto en **Relaciones**. La etapa de Entidades y menciones queda cerrada para el recorrido actual; `DISC-03` continúa abierto como afinado pre-release de la detección sobre corpus diverso. No hay migración y la revisión permanece en `0046_audiovisual_timeline_annotations`.
## 0.89.0 RC20 - 2026-08-20
RC20 corrige tres regresiones localizadas detectadas al cerrar la validación de RC19: sincroniza el bbox resaltado y el selector de bloque mediante el callback previo al rerun del componente v2; reemplaza el expander reactivo de selección masiva por una pestaña estable con `st.form`, evitando reruns mientras se seleccionan referencias; y mueve `Referencias descartadas` a una pestaña propia. También registra en `.assistant/01_INTERACCION_Y_GUIADO.md` la obligación de confirmar en cada mensaje con cambios de código que se verificó la checklist. No hay migración; continúa `0046_audiovisual_timeline_annotations`.
## 0.89.0 RC19 - 2026-08-20
RC19 continúa PILOT-01 en `Entidades y menciones`: sincroniza bbox y selector en `Revisar documentos`; muestra como solo lectura los roles `producer`/`manager` provenientes de Catálogo; simplifica la revisión de referencias a **Aceptar** o **Descartar**, con corrección dentro de la aceptación, restauración append-only y acciones masivas confirmadas; y reescribe agrupamiento/continuidad en lenguaje de tarea. La validación previa de RC18 cierra `PILOT-01H`, `PILOT-01K` y `PILOT-01M`; `PILOT-01N` conserva la optimización post-release de OCR localizado bajo firmas y `DISC-03` abre el afinado pre-release de búsqueda de entidades. RC18 había agregado la checklist obligatoria y validado la arquitectura Streamlit recuperada por RC17 al descartar RC16 y volver al patrón RC7/RC8. No hay migración; continúa `0046_audiovisual_timeline_annotations`.
## 0.89.0 RC14 - 2026-08-16
RC14 corrige la instalación de candidatas que reubican archivos. El ZIP de RC13 ya respetaba la estructura documental, pero la copia por superposición no retiraba las copias antiguas existentes en el repositorio local. Se agrega un actualizador con manifiesto explícito, preflight SHA-256 y reconciliación limitada a las rutas conocidas, sin limpiar contenido local ajeno al paquete. No hay migración nueva.
## 0.89.0 RC13 - 2026-08-16
RC13 corrige la arquitectura de información de `Procesar documentos`: la interfaz refleja la secuencia real `preparar imágenes -> extraer texto -> elegir texto para revisar`, impide iniciar extracción sobre documentos sin una preparación vigente y mueve el reintento de páginas fallidas a una acción secundaria. Elimina la operación duplicada `Preparar páginas para revisión` y presenta el envío masivo como uso de un resultado de extracción como texto inicial en `Revisar documentos`. Los resultados de OCR de zona pueden reemplazar un bloque existente o agregar uno nuevo, con cajas clicables sobre la página y procedencia regional. Se retiran explicaciones negativas innecesarias fuera de los casos donde aclaran seguridad o alcance. Se corrige además la política documental: informes versionados de auditoría salen de `docs/operativos/` y pasan a `docs/historico/actualizaciones/`. No hay migración nueva; continúa `0046_audiovisual_timeline_annotations`. `PILOT-01E`, `PILOT-01G`, `PILOT-01H` y el nuevo `PILOT-01K` quedan parciales hasta validación manual.

### 0.89.0 RC12 - 2026-08-16
RC12 rehace la auditoría de interfaz después de que la prueba manual de RC11 encontrara referentes todavía implícitos. La nueva metodología exige que cada frase o control nombre su objeto aunque se lea fuera de contexto, amplía la revisión a componentes auxiliares y vuelve a recorrer Inicio, Catálogo, procesamiento, revisión, búsquedas, entidades, relaciones, exportación, intercambio, administración, audiovisual y organización de trabajo. Corrige de forma explícita los casos `una parte del trabajo`, `qué significa cada columna` y botones cuyo destino sólo se deducía por contexto. Se mantienen las funciones de RC11, no hay migración nueva y la revisión de base sigue en `0046_audiovisual_timeline_annotations`. `PILOT-01E` y `PILOT-01J` continúan parciales hasta validación manual sin guía externa.
### 0.89.0 - 2026-08-09
RC18 agrega `.assistant/00_CHECKLIST_CAMBIOS.md` como gate obligatorio antes de cualquier cambio, sin duplicar políticas: enlaza sus fuentes canónicas y exige consultar el invariante Streamlit. Mantiene sin cambios funcionales la solución de RC17, que descarta RC16, vuelve a RC15 como base y restablece la arquitectura de continuidad validada en RC7/RC8; también conserva una única vía para agregar texto faltante desde Procesar documentos. RC6 refuerza la continuidad frente a reruns sobre el contenedor real de Streamlit, rehace las paletas personalizadas, exige identidad antes de las vistas operativas y simplifica la evaluación audiovisual. También expone vocabulario esperado, `beam_size` y VAD para repetir de forma controlada la configuración histórica de `large-v3`; `PILOT-01B` a `PILOT-01E` conservan la validación abierta. RC7 corrige la causa estructural de nuevas inconsistencias de estado: elimina el fragmento global de la vista activa, conserva el contexto del reproductor en el navegador y separa el alcance de la asignación de hablantes. También reemplaza la tematización dinámica por CSS por temas nativos de Streamlit aplicados al iniciar la interfaz. La corrida controlada con el vocabulario esperado histórico vuelve a 78 segmentos y reproduce casi por completo la salida de referencia. RC8 corrige la regresión de arranque del componente v2 de continuidad de scroll introducida en RC7, eliminando dimensiones cero inválidas sin tocar la lógica audiovisual ni los datos del piloto. RC9 corrige la continuidad del reproductor al guardar la transcripción: evita que un `currentTime=0` transitorio durante el desmontaje/remonte sobrescriba el último tiempo y segmento válidos. RC10 inicia `Procesar documentos`, corrige la reutilización de una lectura secuencial de pyvips que hacía fallar los dos TIFF reales al generar OCR y preview, y ajusta el texto de la sección para explicitar documentos, versiones de texto y páginas sin metacomentarios sobre la interfaz. Tras la validación acumulada, `PILOT-01B`, `PILOT-01C` y `PILOT-01D` pasan a implementaciones realizadas. La validación real posterior confirma la reparación de ambos TIFF y una extracción Surya 5/5 sin advertencias ni fallos, por lo que `PILOT-01F` queda cerrado. Se abre `PILOT-01G` para inicialización masiva controlada por documento/lote y `PILOT-01E` incorpora la reducción de jerga técnica de `Extraer texto`; siguen abiertos `PILOT-01A`, `PILOT-01E` y `PILOT-01G`.
RC5 había agregado la primera estrategia de posición por vista, contraste/calendario histórico, selectores de faster-whisper y el pendiente `PILOT-01A` sobre colecciones y agrupaciones audiovisuales.
RC4 agrega Colección como nivel estándar, cambio validado de tipo de unidad y eliminación segura de unidades vacías; las plantillas anteriores pueden omitir niveles agregados posteriormente sin quedar inválidas.
RC3 continúa el cierre de la primera fase real de `PILOT-01` después de incorporar 138 originales: simplifica Inicio, refuerza temas y contraste, convierte Unidades del catálogo en pestaña, evita el rerun inmediato de las pestañas internas, exige selectores gráficos junto a campos de carpeta y agrega edición explícita de excepciones en lotes.
RC2 corrige el selector de carpeta del launcher, aplica paletas como temas completos y elimina la excepción de Streamlit al guardar preferencias, preservando nombre y paleta al entrar al proyecto.
RC11 replantea `Procesar documentos` y `Revisar documentos` a partir de la prueba manual: reemplaza el vocabulario opaco del OCR regional por `Trabajar una zona`, permite sustituir únicamente el texto de un objeto con un resultado regional parcial y agrega preparación masiva para revisión sin sobrescribir páginas ya inicializadas. También libera automáticamente los recursos de Surya al terminar la tarea, reordena y explica las pestañas de revisión y ejecuta cinco pasadas de auditoría de referentes con regresiones estáticas. `PILOT-01G`, `PILOT-01H`, `PILOT-01I` y `PILOT-01J` quedan parciales hasta validación manual. No hay migración nueva.
- `PILOT-01` detectó que la primera experiencia seguía dependiendo de CLI, YAML y textos demasiado técnicos. 0.89.0 agrega inicio general, creación y apertura de proyectos, preferencias de usuario, navegación revisada y una guía de sección que no pierde estado al navegar.
- Catálogo pasa a pestañas, agrega ejemplos en las planillas, edición guiada de la jerarquía, creación local de productores/gestores, estados en español, selección de archivos de `corpus/`, rangos de páginas sugeridos y continuidad hacia Procesar documentos sin comandos de terminal.
- Se incorpora un flujo de archivos por lote con revisión de unidad, relación y rango de páginas, reglas por carpeta y procesamiento independiente por archivo.
- Se corrige el movimiento jerárquico dentro de formularios y `init-project` deja de aceptar silenciosamente carpetas existentes.
- No hay migración nueva; continúa `0046_audiovisual_timeline_annotations`.
### 0.88.2 — 2026-08-08
Corrige la aplicación de plantillas cuando una unidad existente marcada `omitir` se usa como contexto jerárquico por `parent_local_id`; agrega `/corpus/` al `.gitignore` para los originales locales de PILOT-01. 0.88.1 había corregido previamente la primera importación sobre una base con `projects: 0`. No hay migración.
### 0.88.0 — 2026-08-08
EXP-01 RC1 agrega **Exportar texto e imágenes (ZIP)** al recorrido existente de exportación. El paquete incluye los registros del perfil, páginas fuente ancladas a la extracción que originó la capa editable, recortes regionales y figuras recortadas desde la geometría vigente. Un manifiesto conserva huellas, procedencia, revisión y vínculos. El contexto textual de página/documento se exporta por separado y distingue objetos principales de objetos usados sólo como contexto. No hay migración. La validación manual final confirmó 1 registro principal, 1 página, 1 recorte regional, 1 figura y 2 objetos de contexto; el verificador comprobó huellas internas, originales intactos, `quick_check: ok`, cero violaciones FK y la separación entre contenido principal y contexto. `project_data` permaneció fuera del recorrido y sin cambios. EXP-01 queda cerrado.
### 0.87.0 — 2026-08-08
Implementa y valida `INT-01`: Google Drive actúa únicamente como transporte opcional de bundles del intercambio existente. La conexión usa OAuth de escritorio con `drive.file`; la subida valida el ZIP y registra SHA-256 e identidad del bundle; Google Picker selecciona un archivo concreto; la descarga es atómica, vuelve a verificar el paquete y compara su manifiesto antes de habilitar el dry-run existente. RC1 expuso una configuración incompleta en el generador descartable y RC2 la corrigió. La prueba real confirmó OAuth, subida, Picker, descarga con SHA-256 idéntico y dry-run `empty/matched` entre dos copias descartables, sin modificar `project_data`. No hay migración y la revisión continúa en `0046_audiovisual_timeline_annotations`. `INT-01` queda cerrado.
### 0.86.0 — 2026-08-07
Inicia AV-03 con métricas reproducibles de rendimiento/segmentación, selección de corridas, muestra determinista de corrección revisada y exportación JSON. Conserva tiempo, CPU, RAM y VRAM observada dentro de la corrida; RC2–RC4 estabilizan un editor continuo para revisión manual. RC5 agrega la migración aditiva `0046_audiovisual_timeline_annotations` para hablantes y anotaciones temporales independientes de la corrida, con autoridad opcional, historial y vista integrada. RC6 reemplaza la selección manual de tramos por una revisión sincronizada junto al reproductor, con avance automático del segmento, salto al pulsar el texto y creación de marcas desde el tiempo actual. RC7 ejecuta `large-v3` GPU sobre el video real; RC8 separa salida automática y corrección revisada pero introduce una alineación local demasiado optimista. RC12 elimina ese sesgo: CER/WER sólo se publican con ventanas temporalmente comparables y las corridas con otra segmentación se inspeccionan mediante su contexto original y su transcripción completa. La validación final confirma el flujo completo y la lectura cualitativa de las dos salidas completas identifica al perfil probado `large-v3` + CUDA como superior a `small` + CPU para este material, aunque más costoso y todavía sujeto a revisión manual. AV-03 queda cerrado.
### 0.85.0 — 2026-08-07
- Incorpora una extensión opcional `platform` basada en `yt-dlp` para audio/video autorizado desde plataformas.
- Conserva procedencia remota y SHA-256 en el registro de fuente existente y entrega el archivo al circuito AV-01.
- Agrega un panel de incorporación cerrado por defecto y amplía la exportación audiovisual con campos de procedencia.
- No agrega migración; continúa `0045_audiovisual_transcription`. La validación real con `RememorArte Horacio BAU` confirmó procedencia/SHA-256/reproducción y ausencia de transcripción automática; RC2 corrigió además la exposición de errores técnicos de validación en la UI. `AV-02` queda cerrado.
### 0.84.0 — 2026-08-07
Implementa y valida `AV-01` para registro local de audio y video, inspección FFprobe, derivados FFmpeg trazables, transcripción segmentada con backend intercambiable y recorrido CPU, corrección append-only, reproducción con velocidad variable, salto a segmentos, búsqueda con navegación directa, entidades, exportación y transporte del estado audiovisual. Agrega la migración `0045_audiovisual_transcription` y excluye audio/video del circuito OCR. La validación manual confirmó ambos medios, persistencia de correcciones, mención, exportación y una corrida `faster-whisper` real en CPU. RC1 reveló fallos en salto temporal y navegación desde búsqueda; RC2 los corrigió y la revalidación fue satisfactoria. `AV-01` queda cerrado.
### 0.83.0 — 2026-08-07
Implementa y valida `OCR-01F`: benchmark reproducible de Tesseract, Docling y Surya sobre los mismos derivados y verdad terreno. La ejecución real controlada obtuvo CER 0.0000 y WER 0.0000 con los tres motores, conservó tiempos, versiones, perfiles, textos, salidas crudas y copia verificable de la referencia, mantuvo intacto el TIFF original y no modificó la selección canónica. Con este cierre, `OCR-01A` a `OCR-01F` quedan implementadas y validadas. No hay migración; la revisión permanece en `0044_layout_structure_review`.

### 0.82.0 — 2026-08-07
Implementa `OCR-01E` con dewarp conservador sobre derivados OCR. La página se analiza por franjas verticales, la curvatura se ajusta mediante una curva reproducible y el remapeo se aplica solo con soporte y confianza suficientes. Agrega un diagnóstico separado, trazabilidad completa y una base descartable con página curva y plana. No modifica el esquema. La validación manual confirmó la corrección de la página curva y la omisión de la plana; la corrección final conserva las selecciones del formulario al abrir el diagnóstico geométrico. `OCR-01E` queda cerrada.
### 0.81.0 — 2026-08-06
Integra y valida `OCR-01D` para OCR regional visual, plantillas o zonas dibujadas, clasificación documental y creación exclusiva de corridas candidatas. La RC2 corrige colisiones de `reading_order`. También incorpora la hoja de ruta pre-release, el piloto persistente, `EXP-01`, `WEB-01`, `GIAR-01` y la planificación audiovisual ampliada.
### 0.80.0 — 2026-08-06

Implementa y valida `OCR-01C` para columnas y orden de lectura revisables, con diagnóstico de fragmentación y duplicaciones, migración `0044_layout_structure_review` y exportación `layout_structures.jsonl`. La RC2 agrega un recorrido numerado, selección visible, creación y asignación combinadas, historial legible, imagen de revisión desde el original cuando falta preview y verificación diagnóstica explícita. La RC3 corrige el uso de un atributo inexistente de `ReviewPageView` que interrumpía el render después del bloque 1. La RC4 distingue **Historial general** del historial específico de layout y muestra la columna actual del objeto. La validación final confirmó tres columnas activas, cinco objetos editables, combinación y archivo explícitos, deshacer/rehacer, exportación 1.4, conservación del PDF y de los siete objetos OCR de origen; `OCR-01C` queda cerrada.

### 0.79.0 — 2026-08-05
- Implementa `OCR-01B`: candidatos de casillero no canónicos, confirmación explícita, estados controlados y grupos estables por página.
- Conserva evidencia, anclajes a objetos editables, ciclo de vida e historial append-only; permite alta manual cuando el casillero visible no fue OCRizado.
- Integra formularios en deshacer/rehacer, intercambio, adopción de estado y la exportación `form_structures.jsonl`.
- Agrega la migración aditiva `0043_form_structure_review` y una base descartable controlada. La validación manual confirmó grupos, controles, historial, deshacer/rehacer, exportación, integridad del original y persistencia de la pestaña activa; `OCR-01B` queda cerrada.

### 0.78.0 — 2026-08-05
- Implementa `OCR-01A`: orientación conservadora, deskew acotado y eliminación controlada de líneas o marcos sobre derivados OCR.
- Conserva originales y previsualizaciones sin cambios y agrega comparación visual con el derivado OCR y la máscara diagnóstica.
- Registra análisis y transformaciones por página mediante la migración aditiva `0042_preprocessing_geometry_trace`.
- Incorpora y valida manualmente una base descartable con cinco casos geométricos controlados: rotación de 90°, deskew de -3°, marco removible, línea que cruza texto y baja confianza. Los originales permanecen intactos y `OCR-01A` queda cerrada.

### 0.77.0 — 2026-08-05
- Implementa conjuntamente `CAT-02` y `GRAPH-02`: roles productores y gestores controlados, historial, períodos, evidencia, procedencia y capas archivísticas o documentales separadas.
- Agrega foco sobre autoridades, unidades, documentos o partes; filtros de niveles, profundidad y límite de nodos; y exportación explicable en JSON, CSV y GraphML.
- Muestra flechas en los vínculos dirigidos, conserva sin flecha las entidades compartidas, corrige la dirección y etiqueta de la pertenencia documental y mantiene disponible la distancia después de aplicar filtros.
- Incorpora la migración aditiva `0041_catalog_authority_roles_graph_layers`; las relaciones existentes permanecen como `analytical`.
- La validación automatizada y manual queda completa: nueve nodos, doce aristas, cero inconsistencias, flechas y filtros correctos; `CAT-02` y `GRAPH-02` quedan cerrados.

### 0.76.0 — 2026-08-04
- Implementa `DISC-02`: formato JSON versionado, esquema, ejemplo, simulación, resolución de duplicados, evidencia obligatoria y aplicación transaccional de autoridades, alias y relaciones.
- Valida manualmente el conflicto nominal sin resolver, el rechazo de relaciones sin evidencia, la conservación de una ficha reutilizada y la reimportación idéntica sin nuevas escrituras; `DISC-02` queda cerrado.
- Agrega la guía vigente [`IMPORTACION_DICCIONARIOS_DISC_02.md`](referencia/IMPORTACION_DICCIONARIOS_DISC_02.md).
- No agrega migración; continúa `0040_discovery_grouping_continuity`.

### 0.75.1 — 2026-08-04
- Corrige el flujo de confirmación de la importación XLSX para que `IMPORTAR` se compruebe después de pulsar un botón habilitado.
- Documenta que `LISTAS` es una hoja auxiliar oculta y neutraliza el nombre del proyecto descartable de validación.
- No agrega migraciones; continúa `0040_discovery_grouping_continuity` y `CAT-01` permanece abierto solo para repetir los pasos afectados.

### 0.75.0 — 2026-08-04
- Implementa `CAT-01` con plantillas XLSX documentadas, estructura jerárquica distribuible, exportación vacía o del catálogo vigente, simulación detallada e importación transaccional con confirmación explícita.
- Incorpora comandos de terminal, interfaz de Catálogo y una primera plantilla pública DIPPBA de 155 filas con fuentes y advertencias sobre ramas parciales.
- No agrega migraciones; continúa `0040_discovery_grouping_continuity` y el bloque queda abierto únicamente para validación manual.

### 0.74.0 — 2026-08-04
- Implementa y valida la calibración semántica reproducible y la comparación de informes por corpus, perfil, modelo, revisión de índice y umbrales.
- Separa y valida relaciones paralelas e inversas en el grafo, conserva tooltips de procedencia y evita colisiones básicas de nodos y etiquetas.
- Cierra `OCR-02` por alcance, incorpora `CAT-01`, `CAT-02` y `GRAPH-02` al plan y mantiene `QA-01` en el cierre pre-release; sin migración, continúa `0040_discovery_grouping_continuity`.

### 0.73.0 — 2026-08-03
- Cierra `DISC-01D` y `DISC-01` con corpus JSONL por familia, métricas reproducibles, errores auditables y comparación de informes.
- Agrega el adaptador opcional `spacy_ner` con selección exacta de modelo y versión, sin declararlo superior al proveedor local.
- Confirma la validación manual de `UX-03`; sin migración nueva.

### 0.72.0 — 2026-08-03
- Cierra `DISC-01C` con cuatro grupos, nueve pertenencias, catorce acciones append-only, una continuidad desde un snapshot equivalente e integridad correcta.
- Resuelve `UX-03` separando Entidades y menciones en tareas persistentes y dividiendo Descubrimiento abierto en revisión, nueva corrida y agrupamiento o continuidad.
- Ordena `HISTORIAL_DE_CAMBIOS.md` e `IMPLEMENTACIONES_REALIZADAS.md` sin migración nueva.

### 0.71.2 — 2026-08-03
- Corrige el validador de continuidad para snapshots equivalentes y registra `UX-03` como reformulación crítica de la interfaz de descubrimiento; sin migración.

### 0.71.1 — 2026-08-03
- Corrige la selección posterior a crear un grupo manual: Streamlit aplica la selección pendiente en el rerun siguiente y conserva el grupo ya persistido; sin migración.

### 0.71.0 — 2026-08-03
- Valida `DISC-01B` e implementa `DISC-01C` con `0040_discovery_grouping_continuity`, grupos y pertenencias sin fusión, acciones append-only y continuidad textual que conserva candidatos obsoletos.

### 0.70.2 — 2026-08-03
- Agrega criterios permanentes de interfaz, mantiene abiertos los paneles interactivos durante reruns y valida las ocho decisiones controladas sin borrar una decisión adicional append-only; sin migración.

### 0.70.1 — 2026-08-03
- Hace obligatorio revisar los principios de interfaz en cada modificación, agrega `UX-02` como auditoría final de complejidad y unifica pruebas relevantes más `collect-only` en un solo comando; sin migración.

### 0.70.0 — 2026-08-03
- Valida `DISC-01A` e implementa `DISC-01B` con `0039_discovery_decisions`, decisiones append-only, autoridades explícitas, registros propios por familia y bloqueo de candidatos obsoletos, sin relaciones automáticas.

### 0.69.2 — 2026-08-03
- Corrige la verificación de `DISC-01A` sobre corpus con otros documentos aprobados sin cambiar detector ni esquema.

### 0.69.1 — 2026-08-03
- Corrige el filtrado de menciones existentes y mueve el panel de `DISC-01A` al final de la vista, cerrado por defecto; sin migración ni nueva copia de prueba.

### 0.69.0 — 2026-08-03
- Implementa `DISC-01A` con perfiles, corridas y candidatos persistentes de descubrimiento abierto.
- Agrega `0038_open_discovery`, proveedor local determinista, interfaz, comandos de terminal y copia descartable de validación.
- Conserva offsets, revisión textual, parámetros y autorización de calidad sin crear registros canónicos.

### 0.68.1 — 2026-08-03
- Cierra `EX-01` después de validar la adopción reversible, el acuerdo bilateral posterior y la integridad de las copias descartables.
- Registra la migración y apertura correcta de `project_data`, con las pruebas OCR todavía visibles.
- Fija el plan completo de `DISC-01` y deja `DISC-01A` como próximo bloque funcional, sin migración nueva.

### 0.68.0 — 2026-08-03
- Implementa `EX-01D`: paquete completo, vista previa, backup, adopción transaccional y rollback de un estado editable divergente.
- Agrega `0037_exchange_state_adoptions`; la adopción no crea base común y el acuerdo bilateral sigue siendo posterior y separado.
- Registra como validada `EX-01C` mediante un acuerdo coincidente en ambas copias y un paquete vacío reconocido por `common_base_agreement`.

### 0.67.0 — 2026-08-03
- Implementa `EX-01C`: propuesta, aceptación y finalización bilateral de una nueva base común cuando dos copias tienen estado editable idéntico.
- Agrega `0036_exchange_common_base_agreements`, manifiestos verificables, puntos de control vinculados y `common_base_agreement`, sin modificar contenido.

### 0.66.0 — 2026-08-03
- Implementa `EX-01B`: recuperación append-only de linaje cuando `EX-01A` demuestra una cadena concluyente y única.
- Agrega la migración `0035_exchange_lineage_recovery`, casos, evidencias y decisiones auditables, y el método persistido `recovered_lineage`.
- La recuperación no modifica contenido, invalida la simulación anterior y obliga a reevaluar el paquete antes de resolver o aplicar.

### 0.65.0 — 2026-08-03
- Implementa `EX-01A`: diagnóstico de solo lectura para paquetes sin base reconocida.
- Verifica SQLite local, paquetes, manifiestos aislados y backups explícitos; clasifica evidencia recuperable, ambigua o insuficiente.
- Agrega interfaz, comando de terminal y proyecto descartable de validación, sin migración ni acciones de recuperación.

### 0.64.2 — 2026-08-03
- Cierra `DATA-02` tras validar las tres autorizaciones, la auditoría por terminal y la integridad de la base.
- Fija la planificación completa de `EX-01` y deja `EX-01A` como próximo bloque funcional.

### 0.64.1 — 2026-08-03
- Corrige el bloqueo del botón de sugerencias de menciones con alcance ampliado: la acción permanece habilitada y la autorización se valida al pulsarla.
- No modifica el esquema; continúa la revisión `0034_automatic_analysis_authorizations` y la validación parcial de `DATA-02`.

### 0.64.0 — 2026-08-03
- Completa la implementación de `DATA-02`: alcance programático seguro, fundamento obligatorio, registro append-only y bloqueo de perfiles sin autorización vigente; su cierre queda sujeto a validación manual.
- Agrega la migración `0034_automatic_analysis_authorizations`, auditoría en interfaz y terminal, y relevo documental para una conversación nueva.

### 0.63.0 — 2026-08-03
- Cierra `DATA-01` tras validar reparaciones agrupadas e inicia `DATA-02` con páginas aprobadas como alcance automático predeterminado y confirmación para ampliarlo.
- Agrega a `.assistant/` una regla obligatoria contra bloqueos circulares entre widgets y botones dentro de `st.form`.

### 0.62.1 — 2026-08-03
- Corrige el bloqueo circular del botón de decisión conjunta: la selección dentro del formulario ya no necesita habilitar el botón mediante un rerender que Streamlit no realiza.
- Valida la mención ganadora al enviar y conserva intacta la transacción de dominio.

### 0.62.0 — 2026-08-02
- Permite revisar como una unidad conjuntos de tres o más menciones coincidentes y elegir una única ganadora sin decisiones parciales.
- Agrega reubicaciones seguras agrupadas, con una revisión individual por mención y cancelación completa ante cualquier cambio.

### 0.61.0 — 2026-08-02
- Permite comparar la fila vigente de una mención con su último snapshot y elegir explícitamente cuál conservar.
- Registra `repair_adopt_current_row` o, al restaurar, conserva primero la divergencia mediante `repair_capture_divergent_row` y agrega después `repair_restore_snapshot`.

### 0.60.0 — 2026-08-02
- Permite resolver ubicaciones ambiguas seleccionando un fragmento literal y una aparición concreta, con revisión `repair_manual_relocation`.
- Permite retirar de manera auditable una mención cuyo fragmento ya no aparece mediante `repair_mark_absent`, sin borrar registro ni historial.

### 0.59.0 — 2026-08-02
- Permite comparar dos menciones que convergen sobre el mismo fragmento vigente y elegir explícitamente cuál conservar.
- Retira la perdedora mediante `repair_duplicate_rejected`; cuando se conserva la histórica, la reubica mediante `repair_duplicate_relocated`.
- Mantiene bloqueados los conjuntos múltiples, las revisiones obsoletas y las divergencias de historial.

### 0.58.0 — 2026-08-02
- Permite resolver menciones aceptadas o modificadas sin entidad mediante `repair_link_authority` o `repair_return_pending`, sin alterar snapshots anteriores y bloqueando divergencias.
- Agrega una copia descartable con dos rutas de validación y corrige los fragmentos de prueba para que no terminen con palabras cortadas.

### 0.57.0 — 2026-08-02
- Cierra `UX-01` y agrega revisión centralizada para reubicar únicamente menciones con proyección única, sin colisiones y con historial consistente.
- Registra `repair_relocation` sin reescribir snapshots previos e incorpora una copia descartable para validar el recorrido.

### 0.56.0 — 2026-08-02
- Evita el recorte de estados largos y simplifica el resumen, las tablas y los filtros de Organización del trabajo.
- Presenta Exportar como configurar, revisar contenido y crear archivo, con identificadores y huellas en detalles técnicos.

### 0.55.0 — 2026-08-02
- Simplifica Revisión, Entidades y el mapa de relaciones, agrupando opciones secundarias y usando un léxico más directo.
- No modifica datos, revisiones, menciones ni algoritmos del grafo.

### 0.54.0 — 2026-08-02
- Simplifica Catálogo y Procesamiento, mantiene las acciones principales visibles y mueve la búsqueda dentro de palabras al bloque principal.
- No modifica datos, perfiles, extracciones ni la revisión de base.

### 0.53.0 — 2026-08-02
- Simplifica las búsquedas literal y por significado, manteniendo la consulta visible y agrupando filtros y configuración técnica.
- No modifica índices, perfiles, resultados ni reglas de filtrado.

### 0.52.0 — 2026-08-02
- Organiza el recorrido en cinco etapas y once pasos, con navegación y orientación contextual opcional.
- Reemplaza anglicismos operativos y relega comandos técnicos a detalles desplegables.

### 0.51.0 — 2026-08-02
- Inicia la simplificación de interfaz con navegación por tareas, ayuda contextual y léxico principal en español.
- Conserva códigos internos en detalles técnicos y registra la corrección visual de perfiles.

### 0.50.3 — 2026-08-02
- Ejecuta las acciones de ciclo de vida antes del render mediante callbacks encolados, evitando formularios duplicados.
- Agrega regresiones para impedir reruns anidados durante el archivado.

### 0.50.1 — 2026-08-02
- Intentó sincronizar selector y formulario de perfiles tras acciones de ciclo de vida sin modificar datos ni historial.

### 0.50.0 — 2026-08-02
- Reorganiza `docs/` en documentación operativa, referencia actual e historial.
- Agrega `.assistant/` con reglas de continuidad, interacción, documentación y pruebas.
- Consolida una única lista de pendientes y un único registro de implementaciones realizadas.
- Recupera pendientes que habían desaparecido: audiovisual, transcripción, plugin de YouTube, imagen Docker, integración Drive, corpus de evaluación y cierre de v1.0.
- Incorpora como pendientes evaluados la simplificación de interfaz, importación de diccionarios, herramientas LLM y RAG.
- No modifica la base ni la lógica funcional.

## Ciclos anteriores

### 0.49.x — ciclo de vida de exportaciones e intercambio
- Confirmación persistente de exportaciones y administración de perfiles.
- Diagnóstico, archivo y limpieza de paquetes obsoletos.
- Presentación segura de paquetes sin base común.
- Confirmaciones de formularios sin bloqueo circular.
- Consolidación inicial de pendientes y estrategia de pruebas.

Detalle: [actualizaciones 0.49.x](historico/actualizaciones/) y `CHANGELOG.md`.

### 0.46.0–0.48.0 — continuidad, rebase y menciones
- Formularios sin acciones por `Enter`.
- Atributos completos en Revisión.
- Filtros de calidad para búsquedas y sugerencias.
- Rebase repetible y conservación de procedencia.
- Deduplicación de menciones entre revisiones.
- Entradas manuales con botones explícitos.

Detalle: [actualizaciones históricas](historico/actualizaciones/) y [decisiones de rebase](historico/decisiones_tecnicas/).

### 0.40.0–0.45.0 — rebase conservador
- Adopción segura de nuevas extracciones.
- Resolución de menciones, texto, estructura, metadatos y atributos.
- Navegación persistente y fragmentos autocontenidos.

Detalle: [decisiones técnicas](historico/decisiones_tecnicas/).

### 0.35.0–0.39.0 — calidad, preprocesamiento y Surya
- Calidad automática de página.
- Derivados conservadores.
- Runtime Surya aislado, servidor persistente y fallback.
- Evaluación empírica inicial y control estructural revisable.

Detalle: [decisiones técnicas](historico/decisiones_tecnicas/).
### 0.30.0–0.34.5 — circuito operativo completo
- Catálogo, procesamiento, revisión, búsqueda, entidades, relaciones, exportación, intercambio y backups.
- Historial integral y revisión de corridas candidatas.
- Intercambio creciente del historial editable.
Detalle: [diseño histórico](historico/diseno/DISENO_Y_PLAN_DE_IMPLEMENTACION_HASTA_0.49.2.md) y [prueba piloto](historico/prueba_piloto/).
## Versiones anteriores
La evolución completa desde el inicio se conserva en [`CHANGELOG.md`](../CHANGELOG.md). Ese archivo es el registro técnico exhaustivo; este documento funciona como índice breve y no repite cada cambio.
## Regla para versiones futuras
La guía vigente permanece en `operativos/ACTUALIZACION_ACTUAL.md`. Al publicar una nueva versión, la guía reemplazada se mueve a `historico/actualizaciones/` con su número de versión. No se crean archivos nuevos en la raíz de `docs/`.
