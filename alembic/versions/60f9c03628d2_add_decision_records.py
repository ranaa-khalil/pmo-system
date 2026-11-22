"""add decision_records — R3: any decision, one place, searchable, chained

Revision ID: 60f9c03628d2
Revises: c5d8e2f4a6b9
Create Date: 2026-11-22
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "60f9c03628d2"
down_revision = "c5d8e2f4a6b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("alternatives", sa.Text(), nullable=True),
        sa.Column("made_by", sa.Integer(), nullable=True),
        sa.Column("made_at", sa.String(), server_default=sa.func.now(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("approval_request_id", sa.Integer(), nullable=True),
        sa.Column("chained_from_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["made_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_id"], ["backlog_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approval_request_id"], ["approval_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chained_from_id"], ["decision_records.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_decision_records_id"), "decision_records", ["id"], unique=False)
    op.create_index(op.f("ix_decision_records_tenant_id"), "decision_records", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_decision_records_tenant_id"), table_name="decision_records")
    op.drop_index(op.f("ix_decision_records_id"), table_name="decision_records")
    op.drop_table("decision_records")
