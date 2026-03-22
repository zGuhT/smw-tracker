/* ── SMW Tracker — Game detail with run-specific stats ── */

const $ = (id) => document.getElementById(id);
const GAME_NAME = window.GAME_NAME;
const _UID = window.PROFILE_USER_ID;
const _UNAME = window.PROFILE_USERNAME;
// Suffix to append to API URLs for user scoping
const _US = _UID ? `?user_id=${_UID}` : "";
// Join char: ? if _US is empty, & if _US already has ?
const _UJ = _US ? "&" : "?";

const C = {
  accent: "#6dd5fa", danger: "#f87171", success: "#4ade80",
  muted: "#7a8ba0", grid: "rgba(42, 53, 68, 0.6)",
  gold: "#fbbf24", panel: "#1e2a36",
};
Chart.defaults.color = C.muted;
Chart.defaults.borderColor = C.grid;
Chart.defaults.font.family = "'Outfit', system-ui, sans-serif";

function formatMs(ms) {
  if (ms == null) return "\u2014";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  const frac = Math.floor((ms % 1000) / 10);
  if (m > 0) return `${m}:${String(s).padStart(2, "0")}.${String(frac).padStart(2, "0")}`;
  return `${s}.${String(frac).padStart(2, "0")}`;
}
function formatDuration(s) { if (!s) return "0m"; const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60); return h > 0 ? `${h}h ${m}m` : `${m}m`; }
function formatDate(iso) { if (!iso) return "\u2014"; return iso.replace("T", " ").replace("Z", "").substring(0, 16); }
function formatShortDate(iso) { if (!iso) return "\u2014"; return iso.substring(0, 10); }
function toHours(s) { return Number((s / 3600).toFixed(2)); }
function parseGenres(g) { if (!g) return []; try { const p = JSON.parse(g); return Array.isArray(p) ? p : []; } catch { return []; } }

let pageData = null;
let currentRunDefId = null;
let pbChart = null;

// ══════════════════════════════════════
// DATA LOAD
// ══════════════════════════════════════

async function loadGameDetail() {
  try {
    const res = await fetch(`/stats/game/${encodeURIComponent(GAME_NAME)}${_US}`);
    pageData = await res.json();
    renderHeader(pageData.metadata);
    renderOverallStats(pageData.summary);
    populateRunSelector(pageData.run_definitions, pageData.default_run);
    renderDeathHeatmap(pageData.death_heatmap);
    renderDeathsChart(pageData.deaths_by_level);
    renderPlaytimeChart(pageData.playtime_trend);
    renderSessions(pageData.sessions);

    // Load run-specific data for default run
    const defaultId = pageData.default_run ? pageData.default_run.id : null;
    if (defaultId) {
      await loadRunData(defaultId);
    } else if (pageData.run_definitions && pageData.run_definitions.length > 0) {
      await loadRunData(pageData.run_definitions[0].id);
    }
  } catch (err) {
    console.error("Failed to load:", err);
  }
}

function populateRunSelector(runDefs, defaultRun) {
  const sel = $("gd-run-select");
  if (!runDefs || !runDefs.length) {
    sel.innerHTML = '<option>No runs defined</option>';
    return;
  }
  sel.innerHTML = runDefs.map(rd =>
    `<option value="${rd.id}" ${defaultRun && rd.id === defaultRun.id ? "selected" : ""}>${rd.run_name}${rd.is_default ? " (default)" : ""}</option>`
  ).join("");
}

async function switchRun() {
  const sel = $("gd-run-select");
  if (sel.value) await loadRunData(parseInt(sel.value));
}

async function loadRunData(runDefId) {
  currentRunDefId = runDefId;
  try {
    const res = await fetch(`/stats/game/${encodeURIComponent(GAME_NAME)}/run/${runDefId}${_US}`);
    const data = await res.json();
    renderRunStats(data);
    renderSplitsTable(data.splits);
    renderPBProgression(data.pb_progression);
    populateCompareSelectors(data.run_history, data.splits);
    renderRunHistory(data.run_history, data.splits);
  } catch (err) {
    console.error("Failed to load run data:", err);
  }
}

// ══════════════════════════════════════
// HEADER
// ══════════════════════════════════════

