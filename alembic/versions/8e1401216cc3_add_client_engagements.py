"""add client_engagements — R4: the contract wrapper around a client's projects

Revision ID: 8e1401216cc3
Revises: 60f9c03628d2
Create Date: 2026-11-22
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "8e1401216cc3"
down_revision = "60f9c03628d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "engagements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("contract_value", sa.String(length=50), nullable=True),
        sa.Column("pmo_lead_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["pmo_lead_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_engagements_id"), "engagements", ["id"], unique=False)
    op.create_index(op.f("ix_engagements_tenant_id"), "engagements", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_engagements_tenant_id"), table_name="engagements")
    op.drop_index(op.f("ix_engagements_id"), table_name="engagements")
    op.drop_table("engagements")
