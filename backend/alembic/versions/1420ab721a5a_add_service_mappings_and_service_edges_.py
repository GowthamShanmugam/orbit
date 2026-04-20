"""add service_mappings and service_edges tables

Revision ID: 1420ab721a5a
Revises: u8v9w0x1y2z3
Create Date: 2026-04-20 15:40:32.634637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1420ab721a5a'
down_revision: Union[str, None] = 'u8v9w0x1y2z3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('service_mappings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('cluster_id', sa.UUID(), nullable=False),
    sa.Column('deployment_name', sa.String(length=512), nullable=False),
    sa.Column('deployment_namespace', sa.String(length=255), nullable=False),
    sa.Column('context_source_id', sa.UUID(), nullable=True),
    sa.Column('is_infrastructure', sa.Boolean(), nullable=False),
    sa.Column('node_position_x', sa.Float(), nullable=False),
    sa.Column('node_position_y', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['cluster_id'], ['project_clusters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['context_source_id'], ['context_sources.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_service_mappings_cluster_id'), 'service_mappings', ['cluster_id'], unique=False)
    op.create_index(op.f('ix_service_mappings_project_id'), 'service_mappings', ['project_id'], unique=False)
    op.create_table('service_edges',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('source_mapping_id', sa.UUID(), nullable=False),
    sa.Column('target_mapping_id', sa.UUID(), nullable=False),
    sa.Column('label', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_mapping_id'], ['service_mappings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_mapping_id'], ['service_mappings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_service_edges_project_id'), 'service_edges', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_service_edges_project_id'), table_name='service_edges')
    op.drop_table('service_edges')
    op.drop_index(op.f('ix_service_mappings_project_id'), table_name='service_mappings')
    op.drop_index(op.f('ix_service_mappings_cluster_id'), table_name='service_mappings')
    op.drop_table('service_mappings')
