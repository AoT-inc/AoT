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

class TestTheAdvancedToggleMatchesTheRealOne:
    """[고급] 스위치는 **화면의 다른 토글과 같은 골격**이어야 한다.

    2026-08-27 사용자 신고: *"고급의 토글 버튼 스타일 적용이 잘못 된 것 같아.
    계속 핸들이 안 보여."* 손으로 마크업을 줄이면서 슬라이더 안의 손잡이
    (`btn-toggle-thumb`)를 빠뜨렸다 — 홈만 그려지고 스위치가 어느 쪽인지
    알 수 없다. CSS 가 그 요소를 움직여 켬/끔을 표현하므로, 없으면 표현할
    것 자체가 없다.
    """

    def _parts(self):
        tpl = _read('aot_flask', 'templates', 'pages', 'form_options',
                    'Custom_Options.html')
        block = tpl.split("== 'bool'", 1)[1].split('{% elif', 1)[0]
        import re as _re
        return [c for c in _re.findall(r'btn-toggle[a-z-]*', block)]

    def test_it_uses_every_piece_the_template_uses(self):
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-scale-input.js')
        for cls in set(self._parts()):
            assert cls in js, (
                '[고급] 스위치에 %s 가 없다 — 정본은 Custom_Options.html 의 '
                'bool 옵션 마크업이다' % cls)

    def test_the_thumb_sits_inside_the_slider(self):
        """손잡이는 홈 **안**에 있어야 한다 — 밖에 두면 CSS 가 못 움직인다.

        ⚠ 파일 전체에서 첫 등장 위치를 비교하지 말 것. 이 규칙을 설명하는
          **주석**이 마크업보다 앞에 있어서, 그렇게 재면 규칙을 적어 둔 것만
          으로 검사가 깨진다(2026-08-27 실제로 그랬다). 중첩 그 자체를 본다.
        """
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-scale-input.js')
        assert 'btn-toggle-slider"><div class="btn-toggle-thumb"' in js, (
            '손잡이가 슬라이더 안에 없다')



# ─────────────────────────────────────────────────────────────────────────────
# 구간 입력(range band) — 설명과 "없는 장비" 안내
# ─────────────────────────────────────────────────────────────────────────────

class TestEveryBandExplainsItself:
    """구간 입력에는 **설명 자리가 아예 없었다.**

    눈금 입력(`aot-scale-input`)은 처음부터 `phrase` 를 가졌는데 구간은 안
    가졌다. 그래서 [빛과 차광] 은 설명을 **안 넣은** 것이 아니라 **넣을 곳이
    없었다** — 사용자는 "설정한 범위에서 어떻게 작동하는지 설명도 없고, 기본값도
    0~1200 인데 어떻게 한다는 건지 나도 모르겠다" 고 했다(2026-08-28).

    그 값은 범위가 아니라 **기준선 둘**이다. 아래로 벗어나면 보광·개방, 위로
    벗어나면 차광, 사이에서는 아무것도 하지 않는다.
    """

    def test_every_band_has_a_phrase(self):
        info = _fi()
        for band in info._RANGE_BANDS:
            assert band.get('phrase'), (
                f"{band['id']} 구간에 설명이 없습니다 — 손잡이 둘이 무엇을 "
                f"뜻하는지 화면에서 알 방법이 없습니다")

    def test_the_template_passes_the_phrase(self):
        tpl = _read('aot_flask', 'templates', 'pages', 'form_options',
                    'Custom_Options.html')
        band = tpl.split("== 'range_band'", 1)[1].split('{% elif', 1)[0]
        assert 'data-hint=' in band, '설명을 markup 으로 내보내지 않습니다'
        assert "each_option.get('phrase'" in band

    def test_the_script_reads_the_phrase(self):
        """`data-hard-label` 이 정확히 이 모양으로 죽어 있었다 — 템플릿은
        `data-guide-label` 을 내보내고 JS 는 `data-hard-label` 을 읽어, 그
        라벨이 **늘 빈 문자열**이었다(에러 없이). 이름이 어긋나면 조용하다."""
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-range-band.js')
        assert "getAttribute('data-hint')" in js
        assert '_hint' in js


