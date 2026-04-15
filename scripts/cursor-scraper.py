#!/usr/bin/env python3
"""
Cursor Agent Session Scraper
Reads Cursor's local SQLite databases to extract agent/composer session data
and pushes it to the Agent Tracker API.

Usage:
  python cursor-scraper.py                     # Print sessions to stdout
  python cursor-scraper.py --push URL          # Push to Agent Tracker API
  python cursor-scraper.py --export out.json   # Export to JSON file

Cursor stores data in:
  macOS:   ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb
  Linux:   ~/.config/Cursor/User/globalStorage/state.vscdb
  Windows: %APPDATA%/Cursor/User/globalStorage/state.vscdb

Plus workspace-specific DBs in:
  .../User/workspaceStorage/*/state.vscdb
"""

import sqlite3
import json
import os
import sys
import platform
import hashlib
import argparse
from pathlib import Path
from datetime import datetime

def get_cursor_base_path():
    system = platform.system()
    if system == 'Darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Cursor' / 'User'
    elif system == 'Linux':
        return Path.home() / '.config' / 'Cursor' / 'User'
    elif system == 'Windows':
        return Path(os.environ.get('APPDATA', '')) / 'Cursor' / 'User'
    else:
        raise RuntimeError(f'Unsupported platform: {system}')

def read_vscdb(db_path, keys=None):
    """Read key-value pairs from a state.vscdb SQLite database."""
    if not db_path.exists():
        return {}

    results = {}
    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        cursor = conn.cursor()

        if keys:
            placeholders = ','.join('?' * len(keys))
            cursor.execute(f'SELECT key, value FROM ItemTable WHERE key IN ({placeholders})', keys)
        else:
            # Get all composer/chat related keys
            cursor.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE '%composer%' OR key LIKE '%chat%' OR key LIKE '%aichat%'"
            )

        for key, value in cursor.fetchall():
            try:
                results[key] = json.loads(value) if isinstance(value, str) else value
            except (json.JSONDecodeError, TypeError):
                results[key] = value

        conn.close()
    except Exception as e:
        print(f'  Warning: Could not read {db_path}: {e}', file=sys.stderr)

    return results

def extract_sessions_from_composer(data, workspace_name=None):
    """Extract session info from composer data."""
    sessions = []

    if isinstance(data, dict):
        # composerData can be a dict with allComposers or similar
        composers = data.get('allComposers', data.get('composers', []))
        if isinstance(composers, dict):
            composers = list(composers.values())

        for comp in composers:
            if not isinstance(comp, dict):
                continue

            session = extract_single_session(comp, workspace_name)
            if session:
                sessions.append(session)

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                session = extract_single_session(item, workspace_name)
                if session:
                    sessions.append(session)

    return sessions

def extract_single_session(comp, workspace_name=None):
    """Extract a single session from a composer entry."""
    # Try to get a title/name
    title = (
        comp.get('name') or
        comp.get('title') or
        comp.get('query', '')[:80] or
        comp.get('text', '')[:80] or
        'Untitled session'
    )

    if not title or title == 'Untitled session':
        # Try to extract from first message
        messages = comp.get('messages', comp.get('conversation', []))
        if isinstance(messages, list) and len(messages) > 0:
            first = messages[0]
            if isinstance(first, dict):
                title = (first.get('text', '') or first.get('content', ''))[:80]

    if not title.strip():
        return None

    # Determine if this was an agent run (vs simple chat)
    is_agent = comp.get('mode') == 'agent' or comp.get('isAgent', False) or comp.get('composerMode') == 'agent'

    # Get timestamp
    created = comp.get('createdAt') or comp.get('timestamp') or comp.get('startTime')
    if isinstance(created, (int, float)):
        # Unix timestamp (ms or s)
        if created > 1e12:
            created = created / 1000
        time_str = datetime.fromtimestamp(created).isoformat()[:16]
    elif isinstance(created, str):
        time_str = created[:16]
    else:
        time_str = datetime.now().isoformat()[:16]

    # Determine status
    status = 'done'
    if comp.get('isRunning') or comp.get('status') == 'running':
        status = 'running'
    elif comp.get('error') or comp.get('status') == 'error':
        status = 'failed'

    # Generate stable ID from content
    id_source = f"cursor-{title}-{time_str}"
    stable_id = hashlib.md5(id_source.encode()).hexdigest()[:8]

    return {
        'id': stable_id,
        'tool': 'cursor',
        'task': title.strip(),
        'time': time_str,
        'status': status,
        'workspace': workspace_name,
        'isAgent': is_agent,
    }

