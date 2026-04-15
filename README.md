# Agent Tracker

A personal dashboard for tracking AI agent sessions across **Cursor** and **Claude**. Automatically scrapes session data from both tools' local storage, shows activity over time, and computes an effort/complexity score per session.

![Dashboard](https://img.shields.io/badge/Next.js-14-black) ![Tailwind](https://img.shields.io/badge/Tailwind-4-06B6D4) ![Python](https://img.shields.io/badge/Python-3.9+-3776AB)

## What it does

- **Scrapes Cursor sessions** from local SQLite databases (`state.vscdb`) -- extracts session names, timestamps, mode (agent/chat/plan), lines added/removed, files changed, and context usage
- **Scrapes Claude Cowork sessions** from local `audit.jsonl` files -- extracts titles, tool usage, message counts
- **Computes effort scores** (0-100) per session based on code churn, file spread, and context consumption
- **Real-time watcher daemon** that polls both sources every 15-30 seconds and pushes changes
- **Dark-themed dashboard** with stat cards, 7-day activity chart, radial effort gauge, and filterable session table
- **Deploys to Vercel** as a read-only snapshot of your data

## Prerequisites

- **Node.js** 18+ and npm
- **Python** 3.9+ (no pip dependencies needed -- uses only stdlib)
- **Cursor** IDE installed (for Cursor session scraping)
- **Claude Desktop** with Cowork/local agent mode (for Claude session scraping)

## Quick Start

### 1. Install and run locally

```bash
git clone https://github.com/haigbd/agent-tracker.git
cd agent-tracker
npm install
npm run dev
```

Dashboard opens at [http://localhost:3000](http://localhost:3000).

### 2. Populate with your data

Run the one-time scrapers to pull existing sessions:

```bash
# Scrape all Cursor sessions and push to the dashboard
python3 scripts/cursor-scraper.py --push http://localhost:3000

# Scrape all Claude Cowork sessions and push to the dashboard
python3 scripts/claude-scraper.py --push http://localhost:3000
```

Your dashboard should now show all historical sessions from both tools.

### 3. Enable real-time sync

The watcher daemon monitors both Cursor and Claude for new sessions and pushes them automatically:

```bash
# Foreground (good for testing)
python3 scripts/cursor-watcher.py http://localhost:3000 --interval 15

# Background (daemonize)
python3 scripts/cursor-watcher.py http://localhost:3000 --interval 15 --daemon

# Cursor only (skip Claude scanning)
python3 scripts/cursor-watcher.py http://localhost:3000 --no-claude
```

The watcher scans Cursor every poll cycle and Claude every 4th cycle (~2 minutes at 15s intervals).

### 4. Auto-start on login (macOS)

Install as a macOS LaunchAgent so it starts automatically:

```bash
./scripts/manage-watcher.sh install
```

Other commands:

```bash
./scripts/manage-watcher.sh status     # Check if running
./scripts/manage-watcher.sh logs       # Tail the watcher log
./scripts/manage-watcher.sh stop       # Stop the watcher
./scripts/manage-watcher.sh uninstall  # Remove the LaunchAgent
```

> **Note**: Edit `scripts/com.agent-tracker.cursor-watcher.plist` to change the API URL if you're not using `http://localhost:3000`.

## Deploy to Vercel

The Vercel deployment serves a **read-only snapshot** of your data. The `data/runs.json` file is baked into the deployment at build time.

```bash
# First time: link the project
npx vercel link

# Set read-only mode
npx vercel env add DATA_MODE production
# Enter: static

# Deploy
npx vercel deploy --prod
```

To update the Vercel dashboard with fresh data:

```bash
# Re-scrape locally, then redeploy
python3 scripts/cursor-scraper.py --push http://localhost:3000
python3 scripts/claude-scraper.py --push http://localhost:3000
npx vercel deploy --prod
```

## How It Works

### Data Sources

| Tool | Location (macOS) | Format |
|------|-----------------|--------|
| Cursor | `~/Library/Application Support/Cursor/User/workspaceStorage/*/state.vscdb` | SQLite `ItemTable` with JSON blobs in `composer.composerData` |
| Cursor (global) | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` | Same as above |
| Claude Cowork | `~/Library/Application Support/Claude/local-agent-mode-sessions/**/audit.jsonl` | JSONL with message/tool_use/tool_result events |

Linux paths use `~/.config/Cursor/` and `~/.config/Claude/` respectively. Windows uses `%APPDATA%`.

### Effort Score

Each Cursor session gets a complexity score (0-100) computed as:

```
effort = clamp(0, 100,
  (linesAdded + linesRemoved) * 0.3     // code churn
  + filesChanged * 8                     // spread across files
  + contextUsagePercent * 0.4            // context window consumption
)
```

- Green (< 30): Light touch -- quick chats, simple edits
- Yellow (30-60): Moderate -- multi-file changes, decent context usage
- Red (> 60): Heavy -- large refactors, many files, high context usage

### Architecture

```
┌─────────────────────────────────────────────────────┐
│  cursor-watcher.py (daemon)                         │
│  ├── Polls Cursor SQLite DBs every 15s              │
│  └── Polls Claude audit.jsonl every ~2min           │
│       ↓ POST /api/runs                              │
├─────────────────────────────────────────────────────┤
│  Next.js App (localhost:3000)                       │
│  ├── GET  /api/runs  → reads data/runs.json         │
│  ├── POST /api/runs  → upserts sessions             │
│  └── Dashboard (React + Tailwind)                   │
│       ├── Stat cards (Today, Running, Claude, etc.) │
│       ├── 7-day stacked bar chart                   │
│       ├── Radial effort gauge                       │
│       └── Filterable session table                  │
├─────────────────────────────────────────────────────┤
│  Vercel (read-only snapshot)                        │
│  └── Same app, DATA_MODE=static rejects writes      │
└─────────────────────────────────────────────────────┘
```

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/runs` | Returns `{ runs: [...] }` |
| `POST` | `/api/runs` | Upsert one run or an array of runs |
| `DELETE` | `/api/runs?id=xxx` | Delete a specific run |
| `DELETE` | `/api/runs` | Clear all runs |

### Run Schema

```json
{
  "id": "a1b2c3d4",
  "tool": "cursor",
  "task": "Refactor auth module",
  "time": "2025-04-14T15:30",
  "status": "done",
  "workspace": "cred-api-commercial",
  "mode": "agent",
  "linesAdded": 142,
  "linesRemoved": 38,
  "filesChanged": 5,
  "contextUsagePercent": 62.5,
  "subtitle": "Edited auth.ts, middleware.ts, routes.ts"
}
```

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `scripts/cursor-scraper.py` | One-time scrape of all Cursor sessions |
| `scripts/claude-scraper.py` | One-time scrape of all Claude Cowork sessions |
| `scripts/cursor-watcher.py` | Real-time daemon that watches both Cursor and Claude |
| `scripts/manage-watcher.sh` | Install/manage the macOS LaunchAgent |
| `scripts/claude-sync.sh` | Legacy: sync via Claude CLI (if available) |

## Caveats

- **Cursor's SQLite schema is undocumented** and can change between updates. The scraper handles the known keys (`composer.composerData` with `allComposers`) but may need adjustment after major Cursor updates.
- **Claude Cowork session files** are local to the machine running Claude Desktop. The scraper reads `audit.jsonl` files which contain the full conversation log.
- **Vercel deployment is a snapshot** -- it shows whatever was in `data/runs.json` at deploy time. Redeploy to refresh.
- **Data is local** -- `data/runs.json` is a plain JSON file. No database, no cloud storage. Back it up if you care about it.

## License

MIT
