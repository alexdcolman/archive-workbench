from pathlib import Path

from archive_workbench.contracts.archival import ArchivalUnitRecord
from archive_workbench.io.jsonl import read_models, write_models_atomic


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "units.jsonl"
    unit = ArchivalUnitRecord(
        id="u1",
        level_key="legajo",
        title="Legajo 1",
        created_by="Alex",
        updated_by="Alex",
    )
    write_models_atomic(path, [unit])
    loaded = read_models(path, ArchivalUnitRecord)
    assert loaded == [unit]
