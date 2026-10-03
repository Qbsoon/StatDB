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
  //  group_by_2 = composite bucket axis, e.g. month + year — todo §15.12;
  //  sort_by/sort_dir = result ordering options — todo §15.15)
  var SORT_FIELDS = ["sort_by", "sort_dir"];
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
    bar:                    ["dataset", "measure", "column", "per_column", "group_by", "group_by_2"].concat(SORT_FIELDS),
    stacked_bar:            ["dataset", "measure", "column", "per_column", "group_by", "group_by_2", "series"].concat(SORT_FIELDS),
    bar_vertical:           ["dataset", "measure", "column", "per_column", "group_by", "group_by_2"].concat(SORT_FIELDS),
    stacked_bar_vertical:   ["dataset", "measure", "column", "per_column", "group_by", "group_by_2", "series"].concat(SORT_FIELDS),
    line:          ["dataset", "measure", "column", "per_column", "group_by", "group_by_2"].concat(SORT_FIELDS),
    pie:           ["dataset", "measure", "column", "per_column", "group_by"].concat(SORT_FIELDS),
    heatmap:       ["dataset", "measure", "column", "per_column", "group_by", "group_by_2", "series"].concat(SORT_FIELDS),
    agg_table:     ["dataset", "measure", "column", "per_column", "group_by", "group_by_2"].concat(SORT_FIELDS),
    table:         ["dataset"],
    form:          ["dataset"],
  };
  function visibleFields(type) { return FIELD_RULES[type] || []; }

  var FIELD_ID_MAP = {
    dataset: "dataset", column: "column", measure: "measure", per_column: "percolumn",
    group_by: "groupby", group_by_2: "groupby2", series: "series", text: "text",
    sort_by: "sortby", sort_dir: "sortdir",
  };

  function updateFieldVisibility(form) {
    if (!form) { return; }
    var prefix = form.querySelector("#wc-type") ? "wc" : "we";
    var typeEl = form.querySelector("#" + prefix + "-type");
    var type = typeEl ? typeEl.value : "";
    var fields = visibleFields(type);
    $$("[data-field]", form).forEach(function (label) {
      var f = label.getAttribute("data-field");
      var visible = fields.indexOf(f) !== -1;
      if (f === "per_column") {
        // divisor field only matters for the avg_per measure — even for
        // chart types that support it, keep it hidden otherwise
        var m = form.querySelector("#" + prefix + "-measure");
        visible = visible && !!(m && m.value === "avg_per");
      }
      if (!visible) {
        label.setAttribute("hidden", "");
      } else {
        label.removeAttribute("hidden");
      }
    });
  }

  function bindMeasureChange(form, prefix) {
    var m = form.querySelector("#" + prefix + "-measure");
    if (m) { m.addEventListener("change", function () { updateFieldVisibility(form); }); }
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
      } else if (f === "sort_by") {
        // "default" = engine order — don't persist it (todo §15.15)
        if (val && val !== "default") { config["sort_by"] = val; }
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
      ["column", "percolumn", "groupby", "groupby2", "series"].forEach(function (suffix) {
        var sel = form.querySelector("#" + prefix + "-" + suffix);
        if (sel) { populateColumns(sel, cols, ""); }
      });
    });
  }

  // ---- modals (todo §15.17-19): add/edit widget + view settings pop up
  // over a dimmed backdrop; click on the backdrop (or Esc) closes them.
  function openModal(overlay) {
    if (overlay) { overlay.removeAttribute("hidden"); }
  }
  function closeModal(overlay) {
    if (overlay) { overlay.setAttribute("hidden", ""); }
  }
  $$("[data-modal-open]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      openModal(document.getElementById(btn.getAttribute("data-modal-open")));
    });
  });
  $$(".modal-overlay").forEach(function (ov) {
    ov.addEventListener("click", function (ev) {
      if (ev.target === ov) { closeModal(ov); } // click on the dimmed backdrop
    });
  });
  $$("[data-modal-close]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      closeModal(btn.closest(".modal-overlay"));
    });
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      $$(".modal-overlay:not([hidden])").forEach(closeModal);
    }
  });

  // ---- create form (issues #2, #3) ----
  var createForm = $("#widget-create-form");
  if (createForm) {
    var wcType = $("#wc-type");
    if (wcType) { wcType.addEventListener("change", function () { updateFieldVisibility(createForm); }); }
    bindDatasetChange(createForm, "wc");
    bindMeasureChange(createForm, "wc");
    updateFieldVisibility(createForm);
    createForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      $("#wc-config").value = JSON.stringify(buildConfig(createForm, "wc"));
      createForm.submit();
    });
  }

  // ---- edit form (issues #2, #3, #5) ----
  var editModal = $("#widget-edit-modal");
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
      [{ s: "column", k: "column" }, { s: "percolumn", k: "per_column" }, { s: "groupby", k: "group_by" }, { s: "groupby2", k: "group_by_2" }, { s: "series", k: "series" }].forEach(function (m) {
        var sel = $("#we-" + m.s);
        if (sel) { populateColumns(sel, cols, cfg[m.k] || ""); }
      });
    } else {
      ["column", "percolumn", "groupby", "groupby2", "series"].forEach(function (suffix) {
        var sel = $("#we-" + suffix);
        if (sel) { sel.innerHTML = '<option value=""></option>'; }
      });
    }
    var weMeasure = $("#we-measure");
    if (weMeasure && cfg.measure) { weMeasure.value = cfg.measure; }
    var weSortBy = $("#we-sortby");
    if (weSortBy) { weSortBy.value = cfg.sort_by || "default"; }
    var weSortDir = $("#we-sortdir");
    if (weSortDir) { weSortDir.value = cfg.sort_dir || "asc"; }
    var weText = $("#we-text");
    if (weText) { weText.value = cfg.text || ""; }
    updateFieldVisibility(editForm);
    openModal(editModal); // pops up over the grid (todo §15.18)
    $("#we-title").focus();
  }
  function closeEdit() {
    currentWidgetNode = null;
    closeModal(editModal);
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
    bindMeasureChange(editForm, "we");
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
