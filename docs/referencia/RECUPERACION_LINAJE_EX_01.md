# EX-01 — Recuperación asistida de linaje y nueva base común verificada

**Estado:** cerrado y validado en 0.68.1. `EX-01A` fue validada en 0.65.0; `EX-01B` en 0.66.0; `EX-01C` en 0.67.0; `EX-01D` en 0.68.0 y su cierre documental en 0.68.1.

## 1. Problema

Cuando una copia recibe un paquete de intercambio cuya base no puede reconocerse, Archive Workbench falla de forma segura: clasifica los eventos como revisables y no supone parentesco. Ese comportamiento debe conservarse.

`EX-01` agrega un procedimiento independiente para distinguir dos situaciones:

1. el parentesco existía, pero la copia perdió o no conserva accesible la evidencia necesaria;
2. no existe evidencia suficiente y los equipos necesitan establecer deliberadamente una nueva base común.

Resolver campos, conservar valores locales, aceptar valores recibidos o aplicar un paquete no debe convertir por sí solo una copia en pariente de otra.

## 2. Objetivo

Permitir que una persona responsable:

- diagnostique por qué un paquete quedó sin base reconocida;
- reúna y verifique evidencia proveniente de puntos de control, paquetes, aplicaciones anteriores, manifiestos o backups;
- recupere el linaje únicamente cuando exista una cadena concluyente y no ambigua;
- cuando esa recuperación sea imposible, establezca una nueva base común mediante una operación separada, bilateral, explícita y auditable;
- vuelva a ejecutar la simulación del paquete después de cualquier decisión de linaje.

## 3. Contratos actuales que se conservan

### Identidades

- `Project.id` identifica el corpus y no puede reescribirse para forzar compatibilidad.
- `ExchangeWorkspace.id` identifica una copia de trabajo.
- `ExchangeCheckpoint` representa un estado local asociado a una secuencia de eventos.
- `ExchangeBundleApplication` registra qué paquete de una copia remota fue incorporado y qué punto de control local resultó.

### Paquetes existentes

El contrato `ChangeBundleManifest` versión `1.0` ya conserva:

- proyecto;
- copia de origen;
- identificador y nombre de la copia;
- punto de control base;
- SHA-256 del estado base;
- secuencia base y última secuencia;
- cantidad y SHA-256 de eventos;
- versión de aplicación y revisión de base.

`EX-01` debe seguir aceptando esos paquetes sin exigir una regeneración.

### Reconocimiento actual

La simulación reconoce una base por:

1. igualdad exacta entre el SHA-256 del estado base del paquete y un punto de control local;
2. ascendencia registrada por un paquete anterior aplicado desde la misma copia de origen y hasta la misma secuencia remota.

Ambas rutas continúan siendo prioritarias y no deben degradarse.

### Backups

Los backups de proyecto verifican manifiesto, checksums, `quick_check`, proyecto y revisión de base. La SQLite incluida puede aportar evidencia histórica de puntos de control, aplicaciones y copias, pero nunca debe restaurarse ni importarse durante un diagnóstico de linaje.

## 4. Invariantes de seguridad

1. **Sin inferencia por similitud.** Un texto, catálogo o hash parecido no demuestra parentesco.
2. **Sin parentesco por resolución.** Resolver el contenido de un paquete no crea linaje.
3. **Sin escritura durante el diagnóstico.** Explorar artefactos solo produce un informe hasta que exista una confirmación separada.
4. **Evidencia íntegra.** Todo archivo usado debe superar estructura, SHA-256 y validaciones internas.
5. **Mismo proyecto.** Un identificador de proyecto diferente bloquea la operación; no se ofrece reidentificación automática.
6. **Cadena no ambigua.** Dos explicaciones incompatibles bloquean la recuperación.
7. **Secuencias continuas.** No se aceptan huecos, retrocesos ni una secuencia remota mayor que la demostrada.
8. **Registro append-only.** Evidencias, decisiones y acuerdos se agregan; no se reescribe el historial de intercambio.
9. **Simulación caduca.** Toda decisión de linaje invalida la simulación previa y obliga a ejecutarla nuevamente.
10. **Adopción transaccional.** Reemplazar un estado editable, si una fase posterior lo habilita, requiere backup previo, verificación posterior y rollback ante fallo.
11. **Acción explícita.** Ninguna decisión se ejecuta con `Enter`; toda escritura exige botón o bandera de confirmación dedicada.
12. **Formularios seguros.** Los botones no dependen mediante `disabled` de widgets ubicados dentro del mismo `st.form`.

## 5. Evidencia y fuerza probatoria

### Concluyente

Puede habilitar una recuperación cuando identifica de manera única proyecto, copias, secuencias y punto local comparable:

