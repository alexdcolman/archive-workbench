# Resolución manual de ubicaciones de menciones — Archive Workbench 0.60.0

## Problema

Una mención histórica puede dejar de tener una proyección automática única sobre el texto vigente por dos motivos principales:

- el mismo fragmento aparece más de una vez;
- el fragmento ya no aparece porque el texto fue corregido, reemplazado o retirado.

La aplicación no debe elegir una aparición por proximidad ni eliminar la mención silenciosamente.

## Decisión

Los casos `unresolved_relocation` admiten dos rutas explícitas:

1. `repair_manual_relocation`: la persona revisora indica un fragmento literal del texto vigente y elige una aparición concreta. La aplicación verifica revisión textual, offsets, contenido exacto, ausencia de otra mención activa y coincidencia con el último snapshot antes de actualizar la mención.
2. `repair_mark_absent`: solo se habilita cuando el fragmento histórico no aparece en el texto vigente. La mención pasa a `rejected`, pero conserva entidad, texto histórico, offsets, revisión textual y todos los snapshots anteriores.

Las dos operaciones requieren confirmación, responsable y fundamento. Ambas generan una revisión nueva y un evento de intercambio `update`.

## Límites conservadores

- No se normalizan espacios, acentos ni puntuación para localizar el fragmento manual: debe existir literalmente, ignorando solo mayúsculas y minúsculas.
- No se permite marcar como ausente un fragmento que todavía aparece una o más veces.
- No se permite reubicar sobre una ubicación que ya tenga otra mención activa.
- Una revisión textual o una revisión de mención cambiada invalida el formulario.
- Las divergencias entre fila y snapshot continúan bloqueadas.
- Los conjuntos con varias menciones activas sobre la misma ubicación continúan requiriendo revisión conjunta.

## Validación descartable

`scripts/create_unresolved_mention_validation_project.py` crea dos casos:

- una mención histórica con dos apariciones posibles, para elegir manualmente la segunda;
- una mención cuyo fragmento fue retirado, para registrar su ausencia sin borrarla.

La copia se crea fuera del proyecto de origen y puede eliminarse después de validar operaciones, integridad y claves foráneas.
