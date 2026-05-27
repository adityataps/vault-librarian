-- PostgreSQL Schema for Vault Crawler
-- Version: 1.0
-- Description: Primary storage for vault notes, embeddings, and agent tracking

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Notes table: Core vault note metadata
CREATE TABLE notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path TEXT UNIQUE NOT NULL,  -- Relative path from vault root (e.g., "Projects/Agent Platform.md")
    title TEXT NOT NULL,
    folder TEXT NOT NULL,  -- Current folder name (e.g., "Projects")
    tags TEXT[] NOT NULL DEFAULT '{}',
    type TEXT CHECK (type IN ('Story', 'Meeting', 'TechNote', 'Project', 'Template', 'Reference', 'Career', 'Other')),
    status TEXT CHECK (status IN ('Backlog', 'Planning', 'In Progress', 'Blocked', 'Done')),
    content_hash TEXT NOT NULL,  -- SHA256 of content for change detection
    word_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_modified TIMESTAMPTZ NOT NULL  -- File system mtime
);

CREATE INDEX idx_notes_folder ON notes(folder);
CREATE INDEX idx_notes_tags ON notes USING GIN(tags);
CREATE INDEX idx_notes_type ON notes(type);
CREATE INDEX idx_notes_status ON notes(status);
CREATE INDEX idx_notes_updated_at ON notes(updated_at);
CREATE INDEX idx_notes_last_modified ON notes(last_modified);

-- Embeddings table: Vector embeddings for semantic search
CREATE TABLE embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    vector vector(1536) NOT NULL,  -- OpenAI text-embedding-3-small dimension
    model TEXT NOT NULL,  -- e.g., 'text-embedding-3-small'
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(note_id, model)
);

-- Create IVFFlat index for fast cosine similarity search
-- lists parameter: sqrt(total_rows) is a good starting point, will create after initial data load
CREATE INDEX ON embeddings USING ivfflat (vector vector_cosine_ops) WITH (lists = 100);

-- Wikilinks table: Graph of internal note links
CREATE TABLE wikilinks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    target_path TEXT NOT NULL,  -- May not exist yet (broken link)
    target_note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
    link_text TEXT NOT NULL,  -- Display text from [[target|link_text]]
    is_broken BOOLEAN NOT NULL DEFAULT FALSE,  -- Cached flag for broken link detection
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_wikilinks_source ON wikilinks(source_note_id);
CREATE INDEX idx_wikilinks_target ON wikilinks(target_note_id);
CREATE INDEX idx_wikilinks_target_path ON wikilinks(target_path);
CREATE INDEX idx_wikilinks_broken ON wikilinks(is_broken) WHERE is_broken = TRUE;

-- Jira tickets table: Jira sync tracking
CREATE TABLE jira_tickets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key TEXT UNIQUE NOT NULL,  -- e.g., 'AICOE-509'
    note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
    summary TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    priority TEXT,
    assignee TEXT,
    parent_key TEXT,
    repos TEXT[] DEFAULT '{}',
    labels TEXT[] DEFAULT '{}',
    jira_created_at TIMESTAMPTZ,
    jira_updated_at TIMESTAMPTZ NOT NULL,
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_jira_tickets_key ON jira_tickets(key);
CREATE INDEX idx_jira_tickets_status ON jira_tickets(status);
CREATE INDEX idx_jira_tickets_note_id ON jira_tickets(note_id);
CREATE INDEX idx_jira_tickets_updated ON jira_tickets(jira_updated_at);
CREATE INDEX idx_jira_tickets_parent ON jira_tickets(parent_key);

-- Agent runs table: Audit log of agent execution
CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    crew_name TEXT NOT NULL,  -- e.g., 'NewNoteCrew', 'DailyAuditCrew'
    agent_name TEXT,  -- e.g., 'Librarian', 'Auditor' (null for crew-level runs)
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('file_event', 'scheduled', 'manual', 'api')),
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'cancelled')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    notes_processed INTEGER DEFAULT 0,
    notes_created INTEGER DEFAULT 0,
    notes_updated INTEGER DEFAULT 0,
    notes_moved INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,  -- Arbitrary key-value data
    
    CONSTRAINT valid_completion CHECK (
        (status = 'running' AND completed_at IS NULL) OR
        (status != 'running' AND completed_at IS NOT NULL)
    )
);

CREATE INDEX idx_agent_runs_crew ON agent_runs(crew_name);
CREATE INDEX idx_agent_runs_agent ON agent_runs(agent_name);
CREATE INDEX idx_agent_runs_started ON agent_runs(started_at DESC);
CREATE INDEX idx_agent_runs_status ON agent_runs(status);
CREATE INDEX idx_agent_runs_trigger ON agent_runs(trigger_type);
CREATE INDEX idx_agent_runs_metadata ON agent_runs USING GIN(metadata);

