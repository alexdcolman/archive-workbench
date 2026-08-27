# Actualización actual - Archive Workbench 0.89.0 RC60

## Alcance de RC60

La validación manual de RC59 confirmó el contrato público de formatos documentales y cierra `PILOT-01L`: **PDF, TIFF, PNG, JPEG y WebP** son los formatos procesables declarados y BMP permanece fuera del contrato. No repetir esa validación salvo regresión concreta.

RC60 realiza la auditoría transversal final exigida por `PILOT-01E` sin reabrir los recorridos funcionales ya cerrados. La revisión se hizo en cinco pasadas independientes sobre títulos y síntesis, rótulos y botones, ayudas y avisos, estados y resultados, y bloques técnicos o avanzados. El registro completo queda en `docs/historico/actualizaciones/AUDITORIA_INTERFAZ_RC60_5_PASADAS.txt`.

Los residuos corregidos son acotados y de referente o jerarquía visual:

- el árbol del Catálogo deja de abreviar contenidos digitales como `obj.` y usa `contenido digital` / `contenidos digitales`;
- expresiones deícticas como `desde acá`, `elegí acá` o `acá son de solo lectura` nombran ahora la pantalla o el selector concreto;
- el progreso de **Procesar documentos** y el listado de páginas fallidas muestran el rótulo legible y desambiguado del documento, no `source_key`;
- cuando dos documentos son indistinguibles por título, archivo y ruta visible, los selectores usan `documento 1`, `documento 2`, etc. como último recurso de presentación, sin exponer `source_key` ni `digital_object_id`;
- el resultado y el historial de **Exportar corpus** priorizan el nombre del archivo y el resultado operativo; ruta completa, tamaño y SHA-256 quedan en detalles técnicos cerrados;
- la creación y verificación de copias de seguridad comunican primero el resultado operativo; rutas y huellas quedan subordinadas en detalles técnicos;
- `Descargar archivo` pasa a **Descargar esta exportación** para nombrar explícitamente el objeto de la acción.

No se modifica `pilot_data`, el esquema de base, los contratos de procesamiento, OCR, exportación, backup ni intercambio. `PILOT-01E` permanece **PARCIAL** hasta una última recorrida manual de la candidata sin guía externa: la auditoría estática no se considera evidencia suficiente de claridad.

## Actualización desde RC59

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC60.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC59 y RC60. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir OCR, Surya, procesamiento, exportaciones, backups ni recorridos ya validados. Para RC60 corresponde ejecutar únicamente navegación/interfaz, las regresiones focales de Procesar documentos, Exportar corpus y Administración, documentación/empaquetado y, al final, `pytest --collect-only -q`. La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC60

Usar el mismo `pilot_data`. No borrar preferencias para repetir el bloqueo inicial de identidad: ese requisito ya fue validado y conserva regresiones automáticas. No crear OCR, exportaciones, backups, cambios de catálogo ni otras escrituras sólo para esta prueba.

La última comprobación de `PILOT-01E` debe hacerse **sin una lista de textos esperados**. Abrir el proyecto normalmente y recorrer durante unos minutos las superficies principales como en un uso ordinario: Inicio, Catálogo, audiovisual, Procesar documentos, Revisar documentos, búsquedas, Entidades y menciones, Exportar corpus y Administrar y recuperar. Usar datos ya existentes y abrir/cerrar tareas o detalles cuando resulte natural.

La pregunta de cierre es deliberadamente simple: ¿hay algún título, botón, ayuda, estado o resultado que obligue a traducir jerga interna, adivinar a qué objeto se refiere o pedir una explicación externa para saber qué hacer? Si la respuesta es no, `PILOT-01E` puede cerrarse. No hace falta repetir las operaciones funcionales que ya quedaron verdes.

Después del cierre manual de `PILOT-01E`, el subsidiario pre-release sustantivo que queda dentro de `PILOT-01` es `PILOT-01A`, dedicado al modelo descriptivo de repositorios, custodia, colecciones y agrupaciones audiovisuales/plataformas. `PILOT-01N` es post-release y no bloquea.
