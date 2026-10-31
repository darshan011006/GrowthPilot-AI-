"""Queue Canva poster jobs and store poster results.

Builds on b3c1d2e4f5a6, which already adds content_items.creative_brief.
"""
import sqlalchemy as sa
from alembic import op

revision = "a81d0a6f4a21"
down_revision = "b3c1d2e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("content_items") as batch_op:
        batch_op.add_column(sa.Column("canva_poster", sa.JSON(), nullable=True))
    op.create_table(
        "canva_poster_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content_id", sa.Integer(), sa.ForeignKey("content_items.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_canva_poster_jobs_content_id", "canva_poster_jobs", ["content_id"], unique=True)
    op.create_index("ix_canva_poster_jobs_workspace_id", "canva_poster_jobs", ["workspace_id"])
    op.create_index("ix_canva_poster_jobs_status", "canva_poster_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_canva_poster_jobs_status", table_name="canva_poster_jobs")
    op.drop_index("ix_canva_poster_jobs_workspace_id", table_name="canva_poster_jobs")
    op.drop_index("ix_canva_poster_jobs_content_id", table_name="canva_poster_jobs")
    op.drop_table("canva_poster_jobs")
    with op.batch_alter_table("content_items") as batch_op:
        batch_op.drop_column("canva_poster")
