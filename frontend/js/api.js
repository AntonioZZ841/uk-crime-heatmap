/* Thin fetch wrapper with a shared "loading" indicator and quiet error policy:
   map-data refreshes fail silently (previous data stays); explicit user actions
   (region click) surface their error. */
App.api = (() => {
  const status = document.getElementById("status");
  let inflight = 0;
  let buildId = ""; // set from meta; version-tags URLs so a data refresh busts the HTTP cache

  async function get(url, { quiet = false, fetchOpts = {} } = {}) {
    inflight += 1;
    status.textContent = "Loading data…";
    status.hidden = false;
    try {
      if (buildId) url += (url.includes("?") ? "&" : "?") + "v=" + buildId;
      const r = await fetch(url, fetchOpts);
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        const err = new Error(body.error || `${r.status} for ${url}`);
        err.quiet = quiet;
        throw err;
      }
      return await r.json();
    } finally {
      inflight -= 1;
      if (inflight === 0) status.hidden = true;
    }
  }

  return {
    meta: async () => {
      const m = await get("/api/meta", { fetchOpts: { cache: "no-store" } });
      buildId = `${m.period.from}-${m.period.to}${m.period.mini ? "-mini" : ""}`;
      return m;
    },
    choropleth: (level, bbox) =>
      get(`/api/choropleth/${level}${bbox ? `?bbox=${bbox}` : ""}`, { quiet: true }),
    region: (level, code) => get(`/api/region/${level}/${encodeURIComponent(code)}`),
    points: (bbox, limit) => get(`/api/points?bbox=${bbox}&limit=${limit}`, { quiet: true }),
    refreshStatus: () => get("/api/refresh/status", { fetchOpts: { cache: "no-store" }, quiet: true }),
    refreshStart: () => fetch("/api/refresh", { method: "POST" }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `${r.status}`);
      return r.json();
    }),
  };
})();
