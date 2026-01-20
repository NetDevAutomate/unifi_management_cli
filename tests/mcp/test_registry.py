"""Unit tests for MCP tool registry.

Tests cover:
- ToolMetadata dataclass creation and defaults
- ToolProxy lazy loading mechanism with mocked importlib
- ToolRegistry manifest loading and search functionality
"""

from __future__ import annotations

import asyncio
import pytest
from pathlib import Path
from typing import Any
from unifi_mapper.mcp.registry import ToolMetadata, ToolProxy, ToolRegistry
from unittest.mock import MagicMock, patch


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_manifest_content() -> str:
    """Sample YAML manifest content for testing."""
    return """
category: test_category
description: Test tools for unit testing

tools:
  test_tool_one:
    module: fake_module.tools
    handler: tool_one_handler
    description: First test tool for testing
    priority: P1
    tags: [test, discovery, inventory]
    parameters:
      query:
        type: string
        required: true
        description: Search query

  test_tool_two:
    module: fake_module.tools
    handler: tool_two_handler
    description: Second test tool
    priority: P2
    tags: [test, analysis]
"""


@pytest.fixture
def second_manifest_content() -> str:
    """Second manifest for multi-file testing."""
    return """
category: another_category
description: Another category of tools

tools:
  another_tool:
    module: another_module.utils
    handler: another_handler
    description: Tool from another category
    tags: [utility, helper]
"""


@pytest.fixture
def manifests_dir(tmp_path: Path, sample_manifest_content: str) -> Path:
    """Create a temporary manifests directory with test manifest."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "test.yaml").write_text(sample_manifest_content)
    return manifests


@pytest.fixture
def multi_manifest_dir(
    tmp_path: Path, sample_manifest_content: str, second_manifest_content: str
) -> Path:
    """Create a temporary manifests directory with multiple manifests."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "test.yaml").write_text(sample_manifest_content)
    (manifests / "another.yaml").write_text(second_manifest_content)
    return manifests


# ============================================================================
# ToolMetadata Tests
# ============================================================================


class TestToolMetadata:
    """Tests for ToolMetadata dataclass."""

    def test_creation_with_all_fields(self) -> None:
        """Test creating ToolMetadata with all fields specified."""
        meta = ToolMetadata(
            name="test_tool",
            module="test.module",
            handler="test_handler",
            description="A test tool",
            category="testing",
            priority="P1",
            tags=["tag1", "tag2"],
            parameters={"param1": {"type": "string"}},
        )

        assert meta.name == "test_tool"
        assert meta.module == "test.module"
        assert meta.handler == "test_handler"
        assert meta.description == "A test tool"
        assert meta.category == "testing"
        assert meta.priority == "P1"
        assert meta.tags == ["tag1", "tag2"]
        assert meta.parameters == {"param1": {"type": "string"}}

    def test_default_priority(self) -> None:
        """Test that priority defaults to P2."""
        meta = ToolMetadata(
            name="test",
            module="mod",
            handler="h",
            description="d",
            category="c",
        )

        assert meta.priority == "P2"

    def test_default_tags_empty_list(self) -> None:
        """Test that tags defaults to empty list."""
        meta = ToolMetadata(
            name="test",
            module="mod",
            handler="h",
            description="d",
            category="c",
        )

        assert meta.tags == []

    def test_default_parameters_empty_dict(self) -> None:
        """Test that parameters defaults to empty dict."""
        meta = ToolMetadata(
            name="test",
            module="mod",
            handler="h",
            description="d",
            category="c",
        )

        assert meta.parameters == {}

    def test_tags_list_independence(self) -> None:
        """Test that default tags list is independent between instances."""
        meta1 = ToolMetadata(name="t1", module="m", handler="h", description="d", category="c")
        meta2 = ToolMetadata(name="t2", module="m", handler="h", description="d", category="c")

        meta1.tags.append("modified")
        assert meta2.tags == []


# ============================================================================
# ToolProxy Tests
# ============================================================================


