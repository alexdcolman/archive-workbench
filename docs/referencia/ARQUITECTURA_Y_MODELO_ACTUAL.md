# Arquitectura y modelo actual — Archive Workbench

Este documento describe el diseño vigente. El desarrollo histórico completo hasta 0.49.2 se conserva en `../historico/diseno/DISENO_Y_PLAN_DE_IMPLEMENTACION_HASTA_0.49.2.md`.

## Propósito

Archive Workbench organiza, procesa, revisa, busca y exporta documentación archivística digitalizada sin convertir resultados automáticos en decisiones humanas definitivas.

## Principios

1. Originales inmutables: los archivos fuente no se alteran.
2. SQLite local es la fuente de verdad de cada proyecto.
3. Derivados, OCR, transcripciones, índices y análisis son versionados o reconstruibles.
4. Las identidades son estables y no dependen del orden visual.
5. Toda escritura importante es explícita, auditable y transaccional.
6. Migraciones solo se ejecutan mediante `db-upgrade`.
7. Los backends automáticos producen candidatos revisables.
8. Las capas derivadas no sustituyen catálogo, texto revisado ni autoridades.
9. El intercambio entre copias requiere simulación, confirmación y backup.
10. Las extensiones opcionales no deben volver obligatorio un backend, nube o GPU.

## Componentes

### Catálogo

Describe fondos, colecciones, series, unidades, documentos, partes internas, objetos digitales, ubicaciones y metadatos configurables. Las entidades productoras y gestoras se vinculan a cada unidad mediante autoridades canónicas existentes y roles controlados, con período, evidencia, procedencia, estado e historial append-only; no se duplican como texto libre canónico. Un cambio de gestión crea otro vínculo temporal y conserva el anterior. Las plantillas XLSX de catálogo transportan instrucciones, una estructura jerárquica restringida, unidades y listas controladas. Pueden ser más estrictas que la configuración del proyecto, pero no ampliar padres permitidos. La importación siempre simula el libro completo, informa errores por ubicación y aplica únicamente con confirmación explícita dentro de una sola transacción.

### Archivos y derivados

Registra originales, checksums, copias locales y derivados de preparación. Cada transformación conserva procedencia, parámetros y archivo de origen.

El preprocesamiento geométrico trabaja únicamente sobre el derivado destinado a OCR. La previsualización de consulta y el original no reciben rotaciones, deskew ni limpieza. Por página se conservan un análisis estructurado, la secuencia exacta de transformaciones y, cuando corresponde, una máscara diagnóstica de los píxeles retirados. La orientación se limita a cuartos de giro; el deskew está acotado; y la eliminación de líneas exige controles conservadores para no borrar trazos que atraviesan texto. Una confianza insuficiente produce una omisión explicable, no una corrección silenciosa.

### Procesamiento

Ejecuta corridas por página mediante perfiles y backends. Las corridas se conservan, se evalúan y pueden seleccionarse por página sin borrar alternativas.

### Revisión

Mantiene objetos editables con texto, tipo, orden, geometría, atributos, estado y revisiones append-only. Comentarios, etiquetas, menciones y relaciones se gestionan como capas vinculadas.

La estructura revisada de formularios pertenece a la página editable y no al resultado OCR. Los detectores producen candidatos sin autoridad canónica; una persona debe confirmar cada control, su estado y su rótulo. Los casilleros se anclan al menos a un objeto editable de marca o etiqueta, pueden agruparse mediante IDs estables y conservan evidencia, método candidato, responsable, fechas y ciclo de vida. Los grupos archivados permanecen en el snapshot histórico y sus controles activos quedan sin grupo. Cada cambio genera una revisión de página y participa en deshacer/rehacer, intercambio y adopción de estado.

### Búsqueda

La búsqueda literal usa índices reconstruibles. La búsqueda semántica utiliza perfiles con modelo, fragmentación, filtros y estado del corpus. Su calibración se ejecuta sin modificar la base: un corpus JSONL de consultas positivas, negativas y ambiguas se compara contra una revisión concreta del índice, se evalúan umbrales y se conservan métricas, falsos positivos, falsos negativos, parámetros y huellas reproducibles. Las comparaciones solo aceptan informes del mismo corpus y tipo de fragmento; cualquier umbral recomendado queda limitado al corpus, perfil, modelo, revisión de índice y grilla evaluada.

### Autoridades y grafo

Separa autoridad canónica, alias y menciones contextuales. Una grafía coincidente no implica identidad automática. Las relaciones se clasifican como analíticas, productoras o gestoras. Los roles archivísticos solo pueden apuntar a unidades y exigen evidencia y procedencia; las relaciones anteriores permanecen como `analytical`.

