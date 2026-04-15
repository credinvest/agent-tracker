#!/usr/bin/env python3
"""
Real-time Cursor session watcher daemon.

Monitors Cursor's SQLite databases for changes and pushes new sessions
to the Agent Tracker API automatically.

Usage:
  python cursor-watcher.py http://localhost:3000           # Watch + push (foreground)
  python cursor-watcher.py http://localhost:3000 --daemon   # Daemonize (background)
  python cursor-watcher.py http://localhost:3000 --interval 10  # Poll every 10s
"""

import sqlite3
import json
import os
import sys
import time
import signal
import hashlib
import argparse
import platform
from pathlib import Path
from datetime import datetime

CACHE_FILE = Path(__file__).parent.parent / 'data' / '.cursor-watcher-cache.json'
PID_FILE = Path(__file__).parent.parent / 'data' / '.cursor-watcher.pid'

def get_cursor_base_path():
    system = platform.system()
    if system == 'Darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Cursor' / 'User'
    elif system == 'Linux':
        return Path.home() / '.config' / 'Cursor' / 'User'
    elif system == 'Windows':
        return Path(os.environ.get('APPDATA', '')) / 'Cursor' / 'User'
    raise RuntimeError(f'Unsupported platform: {system}')

def read_vscdb(db_path):
    if not db_path.exists():
        return {}
    results = {}
    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT key, value FROM ItemTable WHERE "
            "key LIKE '%composer%' OR key LIKE '%chat%' OR key LIKE '%aichat%'"
        )
        for key, value in cursor.fetchall():
            try:
                results[key] = json.loads(value) if isinstance(value, str) else value
            except (json.JSONDecodeError, TypeError):
                results[key] = value
        conn.close()
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        log(f'Warning reading {db_path.name}: {e}')
    return results

def extract_session(comp, workspace_name=None, workspace_path=None):
    title = (
        comp.get('name') or comp.get('title') or
        comp.get('query', '')[:80] or comp.get('text', '')[:80] or ''
    )
    if not title:
        messages = comp.get('messages', comp.get('conversation', []))
        if isinstance(messages, list) and messages:
            first = messages[0]
            if isinstance(first, dict):
                title = (first.get('text', '') or first.get('content', ''))[:80]
    if not title.strip():
        return None

    created = comp.get('createdAt') or comp.get('timestamp') or comp.get('startTime')
    if isinstance(created, (int, float)):
        if created > 1e12:
            created = created / 1000
        time_str = datetime.fromtimestamp(created).isoformat()[:16]
    elif isinstance(created, str):
        time_str = created[:16]
    else:
        time_str = datetime.now().isoformat()[:16]

    status = 'done'
    if comp.get('isRunning') or comp.get('status') == 'running':
        status = 'running'
    elif comp.get('error') or comp.get('status') == 'error':
        status = 'failed'

    stable_id = hashlib.md5(f"cursor-{title}-{time_str}".encode()).hexdigest()[:8]

    mode = comp.get('unifiedMode') or comp.get('composerMode') or comp.get('mode')
    if mode not in ('agent', 'chat', 'plan'):
        mode = None

    lines_added = comp.get('totalLinesAdded')
    lines_removed = comp.get('totalLinesRemoved')
    files_changed = comp.get('filesChangedCount')
    context_pct = comp.get('contextUsagePercent')
    subtitle = comp.get('subtitle')

    if isinstance(lines_added, (int, float)):
        lines_added = int(lines_added)
    else:
        lines_added = None
    if isinstance(lines_removed, (int, float)):
        lines_removed = int(lines_removed)
    else:
        lines_removed = None
    if isinstance(files_changed, (int, float)):
        files_changed = int(files_changed)
    else:
        files_changed = None
    if isinstance(context_pct, (int, float)):
        context_pct = round(context_pct, 1)
    else:
        context_pct = None

    link = None
    if workspace_path:
        link = f'cursor://file/{workspace_path}'

    return {
        'id': stable_id,
        'tool': 'cursor',
        'task': title.strip(),
        'time': time_str,
        'status': status,
        'workspace': workspace_name,
        'workspacePath': workspace_path,
        'mode': mode,
        'linesAdded': lines_added,
        'linesRemoved': lines_removed,
        'filesChanged': files_changed,
        'contextUsagePercent': context_pct,
        'subtitle': subtitle,
        'link': link,
    }

def extract_from_data(data, workspace_name=None, workspace_path=None):
    sessions = []
    if isinstance(data, dict):
        composers = data.get('allComposers', data.get('composers', []))
        if isinstance(composers, dict):
            composers = list(composers.values())
        for comp in composers:
            if isinstance(comp, dict):
                s = extract_session(comp, workspace_name, workspace_path)
                if s:
                    sessions.append(s)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                s = extract_session(item, workspace_name, workspace_path)
                if s:
                    sessions.append(s)
    return sessions

