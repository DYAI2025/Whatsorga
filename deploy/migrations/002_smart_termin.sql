-- Smart Termin System: new columns + feedback table
-- Run: docker exec -i deploy-postgres-1 psql -U radar radar < migrations/002_smart_termin.sql

ALTER TABLE termine ADD COLUMN IF NOT EXISTS category VARCHAR DEFAULT 'appointment';
ALTER TABLE termine ADD COLUMN IF NOT EXISTS relevance VARCHAR DEFAULT 'shared';
ALTER TABLE termine ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'auto';
ALTER TABLE termine ADD COLUMN IF NOT EXISTS reminder_config JSONB;

CREATE TABLE IF NOT EXISTS termin_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    termin_id UUID NOT NULL REFERENCES termine(id),
    action VARCHAR NOT NULL,
    correction JSONB,
    reason VARCHAR,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_termin_feedback_termin_id ON termin_feedback(termin_id);
CREATE INDEX IF NOT EXISTS idx_termin_feedback_action ON termin_feedback(action);
