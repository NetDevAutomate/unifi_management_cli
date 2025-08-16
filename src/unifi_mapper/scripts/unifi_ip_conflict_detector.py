#!/usr/bin/env python3
"""
Console script entry point for unifi-ip-conflict utility.

This module provides a console script entry point for the UniFi IP conflict detector,
allowing users to detect and analyze IP address conflicts in the UniFi network.
"""

import sys
import subprocess
from pathlib import Path
from typing import List, Optional


def main(args: Optional[List[str]] = None) -> int:
    """
    Console script entry point for unifi-ip-conflict.
    
    This function serves as the console script entry point and delegates
    to the existing unifi_ip_conflict_detector.py script while maintaining UV project structure.
    
    Args:
        args: Optional command line arguments (for testing)
        
    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Determine the project root directory
        project_root = Path(__file__).parent.parent.parent.parent
        
        # Path to the existing unifi_ip_conflict_detector script
        script_path = project_root / "src" / "scripts" / "unifi_ip_conflict_detector.py"
        
        # Use provided args or get from sys.argv
        if args is None:
            # Skip the first argument (script name) and pass the rest
            script_args = sys.argv[1:]
        else:
            script_args = args
        
        # Execute the existing script
        cmd = [sys.executable, str(script_path)] + script_args
        result = subprocess.run(cmd, check=False)
        
        return result.returncode
        
    except Exception as e:
        print(f"Error running unifi-ip-conflict: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())