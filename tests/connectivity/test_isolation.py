"""Self-test: this package's conftest isolates every test from the live config and SSH."""

import asyncssh
import os
import pytest
from pathlib import Path
from unifi_mapper.cli import get_default_config_path


def test_the_default_config_path_names_no_existing_file(tmp_path: Path) -> None:
    assert Path.cwd() == tmp_path
    assert os.environ['HOME'] == str(tmp_path)
    assert not get_default_config_path().exists()


async def test_a_real_ssh_connect_fails() -> None:
    with pytest.raises(AssertionError, match='live SSH in a test'):
        await asyncssh.connect('192.0.2.1')
