# coding=utf-8
"""VIGI Open API 오류코드 → 분류. 설계 §6.1-8, §10.2.

V 항목(실카메라 확인)이 끝나기 전까지 모르는 값은 안전한 쪽으로 처리한다:
인증 단계의 모르는 응답은 래치(failed)로 취급한다. 확정할 값은 이 파일 한 곳에 모은다.
"""
import random

from aot.camera_drivers.driver import ErrorClass

# [문서] V1.1
ERR_AUTH_FAILED = -10020    # 인증 실패/비밀번호 오류 (doAuth 1단계 응답에도 챌린지와 함께 온다)
ERR_CLIENT_LIMIT = -10021   # 클라이언트 수 초과 — 인증 실패가 아니다
ERR_LOCKED = -10022         # 재시도 횟수 초과로 잠김

# [미확인] 세션(stok) 무효 코드. TP-Link 계열의 "invalid stok" 로 추정하는 값이다.
# 실카메라 V5 에서 확정한다. 틀려도 안전하다: 모르는 코드는 DEVICE 로 분류되어 재인증하지 않는다.
SESSION_INVALID_CODES = frozenset({-40401})


def classify(code) -> ErrorClass:
    """error_code → ErrorClass. 0 이면 NONE."""
    if code == 0:
        return ErrorClass.NONE
    if code == ERR_AUTH_FAILED:
        return ErrorClass.AUTH_FAILED
    if code == ERR_LOCKED:
        return ErrorClass.LOCKED
    if code == ERR_CLIENT_LIMIT:
        return ErrorClass.CLIENT_LIMIT
    if code in SESSION_INVALID_CODES:
        return ErrorClass.SESSION_INVALID
    return ErrorClass.DEVICE


class Backoff:
    """재연결 간격 수열(설계 §6.2). 인증 실패에는 쓰지 않는다 — 네트워크·-10021 전용.

    kind='network': 5→10→…→300초, kind='client_limit': 60→120→…→900초. 지터 ±20%.
    rng 를 주입하면 결정적으로 시험할 수 있다."""
    _PARAMS = {'network': (5, 300), 'client_limit': (60, 900)}

    def __init__(self, kind, rng=None):
        self.base, self.cap = self._PARAMS[kind]
        self.rng = rng or random.Random()
        self.attempt = 0

    def nominal(self, attempt=None):
        n = self.attempt if attempt is None else attempt
        return min(self.base * (2 ** n), self.cap)

    def next_delay(self):
        d = self.nominal()
        self.attempt += 1
        return d * (1 + self.rng.uniform(-0.2, 0.2))

    def reset(self):
        self.attempt = 0