- un punto de control local con el SHA-256 exacto declarado por el paquete;
- una aplicación anterior registrada que alcance la secuencia remota declarada;
- un backup verificable de esta misma copia cuya SQLite contenga la aplicación o el punto de control faltante y permita enlazarlo sin ambigüedad con la identidad vigente;
- una cadena de paquetes y manifiestos íntegros que conecte un punto local ya reconocido con la base del paquete recibido, sin huecos ni bifurcaciones.

### De apoyo

Se muestra, pero no alcanza por sí sola para escribir una recuperación:

- coincidencia de nombres de copia;
- coincidencia de rutas o fechas;
- un manifiesto aislado no anclado a un punto local;
- igualdad de estado actual sin evidencia de las secuencias intermedias;
- un identificador abreviado de paquete sin coincidencia única.

### Rechazada

- checksums inválidos;
- proyecto diferente;
- copia de origen incompatible;
- secuencias imposibles o incompletas;
- artefactos duplicados con contenido distinto;
- backups que no superan `quick_check`;
- evidencia que exige modificar o restaurar datos para poder ser interpretada.

## 6. Persistencia

La migración `0035_exchange_lineage_recovery` implementa los registros de caso, evidencia y decisión separados de los eventos de contenido. La migración `0036_exchange_common_base_agreements` agrega el registro local append-only del acuerdo bilateral y su vínculo con el punto de control. La migración `0037_exchange_state_adoptions` agrega las adopciones completas de estado y sus rollbacks, también como registros append-only:

### Caso de linaje

Un caso vincula un paquete `unmatched` con su diagnóstico y conserva, como mínimo:

- proyecto, copia local, copia de origen, paquete y simulación;
- estado del caso;
- fecha y responsable de apertura y cierre;
- hash de los parámetros del diagnóstico.

### Evidencia

Cada evidencia conserva:

- tipo de artefacto;
- ruta registrada o identificador lógico;
- SHA-256 del artefacto;
- proyecto y copias identificadas;
- secuencias y puntos de control observados;
- resultado de verificación;
- fuerza probatoria y explicación;
- datos técnicos estructurados.

### Decisión de linaje

Una decisión append-only conserva:

- operación: `recover_lineage` o `establish_common_base`;
- evidencias utilizadas;
- punto y secuencia local comparables;
- copia y secuencia remotas reconocidas;
- estado adoptado cuando corresponda;
- responsable, fundamento y confirmación;
- SHA-256 de parámetros;
- resultado y motivo de cualquier rechazo.

### Acuerdo de base común

Las dos copias deben registrar el mismo identificador de acuerdo y verificar:

- proyecto;
- ambas identidades de copia;
- secuencias locales de cada lado;
- SHA-256 del estado editable acordado;
- estado adoptado: `local`, `remote` o `reconciled`;
- responsable y fundamento en cada copia;
- manifiesto de acuerdo y su SHA-256.

No se reutilizarán `ExchangeConflictResolution` ni `ExchangeBundleApplication` para representar estas decisiones.

### Adopción y rollback de estado

Cada adopción conserva el paquete y su manifiesto, las identidades de origen y destino, los hashes anterior y adoptado, la huella de la base documental, el impacto por sección, el backup previo, responsable, fundamento, origen y SHA-256 de parámetros.

Cada rollback conserva la adopción revertida, el backup restaurado, el backup de seguridad creado antes de restaurar, el estado recuperado, responsable, fundamento, origen y SHA-256 de parámetros. Ninguna de las dos operaciones crea por sí sola un acuerdo bilateral.

## 7. Flujo funcional

### Diagnóstico

1. Seleccionar un paquete `unmatched` activo.
2. Examinar la base declarada y la evidencia ya presente en SQLite.
3. Agregar opcionalmente paquetes, manifiestos o backups para inspección.
4. Verificar todos los artefactos sin escribir linaje ni contenido.
5. Mostrar una explicación ordenada de hallazgos, huecos y contradicciones.
6. Clasificar el resultado como `recoverable`, `ambiguous` o `insufficient`.

### Recuperación

1. Solo se habilita con evidencia concluyente y única.
2. La persona revisora confirma copia local, copia remota, secuencias, evidencias, responsable y fundamento.
3. Se registra una decisión append-only y una referencia de ascendencia recuperada.
4. La simulación anterior pasa a obsoleta; no se conservan sus decisiones como aplicables.
5. Se repite la simulación y el paquete debe quedar clasificado desde la base recuperada.

La recuperación no modifica páginas, objetos, autoridades, menciones, relaciones ni eventos de contenido.

### Nueva base común

Cuando no exista evidencia recuperable:

1. ambas copias deben identificarse explícitamente;
2. debe declararse qué estado se adopta: local, remoto o reconciliado;
3. el estado editable final debe ser idéntico en las dos copias antes de activar el acuerdo;
4. cada copia verifica proyecto, identidad contraparte, secuencias y SHA-256;
5. ambas registran el mismo acuerdo append-only;
6. se crean puntos de control locales vinculados al acuerdo;
7. toda simulación anterior queda obsoleta.

