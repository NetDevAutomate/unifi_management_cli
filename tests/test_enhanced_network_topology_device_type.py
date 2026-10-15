"""How the topology diagrams classify a device from its model (issue 085).

The PNG, SVG, DOT and Mermaid renderers group and colour devices by
``NetworkTopology._determine_device_type``; the HTML page uses ``is_router`` /
``is_unifi_device``. A UXG gateway's model holds ``xg``, which the access-point patterns
match, so before issue 085 it was drawn as an access point (and dropped from the HTML page).

The model codes below are the ones a controller reports in ``stat/device`` ``model``: the
UXG family, and every model on the maintainer's site (``inventory list``, 2026-10-15),
which includes the Flex XG switch (``USFXG``) that the same ``xg`` pattern caught.
"""

import pytest
from unifi_mapper.enhanced_network_topology import NetworkTopology
from unifi_mapper.models import DeviceInfo


def _device(model: str, name: str = 'Device') -> DeviceInfo:
    """A device with only the fields classification reads."""
    return DeviceInfo(
        id='d1', name=name, model=model, mac='02:00:00:00:00:01', ip='192.0.2.1', ports=[]
    )


UXG_MODELS = ['UXG', 'UXGPRO', 'UXG-Pro', 'UXG-Lite', 'UXG-Max', 'UXGB']
# The live site's gateway (UCG Fiber) and older gateway codes keep classifying as routers.
OTHER_GATEWAY_MODELS = ['UDMA6A8', 'UDMPRO', 'UGW3', 'USG-PRO-4']
# Live switches (USWED35/36/37 Flex 2.5G, USL8LP/USL16LP Lite, USM8P210 Ultra, USFXG Flex
# XG) and switches whose model holds ``xg``.
SWITCH_MODELS = [
    'USWED35',
    'USWED36',
    'USWED37',
    'USL8LP',
    'USL16LP',
    'USM8P210',
    'USFXG',
    'USW-Flex-XG',
    'USW-Pro-Max-24-XG',
    'US16XG',
    'US6XG150',
]
# Live access points (UAP6MP U6 Pro, UACCMPOEAF doorbell, U6IW, UAPA6BA U7 Pro XG Wall) and
# the UAP-XG, an access point whose model holds ``xg``.
AP_MODELS = ['UAP6MP', 'UACCMPOEAF', 'U6IW', 'UAPA6BA', 'U6-Pro', 'UAP-XG']


@pytest.mark.parametrize('model', UXG_MODELS + OTHER_GATEWAY_MODELS)
def test_gateway_models_classify_as_router(model: str) -> None:
    assert NetworkTopology()._determine_device_type(_device(model)) == 'router'


@pytest.mark.parametrize('model', SWITCH_MODELS)
def test_switch_models_classify_as_switch(model: str) -> None:
    assert NetworkTopology()._determine_device_type(_device(model)) == 'switch'


@pytest.mark.parametrize('model', AP_MODELS)
def test_access_point_models_classify_as_ap(model: str) -> None:
    assert NetworkTopology()._determine_device_type(_device(model)) == 'ap'


def test_uxg_and_u6_land_in_their_own_layers_of_the_dot_source() -> None:
    """The fixture the record asks for: a UXG and a U6, drawn in the gateway and AP layers."""
    topology = NetworkTopology()
    topology.add_device('gw', 'Edge', 'UXGPRO', '02:00:00:00:00:01', '192.0.2.1')
    topology.add_device('ap', 'Hall', 'UAP6MP', '02:00:00:00:00:02', '192.0.2.2')
    source = topology._generate_dot_source()
    gateway_layer = source.split('// Layer 1: Gateway')[1].split('}')[0]
    assert '"gw"' in gateway_layer
    assert '"ap"' not in gateway_layer


def test_uxg_is_a_gateway_in_the_mermaid_data() -> None:
    topology = NetworkTopology()
    topology.add_device('gw', 'Edge', 'UXG-Lite', '02:00:00:00:00:01', '192.0.2.1')
    (node,) = topology._mermaid_topology_data()['devices']
    assert node['type'] == 'gateway'


def test_uxg_is_a_unifi_router_on_the_html_page() -> None:
    """The HTML page skips a device ``is_unifi_device`` rejects and colours by ``is_router``."""
    topology = NetworkTopology()
    topology.add_device('gw', 'Edge', 'UXGPRO', '02:00:00:00:00:01', '192.0.2.1')
    assert topology.is_unifi_device('gw')
    assert topology.is_router('gw')


def test_flex_xg_is_a_unifi_switch_on_the_html_page_whatever_its_name() -> None:
    """``USFXG`` holds none of the old switch words, so a renamed Flex XG was skipped."""
    topology = NetworkTopology()
    topology.add_device('sw', 'Core', 'USFXG', '02:00:00:00:00:02', '192.0.2.2')
    assert topology.is_unifi_device('sw')
    assert topology.is_switch('sw')
    assert not topology.is_router('sw')
