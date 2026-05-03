#!/usr/bin/env bash
# unifi-cron.sh — Master cron management for UniFi network audit tools
# Supports: macOS (launchd) and Ubuntu/Linux (crontab)
#
# Usage:
#   ./scripts/unifi-cron.sh install   — Install all scheduled tasks
#   ./scripts/unifi-cron.sh uninstall — Remove all scheduled tasks
#   ./scripts/unifi-cron.sh update    — Reinstall (uninstall + install)
#   ./scripts/unifi-cron.sh status    — Show current scheduled tasks
#   ./scripts/unifi-cron.sh run-all   — Run all audit tasks once (manual trigger)

set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────

# Detect project root (where this script lives)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# UV binary (adjust if installed elsewhere)
UV_BIN="${UV_BIN:-$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")}"

# Log directory
LOG_DIR="${LOG_DIR:-$PROJECT_DIR/logs}"

# Schedule definitions: "name|interval|command"
# Intervals: for cron = cron expression, for launchd = seconds
TASKS=(
    "link-error-snapshot|300|analyze link-errors --snapshot"
    "client-roaming-snapshot|300|analyze roaming --snapshot"
    "config-drift-check|3600|analyze config-drift"
    "diagnose-all|3600|diagnose all"
    "radio-report|3600|radio report -o reports/channel-report.md"
    "port-naming|1800|--verify-updates --connected-devices"
)

# Cron expressions matching the intervals above
CRON_SCHEDULES=(
    "*/5 * * * *"    # every 5 min
    "*/5 * * * *"    # every 5 min
    "0 * * * *"      # every hour
    "0 * * * *"      # every hour
    "0 * * * *"      # every hour
    "*/30 * * * *"   # every 30 min
)

LAUNCHD_PREFIX="com.unifi-management"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
CRON_MARKER="# UNIFI-MANAGEMENT-CLI"

# ─── Helpers ──────────────────────────────────────────────────────────────────

is_macos() { [[ "$(uname -s)" == "Darwin" ]]; }
is_linux() { [[ "$(uname -s)" == "Linux" ]]; }

log() { echo "[$(date '+%H:%M:%S')] $*"; }
err() { echo "[ERROR] $*" >&2; }

build_command() {
    local cmd="$1"
    echo "cd $PROJECT_DIR && $UV_BIN run unifi-mapper $cmd"
}

# ─── macOS (launchd) ─────────────────────────────────────────────────────────

