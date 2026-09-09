# coding=utf-8
"""설비 id 는 신원이다 — 겹친 채로 저장되면 소비자마다 다른 답을 낸다.

한 id 를 두 행이 나눠 쓰면 읽는 쪽이 저마다 다르게 해석한다: 면적과 유량은
행마다 더하고(facility_calc, irrigation_nozzles), 장치 배선은 첫 행이 이기고
(device_binding), 베이 귀속은 마지막 행이 이기고(facility_bays), 편집기의
삭제는 id 로 지운다(removeMany — 하나를 지우면 쌍둥이까지 사라진다).

실측된 두 사례가 정확히 반대였다는 점이 이 방어의 모양을 정했다:
  * 외피 창은 낡은 치수와 현재 치수가 같은 id 를 달고 있었다 → 낡은 쪽을 버려야
    했다.
  * 스프링클러 둘은 각각 실재하는 다른 배관에 물려 있었다 → 버리면 진짜 노즐이
    사라진다. 하나에 새 id 를 줘야 했다.
어느 쪽인지는 데이터가 말해주지 않으므로, 서버는 조용히 고르지 않고 거절한다.
내용까지 같은 행만 합친다 — 그건 잃을 것이 없다.
"""
import pytest
from flask import Flask

from aot.aot_flask.geo.facility_io import (
    _dedupe_fittings, _remint_cloned_fitting_ids)


@pytest.fixture
def ctx():
    """`_dedupe_fittings` 는 합칠 때 current_app.logger 로 남긴다."""
    app = Flask(__name__)
    with app.app_context():
        yield


def test_identical_duplicates_collapse(ctx):
    """완전히 같은 행은 하나로 합친다 — 정보가 사라지지 않는다."""
    row = {'id': 'F1', 'kind': 'window', 'size': {'w': 1, 'h': 2}}
    cleaned, error = _dedupe_fittings([dict(row), dict(row), {'id': 'F2'}])
    assert error is None
    assert [f['id'] for f in cleaned] == ['F1', 'F2']


def test_conflicting_duplicates_are_refused(ctx):
    """내용이 다르면 어느 쪽이 진짜인지 데이터가 말해주지 않는다 → 거절."""
    cleaned, error = _dedupe_fittings([
        {'id': 'F1', 'size': {'w': 1}},
        {'id': 'F1', 'size': {'w': 2}},
    ])
    assert cleaned is None
    assert 'F1' in error


def test_clean_payload_passes_through_untouched(ctx):
    rows = [{'id': 'F1'}, {'id': 'F2'}, {'id': 'F3'}]
    cleaned, error = _dedupe_fittings(rows)
    assert error is None and cleaned == rows


def test_rows_without_an_id_are_left_alone(ctx):
    """id 가 없는 행은 서로 겹칠 수 없다 — 판단 대상이 아니다."""
    rows = [{'kind': 'fixture'}, {'kind': 'fixture'}, 'not-a-dict']
    cleaned, error = _dedupe_fittings(rows)
    assert error is None and len(cleaned) == 3


def test_clone_remints_uid_ids_and_follows_references():
    """복제본이 원본의 id 를 그대로 물려받으면 둘이 같은 신원을 갖는다."""
    src = [
        {'id': 'Flayer', 'kind': 'irrigation_layer'},
        {'id': 'Fpipe', 'kind': 'irrigation_pipe', 'layer_id': 'Flayer'},
        {'id': 'Fnozzle', 'kind': 'irrigation_device',
         'layer_id': 'Flayer', 'pipe_id': 'Fpipe'},
    ]
    out = _remint_cloned_fitting_ids([dict(x) for x in src])
    new_ids = [f['id'] for f in out]

    assert all(new != old['id'] for new, old in zip(new_ids, src))
    assert len(set(new_ids)) == 3
    # 참조가 새 id 를 따라가야 한다 — 안 그러면 노즐이 남의 배관을 가리킨다.
    assert out[1]['layer_id'] == new_ids[0]
    assert out[2]['layer_id'] == new_ids[0]
    assert out[2]['pipe_id'] == new_ids[1]


def test_clone_keeps_envelope_ids():
    """외피 id 는 구조에서 유도된 이름이고, 저장본과 가상 기술자를 짝짓는
    유일한 근거다(facility_calc._canon_env_vent_id). 새 이름을 주면 짝을 잃고
    같은 창이 두 번 세어진다."""
    src = [{'id': 'env_side_vent_outer_u0_left_single', 'kind': 'side_window',
            'source': 'envelope'}]
    out = _remint_cloned_fitting_ids([dict(x) for x in src])
    assert out[0]['id'] == 'env_side_vent_outer_u0_left_single'
