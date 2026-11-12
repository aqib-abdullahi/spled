// (function () {
//   const MAP_STYLE = 'https://demotiles.maplibre.org/style.json';
//   const STATUS_COLORS = {
//     planned: '#b9b9c4',
//     in_progress: '#4a90e2',
//     delayed: '#f4b554',
//     stalled: '#d75d5d',
//     complete: '#4aa76d',
//   };

//   function safeJsonParse(value) {
//     if (!value) return null;
//     try {
//       return JSON.parse(value);
//     } catch (error) {
//       return null;
//     }
//   }

//   function statusColor(status) {
//     return STATUS_COLORS[status] || '#4a90e2';
//   }

//   function makePopup(feature) {
//     const props = feature.properties || {};
//     const title = props.name || 'Project';
//     const org = props.organisation || '';
//     const statusLabel = props.status_label || '';
//     const url = props.url || '';
//     const detail = org ? '<div>' + org + '</div>' : '';
//     const link = url ? '<div style="margin-top:6px"><a href="' + url + '" target="_self">Open project</a></div>' : '';
//     return '<div style="font-family:inherit;max-width:220px"><strong>' + title + '</strong>' +
//       '<div style="margin-top:4px; color:#4b5563;">' + statusLabel + '</div>' +
//       detail +
//       link +
//       '</div>';
//   }

//   function fitMapToBounds(map, features) {
//     if (!features || features.length === 0) return;
//     const bounds = new maplibregl.LngLatBounds();
//     for (const feature of features) {
//       if (!feature || !feature.geometry) continue;
//       if (feature.geometry.type === 'Point') {
//         bounds.extend(feature.geometry.coordinates);
//       } else if (feature.geometry.type === 'Polygon' || feature.geometry.type === 'MultiPolygon') {
//         const coords = feature.geometry.coordinates;
//         const flatten = (value) => Array.isArray(value) ? value.flat(Infinity) : [];
//         const numbers = flatten(coords);
//         for (let idx = 0; idx + 1 < numbers.length; idx += 2) {
//           bounds.extend([numbers[idx], numbers[idx + 1]]);
//         }
//       }
//     }
//     if (bounds._ne && !Number.isNaN(bounds._ne.lng)) {
//       map.fitBounds(bounds, { padding: 30, maxZoom: 13, duration: 0 });
//     }
//   }

//   function buildPublicLayers(map, sourceId) {
//     map.addSource(sourceId, {
//       type: 'geojson',
//       data: sourceId === 'public-map-source' ? { type: 'FeatureCollection', features: [] } : { type: 'FeatureCollection', features: [] },
//     });

//     map.addLayer({
//       id: sourceId + '-layer',
//       type: 'circle',
//       source: sourceId,
//       paint: {
//         'circle-radius': 8,
//         'circle-color': [
//           'match',
//           ['get', 'status'],
//           'planned', STATUS_COLORS.planned,
//           'in_progress', STATUS_COLORS.in_progress,
//           'delayed', STATUS_COLORS.delayed,
//           'stalled', STATUS_COLORS.stalled,
//           'complete', STATUS_COLORS.complete,
//           '#4a90e2'
//         ],
//         'circle-stroke-color': '#ffffff',
//         'circle-stroke-width': 2,
//       },
//     });

//     map.on('click', sourceId + '-layer', (event) => {
//       const feature = event.features && event.features[0];
//       if (!feature) return;
//       const popup = new maplibregl.Popup({ closeButton: true, closeOnClick: false })
//         .setLngLat(feature.geometry.coordinates)
//         .setHTML(makePopup(feature))
//         .addTo(map);
//       popup._content.innerHTML = popup._content.innerHTML;
//     });

//     map.on('mouseenter', sourceId + '-layer', () => {
//       map.getCanvas().style.cursor = 'pointer';
//     });
//     map.on('mouseleave', sourceId + '-layer', () => {
//       map.getCanvas().style.cursor = '';
//     });
//   }

//   function initPublicMap(element) {
//     const url = element.dataset.url;
//     const map = new maplibregl.Map({
//       container: element,
//       style: MAP_STYLE,
//       center: [-2.5, 54.0],
//       zoom: 5.2,
//       attributionControl: true,
//     });

