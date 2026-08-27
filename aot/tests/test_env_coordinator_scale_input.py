# coding=utf-8
"""정할 수 없는 숫자는 **눈금**으로 묻는다 (단계 C′, 2026-08-27).

설계: `docs/design/env-coordinator-settings-redesign.md` §3-5.

`emergency_deviation_mult` 에 3.0 을 넣을지 4.0 을 넣을지 사용자는 **답할 수
없다.** 빈칸에 숫자를 요구하면 아무것도 못 하거나 아무 값이나 넣는다.

## ⚠ 이 파일이 지키는 것 하나 — 저장은 **실제 값** 하나다

`actuation_profile` 이 정확히 그 실수를 했다: 모드 문자열과 숫자를 따로 저장해
둘이 어긋났고, 쿠마모토의 `actuation_period_sec=1200` 은 코드가 안 보는 죽은
값이었다(profile 이 'gentle' 이라). 눈금은 **폼 필드를 하나만** 갖는다 —
원래의 숫자 칸. 어긋날 두 번째 값이 없다.
"""
import json
import os
import re
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))


import re as _re


def _re_finditer(text, pat):
    return list(_re.finditer(pat, text))


def _read(*parts):
    with open(os.path.join(_HERE, '..', *parts), encoding='utf-8') as fh:
        return fh.read()


def _fi():
    if 'flask_babel' not in sys.modules:
        b = types.ModuleType('flask_babel')
        b.lazy_gettext = lambda s: s
        b.gettext = lambda s, **k: s
        sys.modules['flask_babel'] = b
    from aot.functions.custom_functions.env_coordinator_impl import (
        _function_info as fi)
    return fi


def _scales():
    return [o for o in _fi().FUNCTION_INFORMATION['custom_options']
            if o.get('type') == 'select_scale']


class TestTheScaleSchema:

    def test_there_are_scales(self):
        assert len(_scales()) >= 5

    def test_every_scale_declares_its_axis(self):
        """양 끝은 **트레이드오프**여야 한다. "약하게/강하게" 만으로는 무엇이
        강해지는지 모른다 — 사용자가 이해하는 두 가지 사이의 축이어야 한다."""
        for o in _scales():
            assert o.get('axis_low') and o.get('axis_high'), o['id']
            assert str(o['axis_low']) != str(o['axis_high']), o['id']

    def test_step_values_are_numbers(self):
        """단계 이름이 아니라 **값**을 저장한다."""
        for o in _scales():
            for value, label in o['steps']:
                assert isinstance(value, (int, float)), (o['id'], value)
                assert isinstance(label, str) or label is not None

    def test_the_default_is_one_of_the_steps(self):
        """기본값이 어느 단계도 아니면 새 설치가 처음부터 '직접 지정' 으로
        보인다 — 눈금을 만든 뜻이 없다."""
        for o in _scales():
            vals = [v for v, _n in o['steps']]
            assert float(o['default_value']) in [float(v) for v in vals], (
                '%s: 기본 %r 이 단계 %r 에 없다' % (o['id'], o['default_value'], vals))

    def test_steps_are_monotonic(self):
        """축이 한 방향이어야 눈금이 뒤섞이지 않는다."""
        for o in _scales():
            vals = [float(v) for v, _n in o['steps']]
            assert vals == sorted(vals) or vals == sorted(vals, reverse=True), (
                '%s: 단계 값이 한 방향이 아니다 %r' % (o['id'], vals))

    def test_step_labels_are_unique(self):
        for o in _scales():
            names = [str(n) for _v, n in o['steps']]
            assert len(names) == len(set(names)), o['id']


class TestOneFormFieldOnly:
    """모드를 따로 저장하면 두 값이 어긋난다 — `actuation_profile` 의 실수."""

    def test_the_template_renders_exactly_one_input(self):
        tpl = _read('aot_flask', 'templates', 'pages', 'form_options',
                    'Custom_Options.html')
        block = tpl.split("== 'select_scale'", 1)[1].split('{% elif', 1)[0]
        assert block.count('<input') == 1, (
            '눈금 분기가 폼 필드를 여러 개 낸다 — 값이 갈린다')
        assert "type=\"number\"" in block

    def test_the_control_writes_into_that_input(self):
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-scale-input.js')
        assert 'input.value = el._steps[i][0]' in js, (
            '눈금이 원래 숫자 칸에 쓰지 않는다')
        assert 'data-for' in js

    def test_it_does_nothing_without_its_input(self):
        """대상 칸이 없으면 눈금만 그려져 **누를 때마다 아무 데도 안 쓰이는
        조작**이 된다."""
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-scale-input.js')
        block = js.split('function wire(', 1)[1].split('\n  function ', 1)[0]
        assert 'if (!input) return;' in block


class TestItExtendsAotViz:
    """설정 화면의 눈금과 모달의 밴드 바가 다른 모양이면, 사용자는 같은 개념을
    두 번 배워야 한다."""

    def test_it_uses_the_viz_skeleton(self):
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-scale-input.js')
        for cls in ('aot-viz', 'aot-viz-head', 'aot-viz-track',
                    'aot-viz-scale', 'aot-viz-label', 'aot-viz-value'):
            assert cls in js, '%s 를 안 쓴다' % cls

    def test_the_css_lives_with_the_other_primitives(self):
        css = _read('aot_flask', 'static', 'css', 'components',
                    'aot-dataviz.css')
        assert '.aot-viz--scale-input' in css and '.aot-viz-step' in css, (
            '눈금 CSS 가 dataviz 밖에 있다 — 따로 두면 톤이 갈린다')

    def test_the_step_uses_the_same_cap_correction(self):
        """트랙 양끝이 둥글어 0~100%% 를 그대로 매핑하면 마커가 라운드에 박힌다.
        마커와 **같은 보정**을 써야 한다 — 숫자를 따로 적으면 트랙 높이를 바꿀
        때 조용히 어긋난다."""
        css = _read('aot_flask', 'static', 'css', 'components',
                    'aot-dataviz.css')
        block = css.split('.aot-viz-step {', 1)[1].split('}', 1)[0]
        assert '--aot-viz-track-h' in block and '--aot-viz-pos' in block


