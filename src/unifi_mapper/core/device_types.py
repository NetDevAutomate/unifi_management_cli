"""UniFi device ``type`` codes, grouped the way the analyses select devices.

The controller reports a short type code on every adopted device (``stat/device`` ``type``).
Several modules filter on it; keeping the groups here stops a new gateway code (``uxg`` in
0.4.0, issue 085) from being learned by one filter and missed by the next.
"""

from __future__ import annotations


GATEWAY_TYPES: frozenset[str] = frozenset({'ugw', 'usg', 'udm', 'udmpro', 'uxg'})
"""Gateways and consoles that route: USG, Dream Machine family, UXG. ``udmpro`` is a legacy code."""

SWITCHING_TYPES: frozenset[str] = GATEWAY_TYPES | {'usw', 'switch'}
"""Devices with a switch fabric whose ports carry a MAC table: gateways and switches."""

NETWORK_DEVICE_TYPES: frozenset[str] = SWITCHING_TYPES | {'uap'}
"""Everything a topology maps: gateways, switches and access points."""
