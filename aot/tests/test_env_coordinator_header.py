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

    def test_it_sits_right_under_the_facility_picker(self):
        """맨 위가 아니라 **[연동 시설] 바로 뒤**다 (2026-08-27).

        사용자 지적: *"옵션 초반에 정보가 너무 많아 … 여긴 설정하는 곳이지
        확인하는 곳은 아니야."* 그리고 *"시설을 연동하면 연동한 시설 정보가
        그 아래에 나오는게 더 자연스러워. 설정하고 그 위치에서 확인."*

        ⚠ 그래도 **첫 묶음 안**이어야 한다. 더 밀리면 시설을 안 고른 사람이
          왜 아무것도 안 도는지 알 수 없다.
        """
        opts = _fi().FUNCTION_INFORMATION['custom_options']
        at = [i for i, o in enumerate(opts)
              if o.get('type') == 'env_status']
        assert len(at) == 1, '상태 줄이 %d개다' % len(at)
        ids = [o.get('id') for o in opts[:at[0]]]
        assert 'geo_facility_id' in ids, '시설 고르는 칸보다 앞에 있다'
        # 두 번째 묶음 제목이 오기 전이어야 한다.
        heads = [i for i, o in enumerate(opts) if o.get('type') == 'header']
        assert len(heads) >= 2 and at[0] < heads[1], (
            '상태 줄이 첫 묶음 밖으로 밀렸다')

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
        """머리말은 옵션이 아니다 — 표식을 더해도 개수가 안 늘어야 한다.

        숫자는 **스냅샷**이다. 옵션을 더하거나 빼는 것은 정상이지만, 그때는
        여기 숫자도 같은 커밋에서 고치면서 "정말 빼도 되는가" 를 한 번 묻게
        된다. 표식(`env_status`·`scale_group`·`range_band`)이 옵션으로 새면
        고치지 않았는데도 숫자가 늘어난다 — 그것이 이 검사가 잡는 것이다.

        이력: 62 → **61** (`shade_transmittance` 가 시설로 갔다 — D9)
              61 → **60** (`schedule_week_offset` 제거 — 구획 `started_on` 을
                           고치면 되는 값이다. 로컬 3개 전부 0 이었다)
              60 → **59** (`debug_logging` 제거 — 화면 위 [기본 설정] 의
                           `log_level_debug` 와 같은 스위치가 둘이었고,
                           그쪽을 켜지 않으면 혼자서는 아무것도 출력하지
                           못했다. 기본 로거 레벨이 ERROR 다). 2026-08-27.
              59 → **58** (`schedule_end_time` 제거 — 구획이 없으면 자기
                           guide 범위로 도는 R2 가 이미 "빈 온실도 안전
                           한계는 지킨다" 를 만족하고 있어, 별도의 하드
                           정지가 필요했던 적이 없었다. 2026-09-02).

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
        assert len(vals) == 58, len(vals)


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
        """자체 클래스를 만들면 화면마다 모양이 갈린다.

        ⚠ 묶음 제목(`aot-modal-group-title`)은 **이제 안 쓴다** — 카드 둘이
          두 줄이 되면서 제목이 내용보다 커졌다. 남는 것은 설정 행과 같은
          골격이다.
        """
        js = self._js()
        for cls in ('aot-modal-option-row', 'aot-modal-option-label',
                    'aot-modal-body-text'):
            assert cls in js, '%s 를 안 쓴다' % cls
        # `.aot-env-status` 는 **담는 그릇**이라 예외다(템플릿이 그 자리를
        # 깐다). 그 밖의 `aot-env-*` 는 자체 모양을 만든 것이다.
        import re as _re
        made = {c for c in _re.findall(r'aot-env-[a-z-]+', js)
                if c != 'aot-env-status'}
        assert not made, '자체 클래스를 만들었다 — 공용 골격을 쓸 것: %s' % made


class TestItSpeaksWhenNothingIsRunning:
    """침묵하면 "아직 안 붙었다" 와 "붙었는데 안 돈다" 를 구분할 수 없다."""

    def test_every_dead_state_has_its_own_sentence(self):
        """"안 돈다" 는 이유가 여럿이고, 뭉치면 사용자가 엉뚱한 곳을 고친다.

        ⚠ **"시설 미선택" 은 예외다.** 그 상태에서는 아무 말도 하지 않는다 —
          바로 위가 [연동 시설] 칸이라 고르라는 말이 그 자리에 이미 있다.
          맨 위에 있던 시절에는 필요했다(2026-08-27 자리 이동).
        """
        js = _read('aot_flask', 'static', 'js', 'common', 'aot-env-status.js')
        # '응답 없음' → '멈춘 것 같음' 으로 고쳤다(2026-08-28). "응답이 없다" 는
        # 통신 문제로 읽히는데, 실제 뜻은 **그 시간 동안 판단이 없었다** 다.
        for needle in ('No integrated environment control is linked',
                       'Control is switched off',
                       'Control seems stopped'):
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


# ─────────────────────────────────────────────────────────────────────────────
# 데이터에 따라 달라지는 문구
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# 데이터에 따라 달라지는 문구
# ─────────────────────────────────────────────────────────────────────────────

class TestDynamicTextIsHonest:
    """옵션·시설 데이터에 따라 달라지는 문구는 **틀리기 쉽고 조용하다.**

    늘 나오는 문구는 눈에 띄지만, 조건이 맞아야 나오는 문구는 그 조건을 만난
    사람만 본다 — 그리고 그 사람은 대개 뭔가 잘못된 상황에 있다.
    """

    def _js(self, name):
        return _read('aot_flask', 'static', 'js', 'common', name)

    def test_the_stale_line_names_the_real_threshold(self):
        """"최근 몇 분간" 은 거짓이다 — 기준은 `max(300초, 제어주기×3)` 이라
        10분 주기 코디네이터에서는 **30분**이다. 뭉뚱그리면 사용자가 3분 뒤에
        다시 보고 "여전히 멈춰 있다" 고 판단한다. 제어가 살아 있는지를 말하는
        가장 중요한 줄이라 여기서 모호하면 안 된다.
        """
        js = self._js('aot-env-status.js')
        assert 'stale_after_s' in js, '서버가 보낸 실제 기준을 쓰지 않습니다'
        assert 'last few minutes' not in js, '뭉뚱그리는 옛 문구가 남아 있습니다'
        assert "'stale_after_s'" in _read('aot_flask', 'routes_geo_iec.py'), \
            '서버가 기준을 보내지 않습니다'

    def test_every_actuator_kind_has_a_label(self):
        """명부에 없는 종류는 **영어 원문 그대로** 나온다("circulation_fan 30%").
        조용하고, 그 종류를 가진 시설에서만 보인다."""
        block = re.search(
            r'ACTUATOR_DOMAIN = \{(.*?)\}',
            _read('functions', 'utils', 'env_control', 'types.py'), re.S).group(1)
        kinds = set(re.findall(r"'([a-z_0-9]+)':", block))
        labels = set(re.findall(
            r'([a-z_0-9]+):',
            self._js('aot-env-status.js').split('var KIND_LABEL = {', 1)[1]
                .split('};', 1)[0]))
        assert kinds - labels == set(), (
            'KIND_LABEL 에 이름이 없는 종류: ' + str(sorted(kinds - labels)))

    def test_an_unmatched_scale_group_says_where_to_look(self):
        """'사용자 지정' 만 띄우면 막다른 길이다 — 손잡이도 안 켜지고 값도 안
        보이는데, 세부 옵션은 [고급 설정] 안에 숨어 있다."""
        body = self._js('aot-scale-input.js') \
            .split('function renderGroup', 1)[1].split('\n  function ', 1)[0]
        assert 'idx < 0' in body
        assert 'Advanced' in body, '어디를 봐야 하는지 말하지 않습니다'

    def test_the_header_speaks_for_this_coordinator_not_the_facility(self):
        """시설 요약은 코디네이터가 여럿이면 **활성 우선**으로 하나를 고른다.

        그래서 한 시설을 가리키는 코디네이터가 둘이면, **꺼져 있는 쪽의 설정
        창이 켜져 있는 쪽의 상태를 자기 것처럼** 보여 준다 — 2026-08-28 실측:
        비활성 코디네이터가 "현재 9분 전" 을 띄웠다. 설정 창은 시설이 아니라
        **이 코디네이터**를 말해야 한다.
        """
        src = _read('aot_flask', 'routes_geo_iec.py')
        body = src.split('def api_coordinator_overview', 1)[1].split('\n@', 1)[0]
        assert "reported != function_uuid" in body, (
            '시설 대표 코디네이터의 상태를 그대로 내보냅니다')
        assert "'other_coordinator'" in body, (
            '실제로 도는 쪽을 알려 주지 않으면 "왜 꺼져 있나" 에 답이 없습니다')

        js = _read('aot_flask', 'static', 'js', 'common', 'aot-env-status.js')
        assert 'other_coordinator' in js, '화면이 그 사실을 쓰지 않습니다'
