# coding=utf-8
"""압력 요약(`pressure_brief`) — L0 일 때 관경이 빈 배관의 id 를 싣는다. 설계 화면 '관경 입력' 목록이 이것으로 어느 배관인지 안다."""
from aot.utils.water_net_link import pressure_brief


def test_l0_brief_lists_which_pipes_lack_a_diameter():
    row = {'level': 'L0', 'reasons': ['pipe-diameter-unknown'],
           'coverage': {'ratio': 0.5},
           'missing': [{'pipe': 'pipe-seg-upho7ao1c', 'length_m': 2.0}, {'pipe': 'a', 'length_m': 31.4}]}
    out = pressure_brief(row)
    assert out['missing_pipes'] == 2
    assert out['missing'] == [{'pipe': 'pipe-seg-upho7ao1c', 'length_m': 2.0}, {'pipe': 'a', 'length_m': 31.4}]


def test_l0_brief_without_missing_pipes_has_no_list():
    out = pressure_brief({'level': 'L0', 'reasons': ['no-pump'], 'coverage': None, 'missing': []})
    assert 'missing' not in out and 'missing_pipes' not in out


def _solved(level, worst, **extra):
    row = {'level': level, 'reasons': [], 'assumptions': ['elevation-flat'], 'warnings': [],
           'coverage': {'ratio': 0.885}, 'missing': [],
           'summary': {'bar_min': 1.73, 'bar_max': 2.41, 'pump_lpm': 396.7, 'pump_head_m': 32.0,
                       'flow_ratio_min': 0.87, 'worst_nozzle': worst}}
    row.update(extra)
    return row


def test_solved_brief_carries_the_weakest_nozzle_for_find_on_map():
    out = pressure_brief(_solved('L1', 'sprinkler-1'))
    assert out['worst_nozzle'] == 'sprinkler-1'
    # 점적 줄은 배관 하나가 노즐 하나 — 지도에서는 그 배관을 찾는다
    assert pressure_brief(_solved('L1', 'drip:pipe-9'))['worst_nozzle'] == 'pipe-9'


def test_partial_brief_adds_excluded_length_and_the_empty_pipes():
    row = _solved('L1-partial', 'n1', excluded_ratio=0.115, excluded_m=21.3,
                  missing=[{'pipe': 'p1', 'length_m': 2.0}, {'pipe': 'p2', 'length_m': 19.3}])
    out = pressure_brief(row)
    assert out['excluded_m'] == 21.3 and out['missing_pipes'] == 2
    assert out['missing'] == [{'pipe': 'p1', 'length_m': 2.0}, {'pipe': 'p2', 'length_m': 19.3}]
    # 기존 키는 그대로
    for key in ('bound', 'excluded_ratio', 'diameter_ratio', 'bar_min', 'bar_max', 'assumptions'):
        assert key in out


def test_full_brief_keeps_its_old_shape_plus_the_nozzle():
    out = pressure_brief(_solved('L1', 'n1'))
    assert set(out) == {'level', 'bar_min', 'bar_max', 'pump_lpm', 'pump_head_m', 'flow_ratio_min',
                        'assumptions', 'worst_nozzle'}


def test_brief_names_its_circuit_so_an_area_with_several_circuits_can_be_told_apart():
    assert pressure_brief(_solved('L1', 'n1', network=2))['network'] == 2
    assert pressure_brief({'level': 'L0', 'reasons': ['no-pump'], 'coverage': None, 'missing': [], 'network': 0})['network'] == 0
