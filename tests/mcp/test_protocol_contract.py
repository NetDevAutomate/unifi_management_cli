"""T1: the MCP protocol contract, both surfaces, in memory, plus the SDK internals we use.

Runs under the autouse isolation fixture; fake handlers declare ``credentials: none``.
This file also runs under the unlocked isolated resolve (test_packaging.py), so the
SDK-internals pins fail loudly on an SDK that changed them.
"""

import inspect
import json
import jsonschema
import pydantic_core
import pytest
import re
from contextlib import asynccontextmanager
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import Tool
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, InitializeResult, TextContent
from pathlib import Path
from tests.mcp import fakes
from typing import Any
from unifi_mapper.mcp import server
from unifi_mapper.mcp.catalog import annotations_for
from unifi_mapper.mcp.registry import ToolRegistry
from unifi_mapper.mcp.runner import ToolRunner


META_NAMES = ['execute_tool', 'get_tool_info', 'list_categories', 'search_tools']
META_ARGS = {
    'search_tools': {'query', 'category', 'tags', 'detail_level'},
    'list_categories': set(),
    'get_tool_info': {'tool_name'},
    'execute_tool': {'tool_name', 'params'},
}
EXTRA = """  sampler:
    module: tests.mcp.fakes
    handler: int_param
    idempotent: false
    credentials: none
  pipeline_tool:
    module: tests.mcp.fakes
    handler: str_param
    pipeline: true
    credentials: none
  hidden_tool:
    module: tests.mcp.fakes
    handler: no_params
    mcp: false
    credentials: none
  writer:
    module: tests.mcp.fakes
    handler: no_params
    writes_local: true
    credentials: none
  pure_tool:
    module: tests.mcp.fakes
    handler: no_params
    open_world: false
    credentials: none
"""


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ToolRegistry:
    """Point the server at the fake manifest (plus the annotation-variant entries)."""
    fake = fakes.fake_registry(tmp_path, extra=EXTRA)
    monkeypatch.setattr(server, 'get_registry', lambda: fake)
    return fake


@asynccontextmanager
async def _session(mcp_server: FastMCP[Any]):
    """An initialised in-memory client session; yields (session, InitializeResult)."""
    results: list[InitializeResult] = []
    original = ClientSession.initialize

    async def _recording(self: ClientSession) -> InitializeResult:
        result = await original(self)
        results.append(result)
        return result

    ClientSession.initialize = _recording  # type: ignore[method-assign]
    try:
        async with create_connected_server_and_client_session(mcp_server._mcp_server) as s:
            yield s, results[0]
    finally:
        ClientSession.initialize = original  # type: ignore[method-assign]


def _expected_direct(registry: ToolRegistry) -> list[str]:
    names = [
        name
        for tools in registry.get_categories().values()
        for name in tools
        if (meta := registry.get_metadata(name))
        and not meta.mutates
        and meta.mcp
        and not meta.pipeline
    ]
    return sorted([*META_NAMES, *names])


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------


async def test_discovery_lists_exactly_the_four_meta_tools(registry) -> None:
    async with _session(server.create_server('discovery')) as (session, _):
        tools = (await session.list_tools()).tools
    assert [t.name for t in tools] == META_NAMES
    for tool in tools:
        assert set(tool.inputSchema.get('properties', {})) == META_ARGS[tool.name]
        assert tool.annotations == server.META_TOOLS[tool.name][1]


async def test_discovery_argument_types_are_unchanged(registry) -> None:
    async with _session(server.create_server('discovery')) as (session, _):
        tools = {t.name: t for t in (await session.list_tools()).tools}
    execute = tools['execute_tool'].inputSchema
    assert execute['required'] == ['tool_name']
    assert execute['properties']['tool_name']['type'] == 'string'
    assert tools['get_tool_info'].inputSchema['required'] == ['tool_name']
    assert tools['search_tools'].inputSchema['properties']['detail_level']['default'] == 'summary'


async def test_direct_lists_meta_tools_plus_every_listable_catalog_tool(registry) -> None:
    async with _session(server.create_server('direct')) as (session, _):
        tools = (await session.list_tools()).tools
    names = [t.name for t in tools]
    assert names == sorted(names) == _expected_direct(registry)
    for absent in ('apply_things', 'pipeline_tool', 'hidden_tool'):
        assert absent not in names


