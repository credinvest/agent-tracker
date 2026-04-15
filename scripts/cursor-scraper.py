#!/usr/bin/env python3
"""
Cursor Agent Session Scraper

Reads Cursor's local SQLite databases to extract agent/composer session data
with full metrics (lines changed, files changed, context usage, deep links)
and pushes to the Agent Tracker API.

Usage:
  python cursor-scraper.py                     # Print sessions to stdout
  python cursor-scraper.py --push URL          # Push to Agent Tracker API
  python cursor-scraper.py --export out.json   # Export to JSON file
"""

import json
import sys
import argparse
import importlib.util
from pathlib import Path

def get_watcher_module():
    """Import scan logic from cursor-watcher.py."""
    watcher_path = Path(__file__).parent / 'cursor-watcher.py'
    spec = importlib.util.spec_from_file_location('cursor_watcher', watcher_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def main():
    parser = argparse.ArgumentParser(description='Scrape Cursor agent sessions')
    parser.add_argument('--push', metavar='URL', help='Push to Agent Tracker API (e.g. http://localhost:3000)')
    parser.add_argument('--export', metavar='FILE', help='Export to JSON file')
    parser.add_argument('--agents-only', action='store_true', help='Only include agent mode sessions')
    args = parser.parse_args()

    watcher = get_watcher_module()
    sessions = watcher.scan_all()

    print(f'Found {len(sessions)} sessions', file=sys.stderr)

    if args.agents_only:
        sessions = [s for s in sessions if s.get('mode') == 'agent']
        print(f'Filtered to {len(sessions)} agent sessions', file=sys.stderr)

    if args.push:
        watcher.push_to_api(sessions, args.push.rstrip('/'))
    elif args.export:
        with open(args.export, 'w') as f:
            json.dump(sessions, f, indent=2)
        print(f'Exported {len(sessions)} sessions to {args.export}', file=sys.stderr)
    else:
        print(json.dumps(sessions, indent=2))

if __name__ == '__main__':
    main()
