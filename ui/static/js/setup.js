/* ── SMW Tracker — Game Setup page ── */

const GAME_NAME = window.GAME_NAME;
const $ = (id) => document.getElementById(id);

let gameLevels = [];
let gameRuns = [];

async function init() {
  $("page-title").textContent = `Setup: ${GAME_NAME}`;
  $("back-link").href = `/game/${encodeURIComponent(GAME_NAME)}`;
  await loadLevels();
  await loadRuns();
}

// ══════════════════════════════════════
// LEVELS
// ══════════════════════════════════════

async function loadLevels() {
  const res = await fetch(`/levels/${encodeURIComponent(GAME_NAME)}`);
  gameLevels = await res.json();
  renderLevels();
}

function renderLevels() {
  const wrap = $("levels-list");
  if (!gameLevels.length) {
    wrap.innerHTML = '<p class="muted text-sm">No levels defined yet.</p>';
    return;
  }
  wrap.innerHTML = gameLevels.map(lv => `
    <div class="setup-item" data-level-id="${lv.id}">
      <div class="setup-item-main">
        <span class="setup-item-name">${lv.level_name}</span>
        <span class="setup-item-badge mono">${lv.level_id || '—'}</span>
        ${lv.has_secret_exit ? '<span class="setup-item-badge secret">Secret Exit</span>' : ''}
      </div>
      <div class="setup-item-actions">
        <button onclick="captureLevel(${lv.id})" class="btn-sm" title="Read level ID from hardware">Capture</button>
        <button onclick="promptEditLevel(${lv.id})" class="btn-sm">Edit</button>
        <button onclick="removeLevel(${lv.id})" class="btn-sm btn-danger">Delete</button>
      </div>
    </div>
  `).join("");
}

async function addLevel() {
  const name = $("new-level-name").value.trim();
  if (!name) return;
  const levelId = $("new-level-id").value.trim() || null;
  const secret = $("new-level-secret").checked;
  await fetch("/levels/", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({game_name: GAME_NAME, level_name: name, level_id: levelId, has_secret_exit: secret}),
  });
  $("new-level-name").value = "";
  $("new-level-id").value = "";
  $("new-level-secret").checked = false;
  await loadLevels();
  await loadRuns();
}

async function removeLevel(id) {
  if (!confirm("Delete this level? It will also be removed from any runs.")) return;
  await fetch(`/levels/${id}`, {method: "DELETE"});
  await loadLevels();
  await loadRuns();
}

async function captureLevel(id) {
  try {
    const res = await fetch(`/levels/${id}/capture`, {method: "POST"});
    if (!res.ok) {
      const err = await res.json();
      alert(`Capture failed: ${err.detail || "Unknown error"}`);
      return;
    }
    const data = await res.json();
    alert(`Captured level ID: ${data.level_id}`);
    await loadLevels();
  } catch (e) {
    alert(`Capture failed: ${e.message}`);
  }
}

async function promptEditLevel(id) {
  const lv = gameLevels.find(l => l.id === id);
  if (!lv) return;
  const newName = prompt("Level name:", lv.level_name);
  if (newName === null) return;
  const newLid = prompt("Level ID (hex):", lv.level_id || "");
  if (newLid === null) return;
  const newSecret = confirm("Does this level have a secret exit?");
  await fetch(`/levels/${id}`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({level_name: newName, level_id: newLid || null, has_secret_exit: newSecret}),
  });
  await loadLevels();
  await loadRuns();
}

// ══════════════════════════════════════
// RUNS
// ══════════════════════════════════════

async function loadRuns() {
  const res = await fetch(`/runs/game/${encodeURIComponent(GAME_NAME)}`);
  gameRuns = await res.json();
  renderRuns();
}

function buildExitTypeSelect(runId, level) {
  // Only show secret option if the game_level has_secret_exit
  if (!level.has_secret_exit) {
    return `<span class="setup-item-badge">normal</span>`;
  }
  return `<select id="add-level-exit-${runId}" class="setup-input setup-input-sm">
    <option value="normal">Normal</option>
    <option value="secret">Secret</option>
  </select>`;
}

