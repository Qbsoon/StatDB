/*
 * StatDB — column configuration editor (type-specific GUI, no raw JSON).
 *
 * Each config section (.cfg-block) carries a `data-form` attribute matching the
 * id of the <form> it belongs to. A hidden input[data-config-input][data-form]
 * holds the JSON config, kept in sync whenever the user edits any field.
 */
(function () {
  "use strict";

  function forEach(list, fn) { Array.prototype.forEach.call(list, fn); }

  function escAttr(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  /* ---------- building the config JSON from DOM ---------- */

  function buildOptionLabel(row, translationsOn) {
    var label = ((row.querySelector(".cfg-opt-label") || {}).value || "").trim();
    if (!translationsOn) return label;
    var en = ((row.querySelector(".cfg-opt-en") || {}).value || "").trim();
    var pl = ((row.querySelector(".cfg-opt-pl") || {}).value || "").trim();
    if (!en && !pl) return label;
    var obj = {};
    if (en) obj.en = en; else if (label) obj.en = label;
    if (pl) obj.pl = pl; else if (label) obj.pl = label;
    return obj;
  }

  function buildOption(row, translationsOn) {
    var opt = { key: row.getAttribute("data-key"), label: buildOptionLabel(row, translationsOn) };
    var has = row.querySelector(".cfg-opt-has-color");
    if (has && has.checked) {
      var c = row.querySelector(".cfg-opt-color");
      if (c && c.value) opt.color = c.value;
    }
    return opt;
  }

  function buildSelectConfig(block) {
    var translationsOn = false;
    var t = block.querySelector("[data-translations-toggle]");
    if (t) translationsOn = t.checked;
    var options = [];
    forEach(block.querySelectorAll(".cfg-option-row"), function (row) {
      options.push(buildOption(row, translationsOn));
    });
    return { options: options };
  }

  function buildScalarConfig(block) {
    var config = {};
    forEach(block.querySelectorAll("[data-cfg]"), function (el) {
      var key = el.getAttribute("data-cfg");
      var raw = (el.value || "").trim();
      if (raw === "") return;
      if (el.getAttribute("type") === "number") {
        var n = parseInt(raw, 10);
        if (!isNaN(n)) config[key] = n;
      } else {
        config[key] = raw;
      }
    });
    return config;
  }

  function buildConfig(block) {
    return block.getAttribute("data-config-type") === "select"
      ? buildSelectConfig(block) : buildScalarConfig(block);
  }

  /* ---------- syncing the hidden input ---------- */

  function findInput(formId) {
    return document.querySelector('input[data-config-input][data-form="' + formId + '"]');
  }

  function visibleBlock(formId) {
    var blocks = document.querySelectorAll('.cfg-block[data-form="' + formId + '"]');
    for (var i = 0; i < blocks.length; i++) {
      var b = blocks[i];
      // Skip blocks inside the add-form that don't have .is-active
      if (b.closest(".cfg-add-sections") && !b.classList.contains("is-active")) continue;
      if (!b.hidden) return b;
    }
    return null;
  }

  function syncForm(formId) {
    var input = findInput(formId);
    if (!input) return;
    var block = visibleBlock(formId);
    if (!block) return;  // no config GUI → keep existing hidden value
    input.value = JSON.stringify(buildConfig(block));
  }

  function blockFormId(block) { return block.getAttribute("data-form"); }

  /* ---------- option row management ---------- */

  function nextKey(block) {
    var n = parseInt(block.getAttribute("data-next-key") || "1", 10);
    block.setAttribute("data-next-key", String(n + 1));
    return String(n);
  }

  function createOptionRow(block) {
    var key = nextKey(block);
    var formId = blockFormId(block);
    var labelPh = escAttr(block.getAttribute("data-label-ph"));
    var delTitle = escAttr(block.getAttribute("data-del-title"));
    var div = document.createElement("div");
    div.className = "cfg-option-row";
    div.setAttribute("data-option", "");
    div.setAttribute("data-key", key);
    div.innerHTML =
      '<button type="button" class="cfg-move" data-move="up" title="▲">▲</button>' +
      '<button type="button" class="cfg-move" data-move="down" title="▼">▼</button>' +
      '<input type="text" class="cfg-opt-label" form="' + formId + '" placeholder="' + labelPh + '">' +
      '<input type="text" class="cfg-opt-en cfg-trans" form="' + formId + '" placeholder="EN">' +
      '<input type="text" class="cfg-opt-pl cfg-trans" form="' + formId + '" placeholder="PL">' +
      '<label class="cfg-opt-color-wrap">' +
        '<input type="checkbox" class="cfg-opt-has-color">' +
        '<input type="color" class="cfg-opt-color" form="' + formId + '" value="#4f8cff">' +
      '</label>' +
      '<button type="button" class="cfg-remove" data-remove-option title="' + delTitle + '">\u00d7</button>';
    return div;
  }

  function updateTranslationsVisibility(block) {
    var t = block.querySelector("[data-translations-toggle]");
    var on = !!(t && t.checked);
    block.classList.toggle("show-trans", on);
  }

  function addOption(block) {
    var list = block.querySelector("[data-options-list]");
    if (!list) return;
    var row = createOptionRow(block);
    list.appendChild(row);
    updateTranslationsVisibility(block);
    syncForm(blockFormId(block));
  }

  function removeOption(row, block) {
    row.parentNode.removeChild(row);
    syncForm(blockFormId(block));
  }

  function moveOption(row, dir) {
    var block = row.closest(".cfg-block");
    if (!block) return;
    var rows = Array.prototype.slice.call(block.querySelectorAll(".cfg-option-row"));
    var idx = rows.indexOf(row);
    var target = dir === "up" ? idx - 1 : idx + 1;
    if (target < 0 || target >= rows.length) return;
    if (dir === "up") row.parentNode.insertBefore(row, rows[target]);
    else row.parentNode.insertBefore(row, rows[target].nextSibling);
    syncForm(blockFormId(block));
  }

  /* ---------- add-form type switching ---------- */

  function showAddSection() {
    var sel = document.querySelector("[data-add-type]");
    if (!sel) return;
    var ty = sel.value;
    var wrap = document.querySelector("[data-add-sections]");
    if (!wrap) return;
    var anyVisible = false;
    forEach(wrap.querySelectorAll(".cfg-block"), function (block) {
      var show = block.getAttribute("data-config-type") === ty;
      block.classList.toggle("is-active", show);
      if (show) anyVisible = true;
    });
    if (!anyVisible) {
      var input = findInput("col-add");
      if (input) input.value = "{}";
    } else {
      syncForm("col-add");
    }
  }

  /* ---------- event wiring ---------- */

  function initBlock(block) {
    if (block.getAttribute("data-config-type") === "select") {
      updateTranslationsVisibility(block);
    }
  }

  document.addEventListener("input", function (ev) {
    var block = ev.target.closest(".cfg-block");
    if (block) syncForm(blockFormId(block));
  });

  document.addEventListener("change", function (ev) {
    var addType = ev.target.closest("[data-add-type]");
    if (addType) { showAddSection(); return; }
    var transToggle = ev.target.closest("[data-translations-toggle]");
    if (transToggle) {
      var block = transToggle.closest(".cfg-block");
      if (block) { updateTranslationsVisibility(block); syncForm(blockFormId(block)); }
      return;
    }
    var block = ev.target.closest(".cfg-block");
    if (block) syncForm(blockFormId(block));
  });

  document.addEventListener("click", function (ev) {
    var add = ev.target.closest("[data-add-option]");
    if (add) {
      var block = add.closest(".cfg-block");
      if (block) addOption(block);
      return;
    }
    var rm = ev.target.closest("[data-remove-option]");
    if (rm) {
      var row = rm.closest(".cfg-option-row");
      var block = rm.closest(".cfg-block");
      if (row && block) removeOption(row, block);
      return;
    }
    var move = ev.target.closest("[data-move]");
    if (move) {
      var row = move.closest(".cfg-option-row");
      if (row) moveOption(row, move.getAttribute("data-move"));
      return;
    }
  });

  /* final sync before submit, so last keystroke is captured */
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    var formId = form.id;
    if (formId && findInput(formId)) syncForm(formId);
  }, true);

  /* ---------- boot ---------- */
  function boot() {
    forEach(document.querySelectorAll(".cfg-block"), initBlock);
    if (document.querySelector("[data-add-type]")) showAddSection();
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
