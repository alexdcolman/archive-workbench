from __future__ import annotations

from collections import Counter, defaultdict
from typing import Literal

from pydantic import Field, model_validator

from archive_workbench.contracts.common import ContractModel


class ArchivalLevelDefinition(ContractModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    plural_label: str = Field(min_length=1)
    display_order: int = Field(ge=0)
    parent_keys: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    optional: bool = True
    enabled: bool = True


class DescriptiveFieldDefinition(ContractModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    applies_to_levels: list[str] = Field(default_factory=lambda: ["all"])
    required: bool = False
    repeatable: bool = False
    data_type: Literal["text", "date", "date_range", "integer", "number", "boolean", "list"] = "text"
    supports_list: bool = False
    examples: list[str] = Field(default_factory=list)
    enabled: bool = True


class CatalogDecisions(ContractModel):
    structure_profiles_by_fund: bool = True
    allow_skipped_levels: bool = True
    provisional_registration_allowed: bool = True
    required_root_levels: list[str] = Field(default_factory=lambda: ["archivo", "fondo"])
    completion_any_of_levels: list[list[str]] = Field(default_factory=list)
    field_value_states: list[Literal["provided", "no_information", "not_applicable", "pending"]] = (
        Field(default_factory=lambda: ["provided", "no_information", "not_applicable", "pending"])
    )
    manual_completion_confirmation: bool = True
    separate_incomplete_inventory: bool = True


class ObjectTypeDefinition(ContractModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    category: Literal["text", "structure", "visual", "paratext", "other"]
    visible_by_default: bool = True
    editable: bool = True
    searchable: bool = True
    export_by_default: bool = True
    text_exportable: bool = True
    asset_exportable: bool = False
    supports_manual_transcription: bool = True
    can_have_children: bool = False


class JsonlDecisions(ContractModel):
    schema_version: str = "1.0"
    objects_filename: str = "objects.jsonl"
    paragraphs_filename: str = "paragraphs.jsonl"
    images_filename: str = "images.jsonl"
    manifest_filename: str = "manifest.json"
    image_storage: Literal["referenced", "embedded"] = "referenced"
    base64_export_available: bool = False
    coordinate_space: Literal["normalized", "pixels", "pdf_points"] = "normalized"


class IdentityDecisions(ContractModel):
    entity_ids: Literal["uuid4"] = "uuid4"
    digital_object_identity: Literal["sha256"] = "sha256"
    same_sha256_policy: Literal["same_digital_object"] = "same_digital_object"
    preserve_original_filename: bool = True
    paths_are_identity: bool = False
    extraction_identity_fields: list[str] = Field(
        default_factory=lambda: ["digital_object_id", "source_sha256", "engine", "options_hash"]
    )
    reextraction_policy: Literal["preserve_versions_mark_current"] = "preserve_versions_mark_current"
    better_scan_policy: Literal["new_linked_representation"] = "new_linked_representation"
    text_object_ids_survive_reordering: bool = True
    split_merge_use_lineage: bool = True


class MergeDecisions(ContractModel):
    additive_entity_types: list[str] = Field(
        default_factory=lambda: [
            "annotation",
            "tag_assignment",
            "entity_mention",
            "relation",
        ]
    )
    exclusive_fields: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "archival_unit": ["parent_id", "level_key", "reference_code", "title"],
            "text_object": ["edited_text", "object_type", "part_id", "superseded_by"],
            "extraction_run": ["is_current"],
        }
    )
    allow_disjoint_field_merge: bool = True
    conflict_requires_admin_confirmation: bool = True
    delete_vs_update_is_conflict: bool = True


class TiffDecisions(ContractModel):
    preserve_original: bool = True
    accept_single_page: bool = True
    accept_multipage: bool = True
    split_multipage_for_processing: bool = True
    ocr_derivative_format: Literal["png", "tiff"] = "png"
    preview_format: Literal["webp", "jpeg", "png"] = "webp"
    target_ocr_dpi: int = Field(default=300, ge=150, le=600)
    preview_dpi: int = Field(default=150, ge=72, le=300)
    use_pyvips_when_available: bool = True
    never_overwrite_source: bool = True


class ProjectDecisions(ContractModel):
    project_name: str = Field(min_length=1)
    project_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    archival_levels: list[ArchivalLevelDefinition]
    descriptive_fields: list[DescriptiveFieldDefinition] = Field(default_factory=list)
    catalog: CatalogDecisions = Field(default_factory=CatalogDecisions)
    object_types: list[ObjectTypeDefinition]
    jsonl: JsonlDecisions = Field(default_factory=JsonlDecisions)
    identity: IdentityDecisions = Field(default_factory=IdentityDecisions)
    merge: MergeDecisions = Field(default_factory=MergeDecisions)
    tiff: TiffDecisions = Field(default_factory=TiffDecisions)

    @model_validator(mode="after")
    def validate_catalogs(self) -> "ProjectDecisions":
        level_keys = [item.key for item in self.archival_levels]
        object_keys = [item.key for item in self.object_types]
        field_keys = [item.key for item in self.descriptive_fields]
        duplicate_levels = [key for key, count in Counter(level_keys).items() if count > 1]
        duplicate_objects = [key for key, count in Counter(object_keys).items() if count > 1]
        duplicate_fields = [key for key, count in Counter(field_keys).items() if count > 1]
        if duplicate_levels:
            raise ValueError(f"Niveles archivísticos duplicados: {duplicate_levels}")
        if duplicate_objects:
            raise ValueError(f"Tipos de objeto duplicados: {duplicate_objects}")
        if duplicate_fields:
            raise ValueError(f"Campos descriptivos duplicados: {duplicate_fields}")

        known = set(level_keys)
        for level in self.archival_levels:
            unknown = sorted(set(level.parent_keys) - known)
            if unknown:
                raise ValueError(f"{level.key}: parent_keys desconocidos: {unknown}")
            if level.key in level.parent_keys:
                raise ValueError(f"{level.key}: no puede ser padre de sí mismo")

        for field in self.descriptive_fields:
            unknown = sorted(set(field.applies_to_levels) - known - {"all"})
            if unknown:
                raise ValueError(f"{field.key}: applies_to_levels desconocidos: {unknown}")

        unknown_roots = sorted(set(self.catalog.required_root_levels) - known)
        if unknown_roots:
            raise ValueError(f"required_root_levels desconocidos: {unknown_roots}")
        for group in self.catalog.completion_any_of_levels:
            unknown = sorted(set(group) - known)
            if unknown:
                raise ValueError(f"completion_any_of_levels contiene niveles desconocidos: {unknown}")

        graph: dict[str, list[str]] = defaultdict(list)
        for level in self.archival_levels:
            for parent in level.parent_keys:
                graph[parent].append(level.key)

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError(f"Ciclo detectado en niveles archivísticos, cerca de {node}")
            if node in visited:
                return
            visiting.add(node)
            for child in graph[node]:
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for key in level_keys:
            visit(key)

        orders = [level.display_order for level in self.archival_levels if level.enabled]
        if len(orders) != len(set(orders)):
            raise ValueError("display_order debe ser único entre niveles habilitados")
        if not any(not level.parent_keys for level in self.archival_levels if level.enabled):
            raise ValueError("Debe existir al menos un nivel raíz sin parent_keys")
        return self
