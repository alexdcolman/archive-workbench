# Descubrimiento abierto — DISC-01

## Estado de implementación

`DISC-01A` está **implementada y validada**. La validación manual recorrió `17` objetos aprobados, produjo `13` candidatos totales y confirmó los `7` candidatos controlados con offsets, revisión textual, familias, integridad y claves foráneas correctas. La migración `0038_open_discovery`, el proveedor `local_deterministic@local_rules_v1`, la interfaz, la terminal y la auditoría permanecen vigentes.

`DISC-01B` está **implementada y validada**. La migración `0039_discovery_decisions` agrega decisiones append-only y registros propios por familia. El estado manual confirmado conserva nueve decisiones —ocho controladas y una aceptación adicional accidental sobre `manifestación`—, cuatro registros propios, doce menciones, siete autoridades y tres relaciones previas. La decisión adicional se conserva como historial válido y no se borra ni se reinterpreta. Los paneles interactivos mantienen su apertura durante los reruns.

`DISC-01C` está **implementada y validada**. La migración `0040_discovery_grouping_continuity` agrega grupos de candidatos, pertenencias, acciones append-only y vínculos de continuidad textual. El cierre confirmó cuatro grupos, nueve pertenencias conservadas, catorce acciones append-only, una continuidad desde un snapshot equivalente y la conservación exacta de los conteos canónicos de `DISC-01B`. La integridad es correcta, las claves foráneas están vacías y la prueba no debe repetirse.

`UX-03` reorganizó y validó en 0.72.0 la interfaz de Entidades y menciones y Descubrimiento abierto sin cambiar contratos ni datos. `DISC-01D` quedó implementada y validada en 0.73.0; `DISC-01` está cerrado.

## Objetivo

Recorrer el corpus autorizado para proponer referencias todavía no registradas y someterlas a revisión manual. No es una ampliación de la búsqueda por nombres y alias conocidos: esa búsqueda parte de una autoridad existente; el descubrimiento abierto parte del texto y produce candidatos nuevos.

La función debe poder proponer:

- actores: personas, organizaciones y colectivos;
- espacios: lugares, edificios, jurisdicciones y otros ámbitos;
- tiempos: fechas, expresiones temporales y períodos;
- acontecimientos;
- acciones y procesos;
- obras y otras clases configurables.

## Exclusiones obligatorias

El descubrimiento abierto nunca debe:

- crear autoridades aceptadas automáticamente;
- fusionar autoridades o candidatos automáticamente;
- crear relaciones definitivas sin una decisión explícita;
- convertir toda clase de candidato en una única semántica de “entidad”;
- trabajar sobre páginas fuera del alcance autorizado;
- aceptar un candidato cuyo texto o revisión de origen ya cambió;
- ocultar el método, versión, confianza o explicación que produjo la sugerencia.

La importación de diccionarios externos continúa siendo `DISC-02`. Las herramientas LLM y RAG continúan siendo capas opcionales separadas.

## Familias semánticas

La capa de sugerencias puede compartir infraestructura técnica, pero cada candidato declara una familia semántica estable:

- `actor`: persona, organización o colectivo;
- `space`: lugar o ámbito;
- `time`: fecha, expresión temporal o período;
- `event`: acontecimiento situado;
- `action_process`: acción o proceso;
- `work`: obra, publicación u objeto cultural;
- `other`: clase configurada que no encaja en las anteriores.

La familia no obliga a un destino canónico único. Una aceptación de `actor`, `space`, `event` o `work` puede vincularse a una autoridad existente o iniciar una creación explícita. `time`, `event` y `action_process` conservan además sus propios datos y decisiones; no se reducen silenciosamente a una autoridad.

## Trazabilidad mínima de cada candidato

Todo candidato conserva, como snapshot reproducible:

- texto exacto;
- documento y objeto editable;
- página o segmento;
- offsets de inicio y fin;
- número de revisión textual del objeto;
- familia y subtipo sugeridos;
- confianza normalizada cuando el proveedor la ofrece;
- método, proveedor, modelo y versión;
- explicación breve;
- parámetros funcionales y su SHA-256;
- corrida que lo produjo;
- fecha y persona responsable de la ejecución;
- alcance de calidad autorizado.

