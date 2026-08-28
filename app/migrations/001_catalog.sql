-- 001: catalog schema (datasets, columns, views, widgets, settings, share links,
-- API tokens). Frozen past the F2 milestone; augmentations land as new files.
--
-- Identifiers (slugs/keys) are validated in application code before any DDL is
-- built from them; values are always parameterized.

CREATE TABLE datasets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,          -- url-safe, used for the physical table data_<slug>
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE columns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id  INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,                 -- physical column name inside data_<slug>
    label       TEXT NOT NULL,                 -- human-facing name in the UI
    type        TEXT NOT NULL,                 -- one of the column types from section 4.2
    config      TEXT NOT NULL DEFAULT '{}',    -- JSON: select options, currency, formula, format…
    position    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (dataset_id, key)
);

CREATE TABLE views (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    icon        TEXT NOT NULL DEFAULT '',
    theme       TEXT NOT NULL DEFAULT '',      -- '' = inherit global settings
    settings    TEXT NOT NULL DEFAULT '{}',    -- JSON: custom css, auto-refresh interval, …
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE widgets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    view_id     INTEGER NOT NULL REFERENCES views(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,                 -- table | form | bar | stacked_bar | kpi_* | …
    title       TEXT NOT NULL DEFAULT '',
    config      TEXT NOT NULL DEFAULT '{}',    -- JSON: dataset, aggregation, group-by, filters, colors…
    x           INTEGER NOT NULL DEFAULT 0,
    y           INTEGER NOT NULL DEFAULT 0,
    w           INTEGER NOT NULL DEFAULT 6,    -- gridstack coordinates (12-col grid)
    h           INTEGER NOT NULL DEFAULT 4,
    position    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL DEFAULT ''
);

-- Public read-only share links for views (F11).
CREATE TABLE share_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    view_id     INTEGER NOT NULL REFERENCES views(id) ON DELETE CASCADE,
    token       TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revoked_at  TEXT
);

-- API tokens for external integrations (F11).
CREATE TABLE api_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    token_hash  TEXT NOT NULL UNIQUE,          -- sha256 hex of the token; plaintext shown once
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revoked_at  TEXT
);
