"""Initial schema with notes, embeddings, wikilinks, jira_tickets, agent_runs, tags, audit_reports

Revision ID: 001
Revises: 
Create Date: 2026-05-27 14:32:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')
    
    # Create notes table
    op.create_table(
        'notes',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('path', sa.Text(), nullable=False, unique=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('folder', sa.Text(), nullable=False),
        sa.Column('tags', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('type', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.Text(), nullable=False),
        sa.Column('word_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('last_modified', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("type IN ('Story', 'Meeting', 'TechNote', 'Project', 'Template', 'Reference', 'Career', 'Other')", name='notes_type_check'),
        sa.CheckConstraint("status IN ('Backlog', 'Planning', 'In Progress', 'Blocked', 'Done')", name='notes_status_check'),
    )
    op.create_index('idx_notes_folder', 'notes', ['folder'])
    op.create_index('idx_notes_tags', 'notes', ['tags'], postgresql_using='gin')
    op.create_index('idx_notes_type', 'notes', ['type'])
    op.create_index('idx_notes_status', 'notes', ['status'])
    op.create_index('idx_notes_updated_at', 'notes', ['updated_at'])
    op.create_index('idx_notes_last_modified', 'notes', ['last_modified'])
    
    # Create embeddings table
    op.create_table(
        'embeddings',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('note_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vector', Vector(1536), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('generated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('note_id', 'model', name='embeddings_note_id_model_key'),
    )
    op.create_index(
        'embeddings_vector_idx',
        'embeddings',
        ['vector'],
        postgresql_using='ivfflat',
        postgresql_with={'lists': 100},
        postgresql_ops={'vector': 'vector_cosine_ops'}
    )
    
    # Create wikilinks table
    op.create_table(
        'wikilinks',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('source_note_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('target_path', sa.Text(), nullable=False),
        sa.Column('target_note_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('link_text', sa.Text(), nullable=False),
        sa.Column('is_broken', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['source_note_id'], ['notes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_note_id'], ['notes.id'], ondelete='SET NULL'),
    )
    op.create_index('idx_wikilinks_source', 'wikilinks', ['source_note_id'])
    op.create_index('idx_wikilinks_target', 'wikilinks', ['target_note_id'])
    op.create_index('idx_wikilinks_target_path', 'wikilinks', ['target_path'])
    op.create_index('idx_wikilinks_broken', 'wikilinks', ['is_broken'], postgresql_where=sa.text('is_broken = TRUE'))
    
    # Create jira_tickets table
    op.create_table(
        'jira_tickets',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('key', sa.Text(), nullable=False, unique=True),
        sa.Column('note_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('issue_type', sa.Text(), nullable=False),
        sa.Column('priority', sa.Text(), nullable=True),
        sa.Column('assignee', sa.Text(), nullable=True),
        sa.Column('parent_key', sa.Text(), nullable=True),
        sa.Column('repos', postgresql.ARRAY(sa.Text()), server_default='{}'),
        sa.Column('labels', postgresql.ARRAY(sa.Text()), server_default='{}'),
        sa.Column('jira_created_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('jira_updated_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('last_synced_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id'], ondelete='SET NULL'),
    )
    op.create_index('idx_jira_tickets_key', 'jira_tickets', ['key'])
    op.create_index('idx_jira_tickets_status', 'jira_tickets', ['status'])
    op.create_index('idx_jira_tickets_note_id', 'jira_tickets', ['note_id'])
    op.create_index('idx_jira_tickets_updated', 'jira_tickets', ['jira_updated_at'])
    op.create_index('idx_jira_tickets_parent', 'jira_tickets', ['parent_key'])
    
    # Create agent_runs table
    op.create_table(
        'agent_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('crew_name', sa.Text(), nullable=False),
        sa.Column('agent_name', sa.Text(), nullable=True),
        sa.Column('trigger_type', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('notes_processed', sa.Integer(), server_default='0'),
        sa.Column('notes_created', sa.Integer(), server_default='0'),
        sa.Column('notes_updated', sa.Integer(), server_default='0'),
        sa.Column('notes_moved', sa.Integer(), server_default='0'),
        sa.Column('tokens_used', sa.Integer(), server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.CheckConstraint("trigger_type IN ('file_event', 'scheduled', 'manual', 'api')", name='agent_runs_trigger_type_check'),
        sa.CheckConstraint("status IN ('running', 'success', 'failed', 'cancelled')", name='agent_runs_status_check'),
        sa.CheckConstraint(
            "(status = 'running' AND completed_at IS NULL) OR (status != 'running' AND completed_at IS NOT NULL)",
            name='agent_runs_completion_check'
        ),
    )
    op.create_index('idx_agent_runs_crew', 'agent_runs', ['crew_name'])
    op.create_index('idx_agent_runs_agent', 'agent_runs', ['agent_name'])
    op.create_index('idx_agent_runs_started', 'agent_runs', [sa.text('started_at DESC')])
    op.create_index('idx_agent_runs_status', 'agent_runs', ['status'])
    op.create_index('idx_agent_runs_trigger', 'agent_runs', ['trigger_type'])
    op.create_index('idx_agent_runs_metadata', 'agent_runs', ['metadata'], postgresql_using='gin')
    
    # Create tags table
    op.create_table(
        'tags',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False, unique=True),
        sa.Column('normalized_name', sa.Text(), nullable=False),
        sa.Column('usage_count', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )
    op.create_index('idx_tags_name', 'tags', ['name'])
    op.create_index('idx_tags_normalized', 'tags', ['normalized_name'])
    op.create_index('idx_tags_usage', 'tags', [sa.text('usage_count DESC')])
    
    # Create audit_reports table
    op.create_table(
        'audit_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('agent_run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('report_type', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('findings_count', sa.Integer(), server_default='0'),
        sa.Column('findings', postgresql.JSONB(), server_default='[]'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], ondelete='CASCADE'),
        sa.CheckConstraint("report_type IN ('daily_audit', 'stale_notes', 'broken_links', 'orphans', 'weekly_digest')", name='audit_reports_type_check'),
    )
    op.create_index('idx_audit_reports_type', 'audit_reports', ['report_type'])
    op.create_index('idx_audit_reports_created', 'audit_reports', [sa.text('created_at DESC')])
    op.create_index('idx_audit_reports_run', 'audit_reports', ['agent_run_id'])
    
    # Create trigger functions
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # Create triggers
    op.execute("""
        CREATE TRIGGER update_notes_updated_at BEFORE UPDATE ON notes
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)
    op.execute("""
        CREATE TRIGGER update_wikilinks_updated_at BEFORE UPDATE ON wikilinks
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)
    op.execute("""
        CREATE TRIGGER update_tags_updated_at BEFORE UPDATE ON tags
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)
    
    # Create tag sync function
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_tag_usage_counts()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
                INSERT INTO tags (name, normalized_name, usage_count)
                SELECT unnest(NEW.tags), LOWER(unnest(NEW.tags)), 1
                ON CONFLICT (name) DO UPDATE SET usage_count = tags.usage_count + 1;
            END IF;
            
            IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND OLD.tags IS DISTINCT FROM NEW.tags) THEN
                UPDATE tags SET usage_count = GREATEST(0, usage_count - 1)
                WHERE name = ANY(OLD.tags);
            END IF;
            
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    op.execute("""
        CREATE TRIGGER sync_note_tags AFTER INSERT OR UPDATE OR DELETE ON notes
            FOR EACH ROW EXECUTE FUNCTION sync_tag_usage_counts();
    """)


def downgrade() -> None:
    # Drop triggers
    op.execute('DROP TRIGGER IF EXISTS sync_note_tags ON notes')
    op.execute('DROP TRIGGER IF EXISTS update_tags_updated_at ON tags')
    op.execute('DROP TRIGGER IF EXISTS update_wikilinks_updated_at ON wikilinks')
    op.execute('DROP TRIGGER IF EXISTS update_notes_updated_at ON notes')
    
    # Drop functions
    op.execute('DROP FUNCTION IF EXISTS sync_tag_usage_counts()')
    op.execute('DROP FUNCTION IF EXISTS update_updated_at_column()')
    
    # Drop tables
    op.drop_table('audit_reports')
    op.drop_table('tags')
    op.drop_table('agent_runs')
    op.drop_table('jira_tickets')
    op.drop_table('wikilinks')
    op.drop_table('embeddings')
    op.drop_table('notes')
