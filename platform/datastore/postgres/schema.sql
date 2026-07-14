-- Enterprise AI Control Plane - Core Database Schema
-- Requires: PostgreSQL 16+ and pgvector extension

-- 0. Extensions Setup
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- 1. Tenant Metadata
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'terminated')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants(status);

-- 2. GRC Compliance Evidence & Audit Logs
CREATE TABLE IF NOT EXISTS compliance_evidence (
    evidence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    control_id VARCHAR(100) NOT NULL,
    source_component VARCHAR(100) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
    payload JSONB NOT NULL,
    minio_object_path VARCHAR(512),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_compliance_tenant_control ON compliance_evidence(tenant_id, control_id);
CREATE INDEX IF NOT EXISTS idx_compliance_severity ON compliance_evidence(severity);

-- 3. LangGraph Checkpoint Store
CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    thread_id VARCHAR(255) NOT NULL,
    checkpoint_id VARCHAR(255) NOT NULL,
    parent_checkpoint_id VARCHAR(255),
    tenant_id VARCHAR(64) REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    metadata JSONB NOT NULL,
    checkpoint_data BYTEA NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (thread_id, checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_langgraph_thread_tenant ON langgraph_checkpoints(thread_id, tenant_id);

-- 4. Semantic Memory (pgvector)
CREATE TABLE IF NOT EXISTS semantic_memories (
    memory_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    thread_id VARCHAR(255),
    collection_name VARCHAR(100) NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(1536) NOT NULL, -- Configured for OpenAI text-embedding-3-small (1536 dims)
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- HNSW Vector Index for Cosine Distance Search
CREATE INDEX IF NOT EXISTS idx_semantic_memories_vector ON semantic_memories 
USING hnsw (embedding vector_cosine_ops);

-- Composite Index for tenant-scoped collections
CREATE INDEX IF NOT EXISTS idx_semantic_memories_tenant_collection ON semantic_memories(tenant_id, collection_name);

-- 5. Row-Level Security (RLS) Policies
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE langgraph_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE semantic_memories ENABLE ROW LEVEL SECURITY;

-- Dynamic Tenant Context Helper:
-- Applications must run 'SET LOCAL app.current_tenant_id = <id>;' inside transactions.

-- RLS Policies for Tenants table
CREATE POLICY tenant_isolation_tenants ON tenants
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- RLS Policies for Compliance Evidence
CREATE POLICY tenant_isolation_evidence ON compliance_evidence
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- RLS Policies for LangGraph Checkpoints
CREATE POLICY tenant_isolation_checkpoints ON langgraph_checkpoints
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- RLS Policies for Semantic Memories
CREATE POLICY tenant_isolation_memories ON semantic_memories
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true));
