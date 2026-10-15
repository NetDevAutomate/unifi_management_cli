"""Issue 022: ``search_tools`` finds multi-word queries, tags and differently-cased categories.

``ToolRegistry.search`` kept a tool only when the whole query was a substring of
``"<name> <description>"``, matched ``category`` case-sensitively and never looked at tags, so
natural queries such as ``"port vlan"`` returned nothing. Now the query is tokenised (on
whitespace, ``_`` and ``-``) and every token must appear in the name (``_`` read as a space),
the description or a tag; ``category`` is case-insensitive; with a query, results are ranked by
where the tokens hit (name, then tags, then description), then priority, then
``(category, name)``; without one, the order is still ``(category, name)``. Summary results
mark the mutating tools with ``mutates: true``.
"""

import pytest
from pathlib import Path
from unifi_mapper.mcp.registry import ToolRegistry


@pytest.fixture(scope='module')
def shipped() -> ToolRegistry:
    return ToolRegistry(strict=True)


# The five calls the issue measured as empty at ab32faa, with a tool each must now find.
ISSUE_CALLS = [
    ({'query': 'port vlan'}, 'audit_vlan_coverage'),
    ({'query': 'list devices'}, 'get_device_inventory'),
    ({'query': 'link speed'}, 'audit_link_speeds'),
    ({'query': 'inventory'}, 'get_cameras'),  # tags: [cameras, devices, inventory, status]
    ({'category': 'Analysis'}, 'analyze_link_quality'),
]


@pytest.mark.parametrize(('params', 'expected'), ISSUE_CALLS, ids=[str(c[0]) for c in ISSUE_CALLS])
def test_the_issue_s_empty_calls_now_find_tools(
    shipped: ToolRegistry, params: dict[str, str], expected: str
) -> None:
    names = [r['name'] for r in shipped.search(**params)]
    assert names, params
    assert expected in names, names[:10]


def test_shipped_ranking_puts_the_name_hit_first(shipped: ToolRegistry) -> None:
    # Both words hit the name of audit_link_speeds; the others hit tags or the description.
    assert [r['name'] for r in shipped.search(query='link speed')][0] == 'audit_link_speeds'
    assert [r['name'] for r in shipped.search(query='list devices')][0] == 'get_device_inventory'


def test_category_match_is_case_insensitive_and_complete(shipped: ToolRegistry) -> None:
    lower = {r['name'] for r in shipped.search(category='analysis')}
    assert lower == {r['name'] for r in shipped.search(category='Analysis')}
    assert lower == {r['name'] for r in shipped.search(category='ANALYSIS')}
    assert lower == set(shipped.get_categories()['analysis'])


def test_a_tag_only_query_matches_what_the_tags_filter_matches(shipped: ToolRegistry) -> None:
    by_tag = {r['name'] for r in shipped.search(tags=['inventory'])}
    by_query = {r['name'] for r in shipped.search(query='inventory')}
    assert by_tag and by_tag <= by_query


def test_summary_results_mark_the_mutating_tools(shipped: ToolRegistry) -> None:
    summary = {r['name']: r for r in shipped.search()}
    full = {r['name']: r for r in shipped.search(detail_level='full')}
    mutating = {name for name, r in full.items() if r['mutates']}
    assert mutating == {'apply_stp_changes', 'apply_radio_optimization', 'restore_radio_config'}
    for name, result in summary.items():
        if name in mutating:
            assert set(result) == {'name', 'description', 'mutates'} and result['mutates'] is True
        else:
            assert set(result) == {'name', 'description'}, name


def test_a_query_with_no_match_is_still_empty(shipped: ToolRegistry) -> None:
    assert shipped.search(query='nonexistent xyzzy') == []
    assert shipped.search(query='port nonexistent_xyzzy') == []  # every token must hit


# --- ranking, on a fixture whose answer is known --------------------------------------------

RANKING = """
category: zzz
tools:
  by_description:
    module: m
    description: Mentions the port speed in its description
    priority: P0
  speed_tagged:
    module: m
    description: Nothing relevant here
    priority: P1
    tags: [port, speed]
  port_speed_check:
    module: m
    description: Name hit, lowest priority
    priority: P2
  port_speed_audit:
    module: m
    description: Name hit, higher priority
    priority: P1
  unrelated:
    module: m
    description: Never matches
"""


@pytest.fixture
def ranked(tmp_path: Path) -> ToolRegistry:
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'ranking.yaml').write_text(RANKING)
    return ToolRegistry(manifests)


def test_results_are_ranked_name_then_tags_then_description_then_priority(
    ranked: ToolRegistry,
) -> None:
    names = [r['name'] for r in ranked.search(query='port speed')]
    # Name hits first (P1 before P2), then the tag hit, then the description hit (even at P0).
    assert names == ['port_speed_audit', 'port_speed_check', 'speed_tagged', 'by_description']


def test_query_tokens_split_on_underscore_and_hyphen(ranked: ToolRegistry) -> None:
    assert [r['name'] for r in ranked.search(query='port-speed-audit')] == ['port_speed_audit']
    assert [r['name'] for r in ranked.search(query='PORT_SPEED  audit')] == ['port_speed_audit']


def test_without_a_query_the_order_is_category_then_name(ranked: ToolRegistry) -> None:
    names = [r['name'] for r in ranked.search()]
    assert names == sorted(names)
