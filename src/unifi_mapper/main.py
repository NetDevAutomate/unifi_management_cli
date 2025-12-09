#!/usr/bin/env python3
"""
UniFi Network Mapper - Main entry point for the package.

This module provides the main() function that serves as the entry point
when the package is installed via UV/pip and called as a console script.
It delegates to the modernized entry point in the project root.
"""

import sys
from pathlib import Path
from typing import List, Optional

# Add the project root to the path so we can import from the legacy structure
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import and delegate to the modernized main function
try:
    from unifi_network_mapper import main as modernized_main
except ImportError:
    # Fallback to relative import if absolute import fails
    import os

    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
    from unifi_network_mapper import main as modernized_main


def main(args: Optional[List[str]] = None) -> int:
    """
    Main entry point for the UniFi Network Mapper package.

    This function serves as the console script entry point and
    delegates to the modernized main function in unifi_network_mapper.py.

    Args:
        args: Optional command line arguments (for testing)

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Temporarily replace sys.argv if args are provided (for testing)
    original_argv = None
    if args is not None:
        original_argv = sys.argv
        sys.argv = ["unifi-network-mapper"] + args

    try:
        return modernized_main()
    finally:
        # Restore original sys.argv if it was modified
        if original_argv is not None:
            sys.argv = original_argv


if __name__ == "__main__":
    sys.exit(main())
