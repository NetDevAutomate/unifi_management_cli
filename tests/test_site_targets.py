"""The one-off site scripts read their targets from a file outside the repo (issue 046).

``scripts/apply_ap_channel_plan.py``, ``scripts/apply_stp_priorities_custom.py`` and
``scripts/remediate_stp_post_apply.py`` used to hard-code the site's device and port names.
They now read them through ``scripts/site_targets.py``, and must stop with exit code 2 before
they read the controller config or contact the controller when the file is missing or
malformed.

Nothing here reaches a controller: ``block_network`` fails any socket connect, and every
function that would read the config or the controller is replaced by one that fails the test.
``XDG_CONFIG_HOME`` points at a temporary directory, so the user's own targets file is never
read. ``scripts/`` is not an importable package, so the modules are loaded by path.
"""

from __future__ import annotations

import asyncio
import json
import pytest
import sys
from pathlib import Path
from tests.script_modules import load_script
from typing import Any, NoReturn
from unifi_mapper.core.models.stp import STPTopology, SwitchSTPConfig


# A site name that must never be echoed back in an error message.
SENTINEL = 'Sentinel Site Name'

pytestmark = pytest.mark.usefixtures('block_network')


@pytest.fixture
def targets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """``scripts/site_targets.py``, with ``XDG_CONFIG_HOME`` in a temporary directory."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg-config'))
    return load_script('site_targets', monkeypatch)


def _write(tmp_path: Path, data: object) -> Path:
    """Write ``data`` as a targets file and return its path."""
    path = tmp_path / 'site-targets.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


def _fail(*_args: object, **_kwargs: object) -> NoReturn:
    """Stand in for any config read or controller call: reaching one fails the test."""
    raise AssertionError('a site script went past its targets check')


# ─── The loader ──────────────────────────────────────────────────────────────


def test_example_file_holds_every_section_with_placeholders(targets: Any) -> None:
    """The shipped example loads for all three scripts and names no real device."""
    plan = targets.channel_plan(targets.EXAMPLE)
    priorities = targets.stp_priorities(targets.EXAMPLE)
    profile, ports = targets.post_apply_ports(targets.EXAMPLE)

    assert [name for name, _, _ in plan] == [f'AP-{n}' for n in range(1, 11)]
    assert set(priorities) == {
        'Switch A',
        'Switch B',
        'Gateway',
        'Switch C',
        'Switch D',
        'Switch E',
    }
    assert profile == 'Port profile name'
    assert ports == {'Switch A': {2: 'AP-1', 3: 'AP-2'}}


def test_missing_file_names_the_path_and_the_example(targets: Any, tmp_path: Path) -> None:
    """A missing file is reported with its path and the example to copy."""
    missing = tmp_path / 'nowhere.json'

    with pytest.raises(targets.TargetsError) as caught:
        targets.channel_plan(missing)

    assert str(missing) in str(caught.value)
    assert 'site-targets.example.json' in str(caught.value)


def test_default_path_follows_xdg_config_home(targets: Any, tmp_path: Path) -> None:
    """Without ``--targets`` the file is read from the XDG config directory."""
    config = tmp_path / 'config'
    expected = config / 'unifi_management_cli' / 'site-targets.json'
    environ = {'XDG_CONFIG_HOME': str(config)}
    expected.parent.mkdir(parents=True)
    expected.write_text(targets.EXAMPLE.read_text(encoding='utf-8'), encoding='utf-8')

    assert targets.default_path(environ) == expected
    assert len(targets.channel_plan(environ=environ)) == 10


def test_default_path_without_xdg_uses_the_home_config(
    targets: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With ``XDG_CONFIG_HOME`` unset the file is ``~/.config/unifi_management_cli/...``."""
    monkeypatch.setenv('HOME', str(tmp_path))

    assert targets.default_path({}) == (
        tmp_path / '.config' / 'unifi_management_cli' / 'site-targets.json'
    )


