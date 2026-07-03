/* Region dashboard panel: header, stats, trend sparkline, category bars,
   severity-ranked "biggest incidents" cluster list. */
App.dashboard = (() => {
  const panel = document.getElementById("panel");
  const content = document.getElementById("panel-content");

  const LEVEL_LABEL = { lad: "Local authority", ward: "Ward", lsoa: "Neighbourhood (LSOA)" };

  // Press-friendly search terms - police category names rarely match headlines.
  const NEWS_TERMS = {
    "Violence and sexual offences": "assault",
    "Robbery": "robbery",
    "Possession of weapons": "weapon offence",
    "Burglary": "burglary",
    "Vehicle crime": "car theft",
    "Theft from the person": "theft",
    "Criminal damage and arson": "arson",
    "Drugs": "drug offence",
    "Public order": "public order offence",
    "Other theft": "theft",
    "Shoplifting": "shoplifting",
    "Bicycle theft": "bike theft",
    "Other crime": "crime",
    "Anti-social behaviour": "anti-social behaviour",
  };

  function nextMonth(ym) {
    let [y, m] = ym.split("-").map(Number);
    m += 1;
    if (m > 12) { y += 1; m = 1; }
    return `${y}-${String(m).padStart(2, "0")}-01`;
  }

  // News search for the most recent incident of a category in this region:
  // term + street of the latest incident + a place name the press would use
  // (LSOA names like "Camden 028D" mean nothing to news sites - use parents),
  // date-bounded to that incident's month.
  function newsUrl(cat, d) {
    const term = NEWS_TERMS[cat.category] || cat.category;
    const place =
      d.level === "lad" ? d.name
      : d.level === "ward" ? `${d.name} ${d.parents[0]?.name || ""}`
      : `${d.parents[1]?.name || ""} ${d.parents[0]?.name || ""}`;
    const street = App.stripLocation(cat.last_location || "");
    let q = `${term} ${street} ${place}`.replace(/\s+/g, " ").trim();
    if (cat.last_month) q += ` after:${cat.last_month}-01 before:${nextMonth(cat.last_month)}`;
    return "https://news.google.com/search?q=" + encodeURIComponent(q);
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function sparkline(trend) {
    const W = 320, H = 44, P = 3;
    const max = Math.max(1, ...trend.map((t) => t.n));
    const step = trend.length > 1 ? (W - 2 * P) / (trend.length - 1) : 0;
    const pt = (t, i) => `${(P + i * step).toFixed(1)},${(H - P - ((H - 2 * P) * t.n) / max).toFixed(1)}`;
    const line = trend.map(pt).join(" ");
    return `
      <svg class="sparkline" viewBox="0 0 ${W} ${H + 12}" preserveAspectRatio="none">
        <polygon points="${P},${H - P} ${line} ${W - P},${H - P}" fill="#dbe7f3"/>
        <polyline points="${line}" fill="none" stroke="var(--accent)" stroke-width="1.8"/>
      </svg>
      <div class="spark-caption">${esc(trend[0]?.month)} → ${esc(trend[trend.length - 1]?.month)},
        peak ${App.fmt(max)}/month</div>`;
  }

  function categoryBars(byCat, d) {
    const max = Math.max(1, ...byCat.map((c) => c.n));
    return byCat
      .map((c) => {
        // proportional to count; keep a 2px sliver so small-but-present
        // categories stay visible, and nothing at all for zero
        const width = c.n > 0 ? `max(${((100 * c.n) / max).toFixed(1)}%, 2px)` : "0";
        const news = c.n > 0
          ? `<a class="news" href="${newsUrl(c, d)}" target="_blank" rel="noopener"
               title="Search news coverage: ${esc(NEWS_TERMS[c.category] || c.category)} near ${esc(App.stripLocation(c.last_location || ""))} (${esc(c.last_month || "")})">↗</a>`
          : "";
        return `
      <div class="row">
        <span class="lbl" title="${esc(c.category)}: ${App.fmt(c.n)}">${esc(c.category)}</span>
        <span class="track"><span class="fill" style="width:${width};
          background:${c.tier === 1 ? "var(--danger)" : "var(--accent)"}"></span></span>
        <span class="n">${App.fmt(c.n)}</span>
        ${news}
      </div>`;
      })
      .join("");
  }

  function clusterCard(cl) {
    const outcomes = cl.outcomes
      .map((o) => `${esc(o.outcome)} <span style="color:#9aa7b5">×${App.fmt(o.n)}</span>`)
      .join("<br>");
    return `
      <div class="cluster">
        <div class="head">
          <span class="rank">#${cl.rank}</span>
          <span class="cat ${cl.tier === 1 ? "tier1" : ""}">${esc(cl.category)}</span>
          <span class="score" title="severity weight × incident count">score ${cl.score}</span>
        </div>
        <div class="meta"><b>${App.fmt(cl.n)}</b> incident${cl.n === 1 ? "" : "s"}
          on or near <b>${esc(App.stripLocation(cl.location)) || "unnamed location"}</b>
          · latest ${esc(cl.last_month) || "–"}</div>
        ${outcomes ? `<div class="outcomes">${outcomes}</div>` : ""}
        ${cl.lon != null ? `<button class="locate" data-lon="${cl.lon}" data-lat="${cl.lat}"
          data-label="${esc(cl.category)} — ${esc(App.stripLocation(cl.location))}">Locate on map</button>` : ""}
      </div>`;
  }

  function render(d) {
    const rate = d.rate_per_1000 == null ? "–" : d.rate_per_1000.toLocaleString("en-GB");
    const rankChip = d.rate_per_1000 == null
      ? ""
      : `<span class="rankchip">#${d.rank.position} of ${d.rank.of} by rate</span>`;
    content.innerHTML = `
      <button class="close" title="Close panel">&times;</button>
      <h2>${esc(d.name)}${rankChip}</h2>
      <div class="sub">${LEVEL_LABEL[d.level] || d.level}
        ${d.parents.length ? "· " + d.parents.map((p) => esc(p.name)).join(" › ") : ""}</div>
      <div class="stats">
        <div class="stat"><b>${App.fmt(d.crimes_12m)}</b><span>crimes in period</span></div>
        <div class="stat"><b>${rate}</b><span>per 1,000 residents / yr</span></div>
        <div class="stat"><b>${App.fmt(d.population)}</b><span>residents</span></div>
      </div>
      ${d.notes.map((n) => `<div class="note">${esc(n)}</div>`).join("")}
      <h4>Monthly trend</h4>
      ${sparkline(d.trend)}
      <h4>Crime types <span style="text-transform:none;letter-spacing:0">(↗ = news search, latest incident)</span></h4>
      <div class="cats">${categoryBars(d.by_category, d)}</div>
      <h4>Biggest incidents <span style="text-transform:none;letter-spacing:0">(severity-ranked)</span></h4>
      ${d.clusters.length ? d.clusters.map(clusterCard).join("") : "<p style='font-size:12px;color:var(--muted)'>No incidents recorded.</p>"}
    `;
    content.querySelector(".close").onclick = () => App.clearSelection();
    content.querySelectorAll(".locate").forEach((btn) => {
      btn.onclick = () =>
        App.mapApi.locate(parseFloat(btn.dataset.lon), parseFloat(btn.dataset.lat), btn.dataset.label);
    });
    panel.classList.remove("hidden");
    panel.scrollTop = 0;
  }

  return { render, hide: () => panel.classList.add("hidden") };
})();
