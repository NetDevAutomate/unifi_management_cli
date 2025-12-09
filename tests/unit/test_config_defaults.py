#!/usr/bin/env python3
"""
Binary pass/fail tests for config file default preferences.
"""

import os
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.config import UnifiConfig


def test_default_format_from_env():
    """Binary test: Default format can be configured via env var"""
    os.environ["UNIFI_URL"] = "https://test.local"
    os.environ["UNIFI_CONSOLE_API_TOKEN"] = "test-token"
    os.environ["UNIFI_DEFAULT_FORMAT"] = "svg"

    config = UnifiConfig.from_env()

    assert config.default_format == "svg"

    # Cleanup
    del os.environ["UNIFI_DEFAULT_FORMAT"]

    print("✅ PASS: Default format configurable")
    return True


def test_default_format_fallback():
    """Binary test: Default format falls back to 'png' if not specified"""
    os.environ["UNIFI_URL"] = "https://test.local"
    os.environ["UNIFI_CONSOLE_API_TOKEN"] = "test-token"

    # Remove if exists
    if "UNIFI_DEFAULT_FORMAT" in os.environ:
        del os.environ["UNIFI_DEFAULT_FORMAT"]

    config = UnifiConfig.from_env()

    assert config.default_format == "png"  # Default

    print("✅ PASS: Default format falls back to 'png'")
    return True


def test_output_directories_configurable():
    """Binary test: Output directories can be configured"""
    os.environ["UNIFI_URL"] = "https://test.local"
    os.environ["UNIFI_CONSOLE_API_TOKEN"] = "test-token"
    os.environ["UNIFI_OUTPUT_DIR"] = "~/custom/reports"
    os.environ["UNIFI_DIAGRAM_DIR"] = "~/custom/diagrams"

    config = UnifiConfig.from_env()

    assert config.default_output_dir == "~/custom/reports"
    assert config.default_diagram_dir == "~/custom/diagrams"

    # Cleanup
    del os.environ["UNIFI_OUTPUT_DIR"]
    del os.environ["UNIFI_DIAGRAM_DIR"]

    print("✅ PASS: Output directories configurable")
    return True


def test_output_directories_optional():
    """Binary test: Output directories are optional (None if not set)"""
    os.environ["UNIFI_URL"] = "https://test.local"
    os.environ["UNIFI_CONSOLE_API_TOKEN"] = "test-token"

    # Ensure not set
    for key in ["UNIFI_OUTPUT_DIR", "UNIFI_DIAGRAM_DIR"]:
        if key in os.environ:
            del os.environ[key]

    config = UnifiConfig.from_env()

    assert config.default_output_dir is None
    assert config.default_diagram_dir is None

    print("✅ PASS: Output directories optional")
    return True


def test_config_to_dict_includes_defaults():
    """Binary test: to_dict() includes output preferences"""
    config = UnifiConfig(
        base_url="https://test.local",
        api_token="test-token",
        default_format="svg",
        default_output_dir="~/reports",
    )

    config_dict = config.to_dict()

    assert "default_format" in config_dict
    assert "default_output_dir" in config_dict
    assert config_dict["default_format"] == "svg"

    print("✅ PASS: to_dict() includes output preferences")
    return True


if __name__ == "__main__":
    tests = [
        test_default_format_from_env,
        test_default_format_fallback,
        test_output_directories_configurable,
        test_output_directories_optional,
        test_config_to_dict_includes_defaults,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print(f"❌ ERROR: {test.__name__} - {e}")
            import traceback

            traceback.print_exc()

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("✅ ALL TESTS PASS")
        sys.exit(0)
    else:
        print(f"❌ {failed} TEST(S) FAILED")
        sys.exit(1)