async def test_direct_annotations_are_computed_per_tool(registry) -> None:
    async with _session(server.create_server('direct')) as (session, _):
        tools = {t.name: t for t in (await session.list_tools()).tools}
    for name, tool in tools.items():
        if name in server.META_TOOLS:
            assert tool.annotations == server.META_TOOLS[name][1]
            continue
        meta = registry.get_metadata(name)
        assert meta is not None
        assert tool.annotations == annotations_for(meta), name
        assert tool.title == meta.title
    assert tools['sampler'].annotations.idempotentHint is False
    assert tools['writer'].annotations.readOnlyHint is False
    assert tools['writer'].annotations.idempotentHint is False
    assert tools['pure_tool'].annotations.openWorldHint is False
    read_port = tools['read_port'].annotations
    assert (
        read_port.readOnlyHint,
        read_port.destructiveHint,
        read_port.idempotentHint,
        read_port.openWorldHint,
    ) == (True, False, True, True)


@pytest.mark.parametrize('surface', ['discovery', 'direct'])
async def test_every_schema_is_valid_2020_12(registry, surface) -> None:
    async with _session(server.create_server(surface)) as (session, _):
        tools = (await session.list_tools()).tools
    for tool in tools:
        jsonschema.Draft202012Validator.check_schema(tool.inputSchema)
        if tool.outputSchema is not None:
            jsonschema.Draft202012Validator.check_schema(tool.outputSchema)


async def test_shipped_direct_listing_has_no_mutating_or_pipeline_tool() -> None:
    shipped = ToolRegistry(strict=True)
    direct = server.create_server('direct')
    listed = {t.name for t in await direct.list_tools()}
    for name in listed - set(META_NAMES):
        meta = shipped.get_metadata(name)
        assert meta is not None and not meta.mutates and not meta.pipeline and meta.mcp
    assert listed == set(_expected_direct(shipped))


# ---------------------------------------------------------------------------
# initialize: serverInfo and instructions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('surface', ['discovery', 'direct'])
async def test_server_info_and_instructions(registry, surface) -> None:
    async with _session(server.create_server(surface)) as (_, init):
        pass
    assert init.serverInfo.name == 'unifi-management'
    assert init.serverInfo.version == server.package_version()
    assert init.instructions
    for category in (
        'analysis',
        'connectivity',
        'diagnostics',
        'discovery',
        'network',
        'observability',
        'protect',
    ):
        assert category in init.instructions
    assert 'search_tools' in init.instructions and 'execute_tool' in init.instructions
    assert 'plan -> review -> apply' in init.instructions


def test_instructions_name_only_registered_link_tools() -> None:
    shipped = ToolRegistry(strict=True)
    text = server.build_instructions(shipped)
    for name in ('inspect_switch_port', 'audit_link_speeds', 'diagnose_switch_port'):
        assert (name in text) is (name in shipped), name
    assert server.mcp.instructions == text


# ---------------------------------------------------------------------------
# tools/call
# ---------------------------------------------------------------------------


async def test_direct_call_reaches_tool_runner(registry, monkeypatch) -> None:
    calls: list[tuple[str, Any, str]] = []
    original = ToolRunner.run

    async def spy(self: ToolRunner, name: str, params: Any, surface: str = 'execute_tool'):
        calls.append((name, params, surface))
        return await original(self, name, params, surface)  # type: ignore[arg-type]

    monkeypatch.setattr(ToolRunner, 'run', spy)
    async with _session(server.create_server('direct')) as (session, _):
        ok = await session.call_tool('read_port', {'switch': 'S', 'port': 1})
        bad = await session.call_tool('read_port', {'switch': 'S'})
    assert calls[:2] == [
        ('read_port', {'switch': 'S', 'port': 1}, 'direct'),
        ('read_port', {'switch': 'S'}, 'direct'),
    ]
    assert ok.isError is False and ok.structuredContent == {'a': 1}
    assert bad.isError is True
    assert isinstance(bad.content[0], TextContent)
    assert bad.content[0].text.startswith('[INVALID_PARAMETERS] invalid parameter(s): port')


