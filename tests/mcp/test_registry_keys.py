"""Manifest key validation, bad-file isolation and deterministic order (plan item 6)."""

import pytest
from loguru import logger
from pathlib import Path
from unifi_mapper.mcp.registry import (
    MANIFEST_KEYS,
    InvalidParamsError,
    ManifestError,
    MutationRefusedError,
    ToolMetadata,
    ToolRegistry,
    UnknownToolError,
    default_title,
)


GOOD = """
category: good
tools:
  zeta_tool:
    module: some.module
    description: Z
  alpha_tool:
    module: some.module
    description: A
"""


@pytest.fixture
def errors() -> list[str]:
    """Capture loguru messages at WARNING and above."""
    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(str(m)), level='WARNING', format='{level} {message}')
    yield seen
    logger.remove(sink)


def _write(tmp_path: Path, **files: str) -> Path:
    manifests = tmp_path / 'manifests'
    manifests.mkdir(exist_ok=True)
    for name, text in files.items():
        (manifests / f'{name}.yaml').write_text(text)
    return manifests


def _entry(extra: str) -> str:
    return f'category: c\ntools:\n  t:\n    module: some.module\n{extra}'


# ---------------------------------------------------------------------------
# Defaults and types
# ---------------------------------------------------------------------------


def test_new_keys_have_the_design_defaults(tmp_path: Path) -> None:
    meta = ToolRegistry(_write(tmp_path, c=_entry('')), strict=True).get_metadata('t')
    assert meta is not None
    assert meta.title == 'T'
    assert meta.writes_local is False
    assert meta.open_world is True
    assert meta.pipeline is False
    assert meta.mcp is True
    assert meta.aliases == {}
    assert meta.credentials == 'controller'
    assert meta.idempotent is True
    assert meta.active_probe is False


def test_default_title_is_the_name_title_cased() -> None:
    assert default_title('inspect_switch_port') == 'Inspect Switch Port'
    assert ToolMetadata('find_mac', 'm', 'h', 'd', 'c').title == 'Find Mac'
    assert ToolMetadata('find_mac', 'm', 'h', 'd', 'c', title='Find MAC').title == 'Find MAC'


def test_every_new_key_is_parsed(tmp_path: Path) -> None:
    extra = (
        '    title: Explicit Title\n    writes_local: true\n    open_world: false\n'
        '    pipeline: true\n    mcp: false\n    aliases: {old: new}\n'
        '    credentials: none\n    idempotent: false\n'
    )
    meta = ToolRegistry(_write(tmp_path, c=_entry(extra)), strict=True).get_metadata('t')
    assert meta is not None
    assert (meta.title, meta.writes_local, meta.open_world, meta.pipeline, meta.mcp) == (
        'Explicit Title',
        True,
        False,
        True,
        False,
    )
    assert meta.aliases == {'old': 'new'}
    assert meta.credentials == 'none'
    assert meta.idempotent is False


def test_active_probe_is_parsed(tmp_path: Path) -> None:
    meta = ToolRegistry(
        _write(tmp_path, c=_entry('    active_probe: true\n')), strict=True
    ).get_metadata('t')
    assert meta is not None
    assert meta.active_probe is True
    assert meta.mutates is False


def test_active_probe_beside_mutates_is_a_load_error(tmp_path: Path, errors: list[str]) -> None:
    # Issue 092: a probe sends traffic, a writer changes the controller; one entry is never both.
    manifests = _write(tmp_path, c=_entry('    active_probe: true\n    mutates: true\n'))
    with pytest.raises(ManifestError, match='active_probe and mutates'):
        len(ToolRegistry(manifests, strict=True))
    registry = ToolRegistry(manifests)
    assert 't' not in registry
    assert len([e for e in errors if e.startswith('ERROR')]) == 1


@pytest.mark.parametrize(
    'extra',
    [
        '    mutates: "yes"\n',
        '    title: 5\n',
        '    writes_local: 1\n',
        '    open_world: "false"\n',
        '    pipeline: []\n',
        '    mcp: null\n',
        '    aliases: [a, b]\n',
        '    aliases: {old: 3}\n',
        '    credentials: keychain\n',
        '    credentials: 1\n',
        '    idempotent: "no"\n',
        '    active_probe: "yes"\n',
        '    tags: [ok, 3]\n',
        '    tags: one\n',
        '    parameters: [x]\n',
    ],
)
def test_wrong_types_are_rejected(tmp_path: Path, extra: str, errors: list[str]) -> None:
    manifests = _write(tmp_path, c=_entry(extra))
    with pytest.raises(ManifestError):
        len(ToolRegistry(manifests, strict=True))
    registry = ToolRegistry(manifests)
    assert 't' not in registry
    assert len([e for e in errors if e.startswith('ERROR')]) == 1


def test_missing_module_is_a_bad_entry(tmp_path: Path) -> None:
    manifests = _write(tmp_path, c='category: c\ntools:\n  t:\n    description: no module\n')
    with pytest.raises(ManifestError, match='module is required'):
        len(ToolRegistry(manifests, strict=True))
    assert len(ToolRegistry(manifests)) == 0


# ---------------------------------------------------------------------------
# Key allow-list
# ---------------------------------------------------------------------------


def test_allow_list_covers_exactly_the_documented_keys() -> None:
    assert set(MANIFEST_KEYS) == {
        'module',
        'handler',
        'description',
        'priority',
        'tags',
        'parameters',
        'mutates',
        'title',
        'writes_local',
        'open_world',
        'pipeline',
        'mcp',
        'aliases',
        'credentials',
        'idempotent',
        'cli',
        'cli_gap',
        'active_probe',
    }


