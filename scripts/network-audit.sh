#!/usr/bin/env bash
#
# network-audit.sh: a read-only audit of a UniFi network, for review before any change.
#
# Runs, each a preview or a read (this script has no apply path):
#   1. unifi-mapper discover --dry-run --connected-devices -o <dir>/port-mapping.md
#   2. unifi-mapper stp snapshot -o <dir>/stp-snapshot.json
#   3. unifi-mapper stp analyze
#   4. unifi-mapper stp optimize --dry-run --plan <dir>/stp-plan.json
#   5. unifi-mapper stp guard
#   6. unifi-mapper stp report -o <dir>/stp-report.md
#   7. unifi-mapper stp validate-10g --planned-switches N   (only with --planned-switches)
# then prints the commands that apply what you agree with, each of which previews first.
# A failed step is reported and the others still run; the exit status is 1 if any failed.
#
# Usage:
#   scripts/network-audit.sh [--config PATH] [--output-dir DIR] [--planned-switches N]
#
#   --config PATH         env file, passed as unifi-mapper's --config (default: its own
#                         search, UNIFI_CONFIG first)
#   --output-dir DIR      where the reports and audit.log go (default:
#                         ${XDG_STATE_HOME:-$HOME/.local/state}/unifi_mapper/audits/<UTC stamp>)
#   --planned-switches N  also check 10G uplink readiness for N planned switches
#
# Rebuilt from the July work's audit script (a local archive, not in the repo): no
# reports/ directory in the repository, no STP apply step and no confirmation prompt
# (`stp apply --plan` already previews, then applies with --no-dry-run), and no default
# for the planned-switch count.

set -euo pipefail
umask 077  # the reports describe the site: keep them private

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CONFIG_PATH=""
OUTPUT_DIR=""
PLANNED_SWITCHES=""

usage() {
    sed -n '3,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

die() {
    echo "network-audit: $*" >&2
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            [[ $# -ge 2 && -n "$2" ]] || die "--config needs a path"
            CONFIG_PATH="$2"
            shift 2
            ;;
        --output-dir)
            [[ $# -ge 2 && -n "$2" ]] || die "--output-dir needs a directory"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --planned-switches)
            [[ $# -ge 2 && "$2" =~ ^[1-9][0-9]*$ ]] || die "--planned-switches needs a whole number of 1 or more"
            PLANNED_SWITCHES="$2"
            shift 2
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $1 (see --help)"
            ;;
    esac
done

command -v uv >/dev/null 2>&1 || die "uv is not installed"
if [[ -n "${CONFIG_PATH}" && ! -r "${CONFIG_PATH}" ]]; then
    die "--config ${CONFIG_PATH} is missing or unreadable"
fi
if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/unifi_mapper/audits/${STAMP}"
fi
[[ -e "${OUTPUT_DIR}" && ! -d "${OUTPUT_DIR}" ]] && die "--output-dir ${OUTPUT_DIR} is not a directory"
mkdir -p "${OUTPUT_DIR}"
LOG_FILE="${OUTPUT_DIR}/audit.log"

MAPPER=(uv run --project "${PROJECT_ROOT}" unifi-mapper)
if [[ -n "${CONFIG_PATH}" ]]; then
    MAPPER+=(--config "${CONFIG_PATH}")
fi

FAILED=()

step() {
    local name="$1"
    shift
    echo
    echo "== ${name}" | tee -a "${LOG_FILE}"
    if "${MAPPER[@]}" "$@" 2>&1 | tee -a "${LOG_FILE}"; then
        echo "-- ${name}: done" | tee -a "${LOG_FILE}"
    else
        echo "-- ${name}: FAILED (see ${LOG_FILE})" | tee -a "${LOG_FILE}"
        FAILED+=("${name}")
    fi
}

echo "Reports: ${OUTPUT_DIR}"
step "Port names (preview)" discover --dry-run --connected-devices -o "${OUTPUT_DIR}/port-mapping.md"
step "STP snapshot" stp snapshot -o "${OUTPUT_DIR}/stp-snapshot.json"
step "STP analysis" stp analyze
step "STP plan (preview)" stp optimize --dry-run --plan "${OUTPUT_DIR}/stp-plan.json"
step "STP guards" stp guard
step "STP report" stp report -o "${OUTPUT_DIR}/stp-report.md"
if [[ -n "${PLANNED_SWITCHES}" ]]; then
    step "10G readiness" stp validate-10g --planned-switches "${PLANNED_SWITCHES}"
fi

cat <<EOF

Review the reports in ${OUTPUT_DIR}, then apply only what you agree with.
Each command below previews first and writes only with its apply flag:
  uv run unifi-mapper ports refresh                          (add --apply to write port names)
  uv run unifi-mapper stp apply --plan ${OUTPUT_DIR}/stp-plan.json   (add --no-dry-run to apply)
Plan STP changes for a maintenance window: a priority change recalculates the topology.
EOF

if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo "network-audit: ${#FAILED[@]} step(s) failed: ${FAILED[*]}" >&2
    exit 1
fi