class TestTheAdvancedSwitch:
    """요약(눈금)과 값(숫자)이 갈라지면 정밀하게 고치려는 사람이 다시 찾아야
    한다(D6). 화면 하나의 스위치가 모든 눈금에 숫자 칸을 함께 연다."""

    def _js(self):
        return _read('aot_flask', 'static', 'js', 'common', 'aot-scale-input.js')

    def test_it_is_one_switch_per_form(self):
        js = self._js()
        assert 'ensureSwitch' in js
        assert '_aotAdvWired' in js, '폼마다 한 번만 만드는 장치가 없다'

    def test_it_opens_the_folds_in_one_go(self):
        """고급을 켰는데 또 세부 메뉴를 열라고 하면 스위치가 일을 절반만 한
        것이다(D13)."""
        js = self._js()
        block = js.split('function applyAdvanced', 1)[1].split('\n  function ', 1)[0]
        assert "collapse:not(.show)" in block

    def test_the_state_is_browser_only(self):
        """설정으로 저장하면 "이 함수는 고급 모드" 라는 없던 상태가 생기고,
        같은 화면을 두 사람이 다르게 본다."""
        js = self._js()
        assert 'localStorage' in js
        assert 'aot_scale_advanced' in js

    def test_the_number_field_is_hidden_not_removed(self):
        """숨길 뿐 지우지 않아야 값이 계속 제출된다 — 스위치를 껐다 켤 때
        설정이 사라지면 안 된다."""
        css = _read('aot_flask', 'static', 'css', 'components',
                    'aot-dataviz.css')
        # ⚠ 리터럴 한 줄로 보지 말 것 — 규칙에 속성을 하나 더하면 여러 줄로
        #   갈라져 검사가 깨진다. 실제로 그랬다(2026-08-27). 보는 것은
        #   **그 선택자의 display 값**이다.
        import re as _re

        def _display(selector):
            m = _re.search(_re.escape(selector) + r"\s*\{([^}]*)\}", css)
            assert m, '%s 규칙이 없다' % selector
            d = _re.search(r"display:\s*([a-z-]+)", m.group(1))
            return d.group(1) if d else None

        assert _display('.aot-scale-number') == 'none'
        assert _display('.aot-advanced .aot-scale-number') == 'flex'


class TestTheViewIsNotDuplicated:
    """`init` 은 설정 폼이 나중에 DOM 에 꽂힐 때 다시 불린다. 그때마다 append
    하면 같은 눈금이 두 벌 그려지고, 두 번째 것을 눌러도 첫 번째가 안 바뀌어
    "눌러도 안 먹는다" 로 보인다(2026-08-27 실제로 그렇게 됐다)."""

    def test_the_view_is_reused(self):
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-scale-input.js')
        # ⚠ `wire()` 안이라고 못박지 말 것 — 그룹 배선이 생기면서 뷰 만드는
        #   자리가 헬퍼로 옮겨졌고, 검사만 깨졌다(2026-08-27). 보는 것은
        #   **만들기 전에 찾아보는가** 이지 어느 함수인가가 아니다.
        assert "querySelector(':scope > .aot-scale-view')" in js
        for m in _re_finditer(js, r"createElement\('div'\)"):
            head = js[max(0, m.start() - 400):m.start()]
            assert 'querySelector' in head, (
                '뷰를 찾아보지 않고 새로 만든다 — init 마다 한 벌씩 쌓인다')


class TestTheParserKnowsIt:
    """빠지면 "Unknown option type" 으로 **파싱이 통째로 멈춘다.**"""

    def test_both_parsers_handle_it(self):
        src = _read('controllers', 'abstract_base_controller.py')
        for fn in ('setup_custom_options_csv', 'setup_custom_options_json'):
            block = src.split('def %s' % fn, 1)[1].split('\n    def ', 1)[0]
            assert "'select_scale'" in block, '%s 가 모른다' % fn

    def test_the_csv_parser_keeps_it_numeric(self):
        """`select` 쪽에 넣으면 문자열로 굳어 제어가 그 값을 못 쓴다."""
        src = _read('controllers', 'abstract_base_controller.py')
        block = src.split('def setup_custom_options_csv', 1)[1].split(
            '\n    def ', 1)[0]
        i_num = block.index("['float', 'select_scale']")
        i_sel = block.index("['select', 'select_custom_choices']")
        assert i_num < i_sel


def test_every_scale_string_is_translated():
    ids = set()
    for o in _scales():
        ids.add(str(o['axis_low']))
        ids.add(str(o['axis_high']))
        for _v, n in o['steps']:
            ids.add(str(n))
    js = _read('aot_flask', 'static', 'js', 'common', 'aot-scale-input.js')
    ids |= set(re.findall(r"_t\('((?:[^'\\]|\\.)+)'\)", js))
    for lang in ('ko', 'ja'):
        po = _read('aot_flask', 'translations', lang, 'LC_MESSAGES',
                   'messages.po')
        missing = [m for m in sorted(ids) if '\nmsgid "%s"\n' % m not in po]
        assert not missing, '%s 카탈로그에 없는 문구: %s' % (lang, missing)
