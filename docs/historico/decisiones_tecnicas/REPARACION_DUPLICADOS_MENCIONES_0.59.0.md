# Resolución de menciones duplicadas — Archive Workbench 0.59.0

## Problema

Una mención creada sobre una revisión textual anterior puede proyectarse al texto vigente y coincidir exactamente con otra mención activa ya ubicada allí. El sistema no debe elegir por antigüedad, entidad, origen o confianza sin una decisión humana.

## Alcance implementado

La reparación se habilita únicamente cuando existe una mención histórica y una sola contraparte activa sobre la ubicación proyectada. La interfaz compara ambas y permite elegir:

1. conservar la mención ya ubicada en el texto vigente y retirar la histórica;
2. conservar la mención histórica, retirar la vigente y reubicar la elegida sobre la revisión textual actual.

No se fusionan entidades, notas ni historiales. En esta operación no se elimina físicamente ninguna mención.

## Operaciones auditables

- `repair_duplicate_rejected`: marca como `rejected` la mención que no se conserva y agrega un snapshot nuevo.
- `repair_duplicate_relocated`: reubica la mención histórica elegida, actualiza sus offsets y revisión textual y agrega un snapshot nuevo.

Cuando se conserva la mención vigente, esta no recibe una revisión artificial porque sus datos no cambian. La decisión queda documentada en la revisión agregada a la mención histórica retirada.

## Condiciones de seguridad

- Las dos menciones deben pertenecer al mismo objeto textual.
- Ambas filas deben coincidir con sus últimos snapshots.
- Las revisiones enviadas por el formulario deben seguir vigentes.
- La revisión y la ubicación del texto no pueden haber cambiado después de mostrar la alerta.
- Debe existir exactamente una contraparte activa sobre la ubicación proyectada.
- La decisión exige actor, fundamento y confirmación explícita.
- Cualquier error revierte la transacción completa.

Los conjuntos con dos o más contrapartes continúan bloqueados: requieren una revisión conjunta y no se reducen automáticamente a decisiones binarias.

## Validación descartable

`scripts/create_duplicate_mention_validation_project.py` crea una copia del proyecto y agrega dos pares independientes:

- alfa: conservar la mención vigente y retirar la histórica;
- beta: conservar la histórica, retirar la vigente y reubicar la elegida.

La copia usa frases completas y entidades diferentes para que la comparación y la decisión sean visibles. El proyecto de origen no se modifica.
