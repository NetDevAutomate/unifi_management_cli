"""The ``network_api`` family with only the controller's config (issue 037).

A config file that sets ``UNIFI_URL``, ``UNIFI_SITE`` and ``UNIFI_CONSOLE_API_TOKEN`` but no
``UNIFI_NETWORK_*`` key used to leave the six Integration API tools ``CONFIG_MISSING``. Now the
host is derived from ``UNIFI_URL`` (same scheme, host and port), the site id is resolved at
first call from ``UNIFI_SITE``, and the console token stands in for the API key only when the
network host is the very same origin as ``UNIFI_URL``. Explicit keys always win.
"""

from __future__ import annotations

import os
import pytest
from tests.fixtures_unifi import FAKE_TOKEN
from unifi_mapper.network.config import (
    NetworkConfig,
    Origin,
    controller_origin,
    network_origin,
    resolve_network_env,
)


SITE_ID = '550e8400-e29b-41d4-a716-446655440000'
NET_KEY = 'FAKE-NETWORK-KEY'  # pragma: allowlist secret
CONTROLLER = {
    'UNIFI_URL': 'https://192.0.2.1',
    'UNIFI_SITE': 'home',
    'UNIFI_CONSOLE_API_TOKEN': FAKE_TOKEN,
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A fresh ``os.environ`` holding only what each test sets."""
    fresh: dict[str, str] = {}
    monkeypatch.setattr(os, 'environ', fresh)
    return fresh


# --- origins ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('url', 'expected'),
    [
        ('https://192.0.2.1', Origin('https', '192.0.2.1', 443)),
        ('https://Console.Example:8443/', Origin('https', 'console.example', 8443)),
        ('http://192.0.2.1', Origin('http', '192.0.2.1', 80)),
        ('192.0.2.1', Origin('https', '192.0.2.1', 443)),
        ('192.0.2.1:8443', Origin('https', '192.0.2.1', 8443)),
    ],
)
def test_controller_origin_normalises_unifi_url(url: str, expected: Origin) -> None:
    assert controller_origin({'UNIFI_URL': url}) == expected


def test_controller_origin_falls_back_to_unifi_host_and_port() -> None:
    assert controller_origin({'UNIFI_HOST': '192.0.2.1', 'UNIFI_PORT': '8443'}) == Origin(
        'https', '192.0.2.1', 8443
    )
    assert controller_origin({}) is None


def test_network_origin_is_explicit_host_else_the_controller() -> None:
    env = {
        **CONTROLLER,
        'UNIFI_NETWORK_HOST': 'https://other.example/',
        'UNIFI_NETWORK_PORT': '8443',
    }
    assert network_origin(env) == Origin('https', 'other.example', 8443)
    assert network_origin(dict(CONTROLLER)) == Origin('https', '192.0.2.1', 443)
    assert network_origin({}) is None


# --- from_env: host derived from UNIFI_URL --------------------------------------------------


def test_host_and_port_are_derived_from_unifi_url(env: dict[str, str]) -> None:
    env.update(
        {**CONTROLLER, 'UNIFI_URL': 'https://192.0.2.1:8443', 'UNIFI_NETWORK_API_KEY': NET_KEY}
    )
    config = NetworkConfig.from_env()
    assert (config.host, config.port, config.scheme) == ('192.0.2.1', 8443, 'https')
    assert config.base_url == 'https://192.0.2.1:8443'
    assert config.api_key.get_secret_value() == NET_KEY
    assert config.api_key_source == 'network'  # pragma: allowlist secret


def test_an_explicit_network_host_wins_over_unifi_url(env: dict[str, str]) -> None:
    env.update(
        {**CONTROLLER, 'UNIFI_NETWORK_HOST': 'other.example', 'UNIFI_NETWORK_API_KEY': NET_KEY}
    )
    config = NetworkConfig.from_env()
    assert (config.host, config.port) == ('other.example', 443)


def test_http_unifi_url_keeps_its_scheme_and_port(env: dict[str, str]) -> None:
    env.update({**CONTROLLER, 'UNIFI_URL': 'http://192.0.2.1', 'UNIFI_NETWORK_API_KEY': NET_KEY})
    config = NetworkConfig.from_env()
    assert config.base_url == 'http://192.0.2.1:80'


def test_without_either_host_the_error_names_both(env: dict[str, str]) -> None:
    env.update({'UNIFI_NETWORK_API_KEY': NET_KEY, 'UNIFI_NETWORK_SITE_ID': SITE_ID})
    with pytest.raises(
        ValueError, match='UNIFI_NETWORK_HOST environment variable is required'
    ) as e:
        NetworkConfig.from_env()
    assert 'UNIFI_URL' in str(e.value)


# --- from_env: the site id is resolved at first call ------------------------------------------


def test_without_a_site_id_the_site_name_is_carried_for_the_lookup(env: dict[str, str]) -> None:
    env.update({**CONTROLLER, 'UNIFI_NETWORK_API_KEY': NET_KEY})
    config = NetworkConfig.from_env()
    assert config.site_id is None
    assert config.site_name == 'home'


def test_unifi_site_defaults_to_default_like_the_controller_family(env: dict[str, str]) -> None:
    env.update({'UNIFI_URL': 'https://192.0.2.1', 'UNIFI_NETWORK_API_KEY': NET_KEY})
    assert NetworkConfig.from_env().site_name == 'default'


def test_an_explicit_site_id_is_used_as_given(env: dict[str, str]) -> None:
    env.update({**CONTROLLER, 'UNIFI_NETWORK_API_KEY': NET_KEY, 'UNIFI_NETWORK_SITE_ID': SITE_ID})
    config = NetworkConfig.from_env()
    assert config.site_id == SITE_ID
    assert config.site_name is None


def test_a_config_needs_a_site_id_or_a_site_name() -> None:
    with pytest.raises(ValueError, match='site_id or site_name'):
        NetworkConfig(host='192.0.2.1', api_key=NET_KEY)  # type: ignore[arg-type]


# --- from_env: the console token only for the same origin -----------------------------------


def test_console_token_is_used_when_the_network_host_is_the_console(env: dict[str, str]) -> None:
    env.update(CONTROLLER)
    config = NetworkConfig.from_env()
    assert config.api_key.get_secret_value() == FAKE_TOKEN
    assert config.api_key_source == 'console'  # pragma: allowlist secret
    assert config.get_headers()['X-API-KEY'] == FAKE_TOKEN


def test_console_token_is_used_for_an_explicit_host_that_is_the_same_origin(
    env: dict[str, str],
) -> None:
    env.update(
        {
            **CONTROLLER,
            'UNIFI_URL': 'https://Console.Example:8443',
            'UNIFI_NETWORK_HOST': 'console.example',
            'UNIFI_NETWORK_PORT': '8443',
        }
    )
    assert NetworkConfig.from_env().api_key_source == 'console'  # pragma: allowlist secret


@pytest.mark.parametrize(
    'network',
    [
        {'UNIFI_NETWORK_HOST': 'other.example'},  # another host
        {'UNIFI_NETWORK_HOST': '192.0.2.1', 'UNIFI_NETWORK_PORT': '8443'},  # another port
    ],
)
def test_console_token_never_goes_to_a_different_origin(
    env: dict[str, str], network: dict[str, str]
) -> None:
    env.update({**CONTROLLER, **network})
    with pytest.raises(
        ValueError, match='UNIFI_NETWORK_API_KEY environment variable is required'
    ) as e:
        NetworkConfig.from_env()
    assert FAKE_TOKEN not in str(e.value)
    assert 'origin' in str(e.value)


def test_an_explicit_network_key_wins_over_the_console_token(env: dict[str, str]) -> None:
    env.update({**CONTROLLER, 'UNIFI_NETWORK_API_KEY': NET_KEY})
    config = NetworkConfig.from_env()
    assert config.api_key.get_secret_value() == NET_KEY
    assert config.api_key_source == 'network'  # pragma: allowlist secret


# --- the offline resolution the readiness report uses -----------------------------------------


def test_resolution_reports_what_is_derived_and_what_is_missing() -> None:
    full = resolve_network_env(dict(CONTROLLER))
    assert full.missing == ()
    assert full.derived == (
        'host: derived from UNIFI_URL',
        'site id: resolved at first call',
        'key: console token (same origin)',
    )

    explicit = resolve_network_env(
        {
            'UNIFI_NETWORK_HOST': '192.0.2.1',
            'UNIFI_NETWORK_API_KEY': NET_KEY,
            'UNIFI_NETWORK_SITE_ID': SITE_ID,
        }
    )
    assert explicit.missing == () and explicit.derived == ()

    other_host = resolve_network_env({**CONTROLLER, 'UNIFI_NETWORK_HOST': 'other.example'})
    assert other_host.derived == ('site id: resolved at first call',)
    assert other_host.missing == (
        'UNIFI_NETWORK_API_KEY (UNIFI_CONSOLE_API_TOKEN is not for this origin)',
    )

    nothing = resolve_network_env({})
    assert nothing.missing == (
        'UNIFI_NETWORK_HOST or UNIFI_URL',
        'UNIFI_NETWORK_API_KEY or UNIFI_CONSOLE_API_TOKEN (same origin)',
        'UNIFI_NETWORK_SITE_ID or UNIFI_SITE',
    )
    assert FAKE_TOKEN not in repr(full)


def test_a_derived_host_inherits_the_controller_tls_setting(env: dict[str, str]) -> None:
    """Same origin, same TLS policy: UNIFI_VERIFY_SSL=true carries over to the derived client.

    Without this, the console token the family borrows from the controller could travel over an
    unverified TLS session that the controller family itself would verify.
    """
    env.update(CONTROLLER, UNIFI_VERIFY_SSL='true')
    assert NetworkConfig.from_env().verify_ssl is True


def test_a_derived_host_without_a_controller_tls_setting_keeps_the_default(
    env: dict[str, str],
) -> None:
    env.update(CONTROLLER)
    assert NetworkConfig.from_env().verify_ssl is False


def test_an_explicit_network_tls_setting_wins_over_the_inherited_one(env: dict[str, str]) -> None:
    env.update(CONTROLLER, UNIFI_VERIFY_SSL='true', UNIFI_NETWORK_VERIFY_SSL='false')
    assert NetworkConfig.from_env().verify_ssl is False


def test_an_explicit_network_host_does_not_inherit_the_controller_tls_setting(
    env: dict[str, str],
) -> None:
    """A different host is a different origin: the controller's TLS policy says nothing about it."""
    env.update(
        CONTROLLER,
        UNIFI_VERIFY_SSL='true',
        UNIFI_NETWORK_HOST='203.0.113.9',
        UNIFI_NETWORK_API_KEY=NET_KEY,
    )
    assert NetworkConfig.from_env().verify_ssl is False


def test_the_borrowed_console_token_inherits_the_tls_setting_with_an_explicit_host(
    env: dict[str, str],
) -> None:
    """The policy follows the token, not how the host was found (council pass B, finding M1).

    An explicit ``UNIFI_NETWORK_HOST`` that is the same origin as ``UNIFI_URL`` still borrows the
    console token, so the token must not travel over a session the controller family verifies.
    """
    env.update(CONTROLLER, UNIFI_VERIFY_SSL='true', UNIFI_NETWORK_HOST='192.0.2.1')
    config = NetworkConfig.from_env()
    assert config.api_key_source == 'console'  # pragma: allowlist secret
    assert config.verify_ssl is True


def test_a_network_owned_key_on_the_same_origin_keeps_the_family_default(
    env: dict[str, str],
) -> None:
    env.update(
        CONTROLLER,
        UNIFI_VERIFY_SSL='true',
        UNIFI_NETWORK_HOST='192.0.2.1',
        UNIFI_NETWORK_API_KEY=NET_KEY,
    )
    config = NetworkConfig.from_env()
    assert config.api_key_source == 'network'  # pragma: allowlist secret
    assert config.verify_ssl is False
