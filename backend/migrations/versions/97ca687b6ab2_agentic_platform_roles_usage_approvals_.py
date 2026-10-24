"""agentic platform: roles, usage, approvals, variants, catalogue provenance

Revision ID: 97ca687b6ab2
Revises: 805df7dfd1b1
Create Date: 2026-10-24 20:21:58.236040

Adds: specialist roles/effects/cost on agent steps, run cost budgets and pause/recovery, usage records, a search
cache, non-content approval requests, platform variants (content_items.master_id), approval hashes, catalogue
provenance on products, brand marketing profile fields, campaign strategy fields, experiment baselines, and a
check constraint that approved/scheduled/published content carries an approval of its current version.
"""
import sqlalchemy as sa
from alembic import op

revision = '97ca687b6ab2'
down_revision = '805df7dfd1b1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('cache_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('request', sa.JSON(), nullable=False),
    sa.Column('response', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('cache_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_cache_entries_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_cache_entries_key_hash'), ['key_hash'], unique=True)

    op.create_table('approval_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.String(length=32), nullable=True),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('requested_at', sa.DateTime(), nullable=False),
    sa.Column('decided_by', sa.Integer(), nullable=True),
    sa.Column('decided_at', sa.DateTime(), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('approval_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approval_requests_run_id'), ['run_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_requests_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_requests_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('usage_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workspace_id', sa.Integer(), nullable=True),
    sa.Column('run_id', sa.String(length=32), nullable=True),
    sa.Column('campaign_id', sa.Integer(), nullable=True),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('operation', sa.String(length=60), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('units', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Double(), nullable=False),
    sa.Column('cached', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('usage_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_usage_records_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_usage_records_run_id'), ['run_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_usage_records_workspace_id'), ['workspace_id'], unique=False)

    with op.batch_alter_table('agent_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cost_usd', sa.Double(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('cost_budget_usd', sa.Double(), nullable=False, server_default='0.5'))
        batch_op.add_column(sa.Column('pause_requested', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('recoveries', sa.Integer(), nullable=False, server_default='0'))

    with op.batch_alter_table('agent_steps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(length=30), nullable=False, server_default='orchestrator'))
        batch_op.add_column(sa.Column('effect', sa.String(length=30), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('cost_usd', sa.Double(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('evidence_ids', sa.JSON(), nullable=False, server_default='[]'))

    with op.batch_alter_table('assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('origin_url', sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column('sha256', sa.String(length=64), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('meta', sa.JSON(), nullable=False, server_default='{}'))
        batch_op.add_column(sa.Column('campaign_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_assets_campaign_id', 'campaigns', ['campaign_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('brands', schema=None) as batch_op:
        batch_op.add_column(sa.Column('content_pillars', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('languages', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('marketing_objectives', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('platform_preferences', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('posting_constraints', sa.JSON(), nullable=False, server_default='{}'))
        batch_op.add_column(sa.Column('campaign_budget_usd', sa.Double(), nullable=True))
        batch_op.add_column(sa.Column('fonts', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('profile_sources', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('catalogue_source', sa.JSON(), nullable=False, server_default='{}'))

    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('objective_metric', sa.String(length=60), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('channel_mix', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('budget_usd', sa.Double(), nullable=True))
        batch_op.add_column(sa.Column('budget_allocation', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('baseline', sa.JSON(), nullable=False, server_default='{}'))
        batch_op.add_column(sa.Column('evaluation_window_days', sa.Integer(), nullable=False, server_default='7'))
        batch_op.add_column(sa.Column('strategy', sa.JSON(), nullable=False, server_default='{}'))

    with op.batch_alter_table('content_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('master_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('approved_hash', sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f('ix_content_items_master_id'), ['master_id'], unique=False)
        batch_op.create_foreign_key('fk_content_items_master_id', 'content_items', ['master_id'], ['id'],
                                    ondelete='SET NULL')
        batch_op.create_check_constraint(
            'ck_content_approved_version_current',
            "status NOT IN ('approved', 'scheduled', 'publishing', 'published') OR "
            "(approved_version IS NOT NULL AND approved_version = version)")

    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('intervention', sa.Text(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('baseline', sa.JSON(), nullable=False, server_default='{}'))
        batch_op.add_column(sa.Column('evaluation_window_days', sa.Integer(), nullable=False, server_default='7'))
        batch_op.add_column(sa.Column('comparison_method', sa.Text(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('confidence', sa.String(length=20), nullable=False, server_default=''))

    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_url', sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column('source_ref', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('retrieved_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('mrp', sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column('stock', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('allow_backorder', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('variants', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('image_urls', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('image_kind', sa.String(length=20), nullable=False, server_default='none'))
        batch_op.add_column(sa.Column('name_local', sa.String(length=255), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('flags', sa.JSON(), nullable=False, server_default='{}'))
        batch_op.add_column(sa.Column('delivery', sa.JSON(), nullable=False, server_default='{}'))
        batch_op.add_column(sa.Column('data_quality', sa.JSON(), nullable=False, server_default='[]'))

    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('proposed_change', sa.JSON(), nullable=False, server_default='{}'))
        batch_op.add_column(sa.Column('decided_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('decided_at', sa.DateTime(), nullable=True))
        batch_op.create_foreign_key('fk_recommendations_decided_by', 'users', ['decided_by'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.add_column(sa.Column('run_budget_usd', sa.Double(), nullable=False, server_default='0.5'))
        batch_op.add_column(sa.Column('monthly_budget_usd', sa.Double(), nullable=False, server_default='10'))
        batch_op.add_column(sa.Column('approval_threshold_usd', sa.Double(), nullable=False, server_default='0.25'))
        batch_op.add_column(sa.Column('search_requests_per_run', sa.Integer(), nullable=False, server_default='8'))
        batch_op.add_column(sa.Column('search_requests_per_day', sa.Integer(), nullable=False, server_default='40'))



def downgrade() -> None:
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.drop_column('search_requests_per_day')
        batch_op.drop_column('search_requests_per_run')
        batch_op.drop_column('approval_threshold_usd')
        batch_op.drop_column('monthly_budget_usd')
        batch_op.drop_column('run_budget_usd')

    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_recommendations_decided_by', type_='foreignkey')
        batch_op.drop_column('decided_at')
        batch_op.drop_column('decided_by')
        batch_op.drop_column('proposed_change')

    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('data_quality')
        batch_op.drop_column('delivery')
        batch_op.drop_column('flags')
        batch_op.drop_column('name_local')
        batch_op.drop_column('image_kind')
        batch_op.drop_column('image_urls')
        batch_op.drop_column('variants')
        batch_op.drop_column('allow_backorder')
        batch_op.drop_column('stock')
        batch_op.drop_column('mrp')
        batch_op.drop_column('retrieved_at')
        batch_op.drop_column('source_ref')
        batch_op.drop_column('source_url')

    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.drop_column('confidence')
        batch_op.drop_column('comparison_method')
        batch_op.drop_column('evaluation_window_days')
        batch_op.drop_column('baseline')
        batch_op.drop_column('intervention')

    with op.batch_alter_table('content_items', schema=None) as batch_op:
        batch_op.drop_constraint('ck_content_approved_version_current', type_='check')
        batch_op.drop_constraint('fk_content_items_master_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_content_items_master_id'))
        batch_op.drop_column('approved_hash')
        batch_op.drop_column('master_id')

    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('strategy')
        batch_op.drop_column('evaluation_window_days')
        batch_op.drop_column('baseline')
        batch_op.drop_column('budget_allocation')
        batch_op.drop_column('budget_usd')
        batch_op.drop_column('channel_mix')
        batch_op.drop_column('objective_metric')

    with op.batch_alter_table('brands', schema=None) as batch_op:
        batch_op.drop_column('catalogue_source')
        batch_op.drop_column('profile_sources')
        batch_op.drop_column('fonts')
        batch_op.drop_column('campaign_budget_usd')
        batch_op.drop_column('posting_constraints')
        batch_op.drop_column('platform_preferences')
        batch_op.drop_column('marketing_objectives')
        batch_op.drop_column('languages')
        batch_op.drop_column('content_pillars')

    with op.batch_alter_table('assets', schema=None) as batch_op:
        batch_op.drop_constraint('fk_assets_campaign_id', type_='foreignkey')
        batch_op.drop_column('campaign_id')
        batch_op.drop_column('meta')
        batch_op.drop_column('sha256')
        batch_op.drop_column('origin_url')

    with op.batch_alter_table('agent_steps', schema=None) as batch_op:
        batch_op.drop_column('evidence_ids')
        batch_op.drop_column('cost_usd')
        batch_op.drop_column('effect')
        batch_op.drop_column('role')

    with op.batch_alter_table('agent_runs', schema=None) as batch_op:
        batch_op.drop_column('recoveries')
        batch_op.drop_column('pause_requested')
        batch_op.drop_column('cost_budget_usd')
        batch_op.drop_column('cost_usd')

    with op.batch_alter_table('usage_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_usage_records_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_usage_records_run_id'))
        batch_op.drop_index(batch_op.f('ix_usage_records_created_at'))

    op.drop_table('usage_records')
    with op.batch_alter_table('approval_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_approval_requests_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_approval_requests_status'))
        batch_op.drop_index(batch_op.f('ix_approval_requests_run_id'))

    op.drop_table('approval_requests')
    with op.batch_alter_table('cache_entries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_cache_entries_key_hash'))
        batch_op.drop_index(batch_op.f('ix_cache_entries_expires_at'))

    op.drop_table('cache_entries')
