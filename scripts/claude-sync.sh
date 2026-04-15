#!/bin/bash
# Claude Session Sync
# Pulls Cowork session data and pushes to Agent Tracker API.
#
# Usage:
#   ./claude-sync.sh                          # Print sessions as JSON
#   ./claude-sync.sh https://your-app.vercel.app  # Push to API
#
# Requirements: claude CLI must be installed and authenticated.
# This script uses `claude sessions list` to get session data.
# If that command isn't available, run this from within a Cowork session
# and use the export feature instead.

API_URL="${1}"

echo "Fetching Claude sessions..." >&2

# Try using the claude CLI
if command -v claude &> /dev/null; then
  SESSIONS=$(claude sessions list --json 2>/dev/null)
  if [ $? -eq 0 ] && [ -n "$SESSIONS" ]; then
    echo "Got sessions from claude CLI" >&2

    # Transform to agent-tracker format
    TRANSFORMED=$(echo "$SESSIONS" | python3 -c "
import sys, json, hashlib
data = json.load(sys.stdin)
runs = []
for s in data:
    title = s.get('name', s.get('title', 'Untitled'))
    time = s.get('createdAt', s.get('startTime', ''))[:16]
    status_map = {'running': 'running', 'idle': 'idle', 'completed': 'done', 'error': 'failed'}
    status = status_map.get(s.get('status', 'idle'), 'idle')
    sid = hashlib.md5(f'claude-{title}-{time}'.encode()).hexdigest()[:8]
    runs.append({'id': sid, 'tool': 'claude', 'task': title, 'time': time, 'status': status})
print(json.dumps(runs, indent=2))
")

    if [ -n "$API_URL" ]; then
      echo "Pushing to $API_URL/api/runs..." >&2
      curl -s -X POST "$API_URL/api/runs" \
        -H "Content-Type: application/json" \
        -d "$TRANSFORMED"
      echo "" >&2
      echo "Done." >&2
    else
      echo "$TRANSFORMED"
    fi
    exit 0
  fi
fi

echo "claude CLI not available or sessions command failed." >&2
echo "Alternative: Export sessions from Cowork using the dashboard export button," >&2
echo "or run the sync from within a Cowork session." >&2
exit 1
