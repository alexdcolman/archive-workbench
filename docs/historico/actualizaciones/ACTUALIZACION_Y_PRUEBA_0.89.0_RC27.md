# Actualización actual - Archive Workbench 0.89.0 RC27

**Estado:** candidata no publicada para validación manual transversal de `UX-04`  
**Última publicación real:** `v0.88.2`  
**Versión de código:** `0.89.0`  
**Revisión de base:** `0046_audiovisual_timeline_annotations`  
**Migración nueva:** no. **No ejecutar `db-upgrade`.**

## Alcance de RC27

La validación manual de RC26 aprobó los cambios funcionales y de disposición introducidos en esa candidata: `Ruta archivística` visible por defecto en `Procesar documentos > Estado`, la compactación de `Corregir o agregar`, el rediseño de `Revisar documentos > Orden y estructura` y la corrección del rerun innecesario al cambiar las pestañas de revisión. La objeción fue transversal y exclusivamente de orientación: el signo `?` no resultó adecuado y la reducción de texto visible había dejado muchas secciones y pestañas sin una explicación equivalente en otro lugar.

RC27 conserva los cambios aprobados de RC26 y reemplaza por completo ese patrón de ayuda:

- elimina los signos `?` y no restaura párrafos explicativos permanentes en el cuerpo principal;
- cada título de sección tiene una explicación explícita de para qué sirve la sección y cómo funciona, visible al posar el cursor sobre el propio título;
- cada pestaña real de la aplicación tiene su propia explicación por hover sobre el nombre de la pestaña;
- cuando una segunda barra de pestañas fue reemplazada por un selector compacto de tarea, el selector muestra por hover la explicación concreta de la tarea actualmente elegida;
- las explicaciones nombran los referentes concretos y las operaciones que se realizan. No usan fórmulas opacas como “gestionar”, “resolver” o “procesar” sin indicar qué objeto se gestiona, resuelve o procesa;
- la redacción aprobada se centraliza en `src/archive_workbench/ui_help.py` para que una refactorización visual no pueda retirar orientación sin modificar también esa fuente explícita;
- `tracked_tabs(...)` recibe obligatoriamente la ayuda correspondiente en todas las superficies de pestañas actuales, y la cobertura queda controlada por tests;
- `.assistant/05_CRITERIOS_INTERFAZ.md` establece como política permanente que toda sección, pestaña y tarea principal nueva o renombrada debe conservar esta explicación en su propio título o selector, sin agregar un `?` ni otra superficie visual paralela;
- `.assistant/00_CHECKLIST_CAMBIOS.md` obliga a comprobar esa cobertura antes de cerrar cualquier modificación de interfaz;
- la ayuda por hover se implementa con un componente v2 que sólo anota el DOM con `title` y `aria-description`: no envía estado a Python, no dispara acciones y no introduce reruns, fragmentos ni estrategias nuevas de conservación de scroll;
- las advertencias de seguridad, las consecuencias materiales y las confirmaciones necesarias para una escritura siguen visibles. El hover reemplaza orientación descriptiva, no advertencias necesarias para decidir una acción;
- no se modifica el modelo de dominio, la persistencia ni la revisión de base.

## Actualización segura desde RC26

Usar el actualizador de candidatas. No copiar el ZIP recursivamente sobre el repositorio y no tocar `pilot_data`.

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC27.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

La versión importada debe seguir informando `0.89.0`; `RC27` identifica la candidata. No ejecutar `db-upgrade`.

## Gate automatizado de RC27

```bash
cd ~/projects/archive_app && source .venv/bin/activate && pytest -q tests/test_ui_navigation.py tests/test_documentation.py tests/test_packaging.py && pytest --collect-only -q
```

El cierre del paquete puede agregar gates funcionales focales de las superficies atravesadas por la navegación, pero no corresponde afirmar que se ejecutó la suite completa salvo que efectivamente se haya hecho.

## Validación manual pendiente

Usar el proyecto persistente `/home/alex/projects/archive_app/pilot_data`. No hace falta ejecutar OCR, transcripción, escrituras, exportaciones reales, intercambio ni recuperación para esta ronda: la validación solicitada es integral de interfaz y orientación.

Recorrer **todas las secciones y todas sus pestañas o tareas principales**. En cada una:

1. posar el cursor sobre el título de la sección y comprobar que la explicación diga de forma explícita para qué sirve y cómo funciona;
2. posar el cursor sobre cada nombre de pestaña y comprobar lo mismo, sin signos `?`, paneles de ayuda ni párrafos permanentes adicionales;
3. donde exista un selector compacto de tarea, elegir cada tarea y posar el cursor sobre el selector para comprobar que la explicación corresponde exactamente a la tarea activa;
4. comprobar que las advertencias que afectan una decisión material sigan visibles y que la economía visual de RC22-RC26 se conserve;
5. comprobar durante el recorrido que cambiar pestañas de `Revisar documentos` siga sin provocar el reinicio ni el desplazamiento horizontal corregidos en RC26;
6. anotar cualquier explicación ambigua, referente implícito, título sin ayuda o superficie todavía demasiado cargada. Los remanentes que no bloqueen este rodeo se volverán a revisar en `UX-02`.

Si RC27 queda validada, cerrar `UX-04` documentalmente y retomar `PILOT-01` exactamente en **Relaciones**. Después continúan búsqueda literal, búsqueda semántica, grafo, exportación, asignación/revisión cruzada, checkpoint/bundle y backup/prueba de recuperación.
