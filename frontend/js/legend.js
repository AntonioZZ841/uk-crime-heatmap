/* Log-scale colour bar + no-data/Scotland chips, driven by /api/meta. */
App.initLegend = function (meta) {
  const cs = meta.color_scale;
  const lo = Math.log10(cs.stops[0][0]);
  const hi = Math.log10(cs.stops[cs.stops.length - 1][0]);
  const gradient = cs.stops
    .map(([v, c]) => `${c} ${(((Math.log10(v) - lo) / (hi - lo)) * 100).toFixed(1)}%`)
    .join(", ");

  const ticks = [10, 30, 100, 300, 1000];
  const period = meta.period.mini
    ? `${meta.period.to} only (mini build, annualised)`
    : `${meta.period.from} – ${meta.period.to}`;

  document.getElementById("legend").innerHTML = `
    <h3>Crime rate <span style="font-weight:400;color:var(--muted)">per 1,000 residents / yr</span></h3>
    <div class="bar" style="background:linear-gradient(to right, ${gradient})"></div>
    <div class="ticks">${ticks.map((t) => `<span>${t >= 1000 ? "1k+" : t}</span>`).join("")}</div>
    <div class="chips">
      <span class="chip"><i style="background:${cs.no_data}"></i>no data</span>
      <span class="chip"><i style="background:${cs.scotland}"></i>Scotland (not published)</span>
      <span class="chip"><i style="width:18px;background:linear-gradient(to right,rgba(70,20,110,.5),#ed6925,#fbfa9e)"></i>street hotspots (z13+)</span>
    </div>
    <div class="period">Period: ${period}</div>
    <div class="opacity-row">
      <label for="opacity-slider">Area opacity</label>
      <input id="opacity-slider" type="range" min="5" max="85" step="5">
      <span id="opacity-val"></span>
    </div>
    <div class="caveat">Rates use resident population — retail &amp; commercial centres
    (e.g. City of London) rank high because visitors aren't counted.</div>`;

  const slider = document.getElementById("opacity-slider");
  const val = document.getElementById("opacity-val");
  slider.value = Math.round(App.areaOpacity * 100);
  val.textContent = `${slider.value}%`;
  slider.oninput = () => {
    val.textContent = `${slider.value}%`;
    App.mapApi?.setBaseOpacity(slider.value / 100);
  };
};