def scan_all_sessions():
    """Scan all Cursor databases for session data."""
    base = get_cursor_base_path()
    all_sessions = []

    print(f'Scanning: {base}', file=sys.stderr)

    # 1. Global state
    global_db = base / 'globalStorage' / 'state.vscdb'
    if global_db.exists():
        print(f'  Reading global DB...', file=sys.stderr)
        data = read_vscdb(global_db)
        for key, value in data.items():
            if value and isinstance(value, (dict, list)):
                sessions = extract_sessions_from_composer(value, workspace_name='global')
                all_sessions.extend(sessions)

    # 2. Workspace-specific databases
    ws_dir = base / 'workspaceStorage'
    if ws_dir.exists():
        workspace_dirs = [d for d in ws_dir.iterdir() if d.is_dir()]
        print(f'  Found {len(workspace_dirs)} workspaces...', file=sys.stderr)

        for ws in workspace_dirs:
            db_path = ws / 'state.vscdb'
            if not db_path.exists():
                continue

            # Try to get workspace name from workspace.json
            ws_name = ws.name[:8]
            ws_json = ws / 'workspace.json'
            if ws_json.exists():
                try:
                    with open(ws_json) as f:
                        ws_info = json.load(f)
                        folder = ws_info.get('folder', '')
                        ws_name = Path(folder).name or ws_name
                except:
                    pass

            data = read_vscdb(db_path)
            for key, value in data.items():
                if value and isinstance(value, (dict, list)):
                    sessions = extract_sessions_from_composer(value, workspace_name=ws_name)
                    all_sessions.extend(sessions)

    # Deduplicate by ID
    seen = set()
    unique = []
    for s in all_sessions:
        if s['id'] not in seen:
            seen.add(s['id'])
            unique.append(s)

    print(f'  Found {len(unique)} sessions total', file=sys.stderr)
    return unique

def push_to_api(sessions, api_url):
    """Push sessions to the Agent Tracker API."""
    import urllib.request

    data = json.dumps(sessions).encode()
    req = urllib.request.Request(
        f'{api_url}/api/runs',
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            print(f'Pushed {len(sessions)} sessions. API now has {result.get("count", "?")} total.', file=sys.stderr)
    except Exception as e:
        print(f'Error pushing to API: {e}', file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Scrape Cursor agent sessions')
    parser.add_argument('--push', metavar='URL', help='Push to Agent Tracker API (e.g. https://your-app.vercel.app)')
    parser.add_argument('--export', metavar='FILE', help='Export to JSON file')
    parser.add_argument('--agents-only', action='store_true', help='Only include agent mode sessions (skip chat)')
    args = parser.parse_args()

    sessions = scan_all_sessions()

    if args.agents_only:
        sessions = [s for s in sessions if s.get('isAgent')]
        print(f'  Filtered to {len(sessions)} agent sessions', file=sys.stderr)

    # Clean up internal fields
    for s in sessions:
        s.pop('isAgent', None)

    if args.push:
        push_to_api(sessions, args.push.rstrip('/'))
    elif args.export:
        with open(args.export, 'w') as f:
            json.dump(sessions, f, indent=2)
        print(f'Exported {len(sessions)} sessions to {args.export}', file=sys.stderr)
    else:
        print(json.dumps(sessions, indent=2))

if __name__ == '__main__':
    main()