function renderRuns() {
  const wrap = $("runs-list");
  if (!gameRuns.length) {
    wrap.innerHTML = '<p class="muted text-sm">No runs defined yet.</p>';
    return;
  }

  // Build level options with secret info
  const levelOptions = gameLevels.map(lv =>
    `<option value="${lv.id}" data-secret="${lv.has_secret_exit ? 1 : 0}">${lv.level_name} (${lv.level_id || '?'})</option>`
  ).join("");

  wrap.innerHTML = gameRuns.map(run => `
    <div class="run-card card" style="padding:16px; margin-bottom:14px">
      <div class="run-card-header">
        <div>
          <span class="run-card-name">${run.run_name}</span>
          ${run.is_default ? '<span class="setup-item-badge default">Default</span>' : ''}
          ${run.start_delay_ms > 0 ? `<span class="setup-item-badge muted">Delay: ${run.start_delay_ms}ms</span>` : ''}
        </div>
        <div class="setup-item-actions">
          <button onclick="addAllLevelsToRun(${run.id})" class="btn-sm">Add All Levels</button>
          <button onclick="editRunSettings(${run.id})" class="btn-sm">Settings</button>
          ${!run.is_default ? `<button onclick="setDefault(${run.id})" class="btn-sm">Set Default</button>` : ''}
          <button onclick="removeRun(${run.id})" class="btn-sm btn-danger">Delete</button>
        </div>
      </div>

      <!-- Add level form ABOVE the list -->
      <div class="run-add-level" style="margin-bottom:12px; display:flex; gap:8px; align-items:center; flex-wrap:wrap">
        <select id="add-level-select-${run.id}" class="setup-input setup-input-sm"
                onchange="onLevelSelectChange(${run.id})">
          <option value="">Add level...</option>
          ${levelOptions}
        </select>
        <span id="exit-type-wrap-${run.id}"></span>
        <button onclick="addLevelToRun(${run.id})" class="btn-sm primary">Add</button>
      </div>

      <div class="run-levels-editor" id="run-levels-${run.id}">
        <p class="muted text-sm">Loading...</p>
      </div>
    </div>
  `).join("");

  gameRuns.forEach(run => loadRunLevels(run.id));
}

function onLevelSelectChange(runId) {
  const select = document.getElementById(`add-level-select-${runId}`);
  const exitWrap = document.getElementById(`exit-type-wrap-${runId}`);
  const selectedOption = select.options[select.selectedIndex];

  if (!selectedOption || !selectedOption.value) {
    exitWrap.innerHTML = "";
    return;
  }

  const hasSecret = selectedOption.dataset.secret === "1";
  if (hasSecret) {
    exitWrap.innerHTML = `<select id="add-level-exit-${runId}" class="setup-input setup-input-sm">
      <option value="normal">Normal Exit</option>
      <option value="secret">Secret Exit</option>
    </select>`;
  } else {
    exitWrap.innerHTML = `<input type="hidden" id="add-level-exit-${runId}" value="normal">
      <span class="setup-item-badge">Normal Exit</span>`;
  }
}

async function loadRunLevels(runId) {
  const res = await fetch(`/runs/${runId}`);
  const data = await res.json();
  const levels = data.levels || [];
  renderRunLevels(runId, levels);
}

