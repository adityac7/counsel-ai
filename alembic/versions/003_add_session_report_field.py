"""Add report text field to sessions table.

Revision ID: 003_add_report
Revises: 002
Create Date: 2026-03-15
"""

from alembic import op
import sqlalchemy as sa

revision = "003_add_report"
down_revision = None  # standalone — safe to run on existing DB
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(sa.Column("report", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_column("report")
