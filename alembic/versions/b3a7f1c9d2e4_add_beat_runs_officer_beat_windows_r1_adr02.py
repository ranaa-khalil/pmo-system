"""add beat_runs — officer beat windows (R1, ADR-02)

Revision ID: b3a7f1c9d2e4
Revises: 228bd174e20a
Create Date: 2026-11-22

The officer beat's idempotency table: one row per (job, window_key) makes a
window run at most once no matter how many times the process restarts
(catch-up-on-start) or how many replicas boot (they also take the Postgres
advisory lock before iterating tenants).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b3a7f1c9d2e4"
down_revision = "228bd174e20a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "beat_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job", sa.String(length=50), nullable=False),
        sa.Column("window_key", sa.String(length=20), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("ran_at", sa.String(), server_default=sa.func.now(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job", "window_key", name="uq_beat_job_window"),
    )
    op.create_index(op.f("ix_beat_runs_id"), "beat_runs", ["id"], unique=False)
    op.create_index(op.f("ix_beat_runs_job"), "beat_runs", ["job"], unique=False)
    op.create_index(op.f("ix_beat_runs_tenant_id"), "beat_runs", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_beat_runs_tenant_id"), table_name="beat_runs")
    op.drop_index(op.f("ix_beat_runs_job"), table_name="beat_runs")
    op.drop_index(op.f("ix_beat_runs_id"), table_name="beat_runs")
    op.drop_table("beat_runs")
