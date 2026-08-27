# coding=utf-8
"""설정 화면 머리말 — **설정이 아니라 답이다** (단계 A, 2026-08-27).

설계: `docs/design/env-coordinator-settings-redesign.md` §3-1.

화면이 "어떤 값을 설정했나" 만 보여 주고 **"그래서 어떻게 도는가" 는 다른
화면(지도 위젯 모달)에 있었다.** 62개를 설정하고 저장했는데 결과를 확인할
방법이 없으면 설정이 맞는지 알 수 없고, **확인할 수 없는 것은 믿을 수 없다.**

그리고 목표(VPD·온도 곡선)는 이 화면이 아니라 **구획에 붙은 프로그램**이
갖는데, 화면이 그 사실을 말하지 않아 사용자가 여기서 찾으면 영영 못 찾는다.
"""
import os
import re
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))


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


class TestItIsAMarkerNotAnOption:
    """값을 싣지 않으므로 `header` 와 같은 부류다."""

    def test_it_comes_first(self):
        opts = _fi().FUNCTION_INFORMATION['custom_options']
        assert opts[0].get('type') == 'env_status', (
            '머리말이 맨 앞이 아니다 — 설정 아래로 밀리면 아무도 안 본다')

    def test_it_carries_no_value(self):
        """`id` 를 주면 값 옵션으로 세어져 파서가 attribute 를 만든다."""
        opts = _fi().FUNCTION_INFORMATION['custom_options']
        marker = [o for o in opts if o.get('type') == 'env_status']
        assert len(marker) == 1
        assert 'id' not in marker[0] and 'default_value' not in marker[0]

    def test_the_parser_skips_it(self):
        """빠지면 "Unknown option type" 으로 **파싱이 통째로 멈춘다** —
        2026-08-27 에 collapse 표식이 실제로 그랬다(62개 중 9개만 설정).

        ⚠ 예전에는 "세 자리에 `'env_status'` 가 적혀 있는가" 로 봤다. 자리가
          여섯이고(CSV·JSON × 세 검사) 손으로 적혀 있었으니, 새 종류를 넣을
          때마다 일부를 빠뜨렸다 — 2026-08-27 하루에 두 번 났다. 이제 목록은
          **상수 하나**이고, 검사는 *그 상수가 실제로 쓰이는가* 를 본다.
        """
        from aot.controllers import abstract_base_controller as abc
        for name in ('NO_ID_REQUIRED_TYPES', 'NO_DEFAULT_REQUIRED_TYPES',
                     'DISPLAY_ONLY_TYPES'):
            assert 'env_status' in getattr(abc, name), (
                '%s 에 머리말 표식이 없다' % name)
        parser = _read('controllers', 'abstract_base_controller.py')
        for fn in ('setup_custom_options_csv', 'setup_custom_options_json'):
            block = parser.split('def %s' % fn, 1)[1].split('\n    def ', 1)[0]
            for name in ('NO_ID_REQUIRED_TYPES', 'NO_DEFAULT_REQUIRED_TYPES',
                         'DISPLAY_ONLY_TYPES'):
                assert name in block, (
                    '%s 가 %s 를 쓰지 않는다 — 목록을 손으로 다시 적었는가?'
                    % (fn, name))

    def test_the_option_count_is_unchanged(self):
        """머리말은 옵션이 아니다 — 62개 그대로여야 한다.

        ⚠ 표식 목록을 여기 손으로 적지 말 것. `range_band` 는 `id` 를 갖는데
          (어느 밴드인지) 옵션이 아니라, 손으로 적은 목록에서 빠지자 **옵션으로
          세어져 64가 됐다.** 정본은 `_apply_layout` 의 `_MARKERS` 하나다.
        """
        import inspect
        import re as _re
        fi = _fi()
        src = inspect.getsource(fi._apply_layout)
        markers = tuple(_re.findall(
            r"'([a-z_]+)'",
            _re.search(r"_MARKERS = \(([^)]*)\)", src, _re.S).group(1)))
        opts = fi.FUNCTION_INFORMATION['custom_options']
        vals = [o for o in opts if o.get('id') and o.get('type') not in markers]
        assert len(vals) == 62, len(vals)


class TestTheTemplateOnlyLaysTheSpot:
    """라이브 데이터라 서버 렌더로는 저장할 때만 갱신된다."""

    def test_the_branch_exists(self):
        tpl = _read('aot_flask', 'templates', 'pages', 'form_options',
                    'Custom_Options.html')
        assert "== 'env_status'" in tpl
        block = tpl.split("== 'env_status'", 1)[1].split('{% elif', 1)[0]
        assert 'data-function-id' in block, '함수 uuid 를 안 넘긴다'

    def test_it_does_not_use_the_message_type(self):
        """`message` 는 import 시점에 고정된 문자열이라 **모든 코디네이터가
        같은 것을 본다.**"""
        fi = _fi()
        opts = fi.FUNCTION_INFORMATION['custom_options']
        assert opts[0].get('type') != 'message'


