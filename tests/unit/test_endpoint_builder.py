#!/usr/bin/env python3
"""
Binary pass/fail tests for UnifiEndpointBuilder.
Each test must have clear pass/fail criteria.
"""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.endpoint_builder import UnifiEndpointBuilder


def test_unifi_os_endpoints():
    """Binary test: UniFi OS endpoints include /proxy/network prefix"""
    builder = UnifiEndpointBuilder(base_url="https://unifi.local:443", is_unifi_os=True)

    # Test devices endpoint
    devices_endpoint = builder.devices("default")
    assert "/proxy/network" in devices_endpoint, (
        f"Missing proxy prefix in: {devices_endpoint}"
    )
    assert (
        devices_endpoint
        == "https://unifi.local:443/proxy/network/api/s/default/stat/device"
    )

    # Test clients endpoint
    clients_endpoint = builder.clients("default")
    assert "/proxy/network" in clients_endpoint
    assert (
        clients_endpoint
        == "https://unifi.local:443/proxy/network/api/s/default/stat/sta"
    )

    # Test device details
    details_endpoint = builder.device_details("default", "abc123")
    assert "/proxy/network" in details_endpoint
    assert (
        details_endpoint
        == "https://unifi.local:443/proxy/network/api/s/default/stat/device/abc123"
    )

    # Test login (no proxy prefix)
    login_endpoint = builder.login()
    assert "/proxy/network" not in login_endpoint
    assert login_endpoint == "https://unifi.local:443/api/auth/login"

    print("✅ PASS: UniFi OS endpoints correct")
    return True


def test_legacy_endpoints():
    """Binary test: Legacy controller endpoints omit /proxy/network prefix"""
    builder = UnifiEndpointBuilder(
        base_url="https://unifi.local:8443", is_unifi_os=False
    )

    # Test devices endpoint
    devices_endpoint = builder.devices("default")
    assert "/proxy/network" not in devices_endpoint
    assert devices_endpoint == "https://unifi.local:8443/api/s/default/stat/device"

    # Test clients endpoint
    clients_endpoint = builder.clients("default")
    assert "/proxy/network" not in clients_endpoint
    assert clients_endpoint == "https://unifi.local:8443/api/s/default/stat/sta"

    # Test device details
    details_endpoint = builder.device_details("default", "def456")
    assert "/proxy/network" not in details_endpoint
    assert (
        details_endpoint == "https://unifi.local:8443/api/s/default/stat/device/def456"
    )

    # Test login
    login_endpoint = builder.login()
    assert "/proxy/network" not in login_endpoint
    assert login_endpoint == "https://unifi.local:8443/api/login"

    print("✅ PASS: Legacy endpoints correct")
    return True


def test_url_normalization():
    """Binary test: Trailing slashes are removed from base URL"""
    builder1 = UnifiEndpointBuilder("https://unifi.local:8443/", is_unifi_os=False)
    builder2 = UnifiEndpointBuilder("https://unifi.local:8443", is_unifi_os=False)

    endpoint1 = builder1.devices("default")
    endpoint2 = builder2.devices("default")

    assert endpoint1 == endpoint2
    assert "//" not in endpoint1.replace("https://", "")  # No double slashes

    print("✅ PASS: URL normalization works")
    return True


def test_site_id_in_endpoints():
    """Binary test: Site ID correctly interpolated in all endpoints"""
    builder = UnifiEndpointBuilder("https://unifi.local", is_unifi_os=False)

    # Test with non-default site
    custom_site = "office-site"

    devices = builder.devices(custom_site)
    assert f"/s/{custom_site}/" in devices

    clients = builder.clients(custom_site)
    assert f"/s/{custom_site}/" in clients

    details = builder.device_details(custom_site, "device123")
    assert f"/s/{custom_site}/" in details

    print("✅ PASS: Site ID interpolation correct")
    return True


if __name__ == "__main__":
    tests = [
        test_unifi_os_endpoints,
        test_legacy_endpoints,
        test_url_normalization,
        test_site_id_in_endpoints,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
                print(f"❌ FAIL: {test.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"❌ FAIL: {test.__name__} - {e}")
        except Exception as e:
            failed += 1
            print(f"❌ ERROR: {test.__name__} - {e}")

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("✅ ALL TESTS PASS")
        sys.exit(0)
    else:
        print(f"❌ {failed} TEST(S) FAILED")
        sys.exit(1)