function renderHeader(meta) {
  if (!meta) { $("gd-title").textContent = GAME_NAME; $("gd-platform").textContent = "SNES"; document.title = `SMW Tracker \u2014 ${GAME_NAME}`; return; }
  const title = meta.display_name || meta.rom_name || GAME_NAME;
  $("gd-title").textContent = title;
  $("gd-platform").textContent = meta.platform_name || "SNES";
  document.title = `SMW Tracker \u2014 ${title}`;
  if (meta.boxart_url) { $("gd-boxart").src = meta.boxart_url; $("gd-boxart").classList.remove("hidden"); }
  let tags = [];
  if (meta.source && meta.source !== "fallback") tags.push(meta.source === "thegamesdb" ? "TheGamesDB" : meta.source);
  if (meta.release_date) tags.push(meta.release_date);
  tags = tags.concat(parseGenres(meta.genres_json));
  $("gd-tags").innerHTML = tags.map(t => `<span class="gd-tag visible">${t}</span>`).join("");
  if (meta.overview) { $("gd-overview").textContent = meta.overview; $("gd-overview-wrap").classList.remove("hidden"); }
}

// ══════════════════════════════════════
// OVERALL STATS (all runs)
// ══════════════════════════════════════

function renderOverallStats(summary) {
  $("gd-playtime").textContent = formatDuration(summary.total_playtime_seconds);
  $("gd-sessions").textContent = String(summary.session_count || 0);
  $("gd-deaths").textContent = String(summary.total_deaths || 0);
  $("gd-exits").textContent = String(summary.total_exits || 0);
}

// ══════════════════════════════════════
// RUN-SPECIFIC STATS
// ══════════════════════════════════════

function renderRunStats(data) {
  const splits = data.splits;
  if (splits) {
    $("gd-pb-time").textContent = splits.pb_total_ms ? formatMs(splits.pb_total_ms) : "\u2014";
    $("gd-sob-time").textContent = splits.sum_of_best_ms ? formatMs(splits.sum_of_best_ms) : "\u2014";
    $("gd-attempts").textContent = String(data.run_attempts || splits.total_attempts || 0);
    const save = (splits.pb_total_ms && splits.sum_of_best_ms) ? splits.pb_total_ms - splits.sum_of_best_ms : null;
    $("gd-possible-save").textContent = save != null ? formatMs(save) : "\u2014";
  } else {
    $("gd-pb-time").textContent = "\u2014";
    $("gd-sob-time").textContent = "\u2014";
    $("gd-attempts").textContent = "0";
    $("gd-possible-save").textContent = "\u2014";
  }
}

// ══════════════════════════════════════
// SPLITS TABLE
// ══════════════════════════════════════

function renderSplitsTable(splits) {
  const wrap = $("gd-splits-table");
  if (!splits || !splits.segments || !splits.segments.length) {
    wrap.innerHTML = '<p class="muted">No splits recorded for this run yet.</p>';
    return;
  }
  const rows = splits.segments.map(seg => {
    const isGold = seg.pb_ms != null && seg.best_ms != null && seg.best_ms < seg.pb_ms;
    const diffMs = seg.diff_ms;
    return `<tr>
      <td>${seg.level_name}</td>
      <td class="mono ${isGold ? "gold" : ""}" title="Best segment">${seg.best_ms != null ? formatMs(seg.best_ms) : "\u2014"}${isGold ? " \u2605" : ""}</td>
      <td class="mono">${seg.pb_ms != null ? formatMs(seg.pb_ms) : "\u2014"}</td>
      <td class="mono ${diffMs != null && diffMs <= 0 ? "gold" : ""}">${diffMs != null ? (diffMs <= 0 ? "\u2212" : "+") + formatMs(Math.abs(diffMs)) : "\u2014"}</td>
      <td class="mono muted">${seg.attempt_count || 0}</td>
    </tr>`;
  });

  const pbTotal = splits.pb_total_ms;
  const sobTotal = splits.sum_of_best_ms;
  const savedMs = (pbTotal && sobTotal) ? pbTotal - sobTotal : null;
  const goldCount = splits.segments.filter(s => s.pb_ms != null && s.best_ms != null && s.best_ms < s.pb_ms).length;

  rows.push(`<tr class="ls-totals-row">
    <td><strong>Total</strong> ${goldCount > 0 ? `<span class="gold">(${goldCount} gold)</span>` : ""}</td>
    <td class="mono gold"><strong>${sobTotal ? formatMs(sobTotal) : "\u2014"}</strong></td>
    <td class="mono"><strong>${pbTotal ? formatMs(pbTotal) : "\u2014"}</strong></td>
    <td class="mono">${savedMs != null ? formatMs(savedMs) + " saveable" : ""}</td>
    <td class="mono muted">${splits.total_attempts}</td>
  </tr>`);

  wrap.innerHTML = `<table class="splits-detail-table">
    <thead><tr><th>Level</th><th>Best \u2605</th><th>PB Split</th><th>Save</th><th>Attempts</th></tr></thead>
    <tbody>${rows.join("")}</tbody></table>`;
}

