"""Views & widgets repository (F5).

Persistence only — rendering comes in F8/F9. ``settings``/``config`` are
JSON blobs; icon/theme/settings see todo.md §4.1. Widgets carry gridstack
coordinates (12-col grid) plus a stable ``position`` for DOM order.
"""

from __future__ import annotations

import json
from typing import Any

from ..db import Database, row_to_dict

# Widget types the renderers (F9) will understand. Anything else is rejected,
# so a typo can't silently persist a widget the UI can't render.
WIDGET_TYPES = {
    "table",            # data table (rows, inline edit)
    "form",             # insert-form widget
    "bar",              # single-series bar chart
    "stacked_bar",      # stacked bar (group × series)
    "line",             # line chart
    "pie",              # pie / donut
    "heatmap",          # heatmap (e.g. month × year)
    "kpi_sum",
    "kpi_avg",
    "kpi_min",
    "kpi_max",
    "kpi_count",
    "kpi_median",
    "kpi_trend",        # value + delta vs previous period
    "agg_table",        # text aggregation table with totals row
    "global_filter",    # view-wide filter widget
    "note",             # markdown note
}


class ViewStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------- helpers ----------

    @staticmethod
    def _view_dict(row: dict[str, Any]) -> dict[str, Any]:
        data = row_to_dict(row)
        data["settings"] = json.loads(data.get("settings") or "{}")
        return data

    @staticmethod
    def _widget_dict(row: dict[str, Any]) -> dict[str, Any]:
        data = row_to_dict(row)
        data["config"] = json.loads(data.get("config") or "{}")
        return data

    @staticmethod
    def _geom(data: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, int]:
        """Gridstack geometry with validation (12-col grid, non-negative)."""
        src = dict(current or {})
        for key in ("x", "y", "w", "h"):
            if key in data and data[key] is not None:
                src[key] = int(data[key])
        if "position" in data and data["position"] is not None:
            src["position"] = int(data["position"])
        geom = {
            "x": int(src.get("x", 0)),
            "y": int(src.get("y", 0)),
            "w": int(src.get("w", 6)),
            "h": int(src.get("h", 4)),
            "position": int(src.get("position", 0)),
        }
        if not (0 <= geom["x"] <= 11):
            raise ValueError("widget x must be within the 12-col grid (0..11)")
        if not (1 <= geom["w"] <= 12) or geom["x"] + geom["w"] > 12:
            raise ValueError("widget x + w must fit the 12-col grid")
        if geom["y"] < 0 or geom["h"] < 1:
            raise ValueError("widget y must be >= 0 and h >= 1")
        return geom

    # ---------- views ----------

    async def create_view(
        self,
        name: str,
        *,
        icon: str = "",
        theme: str = "",
        settings: dict[str, Any] | None = None,
        position: int = 0,
    ) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("view name required")
        view_id = await self.db.execute(
            "INSERT INTO views (name, icon, theme, settings, position) VALUES (?, ?, ?, ?, ?)",
            (name.strip(), icon.strip(), theme.strip(), json.dumps(settings or {}), int(position)),
        )
        return (await self.get_view(view_id)) or {}

    async def get_view(self, view_id: int) -> dict[str, Any] | None:
        row = await self.db.query_one("SELECT * FROM views WHERE id = ?", (view_id,))
        return self._view_dict(row) if row else None

    async def list_views(self) -> list[dict[str, Any]]:
        rows = await self.db.query_all("SELECT * FROM views ORDER BY position, id")
        return [self._view_dict(r) for r in rows]

    async def update_view(
        self,
        view_id: int,
        *,
        name: str | None = None,
        icon: str | None = None,
        theme: str | None = None,
        settings: dict[str, Any] | None = None,
        position: int | None = None,
    ) -> dict[str, Any]:
        current = await self.get_view(view_id)
        if not current:
            raise KeyError(f"view {view_id} not found")
        await self.db.execute(
            "UPDATE views SET name = ?, icon = ?, theme = ?, settings = ?, position = ? WHERE id = ?",
            (
                (name if name is not None else current["name"]).strip() or current["name"],
                current["icon"] if icon is None else icon.strip(),
                current["theme"] if theme is None else theme.strip(),
                json.dumps(current["settings"] if settings is None else settings),
                int(current["position"] if position is None else position),
                view_id,
            ),
        )
        return (await self.get_view(view_id)) or {}

    async def delete_view(self, view_id: int) -> None:
        current = await self.get_view(view_id)
        if not current:
            raise KeyError(f"view {view_id} not found")
        await self.db.execute("DELETE FROM views WHERE id = ?", (view_id,))

    # ---------- widgets ----------

    async def _free_slot(self, view_id: int, w: int, h: int) -> tuple[int, int]:
        """First free slot on the 12-col grid (todo §15.8: new widgets land
        in empty space instead of stacking on top of existing ones)."""
        rows = await self.db.query_all(
            "SELECT x, y, w, h FROM widgets WHERE view_id = ?", (view_id,)
        )
        used: set[tuple[int, int]] = set()
        max_y = 0
        for r in rows:
            max_y = max(max_y, int(r["y"]) + int(r["h"]))
            for x in range(int(r["x"]), int(r["x"]) + int(r["w"])):
                for y in range(int(r["y"]), int(r["y"]) + int(r["h"])):
                    used.add((x, y))
        for y in range(0, max_y + 25):
            for x in range(0, 12 - w + 1):
                if all(
                    (x + i, y + j) not in used
                    for i in range(w)
                    for j in range(h)
                ):
                    return x, y
        return 0, max_y

    async def add_widget(
        self,
        view_id: int,
        widget_type: str,
        *,
        title: str = "",
        config: dict[str, Any] | None = None,
        geometry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        widget_type = widget_type.strip()
        if widget_type not in WIDGET_TYPES:
            raise ValueError(f"unknown widget type '{widget_type}'")
        geometry = geometry or {}
        geom = self._geom(geometry)
        # auto-place in the first empty grid slot unless the caller pinned x/y
        if "x" not in geometry and "y" not in geometry:
            geom["x"], geom["y"] = await self._free_slot(view_id, geom["w"], geom["h"])
        # append after existing widgets unless caller pins a position
        if not (geom.get("position")):
            row = await self.db.query_one(
                "SELECT COALESCE(MAX(position) + 1, 0) AS next FROM widgets WHERE view_id = ?",
                (view_id,),
            )
            geom["position"] = int(row["next"]) if row else 0
        widget_id = await self.db.execute(
            'INSERT INTO widgets (view_id, type, title, config, x, y, w, h, position)'
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                view_id,
                widget_type,
                title.strip(),
                json.dumps(config or {}),
                geom["x"], geom["y"], geom["w"], geom["h"], geom["position"],
            ),
        )
        return (await self.get_widget(widget_id)) or {}

    async def get_widget(self, widget_id: int) -> dict[str, Any] | None:
        row = await self.db.query_one("SELECT * FROM widgets WHERE id = ?", (widget_id,))
        return self._widget_dict(row) if row else None

    async def list_widgets(self, view_id: int) -> list[dict[str, Any]]:
        rows = await self.db.query_all(
            "SELECT * FROM widgets WHERE view_id = ? ORDER BY position, id", (view_id,)
        )
        return [self._widget_dict(r) for r in rows]

    async def update_widget(
        self,
        widget_id: int,
        *,
        title: str | None = None,
        config: dict[str, Any] | None = None,
        widget_type: str | None = None,
        geometry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = await self.get_widget(widget_id)
        if not current:
            raise KeyError(f"widget {widget_id} not found")
        new_type = (widget_type or current["type"]).strip()
        if new_type not in WIDGET_TYPES:
            raise ValueError(f"unknown widget type '{widget_type}'")
        geom = self._geom(geometry or {}, current)
        await self.db.execute(
            'UPDATE widgets SET type = ?, title = ?, config = ?, x = ?, y = ?, w = ?, h = ?, position = ?'
            " WHERE id = ?",
            (
                new_type,
                current["title"] if title is None else title.strip(),
                json.dumps(current["config"] if config is None else config),
                geom["x"], geom["y"], geom["w"], geom["h"], geom["position"],
                widget_id,
            ),
        )
        return (await self.get_widget(widget_id)) or {}

    async def set_layout(self, view_id: int, layout: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Bulk gridstack save: [{id, x, y, w, h, position}]. Unknown ids → KeyError."""
        for item in layout:
            widget_id = int(item.get("id"))
            current: dict[str, Any] = await self.get_widget(widget_id)
            if not current or current["view_id"] != view_id:
                raise KeyError(f"widget {widget_id} not found in view {view_id}")
            geom = self._geom(item, current)
            await self.db.execute(
                'UPDATE widgets SET x = ?, y = ?, w = ?, h = ?, position = ? WHERE id = ?',
                (geom["x"], geom["y"], geom["w"], geom["h"], geom["position"], widget_id),
            )
        return await self.list_widgets(view_id)

    async def delete_widget(self, widget_id: int) -> None:
        current = await self.get_widget(widget_id)
        if not current:
            raise KeyError(f"widget {widget_id} not found")
        await self.db.execute("DELETE FROM widgets WHERE id = ?", (widget_id,))
