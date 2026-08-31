# coding=utf-8
"""시퀀스를 끄면 **정말로 꺼져야** 하고, 못 껐으면 그렇다고 말해야 한다.

운영 농장 사고(aot-004): 시퀀스를 비활성화했는데 다음 날 오전에 밸브가 열렸다.
끄는 라우트가 DB 플래그만 바꾸고 `refresh_daemon_trigger_settings()` 를 불렀는데,
그 호출은 데몬 쪽에서 예외를 통째로 삼키고(aot_daemon.refresh_daemon_trigger_settings)
라우트는 반환값을 보지도 않은 채 무조건 success 를 돌려줬다. RPC 가 실패하면
DB 는 '비활성'인데 돌던 컨트롤러는 is_activated=True 그대로라, 화면에는 꺼진
것으로 보이면서 실제 밸브는 계속 동작했다.

여기서 지키는 계약:
  1. 끄기는 컨트롤러를 **실제로 정지**시키는 호출을 쓴다(설정 새로고침이 아니라).
  2. 끝난 뒤 **실제 상태를 되물어** 의도대로 됐는지 확인한다.
  3. 안 됐거나 확인할 수 없으면 **성공이라고 말하지 않는다**.
"""
import inspect

import pytest


def _code_only(src: str) -> str:
    """주석을 걷어낸 실제 코드만. 주석에 적힌 설명(옛 동작을 서술한 문장)이
    검사에 걸리면 안 된다."""
    out = []
    for line in src.splitlines():
        stripped = line.split('#', 1)[0]
        if stripped.strip():
            out.append(stripped)
    return '\n'.join(out)


@pytest.fixture
def route_src():
    from aot.aot_flask import routes_function
    return _code_only(inspect.getsource(routes_function.sequence_activate_toggle))


@pytest.fixture
def widget_src():
    from aot.widgets import widget_trigger_sequence
    return _code_only(
        inspect.getsource(widget_trigger_sequence.sequence_func_activate_toggle))


class TestFunctionPageToggle:

    def test_컨트롤러를_실제로_정지시킨다(self, route_src):
        assert 'controller_deactivate' in route_src, \
            "설정 새로고침만으로는 돌고 있는 컨트롤러가 멈추지 않는다"
        assert 'controller_activate' in route_src

    def test_설정_새로고침에_의존하지_않는다(self, route_src):
        assert 'refresh_daemon_trigger_settings' not in route_src, \
            "예외를 삼키는 호출에 활성 토글을 맡기면 안 된다"

    def test_데몬_실제_상태를_되묻는다(self, route_src):
        assert 'controller_is_active' in route_src, \
            "반환 코드만 보면 '안 돌고 있다'(정상)와 'RPC 실패'를 구분할 수 없다"

    def test_반영_실패를_성공으로_보고하지_않는다(self, route_src):
        assert '502' in route_src, "데몬에 반영되지 않았을 때 오류를 돌려주지 않는다"
        # 성공 반환이 검증 뒤에 오는지 — 검증 전에 성공을 돌려주면 의미가 없다
        i_check = route_src.index('controller_is_active')
        i_ok = route_src.index("'status': 'success'")
        assert i_check < i_ok, "상태 확인보다 먼저 성공을 반환한다"


class TestWidgetToggle:
    """위젯 토글도 같은 계약을 지켜야 한다 — 끄는 화면이 두 곳이다."""

    def test_데몬_실제_상태를_되묻는다(self, widget_src):
        assert 'controller_is_active' in widget_src

    def test_반영_실패를_성공으로_보고하지_않는다(self, widget_src):
        assert '502' in widget_src
        i_check = widget_src.index('controller_is_active')
        i_ok = widget_src.index("'status': 'success'")
        assert i_check < i_ok
