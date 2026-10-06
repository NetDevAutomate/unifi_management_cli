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
    * So is a key that is, or ends in ``_`` followed by, ``community`` (the SNMP
      community string), ``syslog_key`` or ``lcm_tracker_seed``, in any case:
      ``snmp_community`` and ``my_syslog_key`` go, while ``community_id`` and
      ``syslog_key_id`` stay. Free text is matched on ``syslog_key`` and
      ``lcm_tracker_seed`` by the same rule, but not on ``community``, an
      ordinary word.
    * Bare ``key``, ``name`` and ``id`` keys are never removed. Event records
      use ``key`` for the event type.
    * A mapping whose ``key`` or ``name`` is a string naming a secret by the rules above
      (``{'key': 'api_token', 'value': …}``) loses its ``value`` too: such a pair holds
      the secret under an ordinary key, so the pair's name decides.
    * Values are not otherwise scanned. Free text that may quote a secret (exception
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
# Names that hold a credential although no keyword matches them: the whole key, or its end
# after an '_' (so snmp_community goes and community_id stays), in any case.
SUFFIX_SECRET_KEYS = ('community', 'syslog_key', 'lcm_tracker_seed')
_SUFFIX_SECRET_KEY_RE = re.compile(
    r'(?:^|_)(?:' + '|'.join(SUFFIX_SECRET_KEYS) + r')$', re.IGNORECASE
)
REDACTED = '***redacted***'
DEFAULT_TEXT_LIMIT = 300
# A mapping whose `key` or `name` names a secret holds that secret under `value`.
PAIR_NAME_KEYS = ('key', 'name')
PAIR_VALUE_KEY = 'value'

# A secret-looking name in free text: x_<anything>, <anything><keyword><anything>, or a name
# ending in syslog_key or lcm_tracker_seed (the suffix rule; community is an ordinary word),
# anchored so it starts at a key boundary rather than in the middle of a word like 'max_rate'.
_SECRET_NAME = (
    r'(?<![A-Za-z0-9_.\-])'
    r'(?:x_[A-Za-z0-9_.\-]*'
    r'|[A-Za-z0-9_.\-]*'
    r'(?:password|secret|token|authkey|psk|preshared|passphrase|api[_-]?key|private[_-]?key)'
    r'[A-Za-z0-9_.\-]*'
    r'|(?:[A-Za-z0-9_.\-]*_)?(?:syslog_key|lcm_tracker_seed)(?![A-Za-z0-9_.\-]))'
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
        True for keys starting with ``x_``, containing a secret keyword, or ending in one of
        the suffix names (``community``, ``syslog_key``, ``lcm_tracker_seed``) as the whole
        key or after an ``_``.
    """
    name = str(key)
    return (
        name.lower().startswith('x_')
        or bool(_SUFFIX_SECRET_KEY_RE.search(name))
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


def _names_a_secret(mapping: dict[Any, Any]) -> bool:
    """True when a mapping's ``key`` or ``name`` names a secret: its ``value`` holds it.

    A setting shaped ``{'key': 'api_token', 'value': '…'}`` (or with ``name``) keeps its
    secret under the ordinary key ``value``, so the pair's name decides.
    """
    return any(
        isinstance(mapping.get(field), str) and is_secret_key(mapping[field])
        for field in PAIR_NAME_KEYS
    )


def _strip(value: Any, path: str, removed: list[str]) -> Any:
    """Recursively copy ``value`` without secret keys, recording removed paths."""
    if isinstance(value, dict):
        pair_secret = _names_a_secret(value)
        clean: dict[Any, Any] = {}
        for key, item in value.items():
            child = f'{path}.{key}' if path else str(key)
            if is_secret_key(key) or (pair_secret and key == PAIR_VALUE_KEY):
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


TRACEBACK_LINE_LIMIT = 4000


def redact_traceback(error: BaseException, *, secret_values: frozenset[str] = frozenset()) -> str:
    """Format an exception's traceback with every line passed through :func:`redact_text`.

    Chained causes, exception groups and notes appear as :mod:`traceback` prints them; frame
    locals never do. For the ``--debug`` output of the argparse CLIs, and (with
    ``secret_values``) the MCP server's DEBUG log of a failed tool.

    Args:
        error: The exception being reported, usually the one an ``except`` caught.
        secret_values: Known secret values to replace in each whole line first, so one
            across the line cut leaves no fragment (the MCP server's).

    Returns:
        The traceback text, one redacted line per line (each at most
        ``TRACEBACK_LINE_LIMIT`` characters), ending in a newline.
    """
    import traceback

    ordered = _ordered(secret_values)
    text = ''.join(traceback.format_exception(error))
    return ''.join(
        redact_text(_replace_values(line, ordered), limit=TRACEBACK_LINE_LIMIT) + '\n'
        for line in text.splitlines()
    )


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
    container under such a key are masked the same way, and so is the ``value`` of a
    mapping whose ``key`` or ``name`` names a secret. Non-string values (booleans
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
        pair_secret = _names_a_secret(value)
        return {
            key: _mask(
                item,
                ordered,
                under_secret_key=under_secret_key
                or is_secret_key(key)
                or (pair_secret and key == PAIR_VALUE_KEY),
            )
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
