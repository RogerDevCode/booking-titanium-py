-- Archivo: db/migrations/008_conversations.sql

CREATE TABLE IF NOT EXISTS conversations (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    provider_id UUID,
    channel VARCHAR(20) NOT NULL DEFAULT 'telegram',
    direction VARCHAR(10) NOT NULL, -- 'inbound' o 'outbound'
    content TEXT NOT NULL,
    intent VARCHAR(50),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookup of chat history per user
CREATE INDEX IF NOT EXISTS idx_conversations_client ON conversations(client_id, created_at DESC);