//     map.addControl(new maplibregl.NavigationControl(), 'top-right');
//     map.on('load', () => {
//       const sourceId = 'public-map-source';
//       const layerId = sourceId + '-layer';
//       map.addSource(sourceId, { type: 'geojson', data: url });
//       map.addLayer({
//         id: layerId,
//         type: 'circle',
//         source: sourceId,
//         paint: {
//           'circle-radius': 8,
//           'circle-color': [
//             'match',
//             ['get', 'status'],
//             'planned', STATUS_COLORS.planned,
//             'in_progress', STATUS_COLORS.in_progress,
//             'delayed', STATUS_COLORS.delayed,
//             'stalled', STATUS_COLORS.stalled,
//             'complete', STATUS_COLORS.complete,
//             '#4a90e2'
//           ],
//           'circle-stroke-color': '#ffffff',
//           'circle-stroke-width': 2,
//         },
//       });

//       map.on('click', layerId, (event) => {
//         const feature = event.features && event.features[0];
//         if (!feature) return;
//         new maplibregl.Popup({ closeButton: true, closeOnClick: false })
//           .setLngLat(feature.geometry.coordinates)
//           .setHTML(makePopup(feature))
//           .addTo(map);
//       });

//       map.on('mouseenter', layerId, () => {
//         map.getCanvas().style.cursor = 'pointer';
//       });
//       map.on('mouseleave', layerId, () => {
//         map.getCanvas().style.cursor = '';
//       });

//       fetch(url)
//         .then((response) => response.json())
//         .then((geojson) => {
//           map.getSource(sourceId).setData(geojson);
//           fitMapToBounds(map, geojson.features || []);
//           const status = document.querySelector('.mapstatus');
//           if (status) {
//             status.textContent = (geojson.features || []).length + ' project' + ((geojson.features || []).length === 1 ? '' : 's') + ' shown';
//           }
//         })
//         .catch(() => {
//           if (element) {
//             element.classList.add('mapbox-failed');
//             element.textContent = 'Map data is unavailable right now.';
//           }
//         });
//     });
//   }

//   function initSiteMap(element) {
//     const lat = parseFloat(element.dataset.lat || '0');
//     const lon = parseFloat(element.dataset.lon || '0');
//     const boundary = safeJsonParse(element.dataset.boundary || '');
//     const map = new maplibregl.Map({
//       container: element,
//       style: MAP_STYLE,
//       center: [lon, lat],
//       zoom: 11,
//       attributionControl: true,
//     });

//     map.addControl(new maplibregl.NavigationControl(), 'top-right');
//     map.on('load', () => {
//       const siteSourceId = 'site-map-source';
//       map.addSource(siteSourceId, {
//         type: 'geojson',
//         data: {
//           type: 'FeatureCollection',
//           features: [
//             {
//               type: 'Feature',
//               properties: { status: element.dataset.status || 'in_progress' },
//               geometry: {
//                 type: 'Point',
//                 coordinates: [lon, lat],
//               },
//             },
//           ],
//         },
//       });
//       map.addLayer({
//         id: 'site-map-point',
//         type: 'circle',
//         source: siteSourceId,
//         paint: {
//           'circle-radius': 10,
//           'circle-color': statusColor(element.dataset.status || 'in_progress'),
//           'circle-stroke-color': '#ffffff',
//           'circle-stroke-width': 2,
//         },
//       });

//       if (boundary) {
//         map.addSource('site-boundary', { type: 'geojson', data: boundary });
//         map.addLayer({
//           id: 'site-boundary-fill',
//           type: 'fill',
//           source: 'site-boundary',
//           paint: {
//             'fill-color': '#5fa8ff',
//             'fill-opacity': 0.18,
//           },
//         });
//         map.addLayer({
//           id: 'site-boundary-line',
//           type: 'line',
//           source: 'site-boundary',
//           paint: {
//             'line-color': '#5fa8ff',
//             'line-width': 2,
//           },
//         });
//         fitMapToBounds(map, boundary.features || [boundary]);
//       } else {
//         map.setZoom(11);
//       }
//     });
//   }

//   function initPinPicker(element) {
//     const latInput = document.getElementById(element.dataset.latInput || 'id_latitude');
//     const lonInput = document.getElementById(element.dataset.lonInput || 'id_longitude');
//     if (!latInput || !lonInput) return;

