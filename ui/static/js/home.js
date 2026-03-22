/* ── SMW Tracker — Landing page + local tracker (admin only) ── */

const $ = (id) => document.getElementById(id);
const WINDOW_SIZE = 5;

function formatMs(ms) {
  if (ms == null) return "\u2014";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  const frac = Math.floor((ms % 1000) / 10);
  if (m > 0) return `${m}:${String(s).padStart(2, "0")}.${String(frac).padStart(2, "0")}`;
  return `${s}.${String(frac).padStart(2, "0")}`;
}

function formatDiffMs(diffMs) {
  if (diffMs == null) return "";
  const sign = diffMs >= 0 ? "+" : "\u2212";
  return `${sign}${formatMs(Math.abs(diffMs))}`;
}

function formatHours(seconds) {
  if (!seconds) return "0m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatDate(iso) {
  if (!iso) return "\u2014";
  return iso.replace("T", " ").replace("Z", "").substring(0, 16);
}

// ══════════════════════════════════════
// LIVE BANNER (polls /live/state)
// ══════════════════════════════════════

async function pollLiveBanner() {
  try {
    const res = await fetch("/live/state");
    const data = await res.json();
    const banner = $("live-banner");
    if (data && data.is_active && data.game_name) {
      $("lb-game").textContent = data.game_name;
      const runInfo = data.run_name ? ` \u2014 ${data.run_name}` : "";
      const deaths = data.deaths_this_session || 0;
      const level = data.current_level_name || "";
      $("lb-detail").textContent = `${level ? level + " \u00b7 " : ""}${deaths} deaths${runInfo} \u2014 click to watch`;
      banner.classList.remove("hidden");
    } else {
      banner.classList.add("hidden");
    }
  } catch {
    const banner = $("live-banner");
    if (banner) banner.classList.add("hidden");
  }
}

// ══════════════════════════════════════
// RECENT RUNS
// ══════════════════════════════════════

async function loadRecentRuns() {
  const wrap = $("recent-runs");
  try {
    const res = await fetch("/stats/recent-sessions?limit=10");
    const sessions = await res.json();

    // Filter to only sessions that have meaningful data
    if (!sessions || !sessions.length) {
      wrap.innerHTML = '<p class="muted">No runs yet. Start playing to see your history here.</p>';
      return;
    }

    const cards = sessions.slice(0, 6).map(s => {
      const duration = s.duration_seconds
        ? formatHours(s.duration_seconds)
        : "\u2014";
      return `<div class="recent-run-card">
        <div class="recent-run-game">${s.game_name}</div>
        <div class="recent-run-meta">
          <span>${formatDate(s.start_time)}</span>
          <span>${duration}</span>
          <span>${s.is_active ? '<span class="status-badge active">Live</span>' : ""}</span>
        </div>
      </div>`;
    }).join("");

    wrap.innerHTML = cards;
  } catch {
    wrap.innerHTML = '<p class="muted">Failed to load recent runs.</p>';
  }
}

// ══════════════════════════════════════
// GAMES LIBRARY
// ══════════════════════════════════════

async function loadGamesLibrary() {
  const wrap = $("games-list");
  try {
    const res = await fetch("/stats/games");
    const games = await res.json();
    if (!games.length) {
      wrap.innerHTML = '<p class="muted">No games tracked yet.</p>';
      return;
    }
    wrap.innerHTML = games.map((g) => {
      const boxart = g.boxart_url
        ? `<img class="game-card-art" src="${g.boxart_url}" alt="" onerror="this.style.display='none'">`
        : `<div class="game-card-art-placeholder">&#127918;</div>`;
      return `<a href="/game/${encodeURIComponent(g.game_name)}" class="game-card">
        ${boxart}
        <div class="game-card-body">
          <div class="game-card-title">${g.display_name || g.game_name}</div>
          <div class="game-card-meta">
            <span>${formatHours(g.total_playtime_seconds)}</span>
            <span>${g.session_count} session${g.session_count !== 1 ? "s" : ""}</span>
          </div>
        </div>
      </a>`;
    }).join("");
  } catch {
    wrap.innerHTML = '<p class="muted">Failed to load library.</p>';
  }
}

// ══════════════════════════════════════
// LOCAL TRACKER (only rendered if admin)
// ══════════════════════════════════════

let lastSessionData = null;
let serverTimeOffset = 0;
let lastGameName = null;
let cachedMetadata = null;
let prevSplitCount = 0;
let prevRunComplete = false;
let prevRunStarted = false;

async function fetchMetadata(gameName) {
  if (!gameName) return null;
  if (gameName === lastGameName && cachedMetadata) return cachedMetadata;
  try {
    const res = await fetch(`/metadata/lookup?rom_path=${encodeURIComponent(gameName)}`);
    if (!res.ok) return null;
    cachedMetadata = await res.json();
    lastGameName = gameName;
    return cachedMetadata;
  } catch { return null; }
}

