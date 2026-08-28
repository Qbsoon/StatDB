// StatDB — renderery widżetów (F9): note, KPI, bar/line/pie, tabela agregująca.
(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }

  var DEFAULT_COLORS = ["#4b7bec", "#2bc48a", "#f5a623", "#e0457b", "#7b61ff", "#23c9c9"];

  function fmtNumber(value, decimals) {
    if (value === null || value === undefined) { return "–"; }
    var n = Number(value);
    if (isNaN(n)) { return String(value); }
    var d = (decimals === undefined) ? (Math.abs(n) % 1 ? 2 : 0) : decimals;
    return n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }

  function clearBody(body) { body.innerHTML = ""; }

  function renderNote(body, config) {
    var note = String(config.text || "");
    var div = document.createElement("div");
    div.className = "widget-note";
    div.textContent = note || "";
    body.appendChild(div);
  }

  function fetchAggregate(config) {
    var spec = {
      dataset: config.dataset_id,
      measure: config.measure || "sum",
      column: config.column || null,
      group_by: config.group_by || null,
      series: config.series || null,
      filters: config.filters || null,
      lang: config.lang || undefined,
    };
    return fetch("/api/aggregate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(spec),
    }).then(function (res) {
      if (!res.ok) { return res.text().then(function (txt) { throw new Error(txt); }); }
      return res.json();
    });
  }

  function renderKpi(body, data, config) {
    var value = 0;
    var label = config.column || config.measure || "";
    if (Array.isArray(data) && data.length) {
      value = data[0].value !== undefined ? data[0].value : data[0].v;
      label = data[0].label || label;
    }
    var wrap = document.createElement("div");
    wrap.className = "widget-kpi";
    var val = document.createElement("div");
    val.className = "widget-kpi-value";
    val.textContent = fmtNumber(value);
    var sub = document.createElement("div");
    sub.className = "widget-kpi-label muted";
    sub.textContent = label;
    wrap.appendChild(val);
    wrap.appendChild(sub);
    body.appendChild(wrap);
  }

  function rowsToPoints(data) {
    if (!Array.isArray(data)) { return []; }
    return data.map(function (r) {
      return { label: String(r.label !== undefined ? r.label : r.key), value: Number(r.value) || 0 };
    });
  }

  function renderBar(body, data, config) {
    var pts = rowsToPoints(data);
    if (!pts.length) { return false; }
    var max = Math.max.apply(null, pts.map(function (p) { return Math.abs(p.value); })) || 1;
    var wrap = document.createElement("div");
    wrap.className = "widget-bars";
    pts.forEach(function (p, i) {
      var row = document.createElement("div");
      row.className = "bar-row";
      var lab = document.createElement("span");
      lab.className = "bar-label";
      lab.textContent = p.label;
      var track = document.createElement("div");
      track.className = "bar-track";
      var fill = document.createElement("div");
      fill.className = "bar-fill";
      fill.style.width = Math.min(100, Math.abs(p.value) / max * 100) + "%";
      fill.style.background = cssVar("--accent", DEFAULT_COLORS[i % DEFAULT_COLORS.length]);
      var num = document.createElement("span");
      num.className = "bar-value";
      num.textContent = fmtNumber(p.value);
      track.appendChild(fill);
      row.appendChild(lab);
      row.appendChild(track);
      row.appendChild(num);
      wrap.appendChild(row);
    });
    body.appendChild(wrap);
    return true;
  }

  function renderLine(body, data, config) {
    var pts = rowsToPoints(data);
    if (!pts.length) { return false; }
    var w = 300, h = 140, pad = 16;
    var values = pts.map(function (p) { return p.value; });
    var max = Math.max.apply(null, values);
    var min = Math.min.apply(null, values);
    var span = (max - min) || 1;
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "widget-line");
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    var path = "";
    pts.forEach(function (p, i) {
      var x = pad + (w - pad * 2) * (pts.length === 1 ? 0.5 : i / (pts.length - 1));
      var y = h - pad - (h - pad * 2) * ((p.value - min) / span);
      path += (i === 0 ? "M" : " L") + x.toFixed(1) + " " + y.toFixed(1);
    });
    var pl = document.createElementNS("http://www.w3.org/2000/svg", "path");
    pl.setAttribute("d", path);
    pl.setAttribute("fill", "none");
    pl.setAttribute("stroke", cssVar("--accent", DEFAULT_COLORS[0]));
    pl.setAttribute("stroke-width", "2");
    svg.appendChild(pl);
    body.appendChild(svg);
    return true;
  }

  function renderPie(body, data, config) {
    var pts = rowsToPoints(data).filter(function (p) { return p.value > 0; });
    var total = pts.reduce(function (s, p) { return s + p.value; }, 0);
    if (!total) { return false; }
    var size = 150, r = 60, cx = size / 2, cy = size / 2;
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + size + " " + size);
    svg.setAttribute("class", "widget-pie");
    var angle = 0;
    pts.forEach(function (p, i) {
      var frac = p.value / total;
      var a1 = angle, a2 = angle + frac * Math.PI * 2;
      angle = a2;
      var x1 = cx + r * Math.cos(a1 - Math.PI / 2);
      var y1 = cy + r * Math.sin(a1 - Math.PI / 2);
      var x2 = cx + r * Math.cos(a2 - Math.PI / 2);
      var y2 = cy + r * Math.sin(a2 - Math.PI / 2);
      var large = frac > 0.5 ? 1 : 0;
      var d = "M " + cx + " " + cy + " L " + x1 + " " + y1 +
              " A " + r + " " + r + " 0 " + large + " 1 " + x2 + " " + y2 + " Z";
      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", d);
      path.setAttribute("fill", DEFAULT_COLORS[i % DEFAULT_COLORS.length]);
      var title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = p.label + ": " + fmtNumber(p.value);
      path.appendChild(title);
      svg.appendChild(path);
    });
    body.appendChild(svg);
    return true;
  }

  function renderAggTable(body, data, config) {
    var pts = rowsToPoints(data);
    if (!pts.length) { return false; }
    var table = document.createElement("table");
    table.className = "table widget-agg-table";
    var trH = document.createElement("tr");
    [config.group_by || "group", config.measure || "value"].forEach(function (h) {
      var th = document.createElement("th");
      th.textContent = h;
      trH.appendChild(th);
    });
    table.appendChild(trH);
    pts.forEach(function (p) {
      var tr = document.createElement("tr");
      var td1 = document.createElement("td"); td1.textContent = p.label;
      var td2 = document.createElement("td"); td2.className = "num"; td2.textContent = fmtNumber(p.value);
      tr.appendChild(td1); tr.appendChild(td2);
      table.appendChild(tr);
    });
    body.appendChild(table);
    return true;
  }

  var RENDERERS = {
    note: { render: function (body, cfg) { renderNote(body, cfg); } },
    kpi_sum: { aggConfig: { measure: "sum" }, render: renderKpi, agg: true },
    kpi_avg: { aggConfig: { measure: "avg" }, render: renderKpi, agg: true },
    kpi_min: { aggConfig: { measure: "min" }, render: renderKpi, agg: true },
    kpi_max: { aggConfig: { measure: "max" }, render: renderKpi, agg: true },
    kpi_count: { aggConfig: { measure: "count" }, render: renderKpi, agg: true },
    kpi_median: { aggConfig: { measure: "median" }, render: renderKpi, agg: true },
    kpi_trend: { aggConfig: { measure: "median" }, render: renderKpi, agg: true },
    bar: { render: renderBar, agg: true },
    line: { render: renderLine, agg: true },
    pie: { render: renderPie, agg: true },
    agg_table: { render: renderAggTable, agg: true },
  };

  function renderWidget(section) {
    var body = $("[data-widget-body]", section);
    if (!body) { return; }
    var type = section.getAttribute("data-widget-type") || "";
    var cfg = {};
    try { cfg = JSON.parse(section.getAttribute("data-widget-config") || "{}"); } catch (e) { cfg = {}; }
    var fn = RENDERERS[type];
    if (!fn) { return; } // zostaje placeholder — brak datasetu lub typ nieobsługiwany
    if (fn.agg) {
      cfg = Object.assign({}, (fn.aggConfig || {}), cfg);
      if (!cfg.dataset_id) { return; }
      if (["bar", "line", "pie", "agg_table"].indexOf(type) !== -1 && !cfg.group_by) { cfg.group_by = "month"; }
      fetchAggregate(cfg)
        .then(function (data) {
          clearBody(body);
          fn.render(body, data, cfg);
        })
        .catch(function () { /* brak danych — placeholder */ });
      return;
    }
    clearBody(body);
    fn.render(body, cfg);
  }

  function renderAll(root) {
    var nodes = (root || document).querySelectorAll(".widget[data-widget-type]");
    Array.prototype.forEach.call(nodes, renderWidget);
  }

  window.StatDBWidgets = { renderWidget: renderWidget, renderAll: renderAll };

  document.addEventListener("DOMContentLoaded", function () { renderAll(document); });
})();
