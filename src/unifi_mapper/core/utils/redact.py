"""Strip secrets from controller payloads before they are printed, logged or saved.

Controller records carry credentials in plain view: device ``x_authkey`` and SSH
keys, ``x_passphrase`` on WLAN and network configs, RADIUS secrets and so on.
Diagnostic output is meant to be attached to vendor tickets, so secrets are
removed outright (never masked) and only the dotted *paths* of what was removed
are reported. That proves the stripping was complete without leaking a value.

Rules:
    * A key is removed together with its value when it starts with ``x_`` or
      contains ``password``, ``secret``, ``token``, ``authkey``, ``psk``,
      ``preshared``, ``passphrase``, ``api_key`` or ``private_key``
      (case-insensitive). This applies at every depth, including dicts nested
      inside lists.
    * So is a key that is exactly ``community`` (the SNMP community string),
      ``syslog_key`` or ``lcm_tracker_seed``, in any case. These match the whole
      key only: ``community_id`` and ``snmp_community`` stay. Free text is not
      matched on them, because ``community`` is an ordinary word.
    * Bare ``key``, ``name`` and ``id`` keys are never removed. Event records
      use ``key`` for the event type.
    * Values are not scanned. Free text that may quote a secret (exception
      messages, HTTP response bodies) goes through :func:`redact_text` instead.

Example:
    clean, removed = strip_secrets({'name': 'sw', 'x_authkey': 'v'}, 'device')
    # clean == {'name': 'sw'}; removed == ['device.x_authkey']
"""

import re
from collections.abc import Mapping
from typing import Any


SECRET_KEY_RE = re.compile(
    r'password|secret|token|authkey|psk|preshared|passphrase|api[_-]?key|private[_-]?key',
    re.IGNORECASE,
)
# Whole keys that hold a credential although no keyword matches them (compared lower-cased).
_EXACT_SECRET_KEYS = frozenset({'community', 'syslog_key', 'lcm_tracker_seed'})
REDACTED = '***redacted***'
DEFAULT_TEXT_LIMIT = 300

# A secret-looking name in free text: either x_<anything> or <anything><keyword><anything>,
# anchored so it starts at a key boundary rather than in the middle of a word like 'max_rate'.
_SECRET_NAME = (
    r'(?<![A-Za-z0-9_.\-])'
    r'(?:x_[A-Za-z0-9_.\-]*'
    r'|[A-Za-z0-9_.\-]*'
    r'(?:password|secret|token|authkey|psk|preshared|passphrase|api[_-]?key|private[_-]?key)'
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
        True for keys starting with ``x_``, containing a secret keyword, or equal to one of
        the exact secret keys (``community``, ``syslog_key``, ``lcm_tracker_seed``).
    """
    name = str(key)
    lowered = name.lower()
    return (
        lowered.startswith('x_')
        or lowered in _EXACT_SECRET_KEYS
        or bool(SECRET_KEY_RE.search(name))
    )


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


# --- MCP masking (added for the MCP server; nothing above changes) ---------------------

MIN_SECRET_VALUE_LENGTH = 8
_SECRET_ENV_PREFIXES = ('UNIFI_', 'PROTECT_')


def _replace_values(text: str, ordered: tuple[str, ...]) -> str:
    """Replace every occurrence of each value in ``ordered`` (longest first) in ``text``."""
    for secret in ordered:
        if secret in text:
            text = text.replace(secret, REDACTED)
    return text


def _ordered(secret_values: frozenset[str]) -> tuple[str, ...]:
    """Return the non-empty secret values, longest first, so no fragment survives."""
    return tuple(sorted((v for v in secret_values if v), key=len, reverse=True))


def mask_secrets(value: Any, secret_values: frozenset[str]) -> Any:
    """Mask (not strip) secrets in a JSON-compatible value.

    A ``str`` under a key for which :func:`is_secret_key` is true becomes
    :data:`REDACTED`, at any depth (dicts inside lists included); strings nested inside a
    container under such a key are masked the same way. Non-string values (booleans
    such as ``x_has_ssh_hostkey``, numbers, ``None``) are left as they are, and keys
    are never removed, so a masked result stays valid against its output schema. Every
    occurrence of a value in ``secret_values`` inside any other string is replaced
    with :data:`REDACTED`. :func:`strip_secrets` stays the choice for evidence bundles.

    Args:
        value: Dicts, lists, tuples and scalars (the output of a JSON conversion).
        secret_values: Known secret values to mask wherever they appear.

    Returns:
        A new structure; the input is never mutated. Tuples come back as lists.
    """
    return _mask(value, _ordered(secret_values), under_secret_key=False)


def _mask(value: Any, ordered: tuple[str, ...], *, under_secret_key: bool) -> Any:
    """Recursively copy ``value`` with secret strings masked."""
    if isinstance(value, dict):
        return {
            key: _mask(item, ordered, under_secret_key=under_secret_key or is_secret_key(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_mask(item, ordered, under_secret_key=under_secret_key) for item in value]
    if isinstance(value, str):
        return REDACTED if under_secret_key else _replace_values(value, ordered)
    return value


def mask_secret_values(text: str, secret_values: frozenset[str], limit: int = 500) -> str:
    """Replace known secret values in free text with ``REDACTED``, then ``redact_text``.

    Values are replaced on the full text *before* :func:`redact_text` truncates, so a
    secret that straddles the truncation point can't survive as a fragment. ``limit``
    defaults to the strict 500-character cap, so a call site that doesn't choose gets
    the tighter bound.

    Args:
        text: Error message, suggestion or other free text.
        secret_values: Known secret values to mask.
        limit: Maximum length of the returned string.

    Returns:
        The masked text, at most ``limit`` characters long.
    """
    return redact_text(_replace_values(str(text), _ordered(secret_values)), limit=limit)


def mcp_secret_values(env: Mapping[str, str]) -> frozenset[str]:
    """Return the values to mask by value: credential keys only, length >= 8.

    Drawn from every ``UNIFI_*`` / ``PROTECT_*`` key that :func:`is_secret_key` accepts.
    That covers every credential-family key (controller, ``UNIFI_NETWORK_*``,
    ``PROTECT_*``) and never an unrelated variable, so a host's ``FOO_TOKEN=true`` can't
    turn every ``true`` in a result into a mask.

    Args:
        env: The environment, e.g. ``os.environ``.

    Returns:
        The secret values.
    """
    return frozenset(
        value
        for key, value in env.items()
        if key.startswith(_SECRET_ENV_PREFIXES)
        and is_secret_key(key)
        and isinstance(value, str)
        and len(value) >= MIN_SECRET_VALUE_LENGTH
    )