async function pollSession() {
  // Only poll if admin (the np-card element exists)
  if (!$("np-card")) return;

  try {
    const res = await fetch("/session/current");
    const data = await res.json();
    if (data.server_time) serverTimeOffset = data.server_time - (Date.now() / 1000);

    // Sound triggers
    if (data.is_active && lastSessionData) {
      const newSplits = (data.splits || []).length;
      const pbSplits = data.pb_splits || [];
      const bestSegments = data.best_segments || {};

      if (newSplits > prevSplitCount && newSplits > 0) {
        const latestSplit = data.splits[newSplits - 1];
        const pbMs = pbSplits.find(s => s.level_id === latestSplit.level_id)?.split_ms;
        const bestMs = bestSegments[latestSplit.level_id];
        const isGold = bestMs != null && latestSplit.split_ms <= bestMs;
        if (isGold) SFX.play("gold");
        else if (pbMs != null && latestSplit.split_ms <= pbMs) SFX.play("ahead");
        else if (pbMs != null) SFX.play("behind");
      }
      if (data.run_complete && !prevRunComplete) {
        const completedMs = (data.splits || []).reduce((s, x) => s + (x.split_ms || 0), 0);
        if (data.pb_total_ms && completedMs < data.pb_total_ms) SFX.play("pb");
        else SFX.play("complete");
      }
      if (data.run_start_epoch && !prevRunStarted) SFX.play("start");
      prevSplitCount = newSplits;
      prevRunComplete = !!data.run_complete;
      prevRunStarted = !!data.run_start_epoch;
    } else if (!data.is_active) {
      prevSplitCount = 0; prevRunComplete = false; prevRunStarted = false;
    }

    lastSessionData = data;
    renderSession(data);
  } catch {}
}

function tickTimer() {
  const data = lastSessionData;
  if (!data || !data.is_active) return;

  const completed = data.splits || [];
  const completedMs = completed.reduce((s, x) => s + (x.split_ms || 0), 0);
  const now = (Date.now() / 1000) + serverTimeOffset;
  const delay = data.run_delay_ms || 0;
  const paused = data.is_paused || false;
  const done = data.run_complete || false;
  const pbSplits = data.pb_splits || [];

  let curMs = 0, totalMs = 0;
  if (done) { totalMs = completedMs; }
  else if (paused && data.paused_at) {
    if (completed.length > 0 && data.current_split_start) { curMs = Math.max(0, (data.paused_at - data.current_split_start) * 1000); totalMs = completedMs + curMs; }
    else if (data.run_start_epoch) { totalMs = (data.paused_at - data.run_start_epoch) * 1000 - delay; curMs = Math.max(0, totalMs); }
  } else if (completed.length > 0 && data.current_split_start) { curMs = Math.max(0, (now - data.current_split_start) * 1000); totalMs = completedMs + curMs; }
  else if (data.run_start_epoch) { totalMs = (now - data.run_start_epoch) * 1000 - delay; curMs = Math.max(0, totalMs); }

  const active = !!data.run_start_epoch;
  let pbPartial = 0;
  for (let i = 0; i < completed.length && i < pbSplits.length; i++) pbPartial += pbSplits[i].split_ms || 0;
  const compDiff = completed.length > 0 ? completedMs - pbPartial : null;
  const isAhead = compDiff != null ? compDiff <= 0 : null;
  const curPbMs = completed.length < pbSplits.length ? (pbSplits[completed.length].split_ms || 0) : null;

  const timer = $("np-timer");
  if (timer) {
    timer.className = "ls-timer";
    if (active) {
      if (totalMs < 0) { timer.textContent = `\u2212${formatMs(Math.abs(totalMs))}`; timer.classList.add("muted"); }
      else { timer.textContent = formatMs(totalMs); if (paused) timer.classList.add("paused"); else if (isAhead === true) timer.classList.add("timer-ahead"); else if (isAhead === false) timer.classList.add("timer-behind"); }
    } else { timer.textContent = "0:00.00"; timer.classList.add("muted"); }
  }

  const liveSplitEl = $("np-current-split-time");
  const liveDiffEl = $("np-current-split-diff");
  if (liveSplitEl && active && !done && totalMs >= 0) liveSplitEl.textContent = formatMs(curMs);
  if (liveDiffEl && active && !done && curPbMs != null && totalMs >= 0) {
    const d = curMs - curPbMs;
    liveDiffEl.textContent = formatDiffMs(d);
    liveDiffEl.className = `ls-col-diff mono ${d <= 0 ? "ahead" : "behind"}`;
  } else if (liveDiffEl) { liveDiffEl.textContent = ""; liveDiffEl.className = "ls-col-diff mono"; }

  const pace = $("np-pace");
  if (pace) {
    if (done) {
      if (data.pb_total_ms && completedMs < data.pb_total_ms) { pace.textContent = `\ud83c\udf89 PB! ${formatDiffMs(completedMs - data.pb_total_ms)}`; pace.className = "ls-pace ahead"; }
      else if (data.pb_total_ms) { pace.textContent = `Done: ${formatDiffMs(completedMs - data.pb_total_ms)}`; pace.className = completedMs <= data.pb_total_ms ? "ls-pace ahead" : "ls-pace behind"; }
      else { pace.textContent = `Done: ${formatMs(completedMs)}`; pace.className = "ls-pace ahead"; }
    } else if (paused) { pace.textContent = "\u23f8 Paused"; pace.className = "ls-pace muted"; }
    else if (compDiff != null) { pace.textContent = formatDiffMs(compDiff); pace.className = compDiff <= 0 ? "ls-pace ahead" : "ls-pace behind"; }
    else if (active && totalMs < 0) { pace.textContent = "Starting..."; pace.className = "ls-pace muted"; }
    else { pace.textContent = ""; pace.className = "ls-pace muted"; }
  }

  // Buttons
  const pauseBtn = $("btn-pause"), splitBtn = $("btn-split"), undoBtn = $("btn-undo"), resetBtn = $("btn-reset");
  if (done) {
    [pauseBtn, splitBtn].forEach(b => { if (b) { b.disabled = true; b.style.opacity = "0.3"; b.style.pointerEvents = "none"; } });
    [undoBtn, resetBtn].forEach(b => { if (b) { b.disabled = false; b.style.opacity = "1"; b.style.pointerEvents = "auto"; } });
  } else {
    [pauseBtn, splitBtn, undoBtn, resetBtn].forEach(b => { if (b) { b.disabled = false; b.style.opacity = "1"; b.style.pointerEvents = "auto"; } });
    if (pauseBtn) { if (paused) { pauseBtn.textContent = "\u25b6"; pauseBtn.classList.add("active"); } else if (active) { pauseBtn.textContent = "\u23f8"; pauseBtn.classList.remove("active"); } else { pauseBtn.textContent = "\u25b6"; pauseBtn.classList.remove("active"); } }
  }
}

