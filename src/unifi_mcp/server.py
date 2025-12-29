"""FastMCP server for UniFi network troubleshooting."""

from fastmcp import FastMCP
from loguru import logger
from unifi_mcp.resources import NETWORKING_SPECIALIST_PERSONA
from unifi_mcp.tools import connectivity, diagnostics, discovery, topology, utility
from unifi_mcp.utils.logging import configure_logging


def create_server() -> FastMCP:
    """Create FastMCP server with networking specialist persona."""
    # Configure logging
    configure_logging()

    # Create server with persona
    mcp = FastMCP(
        name='unifi-network-mcp-server',
        instructions=NETWORKING_SPECIALIST_PERSONA,
    )

    # Register all tool groups
    _register_tools(mcp)

    logger.info('UniFi Network MCP Server initialized with all tools')
    return mcp


def _register_tools(mcp: FastMCP) -> None:
    """Register all tools with the MCP server."""
    tool_modules = [connectivity, diagnostics, discovery, topology, utility]

    for module in tool_modules:
        module_name = module.__name__.split('.')[-1]
        logger.info(f'Registering {module_name} tools: {module.__all__}')

        for tool_name in module.__all__:
            tool_func = getattr(module, tool_name)
            mcp.tool(tool_func)

    logger.info(f'Registered {sum(len(m.__all__) for m in tool_modules)} total tools')


# Global server instance
mcp = create_server()


def main() -> None:
    """Main entry point for the MCP server."""
    try:
        logger.info('Starting UniFi Network MCP Server')
        mcp.run()
    except KeyboardInterrupt:
        logger.info('Server stopped by user')
    except Exception as e:
        logger.error('Server error', error=str(e))
        raise


if __name__ == '__main__':
    main()
