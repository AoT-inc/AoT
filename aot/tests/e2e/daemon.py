# coding=utf-8
"""L3 가 쓰는 데몬 제어.

데몬은 `--profile control` 뒤에 있어 평소에는 뜨지 않는다(L0~L2 는 데몬 없이
판정된다). L3 만 이것을 쓴다.
"""
import os
import subprocess
import time

COMPOSE_FILE = os.environ.get(
    'AOT_E2E_COMPOSE', 'docker/docker-compose.e2e.yml')
SERVICE = 'aot_daemon'


def _compose(*args, timeout=180):
    return subprocess.run(
        ['docker', 'compose', '-f', COMPOSE_FILE, *args],
        capture_output=True, text=True, timeout=timeout)


def is_running():
    try:
        out = _compose('ps', '--status', 'running', '--format', '{{.Service}}',
                       timeout=30)
    except Exception:                        # noqa: BLE001
        return False
    return SERVICE in out.stdout


def start(is_ready, wait_s=120):
    """데몬을 올리고, **실제로 응답할 때까지** 기다린다.

    `is_ready` 는 "지금 데몬이 명령을 받는가" 를 참/거짓으로 답하는 함수다
    (보통 앱의 출력 상태 조회를 한 번 해 본다).
    """
    _compose('--profile', 'control', 'up', '-d', SERVICE)
    return wait_until_ready(is_ready, wait_s)


def stop():
    """데몬을 멈춘다. 중단 절차(출력 shutdown state)를 기다려 준다."""
    _compose('stop', '-t', '30', SERVICE)


def wait_until_ready(is_ready, wait_s=120):
    """데몬이 명령을 받을 수 있을 때까지 기다린다.

    **로그로 판단하지 않는다.** 처음엔 `logs` 에서 "AoT daemon started" 를
    찾았는데, 컨테이너를 멈췄다 켜면 로그가 누적되므로 **이전 실행의 그 줄**을
    보고 곧바로 준비됐다고 판단했다. 그래서 아직 포트도 안 연 데몬에 제어를
    보내고 "Connection refused" 를 받았다(2026-09-18 실측).

    컨테이너가 'running' 인 것, 로그가 'started' 라고 말하는 것, 그리고 앱이
    실제로 데몬과 말이 되는 것은 셋 다 다른 사건이다. 마지막 것만 본다.
    """
    deadline = time.time() + wait_s
    while time.time() < deadline:
        try:
            if is_ready():
                time.sleep(1.0)
                return True
        except Exception:                    # noqa: BLE001 — 기동 중 오류는 정상
            pass
        time.sleep(2)
    return False


def restart_app(is_up, wait_s=180):
    """웹 앱 컨테이너를 다시 띄우고, **응답할 때까지** 기다린다.

    웹 프로세스 안에서 도는 것(타이머 위젯의 작업 스레드 등)이 재시작을 어떻게
    넘기는지 보는 검사용이다. 앱이 떠 있는지도 응답으로만 판단한다.
    """
    _compose('restart', 'aot-app')
    return wait_until_ready(is_up, wait_s)