// ══════════════════════════════════════
// PB PROGRESSION
// ══════════════════════════════════════

function renderPBProgression(progression) {
  const canvas = $("chart-pb-progression");
  if (!progression || progression.length < 2) {
    canvas.classList.add("hidden");
    $("no-pb-prog").classList.remove("hidden");
    return;
  }
  canvas.classList.remove("hidden");
  $("no-pb-prog").classList.add("hidden");
  if (pbChart) { pbChart.destroy(); pbChart = null; }

  pbChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: progression.map(p => formatShortDate(p.date)),
      datasets: [{ label: "PB Time", data: progression.map(p => p.total_ms / 1000),
        borderColor: C.accent, backgroundColor: "rgba(109,213,250,0.1)",
        fill: true, tension: 0.3, pointRadius: 5,
        pointBackgroundColor: C.accent, pointBorderColor: C.accent }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => `PB: ${formatMs(ctx.raw * 1000)}` } } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: C.grid }, ticks: { callback: v => formatMs(v * 1000) } } },
    },
  });
}

// ══════════════════════════════════════
// DEATH HEATMAP
// ══════════════════════════════════════

function renderDeathHeatmap(heatmap) {
  const wrap = $("death-heatmap-wrap");
  if (!heatmap || !heatmap.length) { wrap.innerHTML = '<p class="muted">No death position data recorded yet.</p>'; return; }
  wrap.innerHTML = heatmap.slice(0, 10).map(level => {
    const maxX = Math.max(...level.positions.map(p => p.x), 1);
    const maxCount = Math.max(...level.positions.map(p => p.count), 1);
    const segments = level.positions.map(p => {
      const leftPct = (p.x / maxX) * 100;
      const intensity = Math.min(1, p.count / maxCount);
      const r = Math.round(248 * intensity), g = Math.round(113 * (1 - intensity * 0.5)), b = Math.round(113 * (1 - intensity * 0.3));
      const w = Math.max(2, (32 / maxX) * 100);
      return `<div class="heatmap-segment" style="left:${leftPct}%;width:${w}%;background:rgba(${r},${g},${b},${0.3 + intensity * 0.7})" title="x:${p.x} \u2014 ${p.count} death${p.count > 1 ? 's' : ''}"></div>`;
    }).join("");
    const hotspots = level.hotspots.slice(0, 3).map(h => `<span class="heatmap-hotspot">x:${h.x} <span class="danger">(${h.count})</span></span>`).join(" ");
    return `<div class="heatmap-level"><div class="heatmap-level-header"><span class="heatmap-level-name">${level.level_name}</span><span class="heatmap-level-total danger">${level.total_deaths} deaths</span></div><div class="heatmap-bar">${segments}</div><div class="heatmap-hotspots">${hotspots}</div></div>`;
  }).join("");
}

// ══════════════════════════════════════
// CHARTS
// ══════════════════════════════════════

function renderDeathsChart(deaths) {
  const canvas = $("chart-game-deaths");
  if (!deaths || !deaths.length) { canvas.classList.add("hidden"); $("no-deaths").classList.remove("hidden"); return; }
  const avgDeaths = deaths.map(d => d.avg_deaths || 0);
  const attempts = deaths.map(d => d.attempts || 0);
  new Chart(canvas, {
    type: "bar",
    data: { labels: deaths.map(d => d.level), datasets: [{ label: "Deaths", data: deaths.map(d => d.death_count), backgroundColor: C.danger, borderRadius: 4, barPercentage: 0.7 }] },
    options: {
      indexAxis: "y", responsive: true,
      plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: (ctx) => `Avg per attempt: ${avgDeaths[ctx.dataIndex]}\nAttempts: ${attempts[ctx.dataIndex]}` } } },
      scales: { x: { grid: { display: false } }, y: { grid: { display: false } } },
    },
  });
}