class TestToolProxy:
    """Tests for ToolProxy lazy loading mechanism."""

    def test_initial_state_not_loaded(self) -> None:
        """Test that proxy starts in unloaded state."""
        meta = ToolMetadata(
            name="test", module="test.mod", handler="handler", description="d", category="c"
        )
        proxy = ToolProxy(meta)

        assert proxy.is_loaded is False
        assert proxy._implementation is None  # type: ignore[reportPrivateUsage]

    def test_metadata_accessible(self) -> None:
        """Test that metadata is accessible on proxy."""
        meta = ToolMetadata(
            name="test", module="test.mod", handler="handler", description="test desc", category="c"
        )
        proxy = ToolProxy(meta)

        assert proxy.metadata.name == "test"
        assert proxy.metadata.description == "test desc"

    @patch("unifi_mapper.mcp.registry.importlib.import_module")
    def test_lazy_load_on_execute(self, mock_import: MagicMock) -> None:
        """Test that implementation is loaded on first execute."""
        mock_handler = MagicMock(return_value="result")
        mock_module = MagicMock()
        mock_module.my_handler = mock_handler
        mock_import.return_value = mock_module

        meta = ToolMetadata(
            name="test", module="my.module", handler="my_handler", description="d", category="c"
        )
        proxy = ToolProxy(meta)

        result = asyncio.run(proxy.execute(param1="value"))

        mock_import.assert_called_once_with("my.module")
        mock_handler.assert_called_once_with(param1="value")
        assert result == "result"
        assert proxy.is_loaded is True

    @patch("unifi_mapper.mcp.registry.importlib.import_module")
    def test_load_only_once(self, mock_import: MagicMock) -> None:
        """Test that module is only imported once across multiple executes."""
        mock_handler = MagicMock(return_value="result")
        mock_module = MagicMock()
        mock_module.handler = mock_handler
        mock_import.return_value = mock_module

        meta = ToolMetadata(
            name="test", module="test.mod", handler="handler", description="d", category="c"
        )
        proxy = ToolProxy(meta)

        asyncio.run(proxy.execute())
        asyncio.run(proxy.execute())
        asyncio.run(proxy.execute())

        mock_import.assert_called_once()

    @patch("unifi_mapper.mcp.registry.importlib.import_module")
    def test_execute_async_handler(self, mock_import: MagicMock) -> None:
        """Test executing an async handler."""

        async def async_handler(**_kwargs: Any) -> str:
            return "async_result"

        mock_module = MagicMock()
        mock_module.async_handler = async_handler
        mock_import.return_value = mock_module

        meta = ToolMetadata(
            name="test", module="test.mod", handler="async_handler", description="d", category="c"
        )
        proxy = ToolProxy(meta)

        result = asyncio.run(proxy.execute())

        assert result == "async_result"

    @patch("unifi_mapper.mcp.registry.importlib.import_module")
    def test_execute_passes_kwargs(self, mock_import: MagicMock) -> None:
        """Test that kwargs are passed to handler."""
        mock_handler = MagicMock(return_value="ok")
        mock_module = MagicMock()
        mock_module.handler = mock_handler
        mock_import.return_value = mock_module

        meta = ToolMetadata(
            name="test", module="m", handler="handler", description="d", category="c"
        )
        proxy = ToolProxy(meta)

        asyncio.run(proxy.execute(ip="10.0.0.1", timeout=30))

        mock_handler.assert_called_once_with(ip="10.0.0.1", timeout=30)


# ============================================================================
# ToolRegistry Tests
# ============================================================================