Un candidato queda obsoleto cuando la revisión textual vigente no coincide con la registrada. Debe volver a detectarse o proyectarse mediante un procedimiento explícito; no puede aceptarse usando offsets históricos como si siguieran vigentes.

## Alcance de calidad

`open_discovery` usa la política común de `analysis_quality.py`.

- Alcance predeterminado: únicamente páginas `approved`.
- Cualquier ampliación exige confirmación, responsable, fundamento, origen y autorización persistente.
- La huella autorizada debe incluir proveedor, versión, clases, fuentes, umbral y demás parámetros funcionales.
- Una configuración modificada no reutiliza silenciosamente una autorización anterior.

## Persistencia prevista

La implementación funcional usará registros separados:

1. perfiles de descubrimiento: configuración reproducible y ciclo de vida operativo;
2. corridas: ejecución inmutable con parámetros, alcance, cantidades y estado;
3. candidatos: snapshot exacto de cada sugerencia;
4. decisiones: `discovery_decisions`, con aceptación, rechazo, modificación o aplazamiento siempre append-only;
5. registros propios: `discovery_context_records` para tiempos, acontecimientos, acciones, procesos y otras familias que no deben reducirse a una autoridad;
6. grupos y pertenencias: deduplicación explícita por coincidencia exacta, normalizada o decisión manual, sin fusionar filas históricas;
7. acciones de grupo: creación, incorporación, restauración y separación siempre append-only;
8. continuidades: vínculo entre un candidato obsoleto y un candidato nuevo sobre la revisión textual vigente.

Los candidatos son sugerencias analíticas. Las autoridades, menciones, tiempos, acontecimientos y relaciones aceptadas continúan en sus estructuras canónicas actuales o en estructuras específicas posteriores. La tabla de candidatos no se convierte en una tabla canónica universal.

## Simplificación de la interfaz de revisión durante PILOT-01 - RC19

La implementación histórica de `DISC-01B` se conserva: la persistencia admite decisiones append-only `accept`, `reject`, `modify` y `defer`, y los datos existentes no se reescriben. La validación manual de PILOT-01 mostró, sin embargo, que exponer esas cuatro categorías como acciones equivalentes en la interfaz no coincide con la tarea que una persona intenta realizar. `modify` guardaba una corrección sin aceptar la referencia, y `defer` duplicaba en la práctica la posibilidad de dejar una referencia pendiente.

Desde RC19, la interfaz normal de revisión presenta únicamente **Aceptar** y **Descartar**. Si el texto, la familia o el subtipo necesitan corrección, esos cambios se completan dentro de **Aceptar** y la misma confirmación crea o vincula el registro que corresponda. **Descartar** saca la referencia de la cola de trabajo pero conserva la decisión; una acción explícita **Restaurar** agrega una nueva decisión append-only y devuelve la referencia a pendientes. `modify` y `defer` permanecen disponibles sólo como compatibilidad histórica del dominio/CLI y no se generan desde la interfaz nueva.

La interfaz permite además seleccionar varias referencias pendientes y, con confirmación explícita, crear una autoridad nueva con estado `unreviewed` por cada referencia compatible. La operación es transaccional y cada aceptación conserva su candidato y procedencia. El descarte también puede aplicarse en lote y mantiene la misma posibilidad de restauración individual posterior. Ninguna de estas acciones crea relaciones automáticamente.

Esta simplificación no cambia el modelo persistente de DISC-01 ni requiere migración; cambia la forma en que la interfaz presenta y combina las decisiones ya soportadas.

## Proveedores

El núcleo será independiente del motor. Cada proveedor deberá entregar el mismo contrato y declarar sus capacidades.

La primera implementación incluirá un proveedor determinista y local para validar el circuito completo sin servicios externos. Sus reglas serán conservadoras y explicables: expresiones temporales, referencias nominales, lugares introducidos por patrones explícitos, obras entrecomilladas y construcciones léxicas de acontecimientos o procesos. Los resultados serán candidatos revisables, no afirmaciones verdaderas.

