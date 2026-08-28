# coding=utf-8
"""측정값 패널 마스터 스위치(`show_measurement_panel`) — 켜고 끄기가 실제로
패널을 통째로 숨기는지, 그리고 그 스위치가 아래 항목 선택(`measurements_map`)
을 건드리지 않는지 확인한다.

`show_local_time` 과 같은 패턴이다 — 살아 있는 옵션 객체를 먼저 갱신하고
위젯 인스턴스의 갱신 훅을 부른다. 초기 로드와 라이브 재적용
(`_refreshMeasurementPanel`) 이 같은 관문(`addMeasurementPanel`)을 지나므로
그 함수 하나만 지키면 된다.
"""

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


class TestTheOptionIsDeclared:
    def test_show_measurement_panel_exists_with_a_safe_default(self):
        src = _read('widgets', 'AoT_map.py')
        block = src[src.index("'id': 'show_measurement_panel'"):]
        block = block[:block.index('},')]
        # 기본은 켜짐 — 예전 동작(패널 항상 있음) 그대로 유지해야 업그레이드
        # 직후 조용히 패널이 사라지는 설치가 없다.
        assert "'default_value': True" in block

    def test_it_is_a_master_switch_not_a_selection_field(self):
        """이름·설명이 "무엇을 보여줄지" 가 아니라 "보여줄지 말지" 여야 한다
        — 아래 개별 measurements_* 선택과 헷갈리지 않게."""
        src = _read('widgets', 'AoT_map.py')
        block = src[src.index("'id': 'show_measurement_panel'"):]
        block = block[:block.index('},')]
        assert 'Show the measurement panel' in block


class TestTheGuardIsInTheOneChokepoint:
    def _panel_fn(self):
        src = _read('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                    'aot-map-widget-vector.js')
        body = src.split('function addMeasurementPanel', 1)[1]
        return body[:body.index('\n    function ')]

    def test_addMeasurementPanel_returns_early_when_switched_off(self):
        body = self._panel_fn()
        assert 'show_measurement_panel' in body
        assert 'return;' in body.split('show_measurement_panel', 1)[1][:200]

    def test_the_guard_accepts_both_boolean_and_string_false(self):
        """서버가 넘기는 bool 옵션이 문자열로 오는 경로가 있다 — 둘 중 하나만
        보면 그 경로에서 스위치가 무시된다."""
        body = self._panel_fn()
        guard = body.split('if (innerVars.show_measurement_panel', 1)[1][:120]
        assert '=== false' in guard
        assert "'false'" in guard

    def test_only_one_function_builds_the_panel(self):
        """관문이 둘이면 하나만 고쳤을 때 조용히 갈라진다."""
        src = _read('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                    'aot-map-widget-vector.js')
        assert src.count('function addMeasurementPanel(') == 1


class TestLiveApplyDoesNotClearTheSelectionOnToggle:
    """마스터 스위치를 라이브로 껐다 켜는 동작이 [측정값 선택]을 지우면
    안 된다 — 다시 켰을 때 고르던 항목이 사라져 있으면 사용자는 "스위치를
    켰는데 왜 비어 있나" 를 겪는다."""

    def _live_apply_block(self):
        src = _read('aot_flask', 'static', 'js', 'app',
                    'dashboard-widget-live-preview.js')
        block = src[src.index("key === 'show_measurement_panel'"):]
        return block[:block.index('\n      else')]

    def test_the_live_apply_handler_exists(self):
        block = self._live_apply_block()
        assert '_refreshMeasurementPanel' in block

    def test_it_calls_the_refresh_hook_with_no_argument(self):
        """인자를 주면(=측정값 맵) 그 호출이 현재 선택을 덮어써 지운다 —
        마스터 스위치 토글은 선택과 무관해야 한다."""
        block = self._live_apply_block()
        assert 'inst._refreshMeasurementPanel();' in block

    def test_refresh_measurement_panel_treats_no_argument_as_keep_selection(self):
        src = _read('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                    'aot-map-widget-vector.js')
        body = src.split('_refreshMeasurementPanel = function', 1)[1][:400]
        assert 'if (newMeasurementsMap != null)' in body, (
            '인자 없는 호출(마스터 스위치 라이브 적용)이 현재 선택을 지웁니다')


class TestCacheVersionWasBumped:
    """내용이 바뀌었는데 URL 이 그대로면 1년 캐시가 옛 코드를 계속 실행한다."""

    def test_the_script_tag_carries_a_fresh_version(self):
        html = _read('aot_flask', 'templates', 'pages', 'dashboard.html')
        assert 'dashboard-widget-live-preview.js?v=' in html
        assert 'dashboard-widget-live-preview.js?v=20260813a' not in html
