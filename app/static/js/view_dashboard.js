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

  // Widgets
  var editSection = $("#widget-edit-section");
  var editForm = $("#widget-edit-form");
  var editTitle = $("#widget-edit-title");
  var editConfig = $("#widget-edit-config");
  var editCancel = $("#widget-edit-cancel");
  var currentWidgetNode = null;

  function openEdit(node) {
    currentWidgetNode = node;
    var title = $(".widget-title", node).textContent.trim();
    editTitle.value = title;
    editConfig.value = JSON.stringify({});
    editSection.removeAttribute("hidden");
    editSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
    editTitle.focus();
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
    editForm.addEventListener("submit", function (ev) {
      if (!currentWidgetNode) { ev.preventDefault(); return; }
      ev.preventDefault();
      var wid = currentWidgetNode.getAttribute("gs-id");
      var action = editForm.getAttribute("action").replace(/\/widgets\/0(\?|$)/, "/widgets/" + wid + "$1");
      var body = new FormData();
      body.set("title", editTitle.value);
      body.set("config", editConfig.value);
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
        var type = widget.getAttribute("data-widget-type");
        var config = {};
        try { config = JSON.parse(widget.getAttribute("data-widget-config") || "{}"); } catch (e) {}
        var body = $("[data-widget-body]", widget);
        var placeholder = $("[data-widget-placeholder]", widget);
        if (placeholder) { placeholder.style.display = "none"; }
        if (body) { body.innerHTML = ""; }
        if (window.StatDBRenderers) {
          window.StatDBRenderers.render(type, body || widget, { config: config });
        }
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
