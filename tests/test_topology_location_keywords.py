"""Issue 046 item 4: the topology's location words are generic, and a site adds its own.

``NetworkTopology._extract_location`` and the HTML diagram grouped devices by a keyword list
that mixed generic room words with the maintainer's household names. The list is now the
generic rooms only, in one place, and ``UNIFI_LOCATION_KEYWORDS`` (comma-separated) adds a
site's own words at run time without putting them in the repository.
"""

from __future__ import annotations

import pytest
from unifi_mapper import enhanced_network_topology as topo
from unifi_mapper.enhanced_network_topology import (
    DEFAULT_LOCATION_KEYWORDS,
    NetworkTopology,
    location_keywords,
)


@pytest.fixture(autouse=True)
def _no_site_keywords(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('UNIFI_LOCATION_KEYWORDS', raising=False)


def test_the_defaults_are_generic_rooms_only() -> None:
    for word in DEFAULT_LOCATION_KEYWORDS:
        assert word == word.lower()
        assert word in {
            'office',
            'lounge',
            'bedroom',
            'kitchen',
            'shed',
            'hallway',
            'dining',
            'garage',
            'basement',
            'attic',
            'loft',
            'garden',
        }, f'{word!r} is not a generic room word'


def test_extract_location_recognises_a_room_and_falls_back_to_core_or_network() -> None:
    t = NetworkTopology()
    assert t._extract_location('Garage Switch') == 'Garage'
    assert t._extract_location('Attic US 8') == 'Attic'
    assert t._extract_location('Core Switch 24') == 'Core'
    assert t._extract_location('USW-Flex-Mini') == 'Network'


def test_a_persons_name_is_not_a_location_by_default() -> None:
    t = NetworkTopology()
    assert t._extract_location('Robin Bedroom AP') == 'Bedroom'  # the room, not the person
    assert t._extract_location('Morgan Desk Switch') == 'Network'


def test_site_keywords_extend_the_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_LOCATION_KEYWORDS', ' Studio, Workshop ,,')
    assert location_keywords() == (*DEFAULT_LOCATION_KEYWORDS, 'studio', 'workshop')
    assert NetworkTopology()._extract_location('Workshop Flex') == 'Workshop'


def test_the_html_diagram_groups_by_the_same_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both uses read one list, so a site word applies to the diagram's groups too."""
    monkeypatch.setenv('UNIFI_LOCATION_KEYWORDS', 'Studio')
    source = topo.__file__
    text = open(source, encoding='utf-8').read()
    # The second keyword list that used to live inside generate_html_diagram is gone.
    assert text.count("'lounge',") == 1, 'the room list is defined in more than one place'
    assert 'studio' in location_keywords()