El grafo distingue autoridades, unidades archivísticas, objetos digitales y partes documentales. Las capas de jerarquía, pertenencia de documentos, partes, menciones, relaciones analíticas, productores y gestores pueden filtrarse de manera independiente. Cada arista explica la tabla o registro del que procede, por lo que una pertenencia archivística nunca se presenta como relación analítica. El foco puede partir de cualquiera de los cuatro tipos de nodo y limitar profundidad, niveles y cantidad de elementos. El canvas sigue siendo una proyección de lectura: separa de forma determinista relaciones paralelas o inversas, recalcula rutas y etiquetas al mover nodos y conserva tooltips de tipo, dirección, procedencia y evidencia. Cambiar el layout visual no escribe relaciones ni altera el modelo canónico.

Los diccionarios externos usan un contrato JSON versionado. La simulación resuelve cada autoridad como creación, reutilización, omisión o conflicto; compara nombres y alias normalizados y nunca actualiza silenciosamente una ficha existente. Las características externas se conservan como descripción estructurada solo al crear una autoridad nueva. Los alias ambiguos requieren autorización expresa. Cada relación importada exige evidencia y puede apuntar a una autoridad, unidad archivística o parte documental existente. Autoridades, alias y relaciones se aplican dentro de una sola transacción. El formato vigente está en [`IMPORTACION_DICCIONARIOS_DISC_02.md`](IMPORTACION_DICCIONARIOS_DISC_02.md).

### Exportación

Los perfiles seleccionan contenido, agrupación, filtros y formato. Cada materialización registra ruta, tamaño, hash y estado del corpus.

### Descubrimiento abierto

Los perfiles autorizados producen corridas inmutables y candidatos con texto exacto, offsets, revisión textual, familia semántica, método y procedencia. Las decisiones humanas se registran por separado y son append-only. Los grupos reúnen candidatos repetidos sin fusionar sus filas: cada pertenencia conserva corrida, documento, offsets y estado. Las acciones de grupo registran creación, incorporación, restauración y separación. Cuando una edición vuelve obsoleto un candidato, la continuidad crea un candidato nuevo sobre la revisión vigente y mantiene visible el snapshot histórico. La evaluación usa corpus JSONL con verdad terreno, métricas por familia e informes con huellas reproducibles. Los proveedores opcionales comparten el mismo contrato y fijan versión, método y modelo sin declararse superiores por defecto.

### Intercambio offline

Los eventos se exportan desde un punto de control. La copia receptora inspecciona y simula antes de aplicar. Los hashes de estado no sustituyen la ascendencia de eventos. Cuando una base no puede reconocerse, el diagnóstico de `EX-01A` permanece de solo lectura; `EX-01B` puede registrar una recuperación append-only únicamente ante evidencia concluyente y única. Esa decisión invalida la simulación anterior, y la siguiente reevaluación identifica el método `recovered_lineage`. Cuando dos copias distintas ya tienen exactamente el mismo estado editable, `EX-01C` permite registrar bilateralmente una nueva base común mediante propuesta, aceptación y finalización verificables; los paquetes posteriores pueden reconocerla mediante `common_base_agreement`. Cuando los estados divergen, `EX-01D` permite crear un paquete completo dirigido, previsualizar su impacto, respaldar la copia destinataria, adoptar el estado transaccionalmente o restaurar el backup previo. La adopción no crea parentesco: el acuerdo bilateral se registra recién después de comprobar hashes idénticos. La planificación completa está en [`RECUPERACION_LINAJE_EX_01.md`](RECUPERACION_LINAJE_EX_01.md).

### Backups

Los backups incluyen manifiesto, base y configuración. La restauración crea primero una copia de seguridad y requiere migración explícita si la versión de esquema lo necesita.

## Modelo de identidad

- Proyecto: identidad estable del corpus.
- Copia de trabajo: identidad propia para intercambio.
- Unidad archivística: identidad estable independiente de ruta o título.
- Objeto digital: archivo intelectual registrado.
- Instancia local: copia física concreta.
- Derivado de preparación: previsualización intacta, imagen OCR tratada o máscara diagnóstica, vinculada a una corrida y página.
- Corrida de extracción: ejecución versionada.
- Página extraída y objeto extraído: candidatos automáticos.
- Página editable y objeto editable: estado humano activo e historial.
- Estructura de formulario: snapshot coherente por página con grupos y casilleros de IDs estables, estados controlados, anclajes editables, evidencia y ciclo de vida.
- Autoridad: identidad canónica revisada.
- Mención: fragmento contextual con offsets, revisión textual y snapshots append-only.
- Relación: vínculo controlado `analytical`, `producer` o `manager` con destino tipado, evidencia, procedencia, temporalidad, estado e historial.
- Perfil de exportación o búsqueda: configuración versionada.
- Autorización de análisis automático: registro append-only del alcance, responsable, fundamento, origen, destino y hash de parámetros.
- Punto de control y paquete de intercambio: ascendencia y transporte de eventos.
- Caso, evidencia y decisión de recuperación de linaje: auditoría append-only separada del contenido y de las aplicaciones de paquetes.
- Acuerdo bilateral de base común: mismo identificador y manifiesto en ambas copias, con puntos de control locales propios.
- Adopción y rollback de estado: sustitución explícita respaldada y reversible, separada del acuerdo de parentesco.
- Perfil, corrida y candidato de descubrimiento: configuración autorizada, ejecución reproducible y snapshot textual revisable.
- Decisión y registro propio de descubrimiento: juicio humano append-only y datos específicos por familia.
- Grupo, pertenencia y acción de descubrimiento: deduplicación explícita sin fusionar procedencias.
- Continuidad de candidato: vínculo entre un snapshot obsoleto y uno nuevo sobre la revisión vigente.
- Corpus e informe de evaluación de descubrimiento: verdad terreno y comparación reproducible por proveedor, versión y parámetros.
- Corpus e informe de calibración semántica: consultas verificadas, métricas por umbral y comparación reproducible por perfil, modelo, revisión de índice y parámetros.
- Plantilla distribuible de catálogo: contrato XLSX versionado con estructura, unidades, campos, listas y procedencia, sin identidad canónica propia fuera de las unidades importadas.
- Diccionario distribuible de autoridades: contrato JSON versionado con identidad de fuente, autoridades locales, alias, resoluciones y relaciones; no es una autoridad canónica por sí mismo.
- Layout del grafo: proyección visual reconstruible sin identidad ni persistencia propias.

