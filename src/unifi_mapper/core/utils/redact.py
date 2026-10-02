"""Strip secrets from controller payloads before they are printed, logged or saved.

Controller records carry credentials in plain view: device ``x_authkey`` and SSH
keys, ``x_passphrase`` on WLAN and network configs, RADIUS secrets and so on.
Diagnostic output is meant to be attached to vendor tickets, so secrets are
removed outright (never masked) and only the dotted *paths* of what was removed
are reported. That proves the stripping was complete without leaking a value.

Rules:
    * A key is removed together with its value when it starts with ``x_`` or
      contains ``password``, ``secret``, ``token``, ``authkey``, ``psk``,
      ``passphrase``, ``api_key`` or ``private_key`` (case-insensitive). This
      applies at every depth, including dicts nested inside lists.
    * Bare ``key``, ``name`` and ``id`` keys are never removed. Event records
      use ``key`` for the event type.
    * Values are not scanned. Free text that may quote a secret (exception
      messages, HTTP response bodies) goes through :func:`redact_text` instead.

Example:
    clean, removed = strip_secrets({'name': 'sw', 'x_authkey': 'v'}, 'device')
    # clean == {'name': 'sw'}; removed == ['device.x_authkey']
"""

import re
from typing import Any


SECRET_KEY_RE = re.compile(
    r'password|secret|token|authkey|psk|passphrase|api[_-]?key|private[_-]?key',
    re.IGNORECASE,
)
REDACTED = '***redacted***'
DEFAULT_TEXT_LIMIT = 300

# A secret-looking name in free text: either x_<anything> or <anything><keyword><anything>,
# anchored so it starts at a key boundary rather than in the middle of a word like 'max_rate'.
_SECRET_NAME = (
    r'(?<![A-Za-z0-9_.\-])'
    r'(?:x_[A-Za-z0-9_.\-]*'
    r'|[A-Za-z0-9_.\-]*'
    r'(?:password|secret|token|authkey|psk|passphrase|api[_-]?key|private[_-]?key)'
    r'[A-Za-z0-9_.\-]*)'
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r'(?P<prefix>["\']?' + _SECRET_NAME + r'["\']?\s*[=:]\s*)'
    r'(?P<value>"[^"]*"|\'[^\']*\'|[^\s,;&}\]]+)',
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r'(?P<prefix>\bBearer\s+)(?P<value>[^\s,;"\']+)', re.IGNORECASE)


def is_secret_key(key: object) -> bool:
    """Return True if a mapping key names a secret that must be removed.

    Args:
        key: The mapping key. Non-string keys are compared by their ``str()``.

    Returns:
        True for keys starting with ``x_`` or containing a secret keyword.
    """
    name = str(key)
    return name.lower().startswith('x_') or bool(SECRET_KEY_RE.search(name))


def strip_secrets(value: Any, path: str = '') -> tuple[Any, list[str]]:
    """Return a copy of ``value`` with every secret key removed, plus what was removed.

    Args:
        value: Any JSON-like structure (dicts, lists, tuples, scalars).
        path: Dotted prefix for the reported paths, e.g. ``'device.raw'``.

    Returns:
        A ``(clean, removed_paths)`` tuple. ``clean`` is a new structure; the
        input is never mutated. ``removed_paths`` lists dotted paths with
        ``[i]`` list indices (key names only, never values).
    """
    removed: list[str] = []
    return _strip(value, path, removed), removed


def _strip(value: Any, path: str, removed: list[str]) -> Any:
    """Recursively copy ``value`` without secret keys, recording removed paths."""
    if isinstance(value, dict):
        clean: dict[Any, Any] = {}
        for key, item in value.items():
            child = f'{path}.{key}' if path else str(key)
            if is_secret_key(key):
                removed.append(child)
                continue
            clean[key] = _strip(item, child, removed)
        return clean
    if isinstance(value, (list, tuple)):
        return [_strip(item, f'{path}[{index}]', removed) for index, item in enumerate(value)]
    return value


def redact_text(text: object, limit: int = DEFAULT_TEXT_LIMIT) -> str:
    """Mask secret values quoted in free text, then truncate it.

    Replaces the value in any ``<secret-name>=<value>`` or ``<secret-name>: <value>``
    pattern (quoted or not) and any ``Bearer <token>`` with ``***redacted***``.

    Args:
        text: Error message, HTTP body or other free text.
        limit: Maximum length of the returned string.

    Returns:
        The redacted text, at most ``limit`` characters long.
    """
    # Only the first `limit` characters survive, so bound the regex work up front. The
    # margin keeps a secret that starts inside the kept window matched in full.
    bounded = str(text)[: max(limit, 0) * 10 + 200]
    redacted = _SECRET_ASSIGNMENT_RE.sub(lambda m: m.group('prefix') + REDACTED, bounded)
    redacted = _BEARER_RE.sub(lambda m: m.group('prefix') + REDACTED, redacted)
    if len(redacted) > limit:
        redacted = redacted[: max(0, limit - 1)] + '…'
    return redacted