async def test_mutating_tool_is_never_executed_on_the_direct_surface(registry) -> None:
    async with _session(server.create_server('direct')) as (session, _):
        out = await session.call_tool('apply_things', {})
        via_execute = await session.call_tool('execute_tool', {'tool_name': 'apply_things'})
    assert out.isError is True
    assert via_execute.isError is True
    assert via_execute.structuredContent['error_code'] == 'MUTATION_REFUSED'


@pytest.mark.parametrize('surface', ['discovery', 'direct'])
async def test_execute_tool_over_the_protocol(registry, surface) -> None:
    async with _session(server.create_server(surface)) as (session, _):
        ok = await session.call_tool(
            'execute_tool', {'tool_name': 'read_port', 'params': {'switch': 'S', 'port': 1}}
        )
        bad = await session.call_tool('execute_tool', {'tool_name': 'nope'})
    assert ok.isError is False and ok.structuredContent == {'ok': True, 'result': {'a': 1}}
    assert bad.isError is True and bad.structuredContent['error_code'] == 'TOOL_NOT_FOUND'
    for out in (ok, bad):
        [block] = out.content
        assert isinstance(block, TextContent)
        assert json.loads(block.text) == out.structuredContent
        assert (
            block.text
            == pydantic_core.to_json(out.structuredContent, fallback=str, indent=2).decode()
        )


async def test_get_tool_info_adds_annotations(registry) -> None:
    info = await server.get_tool_info('sampler')
    assert info is not None
    assert info['annotations']['idempotentHint'] is False
    assert info['annotations']['readOnlyHint'] is True
    mutating = await server.get_tool_info('apply_things')
    assert mutating is not None and mutating['annotations'] is None


# ---------------------------------------------------------------------------
# Resources and prompts
# ---------------------------------------------------------------------------


async def test_resources_are_listed_and_readable(registry) -> None:
    async with _session(server.create_server('discovery')) as (session, _):
        listed = {str(r.uri) for r in (await session.list_resources()).resources}
        catalog = await session.read_resource('unifi://catalog')  # type: ignore[arg-type]
        status = await session.read_resource('unifi://config/status')  # type: ignore[arg-type]
    assert listed == {'unifi://catalog', 'unifi://config/status'}
    catalog_json = json.loads(catalog.contents[0].text)  # type: ignore[union-attr]
    assert {t['name'] for t in catalog_json['tools']} == set(registry.get_categories()['fake'])
    assert 'fake' in catalog_json['categories']
    status_json = json.loads(status.contents[0].text)  # type: ignore[union-attr]
    assert status_json['source'] == 'none'
    assert set(status_json['families']) == {'controller', 'network_api', 'protect'}


async def test_prompts_are_listed(registry) -> None:
    async with _session(server.create_server('discovery')) as (session, _):
        prompts = {p.name: p for p in (await session.list_prompts()).prompts}
        stp = await session.get_prompt('plan_stp_change')
        port = await session.get_prompt(
            'troubleshoot_port_link', {'switch': 'USW Flex XG', 'port': '5'}
        )
    assert set(prompts) == {'troubleshoot_port_link', 'plan_stp_change'}
    assert {a.name for a in prompts['troubleshoot_port_link'].arguments or []} == {
        'switch',
        'port',
    }
    stp_text = stp.messages[0].content.text  # type: ignore[union-attr]
    assert 'unifi-mapper stp apply' in stp_text
    port_text = port.messages[0].content.text  # type: ignore[union-attr]
    # The fake registry has none of the port tools: only the far-end step remains.
    assert 'execute_tool(' not in port_text
    assert 'ethtool' in port_text and "'USW Flex XG'" in port_text


def test_port_prompt_names_only_registered_tools() -> None:
    text = server.troubleshoot_port_link('USW Flex XG', 5)
    shipped = ToolRegistry(strict=True)
    named = re.findall(r'execute_tool\("([a-z_0-9]+)"', text)
    assert named and all(name in shipped for name in named)
    assert 'inspect_switch_port' in named and 'diagnose_switch_port' in named
    assert '"switch": "USW Flex XG", "port": 5' in text


# ---------------------------------------------------------------------------
# Surface selection and importability
# ---------------------------------------------------------------------------


def test_default_surface_is_discovery() -> None:
    assert server.DEFAULT_SURFACE == 'discovery'
    assert isinstance(server.mcp, server.UnifiFastMCP)
    assert server.mcp.runner is None


