"""SDK ``Tool`` objects for the manifest catalog, built lazily (design §2.4).

The catalog builds tools for listing and argument validation, never for execution:
``ToolRunner`` calls the handler itself. Mutating tools are never built. A handler whose
import or build fails is logged once (stderr ERROR) and reported as not loadable.
"""

import importlib
import threading
from .registry import MutationRefusedError, ToolMetadata, ToolRegistry, UnknownToolError
from collections.abc import Callable
from loguru import logger
from mcp.server.fastmcp.exceptions import InvalidSignature
from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations
from typing import Any
from unifi_mapper.core.utils.redact import redact_text


class ToolNotLoadableError(Exception):
    """A handler could not be imported or built into an SDK ``Tool``.

    Attributes:
        exc_type: The class name of the original failure (never its text).
    """

    def __init__(self, name: str, exc_type: str) -> None:
        """Build the error.

        Args:
            name: The tool name.
            exc_type: The class name of the original failure.
        """
        super().__init__(f'{name}: tool not loadable: {exc_type}')
        self.exc_type = exc_type


def annotations_for(meta: ToolMetadata) -> ToolAnnotations:
    """Derive MCP annotations from one manifest entry (never called for mutates tools).

    ``idempotentHint`` is set on read-only tools too, because some hosts read it as a
    retry signal, which the sampling tools (``idempotent: false``) must not invite. An
    ``active_probe`` (issue 092) sends traffic from the gateway: not read-only, not
    idempotent, open world, whatever else the entry says, so a host that shows annotations
    shows the trust class.

    Args:
        meta: The tool's manifest metadata.

    Returns:
        The tool's annotations.
    """
    if meta.active_probe:
        return ToolAnnotations(
            title=meta.title,
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    read_only = not meta.writes_local
    return ToolAnnotations(
        title=meta.title,
        readOnlyHint=read_only,
        destructiveHint=False,
        idempotentHint=meta.idempotent and read_only,
        openWorldHint=meta.open_world,
    )


def build_tool(fn: Callable[..., Any], meta: ToolMetadata) -> Tool:
    """Build the SDK Tool for a manifest entry, falling back to no outputSchema.

    Args:
        fn: The imported handler.
        meta: The validated manifest metadata.

    Returns:
        An SDK Tool with input schema, title and annotations.
    """
    kw: dict[str, Any] = {
        'name': meta.name,
        'title': meta.title,
        'description': meta.description,
        'annotations': annotations_for(meta),
    }
    try:
        return Tool.from_function(fn, structured_output=True, **kw)
    except InvalidSignature:
        logger.debug('{} has no structured return type; listing without outputSchema', meta.name)
        return Tool.from_function(fn, structured_output=None, **kw)


def is_direct(meta: ToolMetadata) -> bool:
    """Return True if a catalog tool is listed on the direct surface.

    Args:
        meta: The tool's manifest metadata.

    Returns:
        True unless it mutates, is a pipeline-object tool or sets ``mcp: false``.
    """
    return not meta.mutates and meta.mcp and not meta.pipeline


class ToolCatalog:
    """Lazily built SDK tools for one registry."""

    def __init__(self, registry: ToolRegistry) -> None:
        """Create an empty catalog over ``registry``.

        Args:
            registry: The manifest registry.
        """
        self._registry = registry
        self._tools: dict[str, Tool] = {}
        self._failed: dict[str, str] = {}
        self._lock = threading.Lock()

    @property
    def registry(self) -> ToolRegistry:
        """The registry this catalog builds from."""
        return self._registry

    def get(self, name: str) -> Tool:
        """Return the built tool for ``name``, building it on first use.

        Args:
            name: A registered tool name.

        Returns:
            The SDK tool.

        Raises:
            UnknownToolError: No such tool.
            MutationRefusedError: The tool mutates controller state (never built).
            ToolNotLoadableError: Its handler can't be imported or built.
        """
        meta = self._registry.get_metadata(name)
        if meta is None:
            raise UnknownToolError(name)
        if meta.mutates:
            raise MutationRefusedError(name)
        with self._lock:
            if name in self._tools:
                return self._tools[name]
            if name in self._failed:
                raise ToolNotLoadableError(name, self._failed[name])
            try:
                fn = getattr(importlib.import_module(meta.module), meta.handler)
                tool = build_tool(fn, meta)
            except Exception as e:  # noqa: BLE001 - one bad handler must not break the catalog
                self._failed[name] = type(e).__name__
                logger.error(
                    'MCP tool {} is not loadable: {}: {}', name, type(e).__name__, redact_text(e)
                )
                raise ToolNotLoadableError(name, type(e).__name__) from e
            self._tools[name] = tool
            return tool

    def find(self, name: str) -> Tool | None:
        """Return the built tool, or None if it is unknown, mutating or not loadable.

        Args:
            name: A tool name.

        Returns:
            The SDK tool or None.
        """
        try:
            return self.get(name)
        except (UnknownToolError, MutationRefusedError, ToolNotLoadableError):
            return None

    def is_direct(self, name: str) -> bool:
        """Return True if ``name`` is a catalog tool listed on the direct surface.

        Args:
            name: A tool name.

        Returns:
            True for registered, non-mutating, non-pipeline tools with ``mcp`` not false.
        """
        meta = self._registry.get_metadata(name)
        return meta is not None and is_direct(meta)

    def direct_tools(self) -> list[Tool]:
        """Build and return every tool listed on the direct surface, sorted by name.

        Tools that fail to build are logged once and left out.

        Returns:
            The built tools.
        """
        names = sorted(
            name
            for tools in self._registry.get_categories().values()
            for name in tools
            if self.is_direct(name)
        )
        return [tool for name in names if (tool := self.find(name)) is not None]
