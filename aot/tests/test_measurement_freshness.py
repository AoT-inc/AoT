# coding=utf-8
"""측정값 신선도 판정의 정본과 그 소비처 (p6_55, 2026-08-24).

## 무엇을 고정하는가

"이 값이 아직 쓸 만한가" 를 묻는 자리가 다섯이다 — 시설 센서 · 대지 요약 ·
`/data_batch` · AI 날씨 도구 · 지도 위젯. 다섯이 각자 규칙을 들면 갈라지고,
갈라지면 같은 센서가 화면마다 다른 상태로 보인다. 그래서 판정은
`aot.utils.measurement_freshness` 하나이고, 여기서는 **그 규칙**과 **다섯이
실제로 거기를 지나는가**를 함께 본다.

## 왜 소스 검사가 붙어 있나

규칙 함수만 테스트하면 "소비처가 그 함수를 안 부르는" 실패를 못 잡는다. 이
계열이 실제로 났다 — `facility_sensors` 는 호출자가 `max_age` 를 주면 장치
주기를 아예 조회하지 않는 단락(`periods = {} if max_age is not None else ...`)
을 갖고 있었고, 제어는 **항상** 그 인자를 들고 오므로 제어 경로에서 주기 기반
판정이 통째로 죽어 있었다. 함수는 멀쩡했고 테스트도 통과했다.
"""
import ast
import pathlib

import pytest

from aot.utils.measurement_freshness import (
    UNKNOWN, effective_max_age, lookup, widen_window,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestEffectiveMaxAge:
    """판정 — 장치값이 가장 먼저 이긴다."""

    def test_장치값이_호출자_요청을_이긴다(self):
        """이 순서가 뒤집히면 컬럼을 만든 의미가 없다.

        제어(env_coordinator)는 **항상** `requested` 를 들고 온다. 요청을 앞에
        두면 장치별 설정이 제어 경로에서 통째로 무시되고, 화면에만 있는 설정이
        된다 — 즉 사용자는 값을 적었는데 아무 일도 안 일어난다.
        """
        assert effective_max_age(120, 60.0, 1800) == 1800

    def test_장치값이_없으면_호출자_요청(self):
        assert effective_max_age(120, 60.0, None) == 120

    def test_둘_다_없으면_주기_파생(self):
        assert effective_max_age(None, 600.0, None, floor=300, factor=2.0) == 1200

    def test_주기가_짧으면_하한이_이긴다(self):
        """15초 장치를 30초로 판정하면 지터 몇 초에 매번 깜빡인다."""
        assert effective_max_age(None, 15.0, None, floor=300, factor=2.0) == 300

    def test_아무것도_모르면_하한(self):
        assert effective_max_age(None, None, None, floor=300) == 300

    def test_0_은_미설정으로_읽는다(self):
        """`max_age_s=0` 은 '즉시 만료' 가 아니라 '안 정했다' 로 다룬다.

        0 을 유효한 상한으로 받으면 실수로 0 을 넣은 장치의 값이 **영원히**
        오래된 것이 되어 화면에서 사라진다. 저장 핸들러도 같은 판단으로
        0 을 NULL 로 눕힌다.
        """
        assert effective_max_age(120, 60.0, 0) == 120

    def test_망가진_값은_다음_근거로_넘어간다(self):
        assert effective_max_age(120, 60.0, 'abc') == 120


class TestWidenWindow:
    """조회 창 — 넓히기만 한다."""

    def test_장치값이_요청창보다_짧으면_요청창이_이긴다(self):
        """**여기서 좁히면 그래프가 통째로 빈다.**

        판정과 정반대다. 장치가 말하는 것은 "이만큼은 봐야 값이 있다" 이지
        "이보다 멀리 보지 말라" 가 아니다. 30일을 요청한 사용자가 장치 수명
        만큼만 보게 되면 그것은 데이터 손실로 읽힌다.
        """
        assert widen_window(30 * 86400, 60.0, 1800, cap=30 * 86400) == 30 * 86400

    def test_장치값이_길면_그만큼_넓힌다(self):
        assert widen_window(3600, 60.0, 7200, factor=3.0) == 7200

    def test_주기_파생과_장치값_중_큰_쪽(self):
        assert widen_window(3600, 3000.0, 5000, factor=3.0) == 9000.0

    def test_상한을_넘지_않는다(self):
        assert widen_window(3600, 60.0, 99 * 86400, cap=30 * 86400) == 30 * 86400

    def test_0_은_무제한이라_그대로_둔다(self):
        assert widen_window('0', 60.0, 1800) == '0'

    def test_숫자가_아니면_그대로_돌려준다(self):
        assert widen_window(None, 60.0, 1800) is None


class TestLookup:
    def test_없는_장치는_미지_튜플(self):
        assert lookup({}, 'x') == UNKNOWN
        assert lookup({'a': (60.0, 1800)}, 'a') == (60.0, 1800)


class TestEveryConsumerGoesThroughTheOneRule:
    """다섯 소비처가 정본을 지나는가 — 소스로 고정한다.

    함수가 맞게 동작하는 것과 소비처가 그 함수를 부르는 것은 다르다.
    """

    CONSUMERS = {
        'aot_flask/geo/facility_sensors.py':   'measurement_freshness',
        'aot_flask/geo/site_summary.py':       'effective_max_age',
        'aot_flask/routes_general.py':         'widen_window',
        'ai/services/aot_data_tool_service.py': 'widen_window',
        'aot_flask/utils/utils_geo.py':        'freshness_by_device',
    }

    def test_소비처가_정본을_부른다(self):
        missing = [f for f, sym in self.CONSUMERS.items()
                   if sym not in (ROOT / f).read_text(encoding='utf-8')]
        assert not missing, (
            f'이 파일들이 신선도 정본을 지나지 않는다: {missing}. '
            f'규칙을 다시 쓰지 말고 aot.utils.measurement_freshness 를 쓸 것.')

    def test_장치_수명을_읽는_곳은_정본_하나다(self):
        """`Input.max_age_s` 를 실제로 조회하는 두 번째 자리를 만들지 말 것.

        두 벌이 되면 갈라지고, 갈라지면 **느슨한 쪽이 실질 판정**이 된다.
        폼·저장 핸들러·모델은 그 컬럼을 다루는 것이 일이라 예외다.

        **문자열이 아니라 AST 로 본다.** 주석과 독스트링은 그 이름을 설명하려고
        당연히 적으므로, 문자열로 찾으면 설명을 금지하게 된다.
        """
        allowed = {
            'utils/measurement_freshness.py',      # 정본
            'databases/models/input.py',           # 선언
            'aot_flask/forms/forms_input.py',      # 입력
            'aot_flask/utils/utils_input.py',      # 저장
        }
        offenders = []
        for path in ROOT.rglob('*.py'):
            rel = path.relative_to(ROOT).as_posix()
            if rel in allowed or rel.startswith('tests/') or '/tests/' in rel:
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute) and node.attr == 'max_age_s'
                        and isinstance(node.value, ast.Name)
                        and node.value.id == 'Input'):
                    offenders.append(f'{rel}:{node.lineno}')
        assert not offenders, (
            f'`Input.max_age_s` 를 직접 조회하는 곳: {offenders}. '
            f'freshness_by_device() 를 쓸 것.')