@pytest.mark.parametrize(
    ('flag', 'env', 'expected'),
    [
        (None, {}, 'discovery'),
        ('direct', {}, 'direct'),
        (None, {'UNIFI_MCP_TOOL_SURFACE': 'Direct'}, 'direct'),
        ('discovery', {'UNIFI_MCP_TOOL_SURFACE': 'direct'}, 'discovery'),
        (None, {'UNIFI_MCP_TOOL_SURFACE': 'everything'}, 'discovery'),
    ],
)
def test_resolve_surface(flag, env, expected, capsys) -> None:
    assert server.resolve_surface(flag, env) == expected
    warned = 'is not one of' in capsys.readouterr().err
    assert warned is (env.get('UNIFI_MCP_TOOL_SURFACE') == 'everything')


def test_invalid_surface_flag_exits_2(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        server.main(['--surface', 'everything'])
    assert exc.value.code == 2


def test_surface_flag_runs_a_direct_server(registry, monkeypatch) -> None:
    ran: list[FastMCP[Any]] = []
    monkeypatch.setattr(FastMCP, 'run', lambda self, *a, **k: ran.append(self))
    monkeypatch.setattr(server, '_configure_logging', lambda level: None)
    monkeypatch.setattr(server, '_config_path', None)
    monkeypatch.setattr(server, '_settings', None)
    server.main(['--surface', 'DIRECT'])
    [direct] = ran
    assert isinstance(direct, server.UnifiFastMCP) and direct is not server.mcp
    assert direct.runner is not None and direct.runner.is_direct('read_port')


def test_module_level_names_stay_importable() -> None:
    from unifi_mapper.mcp import (
        ToolMetadata,
        ToolProxy,
        ToolRegistry,
        get_registry,
        list_categories,
        mcp,
        search_tools,
    )
    from unifi_mapper.mcp.server import execute_tool, get_tool_info

    assert mcp is server.mcp
    assert all(callable(f) for f in (get_registry, list_categories, search_tools, execute_tool))
    assert callable(get_tool_info) and ToolMetadata and ToolProxy and ToolRegistry


# ---------------------------------------------------------------------------
# SDK internals the runner and the server use (fail loudly on an SDK change)
# ---------------------------------------------------------------------------


def test_sdk_tool_internals() -> None:
    tool = Tool.from_function(fakes.read_port, structured_output=True)
    meta_fn = tool.fn_metadata
    parsed = meta_fn.arg_model.model_validate(meta_fn.pre_parse_json({'switch': 'S', 'port': '1'}))
    assert parsed.model_dump_one_level() == {'switch': 'S', 'port': 1}
    content, structured = meta_fn.convert_result({'a': 1})
    assert structured == {'a': 1} and content[0].text
    assert tool.fn is fakes.read_port
    assert tool.is_async is False
    assert set(tool.parameters['properties']) == {'switch', 'port'}
    assert Tool.from_function(fakes.returns_none).is_async is True


def test_sdk_server_version_attribute() -> None:
    assert server.mcp._mcp_server.version == server.package_version()


async def test_sdk_fastmcp_tools_kwarg_lists_prebuilt_tools() -> None:
    assert inspect.signature(FastMCP.__init__).parameters['tools'].kind is (
        inspect.Parameter.KEYWORD_ONLY
    )
    prebuilt = Tool.from_function(fakes.read_port, name='prebuilt_read_port')
    listed = await FastMCP('t', tools=[prebuilt]).list_tools()
    assert [t.name for t in listed] == ['prebuilt_read_port']


async def test_sdk_routes_tools_call_to_call_tool_and_passes_results_through() -> None:
    fixed = CallToolResult(
        content=[TextContent(type='text', text='fixed')],
        structuredContent={'k': 1},
        isError=True,
    )
    seen: list[str] = []

    class Routed(FastMCP[Any]):
        async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            seen.append(name)
            return fixed

    async with create_connected_server_and_client_session(Routed('t')._mcp_server) as s:
        out = await s.call_tool('anything', {})
    assert seen == ['anything']
    assert out.isError is True
    assert out.structuredContent == {'k': 1}
    assert out.content[0].text == 'fixed'  # type: ignore[union-attr]