class TestTheRendererReusesSharedClasses:
    """`feedback_shared_css`: aot-* 공용 클래스를 재사용하고 새 CSS 를 만들지
    않는다. 자체 클래스를 만들면 화면마다 모양이 갈린다."""

    def _js(self):
        return _read('aot_flask', 'static', 'js', 'common', 'aot-env-status.js')

    def test_no_private_classes(self):
        js = self._js()
        assert 'aot-env-status-' not in js, (
            '자체 CSS 클래스를 만들었다 — 공용 골격(aot-modal-*)을 쓸 것')

    def test_it_uses_the_shared_skeleton(self):
        js = self._js()
        for cls in ('aot-modal-group-title', 'aot-modal-container',
                    'aot-modal-option-row', 'aot-modal-option-label'):
            assert cls in js, '%s 를 안 쓴다' % cls


class TestItSpeaksWhenNothingIsRunning:
    """침묵하면 "아직 안 붙었다" 와 "붙었는데 안 돈다" 를 구분할 수 없다."""

    def test_every_dead_state_has_its_own_sentence(self):
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-env-status.js')
        for needle in ('No facility is linked yet',
                       'No integrated environment control is linked',
                       'Control is switched off',
                       'Not responding'):
            assert needle in js, '%r 상태를 말하지 않는다' % needle


class TestTheEndpointDoesNotDuplicateJudgement:
    """요약 판정을 두 곳에서 계산하면 갈라지고, 갈라지면 설정 화면과 지도
    모달이 **다른 말을 한다.**"""

    def _src(self):
        return _read('aot_flask', 'routes_geo_iec.py')

    def test_it_reuses_the_existing_summary_view(self):
        block = self._src().split('def api_coordinator_overview', 1)[1]
        assert '_unwrap_json(api_facility_env_summary(' in block, (
            '요약을 다시 계산하고 있다 — 기존 뷰를 부를 것')

    def test_it_does_not_use_the_heavy_bundle(self):
        """`/facility/<uuid>/overview` 는 대지 요약·기상 위험까지 묶어 30초
        캐시로 낸다(실측 534~641ms). 설정 화면 머리말에는 과하다."""
        block = self._src().split('def api_coordinator_overview', 1)[1]
        assert 'api_facility_overview(' not in block

    def test_the_facility_key_is_read_in_one_place(self):
        """`geo_facility_id` 와 `geo_facility_id_device_id` 두 키를 읽는 자리가
        여럿이면 갈라지고, "붙었는데 안 붙은 것으로 보이는" 시설이 생긴다."""
        # ⚠ **실제 읽는 호출만 센다.** 이름이 나오는 횟수를 세면 그 규칙을
        #   설명하는 독스트링까지 걸린다 — 규칙을 적는 것이 규칙 위반이 되는
        #   셈이다(CLAUDE.md 가 AST 검사에서 같은 함정을 적어 두었다).
        reads = re.findall(r"\.get\('geo_facility_id(?:_device_id)?'\)",
                           self._src())
        assert len(reads) == 2, (
            '시설 키를 읽는 자리가 `_function_facility_uuid` 밖에도 있다: %d곳'
            % len(reads))

    def test_a_missing_facility_is_reported_not_hidden(self):
        block = self._src().split('def api_coordinator_overview', 1)[1]
        assert "'facility': None" in block


def test_every_ui_string_is_translated():
    """⚠ 문구를 넣고 카탈로그를 빠뜨리면 한국어 화면에 영어가 섞인다 —
    2026-08-27 첫 렌더에서 실제로 절반만 번역돼 나왔다."""
    js = _read('aot_flask', 'static', 'js', 'common', 'aot-env-status.js')
    ids = set(re.findall(r"_t\('((?:[^'\\]|\\.)+)'\)", js))
    kinds = js.split('var KIND_LABEL = {', 1)[1].split('};', 1)[0]
    ids |= set(re.findall(r":\s*'([^']+)'", kinds))
    for lang in ('ko', 'ja'):
        po = _read('aot_flask', 'translations', lang, 'LC_MESSAGES',
                   'messages.po')
        missing = [m for m in sorted(ids)
                   if '\nmsgid "%s"\n' % m.replace('\\', '') not in po]
        assert not missing, '%s 카탈로그에 없는 문구: %s' % (lang, missing)


def test_no_ui_string_carries_a_double_quote():
    """`.po` 의 문자열 구분자라 이스케이프 없이 넣으면 그 카탈로그가 깨진다."""
    js = _read('aot_flask', 'static', 'js', 'common', 'aot-env-status.js')
    for m in re.findall(r"_t\('((?:[^'\\]|\\.)+)'\)", js):
        assert '"' not in m, m
