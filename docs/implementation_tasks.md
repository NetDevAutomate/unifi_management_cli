# Implementation Task List - UniFi Network Mapper Refactoring

## Priority: 🔴 Critical (Week 1)

### Phase 1: Foundation & Cleanup

#### Task 1.1: Delete Duplicate Script Directories
**Binary Test**: `src/unifi_mapper/scripts/` directory does not exist
**Files**: `src/unifi_mapper/scripts/*`
**Action**: Remove duplicate script directory
**Validation**: `test -d src/unifi_mapper/scripts && exit 1 || exit 0`

#### Task 1.2: Create Structured Exception Hierarchy
**Binary Test**: All 6 exception classes defined and importable
**Files**: `src/unifi_mapper/exceptions.py`
**Action**: Create exception hierarchy with UniFiRetryableError, UniFiPermanentError, etc.
**Validation**: `python -c "from src.unifi_mapper.exceptions import UniFiRetryableError, UniFiPermanentError, UniFiAuthenticationError, UniFiConnectionError, UniFiTimeoutError, UniFiValidationError; print('PASS')"`

#### Task 1.3: Create Endpoint Builder Module
**Binary Test**: EndpointBuilder generates correct URLs for both UniFi OS and legacy
**Files**: `src/unifi_mapper/endpoint_builder.py`, `tests/unit/test_endpoint_builder.py`
**Action**: Extract endpoint construction logic from api_client.py
**Validation**: `pytest tests/unit/test_endpoint_builder.py -v`

#### Task 1.4: Create Configuration Management Module
**Binary Test**: UnifiConfig loads from env and validates required fields
**Files**: `src/unifi_mapper/config.py`, `tests/unit/test_config.py`
**Action**: Centralize configuration with validation
**Validation**: `pytest tests/unit/test_config.py -v`

#### Task 1.5: Create Test Directory Structure
**Binary Test**: All required test directories exist
**Files**: `tests/unit/`, `tests/integration/`, `tests/fixtures/`, `tests/conftest.py`
**Action**: Create comprehensive test structure
**Validation**: `test -d tests/unit && test -d tests/integration && test -d tests/fixtures && test -f tests/conftest.py && echo PASS || echo FAIL`

### Phase 2: API Client Refactoring

#### Task 2.1: Create AuthManager Module
**Binary Test**: AuthManager handles login/logout/session with all methods working
**Files**: `src/unifi_mapper/auth_manager.py`, `tests/unit/test_auth_manager.py`
**Action**: Extract authentication logic from UnifiApiClient
**Validation**: `pytest tests/unit/test_auth_manager.py -v`

#### Task 2.2: Create DeviceClient Module
**Binary Test**: DeviceClient fetches devices and details correctly
**Files**: `src/unifi_mapper/device_client.py`, `tests/unit/test_device_client.py`
**Action**: Extract device operations from UnifiApiClient
**Validation**: `pytest tests/unit/test_device_client.py -v`

#### Task 2.3: Create PortClient Module
**Binary Test**: PortClient handles port CRUD operations
**Files**: `src/unifi_mapper/port_client.py`, `tests/unit/test_port_client.py`
**Action**: Extract port operations from UnifiApiClient
**Validation**: `pytest tests/unit/test_port_client.py -v`

#### Task 2.4: Create LldpClient Module
**Binary Test**: LldpClient extracts LLDP from device details
**Files**: `src/unifi_mapper/lldp_client.py`, `tests/unit/test_lldp_client.py`
**Action**: Extract LLDP operations from UnifiApiClient
**Validation**: `pytest tests/unit/test_lldp_client.py -v`

#### Task 2.5: Refactor UnifiApiClient to Use New Modules
**Binary Test**: UnifiApiClient delegates to specialized modules, all integration tests pass
**Files**: `src/unifi_mapper/api_client.py`
**Action**: Refactor to use AuthManager, DeviceClient, PortClient, LldpClient
**Validation**: `pytest tests/ -v`

## Priority: 🟡 High (Week 2)

### Phase 3: Testing Coverage

#### Task 3.1: Add Input Validation Tests
**Binary Test**: All injection attack patterns are sanitized
**Files**: `tests/unit/test_input_validation.py`
**Action**: Test SQL injection, XSS, command injection patterns
**Validation**: `pytest tests/unit/test_input_validation.py -v --cov=src.unifi_mapper.api_client --cov-report=term-missing`

#### Task 3.2: Add Retry Logic Tests
**Binary Test**: Retry logic handles transient failures with exponential backoff
**Files**: `tests/unit/test_retry_logic.py`
**Action**: Test retry behavior, backoff timing, failure thresholds
**Validation**: `pytest tests/unit/test_retry_logic.py -v`