@pytest.mark.parametrize(
    'data',
    [
        {},
        {'apply_ap_channel_plan': []},
        {'apply_ap_channel_plan': {'channel_plan': []}},
        {'apply_ap_channel_plan': {'channel_plan': [[SENTINEL, 36]]}},
        {'apply_ap_channel_plan': {'channel_plan': [['', 36, '40']]}},
        {'apply_ap_channel_plan': {'channel_plan': [[SENTINEL, True, '40']]}},
        {'apply_ap_channel_plan': {'channel_plan': [[SENTINEL, -36, '40']]}},
        {'apply_ap_channel_plan': {'channel_plan': [[SENTINEL, 36, 40]]}},
        {'apply_ap_channel_plan': {'channel_plan': [[SENTINEL, 36, '45']]}},
    ],
)
def test_a_malformed_channel_plan_is_rejected(
    targets: Any, tmp_path: Path, data: dict[str, Any]
) -> None:
    """Each malformed plan raises TargetsError, and no message repeats a site name."""
    with pytest.raises(targets.TargetsError) as caught:
        targets.channel_plan(_write(tmp_path, data))

    assert SENTINEL not in str(caught.value)


def test_invalid_json_is_reported_with_its_line(targets: Any, tmp_path: Path) -> None:
    """A file that isn't JSON is reported, with the line where parsing failed."""
    path = tmp_path / 'site-targets.json'
    path.write_text('{\n  "apply_ap_channel_plan": \n', encoding='utf-8')

    with pytest.raises(targets.TargetsError, match='not valid JSON'):
        targets.channel_plan(path)


def test_a_file_that_is_not_utf8_is_reported(targets: Any, tmp_path: Path) -> None:
    """Bytes that aren't UTF-8 raise TargetsError, not a traceback, and echo no content."""
    path = tmp_path / 'site-targets.json'
    path.write_bytes(b'{"apply_ap_channel_plan": "' + SENTINEL.encode() + b'\xff"}')

    with pytest.raises(targets.TargetsError, match='not UTF-8') as caught:
        targets.channel_plan(path)

    assert SENTINEL not in str(caught.value)


@pytest.mark.parametrize(
    ('loader', 'section'),
    [
        ('stp_priorities', '{"priorities": {"%s": 4096, "%s": 8192}}'),
        ('post_apply_ports', '{"port_profile": "P", "ports": {"%s": {"2": "A", "2": "B"}}}'),
    ],
    ids=['stp-priorities', 'post-apply-ports'],
)
def test_a_key_repeated_in_one_object_is_rejected(
    targets: Any, tmp_path: Path, loader: str, section: str
) -> None:
    """``json`` keeps only the last of two equal keys, so the loader refuses the file."""
    name = {
        'stp_priorities': targets.STP_PRIORITIES,
        'post_apply_ports': targets.POST_APPLY,
    }[loader]
    body = section.replace('%s', SENTINEL)
    path = tmp_path / 'site-targets.json'
    path.write_text(f'{{"{name}": {body}}}', encoding='utf-8')

    with pytest.raises(targets.TargetsError, match='same key twice') as caught:
        getattr(targets, loader)(path)

    assert SENTINEL not in str(caught.value)


def test_a_port_number_written_two_ways_is_rejected(targets: Any, tmp_path: Path) -> None:
    """``"2"`` and ``"02"`` are both port 2, so one entry would silently replace the other."""
    section = {'port_profile': 'Profile', 'ports': {SENTINEL: {'2': 'AP-1', '02': 'AP-2'}}}

    with pytest.raises(targets.TargetsError, match='listed twice') as caught:
        targets.post_apply_ports(_write(tmp_path, {'remediate_stp_post_apply': section}))

    assert SENTINEL not in str(caught.value)


@pytest.mark.parametrize('priority', [4097, 65536, -4096, True, '4096'])
def test_a_malformed_stp_priority_is_rejected(
    targets: Any, tmp_path: Path, priority: object
) -> None:
    """A priority that isn't a multiple of 4096 from 0 to 61440 raises TargetsError."""
    data = {'apply_stp_priorities_custom': {'priorities': {SENTINEL: priority}}}

    with pytest.raises(targets.TargetsError) as caught:
        targets.stp_priorities(_write(tmp_path, data))

    assert SENTINEL not in str(caught.value)


@pytest.mark.parametrize(
    'section',
    [
        {'ports': {SENTINEL: {'2': 'AP-1'}}},
        {'port_profile': ' ', 'ports': {SENTINEL: {'2': 'AP-1'}}},
        {'port_profile': 'Profile', 'ports': {}},
        {'port_profile': 'Profile', 'ports': {SENTINEL: {}}},
        {'port_profile': 'Profile', 'ports': {SENTINEL: {'0': 'AP-1'}}},
        {'port_profile': 'Profile', 'ports': {SENTINEL: {'two': 'AP-1'}}},
        {'port_profile': 'Profile', 'ports': {SENTINEL: {'2': ''}}},
    ],
)
def test_malformed_post_apply_ports_are_rejected(
    targets: Any, tmp_path: Path, section: dict[str, Any]
) -> None:
    """A missing profile, an empty table or a bad port number or name raises TargetsError."""
    with pytest.raises(targets.TargetsError) as caught:
        targets.post_apply_ports(_write(tmp_path, {'remediate_stp_post_apply': section}))

    assert SENTINEL not in str(caught.value)


