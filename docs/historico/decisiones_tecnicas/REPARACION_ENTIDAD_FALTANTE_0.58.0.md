# Reparación de menciones sin entidad — Archive Workbench 0.58.0

## Problema

Bases históricas o migradas pueden contener menciones con estado `accepted` o `modified` pero sin `authority_id`. Ese estado viola la regla vigente según la cual una mención aceptada o modificada debe estar vinculada a una entidad.

## Decisión

La aplicación ofrece dos decisiones humanas explícitas:

1. `repair_link_authority`: vincular la mención a una entidad activa existente del mismo proyecto, conservando el estado aceptado o modificado.
2. `repair_return_pending`: devolver la mención a `pending`, sin entidad, para que vuelva al circuito ordinario de revisión.

Las dos rutas no reescriben snapshots anteriores, no crean entidades nuevas ni eligen una entidad automáticamente.

## Condiciones de seguridad

- La revisión enviada por el formulario debe coincidir con la revisión vigente de la mención.
- La fila vigente debe coincidir exactamente con su último snapshot.
- La entidad elegida debe existir, estar activa y pertenecer al mismo proyecto.
- Las dos decisiones requieren actor, nota y confirmación explícita.
- Una divergencia de snapshot se presenta como problema previo y bloquea esta reparación.

## Auditoría

Cada decisión incrementa la revisión de la mención y agrega un nuevo `EntityMentionRevision`. El historial conserva la fila inválida anterior y registra quién tomó la decisión, cuándo y con qué fundamento.

## Validación descartable

`scripts/create_missing_authority_validation_project.py` copia un proyecto existente y agrega dos frases completas y no superpuestas. Una mención se destina a vinculación y la otra a retorno a pendiente. El proyecto de origen no se modifica.

La selección de fragmentos del generador de reubicación segura también se corrigió para terminar en límites de palabra; el texto de prueba ya no queda cortado a una cantidad arbitraria de caracteres.
