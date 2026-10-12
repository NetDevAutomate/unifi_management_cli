#!/usr/bin/env bash
# unifi-cron.sh — Master cron management for UniFi network audit tools
# Supports: macOS (launchd) and Ubuntu/Linux (crontab)
#
# Usage:
#   ./scripts/unifi-cron.sh install [--with-port-naming]  — Install the read-only audit tasks
#   ./scripts/unifi-cron.sh uninstall                     — Remove every scheduled task
#   ./scripts/unifi-cron.sh update [--with-port-naming]   — Reinstall (uninstall + install)
#   ./scripts/unifi-cron.sh status                        — Show current scheduled tasks
#   ./scripts/unifi-cron.sh run-all [--with-port-naming]  — Run every task once (manual)
#
# Every default task only reads the controller or records to the local state directory. The
# port-naming task WRITES port names to the controller every 30 minutes, so it is scheduled or
# run only with --with-port-naming (issue 025).

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
# port-naming writes port names, so it passes --apply explicitly (discover previews by default).
# link-error-snapshot keeps its name (so uninstall still finds installed jobs) but now appends
# to the counter history (--record) instead of overwriting the comparison baseline; set the
# baseline deliberately with `unifi-mapper analyze link-errors --snapshot`.
# wan-speedtest-record reads the controller's last scheduled speedtest (one read-only GET) and
# appends it to the WAN history under the XDG state directory; it never starts a speedtest.
# Intervals: for cron = cron expression, for launchd = seconds
TASKS=(
    "link-error-snapshot|300|analyze link-errors --record"
    "client-roaming-snapshot|300|analyze roaming --snapshot"
    "config-drift-check|3600|analyze config-drift"
    "diagnose-all|3600|diagnose all"
    "radio-report|3600|radio report -o reports/channel-report.md"
    "wan-speedtest-record|3600|diagnose wan --record"
)

# Cron expressions matching the intervals above
CRON_SCHEDULES=(
    "*/5 * * * *"    # every 5 min
    "*/5 * * * *"    # every 5 min
    "0 * * * *"      # every hour
    "0 * * * *"      # every hour
    "0 * * * *"      # every hour
    "0 * * * *"      # every hour
)

# The one task that writes to the controller. Opt-in: --with-port-naming appends it to TASKS
# for install, update and run-all; uninstall and status always know it, so an opted-in job is
# removed and reported like the others.
PORT_NAMING_TASK="port-naming|1800|--verify-updates --connected-devices --apply"
PORT_NAMING_SCHEDULE="*/30 * * * *"
WITH_PORT_NAMING=0
for arg in "${@:2}"; do
    case "$arg" in
        --with-port-naming) WITH_PORT_NAMING=1 ;;
        *) echo "[ERROR] unknown option: $arg" >&2; exit 2 ;;
    esac
done
if (( WITH_PORT_NAMING )); then
    TASKS+=("$PORT_NAMING_TASK")
    CRON_SCHEDULES+=("$PORT_NAMING_SCHEDULE")
fi
# Every task uninstall and status consider: the defaults plus the opt-in one, so an installed
# port-naming job is removed, and reported (running, not loaded or stale), with or without the
# flag; only a missing one is reported as opt-in.
ALL_TASKS=("${TASKS[@]}")
ALL_SCHEDULES=("${CRON_SCHEDULES[@]}")
if (( ! WITH_PORT_NAMING )); then
    ALL_TASKS+=("$PORT_NAMING_TASK")
    ALL_SCHEDULES+=("$PORT_NAMING_SCHEDULE")
fi

LAUNCHD_PREFIX="com.unifi-management"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
CRON_MARKER="# UNIFI-MANAGEMENT-CLI"

# ─── Helpers ──────────────────────────────────────────────────────────────────

is_macos() { [[ "$(uname -s)" == "Darwin" ]]; }
is_linux() { [[ "$(uname -s)" == "Linux" ]]; }

log() { echo "[$(date '+%H:%M:%S')] $*"; }
err() { echo "[ERROR] $*" >&2; }

build_command() {
    # The command runs under `bash -c` (launchd) or the crontab shell, so the two paths are
    # shell-quoted: a checkout under "Odd & Dir" would otherwise split or fork the line.
    local cmd="$1"
    printf 'cd %q && %q run unifi-mapper %s\n' "$PROJECT_DIR" "$UV_BIN" "$cmd"
}

# A plain install keeps an opted-in port-naming job from an earlier install, and says so.
note_kept_port_naming() {
    log "port-naming kept: it was installed earlier with --with-port-naming and writes port names;" \
        "run '$0 uninstall' (or 'update' without the flag) to remove it"
}

# A plist is XML: the command holds `&&`, which must be `&amp;&amp;` or launchd refuses the
# whole file (issue 025). Every <string> value goes through this, install and status alike.
xml_escape() {
    local s="$1"
    s="${s//&/&amp;}"; s="${s//</&lt;}"; s="${s//>/&gt;}"
    printf '%s' "$s"
}

# ─── macOS (launchd) ─────────────────────────────────────────────────────────

