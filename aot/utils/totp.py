# coding=utf-8
"""RFC 6238 TOTP (시간 기반 일회용 비밀번호) — 2단계 인증용.

**왜 라이브러리(pyotp)를 쓰지 않았나**

pyotp 를 넣으려면 requirements.txt 추가 → Docker 이미지 재빌드가 필요하다
(이 저장소의 Docker 이미지에는 virtualenv 도 setuid 래퍼도 없어
`dependencies_module` 자동설치 경로가 동작하지 않는다). TOTP 는 HMAC 위에
얹힌 RFC 6238 표준 계산이고 구현이 30줄 남짓이라, 의존성 추가 대신 표준
라이브러리(hmac/hashlib/struct/base64)로 구현했다.

"직접 만든 인증 코드"에 대한 우려는 **RFC 6238 부록 B의 공식 테스트 벡터**로
해소한다 — `aot/tests/test_totp.py` 가 SHA1/SHA256/SHA512 벡터를 전부 검증한다.
암호 알고리즘을 새로 설계한 게 아니라 표준 명세를 그대로 구현한 것이다.

Google Authenticator, Authy, 1Password 등 표준 TOTP 앱과 호환된다
(기본값: SHA1, 6자리, 30초 — 이 조합만이 모든 앱에서 통용된다).
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

__all__ = ['generate_secret', 'get_totp_token', 'verify_totp',
           'provisioning_uri']

_DIGITS = 6
_PERIOD = 30
# 앞뒤 한 스텝(±30초)까지 허용해 기기 시계 오차를 흡수한다. 더 넓히면 코드
# 유효창이 그만큼 길어져 재사용 공격 표면이 커진다.
_DEFAULT_WINDOW = 1


def generate_secret(length=20):
    """새 TOTP 공유 비밀을 base32 문자열로 생성.

    RFC 4226 은 최소 128비트, 권장 160비트를 요구한다 — 기본 20바이트=160비트.
    """
    return base64.b32encode(secrets.token_bytes(length)).decode('utf-8').rstrip('=')


def _hotp(secret_b32, counter, digits=_DIGITS, digest=hashlib.sha1):
    """RFC 4226 HOTP. TOTP 는 counter 를 시간에서 유도한 HOTP 다."""
    # base32 패딩 복원 — 저장 시 '=' 을 떼어두므로 되돌려야 디코딩된다.
    padding = '=' * (-len(secret_b32) % 8)
    key = base64.b32decode(secret_b32.upper() + padding, casefold=True)

    msg = struct.pack('>Q', counter)
    digest_bytes = hmac.new(key, msg, digest).digest()

    # Dynamic truncation (RFC 4226 §5.3)
    offset = digest_bytes[-1] & 0x0F
    code = struct.unpack('>I', digest_bytes[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def get_totp_token(secret_b32, at_time=None, digits=_DIGITS, period=_PERIOD,
                   digest=hashlib.sha1):
    """현재(또는 지정 시각)의 TOTP 코드 문자열."""
    if at_time is None:
        at_time = time.time()
    counter = int(at_time // period)
    return _hotp(secret_b32, counter, digits=digits, digest=digest)


def verify_totp(secret_b32, token, at_time=None, window=_DEFAULT_WINDOW,
                digits=_DIGITS, period=_PERIOD):
    """사용자가 입력한 코드 검증. 시계 오차 허용은 window 스텝(기본 ±1).

    비교는 hmac.compare_digest 로 상수 시간 수행한다.
    """
    if not secret_b32 or not token:
        return False

    token = str(token).strip().replace(' ', '')
    if not token.isdigit() or len(token) != digits:
        return False

    if at_time is None:
        at_time = time.time()
    counter = int(at_time // period)

    for offset in range(-window, window + 1):
        try:
            candidate = _hotp(secret_b32, counter + offset, digits=digits)
        except Exception:
            return False
        if hmac.compare_digest(candidate, token):
            return True
    return False


def provisioning_uri(secret_b32, account_name, issuer='AoT'):
    """인증 앱에 등록할 otpauth:// URI (QR 코드로 만들거나 직접 입력).

    QR 이미지는 서버에서 만들지 않는다 — 그러려면 qrcode/Pillow 의존성이 필요한데,
    URI 를 그대로 보여주고 클라이언트에서 렌더하거나 수동 입력하면 충분하다.
    """
    label = urllib.parse.quote('{}:{}'.format(issuer, account_name))
    params = urllib.parse.urlencode({
        'secret': secret_b32,
        'issuer': issuer,
        'algorithm': 'SHA1',
        'digits': _DIGITS,
        'period': _PERIOD,
    })
    return 'otpauth://totp/{label}?{params}'.format(label=label, params=params)
