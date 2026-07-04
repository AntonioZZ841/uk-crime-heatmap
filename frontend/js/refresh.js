/* "Update data" row in the legend: checks police.uk for a newer month,
   starts the backend refresh job, polls progress, reloads when swapped. */
App.initRefresh = async function (meta) {
  if (!meta.refresh_supported) return;

  const legend = document.getElementById("legend");
  const row = document.createElement("div");
  row.className = "refresh-row";
  legend.appendChild(row);

  const POLL_MS = 5000;
  let polling = null;

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function render(html) {
    row.innerHTML = html;
  }

  function minutes(startedAt) {
    return Math.max(1, Math.round((Date.now() / 1000 - startedAt) / 60));
  }

  function showRunning(job) {
    render(`<span class="spin"></span><span class="refresh-note">${esc(job.step || "Updating")}…
      ${minutes(job.started_at)} min</span>`);
    if (!polling) polling = setInterval(poll, POLL_MS);
  }

  async function poll() {
    let s;
    try {
      s = await App.api.refreshStatus();
    } catch {
      return; // transient poll failure - try again next tick
    }
    const job = s.job;
    if (job.state === "running") {
      showRunning(job);
    } else if (job.state === "done" && polling) {
      clearInterval(polling);
      polling = null;
      const version = (s.update && s.update.current) || "the latest data";
      render(`<span class="refresh-note">Update ready</span>
        <button class="refresh-btn" id="refresh-apply">Refresh to apply</button>`);
      document.getElementById("refresh-apply").onclick = () => location.reload();
      showDonePopup(version);
    } else if (job.state === "error" && polling) {
      clearInterval(polling);
      polling = null;
      console.error("data refresh failed:", job.error, job.log_tail);
      render(`<span class="refresh-err" title="${esc(job.error)}">Update failed — still showing
        current data.</span> <button class="refresh-btn" id="refresh-retry">Retry</button>`);
      document.getElementById("refresh-retry").onclick = startUpdate;
    } else if (job.state !== "running") {
      showIdle(s.update);
    }
  }

  function showIdle(update) {
    if (!update) return render("");
    if (update.update_available === true) {
      render(`<button class="refresh-btn" id="refresh-go">Update data to ${esc(update.latest)}</button>
        <span class="refresh-note">~15–25 min</span>`);
      document.getElementById("refresh-go").onclick = startUpdate;
    } else if (update.update_available === false) {
      render(`<span class="refresh-note">Data up to date ✓ (${esc(update.current)})</span>`);
    } else {
      render(`<span class="refresh-note" title="${esc(update.check_error || "")}">Couldn't check for
        new data.</span> <button class="refresh-btn" id="refresh-any">Update anyway</button>`);
      document.getElementById("refresh-any").onclick = startUpdate;
    }
  }

  function showDonePopup(version) {
    document.getElementById("update-modal")?.remove();
    const overlay = document.createElement("div");
    overlay.id = "update-modal";
    overlay.innerHTML = `
      <div class="update-card">
        <h3>Data updated ✓</h3>
        <p>The crime database has been updated to <b>${esc(version)}</b>.
           Refresh the interface to load the new version.</p>
        <div class="update-actions">
          <button class="refresh-btn primary" id="update-reload">Refresh now</button>
          <button class="refresh-btn" id="update-later">Later</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector("#update-reload").onclick = () => location.reload();
    overlay.querySelector("#update-later").onclick = () => overlay.remove();
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
  }

  async function startUpdate() {
    render(`<span class="spin"></span><span class="refresh-note">Starting update…</span>`);
    try {
      await App.api.refreshStart();
    } catch (e) {
      render(`<span class="refresh-err">${esc(e.message)}</span>`);
      return;
    }
    if (!polling) polling = setInterval(poll, POLL_MS);
  }

  // initial state (also resumes the progress UI if a job is already running)
  try {
    const s = await App.api.refreshStatus();
    if (s.job.state === "running") showRunning(s.job);
    else showIdle(s.update);
  } catch {
    render("");
  }
};