function renderPlaytimeChart(playtime) {
  const canvas = $("chart-game-playtime");
  if (!playtime || !playtime.length) { canvas.classList.add("hidden"); $("no-playtime").classList.remove("hidden"); return; }
  new Chart(canvas, {
    type: "line",
    data: { labels: playtime.map(p => p.date), datasets: [{ label: "Hours", data: playtime.map(p => toHours(p.total_playtime_seconds)), borderColor: C.accent, backgroundColor: "rgba(109,213,250,0.08)", fill: true, tension: 0.3, pointRadius: 3, pointBackgroundColor: C.accent }] },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { grid: { color: C.grid }, ticks: { callback: v => Number(v).toFixed(2) + "h" } } } },
  });
}

// ══════════════════════════════════════
// RUN HISTORY (run-specific)
// ══════════════════════════════════════

function renderRunHistory(runs, splitsSummary) {
  const wrap = $("gd-run-history");
  if (!runs || !runs.length) { wrap.innerHTML = '<p class="muted">No completed runs for this category yet.</p>'; return; }
  const bestByLevel = {};
  if (splitsSummary && splitsSummary.segments) { for (const seg of splitsSummary.segments) bestByLevel[seg.level_id] = seg.best_ms; }
  const defLookup = {};
  for (const rd of (pageData?.run_definitions || [])) defLookup[rd.id] = rd.run_name;

  const cards = runs.map(run => {
    const isPB = splitsSummary && splitsSummary.pb && splitsSummary.pb.session_id === run.session_id;
    const runDefName = run.run_definition_id ? defLookup[run.run_definition_id] : null;
    const runBadge = runDefName ? `<span class="setup-item-badge">${runDefName}</span>` : "";
    const splitsPreview = run.splits.slice(0, 5).map(s => {
      const isGold = bestByLevel[s.level_id] != null && s.split_ms === bestByLevel[s.level_id];
      return `<span class="run-history-split ${isGold ? "gold" : ""}">${s.level_name}: ${formatMs(s.split_ms)}</span>`;
    }).join("");
    const moreCount = run.splits.length > 5 ? ` <span class="muted">+${run.splits.length - 5} more</span>` : "";
    return `<div class="run-history-card ${isPB ? "pb-run" : ""}">
      <div class="run-history-header">
        <span class="run-history-date">${formatDate(run.date)} ${runBadge}</span>
        <span class="run-history-time mono ${isPB ? "accent-color" : ""}">${formatMs(run.total_ms)}${isPB ? " PB" : ""}</span>
        <span class="run-history-meta">${run.levels_completed} levels \u00b7 ${run.total_deaths} deaths</span>
      </div>
      <div class="run-history-splits">${splitsPreview}${moreCount}</div>
    </div>`;
  }).join("");
  wrap.innerHTML = cards;
}

// ══════════════════════════════════════
// SESSIONS
// ══════════════════════════════════════