## Reglas de seguridad

- No borrar originales ni corridas históricas.
- Usar baja lógica cuando el historial deba conservarse.
- No aceptar una mención sin autoridad.
- Una mención histórica aceptada o modificada que perdió su autoridad solo puede vincularse a una entidad activa existente o volver a estado pendiente mediante una revisión explícita.
- Una mención desactualizada solo puede reubicarse automáticamente cuando la proyección al texto vigente es única, no colisiona con otra mención activa y la fila coincide con su último snapshot.
- Si una fila diverge de su último snapshot, la persona revisora debe comparar ambos estados y elegir cuál conservar. Restaurar el snapshot exige registrar primero la fila divergente como evidencia.
- Toda reparación de mención agrega una revisión nueva; los snapshots anteriores no se reescriben.
- No fusionar autoridades automáticamente.
- Los candidatos de descubrimiento abierto son sugerencias históricas, no registros canónicos.
- Toda decisión sobre un candidato es append-only y debe comprobar la revisión textual vigente.
- Una autoridad creada desde descubrimiento abierto queda `unreviewed`; ninguna aceptación crea relaciones automáticamente.
- Tiempos, acontecimientos y acciones o procesos conservan registros propios y no se reducen silenciosamente a autoridades.
- Agrupar candidatos no fusiona filas, no copia decisiones y no elimina procedencias.
- Una separación manual conserva el historial y no puede ser revertida por una reconstrucción automática.
- La continuidad textual crea un candidato nuevo; el candidato obsoleto permanece visible y no recibe decisiones nuevas.
- No trasladar anotaciones por similitud ambigua.
- Un candidato de casillero no es una decisión: el estado y la agrupación solo se vuelven revisados mediante confirmación explícita.
- Dar de alta un casillero visible sin marca OCR exige anclarlo a un objeto editable existente y registrar evidencia; no se inventan trazos ni objetos extraídos.
- No aplicar un paquete con simulación obsoleta.
- Resolver contenido de un paquete sin base común no crea linaje.
- Recuperar linaje exige una cadena concluyente única, responsable, fundamento y confirmación; no aplica eventos de contenido.
- Toda recuperación vuelve obsoleta la simulación anterior y obliga a reevaluar el paquete.
- Adoptar un estado divergente exige paquete íntegro dirigido, backup previo, responsable, fundamento, confirmación e integridad válida.
- Una adopción de estado no activa una base común; ambas copias deben registrar después el acuerdo bilateral.
- El rollback de una adopción se bloquea si el estado cambió después o si un acuerdo bilateral ya depende del estado adoptado.
- Una plantilla de catálogo no puede ampliar la jerarquía autorizada por el proyecto; la aplicación exige simulación válida y confirmación explícita.
- Un diccionario externo no puede sobrescribir autoridades existentes ni crear relaciones sin evidencia; los conflictos exigen resolución explícita y toda aplicación es transaccional.
- No sobrescribir exportaciones salvo confirmación explícita.
- No ejecutar escrituras mediante `Enter`.

## Calidad

Los estados de página controlan qué contenido puede alimentar búsquedas, exportaciones y análisis. El alcance predeterminado para toda automatización es únicamente contenido aprobado. Incluir otros estados exige confirmación explícita, responsable, fundamento y una fila append-only en `automatic_analysis_authorizations`. Los tipos de análisis deben estar registrados en la política común; una integración futura no puede inventar una ruta paralela sin este contrato.

## Extensiones previstas

Las extensiones abiertas se describen únicamente en `../operativos/PENDIENTES_ACTIVOS.md`. El diseño vigente de descubrimiento abierto está en `DESCUBRIMIENTO_ABIERTO_DISC_01.md`; entre las extensiones restantes se encuentran audiovisual, herramientas LLM, RAG, Docker y transporte mediante Drive.

Cada extensión debe respetar los mismos contratos de identidad, procedencia, calidad, revisión y auditoría.