class TestToolRegistry:
    """Tests for ToolRegistry manifest loading and search."""

    def test_empty_registry(self, tmp_path: Path) -> None:
        """Test registry with non-existent manifests directory."""
        registry = ToolRegistry(tmp_path / "nonexistent")

        assert len(registry) == 0
        assert registry.get_categories() == {}

    def test_load_single_manifest(self, manifests_dir: Path) -> None:
        """Test loading a single manifest file."""
        registry = ToolRegistry(manifests_dir)

        assert len(registry) == 2
        assert "test_tool_one" in registry
        assert "test_tool_two" in registry

    def test_load_multiple_manifests(self, multi_manifest_dir: Path) -> None:
        """Test loading multiple manifest files."""
        registry = ToolRegistry(multi_manifest_dir)

        assert len(registry) == 3
        assert "test_tool_one" in registry
        assert "test_tool_two" in registry
        assert "another_tool" in registry

    def test_categories_populated(self, multi_manifest_dir: Path) -> None:
        """Test that categories are correctly populated."""
        registry = ToolRegistry(multi_manifest_dir)
        categories = registry.get_categories()

        assert "test_category" in categories
        assert "another_category" in categories
        assert set(categories["test_category"]) == {"test_tool_one", "test_tool_two"}
        assert categories["another_category"] == ["another_tool"]

    def test_get_metadata(self, manifests_dir: Path) -> None:
        """Test getting metadata for a specific tool."""
        registry = ToolRegistry(manifests_dir)
        meta = registry.get_metadata("test_tool_one")

        assert meta is not None
        assert meta.name == "test_tool_one"
        assert meta.module == "fake_module.tools"
        assert meta.handler == "tool_one_handler"
        assert meta.description == "First test tool for testing"
        assert meta.priority == "P1"
        assert "test" in meta.tags
        assert "discovery" in meta.tags

    def test_get_metadata_nonexistent(self, manifests_dir: Path) -> None:
        """Test getting metadata for nonexistent tool returns None."""
        registry = ToolRegistry(manifests_dir)

        assert registry.get_metadata("nonexistent") is None

    def test_get_tool_returns_proxy(self, manifests_dir: Path) -> None:
        """Test that get_tool returns a ToolProxy."""
        registry = ToolRegistry(manifests_dir)
        proxy = registry.get_tool("test_tool_one")

        assert proxy is not None
        assert isinstance(proxy, ToolProxy)
        assert proxy.metadata.name == "test_tool_one"
        assert proxy.is_loaded is False

    def test_get_tool_same_instance(self, manifests_dir: Path) -> None:
        """Test that get_tool returns same instance on multiple calls."""
        registry = ToolRegistry(manifests_dir)

        proxy1 = registry.get_tool("test_tool_one")
        proxy2 = registry.get_tool("test_tool_one")

        assert proxy1 is proxy2

    def test_get_tool_nonexistent(self, manifests_dir: Path) -> None:
        """Test getting nonexistent tool returns None."""
        registry = ToolRegistry(manifests_dir)

        assert registry.get_tool("nonexistent") is None

    def test_contains(self, manifests_dir: Path) -> None:
        """Test __contains__ method."""
        registry = ToolRegistry(manifests_dir)

        assert "test_tool_one" in registry
        assert "nonexistent" not in registry


