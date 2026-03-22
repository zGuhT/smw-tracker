/* ── SMW Tracker — LiveSplit-style home with live timers ── */

const $ = (id) => document.getElementById(id);
const WINDOW_SIZE = 5;

function formatMs(ms) {
  if (ms == null) return "—";
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

// ── State ──
let lastGameName = null;
let cachedMetadata = null;
let lastSessionData = null;
let serverTimeOffset = 0;

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

// ── Session polling (1s) ──
let prevSplitCount = 0;
let prevRunComplete = false;
let prevRunStarted = false;

async function pollSession() {
  try {
    const res = await fetch("/session/current");
    const data = await res.json();
    if (data.server_time) {
      serverTimeOffset = data.server_time - (Date.now() / 1000);
    }

    // Detect sound triggers by comparing with previous state
    if (data.is_active && lastSessionData) {
      const newSplits = (data.splits || []).length;
      const oldSplits = prevSplitCount;
      const pbSplits = data.pb_splits || [];
      const bestSegments = data.best_segments || {};

      // New split completed
      if (newSplits > oldSplits && newSplits > 0) {
        const latestSplit = data.splits[newSplits - 1];
        const pbMs = pbSplits.find(s => s.level_id === latestSplit.level_id)?.split_ms;
        const bestMs = bestSegments[latestSplit.level_id];

        // Gold split check (this split is the new best ever)
        const isGold = bestMs != null && latestSplit.split_ms <= bestMs;

        if (isGold) {
          SFX.play("gold");
        } else if (pbMs != null && latestSplit.split_ms <= pbMs) {
          SFX.play("ahead");
        } else if (pbMs != null) {
          SFX.play("behind");
        }
      }

      // Run complete
      if (data.run_complete && !prevRunComplete) {
        const completedMs = (data.splits || []).reduce((s, x) => s + (x.split_ms || 0), 0);
        if (data.pb_total_ms && completedMs < data.pb_total_ms) {
          SFX.play("pb");
        } else {
          SFX.play("complete");
        }
      }

      // Run started
      if (data.run_start_epoch && !prevRunStarted) {
        SFX.play("start");
      }

      prevSplitCount = newSplits;
      prevRunComplete = !!data.run_complete;
      prevRunStarted = !!data.run_start_epoch;
    } else if (!data.is_active) {
      prevSplitCount = 0;
      prevRunComplete = false;
      prevRunStarted = false;
    }

    lastSessionData = data;
    renderSession(data);
  } catch (err) {
    console.error("Poll failed:", err);
  }
}

// ── Live timer tick (100ms) ──
function tickTimer() {
  const data = lastSessionData;
  if (!data || !data.is_active) return;

  const completedSplits = data.splits || [];
  const completedMs = completedSplits.reduce((sum, s) => sum + (s.split_ms || 0), 0);
  const nowEpoch = (Date.now() / 1000) + serverTimeOffset;
  const delayMs = data.run_delay_ms || 0;
  const isPaused = data.is_paused || false;
  const runComplete = data.run_complete || false;
  const pbSplits = data.pb_splits || [];

  let currentSplitMs = 0;
  let runTimerMs = 0;

  if (runComplete) {
    runTimerMs = completedMs;
  } else if (isPaused && data.paused_at) {
    if (completedSplits.length > 0 && data.current_split_start) {
      currentSplitMs = Math.max(0, (data.paused_at - data.current_split_start) * 1000);
      runTimerMs = completedMs + currentSplitMs;
    } else if (data.run_start_epoch) {
      runTimerMs = (data.paused_at - data.run_start_epoch) * 1000 - delayMs;
      currentSplitMs = Math.max(0, runTimerMs);
    }
  } else if (completedSplits.length > 0 && data.current_split_start) {
    currentSplitMs = Math.max(0, (nowEpoch - data.current_split_start) * 1000);
    runTimerMs = completedMs + currentSplitMs;
  } else if (data.run_start_epoch) {
    const elapsed = (nowEpoch - data.run_start_epoch) * 1000;
    runTimerMs = elapsed - delayMs;
    currentSplitMs = Math.max(0, runTimerMs);
  }

  const runActive = !!data.run_start_epoch;

  // ── Pace calculations ──
  let pbPartial = 0;
  for (let i = 0; i < completedSplits.length && i < pbSplits.length; i++) {
    pbPartial += pbSplits[i].split_ms || 0;
  }
  const currentSplitIdx = completedSplits.length;
  const currentPbMs = currentSplitIdx < pbSplits.length ? (pbSplits[currentSplitIdx].split_ms || 0) : null;
  const completedDiff = completedSplits.length > 0 && pbSplits.length > 0 ? completedMs - pbPartial : null;
  const liveSplitDiff = currentPbMs != null ? currentSplitMs - currentPbMs : null;
  const isAheadOverall = completedDiff != null ? completedDiff <= 0 : null;

  // ── Main timer with dynamic colour ──
  const timerEl = $("np-timer");
  timerEl.className = "ls-timer";
  if (runActive) {
    if (runTimerMs < 0) {
      timerEl.textContent = `\u2212${formatMs(Math.abs(runTimerMs))}`;
      timerEl.classList.add("muted");
    } else {
      timerEl.textContent = formatMs(runTimerMs);
      if (isPaused) {
        timerEl.classList.add("paused");
      } else if (isAheadOverall === true) {
        timerEl.classList.add("timer-ahead");
      } else if (isAheadOverall === false) {
        timerEl.classList.add("timer-behind");
      }
    }
  } else {
    timerEl.textContent = "0:00.00";
    timerEl.classList.add("muted");
  }

  // ── Current split: live time + live diff ──
  const liveSplitEl = $("np-current-split-time");
  const liveDiffEl = $("np-current-split-diff");

  if (liveSplitEl && runActive && !runComplete && runTimerMs >= 0) {
    liveSplitEl.textContent = formatMs(currentSplitMs);
  } else if (liveSplitEl && runActive && runTimerMs < 0) {
    liveSplitEl.textContent = `\u2212${formatMs(Math.abs(runTimerMs))}`;
  }

  if (liveDiffEl && runActive && !runComplete && currentPbMs != null && runTimerMs >= 0) {
    liveDiffEl.textContent = formatDiffMs(liveSplitDiff);
    liveDiffEl.className = `ls-col-diff mono ${liveSplitDiff <= 0 ? "ahead" : "behind"}`;
  } else if (liveDiffEl) {
    liveDiffEl.textContent = "";
    liveDiffEl.className = "ls-col-diff mono";
  }

  // ── Pace text ──
  const pace = $("np-pace");
  if (runComplete) {
    if (data.pb_total_ms && completedMs < data.pb_total_ms) {
      pace.textContent = `\ud83c\udf89 New PB! ${formatDiffMs(completedMs - data.pb_total_ms)}`;
      pace.className = "ls-pace ahead";
    } else if (data.pb_total_ms) {
      pace.textContent = `Run Complete: ${formatDiffMs(completedMs - data.pb_total_ms)}`;
      pace.className = completedMs <= data.pb_total_ms ? "ls-pace ahead" : "ls-pace behind";
    } else {
      pace.textContent = `Run Complete \u2014 ${formatMs(completedMs)}`;
      pace.className = "ls-pace ahead";
    }
  } else if (isPaused && runActive) {
    pace.textContent = "\u23f8 Paused";
    pace.className = "ls-pace muted";
  } else if (completedDiff != null) {
    pace.textContent = `Pace: ${formatDiffMs(completedDiff)}`;
    pace.className = completedDiff <= 0 ? "ls-pace ahead" : "ls-pace behind";
  } else if (runActive && runTimerMs < 0) {
    pace.textContent = "Starting...";
    pace.className = "ls-pace muted";
  } else if (runActive) {
    pace.textContent = "";
    pace.className = "ls-pace muted";
  }

  // ── Buttons ──
  const pauseBtn = $("btn-pause");
  const splitBtn = $("btn-split");
  const undoBtn = $("btn-undo");
  const resetBtn = $("btn-reset");

  if (runComplete) {
    [pauseBtn, splitBtn].forEach(b => { if (b) { b.disabled = true; b.style.opacity = "0.3"; b.style.pointerEvents = "none"; } });
    [undoBtn, resetBtn].forEach(b => { if (b) { b.disabled = false; b.style.opacity = "1"; b.style.pointerEvents = "auto"; } });
  } else {
    [pauseBtn, splitBtn, undoBtn, resetBtn].forEach(b => { if (b) { b.disabled = false; b.style.opacity = "1"; b.style.pointerEvents = "auto"; } });
    if (pauseBtn) {
      if (isPaused) { pauseBtn.textContent = "\u25b6"; pauseBtn.classList.add("active"); }
      else if (runActive) { pauseBtn.textContent = "\u23f8"; pauseBtn.classList.remove("active"); }
      else { pauseBtn.textContent = "\u25b6"; pauseBtn.classList.remove("active"); }
    }
  }
}

function renderSession(data) {
  const empty = $("np-empty");
  const content = $("np-content");
  if (!data || !data.is_active) {
    empty.classList.remove("hidden");
    content.classList.add("hidden");
    lastGameName = null; cachedMetadata = null; lastSessionData = null;
    return;
  }
  empty.classList.add("hidden");
  content.classList.remove("hidden");

  $("np-game-name").textContent = data.game_name || "\u2014";
  const runInfo = data.run_name ? ` \u2014 ${data.run_name}` : "";
  $("np-platform").textContent = (data.platform || "SNES") + runInfo;
  $("np-deaths").textContent = String(data.deaths_this_session ?? 0);
  $("np-level").textContent = data.current_level_name || "\u2014";
  $("np-sob").textContent = data.sum_of_best_ms ? formatMs(data.sum_of_best_ms) : "\u2014";
  $("np-pb").textContent = data.pb_total_ms ? formatMs(data.pb_total_ms) : "\u2014";

  const pace = $("np-pace");
  const runActive = data.run_start_epoch || (data.splits && data.splits.length > 0);
  if (!runActive) { pace.textContent = "Waiting for run start..."; pace.className = "ls-pace muted"; }

  renderSplits(data);

  if (data.game_name && data.game_name !== lastGameName) {
    fetchMetadata(data.game_name).then((meta) => {
      if (meta?.boxart_url) { $("np-boxart").src = meta.boxart_url; $("np-boxart").classList.remove("hidden"); }
      if (meta?.display_name) { $("np-game-name").textContent = meta.display_name; }
    });
  }
  tickTimer();
}

function renderSplits(data) {
  const tbody = $("np-splits-body");
  const completedSplits = data.splits || [];
  const runLevels = data.run_levels || [];
  const pbSplits = data.pb_splits || [];
  const bestSegments = data.best_segments || {};

  const pbLookup = {};
  for (const s of pbSplits) pbLookup[s.level_id] = s.split_ms;
  const completedByLevelId = {};
  for (const s of completedSplits) completedByLevelId[s.level_id] = s;

  const allRows = [];
  if (runLevels.length > 0) {
    for (const rl of runLevels) {
      const completed = completedByLevelId[rl.level_id];
      const pbMs = pbLookup[rl.level_id] ?? null;
      const bestMs = bestSegments[rl.level_id] ?? null;
      if (completed) {
        const diffMs = (pbMs != null && completed.split_ms != null) ? completed.split_ms - pbMs : null;
        const isGold = bestMs != null && completed.split_ms != null && completed.split_ms <= bestMs;
        allRows.push({ levelName: rl.level_name || rl.level_id, splitMs: completed.split_ms, pbMs, diffMs, completed: true, isGold });
      } else {
        allRows.push({ levelName: rl.level_name || rl.level_id, splitMs: null, pbMs, diffMs: null, completed: false, isGold: false });
      }
    }
  } else if (completedSplits.length > 0) {
    for (const split of completedSplits) {
      const pbMs = pbLookup[split.level_id] ?? null;
      const bestMs = bestSegments[split.level_id] ?? null;
      const diffMs = (pbMs != null && split.split_ms != null) ? split.split_ms - pbMs : null;
      const isGold = bestMs != null && split.split_ms != null && split.split_ms <= bestMs;
      allRows.push({ levelName: split.level_name || split.level_id, splitMs: split.split_ms, pbMs, diffMs, completed: true, isGold });
    }
  }

  if (allRows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;padding:16px">No run definition set up. Go to game setup to create one.</td></tr>';
    return;
  }

  let currentIdx = allRows.findIndex(r => !r.completed);
  if (currentIdx === -1) currentIdx = allRows.length;

  const totalRows = allRows.length;
  let windowStart = 0, windowEnd = totalRows;
  if (totalRows > WINDOW_SIZE) {
    const half = Math.floor(WINDOW_SIZE / 2);
    windowStart = Math.max(0, currentIdx - half);
    windowEnd = windowStart + WINDOW_SIZE;
    if (windowEnd > totalRows) { windowEnd = totalRows; windowStart = Math.max(0, windowEnd - WINDOW_SIZE); }
  }

  const visibleRows = allRows.slice(windowStart, windowEnd);
  const html = visibleRows.map((row, idx) => {
    const globalIdx = windowStart + idx;
    const isCurrent = globalIdx === currentIdx;
    const diffClass = row.diffMs == null ? "" : row.diffMs <= 0 ? (row.isGold ? "gold" : "ahead") : "behind";
    const diffText = row.diffMs != null ? formatDiffMs(row.diffMs) : "";
    const rowClass = isCurrent ? "ls-split-row current" : row.completed ? "ls-split-row completed" : "ls-split-row upcoming";
    const goldClass = row.isGold ? " gold" : "";

    let timeCell, diffCell;
    if (row.completed) {
      timeCell = `<td class="ls-col-time mono${goldClass}">${formatMs(row.splitMs)}${row.isGold ? " \u2605" : ""}</td>`;
      diffCell = `<td class="ls-col-diff mono ${diffClass}">${diffText}</td>`;
    } else if (isCurrent) {
      timeCell = `<td class="ls-col-time mono accent" id="np-current-split-time">\u2014</td>`;
      diffCell = `<td class="ls-col-diff mono" id="np-current-split-diff"></td>`;
    } else {
      timeCell = `<td class="ls-col-time mono muted">\u2014</td>`;
      diffCell = `<td class="ls-col-diff mono"></td>`;
    }

    return `<tr class="${rowClass}">
      <td class="ls-col-num mono">${globalIdx + 1}</td>
      <td class="ls-col-name">${row.levelName}</td>
      ${timeCell}
      ${diffCell}
      <td class="ls-col-pb mono muted">${row.pbMs != null ? formatMs(row.pbMs) : "\u2014"}</td>
    </tr>`;
  }).join("");

  const above = windowStart > 0 ? `<tr class="ls-split-indicator"><td colspan="5" class="muted">\u25b2 ${windowStart} more</td></tr>` : "";
  const below = (totalRows - windowEnd) > 0 ? `<tr class="ls-split-indicator"><td colspan="5" class="muted">\u25bc ${totalRows - windowEnd} more</td></tr>` : "";
  tbody.innerHTML = above + html + below;
}

// ── Games Library ──
async function loadGamesLibrary() {
  const wrap = $("games-list");
  try {
    const res = await fetch("/stats/games");
    const games = await res.json();
    if (!games.length) { wrap.innerHTML = '<p class="muted">No games tracked yet.</p>'; return; }
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
  } catch (err) {
    console.error("Failed to load games:", err);
    wrap.innerHTML = '<p class="muted">Failed to load library.</p>';
  }
}

// ── Run Controls ──
async function manualSplit() {
  try {
    const res = await fetch("/run/split", { method: "POST" });
    const data = await res.json();
    if (data.success) pollSession();
  } catch (e) { console.error("Split failed:", e); }
}

async function undoSplit() {
  try {
    const res = await fetch("/run/undo", { method: "POST" });
    const data = await res.json();
    if (data.success) pollSession();
  } catch (e) { console.error("Undo failed:", e); }
}

async function togglePause() {
  try {
    const res = await fetch("/run/pause", { method: "POST" });
    const data = await res.json();
    if (data.success) pollSession();
  } catch (e) { console.error("Pause failed:", e); }
}

async function resetRun() {
  if (!confirm("Reset the current run?\nAll splits will be deleted and the SNES will be soft-reset.")) return;
  try {
    const res = await fetch("/run/reset", { method: "POST" });
    const data = await res.json();
    if (data.success) pollSession();
  } catch (e) { console.error("Reset failed:", e); }
}

// ── Sound Settings ──
function toggleSoundSettings() {
  const el = $("sound-settings");
  const help = $("shortcut-help");
  if (el) el.classList.toggle("hidden");
  if (help) help.classList.toggle("hidden");
}

function saveSoundSettings() {
  SFX.saveSettings();
}

function testSound(type) {
  SFX.play(type);
}

// ── Keyboard Shortcuts ──
const SHORTCUTS = {
  "Numpad1": manualSplit,    // Numpad 1 = Split
  "Numpad2": undoSplit,      // Numpad 2 = Undo
  "Numpad3": togglePause,   // Numpad 3 = Pause/Resume
  "Numpad4": resetRun,      // Numpad 4 = Reset (still shows confirm)
  "Space": manualSplit,      // Space = Split (when not in an input)
  "KeyZ": undoSplit,         // Z = Undo
  "KeyP": togglePause,      // P = Pause/Resume
};

function handleKeyShortcut(e) {
  // Ignore if typing in an input/textarea
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  const fn = SHORTCUTS[e.code];
  if (fn) {
    e.preventDefault();
    fn();
  }
}

// ── Init ──
function init() {
  SFX.loadSettings();
  pollSession();
  setInterval(pollSession, 1000);
  setInterval(tickTimer, 100);
  loadGamesLibrary();
  document.addEventListener("keydown", handleKeyShortcut);
}

document.addEventListener("DOMContentLoaded", init);
