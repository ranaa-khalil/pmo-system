"""add llm_usage — one row per LLM call (LLM resilience layer)

Revision ID: c5d8e2f4a6b9
Revises: b3a7f1c9d2e4
Create Date: 2026-11-22
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c5d8e2f4a6b9"
down_revision = "b3a7f1c9d2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("feature", sa.String(length=50), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.String(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_usage_id"), "llm_usage", ["id"], unique=False)
    op.create_index(op.f("ix_llm_usage_tenant_id"), "llm_usage", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_llm_usage_feature"), "llm_usage", ["feature"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_usage_feature"), table_name="llm_usage")
    op.drop_index(op.f("ix_llm_usage_tenant_id"), table_name="llm_usage")
    op.drop_index(op.f("ix_llm_usage_id"), table_name="llm_usage")
    op.drop_table("llm_usage")