Proveedores posteriores podrán usar NER, extracción de eventos o modelos locales, pero deberán pasar por la misma persistencia, autorización, revisión y evaluación.

## Fases de implementación

### DISC-01A — Contrato, persistencia y detección reproducible — VALIDADA

- agregar perfiles, corridas y candidatos;
- implementar el proveedor local determinista inicial;
- ejecutar solamente sobre el corpus y alcance autorizados;
- mostrar candidatos con trazabilidad completa en `Entidades y menciones`;
- agregar comandos de terminal para ejecutar, listar y auditar;
- no crear autoridades, menciones ni relaciones desde esta fase.

Criterio de cierre cumplido: la copia descartable conservó una única corrida, recorrió 17 objetos, produjo 13 candidatos y verificó los siete candidatos controlados sin escrituras canónicas ni daños en SQLite.

### DISC-01B — Revisión y decisiones por familia — VALIDADA

- aceptar, rechazar, modificar o aplazar candidatos;
- vincular actores, espacios, acontecimientos u obras a una autoridad existente;
- iniciar de manera explícita una autoridad nueva con estado `unreviewed`, sin aprobarla automáticamente;
- conservar tiempos, acontecimientos y acciones con datos propios;
- bloquear decisiones sobre candidatos obsoletos.

Implementación 0.70.0:

- migración `0039_discovery_decisions`;
- `discovery_decisions` y `discovery_context_records`;
- comandos `discovery-decide`, `discovery-decisions` y `discovery-context-records`;
- revisión explícita en cada tarjeta de candidato;
- bloqueo por obsolescencia textual;
- autoridades nuevas siempre `unreviewed`;
- menciones creadas solo después de una aceptación explícita;
- ausencia deliberada de creación automática de relaciones.

Criterio de cierre cumplido: se conservaron las ocho decisiones controladas, la novena decisión adicional append-only, cuatro registros propios, dos menciones controladas y ninguna relación automática. Los paneles interactivos permanecieron abiertos durante los reruns y la integridad de SQLite continuó correcta.

### DISC-01C — Agrupamiento, deduplicación y continuidad textual — VALIDADA

- migración `0040_discovery_grouping_continuity`;
- `discovery_candidate_groups` para la identidad y método del grupo;
- `discovery_group_memberships` para conservar cada procedencia, incluso después de una separación;
- `discovery_group_actions` como historial append-only de creación, incorporación, restauración y separación;
- `discovery_candidate_continuities` para vincular el snapshot obsoleto con un candidato nuevo sobre la revisión vigente;
- propuesta reproducible por coincidencia exacta o normalizada entre corridas;
- creación, incorporación y separación manuales sin fusionar candidatos;
- proyección exacta única o nueva detección local después de una edición textual;
- interfaz secundaria, cerrada inicialmente y con estado persistente durante reruns;
- comandos de terminal para reconstruir, listar, crear, separar, proyectar y auditar.

Los grupos no son registros canónicos y no trasladan decisiones automáticamente. Un candidato separado conserva la pertenencia histórica con estado `removed`; las reconstrucciones automáticas posteriores no revierten esa separación. La continuidad crea una corrida y un candidato nuevos, conserva el candidato obsoleto y hereda únicamente las pertenencias activas de grupo como procedencia, no sus decisiones explícitas.

Criterio de cierre cumplido: el validador confirmó cuatro grupos —tres automáticos y uno manual—, nueve pertenencias conservadas, catorce acciones append-only, una continuidad textual desde un snapshot equivalente y los conteos canónicos exactos de `DISC-01B`. La revisión es `0040_discovery_grouping_continuity`, la integridad es correcta y las claves foráneas están vacías.

### DISC-01D — Evaluación y proveedores adicionales — VALIDADA

La versión 0.73.0 agrega:

- `config/discovery_evaluation_corpus.jsonl`, con texto exacto, offsets, familia, subtipo y procedencia para las siete familias;
- métricas de precisión, recuperación y F1 micro, macro y por familia;
- registro explícito de falsos positivos, falsos negativos y discrepancias de familia o subtipo;
- informes JSON reproducibles con huellas del corpus, parámetros y resultado;
- comparación de informes del mismo corpus por proveedor, versión y configuración;
- `local_deterministic@local_rules_v1` y el adaptador opcional `spacy_ner` mediante un contrato común;
- selección explícita de `modelo@versión` para spaCy, sin cargar dependencias opcionales hasta ejecutar el perfil.

