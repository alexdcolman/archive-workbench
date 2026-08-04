# Descubrimiento abierto — DISC-01

## Estado de implementación

`DISC-01A` está **implementada y validada**. La validación manual recorrió `17` objetos aprobados, produjo `13` candidatos totales y confirmó los `7` candidatos controlados con offsets, revisión textual, familias, integridad y claves foráneas correctas. La migración `0038_open_discovery`, el proveedor `local_deterministic@local_rules_v1`, la interfaz, la terminal y la auditoría permanecen vigentes.

`DISC-01B` está **implementada y validada**. La migración `0039_discovery_decisions` agrega decisiones append-only y registros propios por familia. El estado manual confirmado conserva nueve decisiones —ocho controladas y una aceptación adicional accidental sobre `manifestación`—, cuatro registros propios, doce menciones, siete autoridades y tres relaciones previas. La decisión adicional se conserva como historial válido y no se borra ni se reinterpreta. Los paneles interactivos mantienen su apertura durante los reruns.

`DISC-01C` está **implementada en Archive Workbench 0.71.0, corregida en 0.71.1 y 0.71.2, y pendiente únicamente de repetir el validador final**. La migración `0040_discovery_grouping_continuity` agrega grupos de candidatos, pertenencias, acciones append-only y vínculos de continuidad textual. La fase propone coincidencias exactas o normalizadas entre corridas, permite crear y separar grupos manualmente y proyecta o vuelve a detectar un candidato obsoleto sobre la revisión vigente sin ocultar el snapshot histórico. No fusiona candidatos, no borra procedencias y no modifica autoridades, menciones, relaciones, decisiones ni registros propios.

La corrección 0.71.1 difiere la selección de un grupo manual recién creado hasta el rerun siguiente. La corrección 0.71.2 valida la continuidad desde cualquiera de los dos snapshots controlados equivalentes de `Cuaderno del Delta`, en lugar de exigir un identificador arbitrario. Los grupos, la separación y la continuidad ya fueron creados y no deben repetirse.

`DISC-01D` continúa pendiente y no debe adelantarse antes de validar `DISC-01C` ni antes de resolver `UX-03`, la reformulación completa de la interfaz de descubrimiento.

## Objetivo

Recorrer el corpus autorizado para proponer referencias todavía no registradas y someterlas a revisión humana. No es una ampliación de la búsqueda por nombres y alias conocidos: esa búsqueda parte de una autoridad existente; el descubrimiento abierto parte del texto y produce candidatos nuevos.

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
- crear relaciones definitivas sin una decisión humana;
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

### DISC-01C — Agrupamiento, deduplicación y continuidad textual — IMPLEMENTADA, VALIDADOR FINAL PENDIENTE

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

Los grupos no son registros canónicos y no trasladan decisiones automáticamente. Un candidato separado conserva la pertenencia histórica con estado `removed`; las reconstrucciones automáticas posteriores no revierten esa separación. La continuidad crea una corrida y un candidato nuevos, conserva el candidato obsoleto y hereda únicamente las pertenencias activas de grupo como procedencia, no sus decisiones humanas.

Criterio de cierre pendiente: validar tres grupos controlados —exacto, normalizado y exacto—, un grupo manual con una separación, una continuidad textual y la conservación exacta de los conteos canónicos ya confirmados en `DISC-01B`.

### DISC-01D — Evaluación y proveedores adicionales

- corpus de evaluación por familia;
- precisión, recuperación y errores por proveedor;
- adaptadores opcionales para NER, extracción de eventos o modelos locales;
- comparación reproducible de versiones y parámetros;
- documentación de límites y falsos positivos.

Criterio de cierre: ningún proveedor se declara predeterminado sin evidencia empírica y todos usan el mismo contrato auditable.

## No regresión

La implementación no debe alterar:

- búsqueda por nombres y alias conocidos;
- autoridades, alias, menciones y relaciones vigentes;
- política de páginas aprobadas;
- historial y rebase de texto editable;
- intercambio offline y sus hashes;
- exportaciones e índices semánticos existentes.

`project_data` continúa siendo la base principal local. Las primeras validaciones de `DISC-01` se harán únicamente sobre copias `project_data_*_validation` generadas para cada fase.