install_launchd() {
    mkdir -p "$LAUNCHD_DIR" "$LOG_DIR"

    for i in "${!TASKS[@]}"; do
        IFS='|' read -r name interval cmd <<< "${TASKS[$i]}"
        local plist_name="${LAUNCHD_PREFIX}.${name}"
        local plist_path="${LAUNCHD_DIR}/${plist_name}.plist"
        local full_cmd
        full_cmd=$(build_command "$cmd")

        cat > "$plist_path" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${plist_name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>${full_cmd}</string>
    </array>
    <key>StartInterval</key>
    <integer>${interval}</integer>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/${name}.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/${name}.err</string>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin</string>
    </dict>
</dict>
</plist>
EOF
        launchctl load "$plist_path" 2>/dev/null || true
        log "Installed: $name (every ${interval}s)"
    done
    log "✅ All tasks installed via launchd"
}

uninstall_launchd() {
    for i in "${!TASKS[@]}"; do
        IFS='|' read -r name _ _ <<< "${TASKS[$i]}"
        local plist_name="${LAUNCHD_PREFIX}.${name}"
        local plist_path="${LAUNCHD_DIR}/${plist_name}.plist"

        if [[ -f "$plist_path" ]]; then
            launchctl unload "$plist_path" 2>/dev/null || true
            rm -f "$plist_path"
            log "Removed: $name"
        fi
    done
    log "✅ All tasks uninstalled"
}

status_launchd() {
    log "Scheduled tasks (launchd):"
    for i in "${!TASKS[@]}"; do
        IFS='|' read -r name interval _ <<< "${TASKS[$i]}"
        local plist_name="${LAUNCHD_PREFIX}.${name}"
        if launchctl list "$plist_name" &>/dev/null; then
            echo "  ✅ $name (every ${interval}s) — running"
        else
            echo "  ❌ $name — not loaded"
        fi
    done
}

# ─── Linux (crontab) ─────────────────────────────────────────────────────────

install_crontab() {
    mkdir -p "$LOG_DIR"

    # Get existing crontab (without our entries)
    local existing
    existing=$(crontab -l 2>/dev/null | grep -v "$CRON_MARKER" || true)

    # Build new entries
    local new_entries="$existing"
    for i in "${!TASKS[@]}"; do
        IFS='|' read -r name _ cmd <<< "${TASKS[$i]}"
        local schedule="${CRON_SCHEDULES[$i]}"
        local full_cmd
        full_cmd=$(build_command "$cmd")
        new_entries="${new_entries}
${schedule} ${full_cmd} >> ${LOG_DIR}/${name}.log 2>&1 ${CRON_MARKER}"
    done

    echo "$new_entries" | crontab -
    log "✅ All tasks installed via crontab"
}

uninstall_crontab() {
    local existing
    existing=$(crontab -l 2>/dev/null | grep -v "$CRON_MARKER" || true)
    echo "$existing" | crontab -
    log "✅ All UniFi cron entries removed"
}

status_crontab() {
    log "Scheduled tasks (crontab):"
    local entries
    entries=$(crontab -l 2>/dev/null | grep "$CRON_MARKER" || true)
    if [[ -z "$entries" ]]; then
        echo "  ❌ No UniFi tasks installed"
    else
        echo "$entries" | while read -r line; do
            echo "  ✅ $line"
        done
    fi
}

# ─── Run All (manual) ────────────────────────────────────────────────────────

run_all() {
    mkdir -p "$LOG_DIR"
    log "Running all audit tasks..."

    cd "$PROJECT_DIR"
    $UV_BIN run unifi-mapper analyze link-errors --snapshot
    $UV_BIN run unifi-mapper analyze roaming --snapshot
    $UV_BIN run unifi-mapper analyze config-drift
    $UV_BIN run unifi-mapper diagnose all
    $UV_BIN run unifi-mapper radio report -o reports/channel-report.md
    $UV_BIN run unifi-mapper --verify-updates --connected-devices

    log "✅ All tasks complete"
}

# ─── Main ─────────────────────────────────────────────────────────────────────

case "${1:-help}" in
    install)
        if is_macos; then install_launchd
        elif is_linux; then install_crontab
        else err "Unsupported OS"; exit 1; fi
        ;;
    uninstall)
        if is_macos; then uninstall_launchd
        elif is_linux; then uninstall_crontab
        else err "Unsupported OS"; exit 1; fi
        ;;
    update)
        if is_macos; then uninstall_launchd; install_launchd
        elif is_linux; then uninstall_crontab; install_crontab
        else err "Unsupported OS"; exit 1; fi
        ;;
    status)
        if is_macos; then status_launchd
        elif is_linux; then status_crontab
        else err "Unsupported OS"; exit 1; fi
        ;;
    run-all)
        run_all
        ;;
    help|--help|-h)
        echo "Usage: $0 {install|uninstall|update|status|run-all}"
        echo ""
        echo "Commands:"
        echo "  install    Install scheduled audit tasks (launchd on macOS, cron on Linux)"
        echo "  uninstall  Remove all scheduled audit tasks"
        echo "  update     Reinstall (uninstall + install)"
        echo "  status     Show current scheduled task status"
        echo "  run-all    Run all audit tasks once (manual trigger)"
        echo ""
        echo "Scheduled tasks:"
        for i in "${!TASKS[@]}"; do
            IFS='|' read -r name interval cmd <<< "${TASKS[$i]}"
            printf "  %-25s every %4ss  unifi-mapper %s\n" "$name" "$interval" "$cmd"
        done
        ;;
    *)
        err "Unknown command: $1"
        echo "Usage: $0 {install|uninstall|update|status|run-all}"
        exit 1
        ;;
esac
