from archive_workbench.contracts.changes import ChangeEvent
from archive_workbench.contracts.decisions import MergeDecisions
from archive_workbench.domain.enums import ChangeOperation, MergeDisposition
from archive_workbench.merge import assess_pair


def event(event_id: str, fields: dict, base: int = 1) -> ChangeEvent:
    return ChangeEvent(
        event_id=event_id,
        project_id="test",
        workspace_id="workspace-test",
        sequence_number=1 if event_id == "a" else 2,
        transaction_id=f"tx-{event_id}",
        entity_type="archival_unit",
        entity_id="unit-1",
        operation=ChangeOperation.UPDATE,
        base_revision=base,
        new_revision=base + 1,
        changed_fields=fields,
        actor="tester",
    )


def test_disjoint_fields_can_merge() -> None:
    result = assess_pair(event("a", {"title": "A"}), event("b", {"scope_content": "B"}), MergeDecisions())
    assert result.disposition == MergeDisposition.APPLY


def test_same_field_conflicts() -> None:
    result = assess_pair(event("a", {"title": "A"}), event("b", {"title": "B"}), MergeDecisions())
    assert result.disposition == MergeDisposition.CONFLICT
    assert result.overlapping_fields == ["title"]