class TestClientSidePriority:
    """지도 위젯 JS 도 같은 순서인가 — 서버와 다르면 화면이 갈린다."""

    WIDGET = ROOT / 'aot_flask/static/js/widgets/AoT_map/aot-map-widget-vector.js'

    def test_장치값을_주기보다_먼저_본다(self):
        src = self.WIDGET.read_text(encoding='utf-8')
        assert 'max_age_s' in src, '위젯이 장치 명시 수명을 읽지 않는다'
        i_dec = src.index('c.max_age_s')
        i_per = src.index('c.sample_period')
        assert i_dec < i_per, (
            '장치값을 주기보다 **먼저** 봐야 한다 — 순서가 뒤집히면 '
            '장주기 노드가 정상 동작 중에도 흐리게 그려진다.')

    def test_서버가_그_필드를_실제로_내보낸다(self):
        """위젯이 읽는 이름과 서버가 쓰는 이름이 같아야 한다.

        어긋나면 `undefined` 라 위젯은 조용히 주기 배수로 되돌아간다 —
        에러가 없어서 설정이 안 먹는다는 사실이 어디에도 안 드러난다.
        """
        src = (ROOT / 'aot_flask/utils/utils_geo.py').read_text(encoding='utf-8')
        assert "'max_age_s':" in src
        labels = (ROOT / 'aot_flask/static/js/widgets/AoT_map/'
                  'aot-map-sensor-labels.js').read_text(encoding='utf-8')
        assert 'max_age_s' in labels, (
            '라벨 모듈이 채널 dict 를 다시 만들면서 이 키를 떨어뜨리면 '
            '위젯까지 닿지 않는다.')

    def test_번들이_소스와_같다(self):
        """번들을 안 고치면 배포된 앱은 계속 옛 판정을 쓴다."""
        bundle = ROOT / 'aot_flask/static/js/dist/aot-map-widget.bundle.js'
        if not bundle.exists():
            pytest.skip('번들 미생성 — check_js_bundles.py --rebuild 가 담당')
        assert 'max_age_s' in bundle.read_text(encoding='utf-8')


class TestPriorityIsNotSilentlyReversed:
    """우선순위를 뒤집으면 여기서 깨진다 — 실측으로 확인한 조합."""

    @pytest.mark.parametrize('requested,period,declared,expected', [
        (120, 60.0, 1800, 1800),     # 제어 + 장주기 노드 → 노드가 이긴다
        (120, 60.0, None, 120),      # 제어 + 미설정      → 종전대로
        (None, 60.0, 1800, 1800),    # 표시 + 장주기 노드
        (None, 60.0, None, 300),     # 표시 + 미설정      → 종전대로(하한)
    ])
    def test_네_조합(self, requested, period, declared, expected):
        assert effective_max_age(requested, period, declared,
                                 floor=300, factor=2.0) == expected


def test_소스에_옛_단락이_되살아나지_않았다():
    """`periods = {} if max_age is not None else ...` — 이것이 원래 결함이다.

    이 한 줄 때문에 제어 경로에서 장치별 판정이 통째로 죽어 있었다. 형태가
    조금 달라도 같은 뜻이면 같은 결함이므로, AST 로 '조건부로 조회를
    건너뛰는' 모양 자체를 본다.
    """
    src = (ROOT / 'aot_flask/geo/facility_sensors.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.IfExp):
            continue
        body = node.value.body
        if isinstance(body, ast.Dict) and not body.keys:
            pytest.fail(
                f'{node.lineno}행: 조건에 따라 장치 신선도 조회를 건너뛴다. '
                f'그 단락이 제어 경로에서 장치별 설정을 통째로 무시하게 만든 '
                f'원래 결함이다.')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
