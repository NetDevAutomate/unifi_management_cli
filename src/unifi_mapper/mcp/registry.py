"""Tool registry for UniFi Management MCP Server.

Implements lazy loading of tool definitions from YAML manifests,
following the Code Mode architecture pattern for progressive tool discovery.

Manifest entries are validated when they load: every key must be in
:data:`MANIFEST_KEYS` and every value must have the documented type. A bad file or
entry is skipped with one ERROR log (``ToolRegistry(strict=True)``, used by tests,
raises :class:`ManifestError` instead), so one broken manifest can't break every
tool call.
"""

from __future__ import annotations

import importlib
import importlib.resources
import yaml
from dataclasses import dataclass, field
from loguru import logger
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Literal, get_args


def default_manifests_dir() -> Path:
    """Return the manifests directory shipped inside the installed package.

    Resolved through ``importlib.resources`` rather than ``__file__`` so it follows the
    installed ``unifi_mapper.mcp`` package (wheel, uv tool or uvx environment).

    Returns:
        The ``unifi_mapper/mcp/manifests`` directory.
    """
    return Path(str(importlib.resources.files('unifi_mapper.mcp') / 'manifests'))


CredentialFamily = Literal['controller', 'network_api', 'protect', 'none']
CREDENTIAL_FAMILIES: tuple[str, ...] = get_args(CredentialFamily)

# Every key a manifest tool entry may carry, with the type its value must have.
MANIFEST_KEYS: dict[str, type | tuple[type, ...]] = {
    'module': str,
    'handler': str,
    'description': str,
    'priority': str,
    'tags': list,
    'parameters': dict,
    'mutates': bool,
    'title': str,
    'writes_local': bool,
    'open_world': bool,
    'pipeline': bool,
    'mcp': bool,
    'aliases': dict,
    'credentials': str,
    'idempotent': bool,
    'cli': str,
    'cli_gap': str,
}


class ManifestError(ValueError):
    """A manifest file or entry is malformed (raised only by ``ToolRegistry(strict=True)``)."""


class UnknownToolError(KeyError):
    """No tool is registered under the requested name."""


class MutationRefusedError(PermissionError):
    """The tool changes live controller state and mutation was not allowed."""


class InvalidParamsError(ValueError):
    """The supplied parameters don't match the tool.

    Attributes:
        input_schema: The tool's JSON input schema, when known (for the error payload).
    """

    def __init__(self, message: str, *, input_schema: dict[str, Any] | None = None) -> None:
        """Build the error.

        Args:
            message: What is wrong, naming parameters only (never their values).
            input_schema: The tool's JSON input schema, if known.
        """
        super().__init__(message)
        self.input_schema = input_schema

    @classmethod
    def from_errors(
        cls, errors: list[Any], *, input_schema: dict[str, Any] | None = None
    ) -> InvalidParamsError:
        """Build the error from pydantic ``ValidationError.errors()`` (without inputs).

        Each field error renders as ``loc (msg)``, never ``loc: msg``, so free-text
        redaction can't rewrite the message for a parameter whose name looks secret.

        Args:
            errors: ``e.errors(include_input=False, include_url=False)``.
            input_schema: The tool's JSON input schema.

        Returns:
            The error.
        """
        parts = [
            f'{".".join(str(p) for p in err.get("loc", ())) or "params"} ({err.get("msg", "")})'
            for err in errors
        ]
        return cls(f'invalid parameter(s): {"; ".join(parts)}', input_schema=input_schema)


def default_title(name: str) -> str:
    """Return the default ``title`` for a tool: its name, title-cased.

    Args:
        name: The tool name, e.g. ``inspect_switch_port``.

    Returns:
        E.g. ``'Inspect Switch Port'``.
    """
    return name.replace('_', ' ').title()


