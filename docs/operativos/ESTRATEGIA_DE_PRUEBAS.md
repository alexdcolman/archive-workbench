# Estrategia de pruebas — Archive Workbench

## Objetivo

Conservar la cobertura histórica y obtener resultados confiables sin fingir que la suite monolítica terminó cuando el entorno de construcción tiene un límite de tiempo.

## Presentación de comandos

Las guías entregadas a Alex reúnen todas las pruebas relevantes y `pytest --collect-only -q` en un único bloque encadenado con `&&`. Así se ejecuta una sola secuencia y se detiene ante el primer fallo, sin omitir ninguna regresión pertinente.

## Política vigente

En cada versión se ejecutan, en este orden:

1. pruebas unitarias y de integración del subsistema modificado;
2. pruebas transversales pertinentes —base, migraciones, navegación, documentación o empaquetado—;
3. `pytest --collect-only -q` para verificar importación y colección completa;
4. construcción del wheel;
5. suite completa `pytest`, ejecutada exclusivamente por Alex en su equipo local, como validación final cuando corresponda; el asistente nunca la ejecuta.

La entrega debe indicar qué grupos terminaron y no atribuir a la suite completa un resultado que no obtuvo.

## Selección de pruebas

Un cambio documental ejecuta documentación, empaquetado y recopilación. Un cambio de migración ejecuta todas las rutas relevantes de base. Un cambio de interfaz ejecuta su dominio, navegación y regresiones de formularios.

No se repiten recorridos manuales ya validados si el subsistema no cambió. Una regresión manual nueva debe justificar qué condición distinta cubre.

## Cobertura

No eliminar pruebas por ser lentas. Solo podrá retirarse una si existe redundancia exacta demostrada o si el comportamiento fue eliminado deliberadamente.

## Trabajo pendiente

`OPS-02` incorporará marcadores:

- `fast`: pruebas rápidas sin servicios externos;
- `integration`: persistencia o flujos entre subsistemas;
- `slow`: corpus, backends o recorridos de larga duración.

Los marcadores organizarán la ejecución; no reducirán cobertura.


La suite completa es de ejecución exclusiva de Alex. El asistente prepara el comando y revisa la salida, pero nunca ejecuta la corrida monolítica. Esta regla se define canónicamente en `.assistant/03_POLITICA_DE_PRUEBAS.md`. Un gate pendiente no bloquea la entrega del ZIP: se entrega con el estado de validación declarado.