def scan_all():
    base = get_cursor_base_path()
    all_sessions = []

    global_db = base / 'globalStorage' / 'state.vscdb'
    if global_db.exists():
        for key, value in read_vscdb(global_db).items():
            if value and isinstance(value, (dict, list)):
                all_sessions.extend(extract_from_data(value, 'global'))

    ws_dir = base / 'workspaceStorage'
    if ws_dir.exists():
        for ws in ws_dir.iterdir():
            if not ws.is_dir():
                continue
            db_path = ws / 'state.vscdb'
            if not db_path.exists():
                continue
            ws_name = ws.name[:8]
            ws_path = None
            ws_json = ws / 'workspace.json'
            if ws_json.exists():
                try:
                    with open(ws_json) as f:
                        info = json.load(f)
                        folder = info.get('folder', '')
                        if folder.startswith('file:///'):
                            ws_path = folder[len('file://'):]
                            ws_name = Path(ws_path).name or ws_name
                        elif folder:
                            ws_name = Path(folder).name or ws_name
                except Exception:
                    pass
            for key, value in read_vscdb(db_path).items():
                if value and isinstance(value, (dict, list)):
                    all_sessions.extend(extract_from_data(value, ws_name, ws_path))

    seen = set()
    unique = []
    for s in all_sessions:
        if s['id'] not in seen:
            seen.add(s['id'])
            unique.append(s)
    return unique

def load_cache():
    if CACHE_FILE.exists():
        try:
            return set(json.loads(CACHE_FILE.read_text()))
        except Exception:
            pass
    return set()

def save_cache(ids):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(list(ids)))

def push_to_api(sessions, api_url):
    import urllib.request
    data = json.dumps(sessions).encode()
    req = urllib.request.Request(
        f'{api_url}/api/runs',
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log(f'Push failed: {e}')
        return None

LOG_FILE_HANDLE = None

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}\n'
    if LOG_FILE_HANDLE:
        LOG_FILE_HANDLE.write(line)
        LOG_FILE_HANDLE.flush()
    else:
        print(f'[{ts}] {msg}', flush=True)

def write_pid():
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

def cleanup_pid(*_):
    if PID_FILE.exists():
        PID_FILE.unlink()
    sys.exit(0)

def scan_claude():
    """Import and run Claude scraper if available."""
    try:
        import importlib.util
        scraper_path = Path(__file__).parent / 'claude-scraper.py'
        if not scraper_path.exists():
            return []
        spec = importlib.util.spec_from_file_location('claude_scraper', scraper_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.scan_all_sessions()
    except Exception as e:
        log(f'Claude scan error: {e}')
        return []

def watch_loop(api_url, interval, include_claude=True):
    write_pid()
    signal.signal(signal.SIGTERM, cleanup_pid)
    signal.signal(signal.SIGINT, cleanup_pid)

    known_ids = load_cache()
    log(f'Watcher started (pid {os.getpid()}, interval {interval}s, claude={include_claude})')
    log(f'Pushing to {api_url}')
    log(f'Cache has {len(known_ids)} known sessions')

    sessions = scan_all()
    if include_claude:
        claude_sessions = scan_claude()
        sessions.extend(claude_sessions)
        log(f'Claude: {len(claude_sessions)} sessions found')

    if sessions:
        result = push_to_api(sessions, api_url)
        if result:
            known_ids = {s['id'] for s in sessions}
            save_cache(known_ids)
            log(f'Initial sync: {len(sessions)} sessions pushed')

    claude_counter = 0
    claude_sync_every = 4  # sync Claude every N polls (less frequent since files change rarely)

    while True:
        time.sleep(interval)
        try:
            sessions = scan_all()
            claude_counter += 1
            if include_claude and claude_counter >= claude_sync_every:
                claude_counter = 0
                claude_sessions = scan_claude()
                sessions.extend(claude_sessions)

            current_ids = {s['id'] for s in sessions}
            new_ids = current_ids - known_ids

            changed = []
            for s in sessions:
                if s['id'] in new_ids:
                    changed.append(s)
                elif s['status'] == 'running':
                    changed.append(s)

            if changed:
                result = push_to_api(changed, api_url)
                if result:
                    known_ids = current_ids
                    save_cache(known_ids)
                    log(f'Pushed {len(changed)} sessions ({len(new_ids)} new)')
        except Exception as e:
            log(f'Scan error: {e}')

def main():
    parser = argparse.ArgumentParser(description='Real-time Cursor session watcher')
    parser.add_argument('api_url', help='Agent Tracker API URL (e.g. http://localhost:3000)')
    parser.add_argument('--interval', type=int, default=30, help='Poll interval in seconds (default: 30)')
    parser.add_argument('--daemon', action='store_true', help='Run in background (daemonize)')
    parser.add_argument('--stop', action='store_true', help='Stop a running daemon')
    parser.add_argument('--no-claude', action='store_true', help='Skip Claude session scanning')
    args = parser.parse_args()

    if args.stop:
        if PID_FILE.exists():
            pid = int(PID_FILE.read_text().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                log(f'Stopped watcher (pid {pid})')
            except ProcessLookupError:
                log(f'Watcher not running (stale pid {pid})')
            PID_FILE.unlink()
        else:
            log('No watcher running')
        return

    if args.daemon:
        global LOG_FILE_HANDLE
        log_path = Path(__file__).parent.parent / 'data' / 'watcher.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        pid = os.fork()
        if pid > 0:
            print(f'Watcher daemonized (pid {pid})', flush=True)
            return
        os.setsid()
        sys.stdin = open(os.devnull, 'r')
        LOG_FILE_HANDLE = open(log_path, 'a', buffering=1)
        sys.stdout = LOG_FILE_HANDLE
        sys.stderr = LOG_FILE_HANDLE

    watch_loop(args.api_url.rstrip('/'), args.interval, include_claude=not args.no_claude)

if __name__ == '__main__':
    main()
