CREATE TABLE bot_fsm_storage (
    bot_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    thread_id BIGINT,
    business_connection_id TEXT,
    destiny TEXT NOT NULL,
    state TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(data) = 'object'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT bot_fsm_storage_key UNIQUE NULLS NOT DISTINCT (
        bot_id,
        chat_id,
        user_id,
        thread_id,
        business_connection_id,
        destiny
    )
);

CREATE INDEX idx_bot_fsm_storage_expires_at ON bot_fsm_storage (expires_at);