function renderSessions(sessions) {
  const wrap = $("gd-sessions-table");
  if (!sessions || !sessions.length) { wrap.innerHTML = '<p class="muted">No sessions recorded.</p>'; return; }
  const rows = sessions.map(s => `<tr>
    <td class="mono">${formatDate(s.start_time)}</td>
    <td class="mono">${formatDuration(s.duration_seconds)}</td>
    <td>${s.is_active ? '<span class="status-badge active">Live</span>' : '<span class="muted">Done</span>'}</td>
  </tr>`).join("");
  wrap.innerHTML = `<table class="sessions-table"><thead><tr><th>Started</th><th>Duration</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ══════════════════════════════════════
// RUN COMPARISON (run-specific)
// ══════════════════════════════════════

function populateCompareSelectors(runs, splits) {
  const wrap = $("compare-controls");
  if (!runs || runs.length < 2) { wrap.innerHTML = '<p class="muted">Need at least 2 runs in this category to compare.</p>'; return; }
  const pbSessionId = splits?.pb?.session_id;
  const options = runs.map(r => {
    const isPB = r.session_id === pbSessionId;
    return `<option value="${r.session_id}">${formatShortDate(r.date)} \u2014 ${formatMs(r.total_ms)} (${r.levels_completed} lvls, ${r.total_deaths} deaths)${isPB ? " \u2605 PB" : ""}</option>`;
  }).join("");

  wrap.innerHTML = `<div class="compare-select-row">
    <div class="compare-select-group"><label class="compare-label">Run A</label><select id="compare-run-a" class="compare-select">${options}</select></div>
    <span class="compare-vs">vs</span>
    <div class="compare-select-group"><label class="compare-label">Run B</label><select id="compare-run-b" class="compare-select">${options}</select></div>
    <button onclick="loadComparison()" class="primary">Compare</button>
  </div>`;

  const selA = $("compare-run-a"), selB = $("compare-run-b");
  if (pbSessionId) selA.value = String(pbSessionId);
  if (runs[0].session_id !== pbSessionId) selB.value = String(runs[0].session_id);
  else if (runs.length > 1) selB.value = String(runs[1].session_id);
}

async function loadComparison() {
  const runA = $("compare-run-a")?.value, runB = $("compare-run-b")?.value;
  if (!runA || !runB) return;
  if (runA === runB) { $("compare-result").innerHTML = '<p class="muted">Select two different runs.</p>'; return; }
  try {
    const res = await fetch(`/stats/game/${encodeURIComponent(GAME_NAME)}/compare?run_a=${runA}&run_b=${runB}${_UID ? '&user_id=' + _UID : ''}`);
    renderComparison(await res.json());
  } catch (err) { $("compare-result").innerHTML = '<p class="muted">Failed to load comparison.</p>'; }
}

function renderComparison(data) {
  const wrap = $("compare-result");
  const comp = data.comparison || [];
  const a = data.run_a, b = data.run_b;
  if (!comp.length) { wrap.innerHTML = '<p class="muted">No overlapping splits.</p>'; return; }

  const rows = comp.map(row => {
    const aGold = row.a_is_gold ? " gold" : "", bGold = row.b_is_gold ? " gold" : "";
    let diffCell = "\u2014", diffClass = "";
    if (row.diff_ms != null) {
      diffClass = row.diff_ms > 0 ? "behind" : row.diff_ms < 0 ? "ahead" : "";
      diffCell = `${row.diff_ms > 0 ? "+" : row.diff_ms < 0 ? "\u2212" : ""}${formatMs(Math.abs(row.diff_ms))}`;
    }
    let cumDiff = "", cumClass = "";
    if (row.cumulative_a != null && row.cumulative_b != null) {
      const cd = row.cumulative_a - row.cumulative_b;
      cumClass = cd > 0 ? "behind" : cd < 0 ? "ahead" : "";
      cumDiff = `${cd > 0 ? "+" : cd < 0 ? "\u2212" : ""}${formatMs(Math.abs(cd))}`;
    }
    return `<tr><td>${row.level_name}</td><td class="mono${aGold}">${row.a_ms != null ? formatMs(row.a_ms) : "\u2014"}${row.a_is_gold ? " \u2605" : ""}</td><td class="mono${bGold}">${row.b_ms != null ? formatMs(row.b_ms) : "\u2014"}${row.b_is_gold ? " \u2605" : ""}</td><td class="mono ${diffClass}">${diffCell}</td><td class="mono ${cumClass}">${cumDiff}</td></tr>`;
  }).join("");

  const td = data.total_diff_ms;
  let tdc = "\u2014", tdcl = "";
  if (td != null) { tdcl = td > 0 ? "behind" : td < 0 ? "ahead" : ""; tdc = `${td > 0 ? "+" : td < 0 ? "\u2212" : ""}${formatMs(Math.abs(td))}`; }

  wrap.innerHTML = `<table class="compare-table"><thead><tr><th>Level</th><th>Run A: ${formatShortDate(a.date)}</th><th>Run B: ${formatShortDate(b.date)}</th><th>\u0394 Split</th><th>\u0394 Cumul.</th></tr></thead>
    <tbody>${rows}<tr class="ls-totals-row"><td><strong>Total</strong></td><td class="mono"><strong>${formatMs(a.total_ms)}</strong></td><td class="mono"><strong>${formatMs(b.total_ms)}</strong></td><td class="mono ${tdcl}"><strong>${tdc}</strong></td><td></td></tr></tbody></table>
    <div class="compare-summary"><span>Run A: <strong class="mono">${formatMs(a.total_ms)}</strong> (${a.total_deaths} deaths)</span><span>Run B: <strong class="mono">${formatMs(b.total_ms)}</strong> (${b.total_deaths} deaths)</span></div>`;
}

document.addEventListener("DOMContentLoaded", loadGameDetail);
