"""Anotaciones temporales y hablantes para audio y video."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0046_audiovisual_timeline_annotations"
down_revision = "0045_audiovisual_transcription"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audiovisual_timeline_annotations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "audiovisual_media_id",
            sa.String(length=36),
            sa.ForeignKey("audiovisual_media.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("annotation_type", sa.String(length=32), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "authority_id",
            sa.String(length=36),
            sa.ForeignKey("authority_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "start_time >= 0", name="ck_av_timeline_annotation_start_nonnegative"
        ),
        sa.CheckConstraint(
            "end_time >= start_time", name="ck_av_timeline_annotation_time_order"
        ),
        sa.CheckConstraint(
            "annotation_type IN ('speaker', 'annotation')",
            name="ck_av_timeline_annotation_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_av_timeline_annotation_status",
        ),
    )
    op.create_index(
        "ix_av_timeline_annotation_media_time",
        "audiovisual_timeline_annotations",
        ["audiovisual_media_id", "start_time", "end_time"],
    )
    op.create_index(
        "ix_av_timeline_annotation_authority",
        "audiovisual_timeline_annotations",
        ["authority_id"],
    )

    op.create_table(
        "audiovisual_timeline_annotation_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "annotation_id",
            sa.String(length=36),
            sa.ForeignKey("audiovisual_timeline_annotations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("changed_by", sa.String(length=200), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "annotation_id", "revision_number", name="uq_av_timeline_annotation_revision"
        ),
    )
    op.create_index(
        "ix_av_timeline_annotation_revision",
        "audiovisual_timeline_annotation_revisions",
        ["annotation_id", "revision_number"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_av_timeline_annotation_revision",
        table_name="audiovisual_timeline_annotation_revisions",
    )
    op.drop_table("audiovisual_timeline_annotation_revisions")
    op.drop_index(
        "ix_av_timeline_annotation_authority",
        table_name="audiovisual_timeline_annotations",
    )
    op.drop_index(
        "ix_av_timeline_annotation_media_time",
        table_name="audiovisual_timeline_annotations",
    )
    op.drop_table("audiovisual_timeline_annotations")
