// StatDB — drag/resize save + widget edit/delete (F8)
(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  var cfgEl = $("#view-config");
  if (!cfgEl) { return; }
  var viewId = cfgEl.getAttribute("data-view-id");
  var confirmMsg = cfgEl.getAttribute("data-confirm-delete") || "Delete this widget?";
  var layoutUrl = cfgEl.getAttribute("data-layout-url");
  var gridEl = $("#grid");
  var grid = window.GridStack ? window.GridStack.init({ margin: 8, cellHeight: 96, column: 12, float: false, disableOneColumnMode: true }, gridEl) : null;
  var layoutDirty = false;
  var saveTimer = null;

  // Layout save on drag/resize (debounced)
  if (grid) {
    grid.on("change", function () {
      layoutDirty = true;
      clearTimeout(saveTimer);
      saveTimer = setTimeout(saveLayout, 700);
    });
  }

  function saveLayout() {
    if (!layoutDirty || !layoutUrl) { return; }
    layoutDirty = false;
    var items = $$(".grid-stack-item", gridEl).map(function (node) {
      return {
        id: node.getAttribute("gs-id"),
        x: parseInt(node.getAttribute("gs-x"), 10),
        y: parseInt(node.getAttribute("gs-y"), 10),
        w: parseInt(node.getAttribute("gs-w"), 10),
        h: parseInt(node.getAttribute("gs-h"), 10),
      };
    });
    fetch(layoutUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(items) })
      .catch(function () {});
  }

  // ---- datasets & column picker (issues #2, #3) ----
  var datasetsData = [];
  try {
    var dsEl = document.getElementById("datasets-json");
    if (dsEl) { datasetsData = JSON.parse(dsEl.textContent || "[]"); }
  } catch (e) { datasetsData = []; }

  // Expose dataset metadata for widget renderers (labels, select options)
  window.StatDBDatasets = datasetsData;

  function datasetColumns(dsId) {
    var n = parseInt(dsId, 10);
    for (var i = 0; i < datasetsData.length; i++) {
      if (datasetsData[i].id === n) { return datasetsData[i].columns || []; }
    }
    return [];
  }

  function populateColumns(select, columns, selected) {
    if (!select) { return; }
    select.innerHTML = '<option value=""></option>';
    columns.forEach(function (c) {
      var opt = document.createElement("option");
      opt.value = c.key;
      opt.textContent = c.label || c.key;
      if (selected && c.key === selected) { opt.selected = true; }
      select.appendChild(opt);
    });
  }

  // Which fields each widget type needs
  // (heatmap needs "series" so it can have two axes — issue #10 / todo §15.10;
  //  group_by_2 = composite bucket axis, e.g. month + year — todo §15.12)
  var FIELD_RULES = {
    note:          ["text"],
    global_filter: ["dataset", "column"],
    kpi_sum:       ["dataset", "column"],
    kpi_avg:       ["dataset", "column"],
    kpi_min:       ["dataset", "column"],
    kpi_max:       ["dataset", "column"],
    kpi_count:     ["dataset"],
    kpi_median:    ["dataset", "column"],
    kpi_trend:     ["dataset", "column"],
    bar:           ["dataset", "measure", "column", "group_by", "group_by_2"],
    stacked_bar:   ["dataset", "measure", "column", "group_by", "group_by_2", "series"],
    line:          ["dataset", "measure", "column", "group_by", "group_by_2"],
    pie:           ["dataset", "measure", "column", "group_by"],
    heatmap:       ["dataset", "measure", "column", "group_by", "group_by_2", "series"],
    agg_table:     ["dataset", "measure", "column", "group_by", "group_by_2"],
    table:         ["dataset"],
    form:          ["dataset"],
  };
  function visibleFields(type) { return FIELD_RULES[type] || []; }

  var FIELD_ID_MAP = { dataset: "dataset", column: "column", measure: "measure", group_by: "groupby", group_by_2: "groupby2", series: "series", text: "text" };

  function updateFieldVisibility(form) {
    if (!form) { return; }
    var typeEl = form.querySelector("#wc-type") || form.querySelector("#we-type");
    var type = typeEl ? typeEl.value : "";
    var fields = visibleFields(type);
    $$("[data-field]", form).forEach(function (label) {
      var f = label.getAttribute("data-field");
      if (fields.indexOf(f) === -1) {
        label.setAttribute("hidden", "");
      } else {
        label.removeAttribute("hidden");
      }
    });
  }

  function buildConfig(form, prefix) {
    var typeEl = form.querySelector("#" + prefix + "-type");
    var type = typeEl ? typeEl.value : "";
    var fields = visibleFields(type);
    var config = {};
    fields.forEach(function (f) {
      var el = form.querySelector("#" + prefix + "-" + (FIELD_ID_MAP[f] || f));
      if (!el) { return; }
      var val = el.value;
      if (f === "dataset") {
        if (val) { config["dataset_id"] = parseInt(val, 10); }
      } else if (f === "text") {
        if (val && val.trim()) { config["text"] = val.trim(); }
      } else {
        if (val && val.trim()) { config[f] = val.trim(); }
      }
    });
    return config;
  }

  function bindDatasetChange(form, prefix) {
    var dsEl = form.querySelector("#" + prefix + "-dataset");
    if (!dsEl) { return; }
    dsEl.addEventListener("change", function () {
      var cols = datasetColumns(dsEl.value);
      ["column", "groupby", "groupby2", "series"].forEach(function (suffix) {
        var sel = form.querySelector("#" + prefix + "-" + suffix);
        if (sel) { populateColumns(sel, cols, ""); }
      });
    });
  }

  // ---- create form (issues #2, #3) ----
  var createForm = $("#widget-create-form");
  if (createForm) {
    var wcType = $("#wc-type");
    if (wcType) { wcType.addEventListener("change", function () { updateFieldVisibility(createForm); }); }
    bindDatasetChange(createForm, "wc");
    updateFieldVisibility(createForm);
    createForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      $("#wc-config").value = JSON.stringify(buildConfig(createForm, "wc"));
      createForm.submit();
    });
  }

  // ---- edit form (issues #2, #3, #5) ----
  var editSection = $("#widget-edit-section");
  var editForm = $("#widget-edit-form");
  var editCancel = $("#widget-edit-cancel");
  var currentWidgetNode = null;

  function openEdit(node) {
    currentWidgetNode = node;
    var title = $(".widget-title", node).textContent.trim();
    $("#we-title").value = title;
    var widget = $(".widget", node);
    var type = widget ? widget.getAttribute("data-widget-type") : "";
    var cfg = {};
    try { cfg = JSON.parse(widget ? (widget.getAttribute("data-widget-config") || "{}") : "{}"); } catch (e) { cfg = {}; }
    var weType = $("#we-type");
    if (weType) { weType.value = type; }
    if (cfg.dataset_id) {
      var weDs = $("#we-dataset");
      if (weDs) { weDs.value = String(cfg.dataset_id); }
      var cols = datasetColumns(cfg.dataset_id);
      [{ s: "column", k: "column" }, { s: "groupby", k: "group_by" }, { s: "groupby2", k: "group_by_2" }, { s: "series", k: "series" }].forEach(function (m) {
        var sel = $("#we-" + m.s);
        if (sel) { populateColumns(sel, cols, cfg[m.k] || ""); }
      });
    } else {
      ["column", "groupby", "groupby2", "series"].forEach(function (suffix) {
        var sel = $("#we-" + suffix);
        if (sel) { sel.innerHTML = '<option value=""></option>'; }
      });
    }
    var weMeasure = $("#we-measure");
    if (weMeasure && cfg.measure) { weMeasure.value = cfg.measure; }
    var weText = $("#we-text");
    if (weText) { weText.value = cfg.text || ""; }
    updateFieldVisibility(editForm);
    editSection.removeAttribute("hidden");
    editSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
    $("#we-title").focus();
  }
  function closeEdit() {
    currentWidgetNode = null;
    editSection.setAttribute("hidden", "");
  }

  if (gridEl) {
    gridEl.addEventListener("click", function (ev) {
      var btn = ev.target.closest("button");
      if (!btn) { return; }
      var node = btn.closest(".grid-stack-item");
      if (!node) { return; }
      if (btn.classList.contains("widget-delete")) {
        var title = $(".widget-title", node).textContent.trim();
        var msg = confirmMsg.replace("{title}", title || node.getAttribute("gs-id"));
        if (!confirm(msg)) { return; }
        var delUrl = "/views/" + encodeURIComponent(viewId) + "/widgets/" + encodeURIComponent(node.getAttribute("gs-id")) + "/delete";
        fetch(delUrl, { method: "POST" })
          .then(function () { location.reload(); })
          .catch(function () {});
      } else if (btn.classList.contains("widget-edit")) {
        openEdit(node);
      }
    });
  }

  if (editCancel) {
    editCancel.addEventListener("click", function () { closeEdit(); });
  }

  if (editForm) {
    var weTypeEl = $("#we-type");
    if (weTypeEl) { weTypeEl.addEventListener("change", function () { updateFieldVisibility(editForm); }); }
    bindDatasetChange(editForm, "we");
    editForm.addEventListener("submit", function (ev) {
      if (!currentWidgetNode) { ev.preventDefault(); return; }
      ev.preventDefault();
      var wid = currentWidgetNode.getAttribute("gs-id");
      var action = editForm.getAttribute("action").replace(/\/widgets\/0(\?|$)/, "/widgets/" + wid + "$1");
      var body = new FormData();
      body.set("title", $("#we-title").value);
      body.set("config", JSON.stringify(buildConfig(editForm, "we")));
      fetch(action, { method: "POST", body: body })
        .then(function () { location.reload(); })
        .catch(function () {});
    });
  }

  // --- F15: auto-refresh ---
  var settings = {};
  try { settings = JSON.parse(cfgEl.getAttribute("data-settings") || "{}"); } catch (e) {}
  if (settings.refresh && settings.refresh > 0) {
    setInterval(function () {
      $$(".widget", gridEl).forEach(function (widget) {
        if (window.StatDBWidgets) { window.StatDBWidgets.renderWidget(widget); }
      });
    }, settings.refresh * 1000);
  }

  // --- F15: kiosk mode ---
  var kioskBtn = $("#kiosk-toggle");
  var kioskExitMsg = cfgEl.getAttribute("data-kiosk-exit") || "Exit kiosk";

  function enterKiosk() {
    document.body.classList.add("kiosk-mode");
    try {
      var p = document.documentElement.requestFullscreen();
      if (p && p.catch) { p.catch(function () {}); }
    } catch (e) {}
  }
  function exitKiosk() {
    document.body.classList.remove("kiosk-mode");
    try {
      var p = document.exitFullscreen();
      if (p && p.catch) { p.catch(function () {}); }
    } catch (e) {}
  }

  if (kioskBtn) {
    kioskBtn.addEventListener("click", function () {
      if (document.body.classList.contains("kiosk-mode")) { exitKiosk(); } else { enterKiosk(); }
    });
  }
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && document.body.classList.contains("kiosk-mode")) { exitKiosk(); }
  });

  if (settings.kiosk) { enterKiosk(); }

  window.addEventListener("beforeunload", function (ev) {
    if (layoutDirty) { ev.preventDefault(); ev.returnValue = ""; }
  });
})();
