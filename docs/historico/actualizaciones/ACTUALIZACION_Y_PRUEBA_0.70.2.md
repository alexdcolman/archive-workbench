# Actualización y prueba — Archive Workbench 0.70.2

Esta versión corrige la estabilidad de los paneles interactivos de `DISC-01B` y formaliza los criterios permanentes de interfaz en `.assistant/05_CRITERIOS_INTERFAZ.md`.

La copia de validación ya contiene nueve decisiones: las ocho decisiones controladas y una aceptación adicional accidental sobre `manifestación`. Como el historial es append-only, no se elimina ni se modifica esa decisión. La verificación distingue ahora los resultados controlados de los adicionales.

La revisión de base continúa siendo:

```text
0039_discovery_decisions
```

## 1. Actualizar el código

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.70.2
mkdir -p /tmp/archive_workbench_v0.70.2

unzip -q \
  ~/Downloads/archive_workbench_v0.70.2.zip \
  -d /tmp/archive_workbench_v0.70.2

cp -a /tmp/archive_workbench_v0.70.2/. .

python -m pip install \
  --no-build-isolation \
  --no-deps \
  -e .

python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.70.2
```

## 2. Base de datos

Esta versión **no contiene migración**. No ejecutes `project-backup-create`, `db-upgrade` ni el script de preparación. No vuelvas a ejecutar el descubrimiento.

`project_data` y `project_data_open_discovery_validation` permanecen en:

```text
0039_discovery_decisions
```

Las nueve decisiones y los cuatro registros propios actuales deben conservarse sin cambios.

## 3. Todas las pruebas relevantes — un solo comando

Ejecutá exactamente:

```bash
pytest -q \
  tests/test_open_discovery.py \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

La primera parte debe terminar con `103 passed`. La segunda debe recopilar `404 tests`.

No se ejecutó nuevamente la suite monolítica completa.

## 4. Comprobar la estabilidad de los paneles

Abrí la misma copia:

```bash
archive-workbench review-app \
  project_data_open_discovery_validation
```

Entrá en **Entidades y menciones**.

1. **Descubrimiento abierto** debe aparecer al final y cerrado por defecto.
2. Abrilo. El panel debe permanecer abierto durante todos los cambios siguientes.
3. Abrí **Configurar perfil**, cambiá temporalmente la confianza mínima y volvela al valor anterior. No pulses **Guardar perfil de descubrimiento**. El panel de configuración y el panel principal deben seguir abiertos.
4. Localizá **Cuaderno del Delta**, que está aplazado, y abrí **Revisar candidato**.
5. Cambiá `Decisión` de **Aplazar** a **Aceptar**.
6. Cambiá al menos una vez `Destino de la aceptación` entre las opciones disponibles.

Durante los pasos 5 y 6 deben permanecer abiertos:

- **Descubrimiento abierto**;
- **Revisar candidato**.

Los controles elegidos deben seguir visibles y no debe registrarse ninguna decisión por cambiar selectores o radios.

No pulses **Registrar decisión**. Detené Streamlit con `Ctrl+C`.

## 5. Verificación final sobre el estado real

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
decisiones controladas: 8
decisiones adicionales conservadas: 1
registros propios controlados: 3
registros propios adicionales: 1
menciones controladas: 2
menciones adicionales: 0
autoridad nueva: Valentina Orbe
revisión: 0039_discovery_decisions
integridad: ok
claves foráneas: []
```

Los conteos finales deben conservar nueve decisiones, cuatro registros propios y ninguna relación nueva. Con la salida correcta y la confirmación de que los paneles ya no se cierran, `DISC-01B` queda validada y corresponde continuar con `DISC-01C`.
