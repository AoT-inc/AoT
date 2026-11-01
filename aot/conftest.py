# coding=utf-8
"""`aot/` 아래 모든 테스트 디렉터리에 걸리는 공용 픽스처.

`aot/tests/conftest.py` 는 `aot/tests` 에만 적용된다. 그런데 테스트는
`aot/functions/utils/env_control/tests` 처럼 다른 곳에도 있고, 같은 pytest
프로세스에서 함께 돌면 `aot/tests` 쪽이 남긴 전역 로깅 상태를 그대로 물려받는다.
그래서 로거 격리는 여기 둔다.

이 파일은 `aot/tests/conftest.py` 보다 **먼저** 로드된다. 그쪽은 `aot.config`
import 전에 환경변수를 잡아야 하므로, 여기서는 `aot` 의 어떤 하위 모듈도 import
하지 않는다.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_aot_logger():
    """`'aot'` 로거의 전역 상태를 테스트마다 되돌린다.

    `aot/aot_daemon.py` 는 import 시점에 `'aot'` 로거에 자기 핸들러를 달고
    **`propagate = False`** 를 건다. 데몬 프로세스에서는 옳다 — 그 모듈을
    import 하는 것은 데몬 진입점뿐이다. 하지만 테스트가 데몬 함수를
    monkeypatch 하려고 import 하는 순간 그 설정이 프로세스에 남고, 그 뒤에
    도는 테스트에서는 `aot.*` 의 로그가 root 까지 올라오지 않아 pytest 의
    `caplog` 이 아무것도 못 받는다.

    실제로 겪었다: `test_safety_service` 의 "실패를 조용히 삼키지 않는다"
    검사가 **전체 스위트에서만** 실패하고 그 파일만 돌리면 통과했다. 로그는
    화면에 멀쩡히 찍히는데 `caplog.records` 만 비어 있어 원인을 찾기 어려웠다.

    `aot/tests/conftest.py` 에만 있을 때는 그 디렉터리 밖 테스트에 걸리지 않았다.
    `test_settings_matter_routes.py::TestTemplateRendersInRealApp`(PR #88)의
    `setUpClass` 가 `create_app()` 으로 `propagate=False` 를 남기면, 함께 돌던
    `env_control/tests/test_greybox_fit_bounds.py::TestClampIsLoud` 가 caplog 에서
    "범위" 경고를 못 받아 실패했다 — 혼자 돌리면 통과했다.

    핸들러 목록까지 되돌리는 이유는 남은 핸들러가 테스트의 임시 로그 파일을
    계속 붙들기 때문이다.
    """
    import logging
    aot_logger = logging.getLogger('aot')
    saved = (aot_logger.propagate, list(aot_logger.handlers), aot_logger.level)
    # **되돌리는 것만으로는 부족하다.** 이 픽스처는 함수 스코프라 `setUpClass`
    # 나 세션 픽스처보다 **나중에** 돈다. 그래서 그쪽에서 오염되면(예:
    # `test_mcp_rate_limit` 의 `setUpClass` 가 부르는 `create_app()`) 이미
    # 오염된 상태를 저장했다가 그대로 되돌려 놓아, 그 뒤 스위트 전체가
    # `propagate=False` 로 돈다 — 2026-08-20 까지 `test_safety_service` 의
    # "실패를 조용히 삼키지 않는다" 검사가 **전체 스위트에서만** 실패한 원인이다.
    #
    # 핸들러는 건드리지 않는다(그쪽은 되돌리기만 한다 — 임시 로그 파일을 붙드는
    # 문제 때문이다). 필요한 것은 기록이 root 까지 올라오는 것뿐이고, 그래야
    # caplog 이 받는다. 데몬 핸들러도 그대로 받으므로 잃는 것이 없다.
    aot_logger.propagate = True
    yield
    aot_logger.propagate, aot_logger.handlers[:], aot_logger.level = (
        saved[0], saved[1], saved[2])