-- Tags table: Tag metadata and statistics
CREATE TABLE tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT UNIQUE NOT NULL,
    normalized_name TEXT NOT NULL,  -- Lowercase for case-insensitive matching
    usage_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tags_name ON tags(name);
CREATE INDEX idx_tags_normalized ON tags(normalized_name);
CREATE INDEX idx_tags_usage ON tags(usage_count DESC);

-- Audit reports table: Generated reports from audit/archivist agents
CREATE TABLE audit_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_run_id UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    report_type TEXT NOT NULL CHECK (report_type IN ('daily_audit', 'stale_notes', 'broken_links', 'orphans', 'weekly_digest')),
    summary TEXT NOT NULL,
    findings_count INTEGER DEFAULT 0,
    findings JSONB DEFAULT '[]'::jsonb,  -- Array of finding objects
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_reports_type ON audit_reports(report_type);
CREATE INDEX idx_audit_reports_created ON audit_reports(created_at DESC);
CREATE INDEX idx_audit_reports_run ON audit_reports(agent_run_id);

-- Functions and triggers for maintaining updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_notes_updated_at BEFORE UPDATE ON notes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_wikilinks_updated_at BEFORE UPDATE ON wikilinks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tags_updated_at BEFORE UPDATE ON tags
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to automatically update tag usage counts
CREATE OR REPLACE FUNCTION sync_tag_usage_counts()
RETURNS TRIGGER AS $$
BEGIN
    -- Increment counts for new tags
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        INSERT INTO tags (name, normalized_name, usage_count)
        SELECT unnest(NEW.tags), LOWER(unnest(NEW.tags)), 1
        ON CONFLICT (name) DO UPDATE SET usage_count = tags.usage_count + 1;
    END IF;
    
    -- Decrement counts for removed tags
    IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND OLD.tags IS DISTINCT FROM NEW.tags) THEN
        UPDATE tags SET usage_count = GREATEST(0, usage_count - 1)
        WHERE name = ANY(OLD.tags);
    END IF;
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sync_note_tags AFTER INSERT OR UPDATE OR DELETE ON notes
    FOR EACH ROW EXECUTE FUNCTION sync_tag_usage_counts();

-- Views for common queries

-- View: Recent agent activity
CREATE VIEW recent_agent_activity AS
SELECT 
    ar.id,
    ar.crew_name,
    ar.agent_name,
    ar.status,
    ar.started_at,
    ar.duration_ms,
    ar.notes_processed,
    ar.notes_created + ar.notes_updated + ar.notes_moved AS notes_modified,
    ar.tokens_used,
    ar.error_message
FROM agent_runs ar
WHERE ar.started_at > NOW() - INTERVAL '7 days'
ORDER BY ar.started_at DESC;

-- View: Note statistics by folder
CREATE VIEW folder_stats AS
SELECT
    folder,
    COUNT(*) AS note_count,
    COUNT(DISTINCT unnest(tags)) AS unique_tags,
    AVG(word_count)::INTEGER AS avg_word_count,
    MAX(updated_at) AS last_updated
FROM notes
GROUP BY folder;

-- View: Broken wikilinks summary
CREATE VIEW broken_links_summary AS
SELECT
    n.path AS source_path,
    n.folder,
    wl.target_path,
    wl.link_text,
    wl.updated_at
FROM wikilinks wl
JOIN notes n ON wl.source_note_id = n.id
WHERE wl.is_broken = TRUE
ORDER BY wl.updated_at DESC;

-- View: Stale notes (not updated in 90 days)
CREATE VIEW stale_notes AS
SELECT
    n.id,
    n.path,
    n.title,
    n.folder,
    n.tags,
    n.updated_at,
    NOW() - n.updated_at AS stale_duration
FROM notes n
WHERE n.updated_at < NOW() - INTERVAL '90 days'
ORDER BY n.updated_at ASC;

-- Comments for documentation
COMMENT ON TABLE notes IS 'Core vault note metadata and content hashes';
COMMENT ON TABLE embeddings IS 'Vector embeddings for semantic search using pgvector';
COMMENT ON TABLE wikilinks IS 'Graph of internal [[wikilink]] relationships between notes';
COMMENT ON TABLE jira_tickets IS 'Jira ticket sync tracking and metadata';
COMMENT ON TABLE agent_runs IS 'Audit log of all agent and crew executions';
COMMENT ON TABLE tags IS 'Tag metadata with usage statistics';
COMMENT ON TABLE audit_reports IS 'Generated reports from audit and maintenance agents';

COMMENT ON COLUMN embeddings.vector IS 'OpenAI text-embedding-3-small (1536 dimensions)';
COMMENT ON COLUMN notes.content_hash IS 'SHA256 hash for change detection without storing full content';
COMMENT ON COLUMN wikilinks.is_broken IS 'Cached flag indicating target note does not exist';
