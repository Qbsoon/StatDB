// StatDB — renderery widżetów (F9): notatka, KPI (z trendem), bar/stacked/line/pie/heatmapa,
// tabela agregująca, filtr globalny, notatka. Eksport PNG dla wykresów SVG.
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

  function clearBody(body) { while (body.firstChild) { body.removeChild(body.firstChild); } }

  function renderNote(body, config) {
    var div = document.createElement("div");
    div.className = "widget-note";
    div.textContent = String(config.text || "");
    body.appendChild(div);
  }

  function fetchAggregate(config) {
    var spec = {
      dataset: config.dataset_id,
      measure: config.measure || "sum",
      column: config.column || null,
      group_by: config.group_by || null,
      series: config.series || null,
      filters: Object.assign({}, config.filters || {}),
      lang: config.lang || undefined,
    };
    var g = window.StatDBFilter;
    if (g && g.column && g.value !== undefined && g.value !== "" &&
        String(g.datasetId) === String(config.dataset_id)) {
      spec.filters[g.column] = spec.filters[g.column] || {};
      spec.filters[g.column][g.op || "eq"] = g.value;
    }
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
    var value = null;
    var delta = null;
    if (data && data.kind === "scalar") {
      value = data.value;
    } else {
      var pts = rowsToPoints(data);
      if (pts.length) {
        value = pts[pts.length - 1].value;
        if (config.showTrend && pts.length > 1) {
          var prev = pts[pts.length - 2].value;
          if (prev) { delta = (value - prev) / Math.abs(prev) * 100; }
        }
      }
    }
    var wrap = document.createElement("div");
    wrap.className = "widget-kpi";
    var val = document.createElement("div");
    val.className = "widget-kpi-value";
    val.textContent = value === null || value === undefined ? "\u2013" : fmtNumber(value);
    wrap.appendChild(val);
    if (delta !== null) {
      var tr = document.createElement("div");
      tr.className = "widget-kpi-trend " + (delta >= 0 ? "up" : "down");
      tr.textContent = (delta >= 0 ? "\u25B2 +" : "\u25BC ") + delta.toFixed(1) + "%";
      wrap.appendChild(tr);
    }
    var sub = document.createElement("div");
    sub.className = "widget-kpi-label muted";
    sub.textContent = config.column || config.measure || "";
    wrap.appendChild(sub);
    body.appendChild(wrap);
    return true;
  }

  function rowsToPoints(data) {
    var items = Array.isArray(data) ? data : (data && data.items);
    if (!Array.isArray(items)) { return []; }
    return items.map(function (r) {
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

  function exportSvgPng(svg, filename) {
    var xml = new XMLSerializer().serializeToString(svg);
    var img = new Image();
    img.onload = function () {
      var vb = (svg.getAttribute("viewBox") || "0 0 300 140").split(/\s+/).map(Number);
      var canvas = document.createElement("canvas");
      canvas.width = vb[2] || 300;
      canvas.height = vb[3] || 140;
      var ctx = canvas.getContext("2d");
      ctx.fillStyle = cssVar("--bg", "#ffffff");
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);
      var a = document.createElement("a");
      a.download = filename;
      a.href = canvas.toDataURL("image/png");
      a.click();
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
  }

  function addPngButton(section) {
    var header = $(".widget-header", section);
    if (!header || $(".widget-export", header)) { return; }
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "widget-export widget-icon";
    btn.title = "PNG";
    btn.textContent = "\u2B07";
    btn.addEventListener("mousedown", function (ev) { ev.stopPropagation(); });
    btn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var svg = $("[data-widget-body] svg", section);
      if (svg) {
        var title = $(".widget-title", section);
        exportSvgPng(svg, ((title && title.textContent) || "wykres") + ".png");
      }
    });
    header.appendChild(btn);
  }

  function renderStackedBar(body, data, config) {
    if (!data || data.kind !== "stacked" || !data.buckets.length) { return false; }
    var buckets = data.buckets;
    var series = data.series;
    var totals = buckets.map(function (b, bi) {
      return series.reduce(function (s, sr) { return s + (Number(sr.values[bi]) || 0); }, 0);
    });
    var max = Math.max.apply(null, totals.concat([1]));
    var wrap = document.createElement("div");
    wrap.className = "widget-bars widget-stacked";
    buckets.forEach(function (b, bi) {
      var row = document.createElement("div");
      row.className = "bar-row";
      var lab = document.createElement("span");
      lab.className = "bar-label";
      lab.textContent = b.label;
      var track = document.createElement("div");
      track.className = "bar-track";
      series.forEach(function (sr, si) {
        var v = Number(sr.values[bi]) || 0;
        if (!v) { return; }
        var seg = document.createElement("div");
        seg.className = "bar-fill";
        seg.style.width = (v / max * 100) + "%";
        seg.style.background = sr.color || DEFAULT_COLORS[si % DEFAULT_COLORS.length];
        seg.title = sr.label + ": " + fmtNumber(v);
        track.appendChild(seg);
      });
      var num = document.createElement("span");
      num.className = "bar-value";
      num.textContent = fmtNumber(totals[bi]);
      row.appendChild(lab);
      row.appendChild(track);
      row.appendChild(num);
      wrap.appendChild(row);
    });
    body.appendChild(wrap);
    return true;
  }

  function renderHeatmap(body, data, config) {
    if (!data || data.kind !== "stacked" || !data.buckets.length || !data.series.length) { return false; }
    var buckets = data.buckets;
    var series = data.series;
    var max = 0;
    series.forEach(function (sr) {
      sr.values.forEach(function (v) { max = Math.max(max, Number(v) || 0); });
    });
    max = max || 1;
    var cw = 26, chh = 20, padL = 70, padT = 18;
    var w = padL + series.length * cw + 4;
    var h = padT + buckets.length * chh + 24;
    var accent = cssVar("--accent", DEFAULT_COLORS[0]);
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "widget-heatmap");
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    series.forEach(function (sr, si) {
      var tx = document.createElementNS("http://www.w3.org/2000/svg", "text");
      tx.setAttribute("x", padL + si * cw + cw / 2);
      tx.setAttribute("y", padT - 6);
      tx.setAttribute("text-anchor", "middle");
      tx.setAttribute("class", "hm-label");
      tx.textContent = sr.label;
      svg.appendChild(tx);
    });
    buckets.forEach(function (b, bi) {
      var ty = document.createElementNS("http://www.w3.org/2000/svg", "text");
      ty.setAttribute("x", padL - 6);
      ty.setAttribute("y", padT + bi * chh + 14);
      ty.setAttribute("text-anchor", "end");
      ty.setAttribute("class", "hm-label");
      ty.textContent = b.label;
      svg.appendChild(ty);
      series.forEach(function (sr, si) {
        var v = Number(sr.values[bi]) || 0;
        var r = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        r.setAttribute("x", padL + si * cw + 1);
        r.setAttribute("y", padT + bi * chh + 1);
        r.setAttribute("width", cw - 2);
        r.setAttribute("height", chh - 2);
        r.setAttribute("rx", 3);
        r.setAttribute("fill", sr.color || accent);
        r.setAttribute("opacity", v ? String(0.15 + 0.85 * v / max) : "0.08");
        var t = document.createElementNS("http://www.w3.org/2000/svg", "title");
        t.textContent = b.label + " \u00D7 " + sr.label + ": " + fmtNumber(v);
        r.appendChild(t);
        svg.appendChild(r);
      });
    });
    body.appendChild(svg);
    return true;
  }

  function renderGlobalFilter(body, config) {
    var wrap = document.createElement("div");
    wrap.className = "widget-gfilter";
    var input = document.createElement("input");
    input.type = "text";
    input.placeholder = String(config.column || "warto\u015B\u0107");
    var g = window.StatDBFilter;
    if (g && String(g.datasetId) === String(config.dataset_id)) { input.value = g.value; }
    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "OK";
    function apply() {
      if (input.value === "") {
        window.StatDBFilter = null;
      } else {
        window.StatDBFilter = {
          datasetId: config.dataset_id,
          column: config.column,
          op: config.op || "eq",
          value: input.value,
        };
      }
      renderAll(document);
    }
    btn.addEventListener("click", apply);
    input.addEventListener("keydown", function (ev) { if (ev.key === "Enter") { apply(); } });
    wrap.appendChild(input);
    wrap.appendChild(btn);
    body.appendChild(wrap);
    return true;
  }

  var RENDERERS = {
    note: { render: renderNote },
    global_filter: { render: renderGlobalFilter },
    kpi_sum: { aggConfig: { measure: "sum" }, render: renderKpi, agg: true },
    kpi_avg: { aggConfig: { measure: "avg" }, render: renderKpi, agg: true },
    kpi_min: { aggConfig: { measure: "min" }, render: renderKpi, agg: true },
    kpi_max: { aggConfig: { measure: "max" }, render: renderKpi, agg: true },
    kpi_count: { aggConfig: { measure: "count" }, render: renderKpi, agg: true },
    kpi_median: { aggConfig: { measure: "median" }, render: renderKpi, agg: true },
    kpi_trend: { aggConfig: { measure: "sum", showTrend: true }, render: renderKpi, agg: true },
    bar: { aggConfig: { measure: "sum" }, render: renderBar, agg: true, group: true },
    stacked_bar: { aggConfig: { measure: "sum" }, render: renderStackedBar, agg: true },
    line: { aggConfig: { measure: "sum" }, render: renderLine, agg: true, group: true, png: true },
    pie: { aggConfig: { measure: "sum" }, render: renderPie, agg: true, group: true, png: true },
    heatmap: { aggConfig: { measure: "sum" }, render: renderHeatmap, agg: true, png: true },
    agg_table: { aggConfig: { measure: "sum" }, render: renderAggTable, agg: true, group: true },
  };

  function cfgMsg(attr, fallback) {
    var el = document.getElementById("view-config");
    return (el && el.getAttribute(attr)) || fallback;
  }

  function renderWidget(section) {
    var body = $("[data-widget-body]", section);
    if (!body) { return; }
    var type = section.getAttribute("data-widget-type") || "";
    var cfg = {};
    try { cfg = JSON.parse(section.getAttribute("data-widget-config") || "{}"); } catch (e) { cfg = {}; }
    var fn = RENDERERS[type];
    var ph = $("[data-widget-placeholder]", section);
    clearBody(body);
    if (!fn) {
      if (ph) { ph.textContent = cfgMsg("data-no-renderer", "This widget type has no visual renderer yet."); }
      return;
    }
    if (fn.agg) {
      cfg = Object.assign({}, (fn.aggConfig || {}), cfg);
      if (!cfg.dataset_id) {
        if (ph) { ph.textContent = cfgMsg("data-no-dataset", "Select a dataset to display data."); }
        return;
      }
      fetchAggregate(cfg)
        .then(function (data) {
          var ok = fn.render(body, data, cfg);
          if (ok !== false && ph) { ph.remove(); }
          if (fn.png) { addPngButton(section); }
        })
        .catch(function () { /* brak danych — zostaje placeholder */ });
      return;
    }
    var done = fn.render(body, cfg);
    if (done !== false && ph) { ph.remove(); }
  }

  function renderAll(root) {
    var nodes = (root || document).querySelectorAll(".widget[data-widget-type]");
    Array.prototype.forEach.call(nodes, renderWidget);
  }

  window.StatDBWidgets = { renderWidget: renderWidget, renderAll: renderAll };

  document.addEventListener("DOMContentLoaded", function () { renderAll(document); });
})();
