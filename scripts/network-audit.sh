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
# then prints the apply commands, each previewing first, with this run's --config and --project.
# A failed step is reported and the others still run; the exit status is 1 if any failed.
#
# Usage:
#   scripts/network-audit.sh [--config PATH] [--output-dir DIR] [--planned-switches N]
#
#   --config PATH         env file, passed as unifi-mapper's --config (default: its own
#                         search, UNIFI_CONFIG first)
#   --output-dir DIR      where the reports and audit.log go: a new directory, or an empty
#                         one of yours that no other user can write to and is not a link
#                         (default: ${XDG_STATE_HOME:-$HOME/.local/state}/unifi_mapper/audits/
#                         <UTC stamp>; a relative XDG_STATE_HOME is ignored)
#   --planned-switches N  also check 10G uplink readiness for N planned switches
#
# Example:
#   scripts/network-audit.sh --config ~/.config/unifi_management_cli/prod.env --planned-switches 3
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
    # The header from its first line up to the maintainers' "Rebuilt from" note, so no
    # option line is cut when the header grows.
    awk 'NR >= 3 && /^# Rebuilt from/ { exit } NR >= 3' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
    # A relative XDG_STATE_HOME is ignored, as the XDG spec says (it would be the cwd).
    STATE_HOME="${XDG_STATE_HOME:-}"
    [[ "${STATE_HOME}" == /* ]] || STATE_HOME="${HOME}/.local/state"
    OUTPUT_DIR="${STATE_HOME}/unifi_mapper/audits/${STAMP}"
fi
# The reports and audit.log describe the site: an existing --output-dir must be the user's
# own, writable by no one else, empty and not a symbolic link, so nothing planted there can
# receive them (a new directory is created private).
if [[ -L "${OUTPUT_DIR}" ]]; then
    die "--output-dir ${OUTPUT_DIR} is a symbolic link"
fi
if [[ -e "${OUTPUT_DIR}" ]]; then
    [[ -d "${OUTPUT_DIR}" ]] || die "--output-dir ${OUTPUT_DIR} is not a directory"
    [[ -O "${OUTPUT_DIR}" ]] || die "--output-dir ${OUTPUT_DIR} is not your directory"
    if [[ -n "$(find "${OUTPUT_DIR}" -maxdepth 0 \( -perm -020 -o -perm -002 \) -print)" ]]; then
        die "--output-dir ${OUTPUT_DIR} is writable by other users"
    fi
    [[ -z "$(ls -A "${OUTPUT_DIR}")" ]] || die "--output-dir ${OUTPUT_DIR} must be a new or empty directory"
fi
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

# The follow-up commands are built from the MAPPER the steps ran (--project and --config
# included) and shell-quoted, so a pasted command acts on the controller this audit read.
quoted() {
    local out
    printf -v out '%q ' "$@"
    printf '%s' "${out% }"
}
APPLY_PORTS="$(quoted "${MAPPER[@]}" ports refresh)"
APPLY_STP="$(quoted "${MAPPER[@]}" stp apply --plan "${OUTPUT_DIR}/stp-plan.json")"

cat <<EOF

Review the reports in ${OUTPUT_DIR}, then apply only what you agree with.
Each command below previews first and writes only with its apply flag.
Port names (add --apply to write them):
  ${APPLY_PORTS}
STP priorities (add --no-dry-run to apply the plan):
  ${APPLY_STP}
Plan STP changes for a maintenance window: a priority change recalculates the topology.
EOF

if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo "network-audit: ${#FAILED[@]} step(s) failed: ${FAILED[*]}" >&2
    exit 1
fi
