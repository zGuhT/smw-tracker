# SMW Tracker v1.0.0

Real-time SNES speedrun tracker. Connects to your SNES hardware via [QUsb2Snes](https://github.com/Skarsnik/QUsb2snes), automatically tracks splits, deaths, and level progress, and streams everything live to [smwtracker.com](https://smwtracker.com).

## Features

- **Automatic split tracking** — detects level entries, exits, keyhole activations, and deaths by reading SNES memory 4 times per second
- **Live streaming** — your run data syncs to the cloud in real-time so anyone can watch at `smwtracker.com/u/yourname`
- **Personal stats** — PBs, sum of best, death heatmaps, playtime trends, and run history on your profile
- **Community configs** — share and import level/run definitions so nobody has to set up the same game twice
- **Multi-user** — each user has their own profile, stats, and API key
- **Works with any SMW ROM hack** — the tracker reads memory addresses that are consistent across SMW-based hacks

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/zGuhT/smw-tracker.git
cd smw-tracker

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create an account at smwtracker.com and get your API key

# 4. Make sure QUsb2Snes is running and your SNES is connected

# 5. Start the tracker
python run_tracker.py --cloud --api-key YOUR_API_KEY
```

## How It Works

1. The tracker connects to QUsb2Snes (which talks to your SD2SNES/FXPak Pro or emulator)
2. It reads SNES memory addresses to detect game state: current level, game mode, death counter, keyhole activation, exit flags
3. When you complete a level, the split time and death count are recorded
4. Session data pushes to `smwtracker.com` every 500ms so viewers see your run live
5. Stats, PBs, and split history are saved to your profile

## Game Setup

Before your first run of a game, you need to define the levels and run order. You can do this at `smwtracker.com/game/YOUR_GAME/setup` or check if someone has already published a community config.

Each level needs:
- A **name** (e.g. "Happy Birthday")
- A **Level ID** — the 2-character hex code from the ROM (e.g. `0A`). You can find these in Lunar Magic or use the "Capture from Hardware" button while standing in the level
- Whether it has a **secret exit** (keyhole)

Then create a **run definition** — an ordered list of levels for your speedrun category (100%, Any%, etc.) with a start delay.

## Running Locally (Development)

```bash
# Start the web server
uvicorn api.server:app --host 0.0.0.0 --port 8000

# In another terminal, start the hardware tracker (local mode, no cloud sync)
python run_tracker.py

# Or with cloud sync
python run_tracker.py --cloud --api-key YOUR_API_KEY
```

The local web UI is at `http://localhost:8000` and includes the full dashboard, stats, setup pages, and a stream overlay.

## Project Structure

```
smw-tracker/
├── api/                    # FastAPI web server
│   ├── server.py           # App setup, middleware, lifespan
│   └── routes/
│       ├── auth.py         # Registration, login, email verification
│       ├── community.py    # Shared game config publish/import/verify
│       ├── export.py       # Config export/import (JSON)
│       ├── levels.py       # Level CRUD
│       ├── live.py         # Live push, SSE streaming, session sync
│       ├── runs.py         # Run definition CRUD
│       ├── session.py      # Session start/stop
│       ├── stats.py        # Aggregated stats queries
│       └── users.py        # User management
├── core/                   # Business logic
│   ├── db.py               # Dual SQLite/Postgres with migrations
│   ├── auth_service.py     # Password hashing, tokens, web sessions
│   ├── email_service.py    # Resend API email delivery
│   ├── session_service.py  # Session lifecycle + payload builder
│   ├── splits_service.py   # PB, SOB, best segments
│   ├── stats_service.py    # User-scoped stats queries
│   ├── user_service.py     # User CRUD
│   └── export_service.py   # Game config export/import
├── hardware/               # SNES hardware interface
│   ├── qusb_client.py      # QUsb2Snes WebSocket client
│   ├── smw_tracker.py      # State machine: level detection, splits, deaths
│   ├── smw_memory_map.py   # SNES memory addresses
│   ├── cloud_client.py     # Cloud sync (push to smwtracker.com)
│   └── tracker_client.py   # TrackerClient interface
├── ui/                     # Web frontend
│   ├── routes.py           # Page routes (landing, profile, game, setup, account)
│   ├── templates/          # Jinja2 HTML templates
│   └── static/             # CSS, JS
├── run_tracker.py          # Entry point for the hardware tracker
├── migrate_to_cloud.py     # Migrate local SQLite data to cloud Postgres
├── setup_user.py           # CLI tool to create users
└── requirements.txt
```

## Cloud Deployment

The web server runs on [Railway](https://railway.app) with PostgreSQL. Environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | Postgres connection string (set by Railway) |
| `RESEND_API_KEY` | Yes | [Resend](https://resend.com) API key for transactional email |
| `EMAIL_FROM` | No | From address (default: `SMW Tracker <noreply@smwtracker.com>`) |
| `BASE_URL` | No | Public URL (default: `https://smwtracker.com`) |
| `SMW_ADMIN_KEY` | No | Admin access key for debug endpoints |
| `TURNSTILE_SITE_KEY` | No | Cloudflare Turnstile captcha (registration) |
| `TURNSTILE_SECRET_KEY` | No | Cloudflare Turnstile secret |

## CLI Options

```
python run_tracker.py [options]

  --cloud              Enable cloud sync to smwtracker.com
  --api-key KEY        Your API key (from smwtracker.com/account)
  --api-url URL        Cloud server URL (default: https://smwtracker.com)
  --poll SECONDS       Hardware polling interval (default: 0.25)
  --qusb-url URL       QUsb2Snes WebSocket URL (default: ws://127.0.0.1:23074)
  --http               Use HTTP mode instead of direct service calls
  --verbose            Enable debug logging
```

## License

MIT
