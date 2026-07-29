from __future__ import annotations

from archive_workbench.contracts.changes import ChangeEvent, MergeAssessment
from archive_workbench.contracts.decisions import MergeDecisions
from archive_workbench.domain.enums import ChangeOperation, MergeDisposition


def assess_pair(
    local: ChangeEvent,
    incoming: ChangeEvent,
    rules: MergeDecisions,
) -> MergeAssessment:
    if local.event_id == incoming.event_id:
        return MergeAssessment(
            disposition=MergeDisposition.DUPLICATE,
            reason="El evento ya fue importado.",
            local_event_id=local.event_id,
            incoming_event_id=incoming.event_id,
        )

    if (local.entity_type, local.entity_id) != (incoming.entity_type, incoming.entity_id):
        return MergeAssessment(
            disposition=MergeDisposition.APPLY,
            reason="Los eventos afectan objetos diferentes.",
            local_event_id=local.event_id,
            incoming_event_id=incoming.event_id,
        )

    if local.operation == ChangeOperation.DELETE or incoming.operation == ChangeOperation.DELETE:
        if local.operation != incoming.operation and rules.delete_vs_update_is_conflict:
            return MergeAssessment(
                disposition=MergeDisposition.CONFLICT,
                reason="Una versión elimina el objeto y la otra lo modifica.",
                local_event_id=local.event_id,
                incoming_event_id=incoming.event_id,
            )

    if local.operation == incoming.operation and local.changed_fields == incoming.changed_fields:
        return MergeAssessment(
            disposition=MergeDisposition.DUPLICATE,
            reason="Ambas copias registraron el mismo cambio sobre la misma entidad.",
            local_event_id=local.event_id,
            incoming_event_id=incoming.event_id,
        )

    if local.operation == ChangeOperation.DELETE and incoming.operation == ChangeOperation.DELETE:
        return MergeAssessment(
            disposition=MergeDisposition.DUPLICATE,
            reason="Ambas copias eliminaron la misma entidad.",
            local_event_id=local.event_id,
            incoming_event_id=incoming.event_id,
        )

    if local.operation == ChangeOperation.CREATE and incoming.operation == ChangeOperation.CREATE:
        return MergeAssessment(
            disposition=MergeDisposition.CONFLICT,
            reason="Dos creaciones incompatibles usan la misma identidad.",
            local_event_id=local.event_id,
            incoming_event_id=incoming.event_id,
        )

    local_fields = set(local.changed_fields)
    incoming_fields = set(incoming.changed_fields)
    overlap = sorted(local_fields & incoming_fields)

    if overlap:
        return MergeAssessment(
            disposition=MergeDisposition.CONFLICT,
            reason="Ambas versiones modifican los mismos campos.",
            local_event_id=local.event_id,
            incoming_event_id=incoming.event_id,
            overlapping_fields=overlap,
        )

    if local.base_revision != incoming.base_revision:
        return MergeAssessment(
            disposition=MergeDisposition.REVIEW,
            reason="Los cambios son disjuntos, pero parten de revisiones de base distintas.",
            local_event_id=local.event_id,
            incoming_event_id=incoming.event_id,
        )

    if rules.allow_disjoint_field_merge:
        return MergeAssessment(
            disposition=MergeDisposition.APPLY,
            reason="Los cambios afectan campos diferentes y comparten la misma revisión de base.",
            local_event_id=local.event_id,
            incoming_event_id=incoming.event_id,
        )

    return MergeAssessment(
        disposition=MergeDisposition.REVIEW,
        reason="La política del proyecto no combina automáticamente campos disjuntos.",
        local_event_id=local.event_id,
        incoming_event_id=incoming.event_id,
    )
