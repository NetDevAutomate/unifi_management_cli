"""Tool registry for UniFi Management MCP Server.

Implements lazy loading of tool definitions from YAML manifests,
following the Code Mode architecture pattern for progressive tool discovery.
"""

from __future__ import annotations

import importlib
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable


@dataclass
class ToolMetadata:
    """Metadata for a registered tool."""

    name: str
    module: str
    handler: str
    description: str
    category: str
    priority: str = "P2"
    tags: list[str] = field(default_factory=lambda: [])
    parameters: dict[str, Any] = field(default_factory=lambda: {})


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
        if hasattr(result, "__await__"):
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

    def __init__(self, manifests_dir: Path | None = None) -> None:
        """Initialize the tool registry with an optional manifests directory."""
        self._manifests_dir = manifests_dir or (Path(__file__).parent / "manifests")
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

            for manifest_file in self._manifests_dir.glob("*.yaml"):
                self._load_manifest(manifest_file)

            self._loaded = True

    def _load_manifest(self, manifest_file: Path) -> None:
        """Load a single manifest file."""
        with open(manifest_file) as f:
            data = yaml.safe_load(f)

        if not data or "tools" not in data:
            return

        category = data.get("category", manifest_file.stem)

        for tool_name, tool_data in data["tools"].items():
            metadata = ToolMetadata(
                name=tool_name,
                category=category,
                module=tool_data.get("module", ""),
                handler=tool_data.get("handler", tool_name),
                description=tool_data.get("description", ""),
                priority=tool_data.get("priority", "P2"),
                tags=tool_data.get("tags", []),
                parameters=tool_data.get("parameters", {}),
            )
            self._metadata[tool_name] = metadata
            self._categories.setdefault(category, []).append(tool_name)

    def search(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        detail_level: str = "summary",
    ) -> list[dict[str, Any]]:
        """Search tools with progressive disclosure.

        Args:
            query: Text search in tool names and descriptions
            category: Filter by category
            tags: Filter by tags (match any)
            detail_level: "summary" (name + description) or "full" (includes parameters)

        Returns:
            List of matching tools with requested detail level
        """
        self._load_manifests()

        results: list[dict[str, Any]] = []

        for name, meta in self._metadata.items():
            # Filter by category
            if category and meta.category != category:
                continue

            # Filter by tags (match any)
            if tags and not any(t in meta.tags for t in tags):
                continue

            # Filter by query
            if query:
                search_text = f"{name} {meta.description}".lower()
                if query.lower() not in search_text:
                    continue

            if detail_level == "summary":
                results.append({"name": name, "description": meta.description})
            else:
                results.append(
                    {
                        "name": name,
                        "description": meta.description,
                        "category": meta.category,
                        "priority": meta.priority,
                        "tags": meta.tags,
                        "parameters": meta.parameters,
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