class TestToolRegistrySearch:
    """Tests for ToolRegistry.search() functionality."""

    def test_search_no_filters(self, manifests_dir: Path) -> None:
        """Test search with no filters returns all tools."""
        registry = ToolRegistry(manifests_dir)
        results = registry.search()

        assert len(results) == 2
        names = {r["name"] for r in results}
        assert names == {"test_tool_one", "test_tool_two"}

    def test_search_by_query(self, manifests_dir: Path) -> None:
        """Test search by text query."""
        registry = ToolRegistry(manifests_dir)
        results = registry.search(query="First")

        assert len(results) == 1
        assert results[0]["name"] == "test_tool_one"

    def test_search_query_case_insensitive(self, manifests_dir: Path) -> None:
        """Test search query is case insensitive."""
        registry = ToolRegistry(manifests_dir)

        results_lower = registry.search(query="first")
        results_upper = registry.search(query="FIRST")

        assert len(results_lower) == 1
        assert len(results_upper) == 1
        assert results_lower[0]["name"] == results_upper[0]["name"]

    def test_search_by_category(self, multi_manifest_dir: Path) -> None:
        """Test search filtered by category."""
        registry = ToolRegistry(multi_manifest_dir)
        results = registry.search(category="test_category")

        assert len(results) == 2
        names = {r["name"] for r in results}
        assert names == {"test_tool_one", "test_tool_two"}

    def test_search_by_tags(self, manifests_dir: Path) -> None:
        """Test search filtered by tags (match any)."""
        registry = ToolRegistry(manifests_dir)
        results = registry.search(tags=["discovery"])

        assert len(results) == 1
        assert results[0]["name"] == "test_tool_one"

    def test_search_tags_match_any(self, manifests_dir: Path) -> None:
        """Test that tags filter matches any tag (OR logic)."""
        registry = ToolRegistry(manifests_dir)
        results = registry.search(tags=["discovery", "analysis"])

        assert len(results) == 2

    def test_search_combined_filters(self, multi_manifest_dir: Path) -> None:
        """Test search with multiple filters combined."""
        registry = ToolRegistry(multi_manifest_dir)
        results = registry.search(category="test_category", tags=["discovery"])

        assert len(results) == 1
        assert results[0]["name"] == "test_tool_one"

    def test_search_summary_detail_level(self, manifests_dir: Path) -> None:
        """Test search with summary detail level."""
        registry = ToolRegistry(manifests_dir)
        results = registry.search(detail_level="summary")

        assert len(results) == 2
        for result in results:
            assert "name" in result
            assert "description" in result
            assert "category" not in result
            assert "parameters" not in result

    def test_search_full_detail_level(self, manifests_dir: Path) -> None:
        """Test search with full detail level."""
        registry = ToolRegistry(manifests_dir)
        results = registry.search(detail_level="full")

        assert len(results) == 2
        for result in results:
            assert "name" in result
            assert "description" in result
            assert "category" in result
            assert "priority" in result
            assert "tags" in result
            assert "parameters" in result

    def test_search_no_matches(self, manifests_dir: Path) -> None:
        """Test search with no matching results."""
        registry = ToolRegistry(manifests_dir)
        results = registry.search(query="nonexistent_query_xyz")

        assert results == []


class TestToolRegistryEdgeCases:
    """Edge case tests for ToolRegistry."""

    def test_empty_manifest_file(self, tmp_path: Path) -> None:
        """Test handling of empty manifest file."""
        manifests = tmp_path / "manifests"
        manifests.mkdir()
        (manifests / "empty.yaml").write_text("")

        registry = ToolRegistry(manifests)

        assert len(registry) == 0

    def test_manifest_without_tools_key(self, tmp_path: Path) -> None:
        """Test handling of manifest without tools key."""
        manifests = tmp_path / "manifests"
        manifests.mkdir()
        (manifests / "no_tools.yaml").write_text("category: test\ndescription: No tools here")

        registry = ToolRegistry(manifests)

        assert len(registry) == 0

    def test_tool_with_minimal_fields(self, tmp_path: Path) -> None:
        """Test loading tool with minimal required fields."""
        manifests = tmp_path / "manifests"
        manifests.mkdir()
        (manifests / "minimal.yaml").write_text("""
category: minimal
tools:
  minimal_tool:
    module: some.module
    description: Minimal tool
""")

        registry = ToolRegistry(manifests)
        meta = registry.get_metadata("minimal_tool")

        assert meta is not None
        assert meta.name == "minimal_tool"
        assert meta.handler == "minimal_tool"  # Falls back to tool name
        assert meta.priority == "P2"  # Default
        assert meta.tags == []  # Default

    def test_category_defaults_to_filename(self, tmp_path: Path) -> None:
        """Test that category defaults to manifest filename stem."""
        manifests = tmp_path / "manifests"
        manifests.mkdir()
        (manifests / "my_category.yaml").write_text("""
tools:
  some_tool:
    module: mod
    description: Tool
""")

        registry = ToolRegistry(manifests)
        meta = registry.get_metadata("some_tool")

        assert meta is not None
        assert meta.category == "my_category"

    def test_multiple_loads_idempotent(self, manifests_dir: Path) -> None:
        """Test that calling methods multiple times doesn't re-load manifests."""
        registry = ToolRegistry(manifests_dir)

        # Multiple calls should be idempotent
        _ = len(registry)
        _ = registry.get_categories()
        _ = registry.search()
        _ = len(registry)

        # If manifests were re-loaded each time, we might see issues
        assert len(registry) == 2
