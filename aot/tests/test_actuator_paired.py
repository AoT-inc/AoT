# coding=utf-8
from types import SimpleNamespace

import pytest

from aot.outputs.actuator_paired import (
    OUTPUT_INFORMATION,
    OutputModule,
    ACTUATOR_KIND_OPTIONS,
    KIND_TO_PROFILE_KIND,
)
from aot.functions.utils.env_control.types import ACTUATOR_KINDS


class _EmptyQuery:
    """Stands in for the OutputChannel query so construction stays off the DB."""

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return []


@pytest.fixture
def module(monkeypatch):
    monkeypatch.setattr(
        'aot.outputs.actuator_paired.db_retrieve_table_daemon',
        lambda *args, **kwargs: _EmptyQuery())

    def _plain_logger(self, testing=False, name=None, output_dev=None):
        import logging
        self.logger = logging.getLogger('test.actuator_paired')

    # The real one reads the log level out of the AoT database.
    monkeypatch.setattr(
        'aot.outputs.base_output.AbstractOutput.setup_logger', _plain_logger)

    output = SimpleNamespace(
        unique_id='paired-1', name='paired-1', output_type='actuator_paired',
        latitude=None, longitude=None, location_source='manual',
        log_level_debug=False)
    return OutputModule(output, testing=True)


def test_output_name_unique():
    assert OUTPUT_INFORMATION['output_name_unique'] == 'actuator_paired'


def test_output_types_value():
    assert OUTPUT_INFORMATION['output_types'] == ['value']


def test_channel0_is_value_type():
    ch = OUTPUT_INFORMATION['channels_dict'][0]
    assert 'value' in ch['types']


def test_button_send_value():
    assert 'button_send_value' in OUTPUT_INFORMATION['options_enabled']


def test_required_options_present():
    ids = {o['id'] for o in OUTPUT_INFORMATION['custom_channel_options']}
    must = {
        'actuator_kind',
        'output_open_id', 'output_close_id',
        'travel_time_open_sec', 'travel_time_close_sec',
        'calib_direction',
    }
    assert must.issubset(ids), f"missing: {must - ids}"


def test_no_unidirectional_options():
    ids = {o['id'] for o in OUTPUT_INFORMATION['custom_channel_options']}
    assert 'output_relay_id' not in ids
    assert 'on_threshold_pct' not in ids


def test_all_kinds_map_to_known_actuator_kinds():
    for kind_id, _label in ACTUATOR_KIND_OPTIONS:
        target = KIND_TO_PROFILE_KIND.get(kind_id)
        assert target is not None, f"{kind_id} 매핑 없음"
        assert target in ACTUATOR_KINDS, f"{target} not in ACTUATOR_KINDS"


def test_actuator_kind_default_is_side_vent():
    opt = next(o for o in OUTPUT_INFORMATION['custom_channel_options']
               if o['id'] == 'actuator_kind')
    assert opt['default_value'] == 'side_vent'


def test_kind_to_profile_kind_complete():
    expected = {kind_id for kind_id, _ in ACTUATOR_KIND_OPTIONS}
    assert set(KIND_TO_PROFILE_KIND.keys()) == expected


def test_calibration_commands_present():
    ids = {c['id'] for c in OUTPUT_INFORMATION.get('custom_commands', [])}
    assert 'calib_run' in ids
    assert 'calib_stop' in ids


def test_calibrated_travel_time_takes_effect_without_a_reload(module):
    """A freshly calibrated travel time must be visible to the running module.

    set_custom_channel_option() only writes the database, while options_channels
    is built once in __init__. Before _save_option() existed, calibrating stored a
    travel time the module could not see: _get_travel_time() fell back to its 60 s
    default and the next move drove the motor for that duration instead of the
    measured one, into the end stop. Saving the output form happened to reload the
    module and hide it — which is what the calibration message's "Reload page to
    confirm" hint was really working around.
    """
    saved = {}
    module.set_custom_channel_option = lambda ch, key, value: saved.__setitem__(key, value)

    assert module._get_travel_time('open') == 60.0  # uncalibrated fallback

    module._save_option('travel_time_open_sec', 12.0)  # what calib_stop does

    assert saved['travel_time_open_sec'] == 12.0  # persisted
    assert module._get_travel_time('open') == 12.0  # and visible in-memory


