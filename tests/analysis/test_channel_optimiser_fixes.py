"""Tests for channel optimiser correctness defects found during the 2026-08-03 radio work.

Three defects were found by comparing a `radio auto-channel` dry run against the
controller's real state:

1. Band was derived from channel number (`ch > 14 -> 5GHz`), so a tri-band AP's 6 GHz
   radio (U7 Pro XG Wall, `6e` on ch 37) was classified as 5 GHz and **overwrote** the
   real 5 GHz entry in the per-AP dict. The reported "Office 5 GHz, 2% util" was actually
   6 GHz telemetry, and the resulting `na` recommendation was computed from the wrong radio.

2. `optimize_5ghz` de-duplicated *primary channels* but not 80 MHz *blocks*, so it
   proposed 149 + 153 + 157 for three APs — all inside the single 149-161 block, i.e.
   fully overlapping spectrum. That was worse than the state it replaced.

3. `optimize_24ghz` scored channels from a static pre-computed average, so the channel a
   busy AP had just been assigned did not get more expensive. It put the two busiest APs
   (37 and 18 clients) on the same channel while a 3-client AP got one to itself.
"""

from __future__ import annotations

from unifi_mapper.analysis.channel_optimiser import (
    band_for_radio,
    block_80mhz,
    optimize_5ghz,
    optimize_24ghz,
)


def _ap(
    name: str,
    *,
    ch_24: int | None = None,
    util_24: int = 0,
    sta_24: int = 0,
    ch_5: int | None = None,
    util_5: int = 0,
    sta_5: int = 0,
) -> dict:
    radios: dict[str, dict] = {}
    if ch_24 is not None:
        radios['2.4GHz'] = {
            'channel': ch_24,
            'utilization': util_24,
            'interference': 0,
            'num_sta': sta_24,
            'ht': '20',
        }
    if ch_5 is not None:
        radios['5GHz'] = {
            'channel': ch_5,
            'utilization': util_5,
            'interference': 0,
            'num_sta': sta_5,
            'ht': '80',
        }
    return {'device_id': f'id-{name}', 'name': name, 'mac': f'mac-{name}', 'radios': radios}


# ─── Defect 1: band classification ───────────────────────────────────────────


def test_band_for_radio_maps_6ghz_radio_id_not_channel_number() -> None:
    """A 6 GHz radio on ch 37 must not be called 5 GHz just because 37 > 14."""
    assert band_for_radio('6e', 37) == '6GHz'
    assert band_for_radio('na', 36) == '5GHz'
    assert band_for_radio('ng', 11) == '2.4GHz'


def test_band_for_radio_falls_back_to_channel_when_radio_id_missing() -> None:
    """Older controllers may omit the radio id; the channel heuristic still applies."""
    assert band_for_radio(None, 36) == '5GHz'
    assert band_for_radio(None, 6) == '2.4GHz'


def test_band_for_radio_handles_6ghz_aliases() -> None:
    assert band_for_radio('wifi2', 37) == '6GHz'
    assert band_for_radio('6g', 37) == '6GHz'


# ─── Defect 2: 80 MHz block collisions ───────────────────────────────────────


def test_block_80mhz_groups_all_four_primaries_of_a_block() -> None:
    """149/153/157/161 are one 80 MHz block, not four independent choices."""
    assert block_80mhz(149) == block_80mhz(153) == block_80mhz(157) == block_80mhz(161)
    assert block_80mhz(36) == block_80mhz(48)
    assert block_80mhz(36) != block_80mhz(52)


def test_optimize_5ghz_never_puts_two_aps_in_the_same_80mhz_block() -> None:
    """The exact regression: three APs were assigned 149, 153 and 157."""
    aps = [
        _ap('busy', ch_5=100, util_5=70, sta_5=1),
        _ap('mid', ch_5=161, util_5=19, sta_5=7),
        _ap('quiet', ch_5=60, util_5=16, sta_5=7),
        _ap('idle', ch_5=64, util_5=11, sta_5=1),
        _ap('spare', ch_5=36, util_5=2, sta_5=1),
    ]

    recs = optimize_5ghz(aps)

    blocks = [block_80mhz(r['recommended_channel']) for r in recs]
    assert len(blocks) == len(set(blocks)), f'overlapping 80MHz blocks assigned: {recs}'


