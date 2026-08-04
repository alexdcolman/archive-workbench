# Actualización y prueba — Archive Workbench 0.70.1

Esta versión no cambia la lógica de `DISC-01B`. Registra como obligación permanente el control de complejidad de interfaz, agrega `UX-02` como revisión integral futura y modifica la forma de entregar pruebas: desde ahora todas las pruebas relevantes y `collect-only` se ejecutan en un único bloque.

La migración vigente continúa siendo:

```text
0039_discovery_decisions
```

La base principal `project_data` y `project_data_open_discovery_validation` ya fueron respaldadas y migradas correctamente por Alex. No se repiten esos pasos.

## 1. Actualizar el código

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.70.1
mkdir -p /tmp/archive_workbench_v0.70.1

unzip -q \
  ~/Downloads/archive_workbench_v0.70.1.zip \
  -d /tmp/archive_workbench_v0.70.1

cp -a /tmp/archive_workbench_v0.70.1/. .

python -m pip install \
  --no-build-isolation \
  --no-deps \
  -e .
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.70.1
```

## 2. Base de datos

Esta versión **no contiene migración**. No ejecutes `project-backup-create` ni `db-upgrade` otra vez.

Ambas bases deben permanecer en:

```text
0039_discovery_decisions
```

No recrees la copia y no vuelvas a ejecutar el descubrimiento.

## 3. Pruebas automatizadas — un solo comando

Ejecutá exactamente este único bloque:

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

La primera parte debe terminar con:

```text
42 passed
```

La segunda debe recopilar:

```text
403 tests
```

No se ejecutó nuevamente la suite monolítica completa.

## 4. Preparar la revisión sin repetir la detección

Ejecutá:

```bash
python scripts/prepare_open_discovery_review_validation.py \
  project_data_open_discovery_validation
```

Debe informar:

```text
Revisión: 0039_discovery_decisions
Objetos recorridos conservados: 17
Candidatos totales conservados: 13
Candidatos controlados: 7
No se volvió a ejecutar el descubrimiento y no se creó ninguna decisión.
```

El script agrega después de la detección una única autoridad aprobada y controlada:

```text
Ministerio de Archivos Imaginarios
```

No crea menciones, relaciones ni decisiones.

## 5. Registrar las decisiones desde la interfaz

Abrí:

```bash
archive-workbench review-app \
  project_data_open_discovery_validation