function renderSession(data) {
  const empty = $("np-empty"), content = $("np-content");
  if (!empty || !content) return;
  if (!data || !data.is_active) { empty.classList.remove("hidden"); content.classList.add("hidden"); lastGameName = null; cachedMetadata = null; lastSessionData = null; return; }
  empty.classList.add("hidden"); content.classList.remove("hidden");
  $("np-game-name").textContent = data.game_name || "\u2014";
  $("np-platform").textContent = (data.platform || "SNES") + (data.run_name ? ` \u2014 ${data.run_name}` : "");
  $("np-deaths").textContent = String(data.deaths_this_session ?? 0);
  $("np-level").textContent = data.current_level_name || "\u2014";
  $("np-sob").textContent = data.sum_of_best_ms ? formatMs(data.sum_of_best_ms) : "\u2014";
  $("np-pb").textContent = data.pb_total_ms ? formatMs(data.pb_total_ms) : "\u2014";
  renderSplits(data);
  if (data.game_name && data.game_name !== lastGameName) {
    fetchMetadata(data.game_name).then((meta) => {
      if (meta?.boxart_url) { $("np-boxart").src = meta.boxart_url; $("np-boxart").classList.remove("hidden"); }
      if (meta?.display_name) $("np-game-name").textContent = meta.display_name;
    });
  }
  tickTimer();
}