def test_optimize_5ghz_keeps_current_primary_when_block_is_already_correct() -> None:
    """Avoid pointless re-tuning: 44 and 36 are the same block, so don't move 44 -> 36.

    The AP already sits in the winning block, so the only change on offer is a
    same-spectrum primary shuffle that would drop clients for no gain.
    """
    aps = [_ap('only', ch_5=44, util_5=5, sta_5=2)]
    # Make the only other non-DFS block (149-161) expensive so 36-48 wins outright.
    crowded_elsewhere = dict.fromkeys((149, 153, 157, 161), 40.0)

    recs = optimize_5ghz(aps, neighbour_data=crowded_elsewhere)

    assert recs[0]['recommended_channel'] == 44
    assert recs[0]['change_needed'] is False


def test_optimize_5ghz_degrades_gracefully_when_aps_exceed_blocks() -> None:
    """More APs than 80 MHz blocks must still return one recommendation per AP."""
    aps = [_ap(f'ap{i}', ch_5=36, util_5=i) for i in range(9)]

    recs = optimize_5ghz(aps)

    assert len(recs) == 9
    assert all(r['recommended_channel'] for r in recs)


def test_optimize_5ghz_spreads_excess_aps_evenly_across_blocks() -> None:
    """Live regression: with 10 APs and 6 blocks, ch116 was assigned five times.

    Sorting candidate blocks by score alone meant every AP past the sixth chose the
    same cheapest block.
    """
    aps = [_ap(f'ap{i}', ch_5=36, util_5=5) for i in range(10)]

    recs = optimize_5ghz(aps)

    counts: dict[int | None, int] = {}
    for r in recs:
        block = block_80mhz(r['recommended_channel'])
        counts[block] = counts.get(block, 0) + 1

    assert len(counts) == 6, f'expected all six blocks in use, got {counts}'
    assert max(counts.values()) <= 2, f'block over-subscribed: {counts}'


def test_optimize_5ghz_ignores_aps_with_no_5ghz_radio() -> None:
    aps = [_ap('two-four-only', ch_24=6, util_24=50)]
    assert optimize_5ghz(aps) == []


# ─── Defect 3: load-blind 2.4 GHz pairing ────────────────────────────────────


def test_optimize_24ghz_does_not_pair_the_two_busiest_aps() -> None:
    """The regression: the 78%- and 70%-utilised APs were both sent to channel 6."""
    aps = [
        _ap('busiest', ch_24=11, util_24=78, sta_24=37),
        _ap('second', ch_24=11, util_24=70, sta_24=18),
        _ap('third', ch_24=1, util_24=69, sta_24=4),
        _ap('fourth', ch_24=11, util_24=67, sta_24=0),
        _ap('fifth', ch_24=6, util_24=66, sta_24=3),
    ]

    recs = optimize_24ghz(aps)
    by_name = {r['name']: r['recommended_channel'] for r in recs}

    assert by_name['busiest'] != by_name['second'], f'two busiest APs share a channel: {by_name}'


def test_optimize_24ghz_still_uses_only_non_overlapping_channels() -> None:
    aps = [_ap(f'ap{i}', ch_24=1, util_24=10 * i, sta_24=i) for i in range(6)]

    recs = optimize_24ghz(aps)

    assert {r['recommended_channel'] for r in recs} <= {1, 6, 11}


def test_optimize_24ghz_distributes_evenly() -> None:
    """Six APs over three channels should be 2/2/2, not 4/1/1."""
    aps = [_ap(f'ap{i}', ch_24=1, util_24=50, sta_24=5) for i in range(6)]

    recs = optimize_24ghz(aps)

    counts: dict[int, int] = {}
    for r in recs:
        counts[r['recommended_channel']] = counts.get(r['recommended_channel'], 0) + 1
    assert max(counts.values()) - min(counts.values()) <= 1


def test_optimize_24ghz_prefers_cleanest_channel_for_busiest_ap() -> None:
    """Neighbour congestion measured on 2026-08-03: ch1=165, ch6=113, ch11=52."""
    aps = [
        _ap('busiest', ch_24=1, util_24=80, sta_24=35),
        _ap('quiet', ch_24=6, util_24=5, sta_24=1),
    ]

    recs = optimize_24ghz(aps, neighbour_data={1: 165.0, 6: 113.5, 11: 52.5})
    by_name = {r['name']: r['recommended_channel'] for r in recs}

    assert by_name['busiest'] == 11
