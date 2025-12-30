#!/usr/bin/env python3
"""
Shell completion installation for unifi-mapper CLI.
Supports bash and zsh with comprehensive argument completion.
"""

import os
import sys
from pathlib import Path


def generate_bash_completion() -> str:
    """Generate bash completion script."""
    return """
# Bash completion for unifi-mapper
_unifi_mapper_completion() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # Main options
    opts="--config --output --diagram --format --debug --dry-run --connected-devices --verify-updates --help"

    # Format options for --format
    formats="png svg dot mermaid html"

    case "${prev}" in
        --config|-c)
            # Complete config file paths
            COMPREPLY=( $(compgen -f "${cur}") )
            return 0
            ;;
        --output|-o)
            # Complete .md files
            COMPREPLY=( $(compgen -f -X '!*.md' "${cur}") )
            return 0
            ;;
        --diagram|-d)
            # Complete image files
            COMPREPLY=( $(compgen -f -X '!*.@(png|svg|html|dot)' "${cur}") )
            return 0
            ;;
        --format)
            # Complete format options
            COMPREPLY=( $(compgen -W "${formats}" "${cur}") )
            return 0
            ;;
        *)
            ;;
    esac

    # Default to main options
    COMPREPLY=( $(compgen -W "${opts}" "${cur}") )
    return 0
}

# Register the completion function
complete -F _unifi_mapper_completion unifi-mapper
"""


def generate_zsh_completion() -> str:
    """Generate zsh completion script."""
    return """
#compdef unifi-mapper

# Zsh completion for unifi-mapper
_unifi_mapper() {
    local context state line
    typeset -A opt_args

    _arguments -C \\
        '(-h --help)'{-h,--help}'[Show help message]' \\
        '(-c --config)'{-c,--config}'[Path to .env configuration file]:config file:_files -g "*.env*"' \\
        '(-o --output)'{-o,--output}'[Output path for report]:output file:_files -g "*.md"' \\
        '(-d --diagram)'{-d,--diagram}'[Output path for diagram]:diagram file:_files -g "*.png *.svg *.html *.dot"' \\
        '--format[Diagram format]:format:(png svg dot mermaid html)' \\
        '--debug[Enable debug logging]' \\
        '--dry-run[Dry run mode (don'\''t apply port name changes)]' \\
        '--connected-devices[Include non-UniFi connected devices]' \\
        '--verify-updates[Verify that port name updates were successfully applied]'
}

_unifi_mapper "$@"
"""


def install_bash_completion(force: bool = False) -> bool:
    """Install bash completion script."""
    # Possible bash completion directories
    bash_completion_dirs = [
        Path("/opt/homebrew/etc/bash_completion.d"),  # Homebrew on macOS
        Path("/usr/local/etc/bash_completion.d"),     # Local install
        Path("/etc/bash_completion.d"),               # System wide
        Path.home() / ".bash_completions"             # User directory
    ]

    # Find first writable directory
    target_dir = None
    for completion_dir in bash_completion_dirs:
        if completion_dir.exists() and os.access(completion_dir, os.W_OK):
            target_dir = completion_dir
            break
        elif completion_dir == Path.home() / ".bash_completions":
            # Create user completion directory if none found
            target_dir = completion_dir
            target_dir.mkdir(exist_ok=True)
            break

    if not target_dir:
        print("❌ No writable bash completion directory found")
        print("   Try: sudo mkdir -p /usr/local/etc/bash_completion.d")
        return False

    completion_file = target_dir / "unifi-mapper"

    if completion_file.exists() and not force:
        print(f"⚠️  Completion file already exists: {completion_file}")
        print("   Use --force to overwrite")
        return False

    try:
        completion_file.write_text(generate_bash_completion())
        print(f"✅ Bash completion installed: {completion_file}")

        # Check if bash_completion is sourced
        bashrc_files = [
            Path.home() / ".bashrc",
            Path.home() / ".bash_profile",
            Path.home() / ".profile"
        ]

        source_found = False
        for bashrc in bashrc_files:
            if bashrc.exists() and "bash_completion" in bashrc.read_text():
                source_found = True
                break

        if not source_found:
            print("\n📝 To enable completions, add to your ~/.bashrc or ~/.bash_profile:")
            if target_dir == Path("/opt/homebrew/etc/bash_completion.d"):
                print("   source /opt/homebrew/etc/profile.d/bash_completion.sh")
            else:
                print(f"   source {target_dir}/unifi-mapper")

        print("   Then run: source ~/.bashrc")
        return True

    except Exception as e:
        print(f"❌ Failed to install bash completion: {e}")
        return False


def install_zsh_completion(force: bool = False) -> bool:
    """Install zsh completion script."""
    # Check for zsh function path
    zsh_fpath = os.environ.get("fpath", "").split(":")

    # Common zsh completion directories
    zsh_completion_dirs = [
        Path("/opt/homebrew/share/zsh/site-functions"),  # Homebrew
        Path("/usr/local/share/zsh/site-functions"),     # Local
        Path.home() / ".zsh" / "completions",            # User
    ]

    # Add fpath directories
    for fpath_dir in zsh_fpath:
        if fpath_dir.strip():
            zsh_completion_dirs.append(Path(fpath_dir.strip()))

    # Find first writable directory
    target_dir = None
    for completion_dir in zsh_completion_dirs:
        if completion_dir.exists() and os.access(completion_dir, os.W_OK):
            target_dir = completion_dir
            break
        elif completion_dir == Path.home() / ".zsh" / "completions":
            # Create user completion directory
            target_dir = completion_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            break

    if not target_dir:
        print("❌ No writable zsh completion directory found")
        print("   Try: mkdir -p ~/.zsh/completions")
        return False

    completion_file = target_dir / "_unifi-mapper"

    if completion_file.exists() and not force:
        print(f"⚠️  Completion file already exists: {completion_file}")
        print("   Use --force to overwrite")
        return False

    try:
        completion_file.write_text(generate_zsh_completion())
        print(f"✅ Zsh completion installed: {completion_file}")

        # Check if directory is in fpath
        if str(target_dir) not in zsh_fpath:
            print(f"\n📝 To enable completions, add to your ~/.zshrc:")
            print(f"   fpath=({target_dir} $fpath)")
            print("   autoload -Uz compinit && compinit")
            print("   Then run: source ~/.zshrc")
        else:
            print("\n🔄 Run: compinit")

        return True

    except Exception as e:
        print(f"❌ Failed to install zsh completion: {e}")
        return False


def install_completions(shell: str, force: bool = False) -> bool:
    """Install shell completions.

    Args:
        shell: Shell type ('bash' or 'zsh' or 'both')
        force: Overwrite existing completion files

    Returns:
        True if installation successful
    """
    if shell.lower() in ("bash", "both"):
        bash_success = install_bash_completion(force)
        if shell.lower() == "bash":
            return bash_success

    if shell.lower() in ("zsh", "both"):
        zsh_success = install_zsh_completion(force)
        if shell.lower() == "zsh":
            return zsh_success

        # Both requested
        return bash_success and zsh_success

    print(f"❌ Unsupported shell: {shell}")
    print("   Supported: bash, zsh, both")
    return False


def main():
    """CLI entry point for install-completions subcommand."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Install shell completions for unifi-mapper"
    )
    parser.add_argument(
        "shell",
        choices=["bash", "zsh", "both"],
        help="Shell to install completions for"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing completion files"
    )

    args = parser.parse_args()

    success = install_completions(args.shell, args.force)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()