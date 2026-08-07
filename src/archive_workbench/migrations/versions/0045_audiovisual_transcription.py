"""Registro audiovisual y transcripción segmentada revisable.

Revision ID: 0045_audiovisual_transcription
Revises: 0044_layout_structure_review
Create Date: 2026-08-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0045_audiovisual_transcription"
down_revision = "0044_layout_structure_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audiovisual_media",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "digital_object_id",
            sa.String(length=36),
            sa.ForeignKey("digital_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("producer", sa.Text(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("responsible", sa.Text(), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("recorded_date", sa.Date(), nullable=True),
        sa.Column("rights", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("container_format", sa.String(length=100), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("audio_codec", sa.String(length=100), nullable=True),
        sa.Column("video_codec", sa.String(length=100), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("sample_rate_hz", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("frame_rate", sa.Float(), nullable=True),
        sa.Column("technical_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("digital_object_id", name="uq_audiovisual_media_digital_object"),
    )
    op.create_index(
        "ix_audiovisual_media_digital_object", "audiovisual_media", ["digital_object_id"]
    )

    op.create_table(
        "audiovisual_derivative_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "audiovisual_media_id",
            sa.String(length=36),
            sa.ForeignKey("audiovisual_media.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_kind", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("container_format", sa.String(length=100), nullable=True),
        sa.Column("codec", sa.String(length=100), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("ffmpeg_version", sa.Text(), nullable=True),
        sa.Column("command_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "audiovisual_media_id", "asset_kind", "sha256", name="uq_audiovisual_derivative_asset"
        ),
    )
    op.create_index(
        "ix_audiovisual_derivative_media",
        "audiovisual_derivative_assets",
        ["audiovisual_media_id", "asset_kind"],
    )

    op.create_table(
        "transcription_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "audiovisual_media_id",
            sa.String(length=36),
            sa.ForeignKey("audiovisual_media.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_asset_id",
            sa.String(length=36),
            sa.ForeignKey("audiovisual_derivative_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("backend", sa.String(length=100), nullable=False),
        sa.Column("backend_version", sa.String(length=100), nullable=True),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("device", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("options_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_transcription_runs_media_created",
        "transcription_runs",
        ["audiovisual_media_id", "created_at"],
    )

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "transcription_run_id",
            sa.String(length=36),
            sa.ForeignKey("transcription_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("corrected_text", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("start_time >= 0", name="ck_transcript_segment_start_nonnegative"),
        sa.CheckConstraint("end_time >= start_time", name="ck_transcript_segment_time_order"),
        sa.UniqueConstraint(
            "transcription_run_id", "segment_index", name="uq_transcript_segment_index"
        ),
    )
    op.create_index(
        "ix_transcript_segments_run_time",
        "transcript_segments",
        ["transcription_run_id", "start_time"],
    )

    op.create_table(
        "transcript_segment_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "segment_id",
            sa.String(length=36),
            sa.ForeignKey("transcript_segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=200), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "segment_id", "revision_number", name="uq_transcript_segment_revision"
        ),
    )
    op.create_index(
        "ix_transcript_segment_revisions_segment",
        "transcript_segment_revisions",
        ["segment_id", "revision_number"],
    )

    op.create_table(
        "segment_entity_mentions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "segment_id",
            sa.String(length=36),
            sa.ForeignKey("transcript_segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "authority_id",
            sa.String(length=36),
            sa.ForeignKey("authority_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("mention_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("segment_revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_segment_entity_mentions_segment", "segment_entity_mentions", ["segment_id", "start_offset"]
    )
    op.create_index(
        "ix_segment_entity_mentions_authority", "segment_entity_mentions", ["authority_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_segment_entity_mentions_authority", table_name="segment_entity_mentions")
    op.drop_index("ix_segment_entity_mentions_segment", table_name="segment_entity_mentions")
    op.drop_table("segment_entity_mentions")
    op.drop_index(
        "ix_transcript_segment_revisions_segment", table_name="transcript_segment_revisions"
    )
    op.drop_table("transcript_segment_revisions")
    op.drop_index("ix_transcript_segments_run_time", table_name="transcript_segments")
    op.drop_table("transcript_segments")
    op.drop_index("ix_transcription_runs_media_created", table_name="transcription_runs")
    op.drop_table("transcription_runs")
    op.drop_index("ix_audiovisual_derivative_media", table_name="audiovisual_derivative_assets")
    op.drop_table("audiovisual_derivative_assets")
    op.drop_index("ix_audiovisual_media_digital_object", table_name="audiovisual_media")
    op.drop_table("audiovisual_media")