function renderRunLevels(runId, levels) {
  const wrap = document.getElementById(`run-levels-${runId}`);
  if (!levels.length) {
    wrap.innerHTML = '<p class="muted text-sm">No levels in this run yet. Use "Add All Levels" or add individually above.</p>';
    return;
  }

  wrap.innerHTML = `<div class="run-sortable" id="sortable-${runId}">
    ${levels.map((lv, idx) => `
      <div class="run-level-item" draggable="true" data-run-level-id="${lv.id}" data-idx="${idx}">
        <span class="drag-handle">☰</span>
        <span class="run-level-order">${idx + 1}</span>
        <span class="run-level-name">${lv.level_name}</span>
        <span class="setup-item-badge mono">${lv.level_id || '?'}</span>
        ${lv.exit_type === 'secret' ? '<span class="setup-item-badge secret">Secret</span>' : '<span class="setup-item-badge">Normal</span>'}
        <button onclick="removeLevelFromRun(${runId}, ${lv.id})" class="btn-sm btn-danger" style="margin-left:auto">✕</button>
      </div>
    `).join("")}
  </div>`;

  setupDragDrop(runId, levels);
}

function setupDragDrop(runId) {
  const container = document.getElementById(`sortable-${runId}`);
  if (!container) return;
  let dragSrc = null;

  container.querySelectorAll(".run-level-item").forEach(item => {
    item.addEventListener("dragstart", (e) => {
      dragSrc = item;
      item.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
    });
    item.addEventListener("dragend", () => {
      item.classList.remove("dragging");
      dragSrc = null;
    });
    item.addEventListener("dragover", (e) => {
      e.preventDefault();
      const rect = item.getBoundingClientRect();
      const mid = rect.top + rect.height / 2;
      item.classList.toggle("drag-above", e.clientY < mid);
      item.classList.toggle("drag-below", e.clientY >= mid);
    });
    item.addEventListener("dragleave", () => {
      item.classList.remove("drag-above", "drag-below");
    });
    item.addEventListener("drop", async (e) => {
      e.preventDefault();
      item.classList.remove("drag-above", "drag-below");
      if (!dragSrc || dragSrc === item) return;
      const rect = item.getBoundingClientRect();
      const mid = rect.top + rect.height / 2;
      if (e.clientY < mid) {
        container.insertBefore(dragSrc, item);
      } else {
        container.insertBefore(dragSrc, item.nextSibling);
      }
      await saveRunOrder(runId);
    });
  });
}

async function saveRunOrder(runId) {
  const container = document.getElementById(`sortable-${runId}`);
  const items = container.querySelectorAll(".run-level-item");
  const res = await fetch(`/runs/${runId}`);
  const data = await res.json();
  const currentLevels = data.levels || [];
  const lookup = {};
  currentLevels.forEach(lv => { lookup[lv.id] = lv; });

  const newOrder = [];
  items.forEach((item, idx) => {
    const rlId = parseInt(item.dataset.runLevelId);
    const lv = lookup[rlId];
    if (lv) newOrder.push({game_level_id: lv.game_level_id, exit_type: lv.exit_type, sort_order: idx});
  });

  await fetch(`/runs/${runId}/levels`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({levels: newOrder}),
  });
  await loadRunLevels(runId);
}

async function addLevelToRun(runId) {
  const select = document.getElementById(`add-level-select-${runId}`);
  const exitEl = document.getElementById(`add-level-exit-${runId}`);
  const gameLevelId = parseInt(select.value);
  if (!gameLevelId) return;
  const exitType = exitEl ? exitEl.value : "normal";

  const res = await fetch(`/runs/${runId}`);
  const data = await res.json();
  const currentLevels = data.levels || [];
  const newLevels = currentLevels.map((lv, idx) => ({
    game_level_id: lv.game_level_id, exit_type: lv.exit_type, sort_order: idx,
  }));
  newLevels.push({game_level_id: gameLevelId, exit_type: exitType, sort_order: newLevels.length});

  await fetch(`/runs/${runId}/levels`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({levels: newLevels}),
  });
  select.value = "";
  const exitWrap = document.getElementById(`exit-type-wrap-${runId}`);
  if (exitWrap) exitWrap.innerHTML = "";
  await loadRunLevels(runId);
}

