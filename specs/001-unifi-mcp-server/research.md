# Research: UniFi Network MCP Server

**Feature**: 001-unifi-mcp-server
**Date**: 2024-12-28
**Status**: Complete

## Research Tasks

### 1. UniFi Controller API (UDM Pro Max 4.4.6)

**Decision**: Use existing `unifi_port_mapper@22f6f1f` as API reference

**Rationale**:
- Existing codebase has working API client implementation
- Tested against real UDM Pro Max controller
- Covers authentication, device discovery, port mapping

**Alternatives Considered**:
- Official UniFi API documentation (incomplete, outdated)
- Third-party UniFi libraries (lack async support)
- Reverse engineering from scratch (time-consuming)

**Key Findings from Reference Code**:
- Authentication: POST to `/api/auth/login` with username/password
- Session token returned in cookie, must be maintained
- Device list: GET `/proxy/network/api/s/{site}/stat/device`
- Client list: GET `/proxy/network/api/s/{site}/stat/sta`
- Port overrides: POST `/proxy/network/api/s/{site}/rest/device/{device_id}`
- VLAN config: GET `/proxy/network/api/s/{site}/rest/networkconf`
- Firewall rules: GET `/proxy/network/api/s/{site}/rest/firewallrule`

### 2. FastMCP Framework Best Practices

**Decision**: Follow AWS Labs MCP pattern exactly

**Rationale**:
- Proven architecture with 96.3% complexity reduction
- Clear tool organization by domain
- Prescriptive docstrings guide LLM behavior
- Explicit error handling with ToolError

**Key Patterns**:
```python
# Tool registration
mcp = FastMCP(name='unifi-network-mcp-server', instructions=PERSONA)

# Tool decorator with type hints
@mcp.tool
async def find_device(
    identifier: Annotated[str, Field(description='Device MAC, IP, or name')],
) -> Device:
    '''Find a device on the network.

    When to use:
    - Locating a device before traceroute
    - Verifying a device exists

    Common workflow:
    1. Use find_device() to locate the endpoint
    2. Use get_port_map() to see its connection
    3. Use traceroute() if connectivity issues

    What to do next:
    - If found: Use traceroute() to trace path
    - If not found: Check if device is online
    '''
```

### 3. Credential Chain Implementation

**Decision**: Environment → Keychain → 1Password CLI (sequential fallback)

**Rationale**:
- Environment variables: Standard for CI/CD, MCP server config
- Keychain (keyring): Secure local storage for development
- 1Password CLI: Enterprise-grade secret management

**Implementation Pattern**:
```python
async def get_credentials() -> Credentials:
    # 1. Environment variables (highest priority)
    if host := os.environ.get('UNIFI_HOST'):
        return Credentials(
            host=host,
            username=os.environ['UNIFI_USERNAME'],
            password=os.environ['UNIFI_PASSWORD'],
        )

    # 2. macOS Keychain via keyring
    try:
        import keyring
        if password := keyring.get_password('unifi-mcp', 'controller'):
            # Parse stored JSON with host, username, password
            return Credentials.from_keyring(password)
    except Exception:
        pass

    # 3. 1Password CLI
    try:
        result = await asyncio.create_subprocess_exec(
            'op', 'item', 'get', 'UniFi Controller',
            '--fields', 'host,username,password',
            '--format', 'json',
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, _ = await result.communicate()
        return Credentials.from_onepassword(json.loads(stdout))
    except Exception:
        pass

    raise CredentialError(
        'No credentials found. Tried: UNIFI_* env vars, macOS Keychain, 1Password CLI.'
    )
```

### 4. Async HTTP Client Selection

**Decision**: httpx with connection pooling

**Rationale**:
- Native async/await support
- Connection pooling reduces latency
- Compatible with asyncio
- Better than aiohttp for simple REST APIs

**Configuration**:
```python
self._client = httpx.AsyncClient(
    base_url=f'https://{host}:{port}',
    verify=False,  # UniFi uses self-signed certs
    timeout=httpx.Timeout(30.0),
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
)
```

### 5. Mermaid Diagram Generation

**Decision**: Template-based generation with validation

**Rationale**:
- Mermaid syntax is simple and well-documented
- Templates ensure consistent output
- Validation catches syntax errors before display

**Pattern for Network Path**:
```python
def render_network_path(path: NetworkPath) -> str:
    lines = ['```mermaid', 'graph LR']

    for i, hop in enumerate(path.hops):
        node_id = f'N{i}'
        next_id = f'N{i+1}' if i < len(path.hops) - 1 else None

        # Node with device info
        lines.append(f'    {node_id}["{hop.device_name}<br/>{hop.interface}"]')

        # Edge with VLAN/latency
        if next_id:
            label = f'VLAN {hop.vlan}'
            if hop.latency_ms:
                label += f'<br/>{hop.latency_ms}ms'
            lines.append(f'    {node_id} -->|{label}| {next_id}')

    lines.append('```')
    return '\n'.join(lines)
```

### 6. Testing Strategy

**Decision**: Separate unit (mocked) and integration (live) tests

**Rationale**:
- Unit tests run fast, no controller needed
- Integration tests verify real API compatibility
- pytest markers enable selective execution

**Markers**:
```python
# conftest.py
def pytest_configure(config):
    config.addinivalue_line('markers', 'live: marks tests requiring live controller')

# Usage
@pytest.mark.live
@pytest.mark.asyncio
async def test_find_device_live():
    device = await find_device('192.168.1.1')
    assert device.type == 'gateway'
```

### 7. Error Handling Pattern

**Decision**: ToolError class with structured fields

**Rationale**:
- Consistent error format across all tools
- Actionable suggestions help users recover
- Related tools enable workflow continuation

**Implementation**:
```python
class ToolError(Exception):
    def __init__(
        self,
        message: str,
        error_code: str,
        suggestion: str | None = None,
        related_tools: list[str] | None = None,
    ):
        self.message = message
        self.error_code = error_code
        self.suggestion = suggestion
        self.related_tools = related_tools or []
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [f'[{self.error_code}] {self.message}']
        if self.suggestion:
            parts.append(f'💡 Suggestion: {self.suggestion}')
        if self.related_tools:
            parts.append(f'🔧 Related tools: {", ".join(self.related_tools)}')
        return '\n'.join(parts)
```

## Resolved NEEDS CLARIFICATION

All technical context items were fully specified in the interview. No unresolved clarifications.

## References

- Existing codebase: `/Users/ataylor/code/personal/unifi_port_mapper@22f6f1f`
- AWS Labs MCP: `/Users/ataylor/code/mcp/awslabs/mcp/src/aws-network-mcp-server`
- FastMCP documentation: https://docs.anthropic.com/en/docs/model-context-protocol
- httpx documentation: https://www.python-httpx.org/
- Mermaid documentation: https://mermaid.js.org/
