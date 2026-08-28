-- Performance / lookup indexes for the catalog.
-- Dataset SELECTs join columns by dataset_id constantly (list, delete cascade logic).
CREATE INDEX IF NOT EXISTS idx_columns_dataset ON columns(dataset_id);
CREATE INDEX IF NOT EXISTS idx_columns_position ON columns(dataset_id, position);
-- Widget grid uses view ordering (drag & drop will update many rows).
CREATE INDEX IF NOT EXISTS idx_widgets_view_position ON widgets(view_id, position);
-- Public read-only link resolution by token (F11).
CREATE INDEX IF NOT EXISTS idx_share_links_token ON share_links(token);
-- Fast token lookup without full scan; revoked rows excluded.
CREATE INDEX IF NOT EXISTS idx_api_tokens_hash_revoked ON api_tokens(token_hash, revoked_at);
