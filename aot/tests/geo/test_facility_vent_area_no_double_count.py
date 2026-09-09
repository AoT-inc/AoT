# coding=utf-8
"""A wired envelope vent must be counted once, not twice.

``compute_capacity`` builds virtual descriptors for every envelope opening from
the envelope config, because most of them are never persisted. But the ones the
grower actually wires *are* persisted — ``FittingsUI.read()`` deliberately saves
any ``source='envelope'`` fitting carrying an actuator/input binding, hand-set
geometry, or a detached inherit flag, since regeneration cannot reproduce those.

For a long time the aggregation added both: the virtual descriptor *and* the
saved row for the same physical window. Only wired vents were affected, i.e.
exactly the ones the controller drives. Measured 2026-09-08 on live records:
육묘장 reported 1,031 m² of vent area against a real 643, イチゴ 1,351 against
834. Vent area is not a display number — ``effect_functions`` turns it straight
into the opening's effect gain (``af = area_m2 / 10``), so a controller told the
house has 2.6x the vent it owns concludes a small opening already reaches target
and under-opens the windows. It reads as "the control Function is misbehaving".

The list matters as much as the scalar: ``facility_wind`` sums flow over every
entry in ``vent_openings``, so a duplicate descriptor double-counts wind-driven
ventilation too.

The saved row wins over its virtual twin — it carries the real wiring and the
current geometry — and the two are matched by :func:`_canon_env_vent_id`, which
bridges the id shapes of the two generators. That matcher is the load-bearing
part: if the editor renames an id family, matching silently fails and the double
count comes back with no error anywhere. Hence this test.
"""
from aot.aot_flask.geo.facility_calc import compute_capacity, _canon_env_vent_id


def _facility(fittings):
    """A 3-bay connected house with outer side vents, one stage."""
    return {
        'geometry_3d': {
            'span_width_m': 6, 'eave_height_m': 2, 'ridge_height_m': 4,
            'length_m': 85, 'roof_type': 'arch', 'spacing_m': 1,
        },
        'structure': 'connected',
        'bay_count': 3,
        'preset': 'standard_arch',
        'envelope': {
            'layers': [{'id': 'outer', 'role': 'outer', 'type': 'full',
                        'cover': 'vinyl_double'}],
            'side_vent': {'outer': {'enabled': True,
                                    'stages': [{'id': 'lower', 'height_m': 1.2,
                                                'from_floor_m': 0.3}]}},
            'roof_vent': {'outer': {'enabled': False}},
            'curtain': {},
        },
        'actuators': [],
        'fittings': fittings,
    }


def _saved_side_vent(fid, actuator_id, w=82.45, h=1.9):
    """A side vent as the design page persists it once an actuator is bound."""
    return {
        'id': fid, 'kind': 'side_window', 'source': 'envelope',
        'position': {'x': 18.02, 'y': 1, 'z': 42.5},
        'size': {'w': w, 'h': h, 'd': 0.05},
        'actuator_id': actuator_id, '_auto_geom': True, 'inherit_size': True,
    }


def test_saved_envelope_vent_replaces_its_virtual_twin():
    bare = compute_capacity(_facility([]))
    wired = compute_capacity(_facility([
        _saved_side_vent('env_side_vent_outer_u0_left_single', 'act-left'),
        _saved_side_vent('env_side_vent_outer_u0_right_single', 'act-right'),
    ]))

    # Two openings either way — wiring a vent does not add a vent.
    assert len(bare['vent_openings']) == len(wired['vent_openings']) == 2

    # The saved geometry supersedes the estimate, so the area may differ, but it
    # must stay in the same ballpark — never the sum of both (which was the bug).
    assert wired['vent_open_m2'] < bare['vent_open_m2'] * 1.5, (
        'wired vent area %.2f looks like the virtual estimate %.2f counted '
        'twice' % (wired['vent_open_m2'], bare['vent_open_m2'])
    )

    # The wiring has to survive the merge — this is what per-actuator vent area
    # in facility_integration is built from.
    bound = {o['actuator_id'] for o in wired['vent_openings'] if o.get('actuator_id')}
    assert bound == {'act-left', 'act-right'}


def test_unwired_envelope_vents_keep_their_virtual_descriptor():
    """Only the saved side is superseded; a vent nobody wired still counts."""
    one_wired = compute_capacity(_facility([
        _saved_side_vent('env_side_vent_outer_u0_left_single', 'act-left'),
    ]))
    ids = [o['id'] for o in one_wired['vent_openings']]
    assert 'env_side_vent_outer_u0_left_single' in ids   # saved row
    assert 'env_side_vent_outer_right_single' in ids     # virtual twin, unwired
    assert len(ids) == 2


def test_user_placed_vents_are_still_additive():
    """A door the grower placed is a real extra opening, not a duplicate."""
    door = {'id': 'Fabc123', 'kind': 'door', 'position': {'x': 1, 'y': 1, 'z': 0},
            'size': {'w': 2, 'h': 2, 'd': 0.05}}
    with_door = compute_capacity(_facility([door]))
    assert with_door['vent_open_fittings_m2'] == 4.0
    assert len(with_door['vent_openings']) == 3


def test_canon_env_vent_id_bridges_the_two_id_shapes():
    """The editor's ids carry a unit index, a reinforcement marker and a roof
    slope suffix; the virtual descriptors here carry none of them."""
    # 실측 확인된 짝 (육묘장·イチゴ):
    assert _canon_env_vent_id('env_side_vent_outer_u0_right_single') == \
        'env_side_vent_outer_right_single'
    assert _canon_env_vent_id('env_side_vent_outer_reinf_u0_right_upper') == \
        'env_side_vent_outer_right_upper'
    assert _canon_env_vent_id('env_roof_vent_outer_b5_left') == \
        'env_roof_vent_outer_b5'
    # 접미사가 없는 형태(중앙 배치 지붕창)는 그대로 통과해야 한다.
    assert _canon_env_vent_id('env_roof_vent_outer_b2') == 'env_roof_vent_outer_b2'
    assert _canon_env_vent_id(None) is None