function renderSplits(data) {
  const tbody = $("np-splits-body");
  if (!tbody) return;
  const completed = data.splits || [], runLevels = data.run_levels || [], pbSplits = data.pb_splits || [], bestSegs = data.best_segments || {};
  const pbLookup = {}, completedMap = {};
  for (const s of pbSplits) pbLookup[s.level_id] = s.split_ms;
  for (const s of completed) completedMap[s.level_id] = s;
  const rows = [];
  if (runLevels.length > 0) {
    for (const rl of runLevels) {
      const done = completedMap[rl.level_id], pb = pbLookup[rl.level_id] ?? null, best = bestSegs[rl.level_id] ?? null;
      if (done) { const diff = pb != null ? done.split_ms - pb : null; const isGold = best != null && done.split_ms <= best; rows.push({levelName: rl.level_name || rl.level_id, splitMs: done.split_ms, pbMs: pb, diffMs: diff, completed: true, isGold}); }
      else rows.push({levelName: rl.level_name || rl.level_id, splitMs: null, pbMs: pb, diffMs: null, completed: false, isGold: false});
    }
  } else { for (const s of completed) { const pb = pbLookup[s.level_id] ?? null, best = bestSegs[s.level_id] ?? null, diff = pb != null ? s.split_ms - pb : null, isGold = best != null && s.split_ms <= best; rows.push({levelName: s.level_name || s.level_id, splitMs: s.split_ms, pbMs: pb, diffMs: diff, completed: true, isGold}); } }
  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;padding:16px">No run definition set up.</td></tr>'; return; }
  let curIdx = rows.findIndex(r => !r.completed); if (curIdx === -1) curIdx = rows.length;
  const total = rows.length; let ws = 0, we = total;
  if (total > WINDOW_SIZE) { const half = Math.floor(WINDOW_SIZE / 2); ws = Math.max(0, curIdx - half); we = ws + WINDOW_SIZE; if (we > total) { we = total; ws = Math.max(0, we - WINDOW_SIZE); } }
  const html = rows.slice(ws, we).map((r, i) => {
    const gi = ws + i, isCur = gi === curIdx;
    const diffCls = r.diffMs == null ? "" : r.diffMs <= 0 ? (r.isGold ? "gold" : "ahead") : "behind";
    const rowCls = isCur ? "ls-split-row current" : r.completed ? "ls-split-row completed" : "ls-split-row upcoming";
    const goldCls = r.isGold ? " gold" : "";
    let timeCell, diffCell;
    if (r.completed) { timeCell = `<td class="ls-col-time mono${goldCls}">${formatMs(r.splitMs)}${r.isGold ? " \u2605" : ""}</td>`; diffCell = `<td class="ls-col-diff mono ${diffCls}">${r.diffMs != null ? formatDiffMs(r.diffMs) : ""}</td>`; }
    else if (isCur) { timeCell = `<td class="ls-col-time mono accent" id="np-current-split-time">\u2014</td>`; diffCell = `<td class="ls-col-diff mono" id="np-current-split-diff"></td>`; }
    else { timeCell = `<td class="ls-col-time mono muted">\u2014</td>`; diffCell = `<td class="ls-col-diff mono"></td>`; }
    return `<tr class="${rowCls}"><td class="ls-col-num mono">${gi+1}</td><td class="ls-col-name">${r.levelName}</td>${timeCell}${diffCell}<td class="ls-col-pb mono muted">${r.pbMs != null ? formatMs(r.pbMs) : "\u2014"}</td></tr>`;
  }).join("");
  const above = ws > 0 ? `<tr class="ls-split-indicator"><td colspan="5" class="muted">\u25b2 ${ws} more</td></tr>` : "";
  const below = (total - we) > 0 ? `<tr class="ls-split-indicator"><td colspan="5" class="muted">\u25bc ${total - we} more</td></tr>` : "";
  tbody.innerHTML = above + html + below;
}

// ── Run Controls ──
async function manualSplit() { try { const r = await fetch("/run/split", {method:"POST"}); if ((await r.json()).success) pollSession(); } catch {} }
async function undoSplit() { try { const r = await fetch("/run/undo", {method:"POST"}); if ((await r.json()).success) pollSession(); } catch {} }
async function togglePause() { try { await fetch("/run/pause", {method:"POST"}); pollSession(); } catch {} }
async function resetRun() { if (!confirm("Reset the current run?")) return; try { await fetch("/run/reset", {method:"POST"}); pollSession(); } catch {} }

function toggleSoundSettings() { const el = $("sound-settings"), help = $("shortcut-help"); if (el) el.classList.toggle("hidden"); if (help) help.classList.toggle("hidden"); }
function saveSoundSettings() { SFX.saveSettings(); }
function testSound(type) { SFX.play(type); }

// ── Keyboard Shortcuts ──
const SHORTCUTS = { "Numpad1": manualSplit, "Numpad2": undoSplit, "Numpad3": togglePause, "Numpad4": resetRun, "Space": manualSplit, "KeyZ": undoSplit, "KeyP": togglePause };
function handleKeyShortcut(e) { if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return; const fn = SHORTCUTS[e.code]; if (fn) { e.preventDefault(); fn(); } }

// ── Init ──
function init() {
  SFX.loadSettings();
  // Landing page features (always)
  pollLiveBanner();
  setInterval(pollLiveBanner, 3000);
  loadRecentRuns();
  loadGamesLibrary();

  // Local tracker features (admin only, check if elements exist)
  if ($("np-card")) {
    pollSession();
    setInterval(pollSession, 1000);
    setInterval(tickTimer, 100);
    document.addEventListener("keydown", handleKeyShortcut);
  }
}

document.addEventListener("DOMContentLoaded", init);