class TestInertHandlesSaySo:
    """움직일 장비가 없는 손잡이는 그렇게 말해야 한다.

    2026-08-28 실측: 세 시설 모두 `shade`(차광막)도 `lighting`(보광등)도 등록돼
    있지 않았다. 그런데도 [차광·보광 기준] 은 평범하게 보였다 — 무엇을 넣어도
    아무 일이 일어나지 않는데 화면은 아무 말이 없었다.

    (영양의 '보온커튼'은 `curtain` 이라 해당하지 않는다. 사용자는 아주 강한
    일사일 때만 **수동으로** 쓴다 — 자동 차광용으로 재분류하면 코디네이터가
    멋대로 닫는다.)
    """

    def test_the_light_band_declares_what_it_needs(self):
        info = _fi()
        band = [b for b in info._RANGE_BANDS if b['id'] == 'light'][0]
        assert band.get('requires_min') == 'lighting'
        assert band.get('requires_max') == 'shade'

    def test_the_template_passes_it_with_the_function_id(self):
        tpl = _read('aot_flask', 'templates', 'pages', 'form_options',
                    'Custom_Options.html')
        band = tpl.split("== 'range_band'", 1)[1].split('{% elif', 1)[0]
        for attr in ('data-requires-min', 'data-requires-max', 'data-function-id'):
            assert attr in band, f'{attr} 를 내보내지 않습니다'

    def test_the_endpoint_reports_actuator_kinds(self):
        """출처는 코디네이터가 쓰는 것과 **같아야 한다**.

        `env.summary.commands` 로 대신하면 "이번 사이클에 명령을 받은 것" 만
        보이므로, 아직 한 번도 안 돈 코디네이터에서는 전부 없다고 말한다.
        """
        src = _read('aot_flask', 'routes_geo_iec.py')
        block = src.split('def api_coordinator_overview', 1)[1].split('\n@', 1)[0]
        assert "'actuator_kinds'" in block
        assert 'actuators_resolved' in block, (
            '코디네이터와 다른 출처를 씁니다')

    def test_a_failed_lookup_is_unknown_not_empty(self):
        """조회 실패를 빈 목록으로 두면 **"장비가 하나도 없다" 로 둔갑**해,
        멀쩡한 설정에 "쓰이지 않습니다" 를 붙인다."""
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-range-band.js')
        body = js.split('function loadKinds', 1)[1].split('\n  function ', 1)[0]
        assert 'list ? {list: list} : {}' in body, (
            '조회 실패와 "장비 없음" 이 구분되지 않습니다')
        assert 'known.list' in js, '미지 상태에서 안내를 내면 안 됩니다'