@dataclass
class ToolMetadata:
    """Metadata for a registered tool."""

    name: str
    module: str
    handler: str
    description: str
    category: str
    priority: str = 'P2'
    tags: list[str] = field(default_factory=lambda: [])
    parameters: dict[str, Any] = field(default_factory=lambda: {})
    # True for tools that change live controller state (STP priorities, radio config, ...).
    # The MCP execute_tool meta-tool refuses these; they must go through the CLI's
    # plan -> review -> apply flow. Declared per tool in the YAML manifests.
    mutates: bool = False
    # Human-readable Tool.title; empty means the name, title-cased.
    title: str = ''
    # Writes a local file (e.g. a snapshot under reports/).
    writes_local: bool = False
    # Talks to an external system (annotation only).
    open_world: bool = True
    # A required parameter is a pipeline model (STPTopology, ...); not listed directly.
    pipeline: bool = False
    # Listed on the direct MCP surface.
    mcp: bool = True
    # Deprecated parameter name -> canonical (handler) parameter name.
    aliases: dict[str, str] = field(default_factory=lambda: {})
    # Credential family the MCP gate checks before running the tool.
    credentials: str = 'controller'
    # idempotentHint; false for wall-clock sampling or long-blocking tools.
    idempotent: bool = True
    # The unifi-mapper command this tool is the counterpart of (surface parity, issue 078)...
    cli: str = ''
    # ...or why there is none ("category: detail", see unifi_mapper.mcp.parity).
    cli_gap: str = ''

    def __post_init__(self) -> None:
        """Fill the default title."""
        if not self.title:
            self.title = default_title(self.name)


def _check_entry(tool_name: str, tool_data: Any) -> tuple[dict[str, Any], list[str]]:
    """Validate one manifest entry's types; return it plus any unknown key names.

    Args:
        tool_name: The entry's name.
        tool_data: The entry's mapping as loaded from YAML.

    Returns:
        ``(entry, unknown_keys)``.

    Raises:
        ManifestError: The entry is not a mapping, lacks ``module``, or a value has the
            wrong type.
    """
    if not isinstance(tool_name, str) or not tool_name:
        raise ManifestError(f'tool name {tool_name!r} is not a non-empty string')
    if not isinstance(tool_data, dict):
        raise ManifestError(f'{tool_name}: entry is not a mapping')
    unknown = sorted(str(k) for k in tool_data if k not in MANIFEST_KEYS)
    for key, expected in MANIFEST_KEYS.items():
        if key in tool_data and not isinstance(tool_data[key], expected):
            raise ManifestError(
                f'{tool_name}: {key} must be {_type_name(expected)}, '
                f'not {type(tool_data[key]).__name__}'
            )
    if not tool_data.get('module'):
        raise ManifestError(f'{tool_name}: module is required')
    if not all(isinstance(t, str) for t in tool_data.get('tags', [])):
        raise ManifestError(f'{tool_name}: tags must be a list of strings')
    aliases = tool_data.get('aliases', {})
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in aliases.items()):
        raise ManifestError(f'{tool_name}: aliases must map strings to strings')
    if tool_data.get('credentials', 'controller') not in CREDENTIAL_FAMILIES:
        raise ManifestError(
            f'{tool_name}: credentials must be one of {", ".join(CREDENTIAL_FAMILIES)}'
        )
    return tool_data, unknown


def _type_name(expected: type | tuple[type, ...]) -> str:
    """Return a readable name for an expected type."""
    if isinstance(expected, tuple):
        return ' or '.join(t.__name__ for t in expected)
    return expected.__name__


class ToolProxy:
    """Proxy for lazy loading tool implementations.

    Delays loading the actual tool implementation until first execution,
    reducing startup time and memory usage.
    """

    def __init__(self, metadata: ToolMetadata) -> None:
        """Initialize a tool proxy with metadata."""
        self.metadata = metadata
        self._implementation: Callable[..., Any] | None = None
        self._lock = Lock()

    def _load_implementation(self) -> None:
        """Load the tool implementation from its module."""
        if self._implementation is not None:
            return

        with self._lock:
            if self._implementation is not None:
                return

            module = importlib.import_module(self.metadata.module)
            self._implementation = getattr(module, self.metadata.handler)

    async def execute(self, **params: Any) -> Any:
        """Execute the tool with the given parameters."""
        self._load_implementation()
        assert self._implementation is not None

        result = self._implementation(**params)
        # Handle both sync and async implementations
        if hasattr(result, '__await__'):
            return await result
        return result

    @property
    def is_loaded(self) -> bool:
        """Check if the tool implementation has been loaded."""
        return self._implementation is not None