async function addAllLevelsToRun(runId) {
  // Add all game levels to the run in their current order, normal exit by default
  const res = await fetch(`/runs/${runId}`);
  const data = await res.json();
  const currentLevels = data.levels || [];

  // Start from existing levels
  const newLevels = currentLevels.map((lv, idx) => ({
    game_level_id: lv.game_level_id, exit_type: lv.exit_type, sort_order: idx,
  }));

  // Find which game levels aren't already in the run
  const existingIds = new Set(currentLevels.map(lv => lv.game_level_id));
  let order = newLevels.length;
  for (const gl of gameLevels) {
    if (!existingIds.has(gl.id)) {
      newLevels.push({game_level_id: gl.id, exit_type: "normal", sort_order: order++});
      // If level has secret exit, also add the secret version
      if (gl.has_secret_exit) {
        newLevels.push({game_level_id: gl.id, exit_type: "secret", sort_order: order++});
      }
    }
  }

  await fetch(`/runs/${runId}/levels`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({levels: newLevels}),
  });
  await loadRunLevels(runId);
}

async function removeLevelFromRun(runId, runLevelId) {
  const res = await fetch(`/runs/${runId}`);
  const data = await res.json();
  const currentLevels = (data.levels || []).filter(lv => lv.id !== runLevelId);
  const newLevels = currentLevels.map((lv, idx) => ({
    game_level_id: lv.game_level_id, exit_type: lv.exit_type, sort_order: idx,
  }));
  await fetch(`/runs/${runId}/levels`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({levels: newLevels}),
  });
  await loadRunLevels(runId);
}

async function addRun() {
  const name = $("new-run-name").value.trim();
  if (!name) return;
  const delay = parseInt($("new-run-delay").value) || 0;
  const isDefault = $("new-run-default").checked;
  await fetch("/runs/", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({game_name: GAME_NAME, run_name: name, is_default: isDefault, start_delay_ms: delay}),
  });
  $("new-run-name").value = "";
  $("new-run-delay").value = "0";
  $("new-run-default").checked = false;
  await loadRuns();
}

async function removeRun(runId) {
  if (!confirm("Delete this run definition?")) return;
  await fetch(`/runs/${runId}`, {method: "DELETE"});
  await loadRuns();
}

async function setDefault(runId) {
  await fetch(`/runs/${runId}`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({is_default: true}),
  });
  await loadRuns();
}

async function editRunSettings(runId) {
  const run = gameRuns.find(r => r.id === runId);
  if (!run) return;
  const newName = prompt("Run name:", run.run_name);
  if (newName === null) return;
  const newDelay = prompt("Start delay (ms):", run.start_delay_ms);
  if (newDelay === null) return;
  await fetch(`/runs/${runId}`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({run_name: newName, start_delay_ms: parseInt(newDelay) || 0}),
  });
  await loadRuns();
}

// ══════════════════════════════════════
// EXPORT / IMPORT
// ══════════════════════════════════════

async function exportConfig() {
  try {
    const res = await fetch(`/export/game/${encodeURIComponent(GAME_NAME)}`);
    const data = await res.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${GAME_NAME.replace(/[^a-zA-Z0-9]/g, "_")}_config.json`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert(`Export failed: ${e.message}`);
  }
}

async function importConfig(event) {
  const file = event.target.files[0];
  if (!file) return;

  try {
    const text = await file.text();
    const data = JSON.parse(text);
    const res = await fetch(`/export/import/json?overwrite=false`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(data),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({error: res.statusText}));
      alert(`Import failed: ${err.error || err.detail || res.statusText}`);
      return;
    }

    const result = await res.json();
    const imported = result.imported || [];
    if (imported.length === 0) {
      alert("Nothing was imported. Check the file format.");
      return;
    }
    const summary = imported.map(r =>
      `${r.game_name}: ${r.levels_created} levels created (${r.levels_skipped} skipped), ${r.runs_created} runs created (${r.runs_skipped} skipped)`
    ).join("\n");
    alert(`Import complete:\n${summary}`);
    await loadLevels();
    await loadRuns();
  } catch (e) {
    alert(`Import failed: ${e.message}`);
  }
  event.target.value = "";
}

document.addEventListener("DOMContentLoaded", init);