```

Confirmá que en la barra lateral figure:

```text
Responsable: alex
```

Entrá en:

```text
Entidades y menciones
→ Descubrimiento abierto
```

Abrí el panel, seleccioná la corrida ya existente y no pulses **Ejecutar descubrimiento abierto**.

### 6.1 Vincular una organización existente

Localizá:

```text
Ministerio de Archivos Imaginarios
```

Abrí **Revisar candidato** y elegí:

```text
Decisión: Aceptar
Destino: Vínculo con una autoridad existente
Autoridad existente: Ministerio de Archivos Imaginarios
Fundamento: vacío
```

Pulsá **Registrar decisión** una sola vez.

### 6.2 Crear una persona sin aprobarla automáticamente

Localizá:

```text
Dra. Valentina Orbe
```

Usá:

```text
Decisión: Aceptar
Destino: Nueva autoridad sin revisar
Nombre preferido: Valentina Orbe
Descripción inicial: Persona controlada para validar DISC-01B.
Fundamento: Validación DISC-01B autoridad nueva.
```

Marcá:

```text
Confirmo la creación de una autoridad nueva con estado Sin revisar
```

Pulsá **Registrar decisión** una sola vez.

### 6.3 Conservar una expresión temporal como dato propio

Localizá:

```text
24 de marzo de 1976
```

Usá:

```text
Decisión: Aceptar
Destino: Registro propio de la familia
Descripción: Fecha controlada para validar DISC-01B.
Expresión temporal: 24 de marzo de 1976
Fundamento: vacío
```

Pulsá **Registrar decisión** una sola vez.

### 6.4 Conservar un acontecimiento como dato propio

Localizá:

```text
operativo Horizonte
```

Usá:

```text
Decisión: Aceptar
Destino: Registro propio de la familia
Descripción: Acontecimiento controlado para validar DISC-01B.
Expresión temporal: vacío
Fundamento: vacío
```

Pulsá **Registrar decisión** una sola vez.

### 6.5 Modificar y después aceptar una acción o proceso

Localizá:

```text
investigación documental
```

Primero usá:

```text
Decisión: Modificar propuesta
Texto o etiqueta revisada: investigación documental del operativo
Familia revisada: Acción o proceso
Subtipo revisado: process
Fundamento: Validación DISC-01B modificación.
```

Pulsá **Registrar decisión** una sola vez.

Después del refresco, abrí nuevamente **Revisar candidato** para el mismo candidato. Debe mostrar la etiqueta modificada. Usá:

```text
Decisión: Aceptar
Destino: Registro propio de la familia
Descripción: Proceso controlado aceptado después de modificar su etiqueta.
Fundamento: vacío
```

Pulsá **Registrar decisión** una sola vez.

El historial debe contener dos filas numeradas: primero `Modificado` y después `Aceptado`.

### 6.6 Aplazar una obra

Localizá:

```text
Cuaderno del Delta
```

Usá:

```text
Decisión: Aplazar
Fundamento: Validación DISC-01B aplazamiento.
```

Pulsá **Registrar decisión** una sola vez.

### 6.7 Rechazar un espacio

Localizá:

```text
ciudad de Puerto Niebla
```

Usá:

```text
Decisión: Rechazar
Fundamento: Validación DISC-01B rechazo.
```

Pulsá **Registrar decisión** una sola vez.

Al terminar deben verse estos estados finales en los siete candidatos controlados:

```text
Aceptado: 24 de marzo de 1976
Aceptado: Dra. Valentina Orbe
Rechazado: ciudad de Puerto Niebla
Aceptado: Ministerio de Archivos Imaginarios
Aceptado: operativo Horizonte
Aceptado: investigación documental del operativo
Aplazado: Cuaderno del Delta
```

No crees ni edites relaciones. Detené Streamlit con `Ctrl+C`.

## 7. Revisar las decisiones desde terminal

Ejecutá:

```bash
archive-workbench discovery-decisions \
  project_data_open_discovery_validation \
  --limit 20
```

Debe finalizar con:

```text
Total: 8 decisiones
```

La salida debe mostrar dos decisiones para el candidato de `investigación documental`: números `1` y `2`.

Después:

```bash
archive-workbench discovery-context-records \
  project_data_open_discovery_validation
```

Debe finalizar con:

```text
Total: 3 registros propios
```

Las familias deben ser:

```text
time
event
action_process
```

## 7. Verificación final

Ejecutá:

```bash
python scripts/validate_open_discovery_disc01b.py \
  project_data_open_discovery_validation
```

Debe mostrar:

```text
objetos recorridos: 17
candidatos totales: 13
candidatos controlados: 7
decisiones append-only: 8
registros propios: 3
menciones creadas: 2
autoridad nueva: Valentina Orbe
revisión: 0039_discovery_decisions
integridad: ok
claves foráneas: []
```

El bloque `conteos finales` puede incluir otros registros previos de la copia, pero la comprobación exige exactamente, respecto del estado preparado:

- una autoridad nueva;
- dos menciones nuevas;
- cero relaciones nuevas;
- ocho decisiones nuevas;
- tres registros propios nuevos;
- ninguna decisión sobre los seis candidatos adicionales de la corrida.

`DISC-01B` queda pendiente únicamente de esta validación manual. Después corresponde registrar su cierre e implementar `DISC-01C`, sin repetir la detección ni las decisiones anteriores.
