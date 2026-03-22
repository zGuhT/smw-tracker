/* ── SMW Tracker — Stats page ── */

const COLORS = {
  accent: "#6dd5fa",
  accentDim: "#3a7a99",
  danger: "#f87171",
  warning: "#fbbf24",
  success: "#4ade80",
  muted: "#7a8ba0",
  text: "#e2e8f0",
  grid: "rgba(42, 53, 68, 0.6)",
};

// Chart.js defaults
Chart.defaults.color = COLORS.muted;
Chart.defaults.borderColor = COLORS.grid;
Chart.defaults.font.family = "'Outfit', system-ui, sans-serif";

function toHours(s) {
  return Number((s / 3600).toFixed(2));
}

function formatDuration(s) {
  if (!s) return "0m";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

async function fetchJson(url) {
  const r = await fetch(url);
  return r.json();
}

// ── Charts ──

async function loadMostPlayed() {
  const data = await fetchJson("/stats/most-played");
  if (!data.length) return;

  new Chart(document.getElementById("chart-most-played"), {
    type: "bar",
    data: {
      labels: data.map((x) => x.game_name),
      datasets: [{
        label: "Hours",
        data: data.map((x) => toHours(x.total_playtime_seconds)),
        backgroundColor: COLORS.accent,
        borderRadius: 4,
        barPercentage: 0.7,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { callback: (v) => Number(v).toFixed(2) + "h" } },
        y: { grid: { display: false } },
      },
    },
  });
}

async function loadDeaths() {
  const data = await fetchJson("/stats/deaths");
  if (!data.length) return;
  const avgDeaths = data.map(x => x.avg_deaths || 0);
  const attempts = data.map(x => x.attempts || 0);

  new Chart(document.getElementById("chart-deaths"), {
    type: "bar",
    data: {
      labels: data.map((x) => x.level),
      datasets: [{
        label: "Deaths",
        data: data.map((x) => x.death_count),
        backgroundColor: COLORS.danger,
        borderRadius: 4,
        barPercentage: 0.7,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterLabel: (ctx) => `Avg per attempt: ${avgDeaths[ctx.dataIndex]}\nAttempts: ${attempts[ctx.dataIndex]}`,
          },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: { grid: { display: false } },
      },
    },
  });
}

async function loadPlaytimeTrend() {
  const data = await fetchJson("/stats/playtime-trend");
  if (!data.length) return;

  new Chart(document.getElementById("chart-playtime"), {
    type: "line",
    data: {
      labels: data.map((x) => x.date),
      datasets: [{
        label: "Hours",
        data: data.map((x) => toHours(x.total_playtime_seconds)),
        borderColor: COLORS.accent,
        backgroundColor: "rgba(109, 213, 250, 0.08)",
        fill: true,
        tension: 0.3,
        pointRadius: 3,
        pointBackgroundColor: COLORS.accent,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: COLORS.grid }, ticks: { callback: (v) => Number(v).toFixed(2) + "h" } },
      },
    },
  });
}

async function loadSessionsPerDay() {
  const data = await fetchJson("/stats/sessions-per-day");
  if (!data.length) return;

  new Chart(document.getElementById("chart-sessions"), {
    type: "bar",
    data: {
      labels: data.map((x) => x.date),
      datasets: [{
        label: "Sessions",
        data: data.map((x) => x.session_count),
        backgroundColor: COLORS.success,
        borderRadius: 4,
        barPercentage: 0.6,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: COLORS.grid }, beginAtZero: true },
      },
    },
  });
}

// ── Recent sessions table ──

async function loadRecentSessions() {
  const data = await fetchJson("/stats/recent-sessions?limit=20");
  const wrap = document.getElementById("recent-sessions-wrap");

  if (!data.length) {
    wrap.innerHTML = '<p class="muted">No sessions recorded yet.</p>';
    return;
  }

  const rows = data
    .map(
      (s) => `
    <tr>
      <td>${s.game_name}</td>
      <td>${s.platform || "—"}</td>
      <td class="mono">${s.start_time?.replace("T", " ").replace("Z", "") || "—"}</td>
      <td class="mono">${formatDuration(s.duration_seconds)}</td>
      <td>${s.is_active ? '<span class="status-badge active">Live</span>' : '<span class="muted">Done</span>'}</td>
    </tr>`
    )
    .join("");

  wrap.innerHTML = `
    <table class="sessions-table">
      <thead>
        <tr>
          <th>Game</th>
          <th>Platform</th>
          <th>Started</th>
          <th>Duration</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ── Init ──

async function init() {
  try {
    await Promise.all([
      loadMostPlayed(),
      loadDeaths(),
      loadPlaytimeTrend(),
      loadSessionsPerDay(),
      loadRecentSessions(),
    ]);
  } catch (err) {
    console.error("Failed to load stats:", err);
  }
}

document.addEventListener("DOMContentLoaded", init);