#### Task 3.3: Add Port Mapper Business Logic Tests
**Binary Test**: Port naming logic with LLDP, clients, and defaults works correctly
**Files**: `tests/unit/test_port_mapper.py`
**Action**: Test port name generation, batch updates, client mapping
**Validation**: `pytest tests/unit/test_port_mapper.py -v`

#### Task 3.4: Add Models Validation Tests
**Binary Test**: DeviceInfo and PortInfo validation catches invalid data
**Files**: `tests/unit/test_models.py`
**Action**: Test data class validation, health score calculations
**Validation**: `pytest tests/unit/test_models.py -v`

### Phase 4: Performance Optimization

#### Task 4.1: Implement API Response Cache
**Binary Test**: Cache reduces API calls by ≥50% on second run
**Files**: `src/unifi_mapper/api_cache.py`, `tests/unit/test_api_cache.py`
**Action**: Create TTL-based cache for API responses
**Validation**: `pytest tests/unit/test_api_cache.py -v`

#### Task 4.2: Integrate Caching into API Clients
**Binary Test**: Real-world run shows ≥50% API call reduction
**Files**: `src/unifi_mapper/device_client.py`, `src/unifi_mapper/port_client.py`
**Action**: Add caching decorators to expensive operations
**Validation**: Run mapper twice, verify call count reduction in logs

#### Task 4.3: Implement Circuit Breaker
**Binary Test**: Circuit breaker opens after threshold failures, recovers correctly
**Files**: `src/unifi_mapper/circuit_breaker.py`, `tests/unit/test_circuit_breaker.py`
**Action**: Create circuit breaker for connection resilience
**Validation**: `pytest tests/unit/test_circuit_breaker.py -v`

## Priority: 🔴 Critical Diagrams (Week 3)

### Phase 5: Topology Consolidation

#### Task 5.1: Create Unified Topology Base
**Binary Test**: UnifiedNetworkTopology class exists with all required methods
**Files**: `src/unifi_mapper/unified_topology.py`, `tests/unit/test_unified_topology.py`
**Action**: Create base topology class with device/connection management
**Validation**: `pytest tests/unit/test_unified_topology.py -v`

#### Task 5.2: Implement Graphviz Renderer
**Binary Test**: Graphviz renderer generates valid DOT/PNG/SVG files
**Files**: `src/unifi_mapper/renderers/graphviz_renderer.py`, `tests/unit/test_graphviz_renderer.py`
**Action**: Create renderer with proper Graphviz integration
**Validation**: `pytest tests/unit/test_graphviz_renderer.py -v && file diagrams/test.png | grep -q PNG`

#### Task 5.3: Implement D3 HTML Renderer
**Binary Test**: HTML renderer generates valid interactive diagram
**Files**: `src/unifi_mapper/renderers/d3_html_renderer.py`, `tests/unit/test_d3_html_renderer.py`
**Action**: Migrate enhanced_network_topology HTML logic to renderer
**Validation**: `pytest tests/unit/test_d3_html_renderer.py -v && grep -q "d3.forceSimulation" diagrams/test.html`

#### Task 5.4: Implement Mermaid Renderer
**Binary Test**: Mermaid renderer generates valid Mermaid.js syntax
**Files**: `src/unifi_mapper/renderers/mermaid_renderer.py`, `tests/unit/test_mermaid_renderer.py`
**Action**: Create proper Mermaid.js generator (not DOT)
**Validation**: `pytest tests/unit/test_mermaid_renderer.py -v && grep -q "graph TD" diagrams/test.mermaid`

#### Task 5.5: Migrate to Unified Topology
**Binary Test**: All diagram formats work through unified interface
**Files**: `src/unifi_mapper/network_topology.py`, `src/unifi_mapper/run_methods.py`
**Action**: Update imports and usages to unified topology
**Validation**: `python unifi_network_mapper.py --env --format html && python unifi_network_mapper.py --env --format png`

#### Task 5.6: Delete Obsolete Topology Files
**Binary Test**: Old topology files removed, imports updated
**Files**: Delete `topology.py`, `improved_topology.py`, keep `enhanced_network_topology.py` as deprecated
**Action**: Remove redundant implementations
**Validation**: `test ! -f src/unifi_mapper/topology.py && test ! -f src/unifi_mapper/improved_topology.py && echo PASS`

### Phase 6: Diagram Enhancements

#### Task 6.1: Implement Adaptive Layout Engine
**Binary Test**: Layout parameters adjust based on device count (<20, 20-50, >50)
**Files**: `src/unifi_mapper/layout_engines.py`, `tests/unit/test_layout_engines.py`
**Action**: Create adaptive parameter selection
**Validation**: `pytest tests/unit/test_layout_engines.py -v`

