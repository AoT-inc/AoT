# coding=utf-8
"""서버 비밀값 연동: 지문 키와 비밀번호 봉인. 설계 §5.2.

지문 키는 Flask secret key 에서 HKDF 로 파생한다(비밀번호 봉인과 용도 문자열을 달리한다).
Flask secret key 가 바뀌면 봉인된 비밀번호는 열리지 않고(= 다시 입력 요청) 지문도 달라진다.
"""
import hashlib
import hmac

_INFO = b'aot-camera-credential-fp-v1'
_key = None


def fp_key() -> bytes:
    global _key
    if _key is None:
        from aot.config import ProdConfig
        secret = ProdConfig.SECRET_KEY
        if isinstance(secret, str):
            secret = secret.encode()
        # HKDF-extract+expand 한 블록(32바이트)과 같은 단순 구성: HMAC(HMAC(0,secret), info||1)
        prk = hmac.new(b'\x00' * 32, secret, hashlib.sha256).digest()
        _key = hmac.new(prk, _INFO + b'\x01', hashlib.sha256).digest()
    return _key


def seal_password(password):
    from aot.utils.crypto import seal_secret
    return seal_secret(password) if password else None


def open_password(sealed):
    """(password|None, state). state 는 crypto.SEALED_* — 열 수 없으면 None."""
    from aot.utils.crypto import open_sealed
    return open_sealed(sealed)
