#!/usr/bin/env bash
# Launch the unifi-mcp server for Claude Desktop (or any MCP client).
#
# Why a wrapper instead of putting credentials in claude_desktop_config.json:
#   - Secrets stay in ~/.config/unifi_management_cli/prod.env (chmod 600), not in an
#     app config file that gets copied around / screenshotted.
#   - GUI apps on macOS start with a minimal PATH, so `uv` is resolved explicitly.
#   - The repo's .env symlink is machine-specific; this resolves config per-user.
#
# Override the config file with UNIFI_MCP_ENV=/path/to/file.env
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# A relative XDG_CONFIG_HOME is invalid under the XDG Base Directory spec and is ignored, so
# the config is never read from under the working directory (issue 068).
CONFIG_HOME="$HOME/.config"
if [[ "${XDG_CONFIG_HOME:-}" == /* ]]; then
  CONFIG_HOME="$XDG_CONFIG_HOME"
fi
ENV_FILE="${UNIFI_MCP_ENV:-$CONFIG_HOME/unifi_management_cli/prod.env}"

if [[ ! -r "$ENV_FILE" ]]; then
  echo "unifi-mcp-launch: config not found or unreadable: $ENV_FILE" >&2
  echo "  Copy .env.example there and fill in UNIFI_URL + UNIFI_CONSOLE_API_TOKEN." >&2
  exit 1
fi

# Export every KEY=VALUE in the env file into this process (and the server it execs).
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

UV_BIN="$(command -v uv || true)"
for candidate in "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
  [[ -n "$UV_BIN" ]] && break
  [[ -x "$candidate" ]] && UV_BIN="$candidate"
done
if [[ -z "$UV_BIN" ]]; then
  echo "unifi-mcp-launch: uv not found (install: brew install uv)" >&2
  exit 1
fi

# stdout is the MCP stdio channel - nothing else may print to it before exec.
exec "$UV_BIN" --directory "$REPO_DIR" run --quiet unifi-mcp
