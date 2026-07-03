/* Shared namespace + client-only constants. Everything data-driven comes from /api/meta. */
window.App = {
  meta: null,
  map: null,

  UK_BOUNDS: [[-8.65, 49.85], [1.78, 55.95]], // England, Wales & NI (Scotland greyed)
  BASEMAP_STYLE: "https://tiles.openfreemap.org/styles/positron",
  // Fallback if OpenFreeMap is down: raster Carto tiles, no key needed.
  BASEMAP_FALLBACK: {
    version: 8,
    sources: {
      carto: {
        type: "raster",
        tiles: ["https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"],
        tileSize: 256,
        attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
      },
    },
    layers: [{ id: "carto", type: "raster", source: "carto" }],
  },

  PREFETCH_ZOOM: 0.7,   // start fetching a level's data this far before it shows
  BBOX_PAD: 0.15,       // over-fetch viewport by 15% so edge polygons are ready

  // base fill opacity for non-hovered areas (user-tunable via legend slider).
  // Fills render UNDER the basemap linework, so 55% stays street-legible.
  areaOpacity: (() => {
    const v = parseFloat(localStorage.getItem("areaOpacity"));
    return Number.isFinite(v) ? v : 0.55;
  })(),

  debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  },

  stripLocation(loc) {
    return (loc || "").replace(/^On or near /i, "");
  },

  fmt(n) {
    return n == null ? "–" : n.toLocaleString("en-GB");
  },
};
