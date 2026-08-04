# Reparación conjunta de menciones coincidentes — 0.62.0

## Alcance

Esta versión completa el último bloque funcional previsto de `DATA-01`: resolver conjuntos con tres o más menciones activas que convergen sobre el mismo fragmento y permitir operaciones agrupadas solo cuando todas las menciones comparten una decisión verificable.

## Conjuntos de tres o más menciones

Un conjunto se presenta como `duplicate_group` cuando:

- todas las menciones pertenecen al mismo objeto textual;
- todas proyectan exactamente sobre el mismo intervalo del texto vigente;
- el conjunto activo contiene al menos tres menciones;
- cada fila coincide con su último snapshot.

La interfaz muestra el conjunto completo y obliga a elegir una única mención ganadora: no permite resolver pares aislados dentro del conjunto.

La operación es transaccional: antes de modificar nada vuelve a verificar las revisiones, los snapshots, la revisión textual, los offsets proyectados y la composición exacta del conjunto activo. Si cambió cualquiera de esas condiciones, no aplica ninguna escritura.

Las menciones no elegidas pasan a `rejected` mediante `repair_group_duplicate_rejected`. La ganadora agrega:

- `repair_group_duplicate_relocated` si pertenecía a una revisión textual anterior y debe reubicarse;
- `repair_group_duplicate_kept` si ya estaba ubicada en el texto vigente.

No se eliminan filas, no se fusionan entidades y no se reescriben snapshots previos.

## Reubicaciones seguras agrupadas

Las reubicaciones `safe_relocation` pueden agruparse únicamente cuando:

- pertenecen al mismo objeto textual vigente;
- cada fragmento conserva una proyección única;
- ninguna ubicación colisiona con otra mención activa;
- todas las filas coinciden con su último snapshot.

La operación vuelve a validar el conjunto completo antes de escribir. Si una sola mención dejó de ser segura, se cancela toda la transacción. Cada mención reubicada agrega su propia revisión `repair_group_relocation`; el agrupamiento no reemplaza la trazabilidad individual.

## Proyecto de validación

`scripts/create_grouped_mention_validation_project.py` crea una copia descartable con:

- un conjunto de tres menciones coincidentes, dos históricas y una vigente;
- tres menciones distintas con reubicación segura sobre el mismo objeto.

La prueba manual debe conservar la entidad histórica beta dentro del conjunto y aplicar después la reubicación agrupada de las tres menciones seguras. El proyecto de origen nunca se modifica.