La primera implementación de esta ruta cubrirá estados ya reconciliados e idénticos. La adopción automática de un estado divergente será una fase posterior, con un paquete de estado completo, backup y rollback.

## 8. Fases de implementación

### EX-01A — Diagnóstico de evidencia — IMPLEMENTADA Y VALIDADA EN 0.65.0

- Informe de solo lectura para paquetes `unmatched`.
- Inspección de SQLite local, paquetes íntegros, manifiestos aislados y backups verificables indicados explícitamente.
- Clasificación interna `recoverable`, `ambiguous` o `insufficient`, presentada como recuperable, ambigua o insuficiente.
- Detección de punto de control exacto, aplicación anterior, backup de la misma copia y cadenas continuas de paquetes.
- Rechazo de artefactos alterados, proyectos diferentes, copias de origen incompatibles, ciclos y bifurcaciones.
- Interfaz y terminal sin acciones de escritura de linaje, contenido ni reportes persistentes.
- Script descartable `create_lineage_diagnostic_validation_projects.py` para comprobar una cadena de dos paquetes.

### EX-01B — Recuperación de linaje — IMPLEMENTADA Y VALIDADA EN 0.66.0

- La migración `0035_exchange_lineage_recovery` agrega casos, evidencias y decisiones separadas, además del método persistido de reconocimiento de base.
- La recuperación solo se habilita cuando el diagnóstico vigente devuelve una única cadena concluyente.
- La confirmación exige responsable, fundamento y aceptación explícita; un envío incompleto no escribe nada.
- La decisión y sus evidencias se registran de manera append-only y un segundo intento sobre el mismo paquete se rechaza explícitamente.
- La simulación previa queda `stale` y debe repetirse; la reevaluación reconoce la base con `recovered_lineage`.
- La recuperación no aplica eventos, no altera páginas, objetos, autoridades, menciones, relaciones ni texto editable.
- La interfaz usa un formulario con `enter_to_submit=False`, botón siempre habilitado y validación al enviar.
- La terminal expone `exchange-lineage-recover` y `exchange-lineage-recoveries`.

### EX-01C — Acuerdo de base común con estado idéntico — IMPLEMENTADA Y VALIDADA EN 0.67.0

- La migración `0036_exchange_common_base_agreements` agrega acuerdos locales append-only vinculados a puntos de control propios.
- El recorrido bilateral tiene tres pasos explícitos: propuesta en la copia iniciadora, aceptación en la contraparte y finalización del mismo manifiesto en la iniciadora.
- La propuesta y el acuerdo son ZIP verificables con manifiestos JSON 1.0 y checksums SHA-256.
- Ambas copias conservan el mismo `agreement_id`, la misma huella del manifiesto, el mismo SHA-256 editable y sus secuencias locales respectivas.
- La aceptación se bloquea si el proyecto, la identidad de la contraparte, el nombre de la copia o el estado editable no coinciden.
- La finalización se bloquea si la secuencia o el estado de la copia iniciadora cambiaron desde la propuesta.
- Cada lado crea un punto de control `common_base_<id>` vinculado al acuerdo e invalida simulaciones anteriores.
- Un paquete posterior puede reconocer la nueva base mediante `common_base_agreement`.
- La interfaz usa formularios con `enter_to_submit=False`, botones siempre habilitados y validaciones al enviar.
- La terminal expone `exchange-common-base-propose`, `exchange-common-base-accept`, `exchange-common-base-finalize` y `exchange-common-base-agreements`.
- El script `create_common_base_validation_projects.py` genera dos copias descartables con identidades distintas y estado editable idéntico.

### EX-01D — Adopción explícita de estado divergente — IMPLEMENTADA Y VALIDADA EN 0.68.0

- La migración `0037_exchange_state_adoptions` agrega registros append-only de adopción y rollback, separados de aplicaciones de paquetes y acuerdos.
- El paquete de estado 1.0 contiene manifiesto, estado editable completo, checksums y una huella de la base documental compartida; identifica de manera exacta origen y destino.
- La vista previa compara cada sección por identificador y muestra altas, bajas y cambios sin escribir filas ni archivos persistentes.
- La adopción exige responsable, fundamento y confirmación, crea primero un backup verificable y reemplaza el estado editable dentro de una transacción.
- Antes de confirmar verifica el SHA-256 adoptado, `PRAGMA integrity_check` y `PRAGMA foreign_key_check`; cualquier fallo cancela la escritura.
- Las simulaciones activas quedan obsoletas, pero la adopción no registra parentesco ni base común.
- El rollback explícito restaura el backup anterior, crea un backup de seguridad del estado posterior y conserva la adopción y la reversión como evidencia append-only.
- El rollback se bloquea si la adopción ya fue revertida, si el estado cambió después o si existe un acuerdo de base común que usa el estado adoptado.
- La base bilateral solo puede establecerse después de comprobar que ambas copias tienen hashes editables idénticos.
- La terminal expone `exchange-state-package-create`, `exchange-state-adoption-preview`, `exchange-state-adopt`, `exchange-state-adoptions` y `exchange-state-adoption-rollback`; la interfaz incorpora **Reconciliar estados divergentes**.
- `create_state_adoption_validation_projects.py` genera dos copias descartables divergentes y un paquete inicial dirigido a la copia destinataria.

