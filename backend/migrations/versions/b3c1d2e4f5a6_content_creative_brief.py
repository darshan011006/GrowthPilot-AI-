"""content items: typed creative brief

Revision ID: b3c1d2e4f5a6
Revises: 97ca687b6ab2
Create Date: 2026-10-31 12:00:00

Adds content_items.creative_brief (JSON, nullable): the CreativeBrief written by the Creative Brief Agent.
"""
import sqlalchemy as sa
from alembic import op

revision = 'b3c1d2e4f5a6'
down_revision = '97ca687b6ab2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('content_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('creative_brief', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('content_items', schema=None) as batch_op:
        batch_op.drop_column('creative_brief')
