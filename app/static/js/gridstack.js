/*!
 * gridstack.js — minimal vendored grid manager (drag & drop / resize) for StatDB (F8).
 * API-compatible subset: GridStack.init(options), .save(), .on("change"), .update(),
 * adds 'gs-id', 'gs-x', 'gs-y' (24px rows), 'gs-w', 'gs-h' attributes and manages
 * .grid-stack-item layout on a 12-col grid.
 */
(function () {
  "use strict";

  var CELL_H = 96;           // px per row unit (gs-h)
  var CELL_GAP = 8;
  var COL_COUNT = 12;

  function px(n) { return n + "px"; }

  function toInt(v, fallback) {
    v = parseInt(v, 10);
    return isNaN(v) ? fallback : v;
  }

  function GridStack(el, opts) {
    this.el = el;
    this.opts = opts || {};
    this.opts.column = this.opts.column || COL_COUNT;
    this.opts.cellHeight = toInt(this.opts.cellHeight, CELL_H);
    this._items = [];
    this._bind();
    this._layout();
    this._onChange = [];
  }

  GridStack.prototype._bind = function () {
    var self = this;
    this.el.querySelectorAll(".grid-stack-item").forEach(function (node) {
      self._initItem(node);
    });
  };

  GridStack.prototype._initItem = function (node) {
    if (node._gs) { return; }
    var self = this;
    node._gs = {
      x: toInt(node.getAttribute("gs-x"), 0),
      y: toInt(node.getAttribute("gs-y"), 0),
      w: toInt(node.getAttribute("gs-w"), 6),
      h: toInt(node.getAttribute("gs-h"), 4),
    };
    this._items.push(node);
    this._applyStyle(node);
    var handle = node.querySelector(".widget-header");
    if (handle) {
      handle.addEventListener("mousedown", function (ev) { self._startDrag(ev, node); });
      handle.addEventListener("touchstart", function (ev) { self._startDrag(ev, node); }, { passive: true });
    }
    var resz = document.createElement("div");
    resz.className = "ui-resizable-se";
    node.appendChild(resz);
    resz.addEventListener("mousedown", function (ev) { self._startResize(ev, node, "se"); });
    resz.addEventListener("touchstart", function (ev) { self._startResize(ev, node, "se"); }, { passive: true });
    var reszE = document.createElement("div");
    reszE.className = "ui-resizable-e";
    node.appendChild(reszE);
    reszE.addEventListener("mousedown", function (ev) { self._startResize(ev, node, "e"); });
    reszE.addEventListener("touchstart", function (ev) { self._startResize(ev, node, "e"); }, { passive: true });
    var reszS = document.createElement("div");
    reszS.className = "ui-resizable-s";
    node.appendChild(reszS);
    reszS.addEventListener("mousedown", function (ev) { self._startResize(ev, node, "s"); });
    reszS.addEventListener("touchstart", function (ev) { self._startResize(ev, node, "s"); }, { passive: true });
  };

  GridStack.prototype._cellColWidth = function () {
    var w = this.el.clientWidth;
    return Math.max(1, w / this.opts.column);
  };

  GridStack.prototype._applyStyle = function (node) {
    var g = node._gs;
    var cw = this._cellColWidth();
    var ch = (this.opts.cellHeight + CELL_GAP);
    node.style.left = px(g.x * cw + CELL_GAP / 2);
    node.style.top = px(g.y * ch + CELL_GAP / 2);
    node.style.width = px(g.w * cw - CELL_GAP);
    node.style.height = px(g.h * ch - CELL_GAP);
    node.setAttribute("gs-x", g.x);
    node.setAttribute("gs-y", g.y);
    node.setAttribute("gs-w", g.w);
    node.setAttribute("gs-h", g.h);
  };

  GridStack.prototype._layout = function () {
    var self = this;
    var maxY = 0;
    this._items.forEach(function (n) {
      self._applyStyle(n);
      maxY = Math.max(maxY, n._gs.y + n._gs.h);
    });
    var ch = (this.opts.cellHeight + CELL_GAP);
    this.el.style.minHeight = px(Math.max(200, maxY * ch + CELL_GAP));
  };

  GridStack.prototype._emptySpot = function (w, h) {
    // crude pack: first free spot scanning rows
    var used = {};
    this._items.forEach(function (n) {
      var g = n._gs;
      for (var x = g.x; x < g.x + g.w; x++) {
        for (var y = g.y; y < g.y + g.h; y++) { used[x + ":" + y] = 1; }
      }
    });
    for (var y = 0; y < 60; y++) {
      for (var x = 0; x + w <= COL_COUNT; x++) {
        var ok = true;
        for (var i = 0; i < w && ok; i++) {
          for (var j = 0; j < h; j++) {
            if (used[(x + i) + ":" + (y + j)]) { ok = false; break; }
          }
        }
        if (ok) { return { x: x, y: y }; }
      }
    }
    return { x: 0, y: this._items.length ? 0 : 0 };
  };

  GridStack.prototype._snap = function (g) {
    g.x = Math.max(0, Math.min(COL_COUNT - g.w, g.x));
    g.y = Math.max(0, g.y);
    g.w = Math.max(1, Math.min(COL_COUNT - g.x, g.w));
    g.h = Math.max(1, g.h);
  };

  GridStack.prototype._startDrag = function (ev, node) {
    if (ev.button !== 0 && ev.type === "mousedown") { return; }
    ev.preventDefault();
    var self = this;
    var g = node._gs;
    var cw = this._cellColWidth();
    var ch = (this.opts.cellHeight + CELL_GAP);
    var startX = (ev.touches ? ev.touches[0].clientX : ev.clientX);
    var startY = (ev.touches ? ev.touches[0].clientY : ev.clientY);
    var origX = g.x;
    var origY = g.y;
    node.classList.add("ui-draggable-dragging");

    function move(e) {
      var cx = (e.touches ? e.touches[0].clientX : e.clientX);
      var cy = (e.touches ? e.touches[0].clientY : e.clientY);
      g.x = toInt(origX + Math.round((cx - startX) / cw), g.x);
      g.y = toInt(origY + Math.round((cy - startY) / ch), g.y);
      self._snap(g);
      self._applyStyle(node);
      self._layout();
    }
    function up() {
      node.classList.remove("ui-draggable-dragging");
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      window.removeEventListener("touchmove", move);
      window.removeEventListener("touchend", up);
      self._emitChange();
    }
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    window.addEventListener("touchmove", move);
    window.addEventListener("touchend", up);
  };

  GridStack.prototype._startResize = function (ev, node, axis) {
    if (ev.button !== 0 && ev.type === "mousedown") { return; }
    ev.preventDefault();
    ev.stopPropagation();
    var self = this;
    var g = node._gs;
    var cw = this._cellColWidth();
    var ch = (this.opts.cellHeight + CELL_GAP);
    var startX = (ev.touches ? ev.touches[0].clientX : ev.clientX);
    var startY = (ev.touches ? ev.touches[0].clientY : ev.clientY);
    var origW = g.w;
    var origH = g.h;
    axis = axis || "se";
    node.classList.add("ui-resizable-resizing");
    function move(e) {
      var cx = (e.touches ? e.touches[0].clientX : e.clientX);
      var cy = (e.touches ? e.touches[0].clientY : e.clientY);
      if (axis !== "s") { g.w = toInt(origW + Math.round((cx - startX) / cw), g.w); }
      if (axis !== "e") { g.h = toInt(origH + Math.round((cy - startY) / ch), g.h); }
      self._snap(g);
      self._applyStyle(node);
    }
    function up() {
      node.classList.remove("ui-resizable-resizing");
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      window.removeEventListener("touchmove", move);
      window.removeEventListener("touchend", up);
      self._emitChange();
    }
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    window.addEventListener("touchmove", move);
    window.addEventListener("touchend", up);
  };

  GridStack.prototype._emitChange = function () {
    var self = this;
    this._onChange.forEach(function (cb) { cb(self.save()); });
  };

  GridStack.prototype.on = function (evt, cb) {
    if (evt === "change" && typeof cb === "function") { this._onChange.push(cb); }
    return this;
  };

  GridStack.prototype.save = function () {
    return this._items.map(function (n) {
      return {
        id: n.getAttribute("gs-id"),
        x: n._gs.x, y: n._gs.y, w: n._gs.w, h: n._gs.h,
      };
    });
  };

  GridStack.prototype.update = function (el, opts) {
    if (!el || !el._gs) { return el; }
    var g = el._gs;
    if (opts) {
      if (opts.x !== undefined) { g.x = toInt(opts.x, g.x); }
      if (opts.y !== undefined) { g.y = toInt(opts.y, g.y); }
      if (opts.w !== undefined) { g.w = toInt(opts.w, g.w); }
      if (opts.h !== undefined) { g.h = toInt(opts.h, g.h); }
      this._snap(g);
      this._applyStyle(el);
      this._layout();
      this._emitChange();
    }
    return el;
  };

  GridStack.prototype.addWidget = function (el) {
    // el must already be appended to the grid DOM
    this.el.appendChild(el);
    var spot = this._emptySpot(toInt(el.getAttribute("gs-w"), 6), toInt(el.getAttribute("gs-h"), 4));
    el.setAttribute("gs-x", spot.x);
    el.setAttribute("gs-y", spot.y);
    this._initItem(el);
    this._applyStyle(el);
    this._layout();
    this._emitChange();
    return el;
  };

  GridStack.prototype.removeWidget = function (el) {
    var i = this._items.indexOf(el);
    if (i >= 0) { this._items.splice(i, 1); }
    if (el.parentNode) { el.parentNode.removeChild(el); }
    this._layout();
    this._emitChange();
  };

  GridStack.init = function (options, selector) {
    var el = typeof selector === "string" ? document.querySelector(selector) : selector;
    if (!el) { el = document.querySelector(".grid-stack"); }
    var gs = new GridStack(el, options || {});
    el._gridstack = gs;
    return gs;
  };

  window.GridStack = GridStack;
})();
