#!/bin/bash
# Manage the Cursor + Claude watcher daemon via launchd
#
# Usage:
#   ./manage-watcher.sh install    # Install and start (auto-starts on login)
#   ./manage-watcher.sh uninstall  # Stop and remove
#   ./manage-watcher.sh start      # Start now
#   ./manage-watcher.sh stop       # Stop now
#   ./manage-watcher.sh status     # Check status
#   ./manage-watcher.sh logs       # Tail watcher log

PLIST_NAME="com.agent-tracker.cursor-watcher"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/data/watcher.log"
API_URL="${AGENT_TRACKER_URL:-http://localhost:3000}"
INTERVAL="${AGENT_TRACKER_INTERVAL:-30}"

generate_plist() {
  cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>${SCRIPT_DIR}/cursor-watcher.py</string>
        <string>${API_URL}</string>
        <string>--interval</string>
        <string>${INTERVAL}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_FILE}</string>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
</dict>
</plist>
PLIST
}

case "$1" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/data"
    generate_plist
    launchctl load "$PLIST_DST"
    echo "Installed and started. Watcher will auto-start on login."
    echo "  API URL:  $API_URL"
    echo "  Interval: ${INTERVAL}s"
    echo "  Logs:     $LOG_FILE"
    echo ""
    echo "To change the URL or interval, set env vars before running:"
    echo "  AGENT_TRACKER_URL=https://my-app.vercel.app AGENT_TRACKER_INTERVAL=15 ./manage-watcher.sh install"
    ;;
  uninstall)
    launchctl unload "$PLIST_DST" 2>/dev/null
    rm -f "$PLIST_DST"
    echo "Stopped and uninstalled."
    ;;
  start)
    launchctl start "$PLIST_NAME"
    echo "Started."
    ;;
  stop)
    launchctl stop "$PLIST_NAME"
    echo "Stopped."
    ;;
  status)
    if launchctl list 2>/dev/null | grep -q "$PLIST_NAME"; then
      echo "Running."
      launchctl list "$PLIST_NAME" 2>/dev/null
    else
      echo "Not running."
    fi
    ;;
  logs)
    tail -f "$LOG_FILE"
    ;;
  *)
    echo "Usage: $0 {install|uninstall|start|stop|status|logs}"
    echo ""
    echo "Environment variables:"
    echo "  AGENT_TRACKER_URL       API URL (default: http://localhost:3000)"
    echo "  AGENT_TRACKER_INTERVAL  Poll interval in seconds (default: 30)"
    exit 1
    ;;
esac
