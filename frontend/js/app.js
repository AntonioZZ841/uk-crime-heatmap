/* Boot + drill-down orchestration: breadcrumb stack, region selection, about modal. */
(async () => {
  const bootError = document.getElementById("boot-error");
  let meta;
  try {
    meta = await App.api.meta();
  } catch (e) {
    bootError.textContent =
      "Could not load map data.\nBuild the database first:\n\nmake mini   (quick sample)\nmake all    (full 12 months)\n\nthen restart the server and reload.";
    bootError.hidden = false;
    return;
  }
  App.meta = meta;
  App.initLegend(meta);
  App.initRefresh(meta);
  App.mapApi = App.initMap(meta);
  App.map = App.mapApi.map;

  // ------------------------------------------------------------ breadcrumb
  const crumbEl = document.getElementById("breadcrumb");
  let stack = []; // [{level, code, name}], outermost first

  function renderCrumbs() {
    const parts = [`<button data-i="-1">UK</button>`];
    stack.forEach((c, i) => {
      parts.push(`<span class="sep">›</span>`);
      parts.push(
        i === stack.length - 1
          ? `<span class="here">${c.name}</span>`
          : `<button data-i="${i}">${c.name}</button>`
      );
    });
    crumbEl.innerHTML = parts.join("");
    crumbEl.querySelectorAll("button").forEach((b) => {
      b.onclick = () => {
        const i = parseInt(b.dataset.i, 10);
        if (i < 0) App.clearSelection({ resetView: true });
        else selectRegion(stack[i].level, stack[i].code);
      };
    });
  }

  // ------------------------------------------------------------- selection
  async function selectRegion(level, code) {
    let data;
    try {
      data = await App.api.region(level, code);
    } catch (e) {
      console.error(e);
      return;
    }
    stack = [...data.parents, { level: data.level, code: data.code, name: data.name }];
    renderCrumbs();
    App.mapApi.setSelected(level, code);
    App.mapApi.flyToRegion(data.bbox, level);
    App.dashboard.render(data);
  }
  App.selectRegion = selectRegion;

  App.clearSelection = ({ resetView = false } = {}) => {
    stack = [];
    renderCrumbs();
    App.mapApi.clearSelected();
    App.dashboard.hide();
    if (resetView) App.mapApi.fitUK();
  };

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!document.getElementById("about").classList.contains("hidden")) {
      toggleAbout(false);
    } else if (stack.length > 1) {
      const parent = stack[stack.length - 2];
      selectRegion(parent.level, parent.code);
    } else if (stack.length === 1) {
      App.clearSelection({ resetView: true });
    }
  });

  // ----------------------------------------------------------------- about
  const aboutEl = document.getElementById("about");
  function toggleAbout(show) {
    aboutEl.classList.toggle("hidden", !show);
  }
  document.getElementById("about-btn").onclick = () => toggleAbout(true);
  aboutEl.addEventListener("click", (e) => {
    if (e.target === aboutEl || e.target.dataset.close) toggleAbout(false);
  });

  const sevRows = meta.severity
    .map((s) => `<tr><td>${s.category}</td><td>${s.weight}</td><td>${s.tier}</td></tr>`)
    .join("");
  document.getElementById("about-body").innerHTML = `
    <p><b>What you're looking at.</b> Street-level crimes recorded by police in England,
    Wales &amp; Northern Ireland (${meta.period.from} – ${meta.period.to};
    ${App.fmt(meta.total_crimes)} records from
    <a href="https://data.police.uk" target="_blank" rel="noopener">data.police.uk</a>).
    Colours show the <b>annualised crime rate per 1,000 residents</b> (ONS mid-2024
    population) on a blue→red log scale. Zoom in for ward and then neighbourhood (LSOA)
    detail, and past z13 for a street-level heatmap of individual incidents.</p>
    <p><b>Biggest incidents.</b> Police data has no "incident size", so the dashboard ranks
    <i>clusters</i> — crimes of one category at one snap-point location — by category
    severity first (tier, then weight), then by count. Weights are a heuristic loosely
    informed by the ONS Crime Severity Score:</p>
    <table><tr><th>Category</th><th>Weight</th><th>Tier</th></tr>${sevRows}</table>
    <p><b>Caveats.</b></p>
    <ul>
      <li>Locations are anonymised snap-points ("on or near"), not exact addresses.</li>
      <li>Rates use <i>resident</i> population — commercial centres and transport hubs
          rank high because visitors aren't counted (City of London is the extreme case).</li>
      <li>Scotland: Police Scotland does not publish to data.police.uk.</li>
      <li>Greater Manchester Police has not published since 2019 — its boroughs show as
          "no data". Forces with partial-month gaps have their rates annualised from the
          months they did report, and their dashboards say so.</li>
      <li>Northern Ireland: PSNI publishes coordinates but no small-area codes or outcomes,
          so NI is mapped at district level (street heatmap still available).</li>
      <li>Some forces are missing recent months; affected regions say so in their dashboard.</li>
      <li>Anti-social behaviour records carry no outcomes by design.</li>
      <li>The ↗ links open a date-bounded news search for each category's latest incident.
          Police records are anonymised, so an exact record-to-article match can't be
          guaranteed — and many incidents are never covered by the press.</li>
    </ul>
    <p style="color:var(--muted)">${meta.attribution}</p>`;

  renderCrumbs();
})();