install_launchd() {
    mkdir -p "$LAUNCHD_DIR" "$LOG_DIR"
    if (( ! WITH_PORT_NAMING )) && [[ -f "${LAUNCHD_DIR}/${LAUNCHD_PREFIX}.port-naming.plist" ]]; then
        note_kept_port_naming
    fi

    for i in "${!TASKS[@]}"; do
        IFS='|' read -r name interval cmd <<< "${TASKS[$i]}"
        local plist_name="${LAUNCHD_PREFIX}.${name}"
        local plist_path="${LAUNCHD_DIR}/${plist_name}.plist"
        local full_cmd
        full_cmd=$(xml_escape "$(build_command "$cmd")")

        launchctl unload "$plist_path" 2>/dev/null || true  # so a re-install replaces the job
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
    <string>$(xml_escape "${LOG_DIR}/${name}.log")</string>
    <key>StandardErrorPath</key>
    <string>$(xml_escape "${LOG_DIR}/${name}.err")</string>
    <key>WorkingDirectory</key>
    <string>$(xml_escape "${PROJECT_DIR}")</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$(xml_escape "/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin")</string>
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
    for i in "${!ALL_TASKS[@]}"; do
        IFS='|' read -r name _ _ <<< "${ALL_TASKS[$i]}"
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
    local stale=0
    for i in "${!ALL_TASKS[@]}"; do
        IFS='|' read -r name interval cmd <<< "${ALL_TASKS[$i]}"
        local plist_name="${LAUNCHD_PREFIX}.${name}"
        local plist_path="${LAUNCHD_DIR}/${plist_name}.plist"
        if [[ "$name" == port-naming && ! -f "$plist_path" ]]; then
            echo "  ➖ port-naming: not installed (writes port names; opt in with 'install --with-port-naming')"
            continue
        fi
        if launchctl list "$plist_name" &>/dev/null; then
            echo "  ✅ $name (every ${interval}s) — running"
        else
            echo "  ❌ $name — not loaded"
        fi
        # The command is copied into the plist at install time: flag one that predates TASKS.
        if [[ -f "$plist_path" ]] && ! grep -qF "<string>$(xml_escape "$(build_command "$cmd")")</string>" "$plist_path"; then
            echo "     ⚠️  stale: installed command differs from: unifi-mapper $cmd"
            stale=1
        fi
    done
    if (( stale )); then
        echo "  Run '$0 update' to reinstall the current commands."
    fi
}

# ─── Linux (crontab) ─────────────────────────────────────────────────────────

install_crontab() {
    mkdir -p "$LOG_DIR"

    # Get existing crontab (without our entries). An opted-in port-naming line is ours too,
    # so a plain install keeps it and says so.
    local all_existing existing kept_naming
    all_existing=$(crontab -l 2>/dev/null || true)
    existing=$(grep -v "$CRON_MARKER" <<< "$all_existing" || true)
    kept_naming=$(grep "$CRON_MARKER" <<< "$all_existing" | grep -F -- "/port-naming.log" || true)
    if (( ! WITH_PORT_NAMING )) && [[ -n "$kept_naming" ]]; then
        note_kept_port_naming
        existing="${existing}
${kept_naming}"
    fi

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
        # The command is copied into the crontab line at install time: flag one that
        # predates TASKS.
        local stale=0
        for i in "${!ALL_TASKS[@]}"; do
            IFS='|' read -r name _ cmd <<< "${ALL_TASKS[$i]}"
            if [[ "$name" == port-naming ]] && ! grep -qF -- "${LOG_DIR}/port-naming.log" <<< "$entries"; then
                echo "  ➖ port-naming: not installed (writes port names; opt in with 'install --with-port-naming')"
                continue
            fi
            local expected
            expected="${ALL_SCHEDULES[$i]} $(build_command "$cmd") >> ${LOG_DIR}/${name}.log 2>&1 ${CRON_MARKER}"
            if ! grep -qxF -- "$expected" <<< "$entries"; then
                echo "  ⚠️  $name: stale or missing; current command: unifi-mapper $cmd"
                stale=1
            fi
        done
        if (( stale )); then
            echo "  Run '$0 update' to reinstall the current commands."
        fi
    fi
}

# ─── Run All (manual) ────────────────────────────────────────────────────────

run_all() {
    mkdir -p "$LOG_DIR"
    log "Running all audit tasks..."

    cd "$PROJECT_DIR"
    $UV_BIN run unifi-mapper analyze link-errors --record
    $UV_BIN run unifi-mapper analyze roaming --snapshot
    $UV_BIN run unifi-mapper analyze config-drift
    $UV_BIN run unifi-mapper diagnose all
    $UV_BIN run unifi-mapper radio report -o reports/channel-report.md
    $UV_BIN run unifi-mapper diagnose wan --record

    if (( WITH_PORT_NAMING )); then
        $UV_BIN run unifi-mapper --verify-updates --connected-devices --apply
    else
        log "port-naming skipped (writes port names; pass --with-port-naming to run it)"
    fi

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
        echo "Usage: $0 {install|uninstall|update|status|run-all} [--with-port-naming]"
        echo ""
        echo "Commands:"
        echo "  install    Install the read-only audit tasks (launchd on macOS, cron on Linux)"
        echo "  uninstall  Remove every scheduled task, the port-naming one included"
        echo "  update     Reinstall (uninstall + install)"
        echo "  status     Show current scheduled task status"
        echo "  run-all    Run every task once (manual trigger)"
        echo ""
        echo "  --with-port-naming  also schedule or run port naming, which WRITES port names"
        echo "                      to the controller every 30 minutes (off by default)"
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
