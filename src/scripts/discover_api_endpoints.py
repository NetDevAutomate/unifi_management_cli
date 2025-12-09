#!/usr/bin/env python3
"""
Discover UniFi API endpoints by testing various common patterns.

This script helps identify which API endpoints are available on your UniFi controller,
which is crucial for understanding why port updates might not be working.
"""

import argparse
import logging
import os
import sys
from typing import Any, Dict

import requests
from dotenv import load_dotenv

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unifi_mapper.api_client import UnifiApiClient

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


def test_endpoint(
    session: requests.Session,
    endpoint: str,
    method: str = "GET",
    test_data: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Test a single API endpoint."""
    result = {
        "endpoint": endpoint,
        "method": method,
        "status_code": None,
        "available": False,
        "response_size": 0,
        "error": None,
    }

    try:
        if method == "GET":
            response = session.get(endpoint, timeout=5)
        elif method == "PUT" and test_data:
            response = session.put(endpoint, json=test_data, timeout=5)
        elif method == "POST" and test_data:
            response = session.post(endpoint, json=test_data, timeout=5)
        else:
            response = session.get(endpoint, timeout=5)

        result["status_code"] = response.status_code
        result["available"] = response.status_code < 400
        result["response_size"] = len(response.content)

        # For successful responses, try to get some info about the response
        if response.status_code == 200:
            try:
                data = response.json()
                if isinstance(data, dict) and "data" in data:
                    result["data_count"] = (
                        len(data["data"]) if isinstance(data["data"], list) else 1
                    )
            except:
                pass

    except Exception as e:
        result["error"] = str(e)
        result["status_code"] = "ERROR"

    return result


def discover_endpoints(api_client: UnifiApiClient, device_id: str = None) -> None:
    """Discover available API endpoints."""
    log.info("=== Discovering UniFi API Endpoints ===")

    # Base endpoint patterns to test
    base_patterns = [
        # Legacy patterns
        "/api/s/{site}/stat/device",
        "/api/s/{site}/rest/device",
        "/api/s/{site}/cmd/devmgr",
        "/api/s/{site}/stat/sta",
        "/api/login",
        "/api/logout",
        "/api/self",
        # UniFi OS patterns
        "/proxy/network/api/s/{site}/stat/device",
        "/proxy/network/api/s/{site}/rest/device",
        "/proxy/network/api/s/{site}/cmd/devmgr",
        "/proxy/network/api/s/{site}/stat/sta",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/self",
        # Alternative patterns found in some controllers
        "/v2/api/site/{site}/device",
        "/v2/api/site/{site}/clients",
        "/proxy/network/v2/api/site/{site}/device",
    ]

    # Device-specific patterns (if device_id provided)
    device_patterns = []
    if device_id:
        device_patterns = [
            # Legacy device-specific
            "/api/s/{site}/stat/device/{device_id}",
            "/api/s/{site}/rest/device/{device_id}",
            "/api/s/{site}/rest/device/{device_id}/port",
            # UniFi OS device-specific
            "/proxy/network/api/s/{site}/stat/device/{device_id}",
            "/proxy/network/api/s/{site}/rest/device/{device_id}",
            "/proxy/network/api/s/{site}/rest/device/{device_id}/port",
            # Alternative patterns
            "/v2/api/site/{site}/device/{device_id}",
            "/proxy/network/v2/api/site/{site}/device/{device_id}",
        ]

    all_patterns = base_patterns + device_patterns

    # Test all endpoints
    results = []
    total_patterns = len(all_patterns)

    print(f"\nTesting {total_patterns} endpoint patterns...\n")
    print(f"{'Endpoint':<70} {'Method':<6} {'Status':<8} {'Available':<10} {'Size':<8}")
    print("-" * 110)

    for i, pattern in enumerate(all_patterns):
        # Format the pattern with actual values
        endpoint = pattern.format(site=api_client.site, device_id=device_id or "test")
        full_url = f"{api_client.base_url}{endpoint}"

        # Test GET request
        result = test_endpoint(api_client.session, full_url, "GET")
        results.append(result)

        # Display result
        status_str = str(result["status_code"])
        available_str = "✓" if result["available"] else "✗"
        size_str = f"{result['response_size']}b" if result["response_size"] > 0 else "-"

        print(
            f"{endpoint:<70} {'GET':<6} {status_str:<8} {available_str:<10} {size_str:<8}"
        )

        # If this is a device endpoint and we have a device_id, also test PUT for updates
        if device_id and "rest/device" in endpoint and result["available"]:
            # Create minimal test data for PUT
            test_data = {"_id": device_id, "mac": "00:00:00:00:00:00"}
            put_result = test_endpoint(api_client.session, full_url, "PUT", test_data)
            results.append(put_result)

            put_status_str = str(put_result["status_code"])
            put_available_str = "✓" if put_result["available"] else "✗"

            print(
                f"{endpoint:<70} {'PUT':<6} {put_status_str:<8} {put_available_str:<10} {'-':<8}"
            )

    # Summarize results
    available_endpoints = [r for r in results if r["available"]]
    print("\n=== Summary ===")
    print(f"Total endpoints tested: {len(results)}")
    print(f"Available endpoints: {len(available_endpoints)}")

    if available_endpoints:
        print("\n=== Available Endpoints ===")
        for result in available_endpoints:
            endpoint_short = result["endpoint"].replace(api_client.base_url, "")
            method = result["method"]
            status = result["status_code"]
            size = result["response_size"]
            print(f"  {method} {endpoint_short} (HTTP {status}, {size}b)")

    # Look for potential update endpoints
    update_endpoints = [
        r
        for r in available_endpoints
        if "rest/device" in r["endpoint"] and r["method"] in ["PUT", "POST"]
    ]
    if update_endpoints:
        print("\n=== Potential Update Endpoints ===")
        for result in update_endpoints:
            endpoint_short = result["endpoint"].replace(api_client.base_url, "")
            method = result["method"]
            print(f"  {method} {endpoint_short} - Try this for port updates!")
    else:
        print(
            "\n⚠️  No update endpoints found. This might explain why port updates aren't persisting."
        )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Discover UniFi API endpoints")
    parser.add_argument("--url", help="URL of the UniFi Controller")
    parser.add_argument("--site", default="default", help="Site name")
    parser.add_argument("--token", help="API token for authentication")
    parser.add_argument("--username", help="Username for authentication")
    parser.add_argument("--password", help="Password for authentication")
    parser.add_argument(
        "--env",
        action="store_true",
        help="Use environment variables instead of command line arguments",
    )
    parser.add_argument(
        "--device-id", help="Device ID to test device-specific endpoints"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load environment variables if requested
    if args.env:
        load_dotenv()
        url = os.getenv("UNIFI_URL")
        site = os.getenv("UNIFI_SITE", "default")
        token = os.getenv("UNIFI_CONSOLE_API_TOKEN")
        username = os.getenv("UNIFI_USERNAME")
        password = os.getenv("UNIFI_PASSWORD")
    else:
        url = args.url
        site = args.site
        token = args.token
        username = args.username
        password = args.password

    if not url:
        log.error("UniFi Controller URL is required")
        return 1

    if not token and not (username and password):
        log.error(
            "Either API token or username/password is required for authentication"
        )
        return 1

    # Create API client
    api_client = UnifiApiClient(
        base_url=url,
        site=site,
        api_token=token,
        username=username,
        password=password,
        verify_ssl=False,
    )

    # Login
    if not api_client.login():
        log.error("Failed to login to UniFi Controller")
        return 1

    log.info("Successfully authenticated with UniFi Controller")

    # Discover endpoints
    discover_endpoints(api_client, args.device_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