def test_saved_position_is_visible_in_memory(module):
    saved = {}
    module.set_custom_channel_option = lambda ch, key, value: saved.__setitem__(key, value)

    module._save_position(42.0)

    assert saved['last_position_pct'] == 42.0
    assert module._opt('last_position_pct') == 42.0


# ─────────────────────────────────────────────────────────────────────────────
# 릴레이 참조가 비었을 때 — 조용히 성공으로 돌아가면 안 된다
# ─────────────────────────────────────────────────────────────────────────────
# `select_channel` 옵션은 프레임워크가 읽을 때 dict 로 파싱되는데, 저장된 값이
# 출력 UUID 하나뿐이면 `{'device_id': None, 'channel_id': None}` 이 되어 여기
# 오기도 전에 비어 버린다(`_parse_ref` 주석, 2026-08-19 실측).
#
# 그 상태가 조용하면 명령은 성공으로 돌아가는데 릴레이는 돌지 않는다. 실측
# (2026-09-07 영양 천창1): 130회가 전부 성공으로 집계되고, 코디네이터는 그 창이
# 열렸다고 믿은 채 부하분담 장부에 그 몫을 쌓았다.

_EMPTY_REF = {'device_id': None, 'channel_id': None}


def test_relay_on_with_an_unresolvable_ref_raises(module):
    """켤 수 없으면 **예외**다 — 이 경로에서 위로 가는 신호는 그것뿐이다.

    데몬(`aot_daemon.output_on`)이 이 예외를 잡아 `(1, msg)` 로 바꾸고,
    코디네이터 쪽 어댑터가 그 반환값을 검사한다. 여기서 조용히 return 하면
    그 사슬이 첫 칸에서 끊긴다.
    """
    with pytest.raises(RuntimeError) as exc:
        module._relay_on(_EMPTY_REF)
    assert 'resolve' in str(exc.value)


def test_relay_off_with_an_unresolvable_ref_does_not_raise(module):
    """끄기는 **예외를 올리지 않는다** — 켜기와 일부러 다르다.

    정지 경로(`output_switch(state='off')`)는 양쪽 릴레이에 연달아 이 함수를
    부른다. 한쪽 설정이 비었다고 예외를 올리면 반대쪽 정지와 위치 저장까지
    함께 중단된다 — 못 켜는 것보다 못 끄는 것이 위험하다.
    """
    module._relay_off(_EMPTY_REF)          # 예외가 나면 테스트 실패


def test_empty_option_is_not_an_error(module):
    """옵션 자체가 비어 있는 것(설정 안 함)은 정상이다 — 해소 실패와 다르다."""
    module._relay_on('')
    module._relay_on(None)
    module._relay_off('')


def test_drive_does_not_mark_motion_when_the_relay_could_not_fire(module):
    """켜지 못했으면 '움직이는 중' 상태를 만들지 않는다.

    `_drive` 는 `_relay_on` 뒤에 `_motion_*` 와 워치독을 세운다. 릴레이가 안
    켜졌는데 그 상태가 서면 경과시간 기반 위치 추정(`_compute_current_position`)
    이 **실제로 안 움직인 창을 움직인 것으로** 기록한다.
    """
    module.options_channels = getattr(module, 'options_channels', {})
    module._save_option = lambda *a, **k: None
    module._opt = lambda key: _EMPTY_REF if key in (
        'output_open_id', 'output_close_id') else None

    module._position_pct = 0.0
    module._motion_dir = 'idle'

    with pytest.raises(RuntimeError):
        module._drive(50.0)

    assert module._motion_dir == 'idle', (
        '릴레이가 안 켜졌는데 이동 상태가 섰습니다 — 위치 추정이 오염됩니다')
