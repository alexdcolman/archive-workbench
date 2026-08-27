# Relevo vigente - Archive Workbench 0.89.0 RC27 / PILOT-01

**Candidata actual:** `0.89.0 RC27`, no publicada  
**Última publicación real:** `v0.88.2`  
**Revisión DB:** `0046_audiovisual_timeline_annotations`  
**Migración nueva:** no  
**Proyecto persistente del piloto:** `/home/alex/projects/archive_app/pilot_data`

RC22-RC23 validaron el prototipo de `UX-04` en `Entidades y menciones`. RC24 extendió los criterios al resto de la aplicación. RC25 rediseñó las siete tareas de `Procesar documentos` y quedó validada manualmente como una mejora material. RC26 agregó los últimos ajustes de procesamiento, rediseñó `Revisar documentos > Orden y estructura` y corrigió el rerun innecesario al cambiar las pestañas de revisión; esos cambios quedaron aceptados manualmente. La única objeción material a RC26 fue la capa de orientación: se rechazó el signo `?` y se constató que demasiadas explicaciones habían sido eliminadas sin trasladarlas a un mecanismo equivalente.

RC27 conserva todo lo aprobado de RC26 y reemplaza esa capa de ayuda de forma transversal: **cada sección, cada pestaña real y cada tarea principal seleccionable explica por hover, sobre su propio título o selector, para qué sirve y cómo funciona**, con referentes explícitos y sin agregar otra superficie visual.

## Lectura obligatoria antes de hacer cualquier cosa

Seguir exactamente el orden de `.assistant/00_LEER_PRIMERO.md`. Antes de cualquier modificación completar `.assistant/00_CHECKLIST_CAMBIOS.md`. `05_CRITERIOS_INTERFAZ.md` debe releerse antes de cualquier modificación de código, aunque no parezca de interfaz. Si se modifica código, el mensaje de entrega debe confirmar explícitamente que la checklist fue verificada. Antes de tocar una interacción Streamlit, leer completa `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md#streamlit-interaction-invariant`. No inventar estrategias paralelas de reruns, fragmentos o conservación de scroll.

## Qué NO repetir

No recrear `pilot_data`, no reincorporar los 138 originales y no ejecutar `db-upgrade`. No repetir onboarding, catálogo/incorporación, audiovisual, OCR general, OCR regional, envío masivo a revisión, revisión general de documentos, validaciones Streamlit RC17-RC18 ni la validación funcional ya cerrada de `Entidades y menciones`, salvo una regresión concreta. `GRAPH-03` está validado y cerrado. `DISC-03` sigue pendiente para afinar el descubrimiento de entidades mediante corpus diverso y no se optimiza a partir de ejemplos aislados del piloto.

La validación de RC27 sí debe recorrer transversalmente la **interfaz** porque el nuevo contrato de ayuda afecta todas las secciones y pestañas. No requiere repetir las operaciones de dominio que ya están cerradas.

## Rodeo vigente: UX-04 / foco RC27

La investigación de base está en `docs/historico/diseno/INVESTIGACION_UI_UX_STREAMLIT_UX04_20260820.md`. Los patrones aprobados están en `.assistant/05_CRITERIOS_INTERFAZ.md` y son política transversal.

RC27 elimina todos los badges `?` introducidos como ayuda en RC26. La redacción de ayuda queda centralizada en `src/archive_workbench/ui_help.py`. Los títulos de sección y pestaña reciben `title` y `aria-description` mediante un componente v2 sin salida visual y sin comunicación de estado a Python. Los selectores compactos que sustituyen una segunda barra de pestañas muestran del mismo modo la explicación de la tarea activa. `tracked_tabs(...)` recibe la ayuda de todas las pestañas actuales y los tests controlan la cobertura.

La política canónica exige desde RC27 que una sección, pestaña o tarea nueva o renombrada incorpore su explicación en el mismo cambio. No se admiten signos `?`, iconos de ayuda paralelos ni la eliminación silenciosa de orientación. Las advertencias materiales permanecen visibles.

La validación manual pendiente es completa sobre la UI: recorrer todas las secciones, pestañas y tareas principales, comprobar las ayudas al posar el cursor y detectar cualquier redacción ambigua, referente implícito o superficie todavía sobrecargada. También hay que confirmar que las correcciones aceptadas de RC26 no hayan sufrido regresiones.

## Punto exacto del PILOT-01

El recorrido principal estaba en **Relaciones** y permanece temporalmente detenido por `UX-04`. Si RC27 queda validada, cerrar `UX-04` y retomar exactamente:

`Relaciones -> búsqueda literal -> búsqueda semántica -> grafo -> exportación -> asignación/revisión cruzada -> checkpoint/bundle -> backup/prueba de recuperación`

Consultar `docs/operativos/PENDIENTES_ACTIVOS.md` como única lista de trabajo abierto. Antes de indicar controles de UI, verificar nombres, tipos y orden contra el código vigente. En PILOT-01, si una interfaz no se entiende sin explicación externa, registrar primero el hallazgo y sólo después destrabar la prueba. `UX-02` queda reservado para la revisión integral final, donde se volverán a recorrer remanentes o densificaciones que hayan quedado fuera de este rodeo.