El corpus inicial es sintético y verifica el contrato, no representa la diversidad documental del piloto. Las reglas locales obtienen seis coincidencias exactas de siete y no cubren la familia `other`; ese límite queda visible en el informe. Ningún proveedor se declara mejor ni predeterminado por evidencia empírica. La revisión de base continúa en `0040_discovery_grouping_continuity`.

Criterio de cierre cumplido: todos los proveedores usan el mismo contrato auditable y la comparación no permite mezclar corpus con huellas diferentes.

## Afinado pre-release DISC-03 - RC66/RC69

`DISC-03` no reabre `DISC-01`: conserva sus tablas, decisiones y contratos. RC66 introdujo `local_deterministic@local_rules_v2` y mantuvo `local_rules_v1` ejecutable. RC67 agrega `local_rules_v3` como versión vigente para perfiles nuevos y conserva v1/v2 como versiones históricas reproducibles. La continuidad por `local_redetection` recupera la versión local registrada en el candidato o en el snapshot de su corrida, en lugar de aplicar silenciosamente la versión vigente.

El corpus `config/discovery_evaluation_corpus_disc03.jsonl` contiene 46 controles de géneros administrativos, archivísticos, testimoniales, académicos, periodísticos, técnicos y jurídicos. Incluye positivos, negativos y holdouts. Sobre las seis familias cubiertas por el proveedor local, v1 obtiene F1 micro `0.675676` y v2 `0.911765`. Los errores residuales de v2 se conservan en la auditoría y el corpus no se presenta como representativo del proyecto real.

RC66 dejó `DISC-03` parcial hasta contrastar la versión nueva con material real del piloto. Ninguna evaluación crea autoridades, menciones o relaciones canónicas.


RC67 audita v2 sobre exportaciones reales de 138 documentos y 78 segmentos audiovisuales sin incorporarlas al repositorio. A partir de esa evidencia agrega `local_rules_v3` y `config/discovery_evaluation_corpus_disc03_real_patterns.jsonl`, un corpus de 41 regresiones sintéticas derivadas de patrones reales. Los conteos externos describen diferencias, no precisión/recall; en RC67 `DISC-03` siguió parcial hasta revisión humana de candidatos v3 reales.

RC68 partió de esa revisión humana y agregó `local_rules_v4` sin modificar v1/v2/v3. `config/discovery_evaluation_corpus_disc03_rc68.jsonl` conserva las regresiones sintéticas de precisión y límites reportados. La validación manual posterior reveló que una configuración persistida seguía conservando su `provider_version`, por lo que podía ejecutarse nuevamente con v3 sin que la UI lo hiciera suficientemente visible. RC69 agrega `local_rules_v5`, mantiene v1-v4 como versiones históricas y exige actualización explícita de una configuración local histórica antes de iniciar una búsqueda nueva desde la interfaz. v5 conserva los límites nominales completos y hace **Obra / publicación** más conservadora: las comillas sólo delimitan y se requiere una señal léxica inmediata; se elimina la propagación amplia de contexto de v4. La revisión muestra la versión usada por cada búsqueda y dibuja 500 referencias por defecto, aunque declara siempre los totales y permite elegir 100/250/500/1000/Todas. La validación manual posterior de una corrida v5 real confirmó una mejora material de la utilidad de las referencias; `DISC-03` queda cerrado desde RC70 y no debe reabrirse sin una regresión concreta.

## No regresión

La implementación no debe alterar:

- búsqueda por nombres y alias conocidos;
- autoridades, alias, menciones y relaciones vigentes;
- política de páginas aprobadas;
- historial y rebase de texto editable;
- intercambio offline y sus hashes;
- exportaciones e índices semánticos existentes.

`project_data` continúa siendo la base principal local. Las primeras validaciones de `DISC-01` se harán únicamente sobre copias `project_data_*_validation` generadas para cada fase.
