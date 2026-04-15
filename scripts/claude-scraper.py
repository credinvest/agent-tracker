#!/usr/bin/env python3
"""
Claude session scraper.

Reads Claude Cowork (local agent mode) sessions from:
  macOS: ~/Library/Application Support/Claude/local-agent-mode-sessions/

Extracts session metadata (title, timestamps, message counts, tool usage)
and pushes to the Agent Tracker API.

Usage:
  python claude-scraper.py                          # Print sessions to stdout
  python claude-scraper.py --push http://localhost:3000   # Push to API
  python claude-scraper.py --export out.json        # Export to JSON
"""

import json
import os
import re
import sys
import time as _time
import hashlib
import argparse
import platform
from pathlib import Path
from datetime import datetime

def get_claude_sessions_path():
    system = platform.system()
    if system == 'Darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Claude' / 'local-agent-mode-sessions'
    elif system == 'Linux':
        return Path.home() / '.config' / 'Claude' / 'local-agent-mode-sessions'
    elif system == 'Windows':
        return Path(os.environ.get('APPDATA', '')) / 'Claude' / 'local-agent-mode-sessions'
    raise RuntimeError(f'Unsupported platform: {system}')

def parse_audit_file(audit_path):
    title = ''
    first_ts = None
    last_ts = None
    user_msgs = 0
    assistant_msgs = 0
    tool_uses = 0
    tools_used = set()
    total_input_tokens = 0
    total_output_tokens = 0

    try:
        with open(audit_path) as f:
            for line in f:
                try:
                    d = json.loads(line.strip())
                except (json.JSONDecodeError, ValueError):
                    continue

                ts = d.get('timestamp')
                if ts:
                    if not first_ts:
                        first_ts = ts
                    last_ts = ts

                msg_type = d.get('type')

                if msg_type == 'user':
                    user_msgs += 1
                    if not title:
                        content = d.get('message', {}).get('content', '')
                        if isinstance(content, str):
                            if '<scheduled-task' in content:
                                m = re.search(r'name="([^"]+)"', content)
                                if m:
                                    title = f'Scheduled: {m.group(1)}'
                            else:
                                clean = content.strip()
                                if len(clean) > 0:
                                    title = clean[:80]

                elif msg_type == 'assistant':
                    assistant_msgs += 1
                    usage = d.get('message', {}).get('usage', {})
                    total_input_tokens += usage.get('input_tokens', 0)
                    total_output_tokens += usage.get('output_tokens', 0)

                elif msg_type == 'tool_use':
                    tool_uses += 1
                    tool_name = d.get('name', '')
                    if tool_name:
                        tools_used.add(tool_name.split('__')[-1] if '__' in tool_name else tool_name)

                elif msg_type == 'tool_result':
                    pass

    except Exception as e:
        print(f'  Warning reading {audit_path}: {e}', file=sys.stderr)
        return None

    if not title:
        return None

    return {
        'title': title,
        'first_ts': first_ts,
        'last_ts': last_ts,
        'user_msgs': user_msgs,
        'assistant_msgs': assistant_msgs,
        'tool_uses': tool_uses,
        'tools_used': sorted(tools_used),
        'input_tokens': total_input_tokens,
        'output_tokens': total_output_tokens,
    }

def scan_all_sessions():
    base = get_claude_sessions_path()
    if not base.exists():
        print(f'Claude sessions directory not found: {base}', file=sys.stderr)
        return []

    print(f'Scanning: {base}', file=sys.stderr)
    all_sessions = []

    audit_files = list(base.rglob('audit.jsonl'))
    print(f'  Found {len(audit_files)} session files...', file=sys.stderr)

    for audit_path in audit_files:
        session_dir = audit_path.parent.name
        sid = session_dir.replace('local_', '')

        parsed = parse_audit_file(audit_path)
        if not parsed:
            continue

        mtime = os.path.getmtime(audit_path)
        time_str = datetime.fromtimestamp(mtime).isoformat()[:16]

        if parsed['first_ts']:
            try:
                time_str = parsed['first_ts'][:16]
            except (TypeError, IndexError):
                pass

        age_seconds = _time.time() - mtime
        if age_seconds < 120:
            status = 'running'
        elif age_seconds < 1800:
            status = 'idle'
        else:
            status = 'done'

        total_msgs = parsed['user_msgs'] + parsed['assistant_msgs']
        stable_id = hashlib.md5(f"claude-{parsed['title']}-{time_str}".encode()).hexdigest()[:8]

        complexity = min(100, max(0,
            parsed['tool_uses'] * 2
            + total_msgs * 0.5
            + len(parsed['tools_used']) * 5
            + (parsed['output_tokens'] / 1000) * 0.3
        ))

        subtitle_parts = []
        if parsed['tool_uses'] > 0:
            subtitle_parts.append(f"{parsed['tool_uses']} tool calls")
        if parsed['tools_used']:
            subtitle_parts.append(', '.join(parsed['tools_used'][:5]))
        subtitle = ' -- '.join(subtitle_parts) if subtitle_parts else None

        session_path = str(audit_path.parent)
        link = f'file://{session_path}'

        session = {
            'id': stable_id,
            'tool': 'claude',
            'task': parsed['title'],
            'time': time_str,
            'status': status,
            'workspace': None,
            'mode': 'agent',
            'linesAdded': None,
            'linesRemoved': None,
            'filesChanged': None,
            'contextUsagePercent': None,
            'subtitle': subtitle,
            'link': link,
            'sessionPath': session_path,
        }

        all_sessions.append(session)

    seen = set()
    unique = []
    for s in all_sessions:
        if s['id'] not in seen:
            seen.add(s['id'])
            unique.append(s)

    print(f'  Found {len(unique)} sessions total', file=sys.stderr)
    return unique

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
            result = json.loads(resp.read())
            print(f'Pushed {len(sessions)} sessions. API now has {result.get("count", "?")} total.', file=sys.stderr)
    except Exception as e:
        print(f'Error pushing to API: {e}', file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Scrape Claude Cowork sessions')
    parser.add_argument('--push', metavar='URL', help='Push to Agent Tracker API')
    parser.add_argument('--export', metavar='FILE', help='Export to JSON file')
    args = parser.parse_args()

    sessions = scan_all_sessions()

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
