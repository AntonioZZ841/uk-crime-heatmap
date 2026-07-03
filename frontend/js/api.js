/* Thin fetch wrapper with a shared "loading" indicator and quiet error policy:
   map-data refreshes fail silently (previous data stays); explicit user actions
   (region click) surface their error. */
App.api = (() => {
  const status = document.getElementById("status");
  let inflight = 0;

  async function get(url, { quiet = false } = {}) {
    inflight += 1;
    status.textContent = "Loading data…";
    status.hidden = false;
    try {
      const r = await fetch(url);
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
    meta: () => get("/api/meta"),
    choropleth: (level, bbox) =>
      get(`/api/choropleth/${level}${bbox ? `?bbox=${bbox}` : ""}`, { quiet: true }),
    region: (level, code) => get(`/api/region/${level}/${encodeURIComponent(code)}`),
    points: (bbox, limit) => get(`/api/points?bbox=${bbox}&limit=${limit}`, { quiet: true }),
  };
})();