//     const defaultLat = parseFloat(latInput.value || '51.5');
//     const defaultLon = parseFloat(lonInput.value || '-0.13');
//     const map = new maplibregl.Map({
//       container: element,
//       style: MAP_STYLE,
//       center: [defaultLon, defaultLat],
//       zoom: 10,
//       attributionControl: true,
//     });

//     map.addControl(new maplibregl.NavigationControl(), 'top-right');
//     const marker = new maplibregl.Marker({ draggable: true }).setLngLat([defaultLon, defaultLat]).addTo(map);

//     const updateInputs = () => {
//       const coords = marker.getLngLat();
//       latInput.value = Number(coords.lat).toFixed(6);
//       lonInput.value = Number(coords.lng).toFixed(6);
//     };

//     map.on('load', () => {
//       marker.on('dragend', updateInputs);
//       map.on('click', (event) => {
//         marker.setLngLat(event.lngLat).addTo(map);
//         updateInputs();
//       });
//     });
//   }

//   function bootMaps() {
//     if (!window.maplibregl) return;
//     const elements = document.querySelectorAll('[data-public-map], [data-site-map], [data-pin-picker]');
//     elements.forEach((element) => {
//       if (element.dataset.mapReady === 'true') return;
//       element.dataset.mapReady = 'true';
//       if (element.hasAttribute('data-public-map')) {
//         initPublicMap(element);
//       } else if (element.hasAttribute('data-site-map')) {
//         initSiteMap(element);
//       } else if (element.hasAttribute('data-pin-picker')) {
//         initPinPicker(element);
//       }
//     });
//   }

//   if (document.readyState === 'loading') {
//     document.addEventListener('DOMContentLoaded', bootMaps);
//   } else {
//     bootMaps();
//   }
// })();
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
  var STYLE = {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        maxzoom: 19,
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
      }
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }]
  };

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
        style: STYLE,
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

  // ---- Public map: all published projects ----
  function initPublicMap(el) {
    var note = el.parentNode.querySelector(".mapstatus");
    function say(text) { if (note) { note.textContent = text; } }

    var map = createMap(el, { center: DEFAULT_CENTER, zoom: 9 });
    if (!map) { return; }

    var colour = ["match", ["get", "status"]];
    Object.keys(COLORS).forEach(function (key) { colour.push(key, COLORS[key]); });
    colour.push("#5b6b7f");

    function add(data) {
      map.addSource("projects", { type: "geojson", data: data });
      map.addLayer({
        id: "projects", type: "circle", source: "projects",
        paint: {
          "circle-radius": 9,
          "circle-color": colour,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#ffffff"
        }
      });

      var features = data.features || [];
      if (features.length === 1) {
        map.jumpTo({ center: features[0].geometry.coordinates, zoom: 13 });
      } else if (features.length > 1) {
        var bounds = new maplibregl.LngLatBounds();
        features.forEach(function (f) { bounds.extend(f.geometry.coordinates); });
        map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 0 });
      } else {
        say("No projects have been published yet.");
      }

      map.on("mouseenter", "projects", function () { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "projects", function () { map.getCanvas().style.cursor = ""; });
      map.on("click", "projects", function (e) {
        var f = e.features && e.features[0];
        if (!f) { return; }
        var p = f.properties;
        var box = document.createElement("div");
        var title = document.createElement("strong");
        title.textContent = p.name;
        var line1 = document.createElement("div");
        line1.textContent = p.status_label + " · " + p.progress + "%";
        var line2 = document.createElement("div");
        line2.className = "muted";
        line2.textContent = p.kind + " · " + p.organisation;
        var link = document.createElement("a");
        link.href = p.url;
        link.textContent = "Open project";
        box.appendChild(title);
        box.appendChild(line1);
        box.appendChild(line2);
        box.appendChild(link);
        new maplibregl.Popup({ maxWidth: "260px" })
          .setLngLat(f.geometry.coordinates.slice())
          .setDOMContent(box)
          .addTo(map);
      });
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

  function init() {
    document.querySelectorAll("[data-pin-picker]").forEach(initPinPicker);
    document.querySelectorAll("[data-site-map]").forEach(initSiteMap);
    document.querySelectorAll("[data-public-map]").forEach(initPublicMap);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();