class TestLadderVocabularyIsConsistent:
    """한 사다리는 말투가 하나여야 읽힌다.

    `Standard`·`Strong` 같은 흔한 낱말을 쓰면 카탈로그에 이미 있는 다른 문맥의
    번역이 붙는다 — 실제로 분무 사다리가 `약하게 · 표준 · 강함 · 아주 강하게`
    로 나왔다(2026-08-28). 값은 맞는데 말투만 어긋나서, 화면을 봐야만 안다.
    """

    def test_no_step_label_repeats_inside_a_group(self):
        info = _fi()
        for group in info._SCALE_GROUPS:
            labels = [str(s[0]) for s in group['steps']]
            assert len(labels) == len(set(labels)), f"{group['id']} 단계 이름 중복"

    def test_the_misting_ladder_goes_up_in_frequency(self):
        info = _fi()
        g = [x for x in info._SCALE_GROUPS if x['id'] == 'misting_care'][0]
        assert len(g['steps']) == 5
        assert str(g['steps'][0][0]) == 'Not used', '첫 칸은 끄는 칸이다'
        # 오른쪽으로 갈수록 **더 자주** 돌아야 한다 — 축 라벨이 그렇게 말한다.
        on = [s[1].get('nursery_max_on_sec') for s in g['steps'][1:]]
        assert on == sorted(on), f'1회 작동 시간이 단조 증가하지 않습니다: {on}'
        off = [s[1].get('nursery_min_off_sec') for s in g['steps'][1:]]
        assert off == sorted(off, reverse=True), f'쉬는 시간이 단조 감소하지 않습니다: {off}'

    def test_misting_is_never_called_a_strength(self):
        """관수·분무 밸브는 거의 전부 **on/off 제어**라 PWM 이 안 된다 — 물살을
        줄일 방법이 없다. 조절할 수 있는 것은 작동 시간과 빈도뿐이라 '세기' 는
        물리적으로 틀린 말이다(사용자 지적, 2026-08-28). 한 번 그렇게 붙였다가
        고쳤고, `nursery_max_on_sec` 의 설명은 처음부터 옳게 적혀 있었는데
        그룹 이름만 어긋나 있었다."""
        info = _fi()
        g = [x for x in info._SCALE_GROUPS if x['id'] == 'misting_care'][0]
        text = (str(g['name']) + ' ' + str(g.get('phrase') or '')).lower()
        for bad in ('strength', 'how much water', 'intensity'):
            assert bad not in text, f'분무를 세기로 설명합니다: {bad!r}'
        assert 'frequen' in text, '빈도로 설명하지 않습니다'

    def test_the_leftmost_vent_step_matches_the_axis(self):
        """축 왼쪽 끝이 "목표를 바짝 쫓음" 인데 가장 왼쪽 칸이 '표준' 이었다 —
        없는 선택지를 약속했다."""
        info = _fi()
        g = [x for x in info._SCALE_GROUPS if x['id'] == 'vent_economy'][0]
        assert str(g['steps'][0][0]) == 'High performance'
        assert str(g['steps'][-1][0]) == 'Energy saving'


class TestBandTextDoesNotUsePositions:
    """트랙은 **가로**인데 설명은 트랙 **아래**에 있다.

    그래서 "아래 값" 이 어느 것을 가리키는지 알 수 없다 — 왼쪽 손잡이인지,
    설명 아래의 숫자 칸인지(사용자 지적, 2026-08-28). 손잡이는 위치가 아니라
    **하는 일**이나 **구간과의 관계**로 부른다.
    """

    POSITIONAL = ('lower value', 'upper value', 'the limits below',
                  'the value below', 'value above this')

    def test_no_band_phrase_names_a_position(self):
        info = _fi()
        for band in info._RANGE_BANDS:
            text = str(band.get('phrase') or '').lower()
            for bad in self.POSITIONAL:
                assert bad not in text, (
                    f"{band['id']} 설명이 위치로 가리킵니다: {bad!r}")

    def test_the_inert_notice_names_the_purpose_not_the_side(self):
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-range-band.js')
        body = js.split('function inertNotice', 1)[1].split('\n  function ', 1)[0]
        assert '_kindPurpose' in body, '하는 일(보광·차광)로 부르지 않습니다'
        for bad in ("_t('lower')", "_t('upper')"):
            assert bad not in js, f'위치 낱말이 남아 있습니다: {bad}'


class TestTheInertNoticeComesFirst:
    """설명 끝에 두면 **끝까지 읽어야** 이 설정이 무의미하다는 것을 안다.

    사용자 지적(2026-08-28): *"결국 이 시설에는 아무 설비가 없기 때문에 이
    옵션은 무의미한건데, 사용자가 끝까지 읽어야 알 수 있음."*
    """

    def _render_body(self):
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-range-band.js')
        return js.split('function render(el)', 1)[1].split('\n  /*', 1)[0]

    def test_the_notice_is_emitted_before_the_track(self):
        body = self._render_body()
        notice = body.find('aot-band-inert')
        track = body.find("'<div class=\"aot-viz-track\">'")
        assert notice > 0 and track > 0
        assert notice < track, (
            '안내가 트랙 뒤에 나옵니다 — 맨 먼저 말해야 합니다')

    def test_the_how_it_works_text_is_dropped_when_nothing_can_act(self):
        """아무것도 못 하는 설정에 "이렇게 동작합니다" 를 붙이면 속이는 것이다."""
        body = self._render_body()
        assert 'inert && inert.all' in body, (
            '전부 무의미할 때도 동작 설명을 그대로 보여 줍니다')
