/* Map layers & behaviour.

   Level switching: LAD fill below z8.5, wards 8.5-11, LSOAs 11+, native
   heatmap of severity-weighted points 13+, clickable circles 14.5+.
   Ward/LSOA/point sources are refreshed per-viewport (debounced moveend,
   prefetched slightly before their layer becomes visible). NI stays a
   LAD-level layer at every zoom; Scotland is a static grey layer. */
App.initMap = function (meta) {
  const EMPTY = { type: "FeatureCollection", features: [] };
  const cache = { lad: EMPTY, ward: EMPTY, lsoa: EMPTY, points: EMPTY };
  const lastReq = {};
  const HOVER_OPACITY = 0.85;
  let hovered = null;
  let selected = null;

  const map = new maplibregl.Map({
    container: "map",
    style: App.BASEMAP_STYLE,
    bounds: App.UK_BOUNDS,
    fitBoundsOptions: { padding: 24 },
    minZoom: 4.4,
    maxZoom: 17.5,
    attributionControl: { compact: false, customAttribution: meta.attribution },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

  // Basemap resilience: if the vector style hasn't loaded shortly, fall back to raster.
  const styleTimer = setTimeout(() => {
    if (!map.isStyleLoaded()) map.setStyle(App.BASEMAP_FALLBACK);
  }, 6000);

  function colorExpr() {
    const cs = meta.color_scale;
    const interp = [
      "interpolate-hcl", ["linear"],
      ["log10", ["max", 1, ["to-number", ["get", "rate_per_1000"]]]],
    ];
    for (const [v, c] of cs.stops) interp.push(Math.log10(v), c);
    return ["case", ["!=", ["typeof", ["get", "rate_per_1000"]], "number"], cs.no_data, interp];
  }

  const hoverOpacity = (base, hover) => [
    "case", ["boolean", ["feature-state", "hover"], false], hover, base,
  ];
  const lineStyle = {
    "line-color": ["case", ["boolean", ["feature-state", "selected"], false], "#12212f", "#ffffff"],
    "line-width": [
      "case",
      ["boolean", ["feature-state", "selected"], false], 2.6,
      ["boolean", ["feature-state", "hover"], false], 1.7,
      0.55,
    ],
    "line-opacity": 0.95,
  };
  const country = (c) => ["==", ["get", "country"], c];

  function addOverlays() {
    // Two insertion anchors so the basemap stays legible at any fill opacity:
    // - choropleth fills/borders go BELOW the basemap's water, roads and
    //   labels (classic choropleth-under-linework), so streets and rivers
    //   render fully crisp on top of the colour;
    // - heatmap/circles sit above roads but below labels.
    const layers = map.getStyle().layers;
    const symbolAnchor = layers.find((l) => l.type === "symbol")?.id;
    const lineworkAnchor =
      layers.find(
        (l) =>
          (l.type === "fill" && (l["source-layer"] === "water" || /water/.test(l.id))) ||
          (l.type === "line" && /road|street|highway|transportation|bridge|tunnel|rail|boundary/.test(l.id))
      )?.id || symbolAnchor;
    const before = symbolAnchor;
    for (const id of ["lad", "ward", "lsoa"]) {
      if (!map.getSource(id)) map.addSource(id, { type: "geojson", data: cache[id], promoteId: "code" });
    }
    if (!map.getSource("points")) map.addSource("points", { type: "geojson", data: cache.points });

    // dim-all / spotlight-hover: non-hovered areas sit at App.areaOpacity
    // (legend slider) so the basemap reads through; the hovered region lights up
    const fillPaint = { "fill-color": colorExpr(), "fill-opacity": hoverOpacity(App.areaOpacity, HOVER_OPACITY) };
    const fills = [
      { id: "scot-fill", source: "lad", filter: country("S"),
        paint: { "fill-color": meta.color_scale.scotland, "fill-opacity": App.areaOpacity } },
      { id: "lad-fill", source: "lad", maxzoom: 8.5,
        filter: ["any", country("E"), country("W")], paint: fillPaint },
      { id: "ni-fill", source: "lad", filter: country("N"), paint: fillPaint },
      { id: "ward-fill", source: "ward", minzoom: 8.5, maxzoom: 11, paint: fillPaint },
      { id: "lsoa-fill", source: "lsoa", minzoom: 11, paint: fillPaint },
    ];
    for (const l of fills) {
      if (!map.getLayer(l.id)) map.addLayer({ type: "fill", ...l }, lineworkAnchor);
    }
    const lines = [
      { id: "lad-line", source: "lad", maxzoom: 8.5 },
      { id: "ni-line", source: "lad", filter: country("N") },
      { id: "ward-line", source: "ward", minzoom: 8.5, maxzoom: 11 },
      { id: "lsoa-line", source: "lsoa", minzoom: 11 },
    ];
    for (const l of lines) {
      if (!map.getLayer(l.id)) map.addLayer({ type: "line", paint: lineStyle, ...l }, lineworkAnchor);
    }

    if (!map.getLayer("crime-heat"))
      map.addLayer(
        {
          id: "crime-heat", type: "heatmap", source: "points", minzoom: meta.heatmap_min_zoom,
          paint: {
            "heatmap-weight": ["interpolate", ["linear"], ["get", "w"], 0.5, 0.15, 10, 1],
            "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 13, 0.55, 17, 1.3],
            "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 13, 15, 17, 36],
            // Inferno-style ramp, deliberately a DIFFERENT family from the
            // blue->red choropleth so epicentres contrast against both ends;
            // alpha graded in the ramp: transparent fringe, near-opaque amber
            // core that only genuinely dense clusters reach.
            "heatmap-color": [
              "interpolate", ["linear"], ["heatmap-density"],
              0, "rgba(0,0,0,0)",
              0.2, "rgba(70,20,110,0.25)",
              0.45, "rgba(150,35,120,0.50)",
              0.65, "rgba(210,70,70,0.70)",
              0.82, "rgba(240,120,35,0.88)",
              0.94, "rgba(252,180,40,0.96)",
              1, "rgba(253,225,120,1)",
            ],
            "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 13, 0.9, 16, 0.75],
          },
        },
        before
      );
    if (!map.getLayer("crime-circle"))
      map.addLayer(
        {
          id: "crime-circle", type: "circle", source: "points", minzoom: meta.circle_min_zoom,
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 14.5, 3.5, 17.5, 7],
            "circle-color": ["step", ["get", "w"], "#4393c3", 3, "#f4a582", 5, "#d6604d", 7, "#b2182b"],
            "circle-stroke-color": "#fff",
            "circle-stroke-width": 1,
            "circle-opacity": 0.9,
          },
        },
        before
      );
  }

  // ------------------------------------------------------------------ data
  async function loadLevel(level, bbox) {
    const key = `${level}|${bbox || ""}`;
    if (lastReq[level] === key) return;
    lastReq[level] = key;
    try {
      const fc = await App.api.choropleth(level, bbox);
      cache[level] = fc;
      map.getSource(level)?.setData(fc);
    } catch (e) {
      lastReq[level] = null; // retry on next move
    }
  }

  async function loadPoints(bbox) {
    const key = `points|${bbox}`;
    if (lastReq.points === key) return;
    lastReq.points = key;
    try {
      const fc = await App.api.points(bbox, meta.points_default_limit);
      cache.points = fc;
      map.getSource("points")?.setData(fc);
    } catch (e) {
      lastReq.points = null;
    }
  }

  function refresh() {
    const z = map.getZoom();
    const b = map.getBounds();
    let w = b.getWest(), s = b.getSouth(), e = b.getEast(), n = b.getNorth();
    const px = (e - w) * App.BBOX_PAD, py = (n - s) * App.BBOX_PAD;
    w -= px; e += px; s -= py; n += py;
    const area = (e - w) * (n - s);
    const bbox = [w, s, e, n].map((v) => v.toFixed(4)).join(",");

    for (const level of ["ward", "lsoa"]) {
      const spec = meta.levels[level];
      if (z >= spec.min_zoom - App.PREFETCH_ZOOM &&
          (!spec.max_bbox_deg2 || area <= spec.max_bbox_deg2)) {
        loadLevel(level, bbox);
      }
    }
    if (z >= meta.heatmap_min_zoom - App.PREFETCH_ZOOM && area <= meta.points_max_bbox_deg2) {
      loadPoints(bbox);
    }
  }

  // ------------------------------------------------------------ interaction
  const tooltip = new maplibregl.Popup({
    closeButton: false, closeOnClick: false, offset: 8, maxWidth: "260px",
  });

  function setHover(source, id, on) {
    if (id == null) return;
    map.setFeatureState({ source, id }, { hover: on });
  }

  function wireFillLayer(layerId, source) {
    map.on("mousemove", layerId, (e) => {
      const f = e.features[0];
      if (hovered && (hovered.id !== f.id || hovered.source !== source)) {
        setHover(hovered.source, hovered.id, false);
      }
      hovered = { source, id: f.id };
      setHover(source, f.id, true);
      map.getCanvas().style.cursor = "pointer";
      const p = f.properties;
      const rate = p.rate_per_1000 != null ? `${Number(p.rate_per_1000).toLocaleString("en-GB")} / 1k residents` : "no data";
      tooltip
        .setLngLat(e.lngLat)
        .setHTML(`<b>${p.name}</b><br>${rate}<br>${App.fmt(p.crimes_12m)} crimes in period`)
        .addTo(map);
    });
    map.on("mouseleave", layerId, () => {
      if (hovered) setHover(hovered.source, hovered.id, false);
      hovered = null;
      map.getCanvas().style.cursor = "";
      tooltip.remove();
    });
    map.on("click", layerId, (e) => {
      if (e.originalEvent._consumed) return;
      e.originalEvent._consumed = true;
      const p = e.features[0].properties;
      App.selectRegion(p.level, p.code);
    });
  }

  let marker = null;
  const mapApi = {
    map,
    refresh,
    setBaseOpacity(v) {
      App.areaOpacity = v;
      localStorage.setItem("areaOpacity", String(v));
      const expr = ["case", ["boolean", ["feature-state", "hover"], false], HOVER_OPACITY, v];
      for (const id of ["lad-fill", "ni-fill", "ward-fill", "lsoa-fill"]) {
        if (map.getLayer(id)) map.setPaintProperty(id, "fill-opacity", expr);
      }
      if (map.getLayer("scot-fill")) map.setPaintProperty("scot-fill", "fill-opacity", v);
    },
    setSelected(level, code) {
      this.clearSelected();
      selected = { source: level, id: code };
      map.setFeatureState({ source: level, id: code }, { selected: true });
    },
    clearSelected() {
      if (selected) map.removeFeatureState({ source: selected.source, id: selected.id }, "selected");
      selected = null;
      if (marker) { marker.remove(); marker = null; }
    },
    flyToRegion(bbox, level) {
      const panelPad = window.innerWidth > 640 ? 430 : 60;
      const cam = map.cameraForBounds(
        [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
        { padding: { top: 70, bottom: 70, left: 70, right: panelPad } }
      );
      const child = meta.child_level[level];
      if (child) cam.zoom = Math.max(cam.zoom, meta.levels[child].min_zoom + 0.15);
      cam.zoom = Math.min(cam.zoom, 16);
      map.flyTo({ ...cam, duration: 1100, essential: true });
    },
    fitUK() {
      map.fitBounds(App.UK_BOUNDS, { padding: 24, duration: 900 });
    },
    locate(lon, lat, label) {
      if (marker) marker.remove();
      marker = new maplibregl.Marker({ color: "#b2182b" })
        .setLngLat([lon, lat])
        .setPopup(new maplibregl.Popup({ offset: 20 }).setText(label))
        .addTo(map);
      map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 15.6), duration: 900 });
      marker.togglePopup();
    },
  };

  map.on("style.load", () => {
    clearTimeout(styleTimer);
    addOverlays();
  });

  map.on("load", () => {
    // Crime circles get first claim on clicks (registration order = dispatch order).
    map.on("click", "crime-circle", (e) => {
      if (e.originalEvent._consumed) return;
      e.originalEvent._consumed = true;
      const p = e.features[0].properties;
      new maplibregl.Popup({ offset: 8 })
        .setLngLat(e.lngLat)
        .setHTML(`<b>${p.cat}</b><br>${App.stripLocation(p.loc)}<br>` +
                 `${p.month || ""}<br><span style="color:#67788c">${p.outcome || "No outcome recorded"}</span>`)
        .addTo(map);
    });
    for (const [layer, source] of [
      ["lad-fill", "lad"], ["ni-fill", "lad"], ["ward-fill", "ward"], ["lsoa-fill", "lsoa"],
    ]) wireFillLayer(layer, source);

    map.on("click", "scot-fill", (e) => {
      if (e.originalEvent._consumed) return;
      e.originalEvent._consumed = true;
      new maplibregl.Popup({ offset: 8 })
        .setLngLat(e.lngLat)
        .setHTML("<b>Scotland</b><br>Police Scotland does not publish incident-level data " +
                 "to data.police.uk, so Scotland is not mapped here.")
        .addTo(map);
    });

    loadLevel("lad", null);
    map.on("moveend", App.debounce(refresh, 250));
    refresh();
  });

  return mapApi;
};
