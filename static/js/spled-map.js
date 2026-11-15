(function () {
  "use strict";

  var DEFAULT_CENTER = [7.4, 9.07];
  var MAX_POINTS = 200;
  var COLORS = {
    planned: "#5b6b7f",
    in_progress: "#1f5fa8",
    delayed: "#b24e08",
    stalled: "#a12b2b",
    complete: "#1f6b3f"
  };
  var TILE_DEFAULTS = {
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution:
      '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
    maxZoom: 19,
    tileSize: 256
  };

  // Tile provider settings come from the page (settings.MAP_TILE_*), with OSM as the fallback.
  function buildStyle() {
    var cfg = {};
    try {
      var node = document.getElementById("map-config");
      if (node) { cfg = JSON.parse(node.textContent) || {}; }
    } catch (err) { cfg = {}; }
    return {
      version: 8,
      sources: {
        base: {
          type: "raster",
          tiles: [cfg.tile_url || TILE_DEFAULTS.url],
          tileSize: cfg.tile_size || TILE_DEFAULTS.tileSize,
          maxzoom: cfg.max_zoom || TILE_DEFAULTS.maxZoom,
          attribution: cfg.attribution || TILE_DEFAULTS.attribution
        }
      },
      layers: [{ id: "base", type: "raster", source: "base" }]
    };
  }

  function fail(el, message) {
    el.classList.add("mapbox-failed");
    el.textContent = message;
  }

  function validPoint(lat, lon) {
    return (
      isFinite(lat) && isFinite(lon) &&
      lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
    );
  }

  function createMap(el, options) {
    if (typeof maplibregl === "undefined") {
      fail(el, "The map couldn’t load. You can still use the details on this page.");
      return null;
    }
    try {
      var map = new maplibregl.Map({
        container: el,
        style: buildStyle(),
        center: options.center || DEFAULT_CENTER,
        zoom: options.zoom || 11,
        cooperativeGestures: !!options.cooperativeGestures
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

      return map;
    } catch (err) {
      fail(el, "The map couldn’t start in this browser. You can still use the details on this page.");
      return null;
    }
  }

  function insidePolygon(point, ring) {
    var x = point[0], y = point[1], inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      var crosses = (yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
      if (crosses) { inside = !inside; }
    }
    return inside;
  }

  function readBoundary(input) {
    if (!input || !input.value) { return []; }
    try {
      var g = JSON.parse(input.value);
      var ring = g.coordinates && g.coordinates[0];
      if (!ring || ring.length < 4) { return []; }
      return ring.slice(0, ring.length - 1).map(function (c) { return [c[0], c[1]]; });
    } catch (err) {
      return [];
    }
  }

  // ---- Pin picker and boundary drawing (site form) ----
  function initPinPicker(el) {
    var latInput = document.getElementById(el.dataset.latInput);
    var lonInput = document.getElementById(el.dataset.lonInput);
    if (!latInput || !lonInput) { return; }
    var boundaryInput = el.dataset.boundaryInput ? document.getElementById(el.dataset.boundaryInput) : null;
    var tools = el.dataset.boundaryTools ? document.getElementById(el.dataset.boundaryTools) : null;
    var statusEl = el.dataset.boundaryStatus ? document.getElementById(el.dataset.boundaryStatus) : null;
    var canDraw = !!(boundaryInput && tools);

    function read() {
      var lat = parseFloat(latInput.value);
      var lon = parseFloat(lonInput.value);
      return validPoint(lat, lon) ? [lon, lat] : null;
    }
    function write(lngLat) {
      latInput.value = lngLat.lat.toFixed(6);
      lonInput.value = lngLat.lng.toFixed(6);
      describe();
    }

    var start = read();
    var points = canDraw ? readBoundary(boundaryInput) : [];
    var map = createMap(el, {
      center: start || points[0] || DEFAULT_CENTER,
      zoom: start ? 15 : 11,
      cooperativeGestures: true
    });
    if (!map) { return; }

    var drawing = false;
    var vertexMarkers = [];
    var btnPin = tools && tools.querySelector('[data-mode="pin"]');
    var btnDraw = tools && tools.querySelector('[data-mode="boundary"]');
    var btnUndo = tools && tools.querySelector('[data-action="undo"]');
    var btnClear = tools && tools.querySelector('[data-action="clear"]');

    // ----- pin
    var marker = null;
    function place(lngLat, move) {
      if (!marker) {
        marker = new maplibregl.Marker({ draggable: true, color: "#0e2a24" })
          .setLngLat(lngLat)
          .addTo(map);
        marker.on("dragend", function () { write(marker.getLngLat().wrap()); });
      } else {
        marker.setLngLat(lngLat);
      }
      if (move) {
        map.easeTo({ center: lngLat, zoom: Math.max(map.getZoom(), 14) });
      }
    }
    if (start) { place(start, false); }

    // ----- boundary
    function shape() {
      if (points.length >= 3) {
        return {
          type: "Feature", properties: {},
          geometry: { type: "Polygon", coordinates: [points.concat([points[0]])] }
        };
      }
      if (points.length === 2) {
        return { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: points } };
      }
      return { type: "FeatureCollection", features: [] };
    }
    function syncInput() {
      if (canDraw) {
        boundaryInput.value = points.length >= 3 ? JSON.stringify(shape().geometry) : "";
      }
    }
    function say(text) { if (statusEl) { statusEl.textContent = text; } }
    function describe() {
      if (!canDraw) { return; }
      var text;
      if (points.length === 0) {
        text = drawing ? "Tap the map to add the first corner." : "No boundary drawn. This is optional.";
      } else if (points.length < 3) {
        text = points.length + " point" + (points.length === 1 ? "" : "s") + " added. Add at least 3 to make a boundary.";
      } else {
        text = points.length + " points. Drag a corner to adjust it.";
        var pin = read();
        if (pin && !insidePolygon(pin, points)) {
          text += " The pin is outside the boundary. Move it inside before saving.";
        }
      }
      say(text);
    }
    function drawShape() {
      var source = map.getSource("boundary-draw");
      if (source) { source.setData(shape()); }
    }
    function updateButtons() {
      if (!canDraw) { return; }
      if (btnUndo) { btnUndo.disabled = points.length === 0; }
      if (btnClear) { btnClear.disabled = points.length === 0; }
    }
    function rebuildMarkers() {
      vertexMarkers.forEach(function (m) { m.remove(); });
      vertexMarkers = points.map(function (p, i) {
        var node = document.createElement("div");
        node.className = "vertex";
        node.addEventListener("click", function (ev) { ev.stopPropagation(); });
        var m = new maplibregl.Marker({ element: node, draggable: true }).setLngLat(p).addTo(map);
        m.on("drag", function () {
          var ll = m.getLngLat().wrap();
          points[i] = [ll.lng, ll.lat];
          drawShape();
        });
        m.on("dragend", function () { syncInput(); describe(); });
        node.addEventListener("contextmenu", function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          var idx = vertexMarkers.indexOf(m);
          if (idx > -1) { points.splice(idx, 1); refresh(true); }
        });
        return m;
      });
    }
    function refresh(rebuild) {
      if (rebuild) { rebuildMarkers(); }
      drawShape();
      syncInput();
      describe();
      updateButtons();
    }
    function setMode(on) {
      drawing = on && canDraw;
      if (btnPin) { btnPin.setAttribute("aria-pressed", String(!drawing)); }
      if (btnDraw) { btnDraw.setAttribute("aria-pressed", String(drawing)); }
      map.getCanvas().style.cursor = drawing ? "crosshair" : "";
      describe();
    }

    map.on("load", function () {
      map.addSource("boundary-draw", { type: "geojson", data: shape() });
      map.addLayer({
        id: "boundary-draw-fill", type: "fill", source: "boundary-draw",
        filter: ["==", "$type", "Polygon"],
        paint: { "fill-color": "#3ddbb0", "fill-opacity": 0.2 }
      });
      map.addLayer({
        id: "boundary-draw-line", type: "line", source: "boundary-draw",
        paint: { "line-color": "#0e2a24", "line-width": 2 }
      });
      if (points.length >= 3) {
        var bounds = new maplibregl.LngLatBounds();
        points.forEach(function (p) { bounds.extend(p); });
        if (start) { bounds.extend(start); }
        map.fitBounds(bounds, { padding: 40, maxZoom: 17, duration: 0 });
      }
    });

    map.on("click", function (e) {
      var p = e.lngLat.wrap();
      if (drawing) {
        if (points.length >= MAX_POINTS) {
          say("A boundary can have at most " + MAX_POINTS + " points.");
          return;
        }
        points.push([p.lng, p.lat]);
        refresh(true);
      } else {
        write(p);
        place([p.lng, p.lat], false);
      }
    });

    function fromInputs() {
      var p = read();
      if (p) { place(p, true); }
      describe();
    }
    latInput.addEventListener("change", fromInputs);
    lonInput.addEventListener("change", fromInputs);

    if (canDraw) {
      if (btnPin) { btnPin.addEventListener("click", function () { setMode(false); }); }
      if (btnDraw) { btnDraw.addEventListener("click", function () { setMode(true); }); }
      if (btnUndo) {
        btnUndo.addEventListener("click", function () { points.pop(); refresh(true); });
      }
      if (btnClear) {
        btnClear.addEventListener("click", function () { points = []; refresh(true); });
      }
      var form = el.closest("form");
      if (form) {
        form.addEventListener("submit", function (ev) {
          if (points.length > 0 && points.length < 3) {
            ev.preventDefault();
            say("A boundary needs at least 3 points. Add more, or clear it.");
            el.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        });
      }
      rebuildMarkers();
      setMode(false);
      updateButtons();
    }
  }

  // ---- Single site: pin and, if present, boundary ----
  function initSiteMap(el) {
    var lat = parseFloat(el.dataset.lat);
    var lon = parseFloat(el.dataset.lon);
    if (!validPoint(lat, lon)) {
      fail(el, "This site has no valid location to show.");
      return;
    }
    var map = createMap(el, { center: [lon, lat], zoom: 15, cooperativeGestures: true });
    if (!map) { return; }
    new maplibregl.Marker({ color: COLORS[el.dataset.status] || "#0e2a24" })
      .setLngLat([lon, lat])
      .addTo(map);

    if (!el.dataset.boundary) { return; }
    var geometry;
    try { geometry = JSON.parse(el.dataset.boundary); } catch (err) { return; }
    map.on("load", function () {
      map.addSource("boundary", {
        type: "geojson",
        data: { type: "Feature", geometry: geometry, properties: {} }
      });
      map.addLayer({
        id: "boundary-fill", type: "fill", source: "boundary",
        paint: { "fill-color": "#3ddbb0", "fill-opacity": 0.2 }
      });
      map.addLayer({
        id: "boundary-line", type: "line", source: "boundary",
        paint: { "line-color": "#0e2a24", "line-width": 2 }
      });
      var bounds = new maplibregl.LngLatBounds();
      ((geometry.coordinates && geometry.coordinates[0]) || []).forEach(function (c) {
        bounds.extend(c);
      });
      bounds.extend([lon, lat]);
      map.fitBounds(bounds, { padding: 40, maxZoom: 17, duration: 0 });
    });
  }

  // ---- Clustered projects layer (shared by the public and staff maps) ----
  function statusColour() {
    var colour = ["match", ["get", "status"]];
    Object.keys(COLORS).forEach(function (key) { colour.push(key, COLORS[key]); });
    colour.push("#5b6b7f");
    return colour;
  }

  function textEl(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    node.textContent = text;
    return node;
  }

  function linkEl(url, text) {
    var link = document.createElement("a");
    link.href = url;
    link.textContent = text;
    return link;
  }

  function fitTo(map, features) {
    if (features.length === 1) {
      map.jumpTo({ center: features[0].geometry.coordinates, zoom: 13 });
    } else if (features.length > 1) {
      var bounds = new maplibregl.LngLatBounds();
      features.forEach(function (f) { bounds.extend(f.geometry.coordinates); });
      map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 0 });
    }
  }

  function showPopup(map, e, build) {
    var seen = {};
    var list = [];
    (e.features || []).forEach(function (f) {
      if (!seen[f.properties.id]) { seen[f.properties.id] = true; list.push(f); }
    });
    if (!list.length) { return; }
    var box;
    if (list.length === 1) {
      box = build(list[0].properties);
    } else {
      box = document.createElement("div");
      box.appendChild(textEl("strong", "", list.length + " sites here"));
      list.forEach(function (f) {
        var row = document.createElement("div");
        row.appendChild(linkEl(f.properties.url, f.properties.name));
        box.appendChild(row);
      });
    }
    new maplibregl.Popup({ maxWidth: "260px" })
      .setLngLat(list[0].geometry.coordinates.slice())
      .setDOMContent(box)
      .addTo(map);
  }

  function clusteredLayer(map, id, data, build) {
    var clusterLayer = id + "-clusters";
    var pointLayer = id + "-points";
    var labels = {};

    map.addSource(id, {
      type: "geojson", data: data,
      cluster: true, clusterRadius: 50, clusterMaxZoom: 14
    });
    map.addLayer({
      id: clusterLayer, type: "circle", source: id,
      filter: ["has", "point_count"],
      paint: {
        "circle-color": "#0e2a24",
        "circle-radius": ["step", ["get", "point_count"], 16, 10, 20, 50, 26, 200, 32],
        "circle-stroke-width": 3,
        "circle-stroke-color": "#3ddbb0"
      }
    });
    map.addLayer({
      id: pointLayer, type: "circle", source: id,
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-radius": 9,
        "circle-color": statusColour(),
        "circle-stroke-width": 2,
        "circle-stroke-color": "#ffffff"
      }
    });

    // Counts are page elements, not map text: the map style has no font server.
    function clearLabels() {
      Object.keys(labels).forEach(function (key) { labels[key].remove(); });
      labels = {};
    }
    function syncLabels() {
      if (!map.getSource(id) || !map.getLayer(clusterLayer)) { return; }
      // Only clusters that are actually drawn, one label per cluster id.
      var seen = {};
      map.queryRenderedFeatures({ layers: [clusterLayer] }).forEach(function (f) {
        var key = String(f.properties.cluster_id);
        if (seen[key]) { return; }
        seen[key] = true;
        var text = String(f.properties.point_count_abbreviated);
        if (labels[key]) {
          labels[key].getElement().textContent = text;
          labels[key].setLngLat(f.geometry.coordinates);
        } else {
          var node = textEl("div", "cluster-count", text);
          labels[key] = new maplibregl.Marker({ element: node })
            .setLngLat(f.geometry.coordinates)
            .addTo(map);
        }
      });
      Object.keys(labels).forEach(function (key) {
        if (!seen[key]) { labels[key].remove(); delete labels[key]; }
      });
    }
    ["sourcedata", "moveend", "zoomend", "idle"].forEach(function (name) {
      map.on(name, syncLabels);
    });

    map.on("click", clusterLayer, function (e) {
      var f = e.features && e.features[0];
      if (!f) { return; }
      map.getSource(id).getClusterExpansionZoom(f.properties.cluster_id)
        .then(function (zoom) {
          map.easeTo({ center: f.geometry.coordinates, zoom: zoom });
        })
        .catch(function () {});
    });
    map.on("click", pointLayer, function (e) { showPopup(map, e, build); });

    [clusterLayer, pointLayer].forEach(function (layerId) {
      map.on("mouseenter", layerId, function () { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", layerId, function () { map.getCanvas().style.cursor = ""; });
    });

    return {
      setData: function (next) {
        clearLabels();
        map.getSource(id).setData(next);
      }
    };
  }

  function publicPopup(p) {
    var box = document.createElement("div");
    box.appendChild(textEl("strong", "", p.name));
    box.appendChild(textEl("div", "", p.status_label + " · " + p.progress + "%"));
    box.appendChild(textEl("div", "muted", p.kind + " · " + p.organisation));
    box.appendChild(linkEl(p.url, "Open project"));
    return box;
  }

  function staffPopup(p) {
    var published = p.is_public === true || p.is_public === "true";
    var box = document.createElement("div");
    box.appendChild(textEl("strong", "", p.name));
    box.appendChild(textEl("div", "", p.status_label + " · " + p.progress + "%"));
    box.appendChild(textEl("div", "muted", p.kind + (published ? " · published" : " · not published")));
    box.appendChild(linkEl(p.url, "Open site"));
    return box;
  }

  // ---- Public map: all published projects ----
  function initPublicMap(el) {
    var note = el.parentNode.querySelector(".mapstatus");
    function say(text) { if (note) { note.textContent = text; } }

    var map = createMap(el, { center: DEFAULT_CENTER, zoom: 9 });
    if (!map) { return; }

    function add(data) {
      var features = data.features || [];
      clusteredLayer(map, "projects", data, publicPopup);
      fitTo(map, features);
      if (!features.length) { say("No projects have been published yet."); }
    }

    fetch(el.dataset.url, { headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) { throw new Error("bad response"); }
        return r.json();
      })
      .then(function (data) {
        if (map.isStyleLoaded()) { add(data); } else { map.once("load", function () { add(data); }); }
      })
      .catch(function () {
        say("The projects couldn’t be loaded onto the map. The list below still works.");
      });
  }

  // ---- Staff map: the organisation's own sites, with status filters ----
  function initStaffMap(el) {
    var note = el.parentNode.querySelector(".mapstatus");
    function say(text) { if (note) { note.textContent = text; } }

    var chips = document.querySelectorAll("[data-map-filter]");
    var rows = document.querySelectorAll("[data-site-row]");
    var shown = {};
    chips.forEach(function (chip) { shown[chip.dataset.mapFilter] = true; });

    var map = createMap(el, { center: DEFAULT_CENTER, zoom: 9 });
    var layer = null;
    var all = [];

    function apply() {
      var count = 0;
      rows.forEach(function (row) {
        var on = !!shown[row.dataset.status];
        row.hidden = !on;
        if (on) { count += 1; }
      });
      if (layer) {
        layer.setData({
          type: "FeatureCollection",
          features: all.filter(function (f) { return shown[f.properties.status]; })
        });
      }
      say(count + " of " + rows.length + " site" + (rows.length === 1 ? "" : "s") + " shown");
    }

    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        var key = chip.dataset.mapFilter;
        shown[key] = !shown[key];
        chip.setAttribute("aria-pressed", String(shown[key]));
        apply();
      });
    });

    if (!map) { apply(); return; }

    function add(data) {
      all = data.features || [];
      layer = clusteredLayer(map, "sites", { type: "FeatureCollection", features: all }, staffPopup);
      fitTo(map, all);
      apply();
    }

    apply();
    fetch(el.dataset.url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) { throw new Error("bad response"); }
        return r.json();
      })
      .then(function (data) {
        if (map.isStyleLoaded()) { add(data); } else { map.once("load", function () { add(data); }); }
      })
      .catch(function () {
        say("The sites couldn’t be loaded onto the map. The list below still works.");
      });
  }

  // ---- Overview card: a small map of the organisation's sites ----
  function initOverviewMap(el) {
    var note = el.parentNode.querySelector(".mapstatus");
    function say(text) { if (note) { note.textContent = text; } }

    var map = createMap(el, { center: DEFAULT_CENTER, zoom: 9, cooperativeGestures: true });
    if (!map) { return; }

    function add(data) {
      var features = data.features || [];
      clusteredLayer(map, "sites", data, staffPopup);
      fitTo(map, features);
      say(features.length + " site" + (features.length === 1 ? "" : "s") + " on the map");
    }

    fetch(el.dataset.url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) { throw new Error("bad response"); }
        return r.json();
      })
      .then(function (data) {
        if (map.isStyleLoaded()) { add(data); } else { map.once("load", function () { add(data); }); }
      })
      .catch(function () {
        say("The sites couldn’t be loaded onto the map. The list below still works.");
      });
  }

  function init() {
    document.querySelectorAll("[data-pin-picker]").forEach(initPinPicker);
    document.querySelectorAll("[data-site-map]").forEach(initSiteMap);
    document.querySelectorAll("[data-public-map]").forEach(initPublicMap);
    document.querySelectorAll("[data-staff-map]").forEach(initStaffMap);
    document.querySelectorAll("[data-overview-map]").forEach(initOverviewMap);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();