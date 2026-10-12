"""The one grammar for ``KEY=value`` lines in the project's env files.

Three readers parse the same files (the CLI's ``load_env_from_config``, ``UnifiConfig.from_env``
and the MCP server's ``parse_env_file``); they share this function so a value cannot mean one
thing to the CLI and another to the server. This module has no imports from the package and no
import-time side effects, so the MCP server can use it without pulling in the CLI's logging
set-up.
"""

from __future__ import annotations


def parse_env_value(raw: str) -> str:
    """Return the value of a ``KEY=raw`` env line as the dotenv grammar reads it.

    Surrounding single or double quotes are stripped and keep everything inside them, ``#``
    included. An unquoted value ends at the first ``#`` that follows whitespace, so a
    trailing comment is dropped while a bare ``#`` inside a password is kept.
    """
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    for i, ch in enumerate(value):
        if ch == '#' and i > 0 and value[i - 1].isspace():
            return value[:i].rstrip()
    return value
