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

Describe fondos, colecciones, series, unidades, documentos, partes internas, objetos digitales, ubicaciones y metadatos configurables.

### Archivos y derivados

Registra originales, checksums, copias locales y derivados de preparación. Cada transformación conserva procedencia, parámetros y archivo de origen.

### Procesamiento

Ejecuta corridas por página mediante perfiles y backends. Las corridas se conservan, se evalúan y pueden seleccionarse por página sin borrar alternativas.

### Revisión

Mantiene objetos editables con texto, tipo, orden, geometría, atributos, estado y revisiones append-only. Comentarios, etiquetas, menciones y relaciones se gestionan como capas vinculadas.

### Búsqueda

La búsqueda literal usa índices reconstruibles. La búsqueda semántica utiliza perfiles con modelo, fragmentación, filtros y estado del corpus.

### Autoridades

Separa autoridad canónica, alias y menciones contextuales. Una grafía coincidente no implica identidad automática. Las relaciones explícitas requieren evidencia y revisión.

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
- Corrida de extracción: ejecución versionada.
- Página extraída y objeto extraído: candidatos automáticos.
- Página editable y objeto editable: estado humano activo e historial.
- Autoridad: identidad canónica revisada.
- Mención: fragmento contextual con offsets, revisión textual y snapshots append-only.
- Relación: vínculo explícito con tipo, evidencia, temporalidad y estado.
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
- No aplicar un paquete con simulación obsoleta.
- Resolver contenido de un paquete sin base común no crea linaje.
- Recuperar linaje exige una cadena concluyente única, responsable, fundamento y confirmación; no aplica eventos de contenido.
- Toda recuperación vuelve obsoleta la simulación anterior y obliga a reevaluar el paquete.
- Adoptar un estado divergente exige paquete íntegro dirigido, backup previo, responsable, fundamento, confirmación e integridad válida.
- Una adopción de estado no activa una base común; ambas copias deben registrar después el acuerdo bilateral.
- El rollback de una adopción se bloquea si el estado cambió después o si un acuerdo bilateral ya depende del estado adoptado.
- No sobrescribir exportaciones salvo confirmación explícita.
- No ejecutar escrituras mediante `Enter`.

## Calidad

Los estados de página controlan qué contenido puede alimentar búsquedas, exportaciones y análisis. El alcance predeterminado para toda automatización es únicamente contenido aprobado. Incluir otros estados exige confirmación explícita, responsable, fundamento y una fila append-only en `automatic_analysis_authorizations`. Los tipos de análisis deben estar registrados en la política común; una integración futura no puede inventar una ruta paralela sin este contrato.

## Extensiones previstas

Las extensiones abiertas se describen únicamente en `../operativos/PENDIENTES_ACTIVOS.md`. El diseño vigente de descubrimiento abierto está en `DESCUBRIMIENTO_ABIERTO_DISC_01.md`; entre las demás extensiones se encuentran importación de diccionarios, audiovisual, herramientas LLM, RAG, Docker y transporte mediante Drive.

Cada extensión debe respetar los mismos contratos de identidad, procedencia, calidad, revisión y auditoría.
