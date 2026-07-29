from __future__ import annotations

from enum import StrEnum


class MediaType(StrEnum):
    PDF = "pdf"
    TIFF = "tiff"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    OTHER = "other"


class FilePresence(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    MOVED = "moved"
    MODIFIED = "modified"
    UNVERIFIED = "unverified"


class ExtractionStatus(StrEnum):
    REGISTERED = "registered"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChangeOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"


class MergeDisposition(StrEnum):
    APPLY = "apply"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    REVIEW = "review"