# ─── Each script stops before the controller ─────────────────────────────────


def _run(module: Any, argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    """Run a script's ``main`` with ``argv`` and return its exit code."""
    monkeypatch.setattr(sys, 'argv', argv)
    return asyncio.run(module.main())


def test_channel_plan_script_stops_without_a_targets_file(
    targets: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No targets file: exit 2, naming the default path, before any config read."""
    mod = load_script('apply_ap_channel_plan', monkeypatch)
    monkeypatch.setattr(mod, 'load_config', _fail)
    monkeypatch.setattr(mod, '_load_aps', _fail)

    assert _run(mod, ['apply_ap_channel_plan.py'], monkeypatch) == 2
    assert str(targets.default_path()) in capsys.readouterr().out


def test_channel_plan_script_refuses_a_self_colliding_plan(
    targets: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A plan whose entries share a 40MHz block stops with exit 2 before any config read."""
    mod = load_script('apply_ap_channel_plan', monkeypatch)
    monkeypatch.setattr(mod, 'load_config', _fail)
    monkeypatch.setattr(mod, '_load_aps', _fail)
    plan = {'channel_plan': [['AP-1', 157, '40'], ['AP-2', 161, '40']]}
    path = _write(tmp_path, {'apply_ap_channel_plan': plan})

    assert _run(mod, ['apply_ap_channel_plan.py', '--targets', str(path)], monkeypatch) == 2
    assert 'self-inconsistent' in capsys.readouterr().out


def test_stp_priorities_script_stops_without_a_targets_file(
    targets: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No targets file: exit 2 before the STP topology is read from the controller."""
    mod = load_script('apply_stp_priorities_custom', monkeypatch)
    monkeypatch.setattr(mod, 'discover_stp_topology', _fail)
    missing = tmp_path / 'missing.json'

    argv = ['apply_stp_priorities_custom.py', '--targets', str(missing)]
    assert _run(mod, argv, monkeypatch) == 2
    assert str(missing) in capsys.readouterr().out


def test_post_apply_script_stops_without_a_targets_file(
    targets: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No targets file: exit 2 before the controller config or the topology is read."""
    mod = load_script('remediate_stp_post_apply', monkeypatch)
    monkeypatch.setattr(mod, 'load_env_from_config', _fail)
    monkeypatch.setattr(mod, 'discover_stp_topology', _fail)
    missing = tmp_path / 'missing.json'

    argv = ['remediate_stp_post_apply.py', '--targets', str(missing)]
    assert _run(mod, argv, monkeypatch) == 2
    assert str(missing) in capsys.readouterr().out


# ─── The STP script applies the intended root first ──────────────────────────


def test_stp_changes_put_the_root_first_whatever_the_file_order(
    targets: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``build_changes`` returns the lowest priority first, and the preview shows that order.

    ``apply_stp_changes`` writes and provisions one switch at a time, in list order, so the
    intended root must come first. The example's keys are alphabetical (the
    ``pretty-format-json`` hook sorts them), so the order of the file is not the apply order.
    """
    mod = load_script('apply_stp_priorities_custom', monkeypatch)
    priorities = dict(sorted(targets.stp_priorities(targets.EXAMPLE).items()))
    root = min(priorities, key=priorities.__getitem__)
    assert next(iter(priorities)) != root, 'the premise: the first key is not the root'
    switches = [
        SwitchSTPConfig(device_id=f'device-{n}', name=name, mac='')
        for n, name in enumerate(priorities, 1)
    ]

    async def _topology() -> STPTopology:
        """Every switch at the default priority, so every one of them changes."""
        return STPTopology(switches=switches)

    monkeypatch.setattr(mod, 'discover_stp_topology', _topology)
    monkeypatch.setattr(mod, 'apply_stp_changes', _fail)

    changes = asyncio.run(mod.build_changes(priorities))
    mod.render_diff(changes)

    order = [c.device_name for c in changes]
    assert order[0] == root
    assert order == sorted(priorities, key=lambda name: (priorities[name], name))
    rows = [line for line in capsys.readouterr().out.splitlines()[2:] if line.strip()]
    assert [row[:42].strip() for row in rows] == order
