# coding=utf-8
"""카메라 드라이버 인터페이스 — 제조사 중립.

설계: docs/design/vigi-camera-module.md §3.1.

이 패키지(`aot.camera_drivers`)는 `aot.camera.*` 를 import 하지 않는다
(옛 미완성 패키지, 26-11 에 지웠다. 경계 검사: test_camera_drivers_boundary.py).

핵심 계약 — `CamResult` 는 성공을 따로 증명한다. HTTP 200 이나 빈 응답만으로는
`accepted` 가 아니다. 카메라가 `error_code: 0` 으로 받았을 때만 `accepted` 다.
"""
import enum
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, List, Optional


class CamState(str, enum.Enum):
    ACCEPTED = 'accepted'        # 카메라가 error_code 0 으로 받음 ("받았다"이지 "끝났다"가 아니다)
    REFUSED = 'refused'          # 권한·스코프·래치로 거부 — 카메라에 아무것도 보내지 않았다
    FAILED = 'failed'            # 오류코드 또는 네트워크 오류
    UNSUPPORTED = 'unsupported'  # 이 카메라/드라이버가 지원하지 않는 기능
    UNVERIFIED = 'unverified'    # 응답이 비었거나 형식이 틀려 성공을 증명할 수 없음


class ErrorClass(str, enum.Enum):
    """오류 분류. 인증 계열은 래치, 나머지는 래치하지 않는다."""
    NONE = 'none'
    AUTH_FAILED = 'auth_failed'          # 비밀번호/계정 오류 → 래치(failed)
    LOCKED = 'locked'                    # 카메라가 로그인을 잠금 → 래치(locked)
    CLIENT_LIMIT = 'client_limit'        # 동시 클라이언트 초과 → 래치 아님, 백오프
    SESSION_INVALID = 'session_invalid'  # stok 만료/무효 → 성공한 자격으로 1회 재인증
    CERT_CHANGED = 'cert_changed'        # 인증서 지문 변경 → 자격 증명을 보내기 전에 멈춤
    UNSUPPORTED = 'unsupported'
    NETWORK = 'network'                  # 연결·시간 초과 → 백오프(인증 상태 불변)
    DEVICE = 'device'                    # 그 밖의 카메라 오류코드
    PROTOCOL = 'protocol'                # 형식 오류·빈 응답


# 인증 상태 때문에 래치가 걸리는 분류
LATCHING = frozenset({ErrorClass.AUTH_FAILED, ErrorClass.LOCKED})


@dataclass(frozen=True)
class CamResult:
    """드라이버 호출의 결과 값. 비밀(비밀번호·digest response·stok)을 담지 않는다."""
    state: CamState
    error_class: ErrorClass = ErrorClass.NONE
    code: Optional[int] = None          # 카메라 error_code (있으면)
    message: str = ''                   # 사람이 읽는 이유. 비밀 없음
    data: Any = None                    # 성공 시 카메라 result (호출자가 소비)
    interface: str = ''                 # 'openapi' · 'rtsp'

    @property
    def accepted(self) -> bool:
        return self.state is CamState.ACCEPTED

    @classmethod
    def ok(cls, data=None, code=0, interface='openapi'):
        return cls(CamState.ACCEPTED, ErrorClass.NONE, code, '', data, interface)

    @classmethod
    def refused(cls, message, error_class=ErrorClass.NONE, interface='openapi'):
        return cls(CamState.REFUSED, error_class, None, message, None, interface)

    @classmethod
    def failed(cls, message, error_class=ErrorClass.DEVICE, code=None, interface='openapi'):
        return cls(CamState.FAILED, error_class, code, message, None, interface)

    @classmethod
    def unsupported(cls, message='unsupported'):
        return cls(CamState.UNSUPPORTED, ErrorClass.UNSUPPORTED, None, message)

    @classmethod
    def unverified(cls, message, interface='openapi'):
        return cls(CamState.UNVERIFIED, ErrorClass.PROTOCOL, None, message, None, interface)


# ---------------------------------------------------------------------------
# 비밀 비노출 도구
# ---------------------------------------------------------------------------
_HEX64 = re.compile(r'\b[0-9a-fA-F]{64}\b')


def scrub(text, *secrets) -> str:
    """문자열에서 알려진 비밀과 64자리 hex(digest)를 지운다. 로그·예외 직전에 쓴다."""
    out = str(text)
    for s in secrets:
        if s:
            out = out.replace(str(s), '***')
    return _HEX64.sub('***', out)


def short_token(stok) -> str:
    """stok 은 앞 4자만 남긴다(설계 §6.1-6)."""
    return (stok[:4] + '…') if stok else ''


@dataclass(frozen=True)
class StreamProfile:
    """영상 스트림 하나. URL 에 자격 증명을 넣지 않는다."""
    name: str            # 'main' · 'sub' · 'mjpeg'
    url: str             # 자격 증명 제외
    codec: str = ''
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class Credential:
    """자격 증명. repr 에 비밀번호가 나오지 않는다."""
    username: str
    password: str = field(repr=False)

    def __repr__(self):
        return 'Credential(username=%r, password=***)' % (self.username,)


class CameraDriver:
    """제조사 중립 드라이버 인터페이스. 지원 안 하는 기능은 기본 구현이 unsupported 를 돌려준다."""

    vendor: str = ''

    def verify(self, credential: Credential) -> CamResult:
        """연결 확인 — 사용자가 누를 때만 호출된다."""
        return CamResult.unsupported('verify')

    def capabilities(self, refresh: bool = False):
        """Capabilities 를 돌려준다(캐시 우선). 못 얻으면 None."""
        return None

    def device_info(self) -> CamResult:
        return CamResult.unsupported('device_info')

    def stream_profiles(self) -> List[StreamProfile]:
        return []

    def ptz_move(self, vector, speed=None) -> CamResult:
        return CamResult.unsupported('ptz_move')

    def ptz_stop(self) -> CamResult:
        return CamResult.unsupported('ptz_stop')

    def ptz_goto(self, preset) -> CamResult:
        return CamResult.unsupported('ptz_goto')

    def ptz_set_preset(self, preset, name='') -> CamResult:
        return CamResult.unsupported('ptz_set_preset')

    def set_day_night(self, mode) -> CamResult:
        return CamResult.unsupported('set_day_night')

    def manual_alarm(self, start: bool) -> CamResult:
        return CamResult.unsupported('manual_alarm')

    def open_event_stream(self, kinds=None) -> Iterator:
        """CameraEvent | Heartbeat 반복자. P4 에서 구현한다."""
        raise NotImplementedError
