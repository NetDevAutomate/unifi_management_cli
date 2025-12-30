"""Foundation tests to verify test infrastructure works."""

import os
import sys

import pytest


def test_python_version():
    """Test Python version meets requirements (>=3.12)."""
    assert sys.version_info >= (3, 12), f'Python {sys.version_info} < 3.12'


def test_project_structure():
    """Test that required directories exist."""
    project_root = os.getcwd()

    # Core directories
    assert os.path.exists(os.path.join(project_root, 'src'))
    assert os.path.exists(os.path.join(project_root, 'src', 'unifi_mcp'))
    assert os.path.exists(os.path.join(project_root, 'tests'))
    assert os.path.exists(os.path.join(project_root, 'tests', 'unit'))
    assert os.path.exists(os.path.join(project_root, 'tests', 'integration'))

    # Configuration files
    assert os.path.exists(os.path.join(project_root, 'pyproject.toml'))
    assert os.path.exists(os.path.join(project_root, '.pre-commit-config.yaml'))
    assert os.path.exists(os.path.join(project_root, 'README.md'))


@pytest.mark.skip(reason='Constitution file is optional - only created by SpecKit workflow')
def test_constitution_exists():
    """Test that constitution file exists."""
    constitution_path = os.path.join(os.getcwd(), '.specify', 'memory', 'constitution.md')
    assert os.path.exists(constitution_path), 'Constitution file missing'


def test_spec_artifacts_exist():
    """Test that all SpecKit artifacts were generated."""
    spec_dir = os.path.join(os.getcwd(), 'specs', '001-unifi-mcp-server')

    required_files = [
        'spec.md',
        'plan.md',
        'research.md',
        'data-model.md',
        'quickstart.md',
        'tasks.md',
        'contracts/tools.md',
        'checklists/requirements.md',
    ]

    for file_path in required_files:
        full_path = os.path.join(spec_dir, file_path)
        assert os.path.exists(full_path), f'Missing: {file_path}'


def test_basic_math():
    """Test that testing framework works."""
    assert 2 + 2 == 4
    assert 10 // 3 == 3


def test_file_permissions():
    """Test file system permissions work."""
    test_dir = os.path.join(os.getcwd(), 'tests')
    assert os.access(test_dir, os.R_OK), 'Cannot read tests directory'
