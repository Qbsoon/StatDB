# StatDB

Universal, self-hosted app for logging structured data and building
reporting dashboards out of configurable widgets (charts, KPIs, tables).

Open source, MIT licensed. Self-hosted — one `docker compose up` or
plain `python run.py`.

## Features

- **Dynamic datasets** — define tables with arbitrary columns and types
  (text, integer, float, boolean, date, datetime, year, year-month, select,
  currency, formula). Each dataset is a real SQLite table for native
  `GROUP BY` / `SUM` / `AVG`.
- **Row CRUD** — inline editing, type validation, decimal-comma coercion,
  filtering (`?f.<col>.<op>=`), sorting, pagination.
- **Aggregation engine** — sum / avg / count / min / max / median,
  group-by, stacked series, filters (eq/ne/lt/lte/gt/gte/contains/in/year),
  select ordering by config, year-month sort-key normalization.
- **Dashboards** — views composed of widgets on a 12-column drag-and-drop
  grid (gridstack.js). Auto-save layout, add/edit/delete widgets.
- **Widget renderers** — note, KPI (sum/avg/min/max/count/median, grouped,
  trend %), bar, stacked bar, line, pie, heatmap, aggregate table,
  global filter. PNG export for SVG widgets.
- **CSV import/export** — auto type detection, export to CSV/JSON.
- **Backup & snapshots** — `VACUUM INTO` backup, scheduled snapshots with
  retention, view config export/import.
- **Auth** — optional password (env), API tokens (bearer), public read-only
  links (`/public/views/<id>`), session-based login.
- **i18n** — English (default) + Polish, cookie toggle, env force.
- **Themes** — light/dark + 3 accents, no-flash pre-CSS script.

## Quick start (Docker)

```bash
docker compose up -d --build
# → http://localhost:5000
```

Data is stored in `./data/` (mounted volume). The database is created
automatically on first request — an empty volume works out of the box.

## Quick start (development)

Python **3.12+** required (tested on 3.14.7).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # 107 tests
python run.py     # http://localhost:5000
```

## Configuration (environment variables)

| Variable                    | Default            | Meaning                                              |
| --------------------------- | ------------------ | ---------------------------------------------------- |
| `STATDB_HOST`               | `0.0.0.0`          | Bind host                                            |
| `STATDB_PORT`               | `5000`             | Bind port                                            |
| `STATDB_DEBUG`              | `0`                | Debug mode (`1/true/yes/on`)                        |
| `STATDB_LANGUAGE`           | — (= `en`)         | Default UI language: `en` or `pl` (user can toggle)  |
| `STATDB_PASSWORD`           | — (none)           | Login password; unset = trusted mode (no login)     |
| `STATDB_API_TOKEN`          | — (none)           | Bearer token for `/api/*`; unset = open API         |
| `STATDB_SECRET_KEY`         | random             | Session secret; set to persist sessions across restarts |
| `STATDB_DATA_DIR`           | `./data`           | Data directory (Docker volume)                       |
| `STATDB_DB_PATH`            | `$DATA_DIR/statdb.db` | SQLite database file                              |
| `STATDB_SNAPSHOT_ENABLED`   | `0`                | Enable scheduled snapshots (`1/true/on`)            |
| `STATDB_SNAPSHOT_INTERVAL`  | `86400`            | Seconds between snapshots                           |
| `STATDB_SNAPSHOT_RETENTION` | `7`                | Number of snapshots to keep                          |

## Docker

```bash
# Build & run
docker compose up -d --build

# With auth + Polish UI (default; user can still toggle in-browser)
STATDB_PASSWORD=secret STATDB_LANGUAGE=pl docker compose up -d --build

# Stop
docker compose down
```

The container runs as non-root user `statdb` (uid 1000). Healthcheck
hits `/api/healthz` every 30s.

## API overview

All endpoints are under `/api/`. When `STATDB_API_TOKEN` is set, pass
`Authorization: Bearer <token>`.

| Method | Path                          | Description                       |
| ------ | ----------------------------- | --------------------------------- |
| GET    | `/api/healthz`                | Health check                      |
| GET    | `/api/datasets`               | List datasets                     |
| POST   | `/api/datasets`               | Create dataset                    |
| GET    | `/api/datasets/<id>`          | Get dataset schema                |
| POST   | `/api/datasets/<id>/columns`  | Add column                        |
| GET    | `/api/datasets/<id>/rows`      | List rows (filter/sort/paginate)  |
| POST   | `/api/datasets/<id>/rows`     | Create row                        |
| PATCH  | `/api/datasets/<id>/rows/<r>` | Update row                        |
| DELETE | `/api/datasets/<id>/rows/<r>` | Delete row                        |
| POST   | `/api/aggregate`             | Aggregate (sum/avg/count/...)      |
| GET    | `/api/datasets/<id>/export`   | Export CSV/JSON (`?format=`)      |
| GET    | `/api/views`                  | List views                        |
| POST   | `/api/views`                  | Create view                       |
| GET    | `/api/views/<id>`             | Get view + widgets                |
| GET    | `/api/views/export`           | Export all views (JSON)          |
| POST   | `/api/views/import`           | Import views (JSON)              |
| GET    | `/api/backup`                 | Download DB backup                |
| GET    | `/api/snapshots`              | List snapshots                    |
| POST   | `/api/snapshots`              | Create snapshot                   |
| DELETE | `/api/snapshots/<name>`       | Delete snapshot                   |

Public read-only dashboards: `/public/views/<id>` (no auth required).

## Tech stack

- **Backend:** Python 3.12+ · Quart (async) · Hypercorn (ASGI) · aiosqlite
- **Database:** SQLite (single file, WAL mode)
- **Frontend:** Jinja2 · vanilla JS · gridstack.js · Apache ECharts (SVG/DOM)
- **Tests:** pytest + pytest-asyncio (107 tests)
- **Container:** Docker (python:3.12-slim, non-root, healthcheck)

## License

MIT — see [LICENSE](LICENSE).
