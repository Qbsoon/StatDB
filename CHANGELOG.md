# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-08-28

Initial MVP release.

### Added

- **F0** — Project scaffold: Quart app factory, env config, i18n (EN/PL).
- **F1** — Database layer: aiosqlite, migration runner, healthcheck.
- **F2** — Dataset catalog: dynamic physical tables, all column types,
  preset "Months" generator, REST API for schemas.
- **F3** — Row CRUD: type validation, safe formula engine (`ast` whitelist),
  filtering, sorting, pagination, shadow fields for year-month.
- **F4** — Aggregation engine: sum/avg/count/min/max/median, group-by,
  stacked series, filters (eq/ne/lt/lte/gt/gte/contains/in/year).
- **F5** — Views & widgets: persistence, 16 widget types, gridstack geometry
  validation, REST API for views/widgets/layout.
- **F6** — Frontend: base layout, light/dark themes + 3 accents, dataset
  pages, column schema editor, home page.
- **F7** — Data table UI: inline cell editing, row add/delete, type-aware
  form widgets, decimal-comma coercion, empty state.
- **F8** — Dashboard: view pages, vendored gridstack (drag & drop, resize,
  auto-save layout), add/edit/delete widgets, i18n.
- **F9** — Widget renderers: note, KPI (scalar/grouped/trend), bar, stacked
  bar, line, pie, heatmap, aggregate table, global filter, PNG export.
- **F10** — CSV import (auto type detection), CSV/JSON export, DB backup
  (`VACUUM INTO`), view config export/import, scheduled snapshots with
  retention, transfer page.
- **F11** — Auth: optional password (env), API tokens (bearer), public
  read-only links, session login/logout, i18n EN default + PL toggle.
- **F12** — Docker: Dockerfile (python:3.12-slim, non-root, healthcheck),
  docker-compose.yml (volume mount, env passthrough), .dockerignore.
- **F13** — README, CHANGELOG, MIT LICENSE.

### Tests

- 107 tests across 11 test modules (all green).
