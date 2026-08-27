# Actualización actual - Archive Workbench 0.89.0 RC57

## Alcance de RC57

La validación manual de RC56 cerró `PILOT-01AB`: el intercambio normal entre copias quedó funcional y visualmente verde, incluida la creación de una copia compartible, el paquete incremental, Google Drive, la descarga, la revisión y la aplicación. No repetir ese recorrido salvo evidencia concreta de regresión.

El piloto continuó en **Administrar y recuperar > Integridad**. Sobre el proyecto persistente aparecieron dos advertencias por archivos de exportación eliminados deliberadamente, dos relaciones archivísticas todavía no revisadas y dos índices pendientes de actualización. La funcionalidad de comprobación era correcta, pero la pantalla no ayudaba a pasar del diagnóstico a la acción, mostraba la revisión técnica de la base como información principal y **Autorizaciones de análisis** carecía de filtros para un historial que crecerá de forma continua.

RC57 mantiene la misma persistencia de dominio y reorganiza estas superficies:

- cada diagnóstico conocido ofrece, cuando corresponde, una acción que abre la sección concreta donde puede revisarse: Productores y responsables, Entidades y menciones, Búsqueda textual, Búsqueda semántica, Historial de exportaciones, Catálogo o Probar recuperación;
- las comprobaciones informativas quedan bajo divulgación progresiva y los códigos internos, IDs y revisión de base pasan a **Detalles técnicos**;
- los avisos no bloqueantes que pueden representar una situación aceptada, como una exportación eliminada deliberadamente o un índice pendiente que se decidió no reconstruir todavía, pueden **descartarse** y volver a mostrarse después;
- el descarte es una preferencia operativa reversible guardada en `config/project_health_dismissals.json`: no borra historial, no modifica SQLite ni viaja como cambio incremental; sí queda incluido en los backups porque éstos respaldan `config/`;
- si una copia para trabajar en equipo fue creada omitiendo deliberadamente originales o exportaciones, Integridad respeta esa decisión y no presenta esos grupos como archivos perdidos;
- **Autorizaciones de análisis** incorpora búsqueda y filtros por tipo de análisis, responsable, origen, alcance de páginas y cantidad de registros mostrados.

`PILOT-01AC` queda abierto únicamente hasta validar esta depuración sobre `pilot_data`. Si queda verde, el piloto continúa inmediatamente con **Copias de seguridad > Probar recuperación**, sin reabrir intercambio.

## Actualización desde RC56

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC57.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC56 y RC57. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir recorridos ya validados ni ejecutar la suite completa. Para RC57 corresponde el gate focal de Integridad, navegación administrativa, autorizaciones de análisis, documentación y empaquetado, seguido de `pytest --collect-only -q`. La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC57

Usar el mismo `pilot_data`. No recrear el proyecto y no repetir el intercambio ya validado.

1. Abrir **Administrar y recuperar > Integridad** y ejecutar **Comprobar ahora la integridad del proyecto**. La revisión `0047_authority_relation_profiles` no debe ocupar una tarjeta principal; debe quedar dentro de **Detalles técnicos de la comprobación**.
2. En las relaciones `produjo` y `gestionó`, usar **Abrir Productores y responsables**. Debe abrir la unidad archivística correspondiente y la pestaña **Productores y responsables**. No es necesario modificar la relación para validar la navegación.
3. En una advertencia por una exportación eliminada deliberadamente, usar **Descartar este aviso**. Debe desaparecer de la lista activa y quedar accesible desde **Ver avisos descartados**. El registro histórico de la exportación no debe borrarse. Puede dejarse descartado o restaurarse mediante **Volver a mostrar este aviso**.
4. Abrir **Comprobaciones informativas** y probar las acciones de Búsqueda textual y Búsqueda semántica. Deben navegar a la superficie correspondiente; no hace falta reconstruir los índices en esta pasada.
5. Abrir **Autorizaciones de análisis** y comprobar búsqueda, tipo de análisis, responsable, origen, alcance de páginas y límite de resultados. Cambiar filtros no debe modificar ninguna autorización.
6. Volver a Integridad y comprobar que los códigos internos, IDs y la revisión de base permanecen subordinados en detalles técnicos, y que la pantalla no queda sobrecargada.

Si todo queda verde, cerrar `PILOT-01AC` y continuar con la creación de un backup y la prueba no destructiva de recuperación. No restaurar `pilot_data` durante esa prueba.
