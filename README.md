# SFC Tracker

Real-time Super Famicom / SNES game tracker. Reads console memory via QUsb2Snes,
tracks play sessions, deaths, level progress, and serves a live dashboard.

## Project Structure

```
sfc-tracker/
├── api/
│   ├── server.py              # FastAPI app (lifespan-based startup)
│   └── routes/
│       ├── session.py         # /session/* endpoints
│       ├── tracking.py        # /tracking/* endpoints
│       ├── stats.py           # /stats/* endpoints (including /deaths, /recent-sessions)
│       └── metadata.py        # /metadata/lookup endpoint
├── core/
│   ├── db.py                  # SQLite with WAL mode, thread-local connections
│   ├── time_utils.py          # Shared UTC/ISO helpers
│   ├── models.py              # Pydantic request/response models
│   ├── rom_utils.py           # ROM path cleaning and title normalization
│   ├── smw_levels.py          # Level ID → name lookup
│   ├── session_service.py     # Session lifecycle (atomic create)
│   ├── tracking_service.py    # Event and progress recording
│   ├── stats_service.py       # SQL-aggregated stats queries
│   └── metadata_service.py    # Game metadata: cache → overrides → TheGamesDB
├── hardware/
│   ├── qusb_client.py         # QUsb2Snes WebSocket client (with reconnection)
│   ├── smw_memory_map.py      # SNES memory addresses
│   ├── tracker_client.py      # TrackerClient interface (Direct + HTTP variants)
│   └── smw_tracker.py         # Hardware polling state machine
├── ui/
│   ├── routes.py              # HTML page routes
│   ├── templates/
│   │   ├── home.html          # Now Playing dashboard
│   │   └── stats.html         # Stats & charts page
│   └── static/
│       ├── css/app.css        # Dark theme stylesheet
│       └── js/
│           ├── home.js        # Session polling + metadata integration
│           └── stats.js       # Chart.js visualizations
├── data/
│   ├── game_overrides.json    # Manual metadata for ROM hacks
│   └── smw_levels.json        # Level ID → name mapping
├── run_tracker.py             # Hardware poller entry point
└── requirements.txt
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start the web server
uvicorn api.server:app --host 0.0.0.0 --port 8000

# In another terminal, start the hardware tracker
python run_tracker.py
```

## Key Improvements Over Original

### Database
- **WAL journal mode** — allows concurrent reads/writes without "database is locked" errors
- **Thread-local connections** — reuses connections per thread instead of creating new ones every call
- **`busy_timeout = 5000`** — SQLite waits up to 5s for locks instead of failing immediately
- **Shared `db` module** with `fetchone()`, `fetchall()`, `execute()`, `commit()` helpers

### Architecture
- **Direct service calls** — the hardware tracker calls `record_event()` / `record_progress()` directly
  instead of making HTTP requests to localhost. This eliminates ~4 HTTP round-trips per second.
  The `TrackerClient` interface lets you switch between direct and HTTP modes:
  ```bash
  python run_tracker.py           # Direct (default, recommended)
  python run_tracker.py --http    # HTTP mode for split deployments
  ```
- **Atomic session creation** — `get_or_create_active_session()` uses a single transaction to
  prevent duplicate active sessions from race conditions
- **Lifespan context manager** — replaces deprecated `@app.on_event("startup")`

### Stats Queries
- **SQL aggregation** — `get_most_played_games()`, `get_playtime_trend()`, etc. use
  `SUM`/`GROUP BY`/`julianday()` in SQL instead of fetching all rows and looping in Python
- **New endpoints** — `/stats/deaths` (deaths by level) and `/stats/recent-sessions`

### Hardware Tracker
- **Automatic reconnection** — if QUsb2Snes drops, the tracker waits and reconnects
  instead of crashing
- **Proper logging** — uses Python `logging` module instead of print statements
- **Configurable thresholds** — `TrackerConfig` dataclass for all tuneable values
- **CLI arguments** — `--poll`, `--verbose`, `--qusb-url`, `--http`, `--api-url`

### Frontend
- **Fixed duplicate element IDs** — the original had `np-game` and `np-platform` appearing twice
- **Metadata integration wired up** — box art, overview, and display name now actually render
  when a session is active (was defined but never called in the original)
- **Death stats chart** — shows deaths per level on the stats page
- **Recent sessions table** — shows the last 20 sessions with duration and status
- **Themed Chart.js** — charts use the app's color palette instead of Chart.js defaults
- **Live status badge** — animated green dot for active sessions

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/session/start` | Start a new session |
| POST | `/session/stop` | Stop the active session |
| GET | `/session/current` | Get current session with progress |
| POST | `/tracking/event` | Record a game event (death, exit, etc.) |
| POST | `/tracking/progress` | Record a progress snapshot |
| GET | `/stats/most-played` | Games ranked by total playtime |
| GET | `/stats/playtime-trend` | Daily playtime totals |
| GET | `/stats/sessions-per-day` | Session count per day |
| GET | `/stats/deaths` | Death count by level |
| GET | `/stats/recent-sessions` | Most recent sessions |
| GET | `/metadata/lookup?rom_path=...` | Look up game metadata |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TGDB_API_KEY` | TheGamesDB API key for automatic metadata lookup |