Cada fase se entrega y valida antes de iniciar la siguiente.

## 9. Criterios de no regresión

- Los paquetes ya reconocidos por hash exacto siguen quedando `matched`.
- La ascendencia por paquete aplicado continúa funcionando aunque existan resoluciones locales posteriores.
- Un paquete sin evidencia suficiente sigue `unmatched` y no puede aplicar creaciones masivamente.
- Una simulación obsoleta continúa bloqueándose antes de crear backups.
- Archivar, restaurar o limpiar una entrada no modifica el corpus.
- Los contratos `ChangeEvent` y `ChangeBundleManifest` 1.0 siguen siendo válidos.
- `fork_exchange_workspace` conserva su semántica y no se usa como sustituto de una recuperación.
- Los backups existentes siguen siendo restaurables sin depender de `EX-01`.
- No se alteran originales, extracciones, texto revisado, autoridades, menciones ni relaciones durante diagnóstico, recuperación o acuerdo de base común.
- `PRAGMA integrity_check` devuelve `ok` y `PRAGMA foreign_key_check` no devuelve filas después de cada escritura.

## 10. Pruebas mínimas

### Diagnóstico

- informe sin cambios en ninguna tabla;
- punto de control exacto detectado;
- aplicación anterior detectada;
- backup íntegro con cadena válida detectado;
- paquete o backup alterado rechazado;
- proyecto diferente rechazado;
- dos cadenas incompatibles clasificadas como ambiguas;
- manifiesto aislado clasificado solo como apoyo.

### Recuperación

- migración desde `0034_automatic_analysis_authorizations` con conservación completa;
- decisión incompleta rechazada sin escribir;
- recuperación válida registrada una sola vez;
- evidencia y decisión append-only;
- simulación anterior marcada obsoleta;
- nueva simulación usa el punto recuperado y clasifica correctamente eventos locales, recibidos y duplicados;
- recuperación repetida idempotente o rechazada de forma explícita;
- integridad y claves foráneas válidas.

### Nueva base común

- acuerdo con mismo proyecto, copias distintas y estado idéntico;
- rechazo por estado diferente, identidad repetida o proyecto distinto;
- mismo identificador y manifiesto registrados en ambas copias;
- puntos de control vinculados al acuerdo;
- simulaciones anteriores invalidadas;
- un paquete posterior reconoce la base nueva.

### Adopción de estado

- vista previa sin escritura;
- backup previo verificable;
- aplicación transaccional;
- rollback ante fallo intermedio;
- preservación del backup y del informe;
- hashes editables iguales antes de activar el acuerdo;
- integridad, claves foráneas y revisión de base correctas.

### Interfaz

- botones disponibles y validación al enviar;
- envío incompleto sin escritura;
- envío válido exactamente una vez;
- mensajes persistentes;
- ausencia de paneles duplicados después del rerun;
- ninguna escritura mediante `Enter`.

## 11. Fuera de alcance por ahora

- sincronización en tiempo real o servidor central;
- transporte mediante Google Drive u otra nube;
- firmas criptográficas o infraestructura de claves: se usarán SHA-256 y verificación estructural;
- inferencia de parentesco mediante embeddings, similitud textual o modelos LLM;
- unión automática de proyectos con identificadores diferentes;
- reescritura de UUID para hacer coincidir copias;
- fusión automática de bases SQLite divergentes;
- copia o sustitución de PDF, TIFF, audio, video u originales;
- importación automática de evidencia encontrada fuera de rutas seleccionadas explícitamente;
- eliminación de casos, evidencias, decisiones o acuerdos históricos.

## 12. Criterio de cierre de EX-01

`EX-01` queda cerrado cuando:

1. un paquete `unmatched` puede diagnosticarse sin escritura;
2. una cadena verificable permite recuperar linaje y volver a simular desde la base correcta;
3. dos copias sin evidencia recuperable pueden registrar una nueva base común con estado idéntico;
4. cuando los estados difieren, la adopción elegida se ejecuta con backup, verificación y rollback;
5. todas las decisiones quedan auditadas y las rutas inseguras continúan bloqueadas;
6. las pruebas automatizadas y una validación manual con copias descartables confirman integridad y ausencia de regresiones.
