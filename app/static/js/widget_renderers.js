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

  function datasetMeta(dsId) {
    var list = window.StatDBDatasets;
    if (!list) { return null; }
    var n = parseInt(dsId, 10);
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === n) { return list[i]; }
    }
    return null;
  }

  function columnMeta(dsId, key) {
    var ds = datasetMeta(dsId);
    if (!ds) { return null; }
    var cols = ds.columns || [];
    for (var i = 0; i < cols.length; i++) {
      if (cols[i].key === key) { return cols[i]; }
    }
    return null;
  }

  // Temporal column types first on the bucket axis — so "month (select) over
  // year" produces a chronological x-axis (todo §15.12).
  var TEMPORAL_TYPES = { year: 1, "year-month": 1, date: 1, "date-long": 1, datetime: 1 };

  function groupByList(config) {
    var groups = [];
    if (config.group_by) { groups.push(String(config.group_by)); }
    if (config.group_by_2) { groups.push(String(config.group_by_2)); }
    if (groups.length < 2) {
      return groups.length ? groups[0] : null;
    }
    var typed = groups.map(function (g) {
      var col = columnMeta(config.dataset_id, g);
      return { g: g, temporal: !!(col && TEMPORAL_TYPES[col.type]) };
    });
    var stably = typed.slice().sort(function (a, b) {
      return (b.temporal ? 1 : 0) - (a.temporal ? 1 : 0);
    });
    return stably.map(function (t) { return t.g; });
  }

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
      group_by: groupByList(config),
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
    // Supports: grouped (single series) and stacked (multi series w/ colors).
    // Issue #11 / todo §15.11: axis labels, grid, tooltips, legend.
    var seriesList = [];
    if (data && data.kind === "stacked" && data.buckets && data.buckets.length) {
      data.series.forEach(function (sr) {
        seriesList.push({
          label: sr.label,
          color: sr.color || DEFAULT_COLORS[seriesList.length % DEFAULT_COLORS.length],
          points: data.buckets.map(function (b, i) {
            return { label: b.label, value: Number(sr.values[i]) || 0 };
          }),
        });
      });
    } else {
      var pts = rowsToPoints(data);
      if (!pts.length) { return false; }
      seriesList.push({
        label: config.column || config.measure || "",
        color: cssVar("--accent", DEFAULT_COLORS[0]),
        points: pts,
      });
    }
    var labels = seriesList[0].points.map(function (p) { return p.label; });
    var w = 320, h = 160, padL = 44, padR = 10, padT = 12, padB = 34;
    var allVals = [];
    seriesList.forEach(function (sr) { sr.points.forEach(function (p) { allVals.push(p.value); }); });
    var max = Math.max.apply(null, allVals);
    var min = Math.min.apply(null, allVals);
    if (min === max) { min -= 1; max += 1; }
    var span = max - min;
    var iw = w - padL - padR, ih = h - padT - padB;
    var n = labels.length;
    var labelEvery = Math.max(1, Math.ceil(n / 10));
    var svgNS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("class", "widget-line");
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    var axisColor = cssVar("--fg-dim", "#888");
    function px(i) { return padL + (n === 1 ? iw / 2 : iw * (i / (n - 1))); }
    function py(v) { return padT + ih - ih * ((v - min) / span); }
    // horizontal gridlines + y-axis value labels
    for (var g = 0; g <= 4; g++) {
      var v = min + span * g / 4;
      var y = py(v);
      var line = document.createElementNS(svgNS, "line");
      line.setAttribute("x1", padL); line.setAttribute("x2", w - padR);
      line.setAttribute("y1", y); line.setAttribute("y2", y);
      line.setAttribute("stroke", axisColor);
      line.setAttribute("stroke-opacity", "0.25");
      line.setAttribute("stroke-width", "1");
      svg.appendChild(line);
      var yt = document.createElementNS(svgNS, "text");
      yt.setAttribute("x", padL - 6); yt.setAttribute("y", y + 3);
      yt.setAttribute("text-anchor", "end");
      yt.setAttribute("class", "axis-label");
      yt.textContent = fmtNumber(Math.round(v * 100) / 100);
      svg.appendChild(yt);
    }
    // x-axis labels (thinned so they don't overlap)
    labels.forEach(function (lab, i) {
      if (i % labelEvery !== 0 && i !== n - 1) { return; }
      var xt = document.createElementNS(svgNS, "text");
      xt.setAttribute("x", px(i)); xt.setAttribute("y", h - padB + 16);
      xt.setAttribute("text-anchor", i === 0 ? "start" : (i === n - 1 ? "end" : "middle"));
      xt.setAttribute("class", "axis-label");
      xt.textContent = lab;
      svg.appendChild(xt);
    });
    // series polylines + point tooltips
    seriesList.forEach(function (sr) {
      var path = "";
      sr.points.forEach(function (p, i) {
        path += (i === 0 ? "M" : " L") + px(i).toFixed(1) + " " + py(p.value).toFixed(1);
      });
      var pl = document.createElementNS(svgNS, "path");
      pl.setAttribute("d", path);
      pl.setAttribute("fill", "none");
      pl.setAttribute("stroke", sr.color);
      pl.setAttribute("stroke-width", "2");
      svg.appendChild(pl);
      sr.points.forEach(function (p, i) {
        var c = document.createElementNS(svgNS, "circle");
        c.setAttribute("cx", px(i).toFixed(1));
        c.setAttribute("cy", py(p.value).toFixed(1));
        c.setAttribute("r", "3");
        c.setAttribute("fill", sr.color);
        var t = document.createElementNS(svgNS, "title");
        t.textContent = p.label + ": " + fmtNumber(p.value) + (seriesList.length > 1 ? " (" + sr.label + ")" : "");
        c.appendChild(t);
        svg.appendChild(c);
      });
    });
    body.appendChild(svg);
    // legend for multi-series
    if (seriesList.length > 1) {
      var legend = document.createElement("div");
      legend.className = "chart-legend";
      seriesList.forEach(function (sr) {
        var item = document.createElement("span");
        item.className = "chart-legend-item";
        var dot = document.createElement("span");
        dot.className = "chart-legend-dot";
        dot.style.background = sr.color;
        item.appendChild(dot);
        item.appendChild(document.createTextNode(" " + sr.label));
        legend.appendChild(item);
      });
      body.appendChild(legend);
    }
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

  // grouped (single-axis) result → stacked shape with one synthetic series,
  // so heatmap/stacked widgets degrade gracefully without a series column.
  function groupedToStacked(data) {
    if (!data || data.kind !== "grouped" || !Array.isArray(data.items)) { return data; }
    return {
      kind: "stacked",
      measure: data.measure,
      buckets: data.items.map(function (it) {
        return { key: it.key, label: it.label, sort: it.sort };
      }),
      series: [
        {
          key: "__value",
          label: data.measure || "value",
          color: null,
          values: data.items.map(function (it) { return it.value; }),
        },
      ],
    };
  }

  function renderStackedBar(body, data, config) {
    if (!data) { return false; }
    if (data.kind === "grouped") {
      // no series column configured — degrade to a single-series breakdown
      // so the widget still renders (todo §15.10-style fallback)
      data = groupedToStacked(data);
    }
    if (data.kind !== "stacked" || !data.buckets.length) { return false; }
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
    if (!data) { return false; }
    if (data.kind === "grouped") {
      // no series column — fall back to a single-column heatmap instead of
      // bailing out with a misleading "configure" note (todo §15.10)
      data = groupedToStacked(data);
    }
    if (data.kind !== "stacked" || !data.buckets.length || !data.series.length) { return false; }
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

  // ---- data table & add-record form (issue #9 / todo §15.9) ----

  function fetchRows(config) {
    var limit = Math.min(parseInt(config.limit, 10) || 20, 500);
    var url = "/api/datasets/" + encodeURIComponent(config.dataset_id) +
              "/rows?page=1&page_size=" + limit;
    var g = window.StatDBFilter;
    if (g && g.column && g.value !== undefined && g.value !== "" &&
        String(g.datasetId) === String(config.dataset_id)) {
      url += "&f." + encodeURIComponent(g.column) + "." + encodeURIComponent(g.op || "eq") +
             "=" + encodeURIComponent(g.value);
    }
    return fetch(url).then(function (res) {
      if (!res.ok) { return res.text().then(function (txt) { throw new Error(txt); }); }
      return res.json();
    });
  }

  function cellText(value, col) {
    if (value === null || value === undefined) { return ""; }
    if (col && col.type === "select" && Array.isArray(col.options)) {
      for (var i = 0; i < col.options.length; i++) {
        if (String(col.options[i].key) === String(value)) {
          return col.options[i].label !== undefined ? col.options[i].label : String(value);
        }
      }
      return String(value);
    }
    if (typeof value === "boolean") { return value ? "\u2713" : "\u2717"; }
    return String(value);
  }

  function renderTable(body, data, config) {
    if (!data || !Array.isArray(data.items)) { return false; }
    var ds = datasetMeta(config.dataset_id);
    var cols = (ds && ds.columns) || [];
    if (!cols.length) { return false; }
    var shown = data.items.length;
    var total = (data.total !== undefined) ? data.total : shown;
    var wrap = document.createElement("div");
    wrap.className = "widget-table";
    var table = document.createElement("table");
    table.className = "table";
    var thead = document.createElement("thead");
    var trH = document.createElement("tr");
    cols.forEach(function (c) {
      var th = document.createElement("th");
      th.textContent = c.label || c.key;
      trH.appendChild(th);
    });
    thead.appendChild(trH);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    data.items.forEach(function (row) {
      var tr = document.createElement("tr");
      cols.forEach(function (c) {
        var td = document.createElement("td");
        td.textContent = cellText(row[c.key], c);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    if (total > shown || total > 0) {
      var foot = document.createElement("div");
      foot.className = "muted small widget-table-foot";
      foot.textContent = cfgMsg("data-table-rows", "{shown} of {total} rows")
        .replace("{shown}", String(shown)).replace("{total}", String(total));
      wrap.appendChild(foot);
    }
    body.appendChild(wrap);
    return true;
  }

  function renderForm(body, config) {
    var ds = datasetMeta(config.dataset_id);
    var cols = (ds && ds.columns) || [];
    if (!cols.length) { return false; }
    var wrap = document.createElement("div");
    wrap.className = "widget-form";
    var form = document.createElement("form");
    form.className = "widget-form-fields";
    var msg = document.createElement("div");
    msg.className = "muted small";
    cols.forEach(function (c) {
      if (c.type === "formula") { return; } // computed, not editable
      var label = document.createElement("label");
      label.className = "widget-form-label";
      var name = document.createElement("span");
      name.textContent = c.label || c.key;
      label.appendChild(name);
      var input;
      if (c.type === "select" && Array.isArray(c.options) && c.options.length) {
        input = document.createElement("select");
        var empty = document.createElement("option");
        empty.value = "";
        empty.textContent = "—";
        input.appendChild(empty);
        c.options.forEach(function (o) {
          var opt = document.createElement("option");
          opt.value = o.key;
          opt.textContent = o.label !== undefined ? o.label : o.key;
          input.appendChild(opt);
        });
      } else if (c.type === "number" || c.type === "currency") {
        input = document.createElement("input");
        input.type = "number";
        if (c.type === "currency") { input.step = "0.01"; }
      } else if (c.type === "bool") {
        input = document.createElement("input");
        input.type = "checkbox";
      } else if (c.type === "date") {
        input = document.createElement("input");
        input.type = "date";
      } else if (c.type === "datetime") {
        input = document.createElement("input");
        input.type = "datetime-local";
      } else {
        input = document.createElement("input");
        input.type = "text";
      }
      input.setAttribute("data-col-key", c.key);
      input.setAttribute("data-col-type", c.type);
      label.appendChild(input);
      form.appendChild(label);
    });
    var submit = document.createElement("button");
    submit.type = "submit";
    submit.textContent = "+";
    form.appendChild(submit);
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var payload = {};
      Array.prototype.forEach.call(form.querySelectorAll("[data-col-key]"), function (el) {
        var key = el.getAttribute("data-col-key");
        if (el.type === "checkbox") { payload[key] = el.checked; }
        else if (el.value !== "") {
          if (el.type === "number") { payload[key] = Number(el.value); }
          else { payload[key] = el.value; }
        }
      });
      fetch("/api/datasets/" + encodeURIComponent(config.dataset_id) + "/rows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(function (res) {
        if (!res.ok) { return res.text().then(function (txt) { throw new Error(txt); }); }
        msg.textContent = "\u2713";
        form.reset();
        renderAll(document); // refresh dependent widgets
      }).catch(function (err) {
        msg.textContent = String(err && err.message ? err.message : "error");
      });
    });
    wrap.appendChild(form);
    wrap.appendChild(msg);
    body.appendChild(wrap);
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
    note:          { render: renderNote },
    global_filter: { render: renderGlobalFilter, needsDataset: true },
    kpi_sum:       { aggConfig: { measure: "sum" }, render: renderKpi, agg: true },
    kpi_avg:       { aggConfig: { measure: "avg" }, render: renderKpi, agg: true },
    kpi_min:       { aggConfig: { measure: "min" }, render: renderKpi, agg: true },
    kpi_max:       { aggConfig: { measure: "max" }, render: renderKpi, agg: true },
    kpi_count:     { aggConfig: { measure: "count" }, render: renderKpi, agg: true },
    kpi_median:    { aggConfig: { measure: "median" }, render: renderKpi, agg: true },
    kpi_trend:     { aggConfig: { measure: "sum", showTrend: true }, render: renderKpi, agg: true },
    bar:           { aggConfig: { measure: "sum" }, render: renderBar, agg: true, group: true },
    stacked_bar:   { aggConfig: { measure: "sum" }, render: renderStackedBar, agg: true, png: true },
    line:          { aggConfig: { measure: "sum" }, render: renderLine, agg: true, group: true, png: true },
    pie:           { aggConfig: { measure: "sum" }, render: renderPie, agg: true, group: true, png: true },
    heatmap:       { aggConfig: { measure: "sum" }, render: renderHeatmap, agg: true, png: true },
    agg_table:     { aggConfig: { measure: "sum" }, render: renderAggTable, agg: true, group: true },
    table:         { render: renderTable, rows: true, needsDataset: true },
    form:          { render: renderForm, needsDataset: true },
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
    function showNoData() {
      // distinct from "configure this widget" — the config is fine, there is
      // just nothing to draw (todo §15.9 / §15.10)
      if (ph) { ph.textContent = cfgMsg("data-no-data", "No data to display for this configuration."); }
    }
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
          if (ok === false) { showNoData(); return; }
          if (ph) { ph.remove(); }
          if (fn.png) { addPngButton(section); }
        })
        .catch(function () { showNoData(); });
      return;
    }
    if (fn.rows) {
      // raw data table — reads dataset rows instead of aggregating
      if (!cfg.dataset_id) {
        if (ph) { ph.textContent = cfgMsg("data-no-dataset", "Select a dataset to display data."); }
        return;
      }
      fetchRows(cfg)
        .then(function (data) {
          var ok = fn.render(body, data, cfg);
          if (ok === false) { showNoData(); return; }
          if (ph) { ph.remove(); }
        })
        .catch(function () { showNoData(); });
      return;
    }
    if (fn.needsDataset && !cfg.dataset_id) {
      if (ph) { ph.textContent = cfgMsg("data-no-dataset", "Select a dataset to display data."); }
      return;
    }
    var done = fn.render(body, cfg);
    if (done === false) { showNoData(); return; }
    if (done !== false && ph) { ph.remove(); }
  }

  function renderAll(root) {
    var nodes = (root || document).querySelectorAll(".widget[data-widget-type]");
    Array.prototype.forEach.call(nodes, renderWidget);
  }

  window.StatDBWidgets = { renderWidget: renderWidget, renderAll: renderAll };

  document.addEventListener("DOMContentLoaded", function () { renderAll(document); });
})();