class ToolRegistry:
    """Central registry for UniFi management tools.

    Loads tool metadata from YAML manifests and provides:
    - Progressive tool discovery via search()
    - Lazy loading of tool implementations
    - Category-based organization
    """

    def __init__(self, manifests_dir: Path | None = None, *, strict: bool = False) -> None:
        """Initialize the tool registry.

        Args:
            manifests_dir: Directory of ``*.yaml`` manifests; defaults to the shipped one.
            strict: Raise :class:`ManifestError` on any manifest problem (unknown key,
                bad type, YAML error, duplicate name) instead of logging and skipping.
        """
        self._manifests_dir = manifests_dir or default_manifests_dir()
        self._strict = strict
        self._metadata: dict[str, ToolMetadata] = {}
        self._categories: dict[str, list[str]] = {}
        self._proxies: dict[str, ToolProxy] = {}
        self._lock = Lock()
        self._loaded = False

    def _load_manifests(self) -> None:
        """Load all tool manifests from the manifests directory."""
        if self._loaded:
            return

        with self._lock:
            if self._loaded:
                return

            if not self._manifests_dir.exists():
                self._loaded = True
                return

            for manifest_file in sorted(self._manifests_dir.glob('*.yaml')):
                self._load_manifest(manifest_file)

            self._loaded = True

    def _reject(self, message: str) -> None:
        """Raise in strict mode; otherwise log one ERROR (the caller skips the input)."""
        if self._strict:
            raise ManifestError(message)
        logger.error('MCP manifest: {}; skipped', message)

    def _load_manifest(self, manifest_file: Path) -> None:
        """Load a single manifest file, isolating a bad file or entry."""
        try:
            with open(manifest_file) as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as e:
            self._reject(f'{manifest_file.name}: cannot be read ({type(e).__name__})')
            return

        if not data:
            return
        if not isinstance(data, dict):
            self._reject(f'{manifest_file.name}: top level must be a mapping')
            return
        if not data.get('tools'):
            return
        if not isinstance(data['tools'], dict):
            self._reject(f'{manifest_file.name}: tools must be a mapping')
            return

        category = data.get('category', manifest_file.stem)
        if not isinstance(category, str):
            self._reject(f'{manifest_file.name}: category must be a string')
            return

        for tool_name, tool_data in data['tools'].items():
            try:
                entry, unknown = _check_entry(tool_name, tool_data)
            except ManifestError as e:
                self._reject(f'{manifest_file.name}: {e}')
                continue
            if unknown:
                message = f'{manifest_file.name}: {tool_name}: unknown key(s) {", ".join(unknown)}'
                if self._strict:
                    raise ManifestError(message)
                logger.warning('MCP manifest: {}; ignored', message)
            if tool_name in self._metadata:
                self._reject(
                    f'{manifest_file.name}: {tool_name} is already defined in category '
                    f'{self._metadata[tool_name].category!r}'
                )
                continue
            metadata = ToolMetadata(
                name=tool_name,
                category=category,
                module=entry['module'],
                handler=entry.get('handler', tool_name),
                description=entry.get('description', ''),
                priority=entry.get('priority', 'P2'),
                tags=list(entry.get('tags', [])),
                parameters=dict(entry.get('parameters', {})),
                mutates=entry.get('mutates', False),
                title=entry.get('title', ''),
                writes_local=entry.get('writes_local', False),
                open_world=entry.get('open_world', True),
                pipeline=entry.get('pipeline', False),
                mcp=entry.get('mcp', True),
                aliases=dict(entry.get('aliases', {})),
                credentials=entry.get('credentials', 'controller'),
                idempotent=entry.get('idempotent', True),
                cli=entry.get('cli', ''),
                cli_gap=entry.get('cli_gap', ''),
            )
            self._metadata[tool_name] = metadata
            self._categories.setdefault(category, []).append(tool_name)

    def search(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        detail_level: str = 'summary',
    ) -> list[dict[str, Any]]:
        """Search tools with progressive disclosure.

        Args:
            query: Text search in tool names and descriptions
            category: Filter by category
            tags: Filter by tags (match any)
            detail_level: "summary" (name + description) or "full" (includes parameters)

        Returns:
            List of matching tools with requested detail level, sorted by
            ``(category, name)``.
        """
        self._load_manifests()

        results: list[dict[str, Any]] = []

        for name, meta in sorted(self._metadata.items(), key=lambda i: (i[1].category, i[0])):
            # Filter by category
            if category and meta.category != category:
                continue

            # Filter by tags (match any)
            if tags and not any(t in meta.tags for t in tags):
                continue

            # Filter by query
            if query:
                search_text = f'{name} {meta.description}'.lower()
                if query.lower() not in search_text:
                    continue

            if detail_level == 'summary':
                results.append({'name': name, 'description': meta.description})
            else:
                results.append(
                    {
                        'name': name,
                        'description': meta.description,
                        'category': meta.category,
                        'priority': meta.priority,
                        'tags': meta.tags,
                        'parameters': meta.parameters,
                        'mutates': meta.mutates,
                    }
                )

        return results

    def get_categories(self) -> dict[str, list[str]]:
        """Get all tool categories and their tools."""
        self._load_manifests()
        return dict(self._categories)

    def get_tool(self, name: str) -> ToolProxy | None:
        """Get a tool proxy for lazy execution."""
        self._load_manifests()

        if name not in self._metadata:
            return None

        if name not in self._proxies:
            with self._lock:
                if name not in self._proxies:
                    self._proxies[name] = ToolProxy(self._metadata[name])

        return self._proxies[name]

    async def execute(
        self, name: str, params: dict[str, Any] | None = None, *, allow_mutation: bool = False
    ) -> Any:
        """Validate and run a registered tool.

        This is the single choke point for running tools, so the safety policy lives
        here rather than in each caller.

        Args:
            name: Registered tool name.
            params: Keyword arguments for the tool handler.
            allow_mutation: Must be True to run a tool whose manifest sets
                ``mutates: true``. The MCP server never passes True.

        Raises:
            UnknownToolError: Unknown tool name (a ``KeyError``).
            MutationRefusedError: Tool mutates controller state and allow_mutation is
                False (a ``PermissionError``).
            InvalidParamsError: A parameter marked ``required`` in the manifest is
                missing, or an unknown parameter was supplied (a ``ValueError``).
        """
        params = dict(params or {})
        meta = self.get_metadata(name)
        if meta is None:
            raise UnknownToolError(name)
        if meta.mutates and not allow_mutation:
            raise MutationRefusedError(name)

        declared = meta.parameters or {}
        if declared:
            unknown = sorted(set(params) - set(declared))
            if unknown:
                raise InvalidParamsError(f'unknown parameter(s): {", ".join(unknown)}')
        missing = sorted(
            p
            for p, spec in declared.items()
            if isinstance(spec, dict) and spec.get('required') and p not in params
        )
        if missing:
            raise InvalidParamsError(f'missing required parameter(s): {", ".join(missing)}')

        proxy = self.get_tool(name)
        assert proxy is not None  # metadata exists, so the proxy does too
        return await proxy.execute(**params)

    def get_metadata(self, name: str) -> ToolMetadata | None:
        """Get metadata for a specific tool."""
        self._load_manifests()
        return self._metadata.get(name)

    def __len__(self) -> int:
        """Return the number of registered tools."""
        self._load_manifests()
        return len(self._metadata)

    def __contains__(self, name: str) -> bool:
        """Check if a tool is registered."""
        self._load_manifests()
        return name in self._metadata