#### Task 6.2: Implement Hierarchical Layout Algorithm
**Binary Test**: Hierarchical layout assigns devices to layers correctly
**Files**: `src/unifi_mapper/hierarchical_layout.py`, `tests/unit/test_hierarchical_layout.py`
**Action**: BFS-based layer assignment for large networks
**Validation**: `pytest tests/unit/test_hierarchical_layout.py -v`

#### Task 6.3: Add Connection Type Visual Differentiation
**Binary Test**: LLDP, uplink, inferred connections have different styles
**Files**: `src/unifi_mapper/unified_topology.py`
**Action**: Add style metadata to connections based on type
**Validation**: Generate diagram, verify CSS classes in HTML output

#### Task 6.4: Add Interactive Search/Filter to HTML
**Binary Test**: HTML diagram includes functional search input and filters
**Files**: `src/unifi_mapper/renderers/d3_html_renderer.py`
**Action**: Add search input, device type filters, path highlighting
**Validation**: Open HTML in browser, verify search functionality works

#### Task 6.5: Add Minimap Navigation
**Binary Test**: HTML diagram includes minimap with viewport indicator
**Files**: `src/unifi_mapper/renderers/d3_html_renderer.py`
**Action**: Implement D3 minimap with zoom sync
**Validation**: Open HTML in browser, verify minimap updates on pan/zoom

## Priority: 🟢 Medium (Week 4)

### Phase 7: Security Hardening

#### Task 7.1: Implement Secure Credential Store
**Binary Test**: Credentials encrypted in memory, cleared on exit
**Files**: `src/unifi_mapper/secure_credentials.py`, `tests/unit/test_secure_credentials.py`
**Action**: Cryptography-based credential storage
**Validation**: `pytest tests/unit/test_secure_credentials.py -v`

#### Task 7.2: Fix Credential Logging Sanitization
**Binary Test**: Sanitization always returns "***" for sensitive values
**Files**: `src/unifi_mapper/api_client.py`
**Action**: Replace partial sanitization with fixed replacement
**Validation**: Grep logs for credential patterns, all should be "***"

#### Task 7.3: Add Rate Limiting
**Binary Test**: Rate limiter enforces max calls/second
**Files**: `src/unifi_mapper/rate_limiter.py`, `tests/unit/test_rate_limiter.py`
**Action**: Implement token bucket rate limiter
**Validation**: `pytest tests/unit/test_rate_limiter.py -v`

### Phase 8: Advanced Features

#### Task 8.1: Add Multi-Format Export
**Binary Test**: Single run exports HTML, PNG, SVG, Mermaid, DOT
**Files**: `unifi_network_mapper.py`
**Action**: Add --export-formats argument
**Validation**: `python unifi_network_mapper.py --env --export-formats html png svg mermaid && ls diagrams/ | grep -E "(html|png|svg|mermaid)"`

#### Task 8.2: Implement Performance Monitoring
**Binary Test**: Performance metrics logged for all major operations
**Files**: `src/unifi_mapper/performance_monitor.py`, `tests/unit/test_performance_monitor.py`
**Action**: Track operation durations and generate summary
**Validation**: `pytest tests/unit/test_performance_monitor.py -v`

#### Task 8.3: Add Async API Client (Optional)
**Binary Test**: Async operations 3x faster for 20+ devices
**Files**: `src/unifi_mapper/async_api_client.py`, `tests/unit/test_async_api_client.py`
**Action**: Create asyncio-based parallel fetching
**Validation**: `pytest tests/unit/test_async_api_client.py -v`

## Summary Statistics

**Total Tasks**: 27
**Critical (🔴)**: 17 tasks
**High (🟡)**: 6 tasks
**Medium (🟢)**: 4 tasks

**Estimated Time**: 4-5 weeks
**Code Reduction**: 49% (3500 → 1800 lines)
**Test Coverage Goal**: 70%+
**Performance Improvement**: 3-5x

---

## Task Execution Order (Optimized for Dependencies)

1. Foundation (1.1-1.5): No dependencies
2. API Refactoring (2.1-2.5): Depends on 1.2, 1.3, 1.4
3. Testing (3.1-3.4): Depends on Phase 2
4. Performance (4.1-4.3): Depends on Phase 2
5. Topology (5.1-5.6): Depends on 1.5
6. Diagram Enhancement (6.1-6.5): Depends on Phase 5
7. Security (7.1-7.3): Can run parallel with Phase 6
8. Advanced (8.1-8.3): Depends on Phase 5, 6

**Critical Path**: 1 → 2 → 5 → 6 (Core functionality)
**Parallel Tracks**: 3, 4, 7 (Can overlap with main path)
