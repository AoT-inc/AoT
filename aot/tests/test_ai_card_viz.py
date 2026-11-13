# coding=utf-8
"""AI 카드 viz(게이지/미니그래프) 첨부 — 스펙 검증·직렬화 (2026-11-06).

설계 .local/plans/ai-card-viz-wiring_20261106.md. 전송은 기존 attach 재사용(새 도구·인자 없음),
저장은 attachment kind 'viz' + spec 칸, 그림은 수신함이 AoTViz 로 인라인.
"""
import json
import types

import pytest

from aot.utils import ai_card_files as F
from aot.utils import ai_screen_cards as C


# ── 스펙 검증 ────────────────────────────────────────────────────────────────

def test_gauge_spec_is_normalized():
    s = F.parse_viz_spec(b'{"viz":"gauge","label":"CO2","value":412,"unit":"ppm",'
                         b'"min":300,"max":1500,"okMin":400,"okMax":900}')
    assert s == {'viz': 'gauge', 'label': 'CO2', 'unit': 'ppm',
                 'value': 412.0, 'min': 300.0, 'max': 1500.0, 'okMin': 400.0, 'okMax': 900.0}


def test_spark_spec_keeps_points_in_order():
    s = F.parse_viz_spec('{"viz":"spark","label":"T","unit":"°C","points":[1,2,3]}')
    assert s == {'viz': 'spark', 'label': 'T', 'unit': '°C', 'points': [1.0, 2.0, 3.0]}


def test_spark_span_label_kept_and_capped():
    s = F.parse_viz_spec('{"viz":"spark","points":[1,2],"span":"last 6 h"}')
    assert s['span'] == 'last 6 h'
    long = ('{"viz":"spark","points":[1,2],"span":"' + 'x' * 99 + '"}')
    assert len(F.parse_viz_spec(long)['span']) == F.VIZ_SPAN_MAX
    # 기간 라벨은 선택 — 없으면 키 자체가 빠진다.
    assert 'span' not in F.parse_viz_spec('{"viz":"spark","points":[1,2]}')
    # 게이지에는 기간 개념이 없다 — span 을 줘도 버린다.
    assert 'span' not in F.parse_viz_spec(
        '{"viz":"gauge","value":1,"min":0,"max":2,"span":"x"}')


def test_spark_keeps_ok_range():
    # 미니그래프도 적정 범위를 받는다 — 옅은 초록 면(게이지 녹색 호와 같은 뜻).
    s = F.parse_viz_spec('{"viz":"spark","points":[1,2],"okMin":1.2,"okMax":1.8}')
    assert (s['okMin'], s['okMax']) == (1.2, 1.8)
    assert 'okMin' not in F.parse_viz_spec('{"viz":"spark","points":[1,2]}')


def test_optional_ok_range_dropped_when_absent():
    s = F.parse_viz_spec(b'{"viz":"gauge","value":5,"min":0,"max":10}')
    assert 'okMin' not in s and 'okMax' not in s


@pytest.mark.parametrize("raw", [
    b'{"viz":"pie","value":1}',                                  # 종류 밖
    b'[1,2,3]',                                                  # 객체 아님
    b'not json',                                                 # JSON 아님
    b'{"viz":"gauge","value":1,"max":10}',                       # min 없음
    b'{"viz":"gauge","value":1,"min":5,"max":5}',                # min==max
    b'{"viz":"gauge","value":1e999,"min":0,"max":10}',           # Inf
    b'{"viz":"gauge","value":true,"min":0,"max":10}',            # bool
    b'{"viz":"gauge","value":"5","min":0,"max":10}',             # 문자열 숫자
    b'{"viz":"spark","points":[1]}',                             # 점 1개
    b'{"viz":"spark","points":[1,"x",3]}',                       # 숫자 아님
])
def test_bad_specs_are_rejected(raw):
    with pytest.raises(F.FileError):
        F.parse_viz_spec(raw)


def test_spark_point_cap():
    over = ('{"viz":"spark","points":[' + ','.join(['1'] * (F.VIZ_MAX_POINTS + 1)) + ']}').encode()
    with pytest.raises(F.FileError):
        F.parse_viz_spec(over)
    okay = ('{"viz":"spark","points":[' + ','.join(['1'] * F.VIZ_MAX_POINTS) + ']}').encode()
    assert len(F.parse_viz_spec(okay)['points']) == F.VIZ_MAX_POINTS


def test_label_is_length_capped_not_html_escaped():
    # 길이만 자른다 — HTML 이스케이프는 그리는 쪽(AoTViz)의 몫이라 여기서 하지 않는다.
    s = F.parse_viz_spec(b'{"viz":"gauge","value":5,"min":0,"max":10,'
                         b'"label":"<b>' + b'x' * 60 + b'</b>"}')
    assert len(s['label']) == F.VIZ_LABEL_MAX


def test_oversize_spec_rejected():
    with pytest.raises(F.FileError):
        F.parse_viz_spec(b'{"viz":"spark","points":[1,2],"label":"' + b'x' * (F.VIZ_MAX_BYTES) + b'"}')


def test_viz_bytes_is_compact_utf8():
    b = F.viz_bytes({'viz': 'gauge', 'label': '기온', 'value': 1.0})
    assert b == '{"viz":"gauge","label":"기온","value":1.0}'.encode('utf-8')


def test_prepare_reads_viz_inline_text():
    item = F.prepare({'name': 'co2.viz', 'text': '{"viz":"gauge","value":5,"min":0,"max":10}'},
                     user=None, user_id=7)
    assert item['kind'] == 'viz' and item['spec']['viz'] == 'gauge'
    assert item['mime'] == 'application/json' and item['thumb'] is None
    assert item['data'] == F.viz_bytes(item['spec'])


def test_prepare_refuses_viz_by_url():
    with pytest.raises(F.FileError):
        F.prepare({'name': 'x.viz', 'url': 'https://example.com/x.viz'}, user=None, user_id=7)


# ── 직렬화(수신함 files) ──────────────────────────────────────────────────────

def _att(**kw):
    base = dict(position=0, kind='viz', spec=None, name='', url=None, provider=None,
                host=None, thumb=None, playable=False, mime=None, size=0, path=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_file_items_emits_spec_for_viz():
    spec = {'viz': 'gauge', 'value': 5.0, 'min': 0.0, 'max': 10.0}
    items = C.file_items([_att(position=2, spec=json.dumps(spec))])
    assert items == [{'i': 2, 'kind': 'viz', 'spec': spec}]


def test_file_items_viz_bad_json_gives_none_spec():
    items = C.file_items([_att(spec='{not json')])
    assert items == [{'i': 0, 'kind': 'viz', 'spec': None}]


def test_file_atts_excludes_viz():
    atts = [_att(kind='file', path='2026/11/a.csv', name='a.csv'), _att(kind='viz', spec='{}')]
    assert [a.kind for a in C.file_atts(atts)] == ['file']