def test_unknown_key_raises_in_strict_mode(tmp_path: Path) -> None:
    manifests = _write(tmp_path, c=_entry('    mutate: true\n'))
    with pytest.raises(ManifestError, match='unknown key\\(s\\) mutate'):
        len(ToolRegistry(manifests, strict=True))


def test_unknown_key_is_a_warning_at_runtime(tmp_path: Path, errors: list[str]) -> None:
    registry = ToolRegistry(_write(tmp_path, c=_entry('    mutate: true\n')))
    assert 't' in registry
    assert registry.get_metadata('t').mutates is False  # the typo is not honoured
    assert len(errors) == 1 and errors[0].startswith('WARNING') and 'mutate' in errors[0]


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


def test_yaml_error_skips_only_that_file(tmp_path: Path, errors: list[str]) -> None:
    manifests = _write(tmp_path, bad='tools: [unclosed\n', good=GOOD)
    registry = ToolRegistry(manifests)
    assert len(registry) == 2
    assert [e for e in errors if e.startswith('ERROR')] == [
        next(e for e in errors if 'bad.yaml' in e)
    ]
    with pytest.raises(ManifestError, match='bad.yaml'):
        len(ToolRegistry(manifests, strict=True))


def test_bad_entry_skips_only_that_entry(tmp_path: Path, errors: list[str]) -> None:
    text = GOOD + '  broken: just-a-string\n'
    registry = ToolRegistry(_write(tmp_path, good=text))
    assert set(registry.get_categories()['good']) == {'zeta_tool', 'alpha_tool'}
    assert len(errors) == 1 and 'broken' in errors[0]


@pytest.mark.parametrize('text', ['- a\n- b\n', 'category: c\ntools: [a, b]\n'])
def test_malformed_structure_skips_the_file(tmp_path: Path, text: str) -> None:
    manifests = _write(tmp_path, bad=text, good=GOOD)
    assert len(ToolRegistry(manifests)) == 2
    with pytest.raises(ManifestError):
        len(ToolRegistry(manifests, strict=True))


def test_duplicate_name_in_a_later_file_is_skipped(tmp_path: Path, errors: list[str]) -> None:
    later = 'category: later\ntools:\n  alpha_tool:\n    module: other.module\n'
    manifests = _write(tmp_path, a_first=GOOD, b_later=later)
    registry = ToolRegistry(manifests)
    meta = registry.get_metadata('alpha_tool')
    assert meta is not None and meta.module == 'some.module' and meta.category == 'good'
    assert 'later' not in registry.get_categories()
    assert len(errors) == 1 and errors[0].startswith('ERROR') and 'alpha_tool' in errors[0]
    with pytest.raises(ManifestError, match='already defined'):
        len(ToolRegistry(manifests, strict=True))


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_files_load_in_sorted_order(tmp_path: Path) -> None:
    manifests = _write(
        tmp_path,
        z_last='category: zcat\ntools:\n  dup:\n    module: z.module\n',
        a_first='category: acat\ntools:\n  dup:\n    module: a.module\n',
    )
    meta = ToolRegistry(manifests).get_metadata('dup')
    assert meta is not None and meta.module == 'a.module'


def test_search_is_sorted_by_category_then_name(tmp_path: Path) -> None:
    other = 'category: aaa\ntools:\n  mmm_tool:\n    module: m\n  bbb_tool:\n    module: m\n'
    registry = ToolRegistry(_write(tmp_path, good=GOOD, other=other))
    names = [r['name'] for r in registry.search()]
    assert names == ['bbb_tool', 'mmm_tool', 'alpha_tool', 'zeta_tool']
    full = registry.search(detail_level='full')
    assert [(r['category'], r['name']) for r in full] == sorted(
        (r['category'], r['name']) for r in full
    )


def test_shipped_search_order_is_sorted() -> None:
    results = ToolRegistry(strict=True).search(detail_level='full')
    keys = [(r['category'], r['name']) for r in results]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# execute() exception classes
# ---------------------------------------------------------------------------


MANIFEST = """
category: test
tools:
  read_port:
    module: fake.mod
    parameters:
      switch: {type: string, required: true}
  apply_things:
    module: fake.mod
    mutates: true
"""


@pytest.fixture
def registry(tmp_path: Path) -> ToolRegistry:
    return ToolRegistry(_write(tmp_path, test=MANIFEST))


async def test_unknown_tool_raises_unknown_tool_error(registry: ToolRegistry) -> None:
    with pytest.raises(UnknownToolError) as info:
        await registry.execute('nope')
    assert isinstance(info.value, KeyError)


async def test_mutating_tool_raises_mutation_refused(registry: ToolRegistry) -> None:
    with pytest.raises(MutationRefusedError) as info:
        await registry.execute('apply_things')
    assert isinstance(info.value, PermissionError)


@pytest.mark.parametrize('params', [{}, {'switch': 's', 'colour': 'red'}])
async def test_bad_params_raise_invalid_params(registry: ToolRegistry, params: dict) -> None:
    with pytest.raises(InvalidParamsError) as info:
        await registry.execute('read_port', params)
    assert isinstance(info.value, ValueError)


def test_invalid_params_from_errors_renders_loc_and_msg() -> None:
    errors = [
        {'loc': ('port',), 'msg': 'Input should be a valid integer'},
        {'loc': ('topology', 'devices'), 'msg': 'Field required'},
    ]
    err = InvalidParamsError.from_errors(errors, input_schema={'type': 'object'})
    assert str(err) == (
        'invalid parameter(s): port (Input should be a valid integer); '
        'topology.devices (Field required)'
    )
    assert err.input_schema == {'type': 'object'}
