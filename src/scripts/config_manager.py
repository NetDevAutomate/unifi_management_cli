#!/usr/bin/env python3
"""
UniFi Configuration Manager - Manage configuration for the UniFi Port Mapper.

This script provides functionality to load, display, and validate configuration
for the UniFi Port Mapper and related tools.
"""

import argparse
import json
import logging
import os
import sys

from dotenv import find_dotenv, load_dotenv, set_key

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


def load_config():
    """Load and return configuration for the UniFi Port Mapper."""
    # Load environment variables
    load_dotenv()

    # Get configuration values
    config = {
        "UNIFI_URL": os.getenv("UNIFI_URL", ""),
        "UNIFI_SITE": os.getenv("UNIFI_SITE", "default"),
        "UNIFI_CONSOLE_API_TOKEN": os.getenv("UNIFI_CONSOLE_API_TOKEN", ""),
        "UNIFI_USERNAME": os.getenv("UNIFI_USERNAME", ""),
        "UNIFI_PASSWORD": os.getenv("UNIFI_PASSWORD", ""),
    }

    return config


def display_config(config):
    """Display configuration for the UniFi Port Mapper."""
    print("UniFi Port Mapper Configuration:")
    print(f"  URL: {config['UNIFI_URL']}")
    print(f"  Site: {config['UNIFI_SITE']}")
    print(f"  API Token: {'Set' if config['UNIFI_CONSOLE_API_TOKEN'] else 'Not set'}")
    print(f"  Username: {'Set' if config['UNIFI_USERNAME'] else 'Not set'}")
    print(f"  Password: {'Set' if config['UNIFI_PASSWORD'] else 'Not set'}")


def validate_config(config):
    """Validate configuration for the UniFi Port Mapper."""
    errors = []

    if not config["UNIFI_URL"]:
        errors.append("UNIFI_URL is not set")

    if not config["UNIFI_CONSOLE_API_TOKEN"] and not (
        config["UNIFI_USERNAME"] and config["UNIFI_PASSWORD"]
    ):
        errors.append(
            "Either UNIFI_CONSOLE_API_TOKEN or both UNIFI_USERNAME and UNIFI_PASSWORD must be set"
        )

    return errors


def set_config(key, value):
    """Set a configuration value in the .env file."""
    dotenv_path = find_dotenv()
    if not dotenv_path:
        # Create .env file if it doesn't exist
        with open(".env", "w") as f:
            f.write(f"{key}={value}\n")
        log.info(f"Created .env file and set {key}")
    else:
        # Update existing .env file
        set_key(dotenv_path, key, value)
        log.info(f"Updated {key} in .env file")


def main():
    """Main entry point for the UniFi Configuration Manager."""
    parser = argparse.ArgumentParser(description="UniFi Configuration Manager")
    parser.add_argument(
        "--display", action="store_true", help="Display current configuration"
    )
    parser.add_argument(
        "--validate", action="store_true", help="Validate current configuration"
    )
    parser.add_argument(
        "--set",
        nargs=2,
        metavar=("KEY", "VALUE"),
        help="Set a configuration value in the .env file",
    )
    parser.add_argument(
        "--output", "-o", help="Output file for configuration (JSON format)"
    )
    parser.add_argument(
        "--create-example",
        action="store_true",
        help="Create a .env.example file with placeholders",
    )

    args = parser.parse_args()

    # Load configuration
    config = load_config()

    # Process command-line arguments
    if args.display or (
        not args.validate
        and not args.set
        and not args.output
        and not args.create_example
    ):
        # Display configuration by default
        display_config(config)

    if args.validate:
        # Validate configuration
        errors = validate_config(config)
        if errors:
            log.error("Configuration validation failed:")
            for error in errors:
                log.error(f"  - {error}")
            return 1
        else:
            log.info("Configuration validation passed")

    if args.set:
        # Set a configuration value
        key, value = args.set
        set_config(key, value)

    if args.output:
        # Save configuration to a file
        with open(args.output, "w") as f:
            # Redact sensitive information
            safe_config = config.copy()
            if safe_config["UNIFI_CONSOLE_API_TOKEN"]:
                safe_config["UNIFI_CONSOLE_API_TOKEN"] = "********"
            if safe_config["UNIFI_PASSWORD"]:
                safe_config["UNIFI_PASSWORD"] = "********"

            json.dump(safe_config, f, indent=2)
        log.info(f"Configuration saved to {args.output}")

    if args.create_example:
        # Create a .env.example file
        example_content = """# UniFi Port Mapper Configuration
UNIFI_URL=https://unifi.local:8443
UNIFI_SITE=default
UNIFI_CONSOLE_API_TOKEN=your_api_token
# Or use username/password authentication
UNIFI_USERNAME=your_username
UNIFI_PASSWORD=your_password
"""
        with open(".env.example", "w") as f:
            f.write(example_content)
        log.info("Created .env.example file")

    return 0


if __name__ == "__main__":
    sys.exit(main())
